from backend.app.search.highlight import find_span


def _marked(text: str, query: str) -> str | None:
    span = find_span(text, query)
    if span is None:
        return None
    start, end = span
    return text[start:end]


def test_finds_exact_words():
    text = "привозять холодне, і та шавуха, яку я брала в четвер, була несмачна"
    assert _marked(text, "шавуха несмачна") == "шавуха, яку я брала в четвер, була несмачна"


def test_matches_across_inflection():
    # Порівняння по префіксу: «шавуху» має знаходитися за запитом «шавуха».
    assert _marked("я брала шавуху вчора", "шавуха") == "шавуху"


def test_returns_none_without_lexical_overlap():
    # Збіг міг бути суто смисловим — тоді підсвічувати нема чого,
    # і вигадувати діапазон не можна.
    assert find_span("Ну и вообще тут дети под захистом", "діти в Німеччині") is None


def test_prefers_dense_cluster_over_spread():
    text = "кава на початку, потім багато всякого тексту без нічого, і кава з молоком"
    marked = _marked(text, "кава з молоком")
    assert marked == "кава з молоком"


def test_empty_inputs():
    assert find_span("", "щось") is None
    assert find_span("щось", "") is None


def test_short_words_ignored():
    # Слова коротші за три літери надто часті, щоб на них спиратися.
    assert find_span("я і ти", "я") is None


def test_matches_short_words_across_inflection():
    # «кава» і «кавою» розходяться на четвертій літері, і порівняння по
    # чотирьох перших не знаходило нічого: запит «кава» не підсвічував у
    # тексті жодної форми слова.
    assert _marked("я б узяв морозиво з кавою", "кава") == "кавою"
    assert _marked("дві кави, будь ласка", "кава") == "кави"


def test_short_prefix_does_not_glue_unrelated_words():
    # Послаблення стосується лише коротких слів: довгі порівнюються
    # по-старому, інакше «магазин» чіплявся б до «магії».
    assert find_span("тут була якась магія", "магазин") is None
