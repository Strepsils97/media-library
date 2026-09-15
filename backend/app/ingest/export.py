"""Збереження запису назовні, за потреби — з очищеним звуком.

Бібліотека тримає копію оригіналу під іменем із хешу, і дістати звідти файл
вручну незручно: імена нечитабельні, а розкладка по двох символах хешу
розкидає все по десятках тек. Тому експорт кладе файл під зрозумілою назвою
туди, куди людина звикла качати.

Шум прибирається засобами ffmpeg, який і так у збірці. Окремої моделі це не
потребує, а для голосових записів дає помітний результат.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

from ..config import get_settings
from .media_tools import ffmpeg

log = logging.getLogger(__name__)

# Ланцюжок фільтрів для мовлення.
#
# Свідомо стриманий: агресивне прибирання шуму робить голос «підводним», і
# запис стає гіршим за оригінал. Тому спершу зрізається низькочастотний гул
# (мікрофон у руці, кондиціонер, стіл), далі широкосмуговий шум прибирається
# з відстеженням його профілю, і наприкінці вирівнюється гучність — у
# голосових повідомленнях вона стрибає найбільше.
DENOISE_FILTER = "highpass=f=90,afftdn=nf=-25:tn=1,dynaudnorm=f=200:g=15:p=0.7"

# Формати, у яких є що чистити.
AUDIBLE = ("audio", "video")

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class ExportFailed(Exception):
    pass


def default_target_dir() -> Path:
    """Куди класти за замовчуванням — тека завантажень користувача."""
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


def safe_name(label: str, suffix: str) -> str:
    """Зрозуміла назва файлу з лейбла запису."""
    name = _UNSAFE.sub(" ", label).strip().rstrip(".")
    name = re.sub(r"\s+", " ", name)[:80].strip() or "запис"
    return f"{name}{suffix}"


def _unique(path: Path) -> Path:
    """Не перезаписуємо те, що вже лежить у теці завантажень."""
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise ExportFailed("Не вдалося підібрати вільну назву файлу")


def _run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(
        [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True, text=True, check=False, errors="replace",
    )
    if result.returncode != 0:
        raise ExportFailed(
            "ffmpeg не впорався з обробкою: " + (result.stderr.strip()[:300] or "невідома причина")
        )


def export_item(item, *, denoise: bool = False, target_dir: Path | None = None) -> Path:
    """Кладе копію запису в теку завантажень. Повертає шлях до файлу."""
    settings = get_settings()

    if not item["stored_path"]:
        # Вставлений текст файлу не має — віддаємо його як .txt.
        target = _unique(
            (target_dir or default_target_dir()) / safe_name(item["label"], ".txt")
        )
        target.write_text(item["text_content"] or "", encoding="utf-8")
        return target

    source = settings.originals_dir / item["stored_path"]
    if not source.exists():
        raise ExportFailed("Файл не знайдено в бібліотеці")

    directory = target_dir or default_target_dir()
    directory.mkdir(parents=True, exist_ok=True)

    if not denoise or item["kind"] not in AUDIBLE:
        target = _unique(directory / safe_name(item["label"], source.suffix))
        shutil.copy2(source, target)
        return target

    target = _unique(directory / safe_name(f"{item['label']} (без шуму)", source.suffix))

    if item["kind"] == "video":
        # Відеодоріжку не чіпаємо: перекодування заради звуку зіпсувало б
        # картинку й коштувало б хвилин замість секунд.
        args = ["-i", str(source), "-c:v", "copy", "-af", DENOISE_FILTER,
                "-c:a", "aac", "-b:a", "192k", str(target)]
    else:
        args = ["-i", str(source), "-af", DENOISE_FILTER, str(target)]

    _run_ffmpeg(args)

    if not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise ExportFailed("Оброблений файл вийшов порожнім")

    log.info("Експортовано %s (шум прибрано: %s)", target.name, denoise)
    return target


def reveal(path: Path) -> bool:
    """Показує файл у провіднику. Повертає False, якщо не вийшло."""
    import sys

    if not path.exists():
        return False
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
        return True
    except OSError as exc:
        log.warning("Не вдалося відкрити теку: %s", exc)
        return False
