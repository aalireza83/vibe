import asyncio
import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest, TranscribeAudioRequest
from telethon.tl.types import (
    Channel,
    Chat,
    MessageMediaContact,
    MessageMediaDocument,
    MessageMediaGeo,
    MessageMediaPhoto,
    MessageMediaPoll,
    UpdateTranscribedAudio,
    User,
)

from archive.models import AppSettings, ChatType, Message, MessageEdit, MessageType, TelegramChat, TelegramUser

# Кеш количества участников: {chat_id: member_count}
# Живёт пока запущен listener, избавляет от повторных запросов к Telegram
_member_count_cache: dict[int, int] = {}

logger = logging.getLogger(__name__)


def get_message_type(message) -> str:
    media = message.media
    if media is None:
        return MessageType.TEXT

    if isinstance(media, MessageMediaPhoto):
        return MessageType.PHOTO

    if isinstance(media, MessageMediaDocument):
        doc = media.document
        attrs = {type(a).__name__: a for a in doc.attributes}

        # Стикер проверяем первым — анимированные стикеры (WEBM) имеют
        # одновременно DocumentAttributeSticker и DocumentAttributeVideo
        if "DocumentAttributeSticker" in attrs:
            return MessageType.STICKER
        if "DocumentAttributeAnimated" in attrs:
            return MessageType.GIF
        if "DocumentAttributeVideo" in attrs:
            if attrs["DocumentAttributeVideo"].round_message:
                return MessageType.VIDEO_NOTE
            return MessageType.VIDEO
        if "DocumentAttributeAudio" in attrs:
            if attrs["DocumentAttributeAudio"].voice:
                return MessageType.VOICE
            return MessageType.AUDIO

        return MessageType.DOCUMENT

    if isinstance(media, MessageMediaGeo):
        return MessageType.LOCATION

    if isinstance(media, MessageMediaContact):
        return MessageType.CONTACT

    if isinstance(media, MessageMediaPoll):
        return MessageType.POLL

    return MessageType.UNKNOWN


async def get_or_create_user(sender) -> TelegramUser | None:
    if sender is None:
        return None

    from asgiref.sync import sync_to_async

    user_id = sender.id

    @sync_to_async
    def _get_or_create():
        obj, _ = TelegramUser.objects.update_or_create(
            user_id=user_id,
            defaults={
                "username": getattr(sender, "username", None),
                "first_name": getattr(sender, "first_name", None),
                "last_name": getattr(sender, "last_name", None),
                "is_self": getattr(sender, "is_self", False),
            },
        )
        return obj

    return await _get_or_create()


async def get_or_create_chat(event, client) -> TelegramChat | None:
    from asgiref.sync import sync_to_async

    chat = await event.get_chat()
    if chat is None:
        return None

    chat_id = chat.id

    if isinstance(chat, Channel):
        # megagroup=True — супергруппа, False — канал
        if not getattr(chat, "megagroup", False):
            logger.debug("Пропускаем канал: %s (id=%d)", chat.title, chat_id)
            return None
        # Супергруппа — обрабатываем как группу
        chat_type = ChatType.GROUP
        title = chat.title
        username = getattr(chat, "username", None)
        member_count = getattr(chat, "participants_count", None)
        logger.debug("Супергруппа: %s (id=%d), участников: %s", title, chat_id, member_count)
    elif isinstance(chat, Chat):
        chat_type = ChatType.GROUP
        title = chat.title
        username = None
        member_count = getattr(chat, "participants_count", None)
        logger.debug("Группа: %s (id=%d), участников: %s", title, chat_id, member_count)
    elif isinstance(chat, User):
        if chat.bot:
            chat_type = ChatType.BOT
        else:
            chat_type = ChatType.PRIVATE
        title = " ".join(filter(None, [chat.first_name, chat.last_name]))
        username = chat.username
        member_count = None
        logger.debug("Личка: %s (id=%d)", title, chat_id)
    else:
        logger.debug("Неизвестный тип чата: %s (id=%d)", type(chat).__name__, chat_id)
        return None

    # Проверяем лимит участников для групп
    if chat_type == ChatType.GROUP:
        app_settings = await sync_to_async(AppSettings.get)()

        # 1. Проверяем in-memory кеш
        if member_count is None:
            member_count = _member_count_cache.get(chat_id)

        # 2. Если нет в кеше — запрашиваем у Telegram и кешируем
        if member_count is None:
            try:
                if isinstance(chat, Channel):
                    full = await client(GetFullChannelRequest(chat))
                    member_count = full.full_chat.participants_count
                else:
                    full = await client(GetFullChatRequest(chat_id))
                    member_count = full.full_chat.participants_count
                if member_count is not None:
                    _member_count_cache[chat_id] = member_count
                    logger.info("Запросили у Telegram '%s': %d участников (закешировано)", title, member_count)
            except Exception as exc:
                logger.warning("Не удалось получить участников для '%s': %s", title, exc)
        else:
            logger.debug("Кеш для '%s': %d участников", title, member_count)

        if member_count is not None and member_count > app_settings.max_group_members:
            logger.info(
                "Пропускаем группу '%s' (%d участников > лимита %d)",
                title,
                member_count,
                app_settings.max_group_members,
            )
            return None

    @sync_to_async
    def _get_or_create():
        obj, _ = TelegramChat.objects.update_or_create(
            chat_id=chat_id,
            defaults={
                "title": title,
                "username": username,
                "chat_type": chat_type,
                "member_count": member_count,
            },
        )
        return obj

    return await _get_or_create()


