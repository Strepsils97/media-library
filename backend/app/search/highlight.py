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
#
# Чотирьох літер вистачає не завжди. У коротких слів закінчення починається
# раніше: «кава» проти «кавою» розходяться саме на четвертій літері, і запит
# «кава» не підсвічував у тексті жодної «кави». Тому для коротких слів
# вистачає трьох спільних літер, а для довгих лишається чотири — інакше
# «магазин» чіплявся б до «магії».
_PREFIX = 4
_SHORT_PREFIX = 3
_SHORT_WORD = 4
_MIN_WORD = 3

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _words(text: str) -> list[str]:
    return [
        match.group(0).casefold()
        for match in _WORD_RE.finditer(text)
        if len(match.group(0)) >= _MIN_WORD
    ]


def _same_word(left: str, right: str) -> bool:
    """Чи це те саме слово в різних формах."""
    common = 0
    for a, b in zip(left, right):
        if a != b:
            break
        common += 1
    if common >= _PREFIX:
        return True
    return common >= _SHORT_PREFIX and min(len(left), len(right)) <= _SHORT_WORD


def find_span(snippet: str, query: str) -> tuple[int, int] | None:
    """Межі найщільнішого скупчення слів запиту в уривку.

    Повертає (початок, кінець) у символах або None, якщо лексичного сліду
    немає — таке цілком нормально: збіг міг бути суто смисловим.
    """
    if not snippet or not query:
        return None

    query_words = _words(query)
    if not query_words:
        return None

    words = [
        (match.start(), match.end(), match.group(0).casefold())
        for match in _WORD_RE.finditer(snippet)
    ]
    matched = [
        i
        for i, (_, _, word) in enumerate(words)
        if len(word) >= _MIN_WORD and any(_same_word(word, q) for q in query_words)
    ]
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
