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
    cleaned = export.export_item(item, denoise=True, target_dir=tmp_path)

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
    assert noise_floor(cleaned) < noise_floor(original) - 5, "шум має помітно впасти"


def test_reveal_of_missing_file_is_false(tmp_path):
    assert export.reveal(tmp_path / "немає.mp3") is False
