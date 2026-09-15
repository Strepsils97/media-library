"""Прийом файлу в бібліотеку: хеш, дедуплікація, копіювання, метадані, прев'ю."""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageOps

from ..config import get_settings
from .media_tools import ffprobe, run

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".ogg", ".opus", ".flac", ".aac"}
TEXT_SUFFIXES = {".txt", ".md"}

THUMB_MAX = 512
_HASH_CHUNK = 1 << 20


class UnsupportedFile(Exception):
    pass


@dataclass(slots=True)
class Prepared:
    """Файл, готовий до запису в базу."""

    kind: str
    label: str
    stored_path: str | None
    source_path: str | None
    content_hash: str | None
    mime: str | None
    size_bytes: int | None
    created_at: str
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    text_content: str | None = None


def detect_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    if suffix in TEXT_SUFFIXES:
        return "text"
    raise UnsupportedFile(f"Непідтримуваний тип файлу: {suffix or path.name}")


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def default_label(*, path: Path | None = None, text: str | None = None, words: int = 8) -> str:
    """Лейбл без жодних моделей: ім'я файлу або перші слова тексту."""
    if text:
        parts = text.split()
        label = " ".join(parts[:words])
        return f"{label}…" if len(parts) > words else label or "Без назви"
    if path is not None:
        return path.stem or path.name
    return "Без назви"


def _ffprobe(path: Path) -> dict:
    result = run(
        [ffprobe(), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)]
    )
    if result.returncode != 0:
        log.warning("ffprobe не зміг прочитати %s: %s", path.name, result.stderr.strip()[:200])
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def _media_metadata(path: Path) -> tuple[float | None, int | None, int | None, str | None]:
    """Тривалість, розміри й дата зйомки з контейнера."""
    probe = _ffprobe(path)
    fmt = probe.get("format", {})

    duration = None
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        pass

    width = height = None
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "video":
            width = stream.get("width")
            height = stream.get("height")
            break

    created = None
    tag = (fmt.get("tags") or {}).get("creation_time")
    if tag:
        try:
            created = datetime.fromisoformat(tag.replace("Z", "+00:00")).astimezone(UTC).isoformat()
        except ValueError:
            pass

    return duration, width, height, created


def _image_metadata(path: Path) -> tuple[int | None, int | None, str | None]:
    try:
        with Image.open(path) as img:
            width, height = img.size
            exif = img.getexif()
    except OSError as exc:
        raise UnsupportedFile(f"Не вдалося прочитати зображення: {exc}") from exc

    created = None
    # 36867 = DateTimeOriginal, 306 = DateTime
    for tag in (36867, 306):
        raw = exif.get(tag)
        if not raw:
            continue
        try:
            # EXIF пише "2024:05:11 13:02:44" — двокрапки замість дефісів у даті.
            date_part, time_part = str(raw).split(" ", 1)
            stamp = f"{date_part.replace(':', '-')} {time_part}"
            created = datetime.fromisoformat(stamp).replace(tzinfo=UTC).isoformat()
            break
        except ValueError:
            continue

    return width, height, created


def _fallback_created(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()


def _store(path: Path, content_hash: str) -> str:
    """Копіює файл у бібліотеку. Ім'я — з хешу, щоб уникнути колізій.

    Розкладка по двох символах хешу: інакше в одній теці опиняться десятки
    тисяч файлів, а Windows на таких теках помітно сповільнюється.
    """
    settings = get_settings()
    relative = Path(content_hash[:2]) / f"{content_hash}{path.suffix.lower()}"
    target = settings.originals_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(path, target)
    return relative.as_posix()


def make_thumbnail(source: Path, content_hash: str) -> str | None:
    """Прев'ю для сітки результатів. Повертає шлях відносно data/thumbs."""
    settings = get_settings()
    relative = Path(content_hash[:2]) / f"{content_hash}.webp"
    target = settings.thumbs_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return relative.as_posix()

    try:
        with Image.open(source) as img:
            # exif_transpose: інакше фото з телефона лягають боком.
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
            img.save(target, "WEBP", quality=82, method=4)
    except OSError as exc:
        log.warning("Не вдалося зробити прев'ю для %s: %s", source.name, exc)
        return None

    return relative.as_posix()


def prepare_file(path: Path) -> Prepared:
    """Готує файл до запису: рахує хеш, копіює, витягує метадані."""
    path = Path(path)
    if not path.is_file():
        raise UnsupportedFile(f"Файл не знайдено: {path}")

    kind = detect_kind(path)
    content_hash = hash_file(path)
    stat = path.stat()
    mime = mimetypes.guess_type(path.name)[0]

    duration = width = height = None
    created: str | None = None
    text_content: str | None = None

    if kind == "image":
        width, height, created = _image_metadata(path)
    elif kind in ("video", "audio"):
        duration, width, height, created = _media_metadata(path)
    elif kind == "text":
        # Файли з нашого світу — UTF-8; але не падати на чужих.
        text_content = path.read_text(encoding="utf-8", errors="replace")

    stored = _store(path, content_hash)

    return Prepared(
        kind=kind,
        label=default_label(path=path),
        stored_path=stored,
        source_path=str(path),
        content_hash=content_hash,
        mime=mime,
        size_bytes=stat.st_size,
        created_at=created or _fallback_created(path),
        duration_s=duration,
        width=width,
        height=height,
        text_content=text_content,
    )


def prepare_text(text: str, label: str | None = None) -> Prepared:
    """Готує вставлений вручну текст — файлу на диску немає."""
    text = text.strip()
    if not text:
        raise UnsupportedFile("Порожній текст")

    now = datetime.now(UTC).isoformat()
    return Prepared(
        kind="text",
        label=label or default_label(text=text),
        stored_path=None,
        source_path=None,
        content_hash=hash_text(text),
        mime="text/plain",
        size_bytes=len(text.encode("utf-8")),
        created_at=now,
        text_content=text,
    )
