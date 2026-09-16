"""Конфігурація застосунку та розкладка тек на диску."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# HuggingFace за замовчуванням розкладає кеш симлінками, а Windows без
# привілеїв розробника їх створювати не дає — завантаження падає на першому ж
# файлі. Вимикаємо до першого імпорту huggingface_hub.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# У зібраному застосунку всі ваги лежать поруч. Без цього huggingface_hub
# усе одно лізе в мережу «звіритися з версією» — а застосунок офлайновий,
# і на машині без інтернету це обернулося б таймаутом при кожному старті.
if getattr(sys, "frozen", False):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def _app_root() -> Path:
    """Корінь застосунку.

    У зібраному вигляді PyInstaller розпаковує ресурси у тимчасову теку й кладе
    її шлях у ``sys._MEIPASS``. Дані користувача туди писати не можна — вона
    зникає після виходу, — тож бібліотека завжди живе поруч із виконуваним файлом.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def _bundled_root() -> Path:
    """Корінь незмінних ресурсів: фронтенд і вшиті ваги моделей."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return _app_root()


def _point_hf_cache_at_our_models() -> None:
    """Скеровує кеш HuggingFace у наші ваги.

    Передати `cache_dir` у місці виклику недостатньо: open_clip будує текстову
    вежу сам і кличе `AutoConfig.from_pretrained` без жодного cache_dir, тож
    та йде в домашній кеш користувача. Доки він існував, усе працювало — і
    вшитий у збірку токенізатор лежав мертвим вантажем. Варто було той кеш
    прибрати, і застосунок пішов у мережу по файл, який лежав у нього поруч.

    Змінна середовища закриває всі такі виклики одразу, включно з тими, до
    яких ми не дотягуємося.
    """
    for candidate in (_bundled_root() / "models", _app_root() / "data" / "models"):
        if candidate.is_dir():
            os.environ.setdefault("HF_HUB_CACHE", str(candidate))
            os.environ.setdefault("HF_HOME", str(candidate))
            return


_point_hf_cache_at_our_models()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEDIALIB_", env_file=".env")

    data_dir: Path = Field(default_factory=lambda: _app_root() / "data")
    bundled_dir: Path = Field(default_factory=_bundled_root)

    # Обчислення
    device: str = "auto"  # auto | cuda | cpu
    # Обрано заміром на Фазі 0: small на цьому контенті розпізнає
    # 3-4 запити з 13, large-v3-turbo — близько 9.
    asr_model: str = "large-v3-turbo"
    asr_compute_type: str = "auto"
    asr_languages: tuple[str, ...] = ("uk", "ru", "de")

    # Нарізка кадрів із відео
    max_frames_per_video: int = 12
    min_frame_interval_s: float = 2.0

    # Куди зберігати експортовані файли. Порожньо — тека завантажень.
    download_dir: str = ""

    # Пошук
    knn_candidates: int = 200
    snippet_words: int = 25

    # Розбиття довгих текстів
    text_chunk_words: int = 180
    text_chunk_overlap_words: int = 40

    @property
    def db_path(self) -> Path:
        return self.data_dir / "library.db"

    @property
    def originals_dir(self) -> Path:
        return self.data_dir / "originals"

    @property
    def frames_dir(self) -> Path:
        return self.data_dir / "frames"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def models_dir(self) -> Path:
        """Ваги моделей. Вшиті у збірку, у розробці — поруч із даними."""
        bundled = self.bundled_dir / "models"
        return bundled if bundled.exists() else self.data_dir / "models"

    @property
    def frontend_dir(self) -> Path:
        return self.bundled_dir / "frontend" / "dist"

    @property
    def icon_path(self) -> Path:
        """Знак застосунку. У збірці лежить поруч, у розробці — у brand/."""
        bundled = self.bundled_dir / "brand" / "media-library.ico"
        if bundled.exists():
            return bundled
        return Path(__file__).resolve().parents[2] / "brand" / "media-library.ico"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.originals_dir,
            self.frames_dir,
            self.thumbs_dir,
            self.data_dir / "models",
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
