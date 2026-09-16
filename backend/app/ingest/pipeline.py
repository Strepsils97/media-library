"""Обробка запису: ембедінги, кадри, транскрибція."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from ..config import get_settings
from ..db import repo
from ..db.connection import IMAGE_SPACES
from ..ml import asr
from ..ml.registry import get_image_embedder, get_text_embedder
from . import frames as frames_mod
from . import storage
from .text import chunk_segments, chunk_text

log = logging.getLogger(__name__)

# По скільки кадрів за раз. Стеля max_frames_per_video — дванадцять, тож усе
# відео зазвичай іде однією пачкою; межа тут на випадок, якщо стелю піднімуть.
FRAME_BATCH = 12


def _embed_frames(
    item_id: int,
    paths: list[Path],
    frame_ids: list[int | None],
    stamps: list[float | None],
) -> None:
    """Кодує кадри пачками. Пачка — це той самий прохід моделі, але один раз."""
    if not paths:
        return

    for start in range(0, len(paths), FRAME_BATCH):
        window = slice(start, start + FRAME_BATCH)
        images = []
        try:
            for path in paths[window]:
                with Image.open(path) as image:
                    images.append(image.convert("RGB"))
            vectors = get_image_embedder().encode_images(images)
        finally:
            for image in images:
                image.close()

        for space, batch in vectors.items():
            for offset, vector in enumerate(batch):
                repo.add_embedding(
                    item_id, space, vector,
                    frame_id=frame_ids[window][offset],
                    ts_s=stamps[window][offset],
                )


def _index_frames(item_id: int, saved: list[tuple[float, str]], settings) -> None:
    """Записує кадри в базу й кодує їх однією пачкою.

    Пачка виграє скромні ×1.15 на дванадцяти кадрах, але дістається задарма:
    пам'яті це додає 0.17 ГБ із восьми, а відеокарта й так простоювала між
    окремими викликами.
    """
    frame_ids = [repo.add_frame(item_id, ts, relative) for ts, relative in saved]
    _embed_frames(
        item_id,
        [settings.frames_dir / relative for _, relative in saved],
        frame_ids,
        [ts for ts, _ in saved],
    )


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
    for space in IMAGE_SPACES:
        repo.clear_embeddings(item_id, space)
    _embed_frames(item_id, [path], [None], [None])


def process_text(item_id: int) -> None:
    item = repo.get_item(item_id)
    assert item is not None
    index_text(item_id, item["text_content"] or "")


def process_audio(item_id: int, on_progress=None) -> None:
    settings = get_settings()
    item = repo.get_item(item_id)
    assert item is not None
    path = settings.originals_dir / item["stored_path"]

    if item["transcript_edited"] and item["transcript"]:
        # Людина вже виправила машинний текст. Переіндексація не має права
        # затирати цю роботу: переганяємо лише вектори, а сам текст лишаємо.
        log.info("Запис %s має виправлену транскрипцію — розпізнавання пропущено", item_id)
        if on_progress:
            on_progress(1.0)
        index_text(item_id, item["transcript"])
        return

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

    for space in IMAGE_SPACES:
        repo.clear_embeddings(item_id, space)

    # Кадри ріже ffmpeg на процесорі, мовлення розпізнає відеокарта — і одне
    # одного вони не потребують. Поки що вони чекали по черзі: заміряно 4.2 с
    # ffmpeg і 7.5 с розпізнавання на трьох реальних відео. Разом це те саме
    # розпізнавання плюс нічого.
    #
    # У потік винесено саме ffmpeg, бо він у базу не пише: SQLite тут одне
    # підключення на потік, і розводити записи по двох — шукати собі блокувань.
    with ThreadPoolExecutor(max_workers=1) as pool:
        cutting = pool.submit(
            lambda: frames_mod.extract(
                path,
                frames_mod.pick_timestamps(path, item["duration_s"]),
                item["content_hash"],
            )
        )
        try:
            process_audio(
                item_id,
                on_progress=lambda p: on_progress(0.7 * p) if on_progress else None,
            )
        except asr.NoAudioTrack:
            # Німе відео — не помилка обробки: запис лишається знайденим по
            # кадрах, тож нарізане треба дочекатися й проіндексувати.
            log.info("Відео %s без звукової доріжки — індексуємо лише кадри", item_id)
            _index_frames(item_id, cutting.result(), settings)
            raise
        saved = cutting.result()

    if on_progress:
        on_progress(0.7)

    _index_frames(item_id, saved, settings)


PROCESSORS = {
    "image": process_image,
    "text": process_text,
    "audio": process_audio,
    "video": process_video,
}