def extract_message_fields(message) -> dict:
    msg_type = get_message_type(message)
    fields = {
        "message_type": msg_type,
        "text": None,
        "file_name": None,
        "file_size": None,
        "duration": None,
        "sticker_emoji": None,
        "sticker_set": None,
        "audio_title": None,
        "audio_artist": None,
        "poll_question": None,
        "poll_options": None,
        "latitude": None,
        "longitude": None,
        "contact_name": None,
        "contact_phone": None,
        "contact_user_id": None,
    }

    # Подпись/текст сохраняем сразу для всех типов (caption у фото, видео и т.д.)
    if message.text:
        fields["text"] = message.text

    if msg_type == MessageType.TEXT:
        return fields

    media = message.media

    if msg_type == MessageType.POLL and isinstance(media, MessageMediaPoll):
        poll = media.poll
        fields["poll_question"] = poll.question.text if hasattr(poll.question, "text") else str(poll.question)
        fields["poll_options"] = [
            a.text.text if hasattr(a.text, "text") else str(a.text)
            for a in poll.answers
        ]
        return fields

    if msg_type == MessageType.LOCATION and isinstance(media, MessageMediaGeo):
        geo = media.geo
        fields["latitude"] = geo.lat
        fields["longitude"] = geo.long
        return fields

    if msg_type == MessageType.CONTACT and isinstance(media, MessageMediaContact):
        fields["contact_name"] = " ".join(filter(None, [media.first_name, media.last_name]))
        fields["contact_phone"] = media.phone_number
        fields["contact_user_id"] = media.user_id or None
        return fields

    if msg_type == MessageType.PHOTO:
        return fields

    # Document-based types
    if isinstance(media, MessageMediaDocument):
        doc = media.document
        fields["file_size"] = doc.size
        attrs = {type(a).__name__: a for a in doc.attributes}

        if "DocumentAttributeFilename" in attrs:
            fields["file_name"] = attrs["DocumentAttributeFilename"].file_name

        if "DocumentAttributeVideo" in attrs:
            fields["duration"] = int(attrs["DocumentAttributeVideo"].duration)

        if "DocumentAttributeAudio" in attrs:
            audio = attrs["DocumentAttributeAudio"]
            fields["duration"] = int(audio.duration)
            fields["audio_title"] = audio.title
            fields["audio_artist"] = audio.performer

        if "DocumentAttributeSticker" in attrs:
            sticker = attrs["DocumentAttributeSticker"]
            fields["sticker_emoji"] = sticker.alt
            fields["sticker_set"] = getattr(sticker.stickerset, "short_name", None)

    return fields


