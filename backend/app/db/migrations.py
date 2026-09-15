"""Міграції бази між версіями застосунку.

Оновлення має зводитися до заміни файлів: тека `data` лишається на місці, а
база сама доводиться до схеми, яку очікує новий код. Тому кожна зміна схеми
додається сюди окремим кроком, а не правкою `schema.sql` заднім числом —
`schema.sql` описує лише те, як виглядає база, створена з нуля.

Правила:

* Версії лише зростають, крок нумерується один раз і більше не змінюється.
* Міграція має бути безпечною на вже наповненій базі: не втрачати записи,
  не падати на даних, яких на момент її написання ще не існувало.
* Якщо зміна робить наявні вектори несумісними (інша модель, інша
  розмірність), міграція чистить вектори й ставить записи в чергу на
  переобробку — але не чіпає ні файли, ні теги, ні виправлені транскрипції.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

log = logging.getLogger(__name__)

# Підвищується разом із додаванням міграції нижче.
SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    description: str
    apply: Callable[[sqlite3.Connection], None]


MIGRATIONS: list[Migration] = [
    # Версія 1 — початкова схема (див. schema.sql). Окремого кроку не
    # потребує: бази цієї версії створюються зі schema.sql як є.
    #
    # Наступні зміни додаються сюди, наприклад:
    # Migration(2, "додано поле items.rating", _add_rating),
]


def _stored_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        return None
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return None


def _set_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(version),),
    )


def _is_fresh(conn: sqlite3.Connection) -> bool:
    """Чи це щойно створена база (а не та, що вже має записи)."""
    row = conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()
    return int(row["n"]) == 0 and _stored_version(conn) is None


def run(conn: sqlite3.Connection) -> int:
    """Доводить базу до SCHEMA_VERSION. Повертає версію, на якій зупинилися."""
    current = _stored_version(conn)

    if current is None:
        # База або щойно створена, або зроблена версією, яка ще не вміла
        # нумерувати схему. В обох випадках вона відповідає версії 1:
        # інших схем у природі не існувало.
        current = 1 if _is_fresh(conn) else 1
        _set_version(conn, current)
        conn.commit()

    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"База зроблена новішою версією застосунку (схема {current}, "
            f"ця версія розуміє {SCHEMA_VERSION}). Оновіть застосунок."
        )

    pending = [m for m in MIGRATIONS if m.version > current]
    for migration in sorted(pending, key=lambda m: m.version):
        log.info("Міграція %s: %s", migration.version, migration.description)
        try:
            migration.apply(conn)
            _set_version(conn, migration.version)
            conn.commit()
        except Exception:
            conn.rollback()
            log.exception("Міграція %s не вдалася", migration.version)
            raise
        current = migration.version

    if current != SCHEMA_VERSION:
        _set_version(conn, SCHEMA_VERSION)
        conn.commit()
        current = SCHEMA_VERSION

    return current


def rebuild_vector_space(
    conn: sqlite3.Connection, space: str, dim: int, reason: str
) -> int:
    """Перестворює векторну таблицю під нову розмірність і ставить записи в чергу.

    Використовується, коли нова версія приходить з іншою моделлю ембедінгу:
    старі вектори в новому просторі не мають сенсу, але все інше — файли,
    теги, виправлені транскрипції — має пережити оновлення.
    """
    table = {"image": "vec_image", "text": "vec_text"}[space]

    conn.execute(f"DROP TABLE IF EXISTS {table}")  # noqa: S608 — білий список вище
    conn.execute(
        f"CREATE VIRTUAL TABLE {table} USING vec0(embedding float[{dim}])"  # noqa: S608
    )
    conn.execute("DELETE FROM embeddings WHERE space = ?", (space,))
    # Калібрування рахувалося на старих векторах — воно більше ні про що.
    conn.execute("DELETE FROM score_calibration WHERE space = ?", (space,))

    now = datetime.now(UTC).isoformat()
    rows = conn.execute("SELECT id, kind FROM items").fetchall()
    for row in rows:
        conn.execute(
            """INSERT INTO jobs (item_id, type, status, progress, created_at, updated_at)
               VALUES (?, ?, 'queued', 0, ?, ?)""",
            (row["id"], row["kind"], now, now),
        )
        conn.execute("UPDATE items SET status = 'pending' WHERE id = ?", (row["id"],))

    log.warning(
        "Простір «%s» перебудовано (%s). У черзі на переобробку: %d",
        space, reason, len(rows),
    )
    return len(rows)
