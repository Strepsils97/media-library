"""Теплова підсвітка: чи піднімається потрібне місце над тлом тексту."""

import numpy as np

from backend.app.search.heat import word_heat


class _Embedder:
    """Заглушка: вважає близькими ті вікна, де є слово-маркер.

    Справжня модель тут не потрібна — перевіряється не її якість, а те, що
    з оцінок виходить розмітка: пороги, склеювання, межі слів.
    """

    def __init__(self, marker: str) -> None:
        self.marker = marker

    def encode_texts(self, texts):
        return np.array(
            [[1.0, 0.0] if self.marker in t.casefold() else [0.0, 1.0] for t in texts],
            dtype=np.float32,
        )

    def encode_queries(self, texts):
        return np.array([[1.0, 0.0]] * len(texts), dtype=np.float32)


# Слова з «кав» усередині (як-от «цікавого») тут не до речі: заглушка шукає
# саме цей відтинок, і текст має перевіряти розмітку, а не її дірки.
TEXT = (
    "Ми довго йшли повз порожні будинки і мовчали про все на світі, "
    "а потім я нарешті купив каву на розі, і день став кращим, "
    "далі знову нічого нового не відбувалося аж до самого вечора"
)


def test_marks_the_matching_place():
    spans = word_heat(TEXT, "кава", _Embedder("кав"))
    assert spans, "потрібне місце має бути позначене"
    marked = " ".join(TEXT[start:end] for start, end, _ in spans)
    assert "каву" in marked


def test_leaves_the_rest_alone():
    # Підсвітити весь текст рівним шаром означало б не сказати нічого.
    spans = word_heat(TEXT, "кава", _Embedder("кав"))
    covered = sum(end - start for start, end, _ in spans)
    assert covered < len(TEXT) / 3


def test_nothing_to_mark_when_text_is_uniform():
    # Жодне вікно не виділяється — значить, і підсвічувати нема чого.
    spans = word_heat(TEXT, "кава", _Embedder("не-трапляється"))
    assert spans == []


def test_spans_stay_inside_the_text():
    spans = word_heat(TEXT, "кава", _Embedder("кав"))
    for start, end, value in spans:
        assert 0 <= start < end <= len(TEXT)
        assert 0.0 < value <= 1.0


def test_short_text_is_skipped():
    assert word_heat("два слова", "кава", _Embedder("кав")) == []
    assert word_heat("", "кава", _Embedder("кав")) == []
    assert word_heat(TEXT, "", _Embedder("кав")) == []