class Command(BaseCommand):
    help = "Запускает Telegram listener для архивации сообщений"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Запускаем Telegram listener..."))
        asyncio.run(self._run())

    async def _run(self):
        client = TelegramClient(
            settings.TG_SESSION,
            settings.TG_API_ID,
            settings.TG_API_HASH,
        )

        await client.start(phone=settings.TG_PHONE)
        me = await client.get_me()
        logger.info("Авторизован как: %s (id=%d)", me.first_name, me.id)
        self.stdout.write(self.style.SUCCESS(f"Авторизован как: {me.first_name} (id={me.id})"))

        # Сохраняем себя как TelegramUser
        from asgiref.sync import sync_to_async

        @sync_to_async
        def save_me():
            TelegramUser.objects.update_or_create(
                user_id=me.id,
                defaults={
                    "username": me.username,
                    "first_name": me.first_name,
                    "last_name": me.last_name,
                    "is_self": True,
                },
            )

        await save_me()

        @client.on(events.NewMessage)
        async def on_new_message(event):
            try:
                await handle_new_message(event, client)
            except Exception as exc:
                logger.exception("Ошибка при обработке сообщения: %s", exc)

        @client.on(events.MessageEdited)
        async def on_message_edited(event):
            try:
                await handle_message_edited(event)
            except Exception as exc:
                logger.exception("Ошибка при обработке редактирования: %s", exc)

        @client.on(events.MessageDeleted)
        async def on_message_deleted(event):
            try:
                await handle_message_deleted(event)
            except Exception as exc:
                logger.exception("Ошибка при обработке удаления: %s", exc)

        @client.on(events.Raw(UpdateTranscribedAudio))
        async def on_transcription_ready(update):
            try:
                await handle_transcription_update(update)
            except Exception as exc:
                logger.exception("Ошибка при обработке транскрипции: %s", exc)

        self.stdout.write("Слушаем сообщения... (Ctrl+C для остановки)")
        await client.run_until_disconnected()


async def handle_new_message(event, client):
    from asgiref.sync import sync_to_async

    message = event.message

    # Получаем/создаём чат (возвращает None если канал или группа > лимита)
    tg_chat = await get_or_create_chat(event, client)
    if tg_chat is None:
        return

    # Получаем/создаём отправителя
    sender = await event.get_sender()
    tg_user = await get_or_create_user(sender)

    # Извлекаем поля в зависимости от типа
    fields = extract_message_fields(message)

    # Данные о пересылке
    forward_from_id = None
    forward_from_name = None
    if message.forward:
        fwd = message.forward
        if fwd.sender_id:
            forward_from_id = fwd.sender_id
        if fwd.sender:
            s = fwd.sender
            forward_from_name = getattr(s, "username", None) or " ".join(
                filter(None, [getattr(s, "first_name", None), getattr(s, "last_name", None)])
            )
        elif fwd.channel_post:
            forward_from_name = getattr(fwd.chat, "title", None)

    @sync_to_async
    def save_message():
        Message.objects.get_or_create(
            chat=tg_chat,
            message_id=message.id,
            defaults={
                "sender": tg_user,
                "date": message.date,
                "is_forwarded": message.forward is not None,
                "forward_from_id": forward_from_id,
                "forward_from_name": forward_from_name,
                "reply_to_message_id": message.reply_to_msg_id,
                **fields,
            },
        )

    await save_message()

    # Медиа скачиваем в фоне, не блокируя handler
    if message.media and fields["message_type"] not in (
        MessageType.POLL,
        MessageType.LOCATION,
        MessageType.CONTACT,
        MessageType.TEXT,
    ):
        asyncio.create_task(
            download_media_task(client, message, tg_chat, fields["message_type"])
        )

    # Транскрипция для голосовых и кружков
    if fields["message_type"] in (MessageType.VOICE, MessageType.VIDEO_NOTE):
        asyncio.create_task(
            transcribe_message(client, message, tg_chat)
        )

    logger.debug(
        "Сохранено [%s] %s #%d от %s",
        tg_chat,
        fields["message_type"],
        message.id,
        tg_user,
    )


# Семафор: не более 3 одновременных загрузок
_download_semaphore = asyncio.Semaphore(3)


