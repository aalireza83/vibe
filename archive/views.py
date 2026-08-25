import csv
import json
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Q, Subquery
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from .models import Bookmark, Message, MessageEdit, MessageType, TelegramChat


def _page_range(current, total, delta=2):
    """Return page numbers with None where gaps should appear."""
    pages = set()
    pages.update(range(1, min(3, total + 1)))
    pages.update(range(max(1, total - 1), total + 1))
    pages.update(range(max(1, current - delta), min(total + 1, current + delta + 1)))
    result = []
    prev = None
    for p in sorted(pages):
        if prev is not None and p - prev > 1:
            result.append(None)
        result.append(p)
        prev = p
    return result


@login_required
def chats(request):
    latest_msg_date = (
        Message.objects.filter(chat=OuterRef("pk"))
        .order_by("-date")
        .values("date")[:1]
    )
    latest_msg_text = (
        Message.objects.filter(chat=OuterRef("pk"))
        .order_by("-date")
        .values("text")[:1]
    )
    latest_msg_type = (
        Message.objects.filter(chat=OuterRef("pk"))
        .order_by("-date")
        .values("message_type")[:1]
    )

    chat_list = (
        TelegramChat.objects.annotate(
            message_count=Count("messages"),
            last_date=Subquery(latest_msg_date),
            last_text=Subquery(latest_msg_text),
            last_type=Subquery(latest_msg_type),
        )
        .filter(message_count__gt=0)
        .order_by("-last_date")
    )

    return render(request, "archive/chats.html", {"chat_list": chat_list})


