"""Пункт 2 без Telegram Premium: юзербот на Telethon слушает личные чаты аккаунта менеджера."""

import logging

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import User

from . import leads
from .bot import notify_new_lead
from .config import settings

log = logging.getLogger("crm.personal_tg")

TELEGRAM_SERVICE_USER_ID = 777000  # служебный аккаунт Telegram, присылает коды входа


def enabled() -> bool:
    return bool(settings.tg_api_id and settings.tg_api_hash and settings.tg_session)


async def start() -> TelegramClient | None:
    client = TelegramClient(
        StringSession(settings.tg_session), settings.tg_api_id, settings.tg_api_hash
    )
    await client.connect()
    if not await client.is_user_authorized():
        log.error("TG_SESSION is invalid or expired, run: python -m app.tg_login")
        await client.disconnect()
        return None
    me = await client.get_me()
    client.add_event_handler(_on_private_message, events.NewMessage(func=lambda e: e.is_private))
    log.info("personal Telegram connected as %s (id %s)", me.username or me.first_name, me.id)
    return client


async def _on_private_message(event: events.NewMessage.Event) -> None:
    text = event.raw_text
    if not text:
        return
    try:
        if event.out:
            leads.record_personal_message(chat_id=event.chat_id, text=text, outgoing=True)
            return

        sender = await event.get_sender()
        if not isinstance(sender, User) or sender.bot or sender.id == TELEGRAM_SERVICE_USER_ID:
            return
        # Люди из записной книжки — знакомые и действующие клиенты, а не новые заявки.
        if (settings.tg_skip_contacts and sender.contact
                and leads.lead_for_tg_chat("tg_personal", event.chat_id) is None):
            return

        lead_id, created = leads.record_personal_message(
            chat_id=event.chat_id, text=text, outgoing=False,
            sender_id=sender.id,
            sender_name=" ".join(filter(None, [sender.first_name, sender.last_name])),
            sender_username=sender.username,
        )
        if created:
            await notify_new_lead(lead_id, "Новый лид из личного Telegram")
    except Exception:
        log.exception("failed to process personal message in chat %s", event.chat_id)
