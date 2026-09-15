"""Пошук фрагмента, який збігся із запитом, усередині уривка.

Векторний пошук не каже, які саме слова спрацювали — він порівнює сенси
цілком. Тому для підсвічування доводиться окремо шукати лексичний слід
запиту в тексті: це не пояснення роботи моделі, а підказка оку, куди
дивитися в картці результату.
"""

from __future__ import annotations

import re

# Українська й російська сильно відмінювані, тому порівнюємо не слова цілком,
# а їхні початки: «шавуха» і «шавуху» мають вважатися тим самим.
_PREFIX = 4
_MIN_WORD = 3

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _terms(text: str) -> set[str]:
    return {
        match.group(0).casefold()[:_PREFIX]
        for match in _WORD_RE.finditer(text)
        if len(match.group(0)) >= _MIN_WORD
    }


def find_span(snippet: str, query: str) -> tuple[int, int] | None:
    """Межі найщільнішого скупчення слів запиту в уривку.

    Повертає (початок, кінець) у символах або None, якщо лексичного сліду
    немає — таке цілком нормально: збіг міг бути суто смисловим.
    """
    if not snippet or not query:
        return None

    query_terms = _terms(query)
    if not query_terms:
        return None

    words = [
        (match.start(), match.end(), match.group(0).casefold()[:_PREFIX])
        for match in _WORD_RE.finditer(snippet)
    ]
    matched = [i for i, (_, _, stem) in enumerate(words) if stem in query_terms]
    if not matched:
        return None

    # Найкраще вікно — те, де збігів найбільше на найменшій довжині.
    # Так підсвітка лягає на фразу, а не розтягується через пів уривка
    # заради двох випадкових слів на краях.
    best: tuple[int, int] | None = None
    best_score = -1.0

    for start in range(len(matched)):
        for end in range(start, len(matched)):
            first, last = matched[start], matched[end]
            span_words = last - first + 1
            if span_words > 12:
                break
            count = end - start + 1
            score = count - 0.12 * (span_words - count)
            if score > best_score:
                best_score = score
                best = (words[first][0], words[last][1])

    return best