@login_required
def chat_detail(request, chat_id):
    tg_chat = get_object_or_404(TelegramChat, pk=chat_id)

    messages_qs = (
        tg_chat.messages.select_related("sender", "bookmark")
        .prefetch_related("edits")
        .order_by("-date")
    )

    msg_type = request.GET.get("type", "")
    show_deleted = request.GET.get("deleted", "")
    show_edited = request.GET.get("edited", "")
    show_bookmarked = request.GET.get("bookmarked", "")

    if msg_type:
        messages_qs = messages_qs.filter(message_type=msg_type)
    if show_deleted:
        messages_qs = messages_qs.filter(is_deleted=True)
    if show_edited:
        messages_qs = messages_qs.filter(edited_at__isnull=False)
    if show_bookmarked:
        messages_qs = messages_qs.filter(bookmark__isnull=False)

    filter_params = ""
    if msg_type:
        filter_params += f"&type={msg_type}"
    if show_deleted:
        filter_params += "&deleted=1"
    if show_edited:
        filter_params += "&edited=1"
    if show_bookmarked:
        filter_params += "&bookmarked=1"

    paginator = Paginator(messages_qs, 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    has_filters = bool(msg_type or show_deleted or show_edited or show_bookmarked)

    reply_ids = [m.reply_to_message_id for m in page_obj if m.reply_to_message_id]
    replied_messages = {
        m.message_id: m
        for m in Message.objects.filter(
            chat=tg_chat, message_id__in=reply_ids
        ).select_related("sender")
    } if reply_ids else {}

    return render(request, "archive/chat.html", {
        "tg_chat": tg_chat,
        "page_obj": page_obj,
        "page_range": _page_range(page_obj.number, paginator.num_pages),
        "msg_type": msg_type,
        "show_deleted": show_deleted,
        "show_edited": show_edited,
        "show_bookmarked": show_bookmarked,
        "filter_params": filter_params,
        "has_filters": has_filters,
        "message_types": MessageType.choices,
        "replied_messages": replied_messages,
    })


@login_required
def search(request):
    query = request.GET.get("q", "").strip()
    page_obj = None
    chat_filter = request.GET.get("chat", "")

    if query:
        search_query = SearchQuery(query, config=settings.SEARCH_CONFIG)
        messages_qs = (
            Message.objects.filter(search_vector=search_query)
            .select_related("chat", "sender")
            .annotate(rank=SearchRank("search_vector", search_query))
            .order_by("-rank", "-date")
        )

        if chat_filter:
            messages_qs = messages_qs.filter(chat_id=chat_filter)

        paginator = Paginator(messages_qs, 30)
        page_obj = paginator.get_page(request.GET.get("page", 1))

    all_chats = TelegramChat.objects.order_by("title")

    return render(request, "archive/search.html", {
        "query": query,
        "page_obj": page_obj,
        "all_chats": all_chats,
        "chat_filter": chat_filter,
    })


@login_required
def bookmarks(request):
    bookmark_list = (
        Bookmark.objects.select_related("message__chat", "message__sender")
        .prefetch_related("message__edits")
        .order_by("-created_at")
    )
    paginator = Paginator(bookmark_list, 50)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    return render(request, "archive/bookmarks.html", {
        "page_obj": page_obj,
        "page_range": _page_range(page_obj.number, paginator.num_pages),
    })


@login_required
def message_changes(request):
    display = request.GET.get("display", "timeline")
    if display not in ("timeline", "chat"):
        display = "timeline"

    event_type = request.GET.get("event", "all")
    if event_type not in ("all", "deleted", "edited"):
        event_type = "all"

    chat_id = request.GET.get("chat", "")
    affected_chats = (
        TelegramChat.objects.filter(
            Q(messages__is_deleted=True) | Q(messages__edits__isnull=False)
        )
        .distinct()
        .order_by("title", "chat_id")
    )

    selected_chat = None
    replied_messages = {}
    if display == "chat":
        messages_qs = Message.objects.none()
        if chat_id:
            selected_chat = get_object_or_404(affected_chats, pk=chat_id)
            messages_qs = (
                selected_chat.messages.select_related("sender", "bookmark")
                .prefetch_related("edits")
            )
            if event_type == "deleted":
                messages_qs = messages_qs.filter(is_deleted=True)
            elif event_type == "edited":
                messages_qs = messages_qs.filter(edits__isnull=False)
            else:
                messages_qs = messages_qs.filter(
                    Q(is_deleted=True) | Q(edits__isnull=False)
                )
            messages_qs = messages_qs.distinct().order_by("-date")

        paginator = Paginator(messages_qs, 50)
        page_obj = paginator.get_page(request.GET.get("page", 1))
        reply_ids = [m.reply_to_message_id for m in page_obj if m.reply_to_message_id]
        if selected_chat and reply_ids:
            replied_messages = {
                m.message_id: m
                for m in Message.objects.filter(
                    chat=selected_chat, message_id__in=reply_ids
                ).select_related("sender")
            }
    else:
        events = []
        if event_type in ("all", "deleted"):
            deleted_messages = (
                Message.objects.filter(is_deleted=True, deleted_at__isnull=False)
                .select_related("chat", "sender", "bookmark")
                .prefetch_related("edits")
            )
            events.extend({
                "kind": "deleted",
                "occurred_at": message.deleted_at,
                "message": message,
            } for message in deleted_messages)

        if event_type in ("all", "edited"):
            edits = (
                MessageEdit.objects.select_related(
                    "message__chat", "message__sender", "message__bookmark"
                )
                .prefetch_related("message__edits")
            )
            events.extend({
                "kind": "edited",
                "occurred_at": edit.edited_at,
                "message": edit.message,
                "edit": edit,
            } for edit in edits)

        events.sort(key=lambda event: event["occurred_at"], reverse=True)
        paginator = Paginator(events, 50)
        page_obj = paginator.get_page(request.GET.get("page", 1))

    query_params = {"display": display, "event": event_type}
    if chat_id:
        query_params["chat"] = chat_id

    return render(request, "archive/message_changes.html", {
        "display": display,
        "event_type": event_type,
        "affected_chats": affected_chats,
        "selected_chat": selected_chat,
        "chat_id": chat_id,
        "page_obj": page_obj,
        "page_range": _page_range(page_obj.number, paginator.num_pages),
        "pagination_query": urlencode(query_params),
        "replied_messages": replied_messages,
    })


@login_required
def export_chat(request, chat_id):
    tg_chat = get_object_or_404(TelegramChat, pk=chat_id)
    fmt = request.GET.get("format", "json")

    messages = list(
        tg_chat.messages.select_related("sender")
        .order_by("date")
        .values(
            "message_id", "date", "message_type", "text",
            "is_deleted", "deleted_at", "edited_at",
            "is_forwarded", "forward_from_name",
            "media_path", "transcription",
            "sender__username", "sender__first_name", "sender__last_name",
        )
    )

    filename = tg_chat.display_name.replace("/", "_")

    if fmt == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
        response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        writer = csv.writer(response)
        writer.writerow([
            "id", "date", "sender", "type", "text",
            "deleted", "deleted_at", "edited_at",
            "forwarded", "forward_from", "media_path", "transcription",
        ])
        for m in messages:
            sender = " ".join(filter(None, [
                m["sender__first_name"], m["sender__last_name"]
            ])) or m["sender__username"] or ""
            writer.writerow([
                m["message_id"],
                m["date"].strftime("%Y-%m-%d %H:%M:%S") if m["date"] else "",
                sender,
                m["message_type"],
                m["text"] or "",
                "1" if m["is_deleted"] else "0",
                m["deleted_at"].strftime("%Y-%m-%d %H:%M:%S") if m["deleted_at"] else "",
                m["edited_at"].strftime("%Y-%m-%d %H:%M:%S") if m["edited_at"] else "",
                "1" if m["is_forwarded"] else "0",
                m["forward_from_name"] or "",
                m["media_path"] or "",
                m["transcription"] or "",
            ])
        return response

    # JSON
    for m in messages:
        m["date"] = m["date"].isoformat() if m["date"] else None
        m["deleted_at"] = m["deleted_at"].isoformat() if m["deleted_at"] else None
        m["edited_at"] = m["edited_at"].isoformat() if m["edited_at"] else None
    response = HttpResponse(
        json.dumps(messages, ensure_ascii=False, indent=2),
        content_type="application/json; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.json"'
    return response


@login_required
@require_POST
def api_toggle_bookmark(request, message_pk):
    msg = get_object_or_404(Message, pk=message_pk)
    bookmark, created = Bookmark.objects.get_or_create(message=msg)
    if not created:
        bookmark.delete()
        return JsonResponse({"bookmarked": False})
    return JsonResponse({"bookmarked": True})


@login_required
def chat_media(request, chat_id):
    tg_chat = get_object_or_404(TelegramChat, pk=chat_id)
    media_type = request.GET.get("type", "")

    qs = (
        tg_chat.messages
        .filter(message_type__in=["photo", "video", "gif"], media_path__isnull=False)
        .order_by("-date")
    )
    if media_type in ("photo", "video", "gif"):
        qs = qs.filter(message_type=media_type)

    paginator = Paginator(qs, 60)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(request, "archive/chat_media.html", {
        "tg_chat": tg_chat,
        "page_obj": page_obj,
        "page_range": _page_range(page_obj.number, paginator.num_pages),
        "media_type": media_type,
    })


@login_required
def api_poll_chat(request, chat_id):
    tg_chat = get_object_or_404(TelegramChat, pk=chat_id)
    after_id = request.GET.get("after", 0)

    new_messages = (
        tg_chat.messages.select_related("sender", "bookmark")
        .prefetch_related("edits")
        .filter(message_id__gt=after_id)
        .order_by("-date")
    )

    if not new_messages.exists():
        return JsonResponse({"html": "", "latest_id": after_id})

    reply_ids = [m.reply_to_message_id for m in new_messages if m.reply_to_message_id]
    replied_messages = {
        m.message_id: m
        for m in Message.objects.filter(
            chat=tg_chat, message_id__in=reply_ids
        ).select_related("sender")
    } if reply_ids else {}

    html = "".join(
        render_to_string("archive/_message.html", {"msg": msg, "replied_messages": replied_messages})
        for msg in new_messages
    )
    latest_id = new_messages.order_by("-message_id").values_list("message_id", flat=True).first()

    return JsonResponse({"html": html, "latest_id": latest_id})


@login_required
def api_chats_list(request):
    latest_msg_date = (
        Message.objects.filter(chat=OuterRef("pk")).order_by("-date").values("date")[:1]
    )
    latest_msg_text = (
        Message.objects.filter(chat=OuterRef("pk")).order_by("-date").values("text")[:1]
    )
    latest_msg_type = (
        Message.objects.filter(chat=OuterRef("pk")).order_by("-date").values("message_type")[:1]
    )

    chat_list = (
        TelegramChat.objects.annotate(
            message_count=Count("messages"),
            last_date=Subquery(latest_msg_date),
            last_text=Subquery(latest_msg_text),
            last_type=Subquery(latest_msg_type),
        )
        .filter(message_count__gt=0)
        .order_by("-last_date")
    )

    html = render_to_string("archive/_chats_list.html", {"chat_list": chat_list})
    return JsonResponse({"html": html, "count": chat_list.count()})
