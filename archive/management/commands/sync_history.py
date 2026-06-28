import asyncio
import logging
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.core.management.base import BaseCommand
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl import types
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.types import Channel, Chat, User

from archive.management.commands.run_listener import (
    _member_count_cache,
    extract_message_fields,
    get_or_create_user,
)
from archive.models import AppSettings, ChatType, Message, TelegramChat

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Synchronizes message history for the last N days"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=7,
            help="Sync depth in days (default: 7)",
        )
        parser.add_argument(
            "--chat", type=int, default=None,
            help="Telegram ID of a specific chat (default: all)",
        )

    def handle(self, *args, **options):
        try:
            asyncio.run(self._run(options["days"], options["chat"]))
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nStopped."))

    async def _run(self, days, chat_id_filter):
        from asgiref.sync import sync_to_async

        client = TelegramClient(
            settings.TG_SESSION,
            settings.TG_API_ID,
            settings.TG_API_HASH,
            device_model=settings.DEVICE_MODEL,
            system_version=settings.SYSTEM_VERSION,
            app_version=settings.APP_VERSION,
            lang_code=settings.LANG_CODE,
            system_lang_code=settings.SYSTEM_LANG_CODE
        )

        client._init_request.lang_pack = "tdesktop" or ""

        client._init_request.params = types.JsonObject([
            types.JsonObjectValue(
                key="tz_offset",
                value=types.JsonNumber(
                    value=12600
                )
            )
        ])

        await client.start(phone=settings.TG_PHONE)
        self.stdout.write(self.style.SUCCESS(f"Synchronizing the last {days} days..."))

        # Load member count cache from the database.
        @sync_to_async
        def load_cache():
            for chat_id, mc in TelegramChat.objects.filter(
                member_count__isnull=False
            ).values_list("chat_id", "member_count"):
                _member_count_cache[chat_id] = mc

        await load_cache()

        app_settings = await sync_to_async(AppSettings.get)()
        since = datetime.now(timezone.utc) - timedelta(days=days)

        if chat_id_filter:
            # Synchronize one specific chat.
            try:
                entity = await client.get_entity(chat_id_filter)
                dialogs = [entity]
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"Chat {chat_id_filter} was not found: {exc}"))
                await client.disconnect()
                return
        else:
            # All dialogs.
            self.stdout.write("Fetching dialog list...")
            dialogs = [d.entity async for d in client.iter_dialogs()]

        total_saved = 0

        for entity in dialogs:
            tg_chat = await self._get_or_create_chat(entity, client, app_settings)
            if tg_chat is None:
                continue

            count = await self._sync_chat(client, entity, tg_chat, since)
            if count > 0:
                self.stdout.write(f"  {tg_chat.display_name}: +{count} messages")
            total_saved += count

        await client.disconnect()
        self.stdout.write(self.style.SUCCESS(f"\nDone. Saved: {total_saved} messages."))

    async def _get_or_create_chat(self, entity, client, app_settings) -> TelegramChat | None:
        from asgiref.sync import sync_to_async

        if isinstance(entity, Channel):
            if not getattr(entity, "megagroup", False):
                return None
            chat_type = ChatType.GROUP
            title = entity.title
            username = getattr(entity, "username", None)
            chat_id = entity.id
            member_count = _member_count_cache.get(chat_id)
            if member_count is None:
                try:
                    full = await client(GetFullChannelRequest(entity))
                    member_count = full.full_chat.participants_count
                    if member_count is not None:
                        _member_count_cache[chat_id] = member_count
                except Exception:
                    pass

        elif isinstance(entity, Chat):
            chat_type = ChatType.GROUP
            title = entity.title
            username = None
            chat_id = entity.id
            member_count = _member_count_cache.get(chat_id)
            if member_count is None:
                try:
                    full = await client(GetFullChatRequest(chat_id))
                    member_count = full.full_chat.participants_count
                    if member_count is not None:
                        _member_count_cache[chat_id] = member_count
                except Exception:
                    pass

        elif isinstance(entity, User):
            chat_type = ChatType.BOT if entity.bot else ChatType.PRIVATE
            title = " ".join(filter(None, [entity.first_name, entity.last_name]))
            username = entity.username
            chat_id = entity.id
            member_count = None
        else:
            return None

        if chat_type == ChatType.GROUP and member_count is not None:
            if member_count > app_settings.max_group_members:
                return None

        @sync_to_async
        def _save():
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

        return await _save()

    async def _sync_chat(self, client, entity, tg_chat: TelegramChat, since: datetime) -> int:
        from asgiref.sync import sync_to_async

        count = 0

        try:
            async for message in client.iter_messages(
                entity,
                reverse=True,
                offset_date=since,
            ):
                # Skip service messages, such as group joins.
                if message.action is not None:
                    continue

                sender = await message.get_sender()
                tg_user = await get_or_create_user(sender)
                fields = extract_message_fields(message)

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

                @sync_to_async
                def save_msg():
                    _, created = Message.objects.get_or_create(
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
                    return created

                created = await save_msg()
                if created:
                    count += 1

        except FloodWaitError as exc:
            self.stdout.write(self.style.WARNING(f"  FloodWait {exc.seconds}s for {tg_chat}..."))
            await asyncio.sleep(exc.seconds)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Error for {tg_chat}: {exc}"))

        return count
