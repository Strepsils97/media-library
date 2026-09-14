"""Підготовка тексту до ембедінгу."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import get_settings


@dataclass(slots=True)
class Chunk:
    index: int
    text: str
    ts_s: float | None = None


def chunk_text(text: str) -> list[Chunk]:
    """Ріже довгий текст на фрагменти з перекриттям.

    Без цього ембедінг сторінки тексту вироджується в середнє по всьому
    документу й перестає знаходитися за конкретною згадкою.
    """
    settings = get_settings()
    size = settings.text_chunk_words
    overlap = settings.text_chunk_overlap_words

    words = text.split()
    if not words:
        return []
    if len(words) <= size:
        return [Chunk(0, text.strip())]

    step = max(1, size - overlap)
    chunks: list[Chunk] = []
    for index, start in enumerate(range(0, len(words), step)):
        piece = words[start : start + size]
        if not piece:
            break
        chunks.append(Chunk(index, " ".join(piece)))
        if start + size >= len(words):
            break
    return chunks


def chunk_segments(segments, max_words: int = 60) -> list[Chunk]:
    """Групує сегменти транскрипції у фрагменти, зберігаючи момент початку.

    Момент потрібен, щоб із результату пошуку можна було перемотати саме туди,
    де прозвучав збіг.
    """
    chunks: list[Chunk] = []
    buffer: list[str] = []
    start_ts: float | None = None
    words = 0

    for segment in segments:
        if start_ts is None:
            start_ts = segment.start
        buffer.append(segment.text)
        words += len(segment.text.split())
        if words >= max_words:
            chunks.append(Chunk(len(chunks), " ".join(buffer), start_ts))
            buffer, words, start_ts = [], 0, None

    if buffer:
        chunks.append(Chunk(len(chunks), " ".join(buffer), start_ts))
    return chunks


def snippet(text: str, words: int | None = None) -> str:
    limit = words or get_settings().snippet_words
    parts = text.split()
    return " ".join(parts[:limit]) + ("…" if len(parts) > limit else "")


def word_count(text: str) -> int:
    return len(text.split())
