"""Пошук CUDA-бібліотек для CTranslate2 на Windows.

cuBLAS і cuDNN приїжджають pip-пакетами `nvidia-*-cu12`, які кладуть DLL у
site-packages, а не в системний PATH. CTranslate2 шукає їх звичайним
завантажувачем Windows, тож теки треба явно додати у шлях пошуку до першого
звернення до моделі.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_REQUIRED_DLL = "cublas64_12.dll"
_registered = False


def _candidate_dirs() -> list[Path]:
    dirs: list[Path] = []

    # Зібраний застосунок: DLL лежать поруч із виконуваним файлом.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass) / "cuda")

    # Розробка: pip-пакети nvidia-*.
    for entry in sys.path:
        nvidia = Path(entry) / "nvidia"
        if nvidia.is_dir():
            dirs.extend(p for p in nvidia.glob("*/bin") if p.is_dir())

    return dirs


def ensure_cuda_libs() -> bool:
    """Додає теки з CUDA-бібліотеками у шлях пошуку DLL.

    Повертає True, якщо потрібні бібліотеки знайдено. Викликати до створення
    моделі: після завантаження CTranslate2 шлях пошуку вже не переглядається.
    """
    global _registered
    if _registered:
        return True
    if sys.platform != "win32":
        return True

    found = False
    for path in _candidate_dirs():
        os.add_dll_directory(str(path))
        os.environ["PATH"] = f"{path}{os.pathsep}{os.environ.get('PATH', '')}"
        if (path / _REQUIRED_DLL).exists():
            found = True

    if not found:
        log.warning(
            "CUDA-бібліотеки не знайдено (%s). Розпізнавання піде на процесорі.",
            _REQUIRED_DLL,
        )

    _registered = found
    return found


def resolve_device(preference: str = "auto") -> tuple[str, str]:
    """Обирає пристрій і тип обчислень для CTranslate2.

    Повертає пару (device, compute_type).
    """
    import ctranslate2

    if preference == "cpu":
        return "cpu", "int8"

    has_gpu = ctranslate2.get_cuda_device_count() > 0 and ensure_cuda_libs()

    if preference == "cuda":
        if not has_gpu:
            raise RuntimeError(
                "Запитано cuda, але відеокарта або CUDA-бібліотеки недоступні."
            )
        return "cuda", "int8_float16"

    return ("cuda", "int8_float16") if has_gpu else ("cpu", "int8")
