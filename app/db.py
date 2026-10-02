import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL DEFAULT '',
    contact       TEXT NOT NULL DEFAULT '',
    request       TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL CHECK (source IN ('bot', 'tg_personal', 'manual')),
    status        TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'in_work', 'done')),
    tg_user_id    INTEGER,
    tg_username   TEXT,
    tg_chat_id    INTEGER,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS lead_tags (
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (lead_id, tag_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id    INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    direction  TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_leads_tg_chat ON leads (source, tg_chat_id);
CREATE INDEX IF NOT EXISTS idx_lead_tags_tag ON lead_tags (tag_id);
CREATE INDEX IF NOT EXISTS idx_messages_lead ON messages (lead_id);
"""


def _lower(value):
    # Встроенный LOWER() в SQLite не понимает кириллицу, поиск без учёта регистра идёт через Python.
    return value.lower() if isinstance(value, str) else value


@contextmanager
def connect():
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("py_lower", 1, _lower, deterministic=True)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
