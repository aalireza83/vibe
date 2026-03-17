from django.contrib.auth.decorators import login_required
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Subquery
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string

from .models import Message, TelegramChat


@login_required
def chats(request):
    # Последнее сообщение и счётчик для каждого чата
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
        tg_chat.messages.select_related("sender")
        .prefetch_related("edits")
        .order_by("-date")
    )

    paginator = Paginator(messages_qs, 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(request, "archive/chat.html", {
        "tg_chat": tg_chat,
        "page_obj": page_obj,
    })


@login_required
def search(request):
    query = request.GET.get("q", "").strip()
    page_obj = None
    chat_filter = request.GET.get("chat", "")

    if query:
        search_query = SearchQuery(query, config="russian")
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
def api_poll_chat(request, chat_id):
    tg_chat = get_object_or_404(TelegramChat, pk=chat_id)
    after_id = request.GET.get("after", 0)

    new_messages = (
        tg_chat.messages.select_related("sender")
        .prefetch_related("edits")
        .filter(message_id__gt=after_id)
        .order_by("-date")
    )

    if not new_messages.exists():
        return JsonResponse({"html": "", "latest_id": after_id})

    html = "".join(
        render_to_string("archive/_message.html", {"msg": msg})
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
