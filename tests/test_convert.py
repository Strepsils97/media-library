"""Переганяння форматів: чужа тека, чужі файли, бібліотека не при справах."""

import subprocess

import pytest

from backend.app.ingest import convert
from backend.app.ingest.media_tools import ffmpeg


def _tone(path, seconds: float = 0.5) -> None:
    subprocess.run(
        [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", str(path)],
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "голосове.ogg"
    _tone(path)
    return path


@pytest.mark.slow
def test_converts_to_mp3(source, tmp_path):
    out = tmp_path / "готове"
    target = convert.convert_file(source, out, "mp3")
    assert target.suffix == ".mp3"
    assert target.parent == out
    assert target.stat().st_size > 0
    # Оригінал лишається на місці: це перегін, а не переміщення.
    assert source.exists()


@pytest.mark.slow
def test_keeps_the_name(source, tmp_path):
    target = convert.convert_file(source, tmp_path / "out", "mp3")
    assert target.stem == "голосове"


@pytest.mark.slow
def test_does_not_overwrite(source, tmp_path):
    out = tmp_path / "out"
    first = convert.convert_file(source, out, "mp3")
    second = convert.convert_file(source, out, "mp3")
    assert first != second
    assert first.exists() and second.exists()


@pytest.mark.slow
def test_batch_survives_a_bad_file(source, tmp_path):
    broken = tmp_path / "не-звук.ogg"
    broken.write_text("це не аудіо", encoding="utf-8")

    results = convert.convert_many([source, broken], "mp3", target_dir=tmp_path / "out")
    assert len(results) == 2
    good = [r for r in results if not r.error]
    bad = [r for r in results if r.error]
    # Один зіпсований файл не забирає із собою решту пачки.
    assert len(good) == 1 and len(bad) == 1


def test_rejects_unknown_format(source, tmp_path):
    with pytest.raises(convert.ConvertFailed):
        convert.convert_file(source, tmp_path, "aiff")
    with pytest.raises(convert.ConvertFailed):
        convert.convert_file(source, tmp_path, "mp3", bitrate="7k")


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(convert.ConvertFailed):
        convert.convert_file(tmp_path / "нема.ogg", tmp_path, "mp3")
