"""Ембедери: SigLIP2 для зображень і запитів, E5 для текстів і транскрипцій."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from pathlib import Path

from ..config import get_settings
from .registry import normalize

if TYPE_CHECKING:
    from PIL.Image import Image

log = logging.getLogger(__name__)

IMAGE_MODEL = "google/siglip2-large-patch16-256"
TEXT_MODEL = "intfloat/multilingual-e5-base"

# Замір на Фазі 0: український запит «як є» дає 28.6% Recall@1, а загорнутий
# у природний англійський шаблон і переведений у нижній регістр — 76.2%.
# Це найдешевше покращення в усьому пошуку, тому шаблон зашитий у код, а не
# лишений на розсуд користувача.
QUERY_TEMPLATE = "a photo of {}."

# E5 навчали з префіксами, і без них якість помітно гірша.
E5_QUERY_PREFIX = "query: "
E5_PASSAGE_PREFIX = "passage: "


def _local_model_dir(name: str) -> Path | None:
    """Локальна fp16-копія, підготовлена до збірки (scripts/prepare_models.py)."""
    settings = get_settings()
    for base in (settings.models_dir, settings.data_dir / "models"):
        candidate = base / "local" / name
        if (candidate / "config.json").exists():
            return candidate
    return None


def _load_kwargs(name: str, repo_id: str) -> tuple[str, dict]:
    """Звідки вантажити модель і з якими параметрами."""
    local = _local_model_dir(name)
    if local is not None:
        return str(local), {}
    return repo_id, {"cache_dir": get_settings().models_dir}


def _torch_device() -> str:
    import torch

    preference = get_settings().device
    if preference == "cpu":
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    if preference == "cuda":
        log.warning("Запитано cuda, але torch її не бачить — працюємо на процесорі.")
    return "cpu"


class SiglipEmbedder:
    """Зображення та текстові запити в одному векторному просторі."""

    def __init__(self) -> None:
        import torch
        from transformers import AutoModel, AutoProcessor

        self.device = _torch_device()
        self._torch = torch

        source, kwargs = _load_kwargs("siglip", IMAGE_MODEL)
        log.info("Завантаження %s на %s", source, self.device)

        self.processor = AutoProcessor.from_pretrained(source, **kwargs)
        # Ваги зберігаються у fp16 заради розміру збірки, але на процесорі
        # половинна точність підтримана не всюди — там піднімаємо до fp32.
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.model = (
            AutoModel.from_pretrained(source, dtype=dtype, **kwargs).eval().to(self.device)
        )
        self.dim = int(self.model.config.text_config.hidden_size)

    def _features(self, outputs) -> np.ndarray:
        # transformers повертає то тензор, то об'єкт виходу — залежно від версії.
        tensor = getattr(outputs, "pooler_output", outputs)
        return tensor.float().cpu().numpy()

    def encode_images(self, images: list[Image]) -> np.ndarray:
        if not images:
            return np.zeros((0, self.dim), dtype=np.float32)
        with self._torch.inference_mode():
            batch = self.processor(images=images, return_tensors="pt").to(self.device)
            return normalize(self._features(self.model.get_image_features(**batch)))

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        prompts = [QUERY_TEMPLATE.format(t.strip().lower()) for t in texts]
        with self._torch.inference_mode():
            batch = self.processor(
                text=prompts,
                padding="max_length",  # SigLIP навчали саме так
                truncation=True,
                return_tensors="pt",
            ).to(self.device)
            return normalize(self._features(self.model.get_text_features(**batch)))


class E5Embedder:
    """Тексти, транскрипції та текстова частина пошукового запиту."""

    def __init__(self) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.device = _torch_device()
        self._torch = torch

        source, kwargs = _load_kwargs("e5", TEXT_MODEL)
        log.info("Завантаження %s на %s", source, self.device)

        self.tokenizer = AutoTokenizer.from_pretrained(source, **kwargs)
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.model = (
            AutoModel.from_pretrained(source, dtype=dtype, **kwargs).eval().to(self.device)
        )
        self.dim = int(self.model.config.hidden_size)

    def _encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        with self._torch.inference_mode():
            batch = self.tokenizer(
                texts, padding=True, truncation=True, max_length=512, return_tensors="pt"
            ).to(self.device)
            output = self.model(**batch).last_hidden_state
            # Усереднення по токенах з урахуванням маски: доповнення не повинно
            # тягнути вектор до нуля.
            mask = batch["attention_mask"].unsqueeze(-1).float()
            pooled = (output * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
            return normalize(pooled.float().cpu().numpy())

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        return self._encode([E5_PASSAGE_PREFIX + t for t in texts])

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode([E5_QUERY_PREFIX + t for t in texts])
