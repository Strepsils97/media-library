"""Нечіткий пошук фрази в транскрипціях і текстах.

Векторний пошук знаходить сенс, але не вміє знайти конкретну фразу — надто
коли розпізнавання її спотворило. «Купила кока колу за євро» в транскрипції
виглядає як «Купила я кока-колы за евро»: за змістом те саме, лексично інше.

Тому поруч із векторним іде другий, чисто лексичний прохід: швидкий відбір
кандидатів через повнотекстовий індекс, а тоді зіставлення фрази з кожним
вікном тексту з допуском на помилки.

Замір на реальних транскрипціях (scripts/bench_phrase.py):
надійні збіги дають 0.86 і вище, а на 0.50-0.62 починаються хибні
спрацювання — звідти й поріг.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from difflib import SequenceMatcher

# Нижче цього збіг вважається випадковим і не враховується.
THRESHOLD = 0.72

# Скільки кандидатів брати з повнотекстового індексу перед нечітким
# зіставленням. Беруться найдоречніші за bm25, а не перші-ліпші: на
# бібліотеці, де запитані слова трапляються всюди, довільна вибірка змушувала
# б точно переміряти сотні свідомо слабких фрагментів.
FTS_LIMIT = 200

# Літери, які в українській і російській пишуться по-різному, а звучать
# однаково. Розпізнавання плутає їх постійно, а для пошуку фрази ця різниця
# значення не має: «Німеччина» і «Немеччина» мають вважатися тим самим.
_FOLD = str.maketrans(
    {
        "і": "и", "ї": "и", "ы": "и",
        "є": "е", "э": "е", "ё": "е",
        "ґ": "г",
        "'": "", "’": "", "ʼ": "", "`": "",
    }
)

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_FTS_TOKEN = re.compile(r"\w{2,}", re.UNICODE)


def fold(text: str) -> str:
    """Зводить текст до форми, у якій орфографічні відмінності не заважають."""
    text = unicodedata.normalize("NFKC", text).casefold().translate(_FOLD)
    return _SPACES.sub(" ", _PUNCT.sub(" ", text)).strip()


# Порівнювати кожне вікно фрагмента окремо надто дорого: на бібліотеці в
# 5000 записів це давало 6-10 секунд на запит. Натомість фраза один раз
# зіставляється з фрагментом цілком, а тоді точно переміряються лише ті
# кілька місць, де збіги згустилися.

# Частка триграм запиту, яка має знайтися у фрагменті, щоб узагалі рахувати
# далі. Поріг із запасом: збіг на 0.72 означає, що більшість символів фрази
# присутня в тексті по порядку, тож спільних триграм у нього завідомо більше.
_MIN_TRIGRAM_OVERLAP = 0.34

# Скільки найбільших збігів перевіряти точно.
_MAX_PROBES = 8

# Ширини вікна відносно довжини фрази. Кілька, бо ASR то втрачає службові
# слова, то додає свої; одна фіксована ширина відкидала б саме такі збіги.
# Пропорційні, а не з фіксованим запасом: для короткого запиту зайві символи
# у вікні коштують більше, ніж для довгого.
_WINDOW_RATIOS = (0.85, 1.0, 1.2)

# Довші фрагменти не трапляються: текст ріжеться на шматки при індексуванні.
_MAX_CHARS = 4000


def _trigrams(text: str) -> set[str]:
    return {text[i : i + 3] for i in range(len(text) - 2)} or {text}


def _overlap(query_grams: set[str], text: str) -> float:
    """Яка частка триграм запиту взагалі є в тексті."""
    if not query_grams:
        return 0.0
    return len(query_grams & _trigrams(text)) / len(query_grams)


def similarity(haystack: str, needle: str) -> float:
    """Найкраща схожість фрази з будь-яким місцем тексту.

    Вікно береться трохи ширшим за саму фразу: ASR любить втрачати або
    додавати службові слова, і жорстка довжина відкидала б саме ті збіги,
    заради яких це все й робиться.
    """
    folded = fold(haystack)[:_MAX_CHARS]
    target = fold(needle)
    if not folded or not target:
        return 0.0

    if _overlap(_trigrams(target), folded) < _MIN_TRIGRAM_OVERLAP:
        return 0.0

    widths = sorted({max(2, int(len(target) * r)) for r in _WINDOW_RATIOS})

    # Короткий фрагмент порівнюємо цілком — ділити нема чого.
    if len(folded) <= max(widths):
        return SequenceMatcher(None, target, folded, autojunk=False).ratio()

    # Один прохід по всьому фрагменту показує, де збіги взагалі є.
    blocks = [
        block
        for block in SequenceMatcher(
            None, target, folded, autojunk=False
        ).get_matching_blocks()
        if block.size >= 2
    ]
    if not blocks:
        return 0.0

    best = 0.0
    seen: set[tuple[int, int]] = set()
    matcher = SequenceMatcher(None, b=target, autojunk=False)

    for block in sorted(blocks, key=lambda b: -b.size)[:_MAX_PROBES]:
        for width in widths:
            # Ставимо вікно так, щоб знайдений збіг опинився в ньому на тому
            # ж місці, що й у самій фразі.
            start = max(0, min(block.b - block.a, len(folded) - width))
            if (start, width) in seen:
                continue
            seen.add((start, width))
            matcher.set_seq1(folded[start : start + width])
            if matcher.real_quick_ratio() <= best or matcher.quick_ratio() <= best:
                continue
            best = max(best, matcher.ratio())

    return best


# Опорні точки відображення схожості в оцінку.
#
# Взяті з розподілу на реальних транскрипціях, а не з рівномірної шкали:
# справжні збіги там ідуть від 0.86, хибні не піднімаються вище 0.65, тобто
# все, що подолало поріг, майже напевно справжнє.
#
# Крива навмисно крута. Збіг фрази — єдиний сигнал у цьому пошуку з
# заміряно нульовою кількістю хибних спрацювань: косинус же між запитом і
# картинкою залежить радше від самого тексту запиту, ніж від того, наскільки
# він пасує зображенню («нічо не хоче» дає вищий косинус, ніж «кіт»). Тому
# впевнений збіг фрази має перемагати будь-яку смислову здогадку, а не
# ділити з нею місце.
_ANCHORS = ((THRESHOLD, 88.0), (0.85, 99.0), (1.0, 100.0))

# У скільки разів слабший доказ — збіг одного слова й збіг пари слів.
# Одне слово в довгій транскрипції цілком може трапитися випадково: запит
# «ікра» знаходив відео про покупки лише тому, що там раз прозвучало це
# слово. Ціла фраза випадково не збігається.
_LENGTH_WEIGHT = {1: 0.45, 2: 0.75}


def to_score(ratio: float, words: int = 3) -> float:
    """Схожість фрази -> оцінка в тій самій шкалі 0..100, що й у векторів."""
    if ratio < THRESHOLD:
        return 0.0

    for (low_r, low_s), (high_r, high_s) in zip(_ANCHORS, _ANCHORS[1:], strict=False):
        if ratio <= high_r:
            span = high_r - low_r
            base = low_s + (high_s - low_s) * ((ratio - low_r) / span if span else 1.0)
            break
    else:
        base = _ANCHORS[-1][1]

    weight = _LENGTH_WEIGHT.get(words, 1.0)
    # Послаблюємо саме перевищення над порогом: короткий, але точний збіг
    # лишається помітним, просто не витісняє впевнений смисловий результат.
    return 70.0 + (base - 70.0) * weight


def word_count(text: str) -> int:
    return len(fold(text).split())


def _fts_query(text: str) -> str:
    """Запит до FTS5: будь-яке зі слів. Лапки — бо слово може збігтися
    зі службовим словом синтаксису FTS (NEAR, AND, OR)."""
    tokens = _FTS_TOKEN.findall(text)
    return " OR ".join(f'"{token}"' for token in tokens)


_COLUMNS = "e.id, e.item_id, e.chunk_text, e.ts_s, e.frame_id, e.chunk_ix"


def _fts_candidates(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    fts = _fts_query(query)
    if not fts:
        return []
    try:
        return conn.execute(
            f"""SELECT {_COLUMNS}
               FROM chunk_fts f
               JOIN embeddings e ON e.id = f.rowid
               WHERE chunk_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (fts, FTS_LIMIT),
        ).fetchall()
    except sqlite3.OperationalError:
        # Некоректний вираз FTS (наприклад, запит із самих розділових знаків)
        # не має валити пошук — решта проходів працює далі сама.
        return []


