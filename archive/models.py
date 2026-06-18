from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.conf import settings


class AppSettings(models.Model):
    max_group_members = models.IntegerField(
        default=50,
        verbose_name="Max group members",
        help_text="Groups with more members are ignored",
    )
    download_audio = models.BooleanField(
        default=False,
        verbose_name="Download audio",
    )
    download_documents = models.BooleanField(
        default=False,
        verbose_name="Download documents",
    )
    max_file_size_mb = models.IntegerField(
        default=50,
        verbose_name="Max file size (MB)",
        help_text="Files larger than this size are not downloaded",
    )

    class Meta:
        verbose_name = "Settings"
        verbose_name_plural = "Settings"

    def __str__(self):
        return "Application settings"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class TelegramUser(models.Model):
    user_id = models.BigIntegerField(unique=True, verbose_name="Telegram ID")
    username = models.CharField(max_length=255, blank=True, null=True, verbose_name="Username")
    first_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="First name")
    last_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Last name")
    is_self = models.BooleanField(default=False, verbose_name="This is me")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Telegram user"
        verbose_name_plural = "Telegram users"

    def __str__(self):
        if self.username:
            return f"@{self.username}"
        name = " ".join(filter(None, [self.first_name, self.last_name]))
        return name or str(self.user_id)

    @property
    def display_name(self):
        name = " ".join(filter(None, [self.first_name, self.last_name]))
        if name and self.username:
            return f"{name} (@{self.username})"
        return name or f"@{self.username}" or str(self.user_id)


class ChatType(models.TextChoices):
    PRIVATE = "private", "Private chat"
    GROUP = "group", "Group"
    BOT = "bot", "Bot"


class TelegramChat(models.Model):
    chat_id = models.BigIntegerField(unique=True, verbose_name="Telegram chat ID")
    title = models.CharField(max_length=255, blank=True, null=True, verbose_name="Title")
    username = models.CharField(max_length=255, blank=True, null=True, verbose_name="Username")
    chat_type = models.CharField(max_length=20, choices=ChatType.choices, verbose_name="Type")
    member_count = models.IntegerField(blank=True, null=True, verbose_name="Members")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated")

    class Meta:
        verbose_name = "Chat"
        verbose_name_plural = "Chats"
        indexes = [
            models.Index(fields=["-updated_at"]),
        ]

    def __str__(self):
        return self.title or f"Chat {self.chat_id}"

    @property
    def display_name(self):
        return self.title or self.username or str(self.chat_id)


class MessageType(models.TextChoices):
    TEXT = "text", "Text"
    PHOTO = "photo", "Photo"
    VIDEO = "video", "Video"
    AUDIO = "audio", "Audio"
    VOICE = "voice", "Voice"
    VIDEO_NOTE = "video_note", "Video note"
    STICKER = "sticker", "Sticker"
    GIF = "gif", "GIF"
    DOCUMENT = "document", "Document"
    POLL = "poll", "Poll"
    LOCATION = "location", "Location"
    CONTACT = "contact", "Contact"
    UNKNOWN = "unknown", "Unknown"


