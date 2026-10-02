import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Явный путь: без него python-dotenv ищет .env вверх по дереву и может подхватить чужой.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _int_list(raw: str) -> tuple[int, ...]:
    return tuple(int(part) for part in raw.replace(" ", "").split(",") if part)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    manager_chat_ids: tuple[int, ...]
    public_url: str
    admin_login: str
    admin_password: str
    secret_key: str
    db_path: str
    timezone: str
    seed_demo: bool
    telegram_proxy: str


settings = Settings(
    bot_token=os.getenv("BOT_TOKEN", "").strip(),
    manager_chat_ids=_int_list(os.getenv("MANAGER_CHAT_IDS", "")),
    public_url=os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/"),
    admin_login=os.getenv("ADMIN_LOGIN", "demo"),
    admin_password=os.getenv("ADMIN_PASSWORD", "demo"),
    secret_key=os.getenv("SECRET_KEY", "dev-secret-change-me"),
    db_path=os.getenv("DB_PATH", "data/crm.db"),
    timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
    seed_demo=os.getenv("SEED_DEMO", "0") == "1",
    telegram_proxy=os.getenv("TELEGRAM_PROXY", "").strip(),
)
