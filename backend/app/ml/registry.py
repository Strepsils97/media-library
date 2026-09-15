"""Реєстр моделей: лінива загрузка й єдиний інтерфейс до ембедерів.

Зображення кодує ансамбль із двох моделей, тому його методи повертають
словник «простір -> вектори». Решта коду завдяки цьому не знає, скільки
саме моделей стоїть за зображеннями, і додавання третьої нічого не зламає.

Для тестів реєстр підмінюється детермінованими заглушками: вантажити
гігабайти ваг заради перевірки логіки пошуку немає сенсу.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    from PIL.Image import Image

log = logging.getLogger(__name__)


@runtime_checkable
class ImageEmbedder(Protocol):
    """Зображення та текст запиту в спільних просторах (крос-модальний пошук)."""

    dims: dict[str, int]

    def encode_images(self, images: list[Image]) -> dict[str, np.ndarray]: ...
    def encode_queries(self, texts: list[str]) -> dict[str, np.ndarray]: ...


@runtime_checkable
class TextEmbedder(Protocol):
    """Тексти й транскрипції."""

    dim: int

    def encode_texts(self, texts: list[str]) -> np.ndarray: ...


def normalize(vectors: np.ndarray) -> np.ndarray:
    """L2-нормування рядків.

    Пошук порівнює вектори косинусом, а sqlite-vec рахує евклідову відстань.
    На нормованих векторах ці метрики впорядковують однаково, тож нормувати
    треба один раз тут, а не при кожному запиті.
    """
    vectors = np.asarray(vectors, dtype=np.float32)
    if vectors.ndim == 1:
        vectors = vectors[None, :]
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    # Нульовий вектор лишається нульовим замість того, щоб дати NaN.
    norms[norms == 0] = 1.0
    return vectors / norms


class _DeterministicStub:
    """Заглушка: вектор із хешу вмісту.

    Не має жодного семантичного сенсу, але стабільна між запусками, тож на ній
    можна перевіряти сам механізм: запис, читання, фільтрацію, злиття оцінок.
    """

    def __init__(self, dim: int, salt: str) -> None:
        self.dim = dim
        self._salt = salt

    def _vector(self, payload: bytes) -> np.ndarray:
        digest = hashlib.sha256(self._salt.encode() + payload).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
        return rng.standard_normal(self.dim, dtype=np.float32)

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        return normalize(np.stack([self._vector(t.encode("utf-8")) for t in texts]))

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return self.encode_texts(texts)


class _ImageStub:
    """Заглушка ансамблю: той самий словник просторів, але без ваг."""

    def __init__(self, dims: dict[str, int]) -> None:
        self.dims = dims
        self._members = {
            space: _DeterministicStub(dim, salt=space) for space, dim in dims.items()
        }

    @property
    def device(self) -> str:
        return "cpu"

    def encode_images(self, images: list[Image]) -> dict[str, np.ndarray]:
        payloads = [img.resize((16, 16)).convert("RGB").tobytes() for img in images]
        return {
            space: normalize(np.stack([member._vector(p) for p in payloads]))
            for space, member in self._members.items()
        }

    def encode_queries(self, texts: list[str]) -> dict[str, np.ndarray]:
        return {space: member.encode_texts(texts) for space, member in self._members.items()}


_lock = threading.Lock()
_image_embedder: ImageEmbedder | None = None
_text_embedder: TextEmbedder | None = None


def use_stubs() -> None:
    """Перемкнути реєстр на заглушки — тести не мають вантажити гігабайти ваг."""
    from ..db.connection import IMAGE_SPACES, SPACES, TEXT_SPACE

    set_embedders(
        image=_ImageStub({space: SPACES[space] for space in IMAGE_SPACES}),
        text=_DeterministicStub(SPACES[TEXT_SPACE], salt=TEXT_SPACE),
    )


def get_image_embedder() -> ImageEmbedder:
    global _image_embedder
    with _lock:
        if _image_embedder is None:
            from .embedders import ImageEnsemble

            _image_embedder = ImageEnsemble()
        return _image_embedder


def get_text_embedder() -> TextEmbedder:
    global _text_embedder
    with _lock:
        if _text_embedder is None:
            from .embedders import E5Embedder

            _text_embedder = E5Embedder()
        return _text_embedder


def warm_up() -> None:
    """Примусово завантажити обидві моделі.

    Викликається на старті у фоні: інакше перша ж дія користувача — додавання
    файлу чи пошук — мовчки чекала б десятки секунд на завантаження ваг.
    """
    get_image_embedder()
    get_text_embedder()


def set_embedders(
    image: ImageEmbedder | None = None, text: TextEmbedder | None = None
) -> None:
    """Підміна реалізацій — для тестів і для переходу на справжні моделі."""
    global _image_embedder, _text_embedder
    with _lock:
        if image is not None:
            _image_embedder = image
        if text is not None:
            _text_embedder = text


def reset() -> None:
    global _image_embedder, _text_embedder
    with _lock:
        _image_embedder = None
        _text_embedder = None
