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

# Векторні простори та їхні розмірності.
#
# Зображення кодуються двома моделями, а не однією: заміром на реальних файлах
# видно, що вони помиляються на різних запитах, і разом дають 81% Recall@1
# проти 76% у кращої з них поодинці. Розмірність фіксується при створенні
# vec0-таблиці, тож зміна моделі — це завжди міграція.
SPACES: dict[str, int] = {
    "image_a": 1152,  # google/siglip2-so400m-patch16-384
    "image_b": 768,   # nllb-clip-base-siglip
    "text": 768,      # intfloat/multilingual-e5-base
}

IMAGE_SPACES = ("image_a", "image_b")
TEXT_SPACE = "text"

_local = threading.local()


def vec_table(space: str) -> str:
    """Назва векторної таблиці. Заразом — перевірка, що простір відомий:
    ці назви підставляються в SQL, тож приймати довільний рядок не можна."""
    if space not in SPACES:
        raise KeyError(f"Невідомий векторний простір: {space}")
    return f"vec_{space}"


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

    for space, dim in SPACES.items():
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {vec_table(space)} "  # noqa: S608
            f"USING vec0(embedding float[{dim}])"
        )
    conn.commit()

    migrations.run(conn)
    _reconcile_dims(conn)
    conn.commit()
    return conn


def _reconcile_dims(conn: sqlite3.Connection) -> None:
    """Звіряє розмірності векторів із тими, що очікує код.

    Розмірність фіксується при створенні vec0-таблиці, тож нова версія з
    іншою моделлю ембедінгу не змогла б із нею працювати. Замість того щоб
    відмовитися стартувати, простір перебудовується, а записи стають у чергу
    на переобробку: файли, теги й виправлені транскрипції лишаються цілими.
    """
    for space, dim in SPACES.items():
        key = f"{space}_dim"
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)", (key, str(dim)))
            continue
        if row["value"] == str(dim):
            continue

        migrations.rebuild_vector_space(
            conn, space, dim, reason=f"розмірність змінилася з {row['value']} на {dim}"
        )
        conn.execute("UPDATE meta SET value = ? WHERE key = ?", (str(dim), key))


# Стеля SQLite на кількість параметрів у запиті — 32766; лишаємо запас на
# решту прив'язок.
_MAX_IN_PARAMS = 30000


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
    table = vec_table(space)
    blob = serialize(query)

    def run(chunk: list[int] | None) -> list[sqlite3.Row]:
        # vec0 не бачить `LIMIT ?`, переданий як параметр, і вимагає явного `k`.
        params: list[object] = [blob, limit]
        clause = ""
        if chunk is not None:
            clause = f" AND rowid IN ({','.join('?' * len(chunk))})"
            params.extend(chunk)
        sql = (
            f"SELECT rowid, distance FROM {table} "  # noqa: S608 — назва з білого списку
            f"WHERE embedding MATCH ? AND k = ?{clause} ORDER BY distance"
        )
        return conn.execute(sql, params).fetchall()

    if restrict_to is None:
        return run(None)

    rowids = list(restrict_to)
    if not rowids:
        return []
    if len(rowids) <= _MAX_IN_PARAMS:
        return run(rowids)

    # Довгий список не влазить у запит: у SQLite є стеля на кількість
    # параметрів, і на бібліотеці з тисяч відео фільтр по типу об неї спотикався.
    # Найближчі сусіди підмножини — це найкращі з найближчих сусідів її частин,
    # тож розбиваємо на шматки й зливаємо результати.
    found: list[sqlite3.Row] = []
    for start in range(0, len(rowids), _MAX_IN_PARAMS):
        found.extend(run(rowids[start : start + _MAX_IN_PARAMS]))
    found.sort(key=lambda row: row["distance"])
    return found[:limit]


def similarities(
    conn: sqlite3.Connection, space: str, query: Sequence[float], vec_rowids: Iterable[int]
) -> dict[int, float]:
    """Точна косинусна схожість для конкретних векторів.

    Потрібна, коли кандидат потрапив у видачу однієї моделі, але не втрапив у
    межі kNN іншої: без цього його оцінка в другому просторі була б невідома,
    і середнє по ансамблю вийшло б заниженим.
    """
    rowids = list(vec_rowids)
    if not rowids:
        return {}

    import numpy as np

    table = vec_table(space)
    query_vec = np.asarray(query, dtype=np.float32)
    result: dict[int, float] = {}

    # Порціями: sqlite має межу на кількість параметрів у запиті.
    for start in range(0, len(rowids), 400):
        chunk = rowids[start : start + 400]
        rows = conn.execute(
            f"SELECT rowid, embedding FROM {table} "  # noqa: S608 — назва з білого списку
            f"WHERE rowid IN ({','.join('?' * len(chunk))})",
            chunk,
        ).fetchall()
        for row in rows:
            vector = np.frombuffer(row["embedding"], dtype=np.float32)
            result[int(row["rowid"])] = float(query_vec @ vector)

    return result
