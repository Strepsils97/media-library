"""Збереження запису назовні, за потреби — з очищеним звуком.

Бібліотека тримає копію оригіналу під іменем із хешу, і дістати звідти файл
вручну незручно: імена нечитабельні, а розкладка по двох символах хешу
розкидає все по десятках тек. Тому експорт кладе файл під зрозумілою назвою
туди, куди людина звикла качати.

Шум прибирає DeepFilterNet — окремий виконуваний файл поруч із застосунком.
Саме окремий, а не pip-пакет: той тягне torchaudio, якого під наш torch не
існує, і заради нього довелося б відкочувати torch у всьому застосунку.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
from pathlib import Path

from ..config import get_settings
from .media_tools import deep_filter, ffmpeg, popen, run

log = logging.getLogger(__name__)

# Прибирання шуму робить DeepFilterNet — нейромережа, яка на відміну від
# спектрального віднімання справляється й з нестаціонарним шумом: дорогою,
# машинами, чужими голосами.
#
# Заміряно на реальних записах (рівень шуму / що чує розпізнавання):
#   без обробки              -37 дБ   транскрипція зв'язна
#   спектральний фільтр      -60 дБ   трохи гірша
#   DeepFilterNet 15         -53 дБ   трохи гірша
#   DeepFilterNet 30         -68 дБ   помітно гірша
#   DeepFilterNet 60         -84 дБ   помітно гірша
#   DeepFilterNet 100        -84 дБ   те саме, що й 60
#
# Тут криється розбіжність, яку варто розуміти. Чим сильніше чистити, тим
# гірше розпізнає Whisper: разом із шумом зникають тонкі деталі мовлення,
# які людина добудовує з контексту, а модель — ні. На слух же сильні режими
# помітно приємніші. Обидва спостереження правдиві, і суперечності немає:
# розпізнавання працює з оригіналом у бібліотеці, а фільтр застосовується
# лише до файлу, який людина забирає послухати. Тобто за чистий звук не
# доводиться платити якістю пошуку.
#
# Вище 60 сенсу немає: 100 дає той самий результат.
DENOISE_LEVELS: dict[str, int] = {
    "light": 15,
    "medium": 30,
    "strong": 60,
}
DEFAULT_LEVEL = "strong"

# Звук для DeepFilterNet: 48 кГц моно, як його навчали.
DENOISE_RATE = 48000

# Формати, у яких є що чистити.
AUDIBLE = ("audio", "video")

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class ExportFailed(Exception):
    pass


def default_target_dir() -> Path:
    """Куди класти файли: обрана в налаштуваннях тека або завантаження."""
    chosen = get_settings().download_dir
    if chosen:
        path = Path(chosen)
        if path.is_dir():
            return path
        log.warning("Тека для завантажень %s недоступна — беремо стандартну", path)

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
    result = run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args])
    if result.returncode != 0:
        raise ExportFailed(
            "ffmpeg не впорався з обробкою: " + (result.stderr.strip()[:300] or "невідома причина")
        )


def preview_path(item, level: str) -> Path:
    """Оброблений файл для прослуховування.

    Обробка триває секунди, а порівнювати рівні на слух хочеться швидко —
    тож результат лишається в кеші. Він же потім віддається на завантаження,
    щоб не робити ту саму роботу двічі.
    """
    if level not in DENOISE_LEVELS:
        raise ExportFailed(f"Невідомий рівень прибирання шуму: {level}")

    settings = get_settings()
    cache = settings.data_dir / "cache" / "denoise"
    cache.mkdir(parents=True, exist_ok=True)

    digest = item["content_hash"] or str(item["id"])
    target = cache / f"{digest}-{level}.mp3"
    if target.exists() and target.stat().st_size > 0:
        return target

    source = settings.originals_dir / item["stored_path"]
    if not source.exists():
        raise ExportFailed("Файл не знайдено в бібліотеці")

    with tempfile.TemporaryDirectory(prefix="medialib-denoise-") as tmp:
        clean = _denoise_to_wav(source, Path(tmp), DENOISE_LEVELS[level])
        _run_ffmpeg(["-i", str(clean), "-b:a", "192k", str(target)])

    if not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise ExportFailed("Обробка не дала результату")
    return target


def clear_preview_cache() -> int:
    """Прибирає кеш прослуховування. Повертає, скільки файлів видалено."""
    cache = get_settings().data_dir / "cache" / "denoise"
    if not cache.is_dir():
        return 0
    removed = 0
    for path in cache.glob("*.mp3"):
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def _denoise_to_wav(source: Path, work: Path, strength: int) -> Path:
    """Проганяє звук через DeepFilterNet. Повертає очищений WAV."""
    plain = work / "plain.wav"
    _run_ffmpeg([
        "-i", str(source), "-vn", "-ac", "1", "-ar", str(DENOISE_RATE), str(plain)
    ])

    out_dir = work / "clean"
    out_dir.mkdir(parents=True, exist_ok=True)

    # -D вирівнює затримку, яку вносять перетворення й заглядання моделі
    # вперед: без нього звук поїхав би відносно відео.
    result = run([deep_filter(), "-D", "-a", str(strength),
                  "-o", str(out_dir), str(plain)])
    if result.returncode != 0:
        raise ExportFailed(
            "Не вдалося прибрати шум: " + (result.stderr.strip()[:300] or "невідома причина")
        )

    produced = sorted(out_dir.glob("*.wav"))
    if not produced:
        raise ExportFailed("Обробка шуму не дала результату")
    return produced[0]


def export_item(
    item,
    *,
    denoise: bool | str = False,
    target_dir: Path | None = None,
) -> Path:
    """Кладе копію запису в теку завантажень. Повертає шлях до файлу.

    `denoise` — назва рівня з DENOISE_LEVELS, або True для типового.
    """
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

    level = DEFAULT_LEVEL if denoise is True else denoise
    if not level or item["kind"] not in AUDIBLE:
        # Без обробки — саме копія, байт у байт. Перекодування «про всяк
        # випадок» зіпсувало б оригінал там, де про це ніхто не просив.
        target = _unique(directory / safe_name(item["label"], source.suffix))
        shutil.copy2(source, target)
        return target

    if level not in DENOISE_LEVELS:
        raise ExportFailed(f"Невідомий рівень прибирання шуму: {level}")

    target = _unique(directory / safe_name(f"{item['label']} (без шуму)", source.suffix))

    if item["kind"] == "audio":
        # Те саме вже зроблено для прослуховування — просто забираємо звідти.
        shutil.copy2(preview_path(item, level), target)
    else:
        with tempfile.TemporaryDirectory(prefix="medialib-denoise-") as tmp:
            clean = _denoise_to_wav(source, Path(tmp), DENOISE_LEVELS[level])
            # Відеодоріжку не чіпаємо: перекодування заради звуку зіпсувало б
            # картинку й коштувало б хвилин замість секунд.
            _run_ffmpeg([
                "-i", str(source), "-i", str(clean),
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", str(target),
            ])

    if not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise ExportFailed("Оброблений файл вийшов порожнім")

    log.info("Експортовано %s (шум: %s)", target.name, level)
    return target


def reveal(path: Path) -> bool:
    """Показує файл у провіднику. Повертає False, якщо не вийшло."""
    import sys

    if not path.exists():
        return False
    try:
        if sys.platform == "win32":
            popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            popen(["open", "-R", str(path)])
        else:
            popen(["xdg-open", str(path.parent)])
        return True
    except OSError as exc:
        log.warning("Не вдалося відкрити теку: %s", exc)
        return False
