import pytest

from backend.app import config


@pytest.fixture
def library(tmp_path, monkeypatch):
    """Ізольована бібліотека на час тесту.

    Налаштування підміняються через змінну оточення й скидання кешу, а не
    помодульним monkeypatch: модулі беруть `get_settings` до себе при імпорті,
    тож патчити довелося б кожен окремо — і кожен новий модуль мовчки писав би
    у справжню теку даних, доки хтось це не помітить.
    """
    monkeypatch.setenv("MEDIALIB_DATA_DIR", str(tmp_path / "data"))
    config.get_settings.cache_clear()

    settings = config.get_settings()
    settings.ensure_dirs()
    assert settings.data_dir == tmp_path / "data", "тест не має чіпати справжню бібліотеку"

    from backend.app import settings_store
    from backend.app.db import connection
    from backend.app.ml import registry

    monkeypatch.setattr(settings_store, "_extra", {"theme": "dark"})

    # Жоден тест не має вантажити справжні ваги: це гігабайти й хвилини.
    registry.use_stubs()

    # З'єднання кешується в потоко-локальному сховищі, тож без скидання
    # наступний тест працював би з базою попереднього.
    _close_connection(connection)
    yield settings
    _close_connection(connection)
    registry.reset()
    config.get_settings.cache_clear()


def _close_connection(connection) -> None:
    conn = getattr(connection._local, "conn", None)
    if conn is not None:
        conn.close()
        del connection._local.conn
