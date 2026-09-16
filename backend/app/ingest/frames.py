"""Відбір кадрів із відео по зміні сцени."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import get_settings
from .media_tools import ffmpeg, run

log = logging.getLogger(__name__)


def _scene_timestamps(path: Path, threshold: float = 0.30) -> list[float]:
    """Моменти зміни сцени за фільтром ffmpeg.

    Свій детектор тут зайвий: ffmpeg уже в залежностях заради декодування,
    а його scene-фільтр дає цілком придатні межі.
    """
    result = run(
        [ffmpeg(), "-hide_banner", "-i", str(path),
         "-filter:v", f"select='gt(scene,{threshold})',showinfo",
         "-f", "null", "-"]
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


def _grab(path: Path, ts: float, target: Path) -> bool:
    """Один кадр. Швидке перемотування до `-i` — інакше ffmpeg декодує все
    з початку файлу до потрібної секунди."""
    result = run(
        [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{ts:.3f}", "-i", str(path), "-frames:v", "1",
         "-vf", "scale='min(512,iw)':-2", str(target)]
    )
    if result.returncode != 0 or not target.exists():
        log.warning("Не вдалося витягти кадр на %.1fs з %s", ts, path.name)
        return False
    return True


# Кадри один від одного не залежать, а кожен — це окремий процес ffmpeg, який
# більшу частину часу шукає потрібне місце у файлі. Заміряно на реальних
# відео: послідовно 10.6 с, у чотири потоки 2.8 с, у вісім 1.7 с. Це була
# найдорожча частина обробки відео — 42% часу.
def _workers() -> int:
    return max(1, min(8, (os.cpu_count() or 4)))


def extract(path: Path, timestamps: list[float], content_hash: str) -> list[tuple[float, str]]:
    """Витягує кадри у data/frames. Повертає пари (момент, відносний шлях)."""
    settings = get_settings()
    out_dir = settings.frames_dir / content_hash[:2]
    out_dir.mkdir(parents=True, exist_ok=True)

    planned: list[tuple[float, Path, Path]] = []
    for index, ts in enumerate(timestamps):
        relative = Path(content_hash[:2]) / f"{content_hash}_{index:02d}.webp"
        planned.append((ts, relative, settings.frames_dir / relative))

    todo = [item for item in planned if not item[2].exists()]
    failed: set[Path] = set()
    if todo:
        with ThreadPoolExecutor(max_workers=_workers()) as pool:
            results = {
                target: pool.submit(_grab, path, ts, target) for ts, _, target in todo
            }
        failed = {target for target, task in results.items() if not task.result()}

    # Порядок кадрів — це порядок часу, тож збираємо його з плану, а не з
    # того, хто з потоків устиг першим.
    return [
        (ts, relative.as_posix())
        for ts, relative, target in planned
        if target not in failed
    ]
