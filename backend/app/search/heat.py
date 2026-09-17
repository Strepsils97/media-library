"""Наскільки кожне слово тексту відповідає запиту.

Підсвітка збігу (`highlight.py`) шукає лексичний слід: ті самі слова в інших
формах. Але пошук у цьому застосунку смисловий, і найцікавіші влучання —
саме ті, де жодного спільного слова немає. Там підсвічувати не було чого, і
людина відкривала довгу транскрибцію, де збіг знайшла модель, а шукати його
доводилося очима.

Тут те саме питання ставиться самій моделі: текст ріжеться на короткі вікна,
кожне порівнюється із запитом, і слова заливаються тим густіше, чим ближче
вікно до запиту.

Чому вікна по три слова, а не речення. Заміряно на живій бібліотеці —
наскільки правильне місце підіймається над рештою тексту, у сигмах розкиду:

    запит      три слова   речення
    магазин        6.4σ      4.3σ
    гроші          5.6σ      2.5σ
    робота         3.7σ      1.2σ
    дорога         2.9σ      1.3σ

Речення вдвічі гірші: збіг у них тоне серед десятка сусідніх слів. Рвано при
цьому не виходить — вікна йдуть із кроком в одне слово й перекриваються, тож
кожне слово бере найкращу зі своїх оцінок, а заливка лягає плавно.
"""

from __future__ import annotations

import re

import numpy as np

WINDOW_WORDS = 3

# Довгі тексти не варті того, щоб рахувати їх цілком: вікон стає кілька тисяч,
# а користь від кожного та сама. Крок збільшується — заливка грубішає, але
# лишається на місці.
MAX_WINDOWS = 900

# Нижче цього — просто тло тексту. Поріг у сигмах: косинуси E5 тиснуться
# купно (у фоновому розподілі σ близько 0.02), тож абсолютні числа тут не
# скажуть нічого, а відрив від власного тла документа — скаже.
FLOOR_SIGMAS = 0.8
FULL_SIGMAS = 3.0

_WORD_RE = re.compile(r"\S+", re.UNICODE)


def _words(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _WORD_RE.finditer(text)]


def word_heat(text: str, query: str, embedder) -> list[tuple[int, int, float]]:
    """Ділянки тексту та їхня близькість до запиту, від 0 до 1.

    Повертає (початок, кінець, наскільки гаряче) у символах. Ділянки, що
    не піднялися над тлом документа, не повертаються зовсім — підсвічувати
    рівним шаром увесь текст означало б не сказати нічого.
    """
    if not text or not query:
        return []

    words = _words(text)
    if len(words) < WINDOW_WORDS * 2:
        return []

    stride = max(1, (len(words) - WINDOW_WORDS) // MAX_WINDOWS + 1)
    starts = list(range(0, max(1, len(words) - WINDOW_WORDS + 1), stride))
    windows = [
        text[words[i][0] : words[min(i + WINDOW_WORDS - 1, len(words) - 1)][1]]
        for i in starts
    ]

    scores = embedder.encode_texts(windows) @ embedder.encode_queries([query])[0]

    # Порівнюємо вікна між собою, а не з абсолютною шкалою: у тексті про
    # каву всі вікна будуть «про каву», і заливати треба не всі.
    spread = float(np.std(scores))
    if spread < 1e-6:
        return []
    z = (scores - float(np.mean(scores))) / spread

    heat = np.zeros(len(words), dtype=np.float32)
    for index, start in enumerate(starts):
        value = (z[index] - FLOOR_SIGMAS) / (FULL_SIGMAS - FLOOR_SIGMAS)
        if value <= 0:
            continue
        end = min(start + WINDOW_WORDS, len(words))
        np.maximum(heat[start:end], min(1.0, float(value)), out=heat[start:end])

    spans: list[tuple[int, int, float]] = []
    for index, (start, end) in enumerate(words):
        value = round(float(heat[index]), 2)
        if value <= 0:
            continue
        # Сусідні слова однакової густини склеюються — так у розмітці менше
        # шматків, а на око різниці немає.
        if spans and spans[-1][2] == value and start - spans[-1][1] <= 2:
            spans[-1] = (spans[-1][0], end, value)
        else:
            spans.append((start, end, value))
    return spans
