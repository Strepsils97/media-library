"""Налаштування, які змінює користувач, і їхнє збереження між запусками.

Settings у config.py — це значення за замовчуванням і розкладка тек. Те, що
людина перемикає в інтерфейсі, живе тут: у простому JSON поруч із бібліотекою.
Окремий шар потрібен, бо ці значення мають пережити перезапуск і при цьому
застосуватися до вже завантажених моделей, а не лише до наступного старту.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from .config import get_settings
from .db.migrations import SCHEMA_VERSION
from .version import APP_VERSION

log = logging.getLogger(__name__)

# Лише ці поля користувач може змінювати з інтерфейсу. Білий список тут
# свідомий: інакше будь-яке поле конфігурації (включно зі шляхами) можна було б
# перезаписати через HTTP.
EDITABLE = {"asr_model", "device", "theme", "max_frames_per_video", "snippet_words"}

ASR_MODELS = ("tiny", "base", "small", "medium", "large-v3-turbo")
DEVICES = ("auto", "cuda", "cpu")
THEMES = ("dark", "light")

_lock = threading.Lock()
_extra: dict[str, Any] = {"theme": "dark"}


def _path():
    return get_settings().data_dir / "settings.json"


def load() -> None:
    """Застосовує збережені налаштування до конфігурації застосунку."""
    path = _path()
    if not path.exists():
        return
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Не вдалося прочитати %s: %s — беремо значення за замовчуванням", path, exc)
        return

    settings = get_settings()
    for key, value in stored.items():
        if key not in EDITABLE:
            continue
        if hasattr(settings, key):
            try:
                setattr(settings, key, value)
            except Exception:  # noqa: BLE001 — некоректне значення не має валити старт
                log.warning("Пропущено налаштування %s=%r", key, value)
        else:
            _extra[key] = value


def current() -> dict[str, Any]:
    settings = get_settings()
    return {
        "asr_model": settings.asr_model,
        "device": settings.device,
        "theme": _extra.get("theme", "dark"),
        "max_frames_per_video": settings.max_frames_per_video,
        "snippet_words": settings.snippet_words,
        "app_version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
        "available": {
            "asr_models": list(ASR_MODELS),
            "devices": list(DEVICES),
            "themes": list(THEMES),
        },
    }


def _validate(key: str, value: Any) -> Any:
    if key == "asr_model" and value not in ASR_MODELS:
        raise ValueError(f"Невідома модель розпізнавання: {value}")
    if key == "device" and value not in DEVICES:
        raise ValueError(f"Невідомий пристрій: {value}")
    if key == "theme" and value not in THEMES:
        raise ValueError(f"Невідома тема: {value}")
    if key in ("max_frames_per_video", "snippet_words"):
        value = int(value)
        if value < 1:
            raise ValueError(f"{key} має бути додатним")
    return value


def update(changes: dict[str, Any]) -> dict[str, Any]:
    """Зберігає зміни й одразу застосовує їх до застосунку."""
    settings = get_settings()

    with _lock:
        device_changed = False
        for key, value in changes.items():
            if key not in EDITABLE or value is None:
                continue
            value = _validate(key, value)
            if hasattr(settings, key):
                if key == "device" and getattr(settings, key) != value:
                    device_changed = True
                setattr(settings, key, value)
            else:
                _extra[key] = value

        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {key: current()[key] for key in EDITABLE if key in current()}
        path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if device_changed:
        # Моделі вже лежать на старому пристрої — їх треба підняти заново,
        # інакше перемикач у налаштуваннях нічого б не змінив до перезапуску.
        from .ml import asr
        from .ml.registry import reset

        reset()
        asr.unload()
        log.info("Пристрій змінено на %s — моделі буде перезавантажено", settings.device)

    return current()
