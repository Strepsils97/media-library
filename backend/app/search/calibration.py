"""Калібрування оцінок схожості.

Косинуси двох векторних просторів живуть у різних діапазонах: у SigLIP типова
схожість тримається біля 0.05, у E5 — біля 0.8. Порівнювати їх напряму не
можна, а нормувати в межах видачі — теж (тоді найкращий кандидат кожного
простору завжди виглядає відмінним, навіть коли не стосується запиту).

Тому для кожного простору один раз рахується опорний розподіл: схожість
свідомо не пов'язаних запитів до наявних записів. Далі оцінка конкретного
збігу — це його відхилення від цього фону. Так 90 означає «помітно вище за
типовий шум цього простору» однаково для картинки й для транскрипції.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import numpy as np

from ..db.connection import IMAGE_SPACES, deserialize, get_connection, vec_table

log = logging.getLogger(__name__)

# Свідомо різнорідні й не пов'язані між собою фрази: вони мають дати
# «типову» схожість, а не влучити в якийсь конкретний запис.
DECOY_QUERIES = [
    "залізничний вокзал узимку",
    "інструкція до пральної машини",
    "гірський краєвид на світанку",
    "сторінка бухгалтерського звіту",
    "діти грають у футбол",
    "схема електропроводки",
    "морський берег із камінням",
    "рецепт борщу",
    "автомобіль на трасі вночі",
    "концерт у великому залі",
    "медичний рецепт від лікаря",
    "кіт спить на дивані",
    "будівельний майданчик",
    "весільна церемонія",
    "розмова про оренду квартири",
    "графік роботи магазину",
]

# Наскільки різко оцінка зростає з відхиленням. 1.1 підібрано так, щоб
# упевнений збіг (≈3 сигми над фоном) давав ~96, а фоновий шум — ~50.
_SHARPNESS = 1.1

# Мінімум векторів, на яких ще має сенс міряти фон.
#
# Достатньо одного: фон — це схожість набору свідомо не пов'язаних запитів до
# вмісту простору, і на одному векторі він теж визначений (стільки замірів,
# скільки приманок). Питання, на яке фон відповідає, — «наскільки цей збіг
# незвичний для цього простору», а не «як виглядає бібліотека загалом».
#
# Вищий поріг тут коштував дорого: доки простір лишався без калібрування,
# транскрипції систематично програвали картинкам, бо їхні косинуси живуть
# у зовсім іншому діапазоні. На щойно створеній бібліотеці з одним відео
# пошук по звуку через це не працював узагалі.
_MIN_ITEMS = 1


def _space_vectors(space: str, limit: int = 400) -> np.ndarray:
    rows = get_connection().execute(
        f"SELECT embedding FROM {vec_table(space)} LIMIT ?",  # noqa: S608 — назва з білого списку
        (limit,),
    ).fetchall()
    if not rows:
        return np.zeros((0, 0), dtype=np.float32)
    return np.array([deserialize(row["embedding"]) for row in rows], dtype=np.float32)


def compute(space: str) -> tuple[float, float] | None:
    """Рахує фоновий розподіл схожості для простору."""
    from ..ml.registry import get_image_embedder, get_text_embedder

    vectors = _space_vectors(space)
    if vectors.shape[0] < _MIN_ITEMS:
        return None

    if space in IMAGE_SPACES:
        # Ансамбль повертає словник просторів — беремо той, який калібруємо.
        queries = get_image_embedder().encode_queries(DECOY_QUERIES)[space]
    else:
        queries = get_text_embedder().encode_queries(DECOY_QUERIES)

    similarities = (queries @ vectors.T).ravel()
    mean = float(similarities.mean())
    std = float(similarities.std())
    if std < 1e-6:
        return None

    conn = get_connection()
    conn.execute(
        """INSERT INTO score_calibration (space, mean, stddev, sample_n, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(space) DO UPDATE SET
             mean = excluded.mean, stddev = excluded.stddev,
             sample_n = excluded.sample_n, updated_at = excluded.updated_at""",
        (space, mean, std, int(similarities.size), datetime.now(UTC).isoformat()),
    )
    conn.commit()
    log.info("Калібрування %s: середнє %.4f, σ %.4f", space, mean, std)
    return mean, std


def load(space: str) -> tuple[float, float] | None:
    row = get_connection().execute(
        "SELECT mean, stddev, sample_n FROM score_calibration WHERE space = ?", (space,)
    ).fetchone()
    if row is None:
        return None
    return float(row["mean"]), float(row["stddev"])


def _vector_count(space: str) -> int:
    row = get_connection().execute(
        f"SELECT COUNT(*) AS n FROM {vec_table(space)}"  # noqa: S608 — назва з білого списку
    ).fetchone()
    return int(row["n"])


def get(space: str) -> tuple[float, float] | None:
    """Калібрування простору, за потреби порахувавши його зараз.

    Фон перераховується, коли простір помітно виріс: калібрування, зняте на
    п'яти записах, на тисячі вже нічого не описує.
    """
    row = get_connection().execute(
        "SELECT mean, stddev, sample_n FROM score_calibration WHERE space = ?", (space,)
    ).fetchone()

    if row is not None:
        calibrated_on = int(row["sample_n"]) / max(1, len(DECOY_QUERIES))
        current = _vector_count(space)
        if current <= calibrated_on * 1.5:
            return float(row["mean"]), float(row["stddev"])

    return compute(space)


def invalidate() -> None:
    """Скидає калібрування — викликається, коли бібліотека помітно змінилася."""
    conn = get_connection()
    conn.execute("DELETE FROM score_calibration")
    conn.commit()


def to_score(similarity: float, calibration: tuple[float, float] | None) -> float:
    """Косинус -> оцінка 0..100, порівнювана між просторами."""
    if calibration is None:
        # Простір замалий навіть для фону (один запис). Порівнювати його
        # з іншим простором нічим, тож віддаємо середину шкали: краще не
        # показати впевненості, ніж показати вигадану.
        return 50.0
    mean, std = calibration
    z = (similarity - mean) / std
    return float(100.0 / (1.0 + np.exp(-z * _SHARPNESS)))
