"""Обробка запису: ембедінги, кадри, транскрибція."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from ..config import get_settings
from ..db import repo
from ..ml import asr
from ..ml.registry import get_image_embedder, get_text_embedder
from . import frames as frames_mod
from . import storage
from .text import chunk_segments, chunk_text

log = logging.getLogger(__name__)


def _embed_image_file(item_id: int, path: Path, frame_id: int | None, ts_s: float | None) -> None:
    with Image.open(path) as image:
        vector = get_image_embedder().encode_images([image.convert("RGB")])[0]
    repo.add_embedding(item_id, "image", vector, frame_id=frame_id, ts_s=ts_s)


def index_text(item_id: int, text: str, *, from_transcript_segments=None) -> None:
    """Будує текстові вектори запису. Повністю перебудовує — виклик після
    правки транскрипції має замінити старі вектори, а не додати до них."""
    repo.clear_embeddings(item_id, "text")

    chunks = (
        chunk_segments(from_transcript_segments)
        if from_transcript_segments
        else chunk_text(text)
    )
    if not chunks:
        return

    vectors = get_text_embedder().encode_texts([c.text for c in chunks])
    for chunk, vector in zip(chunks, vectors, strict=True):
        repo.add_embedding(
            item_id, "text", vector,
            chunk_ix=chunk.index, chunk_text=chunk.text, ts_s=chunk.ts_s,
        )


def process_image(item_id: int) -> None:
    settings = get_settings()
    item = repo.get_item(item_id)
    assert item is not None
    path = settings.originals_dir / item["stored_path"]

    storage.make_thumbnail(path, item["content_hash"])
    repo.clear_embeddings(item_id, "image")
    _embed_image_file(item_id, path, frame_id=None, ts_s=None)


def process_text(item_id: int) -> None:
    item = repo.get_item(item_id)
    assert item is not None
    index_text(item_id, item["text_content"] or "")


def process_audio(item_id: int, on_progress=None) -> None:
    settings = get_settings()
    item = repo.get_item(item_id)
    assert item is not None
    path = settings.originals_dir / item["stored_path"]

    transcript = asr.transcribe(path, on_progress=on_progress)
    repo.update_item(
        item_id,
        transcript=transcript.text,
        transcript_lang=transcript.language,
    )
    # Лейбл лишається детермінованим: перші слова транскрипції, якщо
    # користувач ще не правив назву вручну.
    if item["label"] == Path(item["stored_path"]).stem and transcript.text:
        repo.update_item(item_id, label=storage.default_label(text=transcript.text))

    index_text(item_id, transcript.text, from_transcript_segments=transcript.segments)


def process_video(item_id: int, on_progress=None) -> None:
    settings = get_settings()
    item = repo.get_item(item_id)
    assert item is not None
    path = settings.originals_dir / item["stored_path"]

    repo.clear_embeddings(item_id, "image")
    timestamps = frames_mod.pick_timestamps(path, item["duration_s"])
    saved = frames_mod.extract(path, timestamps, item["content_hash"])

    for ts, relative in saved:
        frame_id = repo.add_frame(item_id, ts, relative)
        _embed_image_file(item_id, settings.frames_dir / relative, frame_id, ts)

    if on_progress:
        on_progress(0.3)

    try:
        process_audio(item_id, on_progress=lambda p: on_progress(0.3 + 0.7 * p) if on_progress else None)
    except asr.NoAudioTrack:
        # Німе відео — не помилка обробки: запис лишається знайденим по кадрах.
        log.info("Відео %s без звукової доріжки — індексуємо лише кадри", item_id)
        raise


PROCESSORS = {
    "image": process_image,
    "text": process_text,
    "audio": process_audio,
    "video": process_video,
}