class Message(models.Model):
    message_id = models.BigIntegerField(verbose_name="Telegram message ID")
    chat = models.ForeignKey(
        TelegramChat,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="Chat",
    )
    sender = models.ForeignKey(
        TelegramUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
        verbose_name="Sender",
    )
    date = models.DateTimeField(verbose_name="Sent at")
    message_type = models.CharField(
        max_length=20,
        choices=MessageType.choices,
        default=MessageType.TEXT,
        verbose_name="Type",
    )

    # Content
    text = models.TextField(blank=True, null=True, verbose_name="Text")
    media_path = models.CharField(max_length=500, blank=True, null=True, verbose_name="File path")
    file_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="File name")
    file_size = models.BigIntegerField(blank=True, null=True, verbose_name="File size (bytes)")
    duration = models.IntegerField(blank=True, null=True, verbose_name="Duration (seconds)")

    # Sticker
    sticker_emoji = models.CharField(max_length=10, blank=True, null=True, verbose_name="Sticker emoji")
    sticker_set = models.CharField(max_length=255, blank=True, null=True, verbose_name="Sticker set")

    # Audio
    audio_title = models.CharField(max_length=255, blank=True, null=True, verbose_name="Track title")
    audio_artist = models.CharField(max_length=255, blank=True, null=True, verbose_name="Artist")

    # Poll
    poll_question = models.TextField(blank=True, null=True, verbose_name="Poll question")
    poll_options = models.JSONField(blank=True, null=True, verbose_name="Answer options")

    # Location
    latitude = models.FloatField(blank=True, null=True, verbose_name="Latitude")
    longitude = models.FloatField(blank=True, null=True, verbose_name="Longitude")

    # Contact
    contact_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Contact name")
    contact_phone = models.CharField(max_length=50, blank=True, null=True, verbose_name="Contact phone")
    contact_user_id = models.BigIntegerField(blank=True, null=True, verbose_name="Telegram contact ID")

    # Transcription (voice messages and video notes)
    transcription = models.TextField(blank=True, null=True, verbose_name="Transcription")
    transcription_pending = models.BooleanField(default=False, verbose_name="Transcription in progress")

    # Forwarding
    is_forwarded = models.BooleanField(default=False, verbose_name="Forwarded")
    forward_from_id = models.BigIntegerField(blank=True, null=True, verbose_name="Forwarded from (ID)")
    forward_from_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Forwarded from (name)")

    # Reply
    reply_to_message_id = models.BigIntegerField(blank=True, null=True, verbose_name="Reply to message ID")

    # Editing
    edited_at = models.DateTimeField(blank=True, null=True, verbose_name="Edited")

    # Deletion
    is_deleted = models.BooleanField(default=False, verbose_name="Deleted")
    deleted_at = models.DateTimeField(blank=True, null=True, verbose_name="Deleted at")

    # Full-text search
    search_vector = SearchVectorField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Message"
        verbose_name_plural = "Messages"
        constraints = [
            models.UniqueConstraint(fields=["chat", "message_id"], name="unique_message_in_chat"),
        ]
        indexes = [
            models.Index(fields=["chat", "-date"], name="idx_message_chat_date"),
            models.Index(fields=["chat", "message_id"], name="idx_message_chat_msgid"),
            models.Index(
                fields=["transcription_pending"],
                name="idx_msg_transcribe_pending",
                condition=models.Q(transcription_pending=True),
            ),
            GinIndex(fields=["search_vector"], name="idx_message_search_vector"),
        ]

    def __str__(self):
        return f"[{self.chat}] {self.message_type} #{self.message_id}"

    @property
    def media_url(self):
        if not self.media_path:
            return None
        media_root = str(settings.MEDIA_ROOT)
        path = str(self.media_path)
        if path.startswith(media_root):
            relative = path[len(media_root):].lstrip("/")
        else:
            relative = path.lstrip("/")
        return f"{settings.MEDIA_URL}{relative}"


class Bookmark(models.Model):
    message = models.OneToOneField(
        Message,
        on_delete=models.CASCADE,
        related_name="bookmark",
        verbose_name="Message",
    )
    note = models.TextField(blank=True, null=True, verbose_name="Note")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Bookmark"
        verbose_name_plural = "Bookmarks"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Bookmark for #{self.message_id}"


class MessageEdit(models.Model):
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="edits",
        verbose_name="Message",
    )
    text = models.TextField(verbose_name="Text before edit")
    edited_at = models.DateTimeField(verbose_name="Edit time")

    class Meta:
        verbose_name = "Edit history"
        verbose_name_plural = "Edit history"
        ordering = ["edited_at"]

    def __str__(self):
        return f"Edit for message #{self.message_id} at {self.edited_at}"
