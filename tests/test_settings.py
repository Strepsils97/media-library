import json

import pytest

from backend.app import settings_store


def test_defaults_are_exposed(library):
    current = settings_store.current()
    assert current["asr_model"] == "large-v3-turbo"
    assert current["theme"] == "dark"
    assert "cuda" in current["available"]["devices"]


def test_update_persists_to_disk(library):
    settings_store.update({"asr_model": "small", "theme": "light"})
    stored = json.loads((library.data_dir / "settings.json").read_text(encoding="utf-8"))
    assert stored["asr_model"] == "small"
    assert stored["theme"] == "light"


def test_update_applies_immediately(library):
    settings_store.update({"max_frames_per_video": 4})
    assert library.max_frames_per_video == 4


def test_rejects_unknown_values(library):
    with pytest.raises(ValueError):
        settings_store.update({"device": "quantum"})
    with pytest.raises(ValueError):
        settings_store.update({"asr_model": "gigantic"})


def test_ignores_fields_outside_whitelist(library):
    # Шляхи не мають змінюватися через HTTP.
    original = library.data_dir
    settings_store.update({"data_dir": "C:/somewhere-else"})
    assert library.data_dir == original


def test_load_survives_broken_file(library):
    (library.data_dir / "settings.json").write_text("{ не json", encoding="utf-8")
    settings_store.load()  # не має кидати
    assert settings_store.current()["asr_model"]
