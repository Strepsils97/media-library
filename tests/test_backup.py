"""Резервні копії. Головне — щоб копія відкривалася саме тоді, коли потрібна."""

import sqlite3

import pytest

from backend.app.db import backup, repo
from backend.app.db.connection import get_connection, init_db
from backend.app.ingest.storage import Prepared


def _seed(label: str = "запис", content_hash: str = "h1") -> int:
    return repo.create_item(
        Prepared(kind="text", label=label, stored_path=None, source_path=None,
                 content_hash=content_hash, mime="text/plain", size_bytes=1,
                 created_at="2026-01-01T00:00:00+00:00", text_content="текст")
    )


def test_backup_of_empty_library_is_skipped(library):
    assert backup.create("test") is None


def test_backup_captures_data_and_verifies(library):
    init_db()
    _seed()
    created = backup.create("test")

    assert created is not None
    assert created.reason == "test"
    assert backup.verify(created.path)

    conn = sqlite3.connect(f"file:{created.path}?mode=ro", uri=True)
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
    conn.close()


def test_backup_is_consistent_with_open_writes(library):
    """Копія знімається з живої бази — саме тому не копіюванням файлу."""
    init_db()
    _seed()
    # Незавершена транзакція в іншому підключенні не має потрапити в копію.
    other = sqlite3.connect(library.db_path)
    other.execute("BEGIN")
    other.execute(
        "INSERT INTO tags (name, created_at) VALUES ('незавершений', '2026-01-01')"
    )

    created = backup.create("test")
    other.rollback()
    other.close()

    assert created is not None
    conn = sqlite3.connect(f"file:{created.path}?mode=ro", uri=True)
    names = [r[0] for r in conn.execute("SELECT name FROM tags")]
    conn.close()
    assert "незавершений" not in names


def test_prune_keeps_newest(library):
    init_db()
    _seed()
    for index in range(4):
        backup.create(f"test{index}")

    before = len(backup.listing())
    removed = backup.prune(keep=2)

    assert removed == before - 2
    remaining = backup.listing()
    assert len(remaining) == 2
    # Лишитися мають саме найсвіжіші.
    assert remaining[0].created_at >= remaining[1].created_at


def test_restore_is_deferred_until_restart(library):
    init_db()
    _seed(label="до копії")
    created = backup.create("test")
    assert created is not None

    _seed(label="після копії", content_hash="h2")
    assert repo.count_items() == 2

    backup.schedule_restore(created.name)
    # Жива база не чіпається, поки застосунок працює.
    assert repo.count_items() == 2
    assert backup.pending_restore() is not None
    # Людина має бачити, що саме буде відновлено, а не службову назву файлу.
    assert backup.pending_restore_source() == created.name


def test_restore_applies_on_next_start(library):
    init_db()
    _seed(label="до копії")
    created = backup.create("test")
    _seed(label="після копії", content_hash="h2")
    backup.schedule_restore(created.name)

    # Імітуємо перезапуск: закриваємо підключення й застосовуємо відкладене.
    get_connection().close()
    from backend.app.db import connection

    del connection._local.conn

    assert backup.apply_pending_restore() is True
    init_db()

    labels = [r["label"] for r in get_connection().execute("SELECT label FROM items")]
    assert labels == ["до копії"], "має лишитися стан із копії"
    # Попередня база не викидається: відкотитися має бути до чого.
    assert (library.data_dir / "replaced-before-restore.db").exists()


def test_restore_refuses_broken_backup(library):
    init_db()
    _seed()
    created = backup.create("test")
    assert created is not None
    created.path.write_bytes("це вже не база".encode())

    with pytest.raises(ValueError, match="пошкоджена"):
        backup.schedule_restore(created.name)


def test_cancel_restore(library):
    init_db()
    _seed()
    created = backup.create("test")
    backup.schedule_restore(created.name)

    assert backup.cancel_restore() is True
    assert backup.pending_restore() is None
    assert backup.pending_restore_source() is None
    assert backup.apply_pending_restore() is False
