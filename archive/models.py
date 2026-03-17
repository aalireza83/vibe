from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models


class AppSettings(models.Model):
    max_group_members = models.IntegerField(
        default=50,
        verbose_name="Макс. участников в группе",
        help_text="Группы с бо́льшим числом участников игнорируются",
    )
    download_audio = models.BooleanField(
        default=False,
        verbose_name="Скачивать аудио",
    )
    download_documents = models.BooleanField(
        default=False,
        verbose_name="Скачивать документы",
    )
    max_file_size_mb = models.IntegerField(
        default=50,
        verbose_name="Макс. размер файла (МБ)",
        help_text="Файлы больше этого размера не скачиваются",
    )

    class Meta:
        verbose_name = "Настройки"
        verbose_name_plural = "Настройки"

    def __str__(self):
        return "Настройки приложения"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class TelegramUser(models.Model):
    user_id = models.BigIntegerField(unique=True, verbose_name="Telegram ID")
    username = models.CharField(max_length=255, blank=True, null=True, verbose_name="Username")
    first_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Имя")
    last_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Фамилия")
    is_self = models.BooleanField(default=False, verbose_name="Это я")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Пользователь Telegram"
        verbose_name_plural = "Пользователи Telegram"

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
    PRIVATE = "private", "Личная переписка"
    GROUP = "group", "Группа"
    BOT = "bot", "Бот"


class TelegramChat(models.Model):
    chat_id = models.BigIntegerField(unique=True, verbose_name="Telegram ID чата")
    title = models.CharField(max_length=255, blank=True, null=True, verbose_name="Название")
    username = models.CharField(max_length=255, blank=True, null=True, verbose_name="Username")
    chat_type = models.CharField(max_length=20, choices=ChatType.choices, verbose_name="Тип")
    member_count = models.IntegerField(blank=True, null=True, verbose_name="Участников")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    class Meta:
        verbose_name = "Чат"
        verbose_name_plural = "Чаты"
        indexes = [
            models.Index(fields=["-updated_at"]),
        ]

    def __str__(self):
        return self.title or f"Chat {self.chat_id}"

    @property
    def display_name(self):
        return self.title or self.username or str(self.chat_id)


class MessageType(models.TextChoices):
    TEXT = "text", "Текст"
    PHOTO = "photo", "Фото"
    VIDEO = "video", "Видео"
    AUDIO = "audio", "Аудио"
    VOICE = "voice", "Голосовое"
    VIDEO_NOTE = "video_note", "Кружок"
    STICKER = "sticker", "Стикер"
    GIF = "gif", "GIF"
    DOCUMENT = "document", "Документ"
    POLL = "poll", "Опрос"
    LOCATION = "location", "Геолокация"
    CONTACT = "contact", "Контакт"
    UNKNOWN = "unknown", "Неизвестно"


class Message(models.Model):
    message_id = models.BigIntegerField(verbose_name="Telegram ID сообщения")
    chat = models.ForeignKey(
        TelegramChat,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="Чат",
    )
    sender = models.ForeignKey(
        TelegramUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
        verbose_name="Отправитель",
    )
    date = models.DateTimeField(verbose_name="Дата отправки")
    message_type = models.CharField(
        max_length=20,
        choices=MessageType.choices,
        default=MessageType.TEXT,
        verbose_name="Тип",
    )

    # Контент
    text = models.TextField(blank=True, null=True, verbose_name="Текст")
    media_path = models.CharField(max_length=500, blank=True, null=True, verbose_name="Путь к файлу")
    file_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Имя файла")
    file_size = models.BigIntegerField(blank=True, null=True, verbose_name="Размер файла (байт)")
    duration = models.IntegerField(blank=True, null=True, verbose_name="Длительность (сек)")

    # Стикер
    sticker_emoji = models.CharField(max_length=10, blank=True, null=True, verbose_name="Эмодзи стикера")
    sticker_set = models.CharField(max_length=255, blank=True, null=True, verbose_name="Набор стикеров")

    # Аудио
    audio_title = models.CharField(max_length=255, blank=True, null=True, verbose_name="Название трека")
    audio_artist = models.CharField(max_length=255, blank=True, null=True, verbose_name="Исполнитель")

    # Опрос
    poll_question = models.TextField(blank=True, null=True, verbose_name="Вопрос опроса")
    poll_options = models.JSONField(blank=True, null=True, verbose_name="Варианты ответа")

    # Геолокация
    latitude = models.FloatField(blank=True, null=True, verbose_name="Широта")
    longitude = models.FloatField(blank=True, null=True, verbose_name="Долгота")

    # Контакт
    contact_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Имя контакта")
    contact_phone = models.CharField(max_length=50, blank=True, null=True, verbose_name="Телефон контакта")
    contact_user_id = models.BigIntegerField(blank=True, null=True, verbose_name="Telegram ID контакта")

    # Транскрипция (голосовые и кружки)
    transcription = models.TextField(blank=True, null=True, verbose_name="Транскрипция")
    transcription_pending = models.BooleanField(default=False, verbose_name="Транскрипция в процессе")

    # Пересылка
    is_forwarded = models.BooleanField(default=False, verbose_name="Пересланное")
    forward_from_id = models.BigIntegerField(blank=True, null=True, verbose_name="Переслано от (ID)")
    forward_from_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Переслано от (имя)")

    # Ответ
    reply_to_message_id = models.BigIntegerField(blank=True, null=True, verbose_name="Ответ на сообщение ID")

    # Редактирование
    edited_at = models.DateTimeField(blank=True, null=True, verbose_name="Отредактировано")

    # Удаление
    is_deleted = models.BooleanField(default=False, verbose_name="Удалено")
    deleted_at = models.DateTimeField(blank=True, null=True, verbose_name="Удалено в")

    # Полнотекстовый поиск
    search_vector = SearchVectorField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Сообщение"
        verbose_name_plural = "Сообщения"
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


class MessageEdit(models.Model):
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="edits",
        verbose_name="Сообщение",
    )
    text = models.TextField(verbose_name="Текст до редактирования")
    edited_at = models.DateTimeField(verbose_name="Время редактирования")

    class Meta:
        verbose_name = "История правок"
        verbose_name_plural = "История правок"
        ordering = ["edited_at"]

    def __str__(self):
        return f"Правка сообщения #{self.message_id} в {self.edited_at}"
