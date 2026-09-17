"""Доступ до даних: записи, теги, вектори, задачі."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import numpy as np

from ..ingest.storage import Prepared
from .connection import SPACES, TEXT_SPACE, get_connection, serialize, vec_table


def _now() -> str:
    return datetime.now(UTC).isoformat()


# --- записи ---------------------------------------------------------------


def find_by_hash(content_hash: str) -> sqlite3.Row | None:
    return get_connection().execute(
        "SELECT * FROM items WHERE content_hash = ?", (content_hash,)
    ).fetchone()


def create_item(prepared: Prepared, status: str = "pending") -> int:
    conn = get_connection()
    cursor = conn.execute(
        """
        INSERT INTO items (kind, label, status, created_at, added_at, stored_path,
                           source_path, content_hash, mime, size_bytes, duration_s,
                           width, height, text_content)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            prepared.kind, prepared.label, status, prepared.created_at, _now(),
            prepared.stored_path, prepared.source_path, prepared.content_hash,
            prepared.mime, prepared.size_bytes, prepared.duration_s,
            prepared.width, prepared.height, prepared.text_content,
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def get_item(item_id: int) -> sqlite3.Row | None:
    return get_connection().execute(
        "SELECT * FROM items WHERE id = ?", (item_id,)
    ).fetchone()


def update_item(item_id: int, **fields: Any) -> None:
    if not fields:
        return
    conn = get_connection()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(
        f"UPDATE items SET {assignments} WHERE id = ?",  # noqa: S608 — ключі з коду
        (*fields.values(), item_id),
    )
    conn.commit()


def delete_item(item_id: int) -> sqlite3.Row | None:
    """Видаляє запис. Вектори чистяться явно: vec0-таблиці не беруть участі
    в каскадах зовнішніх ключів."""
    conn = get_connection()
    item = get_item(item_id)
    if item is None:
        return None

    for space in SPACES:
        rows = conn.execute(
            "SELECT id, vec_rowid FROM embeddings WHERE item_id = ? AND space = ?",
            (item_id, space),
        ).fetchall()
        table = vec_table(space)
        for row in rows:
            conn.execute(f"DELETE FROM {table} WHERE rowid = ?", (row["vec_rowid"],))  # noqa: S608
            conn.execute("DELETE FROM chunk_fts WHERE rowid = ?", (row["id"],))

    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()
    return item


def count_items() -> int:
    row = get_connection().execute("SELECT COUNT(*) AS n FROM items").fetchone()
    return int(row["n"])


def originals_bytes() -> int:
    """Скільки важать оригінали. Розмір кожного вже лежить у базі, тож обхід
    диска тут зайвий — а на тисячах файлів він коштував секунди."""
    row = get_connection().execute(
        "SELECT COALESCE(SUM(size_bytes), 0) AS n FROM items WHERE stored_path IS NOT NULL"
    ).fetchone()
    return int(row["n"])


def list_frames(item_id: int) -> list[sqlite3.Row]:
    return get_connection().execute(
        "SELECT * FROM frames WHERE item_id = ? ORDER BY ts_s", (item_id,)
    ).fetchall()


def get_frame(frame_id: int) -> sqlite3.Row | None:
    return get_connection().execute(
        "SELECT * FROM frames WHERE id = ?", (frame_id,)
    ).fetchone()


def add_frame(item_id: int, ts_s: float, path: str) -> int:
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO frames (item_id, ts_s, path) VALUES (?, ?, ?)",
        (item_id, ts_s, path),
    )
    conn.commit()
    return int(cursor.lastrowid)


# --- вектори --------------------------------------------------------------


def clear_embeddings(item_id: int, space: str) -> None:
    conn = get_connection()
    table = vec_table(space)
    rows = conn.execute(
        "SELECT id, vec_rowid FROM embeddings WHERE item_id = ? AND space = ?",
        (item_id, space),
    ).fetchall()
    for row in rows:
        conn.execute(f"DELETE FROM {table} WHERE rowid = ?", (row["vec_rowid"],))  # noqa: S608
        # Повнотекстовий індекс живе окремою таблицею й каскадів не знає.
        conn.execute("DELETE FROM chunk_fts WHERE rowid = ?", (row["id"],))
    conn.execute(
        "DELETE FROM embeddings WHERE item_id = ? AND space = ?", (item_id, space)
    )
    conn.commit()


