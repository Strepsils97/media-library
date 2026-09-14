"""Відбір кадрів із відео по зміні сцени."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from ..config import get_settings
from .media_tools import ffmpeg

log = logging.getLogger(__name__)


def _scene_timestamps(path: Path, threshold: float = 0.30) -> list[float]:
    """Моменти зміни сцени за фільтром ffmpeg.

    Свій детектор тут зайвий: ffmpeg уже в залежностях заради декодування,
    а його scene-фільтр дає цілком придатні межі.
    """
    result = subprocess.run(
        [ffmpeg(), "-hide_banner", "-i", str(path),
         "-filter:v", f"select='gt(scene,{threshold})',showinfo",
         "-f", "null", "-"],
        capture_output=True, text=True, check=False, errors="replace",
    )
    stamps: list[float] = []
    for line in result.stderr.splitlines():
        if "pts_time:" not in line:
            continue
        try:
            stamps.append(float(line.split("pts_time:")[1].split()[0]))
        except (IndexError, ValueError):
            continue
    return stamps


def pick_timestamps(path: Path, duration_s: float | None) -> list[float]:
    """Обирає моменти для кадрів: не кожен фрейм, а обмежена вибірка."""
    settings = get_settings()
    limit = settings.max_frames_per_video
    gap = settings.min_frame_interval_s

    stamps = _scene_timestamps(path)

    # Коротке або монотонне відео сцен не дає — беремо рівномірно.
    if len(stamps) < 2 and duration_s:
        count = max(1, min(limit, int(duration_s // max(gap, 1)) or 1))
        stamps = [duration_s * (i + 0.5) / count for i in range(count)]

    picked: list[float] = []
    for ts in sorted(stamps):
        if not picked or ts - picked[-1] >= gap:
            picked.append(ts)

    if len(picked) > limit:
        # Рівномірно проріджуємо, щоб покрити весь запис, а не тільки початок.
        step = len(picked) / limit
        picked = [picked[int(i * step)] for i in range(limit)]

    return picked


def extract(path: Path, timestamps: list[float], content_hash: str) -> list[tuple[float, str]]:
    """Витягує кадри у data/frames. Повертає пари (момент, відносний шлях)."""
    settings = get_settings()
    out_dir = settings.frames_dir / content_hash[:2]
    out_dir.mkdir(parents=True, exist_ok=True)

    saved: list[tuple[float, str]] = []
    for index, ts in enumerate(timestamps):
        relative = Path(content_hash[:2]) / f"{content_hash}_{index:02d}.webp"
        target = settings.frames_dir / relative
        if not target.exists():
            result = subprocess.run(
                [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                 "-ss", f"{ts:.3f}", "-i", str(path), "-frames:v", "1",
                 "-vf", "scale='min(512,iw)':-2", str(target)],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0 or not target.exists():
                log.warning("Не вдалося витягти кадр на %.1fs з %s", ts, path.name)
                continue
        saved.append((ts, relative.as_posix()))
    return saved
