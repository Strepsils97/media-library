"""Пошук ffmpeg і ffprobe.

У зібраному застосунку вони лежать поруч із кодом, а не в PATH, тож
викликати їх просто за іменем не можна — у frozen-режимі це мовчазний збій
на кожному відео й аудіо.
"""

from __future__ import annotations

import functools
import shutil
import subprocess
import sys
from pathlib import Path


class MissingTool(Exception):
    """Немає ffmpeg — декодувати медіа нічим."""


def _bundled(name: str) -> Path | None:
    """Поруч із зібраним застосунком або в tools/ у корені проєкту."""
    roots = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    # У розробці системного deep-filter немає — беремо з tools/.
    roots.append(Path(__file__).resolve().parents[3] / "tools")

    for root in roots:
        for candidate in (root / f"{name}.exe", root / f"{name}.EXE", root / name):
            if candidate.exists():
                return candidate
    return None


@functools.lru_cache(maxsize=4)
def tool_path(name: str) -> str:
    found = _bundled(name) or shutil.which(name)
    if found is None:
        raise MissingTool(
            f"{name} не знайдено. Без нього не працюють відео й аудіо: "
            "застосунок не має власного декодера."
        )
    return str(found)


def ffmpeg() -> str:
    return tool_path("ffmpeg")


def ffprobe() -> str:
    return tool_path("ffprobe")


def deep_filter() -> str:
    """DeepFilterNet — окремий виконуваний файл, без Python і torch.

    Саме тому й обраний: pip-пакет тягне torchaudio, якого під наш torch
    немає, і заради нього довелося б відкочувати torch у всьому застосунку.
    """
    return tool_path("deep-filter")


def _no_window_flags() -> int:
    """Прапорці запуску, за яких не блимає консоль.

    Застосунок віконний, а ffmpeg — консольна програма: без цього Windows
    відкриває для кожного виклику чорне вікно на частку секунди. На додаванні
    відео таких викликів десятки, і виглядає це так, ніби щось ламається.
    """
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Запускає зовнішній інструмент тихо.

    Єдина точка запуску: інакше прапорець доводилося б пам'ятати при кожному
    новому виклику, і перший забутий повернув би блимання назад.
    """
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("check", False)
    kwargs.setdefault("errors", "replace")
    return subprocess.run(args, creationflags=_no_window_flags(), **kwargs)


def popen(args: list[str], **kwargs) -> subprocess.Popen:
    """Те саме для запуску без очікування."""
    return subprocess.Popen(args, creationflags=_no_window_flags(), **kwargs)
