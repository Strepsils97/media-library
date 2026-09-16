"""Експорт назовні: зрозуміла назва, збережений оригінал, очищений звук."""

import subprocess
from pathlib import Path

import pytest

from backend.app.db import repo
from backend.app.db.connection import init_db
from backend.app.ingest import export
from backend.app.ingest.storage import Prepared

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def _item(library, kind: str, name: str, label: str) -> dict:
    init_db()
    source = SAMPLES / ("audio" if kind != "image" else "images") / name
    # Семпли не в репозиторії — це чужі записи. Без них тест не має що
    # перевіряти, і чесніше пропустити його, ніж падати з FileNotFoundError.
    if not source.exists():
        pytest.skip(f"немає семпла {source.name}")
    stored = Path("ab") / name
    target = library.originals_dir / stored
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())

    item_id = repo.create_item(
        Prepared(kind=kind, label=label, stored_path=stored.as_posix(),
                 source_path=None, content_hash=name, mime=None,
                 size_bytes=target.stat().st_size,
                 created_at="2026-01-01T00:00:00+00:00")
    )
    return repo.get_item(item_id)


def test_safe_name_strips_forbidden_characters():
    # Заборонені у Windows символи замінюються, зайві пробіли схлопуються.
    assert export.safe_name('розмова: "та сама"/2', ".mp3") == "розмова та сама 2.mp3"
    assert export.safe_name("", ".mp3") == "запис.mp3"
    # Назва не має впиратися в межу довжини шляху Windows.
    assert len(export.safe_name("д" * 300, ".mp3")) <= 84


def test_export_of_pasted_text_writes_txt(library, tmp_path):
    init_db()
    item_id = repo.create_item(
        Prepared(kind="text", label="Нотатка про податки", stored_path=None,
                 source_path=None, content_hash="t1", mime="text/plain",
                 size_bytes=1, created_at="2026-01-01T00:00:00+00:00",
                 text_content="вміст нотатки")
    )
    path = export.export_item(repo.get_item(item_id), target_dir=tmp_path)

    assert path.name == "Нотатка про податки.txt"
    assert path.read_text(encoding="utf-8") == "вміст нотатки"


def test_export_without_denoise_is_byte_identical(library, tmp_path):
    item = _item(library, "audio", "1.mp3", "Шукала пароль")
    path = export.export_item(item, denoise=False, target_dir=tmp_path)

    assert path.name == "Шукала пароль.mp3"
    original = library.originals_dir / item["stored_path"]
    assert path.read_bytes() == original.read_bytes(), "без обробки файл має лишитися тим самим"


def test_export_does_not_overwrite(library, tmp_path):
    item = _item(library, "audio", "1.mp3", "Розмова")
    first = export.export_item(item, target_dir=tmp_path)
    second = export.export_item(item, target_dir=tmp_path)

    assert first.exists() and second.exists()
    assert first != second
    assert "(2)" in second.name


@pytest.mark.slow
def test_denoise_lowers_noise_floor(library, tmp_path):
    """Сенс фільтра — саме в цьому, тож перевіряємо вимірюванням, а не оком."""
    item = _item(library, "audio", "1.mp3", "Шукала пароль")
    cleaned = export.export_item(item, denoise="strong", target_dir=tmp_path)

    assert "без шуму" in cleaned.name

    def noise_floor(path: Path) -> float:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "astats=metadata=1:reset=0",
             "-f", "null", "-"],
            capture_output=True, text=True, errors="replace",
        ).stderr
        values = [
            float(line.split(":")[1])
            for line in out.splitlines()
            if "Noise floor dB" in line
        ]
        return values[-1] if values else 0.0

    original = library.originals_dir / item["stored_path"]
    assert noise_floor(cleaned) < noise_floor(original) - 20, "шум має помітно впасти"


def test_reveal_of_missing_file_is_false(tmp_path):
    assert export.reveal(tmp_path / "немає.mp3") is False


def test_download_dir_setting_is_respected(library, tmp_path):
    from backend.app import settings_store

    target = tmp_path / "моя тека"
    target.mkdir()
    settings_store.update({"download_dir": str(target)})

    assert export.default_target_dir() == target

    item = _item(library, "audio", "1.mp3", "Розмова")
    assert export.export_item(item).parent == target


def test_missing_download_dir_falls_back(library, tmp_path):
    from backend.app import settings_store

    # Теку могли видалити або відключити зовнішній диск після вибору.
    gone = tmp_path / "зникла"
    gone.mkdir()
    settings_store.update({"download_dir": str(gone)})
    gone.rmdir()

    fallback = export.default_target_dir()
    assert fallback.is_dir(), "експорт має лишитися можливим"
    assert fallback != gone


def test_denoise_levels_are_ordered_and_capped():
    """Рівні мають зростати, і жоден не має перевищувати заміряну межу.

    Вище 60 сенсу немає: замір показав, що 100 дає той самий рівень шуму,
    але зайве ріже мовлення.
    """
    values = list(export.DENOISE_LEVELS.values())
    assert values == sorted(values), "рівні мають іти від слабшого до сильнішого"
    assert max(values) <= 60
    assert export.DEFAULT_LEVEL in export.DENOISE_LEVELS


def test_unknown_denoise_level_is_rejected(library, tmp_path):
    item = _item(library, "audio", "1.mp3", "Розмова")
    with pytest.raises(export.ExportFailed, match="Невідомий рівень"):
        export.export_item(item, denoise="дуже-сильно", target_dir=tmp_path)


@pytest.mark.slow
def test_denoise_level_changes_result(library, tmp_path):
    """Різні рівні мають давати різний звук — інакше вибір нічого не означає."""
    item = _item(library, "audio", "1.mp3", "Розмова")
    light = export.export_item(item, denoise="light", target_dir=tmp_path)
    strong = export.export_item(item, denoise="strong", target_dir=tmp_path)

    assert light.read_bytes() != strong.read_bytes()


@pytest.mark.slow
def test_preview_is_cached_and_reused(library, tmp_path):
    """Обробка триває секунди — переслухати той самий рівень має бути миттєво."""
    item = _item(library, "audio", "1.mp3", "Розмова")

    first = export.preview_path(item, "light")
    stamp = first.stat().st_mtime_ns
    second = export.preview_path(item, "light")

    assert first == second
    assert second.stat().st_mtime_ns == stamp, "повторний виклик не має переробляти"

    other = export.preview_path(item, "strong")
    assert other != first, "різні рівні — різні файли"


@pytest.mark.slow
def test_audio_export_reuses_preview(library, tmp_path):
    """Завантаження після прослуховування не має рахувати те саме вдруге."""
    item = _item(library, "audio", "1.mp3", "Розмова")
    preview = export.preview_path(item, "strong")

    saved = export.export_item(item, denoise="strong", target_dir=tmp_path)

    assert saved.read_bytes() == preview.read_bytes()
