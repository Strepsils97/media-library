"""Оновлення застосунку: заміна файлів не має коштувати даних."""

import sqlite3

import pytest

from backend.app.db import connection as db
from backend.app.db import migrations, repo
from backend.app.ingest.storage import Prepared


def _seed_item(**overrides) -> int:
    prepared = Prepared(
        kind="audio",
        label="розмова",
        stored_path="ab/abc.mp3",
        source_path=None,
        content_hash="abc",
        mime="audio/mpeg",
        size_bytes=10,
        created_at="2026-01-01T00:00:00+00:00",
        duration_s=12.0,
        **overrides,
    )
    return repo.create_item(prepared)


def test_fresh_database_is_stamped(library):
    conn = db.init_db()
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    assert int(row["value"]) == migrations.SCHEMA_VERSION


def test_init_is_idempotent(library):
    db.init_db()
    item_id = _seed_item()
    db.init_db()
    db.init_db()
    assert repo.get_item(item_id) is not None
    assert repo.count_items() == 1


def test_unknown_future_schema_refuses_to_start(library):
    conn = db.init_db()
    conn.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")
    conn.commit()
    with pytest.raises(RuntimeError, match="новішою версією"):
        migrations.run(conn)


def test_dimension_change_rebuilds_without_losing_data(library, monkeypatch):
    """Нова модель ембедінгу приходить з іншою розмірністю.

    Це найпоширеніший сценарій оновлення, і найнебезпечніший: старі вектори
    стають безглуздими, але все, що людина зробила руками, має вціліти.
    """
    conn = db.init_db()
    item_id = _seed_item()
    repo.update_item(
        item_id, transcript="виправлений людиною текст", transcript_edited=1
    )
    repo.create_tag("важливе")
    repo.set_item_tags(item_id, ["важливе"])
    repo.add_embedding(item_id, "text", [0.1] * db.TEXT_DIM, chunk_ix=0, chunk_text="x")
    repo.clear_done_jobs()

    assert conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"] == 1

    # Нова версія застосунку з іншим текстовим ембедером.
    monkeypatch.setattr(db, "TEXT_DIM", 384)
    db.init_db(conn)

    item = repo.get_item(item_id)
    assert item is not None, "запис не має зникнути"
    assert item["transcript"] == "виправлений людиною текст", "правки мають вціліти"
    assert repo.tags_for_item(item_id) == ["важливе"], "теги мають вціліти"
    assert item["stored_path"] == "ab/abc.mp3", "посилання на файл має вціліти"

    assert conn.execute(
        "SELECT COUNT(*) AS n FROM embeddings WHERE space = 'text'"
    ).fetchone()["n"] == 0, "несумісні вектори мають зникнути"

    queued = conn.execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE status = 'queued'"
    ).fetchone()["n"]
    assert queued == 1, "запис має стати в чергу на переобробку"

    # Нова таблиця справді приймає вектори нової розмірності.
    repo.add_embedding(item_id, "text", [0.2] * 384, chunk_ix=0, chunk_text="y")
    with pytest.raises(sqlite3.OperationalError):
        repo.add_embedding(item_id, "text", [0.2] * 768, chunk_ix=1, chunk_text="z")


def test_unchanged_dimensions_keep_vectors(library):
    conn = db.init_db()
    item_id = _seed_item()
    repo.add_embedding(item_id, "text", [0.1] * db.TEXT_DIM, chunk_ix=0, chunk_text="x")

    db.init_db(conn)

    assert conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"] == 1


def test_pending_migration_runs_once_and_keeps_data(library, monkeypatch):
    """Повний шлях оновлення: нова версія приносить крок, база доганяє схему."""
    conn = db.init_db()
    item_id = _seed_item()
    repo.create_tag("збережи")
    repo.set_item_tags(item_id, ["збережи"])

    applied: list[int] = []

    def add_column(connection):
        applied.append(2)
        connection.execute("ALTER TABLE items ADD COLUMN rating INTEGER")

    monkeypatch.setattr(migrations, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(
        migrations,
        "MIGRATIONS",
        [migrations.Migration(2, "додано items.rating", add_column)],
    )

    assert migrations.run(conn) == 2
    assert applied == [2], "міграція має відпрацювати рівно раз"

    # Дані на місці, нова колонка теж.
    assert repo.get_item(item_id)["rating"] is None
    assert repo.tags_for_item(item_id) == ["збережи"]

    # Другий старт нічого не повторює.
    assert migrations.run(conn) == 2
    assert applied == [2]


def test_failed_migration_rolls_back(library, monkeypatch):
    """Зламаний крок не має лишати базу напівоновленою."""
    conn = db.init_db()
    _seed_item()

    def broken(connection):
        connection.execute("ALTER TABLE items ADD COLUMN half_done INTEGER")
        raise RuntimeError("щось пішло не так")

    monkeypatch.setattr(migrations, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(
        migrations, "MIGRATIONS", [migrations.Migration(2, "зламана", broken)]
    )

    with pytest.raises(RuntimeError, match="щось пішло не так"):
        migrations.run(conn)

    # Версія лишилася старою, тож наступний запуск спробує крок заново.
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    assert int(row["value"]) == 1