async def download_media_task(client, message, tg_chat: TelegramChat, msg_type: str):
    from asgiref.sync import sync_to_async

    app_settings = await sync_to_async(AppSettings.get)()

    # Проверяем нужно ли скачивать этот тип
    if msg_type == MessageType.AUDIO and not app_settings.download_audio:
        return
    if msg_type == MessageType.DOCUMENT and not app_settings.download_documents:
        return

    # Проверяем размер файла
    if hasattr(message.media, "document"):
        file_size_mb = (message.media.document.size or 0) / (1024 * 1024)
        if file_size_mb > app_settings.max_file_size_mb:
            logger.info(
                "Пропускаем файл %.1f МБ > лимита %d МБ",
                file_size_mb,
                app_settings.max_file_size_mb,
            )
            return

    # Определяем папку
    type_dir = {
        MessageType.PHOTO: "photo",
        MessageType.VIDEO: "video",
        MessageType.VIDEO_NOTE: "vnote",
        MessageType.VOICE: "audio",
        MessageType.AUDIO: "audio",
        MessageType.STICKER: "sticker",
        MessageType.GIF: "gif",
        MessageType.DOCUMENT: "document",
    }.get(msg_type, "other")

    from pathlib import Path

    from django.conf import settings as django_settings

    save_dir = Path(django_settings.MEDIA_ROOT) / str(tg_chat.chat_id) / type_dir
    save_dir.mkdir(parents=True, exist_ok=True)

    # Фото — небольшой размер, остальное — полный файл
    thumb = None
    if msg_type == MessageType.PHOTO:
        thumb = 1  # небольшой размер, не оригинал

    async with _download_semaphore:
        try:
            path = await client.download_media(
                message,
                file=str(save_dir) + "/",
                thumb=thumb,
            )
            if path:
                @sync_to_async
                def update_path():
                    Message.objects.filter(
                        chat=tg_chat,
                        message_id=message.id,
                    ).update(media_path=path)

                await update_path()
                logger.debug("Скачан файл: %s", path)

        except FloodWaitError as exc:
            logger.warning("FloodWait %d сек, ждём...", exc.seconds)
            await asyncio.sleep(exc.seconds)
            # Повторная попытка
            await download_media_task(client, message, tg_chat, msg_type)
        except Exception as exc:
            logger.exception("Ошибка загрузки медиа: %s", exc)


async def transcribe_message(client, message, tg_chat: TelegramChat):
    from asgiref.sync import sync_to_async

    try:
        result = await client(TranscribeAudioRequest(
            peer=await client.get_input_entity(tg_chat.chat_id),
            msg_id=message.id,
        ))

        if not result.pending:
            # Текст уже готов
            @sync_to_async
            def save_transcription():
                Message.objects.filter(
                    chat=tg_chat,
                    message_id=message.id,
                ).update(
                    transcription=result.text,
                    transcription_pending=False,
                )

            await save_transcription()
            logger.debug("Транскрипция готова для сообщения #%d", message.id)
        else:
            # Помечаем как pending, результат придёт через UpdateTranscribedAudio
            @sync_to_async
            def mark_pending():
                Message.objects.filter(
                    chat=tg_chat,
                    message_id=message.id,
                ).update(transcription_pending=True)

            await mark_pending()
            logger.debug("Транскрипция ожидается для сообщения #%d", message.id)

    except Exception as exc:
        logger.warning("Не удалось запустить транскрипцию для #%d: %s", message.id, exc)


async def handle_transcription_update(update: UpdateTranscribedAudio):
    from asgiref.sync import sync_to_async

    if update.pending:
        return  # ещё не готово

    @sync_to_async
    def save():
        Message.objects.filter(
            chat__chat_id=update.peer.channel_id
            if hasattr(update.peer, "channel_id")
            else update.peer.chat_id
            if hasattr(update.peer, "chat_id")
            else update.peer.user_id,
            message_id=update.msg_id,
        ).update(
            transcription=update.text,
            transcription_pending=False,
        )

    await save()
    logger.debug("Транскрипция обновлена для сообщения #%d", update.msg_id)


async def handle_message_edited(event):
    from asgiref.sync import sync_to_async

    message = event.message
    chat = await event.get_chat()
    if chat is None:
        return

    new_text = message.text or ""
    edited_at = message.edit_date or timezone.now()

    @sync_to_async
    def update_message():
        try:
            msg = Message.objects.get(
                chat__chat_id=chat.id,
                message_id=message.id,
            )
        except Message.DoesNotExist:
            return

        # Сохраняем предыдущую версию в историю
        if msg.text:
            MessageEdit.objects.create(
                message=msg,
                text=msg.text,
                edited_at=edited_at,
            )

        msg.text = new_text
        msg.edited_at = edited_at
        msg.save(update_fields=["text", "edited_at"])

    await update_message()
    logger.debug("Отредактировано сообщение #%d в чате %d", message.id, chat.id)


async def handle_message_deleted(event):
    from asgiref.sync import sync_to_async

    deleted_ids = event.deleted_ids
    chat = await event.get_chat()
    chat_id = chat.id if chat else None

    if not deleted_ids:
        return

    now = timezone.now()

    @sync_to_async
    def mark_deleted():
        qs = Message.objects.filter(message_id__in=deleted_ids)
        if chat_id:
            qs = qs.filter(chat__chat_id=chat_id)
        count = qs.update(is_deleted=True, deleted_at=now)
        return count

    count = await mark_deleted()
    logger.debug(
        "Помечено удалёнными %d сообщений (ids: %s)",
        count,
        deleted_ids[:5],
    )
