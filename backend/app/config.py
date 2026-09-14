"""Конфігурація застосунку та розкладка тек на диску."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEDIALIB_", env_file=".env")

    data_dir: Path = Field(default_factory=lambda: _app_root() / "data")
    bundled_dir: Path = Field(default_factory=_bundled_root)

    # Обчислення
    device: str = "auto"  # auto | cuda | cpu
    asr_model: str = "small"
    asr_compute_type: str = "auto"
    asr_languages: tuple[str, ...] = ("uk", "ru", "de")

    # Нарізка кадрів із відео
    max_frames_per_video: int = 12
    min_frame_interval_s: float = 2.0

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
