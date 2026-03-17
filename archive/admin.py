from django.contrib import admin

from .models import AppSettings, Message, MessageEdit, TelegramChat, TelegramUser


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Фильтрация чатов", {
            "fields": ("max_group_members",),
        }),
        ("Загрузка файлов", {
            "fields": ("download_audio", "download_documents", "max_file_size_mb"),
        }),
    )

    def has_add_permission(self, request):
        return not AppSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ("user_id", "username", "first_name", "last_name", "is_self", "created_at")
    search_fields = ("user_id", "username", "first_name", "last_name")
    readonly_fields = ("user_id", "created_at", "updated_at")


@admin.register(TelegramChat)
class TelegramChatAdmin(admin.ModelAdmin):
    list_display = ("chat_id", "title", "username", "chat_type", "member_count", "updated_at")
    list_filter = ("chat_type",)
    search_fields = ("chat_id", "title", "username")
    readonly_fields = ("chat_id", "updated_at")


class MessageEditInline(admin.TabularInline):
    model = MessageEdit
    fields = ("text", "edited_at")
    readonly_fields = ("text", "edited_at")
    extra = 0
    can_delete = False


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("message_id", "chat", "sender", "message_type", "date", "is_deleted")
    list_filter = ("message_type", "is_deleted", "is_forwarded", "chat__chat_type")
    search_fields = ("text", "transcription", "file_name")
    readonly_fields = ("message_id", "chat", "sender", "date", "search_vector", "created_at")
    inlines = [MessageEditInline]