def add_embedding(
    item_id: int,
    space: str,
    vector: Sequence[float] | np.ndarray,
    *,
    frame_id: int | None = None,
    chunk_ix: int | None = None,
    chunk_text: str | None = None,
    ts_s: float | None = None,
) -> int:
    conn = get_connection()
    table = vec_table(space)
    cursor = conn.execute(
        f"INSERT INTO {table}(embedding) VALUES (?)",  # noqa: S608 — назва з білого списку
        (serialize(np.asarray(vector, dtype=np.float32).ravel().tolist()),),
    )
    vec_rowid = int(cursor.lastrowid)
    cursor = conn.execute(
        """INSERT INTO embeddings (item_id, space, frame_id, chunk_ix, chunk_text,
                                   ts_s, vec_rowid)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (item_id, space, frame_id, chunk_ix, chunk_text, ts_s, vec_rowid),
    )
    embedding_id = int(cursor.lastrowid)

    # Той самий фрагмент потрапляє і в повнотекстовий індекс — щоб пошук умів
    # знаходити конкретну фразу, а не лише схожий за змістом запис.
    if space == TEXT_SPACE and chunk_text:
        conn.execute(
            "INSERT INTO chunk_fts(rowid, chunk_text) VALUES (?, ?)",
            (embedding_id, chunk_text),
        )

    conn.commit()
    return vec_rowid


# --- теги -----------------------------------------------------------------


def list_tags() -> list[sqlite3.Row]:
    return get_connection().execute(
        """SELECT t.id, t.name, COUNT(it.item_id) AS usage_count
           FROM tags t LEFT JOIN item_tags it ON it.tag_id = t.id
           GROUP BY t.id ORDER BY t.name COLLATE NOCASE"""
    ).fetchall()


def create_tag(name: str) -> sqlite3.Row:
    conn = get_connection()
    conn.execute(
        "INSERT INTO tags (name, created_at) VALUES (?, ?)", (name.strip(), _now())
    )
    conn.commit()
    return conn.execute("SELECT * FROM tags WHERE name = ?", (name.strip(),)).fetchone()


def rename_tag(tag_id: int, name: str) -> None:
    conn = get_connection()
    conn.execute("UPDATE tags SET name = ? WHERE id = ?", (name.strip(), tag_id))
    conn.commit()


def delete_tag(tag_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    conn.commit()


def tags_for_item(item_id: int) -> list[str]:
    rows = get_connection().execute(
        """SELECT t.name FROM tags t
           JOIN item_tags it ON it.tag_id = t.id
           WHERE it.item_id = ? ORDER BY t.name COLLATE NOCASE""",
        (item_id,),
    ).fetchall()
    return [row["name"] for row in rows]


def set_item_tags(item_id: int, names: Sequence[str]) -> None:
    """Проставляє теги запису. Теги беруться лише з наявного словника —
    довільні на льоту не створюються."""
    conn = get_connection()
    conn.execute("DELETE FROM item_tags WHERE item_id = ?", (item_id,))
    for name in names:
        row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if row is not None:
            conn.execute(
                "INSERT OR IGNORE INTO item_tags (item_id, tag_id) VALUES (?, ?)",
                (item_id, row["id"]),
            )
    conn.commit()


# --- задачі ---------------------------------------------------------------


def create_job(item_id: int | None, job_type: str) -> int:
    conn = get_connection()
    now = _now()
    cursor = conn.execute(
        """INSERT INTO jobs (item_id, type, status, progress, created_at, updated_at)
           VALUES (?, ?, 'queued', 0, ?, ?)""",
        (item_id, job_type, now, now),
    )
    conn.commit()
    return int(cursor.lastrowid)


def update_job(job_id: int, **fields: Any) -> None:
    fields["updated_at"] = _now()
    conn = get_connection()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(
        f"UPDATE jobs SET {assignments} WHERE id = ?",  # noqa: S608 — ключі з коду
        (*fields.values(), job_id),
    )
    conn.commit()


def next_queued_job() -> sqlite3.Row | None:
    return get_connection().execute(
        "SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1"
    ).fetchone()


def list_jobs(limit: int = 100) -> list[sqlite3.Row]:
    return get_connection().execute(
        """SELECT j.*, i.kind, i.label, i.stored_path
           FROM jobs j LEFT JOIN items i ON i.id = j.item_id
           ORDER BY
             CASE j.status WHEN 'running' THEN 0 WHEN 'failed' THEN 1
                           WHEN 'queued' THEN 2 ELSE 3 END,
             j.id
           LIMIT ?""",
        (limit,),
    ).fetchall()


def job_counts() -> dict[str, int]:
    rows = get_connection().execute(
        "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
    ).fetchall()
    return {row["status"]: int(row["n"]) for row in rows}


def clear_done_jobs() -> int:
    conn = get_connection()
    cursor = conn.execute("DELETE FROM jobs WHERE status = 'done'")
    conn.commit()
    return cursor.rowcount


def requeue_all() -> int:
    """Створює задачу на повторну обробку для кожного запису."""
    conn = get_connection()
    rows = conn.execute("SELECT id, kind FROM items ORDER BY id").fetchall()
    now = _now()
    for row in rows:
        conn.execute(
            """INSERT INTO jobs (item_id, type, status, progress, created_at, updated_at)
               VALUES (?, ?, 'queued', 0, ?, ?)""",
            (row["id"], row["kind"], now, now),
        )
        conn.execute("UPDATE items SET status = 'pending' WHERE id = ?", (row["id"],))
    conn.commit()
    return len(rows)


def reset_running_jobs() -> None:
    """Задачі, що лишилися 'running' після падіння, повертаються в чергу."""
    conn = get_connection()
    conn.execute("UPDATE jobs SET status = 'queued', progress = 0 WHERE status = 'running'")
    conn.commit()
