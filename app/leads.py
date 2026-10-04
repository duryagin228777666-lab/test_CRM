"""Единственное место, где создаются лиды и меняются теги. Бот и веб ходят только сюда."""

import re
import sqlite3
from datetime import datetime, timezone
from typing import Iterable

from .db import connect

SOURCES = {
    "bot": "Бот",
    "tg_personal": "Личный Telegram",
    "manual": "Вручную",
}
SOURCE_TAGS = {
    "bot": "бот",
    "tg_personal": "личный tg",
    "manual": "вручную",
}
STATUSES = {
    "new": "Новый",
    "in_work": "В работе",
    "done": "Закрыт",
}
TAG_MAX_LEN = 40


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_tag(raw: str) -> str | None:
    name = re.sub(r"\s+", " ", raw.strip().lstrip("#").strip()).lower()
    return name[:TAG_MAX_LEN] or None


def parse_tags(raw: str) -> list[str]:
    seen: list[str] = []
    for part in re.split(r"[,;\n]", raw or ""):
        name = normalize_tag(part)
        if name and name not in seen:
            seen.append(name)
    return seen


def _tag_id(conn: sqlite3.Connection, name: str) -> int:
    conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
    return conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()["id"]


def _attach_tags(conn: sqlite3.Connection, lead_id: int, names: Iterable[str]) -> None:
    for raw in names:
        name = normalize_tag(raw)
        if name:
            conn.execute(
                "INSERT OR IGNORE INTO lead_tags (lead_id, tag_id) VALUES (?, ?)",
                (lead_id, _tag_id(conn, name)),
            )


def _touch(conn: sqlite3.Connection, lead_id: int) -> None:
    conn.execute("UPDATE leads SET updated_at = ? WHERE id = ?", (_now(), lead_id))


def create_lead(
    *,
    name: str,
    contact: str,
    request: str,
    source: str,
    tags: Iterable[str] = (),
    tg_user_id: int | None = None,
    tg_username: str | None = None,
    tg_chat_id: int | None = None,
) -> int:
    if source not in SOURCES:
        raise ValueError(f"unknown source: {source}")
    now = _now()
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO leads (name, contact, request, source, tg_user_id, tg_username,
                                  tg_chat_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name.strip(), contact.strip(), request.strip(), source,
             tg_user_id, tg_username, tg_chat_id, now, now),
        )
        lead_id = cur.lastrowid
        _attach_tags(conn, lead_id, [SOURCE_TAGS[source], *tags])
        return lead_id


def update_lead(lead_id: int, *, name: str, contact: str, request: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE leads SET name = ?, contact = ?, request = ?, updated_at = ? WHERE id = ?",
            (name.strip(), contact.strip(), request.strip(), _now(), lead_id),
        )


