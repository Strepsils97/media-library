"""Нечіткий пошук фрази — головне, щоб він терпів помилки розпізнавання."""

import pytest

from backend.app.search import phrase


def test_fold_unifies_spelling():
    # Українське «і» та російське «и» звучать по-різному, але ASR між ними
    # плутається, а для пошуку фрази ця різниця не має значення.
    assert phrase.fold("Німеччина") == phrase.fold("Нимеччина")
    assert phrase.fold("дев'ятої") == phrase.fold("девятої")
    assert phrase.fold("Привіт, світе!") == "привит свите"


@pytest.mark.parametrize(
    ("transcript", "query"),
    [
        # Так ці фрази справді звучать у транскрипціях із samples/.
        ("Купила я кока-колы за евро, зеро цукор", "купила кока колу за євро"),
        ("Я пішла путаю, де що знаходиться", "плутаю де що знаходиться"),
        ("Боже, какая наивная дурочка просто", "наївна дурочка"),
        ("У всіх-слаць це нормально. Це нормально", "срач це нормально"),
    ],
)
def test_finds_phrase_despite_recognition_errors(transcript, query):
    assert phrase.similarity(transcript, query) >= phrase.THRESHOLD


def test_unrelated_text_stays_below_threshold():
    text = "Значить, стоїмо ми в тому магазині на касі, і вона дивиться на цінник"
    assert phrase.similarity(text, "діти грають у футбол") < phrase.THRESHOLD


def test_exact_match_is_near_one():
    text = "у мене вдома завжди срач і нічого"
    assert phrase.similarity(text, "вдома завжди срач") > 0.95


def test_score_mapping():
    assert phrase.to_score(phrase.THRESHOLD - 0.01) == 0.0
    assert phrase.to_score(1.0) == pytest.approx(100.0)
    # Монотонність: кращий збіг не може дати нижчу оцінку.
    assert phrase.to_score(0.9) > phrase.to_score(0.8)
    assert phrase.to_score(0.8) > phrase.to_score(phrase.THRESHOLD)


def test_long_phrase_outweighs_single_word():
    """Одне слово в довгій транскрипції може трапитися випадково, фраза — ні.

    Без цієї різниці запит «ікра» витягував відео про покупки нагору лише
    тому, що там раз прозвучало це слово.
    """
    assert phrase.to_score(1.0, words=1) < phrase.to_score(0.85, words=4)
    assert phrase.to_score(1.0, words=1) < phrase.to_score(1.0, words=2)
    assert phrase.to_score(1.0, words=2) < phrase.to_score(1.0, words=3)


def test_confident_phrase_beats_typical_semantic_score():
    # Смислові збіги на реальних даних тримаються в межах 95-98, тож
    # упевнений збіг фрази має підніматися вище — інакше дослівно набрана
    # фраза з транскрипції програвала б випадковій картинці.
    assert phrase.to_score(0.85, words=4) >= 99.0


def test_empty_inputs():
    assert phrase.similarity("", "щось") == 0.0
    assert phrase.similarity("щось", "") == 0.0


def test_single_word_query_works():
    assert phrase.similarity("там була якась шавуха холодна", "шавуха") >= phrase.THRESHOLD


def test_finds_in_database(library):
    from backend.app.db import repo
    from backend.app.db.connection import get_connection, init_db
    from backend.app.ingest.storage import Prepared

    init_db()
    item_id = repo.create_item(
        Prepared(kind="text", label="нотатка", stored_path=None, source_path=None,
                 content_hash="h1", mime="text/plain", size_bytes=1,
                 created_at="2026-01-01T00:00:00+00:00",
                 text_content="і та шавуха яку я брала в четвер була несмачна")
    )
    repo.add_embedding(
        item_id, "text", [0.1] * 768, chunk_ix=0,
        chunk_text="і та шавуха яку я брала в четвер була несмачна",
    )

    found = phrase.find(get_connection(), "шавуха була несмачна")
    assert item_id in found
    ratio, row = found[item_id]
    assert ratio >= phrase.THRESHOLD
    assert row["item_id"] == item_id

    assert phrase.find(get_connection(), "гірський краєвид на світанку") == {}


def test_respects_item_filter(library):
    from backend.app.db import repo
    from backend.app.db.connection import get_connection, init_db
    from backend.app.ingest.storage import Prepared

    init_db()
    item_id = repo.create_item(
        Prepared(kind="text", label="нотатка", stored_path=None, source_path=None,
                 content_hash="h2", mime="text/plain", size_bytes=1,
                 created_at="2026-01-01T00:00:00+00:00", text_content="шавуха несмачна")
    )
    repo.add_embedding(item_id, "text", [0.1] * 768, chunk_ix=0,
                       chunk_text="шавуха несмачна")

    assert phrase.find(get_connection(), "шавуха несмачна", allowed_items={item_id})
    # Фільтри пошуку мають діяти й на фразовий прохід.
    assert phrase.find(get_connection(), "шавуха несмачна", allowed_items=set()) == {}
