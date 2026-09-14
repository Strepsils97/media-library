"""Пошук ffmpeg і ffprobe.

У зібраному застосунку вони лежать поруч із кодом, а не в PATH, тож
викликати їх просто за іменем не можна — у frozen-режимі це мовчазний збій
на кожному відео й аудіо.
"""

from __future__ import annotations

import functools
import shutil
import sys
from pathlib import Path


class MissingTool(Exception):
    """Немає ffmpeg — декодувати медіа нічим."""


def _bundled(name: str) -> Path | None:
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    for candidate in (Path(meipass) / f"{name}.exe", Path(meipass) / f"{name}.EXE"):
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
