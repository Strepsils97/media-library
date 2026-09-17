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


def test_api_accepts_every_editable_field():
    """Модель запиту має знати всі поля, які дозволено міняти.

    Поле, якого немає в SettingsPatch, pydantic викидає мовчки — ще до
    білого списку. Саме так тека для завантажень була скрізь, крім моделі
    запиту, і перемикач у налаштуваннях не робив нічого: ні помилки, ні
    ефекту. Два переліки в різних файлах розходяться легко, тож нехай за
    цим стежить тест, а не пам'ять.
    """
    from backend.app.api.routes import SettingsPatch

    assert settings_store.EDITABLE <= set(SettingsPatch.model_fields)


def test_download_dir_must_exist(library, tmp_path):
    settings_store.update({"download_dir": str(tmp_path)})
    assert library.download_dir == str(tmp_path)

    # Неіснуючу теку приймати не можна: збереження мовчки пішло б у стандартну.
    with pytest.raises(ValueError):
        settings_store.update({"download_dir": str(tmp_path / "нема-такої")})

    # Порожнє значення — повернення до стандартної теки завантажень.
    settings_store.update({"download_dir": ""})
    assert library.download_dir == ""
