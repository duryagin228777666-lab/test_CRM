"""Однократный вход в личный Telegram: python -m app.tg_login

Спросит номер телефона, код из Telegram и пароль 2FA (если есть) и напечатает
строку сессии. Её нужно положить в TG_SESSION. Строка даёт полный доступ к аккаунту:
храните её только в .env / секретах хостинга.
"""

import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession

from .config import settings


async def main() -> None:
    if not (settings.tg_api_id and settings.tg_api_hash):
        raise SystemExit("Заполните TG_API_ID и TG_API_HASH в .env (https://my.telegram.org/apps)")
    async with TelegramClient(StringSession(), settings.tg_api_id, settings.tg_api_hash) as client:
        me = await client.get_me()
        print(f"\nВошли как {me.first_name} (@{me.username}). Добавьте в .env строку:\n")
        print(f"TG_SESSION={client.session.save()}")


if __name__ == "__main__":
    asyncio.run(main())
