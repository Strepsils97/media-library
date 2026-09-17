"""Перегін файлів з формату у формат.

Голосові приходять у ogg, а віддати їх комусь часто треба в mp3 — і заради
цього людина шукає конвертер в інтернеті, хоча ffmpeg уже лежить усередині
застосунку. Тут він і використовується.

Бібліотеки це не торкається взагалі: файли беруться звідки вкажуть і лягають
куди вкажуть. Ніщо не додається до записів, ніщо не індексується.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .export import _unique, default_target_dir, safe_name
from .media_tools import ffmpeg, run

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Format:
    suffix: str
    args: tuple[str, ...]
    lossy: bool


# Що вміємо. Більше не треба: це не універсальний конвертер, а відповідь на
# просте питання «дай мені це у звичайному форматі».
FORMATS: dict[str, Format] = {
    "mp3": Format(".mp3", ("-c:a", "libmp3lame"), True),
    "m4a": Format(".m4a", ("-c:a", "aac"), True),
    "opus": Format(".opus", ("-c:a", "libopus"), True),
    "wav": Format(".wav", ("-c:a", "pcm_s16le"), False),
    "flac": Format(".flac", ("-c:a", "flac"), False),
}

BITRATES = ("128k", "192k", "256k", "320k")
DEFAULT_BITRATE = "192k"

# Кожен файл — окремий процес ffmpeg, і один одного вони не чекають.
# Заміряно на голосових: послідовно 0.52 с на файл, тобто 3.5 хвилини на
# чотириста штук; у кілька потоків — десятки секунд.
def _workers() -> int:
    return max(1, min(8, os.cpu_count() or 4))


class ConvertFailed(Exception):
    pass


@dataclass
class Converted:
    source: str
    path: str | None = None
    name: str | None = None
    error: str | None = None


def convert_file(
    source: Path,
    target_dir: Path,
    fmt: str,
    bitrate: str = DEFAULT_BITRATE,
) -> Path:
    """Переганяє один файл. Повертає шлях до результату."""
    spec = FORMATS.get(fmt)
    if spec is None:
        raise ConvertFailed(f"Невідомий формат: {fmt}")
    if bitrate not in BITRATES:
        raise ConvertFailed(f"Невідомий бітрейт: {bitrate}")
    if not source.exists():
        raise ConvertFailed(f"Файл не знайдено: {source.name}")

    target_dir.mkdir(parents=True, exist_ok=True)
    target = _unique(target_dir / safe_name(source.stem, spec.suffix))

    args = [
        ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        # Відео відкидаємо: обкладинка в mp3 нікому не заважає, але картинка
        # з відео перетворила б звуковий файл на щось дивне.
        "-vn",
        *spec.args,
    ]
    if spec.lossy:
        args += ["-b:a", bitrate]
    args.append(str(target))

    result = run(args)
    if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise ConvertFailed(result.stderr.strip()[:200] or "ffmpeg не впорався")
    return target


def convert_many(
    sources: list[Path],
    fmt: str,
    bitrate: str = DEFAULT_BITRATE,
    target_dir: Path | None = None,
) -> list[Converted]:
    """Переганяє пачку файлів. Помилка в одному не зупиняє решту."""
    directory = target_dir or default_target_dir()

    def one(source: Path) -> Converted:
        try:
            target = convert_file(source, directory, fmt, bitrate)
            return Converted(source=str(source), path=str(target), name=target.name)
        except ConvertFailed as exc:
            return Converted(source=str(source), error=str(exc))
        except OSError as exc:
            return Converted(source=str(source), error=str(exc))

    with ThreadPoolExecutor(max_workers=_workers()) as pool:
        results = list(pool.map(one, sources))

    failed = sum(1 for r in results if r.error)
    log.info("Переганяння у %s: %d файлів, невдалих %d", fmt, len(results), failed)
    return results