def delete_lead(lead_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
        return cur.rowcount > 0


def set_status(lead_id: int, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status}")
    with connect() as conn:
        conn.execute(
            "UPDATE leads SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), lead_id)
        )


def add_tags(lead_id: int, names: Iterable[str]) -> None:
    with connect() as conn:
        _attach_tags(conn, lead_id, names)
        _touch(conn, lead_id)


def remove_tag(lead_id: int, name: str) -> None:
    with connect() as conn:
        conn.execute(
            """DELETE FROM lead_tags
               WHERE lead_id = ? AND tag_id = (SELECT id FROM tags WHERE name = ?)""",
            (lead_id, name),
        )
        _touch(conn, lead_id)


def create_tag(raw: str) -> str | None:
    name = normalize_tag(raw)
    if not name:
        return None
    with connect() as conn:
        _tag_id(conn, name)
    return name


def rename_tag(old: str, new_raw: str) -> str | None:
    """Переименовывает тег у всех лидов. Если новое имя уже есть, лиды переезжают на него."""
    old_name = normalize_tag(old)
    new_name = normalize_tag(new_raw)
    if not old_name or not new_name or old_name == new_name:
        return new_name
    with connect() as conn:
        old_row = conn.execute("SELECT id FROM tags WHERE name = ?", (old_name,)).fetchone()
        if old_row is None:
            return None
        new_row = conn.execute("SELECT id FROM tags WHERE name = ?", (new_name,)).fetchone()
        if new_row is None:
            conn.execute("UPDATE tags SET name = ? WHERE id = ?", (new_name, old_row["id"]))
            return new_name
        conn.execute(
            """INSERT OR IGNORE INTO lead_tags (lead_id, tag_id)
               SELECT lead_id, ? FROM lead_tags WHERE tag_id = ?""",
            (new_row["id"], old_row["id"]),
        )
        conn.execute("DELETE FROM lead_tags WHERE tag_id = ?", (old_row["id"],))
        conn.execute("DELETE FROM tags WHERE id = ?", (old_row["id"],))
    return new_name


def delete_tag(name: str) -> None:
    with connect() as conn:
        row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if row is None:
            return
        conn.execute("DELETE FROM lead_tags WHERE tag_id = ?", (row["id"],))
        conn.execute("DELETE FROM tags WHERE id = ?", (row["id"],))


def add_message(lead_id: int, direction: str, text: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO messages (lead_id, direction, text, created_at) VALUES (?, ?, ?, ?)",
            (lead_id, direction, text, _now()),
        )
        _touch(conn, lead_id)


def _tags_by_lead(conn: sqlite3.Connection, lead_ids: list[int]) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {lead_id: [] for lead_id in lead_ids}
    if not lead_ids:
        return result
    marks = ",".join("?" * len(lead_ids))
    rows = conn.execute(
        f"""SELECT lt.lead_id, t.name FROM lead_tags lt JOIN tags t ON t.id = lt.tag_id
            WHERE lt.lead_id IN ({marks}) ORDER BY t.name""",
        lead_ids,
    )
    for row in rows:
        result[row["lead_id"]].append(row["name"])
    return result


def list_leads(*, tag: str | None = None, q: str | None = None) -> list[dict]:
    sql = "SELECT * FROM leads WHERE 1 = 1"
    params: list = []
    if tag:
        sql += """ AND id IN (SELECT lt.lead_id FROM lead_tags lt
                              JOIN tags t ON t.id = lt.tag_id WHERE t.name = ?)"""
        params.append(tag)
    if q and q.strip():
        pattern = f"%{q.strip().lower()}%"
        sql += """ AND (py_lower(name) LIKE ? OR py_lower(contact) LIKE ?
                        OR py_lower(request) LIKE ? OR py_lower(tg_username) LIKE ?)"""
        params += [pattern] * 4
    sql += " ORDER BY created_at DESC, id DESC"
    with connect() as conn:
        leads = [dict(row) for row in conn.execute(sql, params)]
        tags = _tags_by_lead(conn, [lead["id"] for lead in leads])
    for lead in leads:
        lead["tags"] = tags[lead["id"]]
    return leads


def tag_counts() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT t.name, COUNT(lt.lead_id) AS count FROM tags t
               LEFT JOIN lead_tags lt ON lt.tag_id = t.id
               GROUP BY t.id ORDER BY count DESC, t.name"""
        )
        return [dict(row) for row in rows]


def get_lead(lead_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        if row is None:
            return None
        lead = dict(row)
        lead["tags"] = _tags_by_lead(conn, [lead_id])[lead_id]
        lead["messages"] = [
            dict(m) for m in conn.execute(
                "SELECT * FROM messages WHERE lead_id = ? ORDER BY id", (lead_id,)
            )
        ]
    return lead


def latest_lead_for_tg_user(source: str, tg_user_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM leads WHERE source = ? AND tg_user_id = ? ORDER BY id DESC LIMIT 1",
            (source, tg_user_id),
        ).fetchone()
    return dict(row) if row else None


def lead_for_tg_chat(source: str, tg_chat_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM leads WHERE source = ? AND tg_chat_id = ? ORDER BY id DESC LIMIT 1",
            (source, tg_chat_id),
        ).fetchone()
    return dict(row) if row else None


def record_personal_message(
    *,
    chat_id: int,
    text: str,
    outgoing: bool,
    sender_id: int | None = None,
    sender_name: str = "",
    sender_username: str | None = None,
) -> tuple[int | None, bool]:
    """Сообщение из личного Telegram менеджера. Возвращает (lead_id, создан_ли_новый_лид).

    Новый лид появляется только от входящего сообщения: если переписку начал сам
    менеджер, это не заявка, и такой чат игнорируется.
    """
    lead = lead_for_tg_chat("tg_personal", chat_id)
    if lead is None:
        if outgoing:
            return None, False
        lead_id = create_lead(
            name=sender_name,
            contact=f"@{sender_username}" if sender_username else f"tg id {sender_id}",
            request=text[:2000],
            source="tg_personal",
            tg_user_id=sender_id, tg_username=sender_username, tg_chat_id=chat_id,
        )
        add_message(lead_id, "in", text[:4000])
        return lead_id, True
    add_message(lead["id"], "out" if outgoing else "in", text[:4000])
    return lead["id"], False


def is_empty() -> bool:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0


def seed_demo() -> None:
    if not is_empty():
        return
    demo = [
        ("Ирина, кофейня «Зерно»", "+7 900 111-22-33",
         "Открываем вторую точку, нужен таргет ВК на район. Бюджет 50 тыс/мес.",
         "manual", ["таргет", "демо"]),
        ("Олег", "@oleg_auto_parts",
         "Интернет-магазин автозапчастей, хотим Директ и посмотреть, что с SEO.",
         "manual", ["контекст", "seo", "демо"]),
        ("Студия маникюра «Лак»", "lak.studio@example.com",
         "Нужен лендинг под акцию и запуск рекламы.",
         "manual", ["сайт", "демо"]),
    ]
    for name, contact, request, source, tags in demo:
        create_lead(name=name, contact=contact, request=request, source=source, tags=tags)
