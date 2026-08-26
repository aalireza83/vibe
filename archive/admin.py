from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import path

from .forms import MediaBackupForm
from .media_backup import (
    create_media_backup,
    delete_archived_originals,
    send_backup_to_saved_messages,
)
from .models import AppSettings, Bookmark, Message, MessageEdit, TelegramChat, TelegramUser


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    change_list_template = "admin/archive/appsettings/change_list.html"
    change_form_template = "admin/archive/appsettings/change_form.html"
    fieldsets = (
        ("Chat Filtering", {
            "fields": ("max_group_members", "archive_bot_chats"),
        }),
        ("File Downloads", {
            "fields": ("download_audio", "download_documents", "max_file_size_mb"),
        }),
    )

    def has_add_permission(self, request):
        return not AppSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        custom_urls = [
            path(
                "media-backup/",
                self.admin_site.admin_view(self.media_backup_view),
                name="archive_appsettings_media_backup",
            ),
        ]
        return custom_urls + super().get_urls()

    def media_backup_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied

        if request.method == "POST":
            form = MediaBackupForm(request.POST)
            if form.is_valid():
                try:
                    result = create_media_backup(form.cleaned_data["cutoff_date"])
                    send_backup_to_saved_messages(result)
                except Exception as exc:
                    self.message_user(
                        request,
                        f"Media backup or Telegram upload failed: {exc}. The ZIP was kept locally.",
                        level=messages.ERROR,
                    )
                else:
                    deleted_count = 0
                    try:
                        if form.cleaned_data["delete_originals"]:
                            deleted_count = delete_archived_originals(result)
                    except Exception as exc:
                        self.message_user(
                            request,
                            f"Backup was sent to Saved Messages, but original-file cleanup failed: {exc}",
                            level=messages.WARNING,
                        )
                        return redirect("admin:archive_appsettings_media_backup")

                    # Saved Messages is the backup destination; do not retain a duplicate ZIP locally.
                    try:
                        result.archive_path.unlink(missing_ok=True)
                    except OSError as exc:
                        self.message_user(
                            request,
                            f"Backup was sent, but the temporary local ZIP could not be removed: {exc}",
                            level=messages.WARNING,
                        )
                        return redirect("admin:archive_appsettings_media_backup")

                    self.message_user(
                        request,
                        (
                            f"Backup sent to Telegram Saved Messages: "
                            f"{result.file_count} files, {result.skipped_count} skipped, "
                            f"{deleted_count} originals deleted."
                        ),
                        level=messages.SUCCESS,
                    )
                    return redirect("admin:archive_appsettings_media_backup")
        else:
            form = MediaBackupForm()

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Back up old media",
            "form": form,
        }
        return render(request, "admin/archive/appsettings/media_backup.html", context)


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ("user_id", "username", "first_name", "last_name", "is_self", "created_at")
    search_fields = ("user_id", "username", "first_name", "last_name")
    readonly_fields = ("user_id", "created_at", "updated_at")


@admin.register(TelegramChat)
class TelegramChatAdmin(admin.ModelAdmin):
    list_display = ("chat_id", "title", "username", "chat_type", "member_count", "is_hidden", "updated_at")
    list_editable = ("is_hidden",)
    list_filter = ("chat_type", "is_hidden")
    search_fields = ("chat_id", "title", "username")
    readonly_fields = ("chat_id", "updated_at")


class MessageEditInline(admin.TabularInline):
    model = MessageEdit
    fields = ("text", "edited_at")
    readonly_fields = ("text", "edited_at")
    extra = 0
    can_delete = False


@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    list_display = ("message", "note", "created_at")
    readonly_fields = ("message", "created_at")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("message_id", "chat", "sender", "message_type", "date", "is_deleted")
    list_filter = ("message_type", "is_deleted", "is_forwarded", "chat__chat_type")
    search_fields = ("text", "transcription", "file_name")
    readonly_fields = ("message_id", "chat", "sender", "date", "search_vector", "created_at")
    inlines = [MessageEditInline]
