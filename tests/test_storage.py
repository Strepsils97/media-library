from pathlib import Path

import pytest

from backend.app.ingest import storage

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_default_label_from_path():
    assert storage.default_label(path=Path("a/b/cat_window.jpg")) == "cat_window"


def test_default_label_from_text_truncates():
    text = " ".join(f"слово{i}" for i in range(20))
    label = storage.default_label(text=text, words=8)
    assert label.endswith("…")
    assert len(label.split()) == 8


def test_default_label_short_text_not_truncated():
    assert storage.default_label(text="коротко") == "коротко"


def test_detect_kind():
    assert storage.detect_kind(Path("x.jpg")) == "image"
    assert storage.detect_kind(Path("x.MP4")) == "video"
    assert storage.detect_kind(Path("x.mp3")) == "audio"
    assert storage.detect_kind(Path("x.md")) == "text"
    with pytest.raises(storage.UnsupportedFile):
        storage.detect_kind(Path("x.exe"))


def test_prepare_text():
    prepared = storage.prepare_text("  Нотатка про податки і все таке  ")
    assert prepared.kind == "text"
    assert prepared.stored_path is None
    assert prepared.text_content.startswith("Нотатка")
    assert prepared.label.startswith("Нотатка")


def test_prepare_text_rejects_empty():
    with pytest.raises(storage.UnsupportedFile):
        storage.prepare_text("   ")


@pytest.mark.skipif(not (SAMPLES / "images").exists(), reason="немає семплів")
def test_prepare_image_copies_and_thumbnails(library):
    source = next((SAMPLES / "images").iterdir())
    prepared = storage.prepare_file(source)

    assert prepared.kind == "image"
    assert prepared.width and prepared.height
    assert prepared.label == source.stem

    stored = library.originals_dir / prepared.stored_path
    assert stored.exists()
    assert stored.stat().st_size == source.stat().st_size

    thumb_rel = storage.make_thumbnail(stored, prepared.content_hash)
    thumb = library.thumbs_dir / thumb_rel
    assert thumb.exists()
    assert thumb.stat().st_size < source.stat().st_size


@pytest.mark.skipif(not (SAMPLES / "images").exists(), reason="немає семплів")
def test_same_file_twice_is_deduplicated(library):
    source = next((SAMPLES / "images").iterdir())
    first = storage.prepare_file(source)
    second = storage.prepare_file(source)
    assert first.content_hash == second.content_hash
    assert first.stored_path == second.stored_path
