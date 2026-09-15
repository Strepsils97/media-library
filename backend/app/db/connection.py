"""Підключення до SQLite з підвантаженим sqlite-vec."""

from __future__ import annotations

import sqlite3
import struct
import threading
from collections.abc import Iterable, Sequence
from pathlib import Path

import sqlite_vec

from ..config import get_settings
from . import migrations

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Розмірності векторів. Фіксуються при створенні vec0-таблиць, тому зміна
# моделі вимагає переіндексації — ці значення записуються у meta, і
# невідповідність виявляється при старті.
IMAGE_DIM = 1024  # siglip2-large-patch16-256
TEXT_DIM = 768   # multilingual-e5-base

_local = threading.local()


def serialize(vector: Sequence[float]) -> bytes:
    """Вектор -> компактне подання, яке очікує sqlite-vec."""
    return struct.pack(f"{len(vector)}f", *vector)


def deserialize(blob: bytes) -> tuple[float, ...]:
    return struct.unpack(f"{len(blob) // 4}f", blob)


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    settings = get_settings()
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_connection() -> sqlite3.Connection:
    """Одне підключення на потік.

    Воркер і HTTP-обробники ходять у базу з різних потоків, а об'єкт
    sqlite3.Connection не призначений для одночасного використання кількома.
    """
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = connect()
        _local.conn = conn
    return conn


def init_db(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    """Готує базу до роботи: схема, міграції, векторні таблиці.

    Викликається на кожному старті. Оновлення застосунку зводиться до заміни
    файлів: тека з даними лишається на місці, а база доводиться тут до того
    стану, якого очікує новий код.
    """
    conn = conn or get_connection()
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))

    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_image USING vec0(embedding float[{IMAGE_DIM}])"
    )
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_text USING vec0(embedding float[{TEXT_DIM}])"
    )
    conn.commit()

    migrations.run(conn)
    _reconcile_dims(conn)
    conn.commit()
    return conn


def _reconcile_dims(conn: sqlite3.Connection) -> None:
    """Звіряє розмірності векторів із тими, що очікує код.

    Розмірність фіксується при створенні vec0-таблиці, тож нова версія з
    іншою моделлю ембедінгу не змогла б із нею працювати. Раніше це було
    фатальною помилкою — застосунок просто не стартував. Тепер простір
    перебудовується, а записи стають у чергу на переобробку: файли, теги й
    виправлені транскрипції при цьому лишаються цілими.
    """
    for key, space, dim in (
        ("image_dim", "image", IMAGE_DIM),
        ("text_dim", "text", TEXT_DIM),
    ):
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?)", (key, str(dim))
            )
            continue

        if row["value"] == str(dim):
            continue

        migrations.rebuild_vector_space(
            conn, space, dim,
            reason=f"розмірність змінилася з {row['value']} на {dim}",
        )
        conn.execute(
            "UPDATE meta SET value = ? WHERE key = ?", (str(dim), key)
        )


def knn(
    conn: sqlite3.Connection,
    space: str,
    query: Sequence[float],
    limit: int,
    restrict_to: Iterable[int] | None = None,
) -> list[sqlite3.Row]:
    """kNN у вказаному просторі, за потреби — обмежений набором rowid.

    Обмеження по rowid дозволяє застосувати фільтри (тип, дата, теги) до того,
    як рахується схожість, а не відсіювати вже знайдене.
    """
    table = {"image": "vec_image", "text": "vec_text"}[space]
    # vec0 не бачить `LIMIT ?`, переданий як параметр, і вимагає явного `k`.
    params: list[object] = [serialize(query), limit]
    clause = ""

    if restrict_to is not None:
        rowids = list(restrict_to)
        if not rowids:
            return []
        clause = f" AND rowid IN ({','.join('?' * len(rowids))})"
        params.extend(rowids)

    sql = (
        f"SELECT rowid, distance FROM {table} "  # noqa: S608 — таблиця з білого списку вище
        f"WHERE embedding MATCH ? AND k = ?{clause} ORDER BY distance"
    )
    return conn.execute(sql, params).fetchall()
