import pytest

from backend.app import config


@pytest.fixture
def library(tmp_path, monkeypatch):
    """Ізольована бібліотека на час тесту."""
    settings = config.Settings(data_dir=tmp_path / "data")
    settings.ensure_dirs()
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    # Модулі імпортують get_settings напряму, тому підміняємо і в них.
    from backend.app.db import connection
    from backend.app.ingest import storage

    monkeypatch.setattr(connection, "get_settings", lambda: settings)
    monkeypatch.setattr(storage, "get_settings", lambda: settings)

    from backend.app import settings_store

    monkeypatch.setattr(settings_store, "get_settings", lambda: settings)
    monkeypatch.setattr(settings_store, "_extra", {"theme": "dark"})

    # Жоден тест не має вантажити справжні ваги: це гігабайти й хвилини.
    from backend.app.ml import registry

    registry.use_stubs()

    # З'єднання кешується в потоко-локальному сховищі, тож без скидання
    # наступний тест працював би з базою попереднього.
    _close_connection(connection)
    yield settings
    _close_connection(connection)
    registry.reset()


def _close_connection(connection) -> None:
    conn = getattr(connection._local, "conn", None)
    if conn is not None:
        conn.close()
        del connection._local.conn
