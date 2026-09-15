"""Ембедери: дві моделі для зображень, одна для текстів.

Зображення кодуються двома моделями одночасно. Це не надмірність: замір на
реальних файлах показав, що вони помиляються на різних запитах — siglip2
губить «Солдат» і «Зубну пасту», nllb-clip — «Ікру» й «Ніж з кс». Разом вони
дають 81% Recall@1 і 95% Recall@3 проти 76% і 86% у кращої з них поодинці.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from ..config import get_settings
from ..db.connection import IMAGE_SPACES
from .registry import normalize

if TYPE_CHECKING:
    from PIL.Image import Image

log = logging.getLogger(__name__)

# space -> модель
IMAGE_MODELS = {
    "image_a": "google/siglip2-so400m-patch16-384",
    "image_b": ("nllb-clip-base-siglip", "v1"),  # open_clip
}
TEXT_MODEL = "intfloat/multilingual-e5-base"

# Замір на Фазі 0: український запит «як є» дає 28.6% Recall@1, а загорнутий
# у природний англійський шаблон і переведений у нижній регістр — 76.2%.
# Стосується лише siglip: nllb-clip навчали на 201 мові, і шаблон йому не
# потрібен.
SIGLIP_TEMPLATE = "a photo of {}."

# E5 навчали з префіксами, і без них якість помітно гірша.
E5_QUERY_PREFIX = "query: "
E5_PASSAGE_PREFIX = "passage: "


def _local_model_dir(name: str) -> Path | None:
    """Локальна копія, підготовлена до збірки (scripts/prepare_models.py)."""
    settings = get_settings()
    for base in (settings.models_dir, settings.data_dir / "models"):
        candidate = base / "local" / name
        if candidate.is_dir() and any(candidate.iterdir()):
            return candidate
    return None


def _load_kwargs(name: str, repo_id: str) -> tuple[str, dict]:
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
    """SigLIP2: зображення та англомовні формулювання запиту."""

    space = "image_a"

    def __init__(self) -> None:
        import torch
        from transformers import AutoModel, AutoProcessor

        self.device = _torch_device()
        self._torch = torch

        source, kwargs = _load_kwargs("siglip", IMAGE_MODELS["image_a"])
        log.info("Завантаження %s на %s", source, self.device)

        self.processor = AutoProcessor.from_pretrained(source, **kwargs)
        # Ваги у fp16 заради розміру збірки; на процесорі половинна точність
        # підтримана не всюди, тому там піднімаємо до fp32.
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.model = (
            AutoModel.from_pretrained(source, dtype=dtype, **kwargs).eval().to(self.device)
        )
        self.dim = int(self.model.config.text_config.hidden_size)

    def _features(self, outputs) -> np.ndarray:
        tensor = getattr(outputs, "pooler_output", outputs)
        return tensor.float().cpu().numpy()

    def encode_images(self, images: list[Image]) -> np.ndarray:
        with self._torch.inference_mode():
            batch = self.processor(images=images, return_tensors="pt").to(self.device)
            return normalize(self._features(self.model.get_image_features(**batch)))

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        prompts = [SIGLIP_TEMPLATE.format(t.strip().lower()) for t in texts]
        with self._torch.inference_mode():
            batch = self.processor(
                text=prompts,
                padding="max_length",  # SigLIP навчали саме так
                truncation=True,
                return_tensors="pt",
            ).to(self.device)
            return normalize(self._features(self.model.get_text_features(**batch)))


class NllbClipEmbedder:
    """NLLB-CLIP: текстова вежа на 201 мові, українську розуміє напряму."""

    space = "image_b"

    def __init__(self) -> None:
        import open_clip
        import torch

        self.device = _torch_device()
        self._torch = torch

        model_name, pretrained = IMAGE_MODELS["image_b"]
        local = _local_model_dir("nllbclip")
        settings = get_settings()

        log.info("Завантаження %s на %s", model_name, self.device)
        model, _, preprocess = open_clip.create_model_and_transforms(
            model_name,
            pretrained=str(local / "open_clip_pytorch_model.bin") if local else pretrained,
            cache_dir=str(settings.models_dir),
        )
        self.dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.model = model.eval().to(self.device, dtype=self.dtype)
        self.preprocess = preprocess
        # cache_dir обов'язковий: токенізатор NLLB тягнеться окремо від ваг,
        # і без цього у зібраному застосунку він шукався б у домашньому кеші,
        # якого там немає.
        self.tokenizer = open_clip.get_tokenizer(
            model_name, cache_dir=str(settings.models_dir)
        )
        # Розмірність питаємо в самої моделі, а не вгадуємо за назвами шарів:
        # open_clip будує CLIP по-різному залежно від архітектури, і в цієї
        # текстова проєкція лежить не там, де у ванільної.
        with torch.inference_mode():
            probe = self.model.encode_text(self.tokenizer(["проба"]).to(self.device))
        self.dim = int(probe.shape[-1])

    def encode_images(self, images: list[Image]) -> np.ndarray:
        batch = self._torch.stack([self.preprocess(img) for img in images])
        batch = batch.to(self.device, dtype=self.dtype)
        with self._torch.inference_mode():
            return normalize(self.model.encode_image(batch).float().cpu().numpy())

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        tokens = self.tokenizer(texts).to(self.device)
        with self._torch.inference_mode():
            return normalize(self.model.encode_text(tokens).float().cpu().numpy())


class ImageEnsemble:
    """Обидві візуальні моделі за одним інтерфейсом.

    Повертає словник «простір -> вектори», щоб решта коду не знала, скільки
    саме моделей стоїть за зображеннями.
    """

    def __init__(self) -> None:
        self.members = {
            "image_a": SiglipEmbedder(),
            "image_b": NllbClipEmbedder(),
        }
        self.dims = {space: member.dim for space, member in self.members.items()}

    @property
    def device(self) -> str:
        return self.members["image_a"].device

    def encode_images(self, images: list[Image]) -> dict[str, np.ndarray]:
        if not images:
            return {space: np.zeros((0, dim), np.float32) for space, dim in self.dims.items()}
        return {space: member.encode_images(images) for space, member in self.members.items()}

    def encode_queries(self, texts: list[str]) -> dict[str, np.ndarray]:
        if not texts:
            return {space: np.zeros((0, dim), np.float32) for space, dim in self.dims.items()}
        return {space: member.encode_queries(texts) for space, member in self.members.items()}


class E5Embedder:
    """Тексти, транскрипції та текстова частина пошукового запиту."""

    space = "text"

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


assert set(IMAGE_MODELS) == set(IMAGE_SPACES), "простори зображень розійшлися з моделями"
