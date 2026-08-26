from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import path

from .forms import MediaBackupForm
from .models import (
    AppSettings,
    Bookmark,
    MediaBackupJob,
    Message,
    MessageEdit,
    TelegramChat,
    TelegramUser,
)


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
                    job = MediaBackupJob.objects.create(
                        cutoff_date=form.cleaned_data["cutoff_date"],
                        delete_originals=form.cleaned_data["delete_originals"],
                    )
                except Exception as exc:
                    self.message_user(
                        request,
                        f"Media backup request could not be queued: {exc}",
                        level=messages.ERROR,
                    )
                else:
                    self.message_user(
                        request,
                        f"Backup #{job.pk} was queued. The listener will create and send it to Saved Messages.",
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


@admin.register(MediaBackupJob)
class MediaBackupJobAdmin(admin.ModelAdmin):
    list_display = (
        "id", "cutoff_date", "status", "file_count", "skipped_count",
        "deleted_count", "delete_originals", "created_at", "completed_at",
    )
    list_filter = ("status", "delete_originals")
    readonly_fields = (
        "cutoff_date", "archive_path", "delete_originals", "status",
        "file_count", "skipped_count", "deleted_count", "error",
        "created_at", "started_at", "completed_at",
    )
    actions = ("retry_failed_jobs",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Retry selected failed or interrupted backup jobs")
    def retry_failed_jobs(self, request, queryset):
        count = queryset.filter(
            status__in=(MediaBackupJob.Status.FAILED, MediaBackupJob.Status.UPLOADING)
        ).update(
            status=MediaBackupJob.Status.PENDING,
            error="",
            started_at=None,
            completed_at=None,
        )
        self.message_user(request, f"{count} backup job(s) queued for retry.")


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
