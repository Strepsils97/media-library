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
    return settings