def _by_ids(conn: sqlite3.Connection, ids: set[int]) -> list[sqlite3.Row]:
    rows: list[sqlite3.Row] = []
    listed = list(ids)
    for start in range(0, len(listed), 400):
        chunk = listed[start : start + 400]
        rows.extend(
            conn.execute(
                f"SELECT {_COLUMNS} FROM embeddings e "  # noqa: S608
                f"WHERE e.id IN ({','.join('?' * len(chunk))}) AND e.chunk_text IS NOT NULL",
                chunk,
            ).fetchall()
        )
    return rows


def find(
    conn: sqlite3.Connection,
    query: str,
    allowed_items: set[int] | None = None,
    extra_ids: set[int] | None = None,
) -> dict[int, tuple[float, sqlite3.Row]]:
    """Шукає фразу. Повертає {item_id: (схожість, рядок embeddings)}.

    Кандидати беруться з двох джерел. Повнотекстовий індекс відсікає більшість
    бібліотеки за один запит, але шукає слова точно — а саме там, де ASR
    спотворив слово («наївна» проти «наивная»), точного збігу й немає. Тому до
    нього додаються фрагменти, які знайшов смисловий пошук: він до таких
    випадків стійкий, а нечітке зіставлення вже розбереться, чи це справді та
    сама фраза.
    """
    rows = _fts_candidates(conn, query)
    seen = {int(row["id"]) for row in rows}
    if extra_ids:
        rows.extend(_by_ids(conn, extra_ids - seen))

    if not rows:
        return {}

    best: dict[int, tuple[float, sqlite3.Row]] = {}
    for row in rows:
        item_id = int(row["item_id"])
        if allowed_items is not None and item_id not in allowed_items:
            continue
        ratio = similarity(row["chunk_text"] or "", query)
        if ratio < THRESHOLD:
            continue
        if item_id not in best or ratio > best[item_id][0]:
            best[item_id] = (ratio, row)

    return best
