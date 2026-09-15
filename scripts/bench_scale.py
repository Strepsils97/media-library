"""Як пошук поводиться на бібліотеці реального розміру.

Заміри якості робилися на 56 записах. Це нічого не каже про те, що буде на
десятках тисяч: kNN у sqlite-vec — повний перебір, а нечітке зіставлення
фрази лінійне від кількості кандидатів. Тут будується синтетична бібліотека
й міряється час пошуку по частинах.

Моделі підмінюються заглушками: перевіряється шлях даних, а не якість.

  python scripts/bench_scale.py --items 5000
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from backend.app.config import Settings  # noqa: E402

WORDS = (
    "магазин каса цінник холодне шавуха четвер несмачна кухня вокзал сусідка "
    "коробка папірець пароль заметки німеччина діти захист голос кросівки "
    "енергія кока кола євро цукор наклейки булки ікра палички грейпфрут "
    "штуки скидки мама бабуся погода жарко машина квартира оренда графік"
).split()


def sentence(rng: random.Random, length: int = 40) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(length))


def build(settings: Settings, items: int, seed: int = 7) -> dict[str, int]:
    from backend.app.db import repo
    from backend.app.db.connection import IMAGE_SPACES, SPACES, TEXT_SPACE, init_db
    from backend.app.ingest.storage import Prepared

    init_db()
    rng = random.Random(seed)
    counts = {"items": 0, "vectors": 0}

    for index in range(items):
        # Приблизно як у реальній бібліотеці: більшість — картинки,
        # менша частина — відео з кадрами й транскрипцією.
        kind = "image" if index % 3 else ("video" if index % 2 else "text")
        item_id = repo.create_item(
            Prepared(
                kind=kind,
                label=f"запис {index}",
                stored_path=f"ab/{index}.bin",
                source_path=None,
                content_hash=f"hash{index}",
                mime=None,
                size_bytes=1,
                created_at="2026-01-01T00:00:00+00:00",
                duration_s=30.0 if kind == "video" else None,
                text_content=sentence(rng) if kind == "text" else None,
            )
        )
        counts["items"] += 1

        if kind in ("image", "video"):
            frames = 1 if kind == "image" else 4
            for frame in range(frames):
                frame_id = (
                    repo.add_frame(item_id, frame * 7.0, f"ab/{index}_{frame}.webp")
                    if kind == "video"
                    else None
                )
                for space in IMAGE_SPACES:
                    vector = np.random.default_rng(index * 10 + frame).standard_normal(
                        SPACES[space]
                    )
                    vector /= np.linalg.norm(vector)
                    repo.add_embedding(item_id, space, vector, frame_id=frame_id)
                    counts["vectors"] += 1

        if kind in ("video", "text"):
            for chunk in range(2):
                vector = np.random.default_rng(index * 100 + chunk).standard_normal(
                    SPACES[TEXT_SPACE]
                )
                vector /= np.linalg.norm(vector)
                repo.add_embedding(
                    item_id, TEXT_SPACE, vector,
                    chunk_ix=chunk, chunk_text=sentence(rng), ts_s=chunk * 15.0,
                )
                counts["vectors"] += 1

    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=int, default=5000)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()

    import tempfile

    from backend.app import config

    tmp = Path(tempfile.mkdtemp(prefix="medialib-scale-"))
    settings = Settings(data_dir=tmp)
    settings.ensure_dirs()

    # Підміняємо налаштування всюди, де їх читають напряму.
    from backend.app.db import connection
    from backend.app.ingest import storage

    for module in (config, connection, storage):
        module.get_settings = lambda s=settings: s  # type: ignore[assignment]

    from backend.app.ml import registry

    registry.use_stubs()

    print(f"Будую бібліотеку на {args.items} записів у {tmp}…")
    started = time.perf_counter()
    counts = build(settings, args.items)
    print(
        f"  {counts['items']} записів · {counts['vectors']} векторів · "
        f"{time.perf_counter() - started:.0f}s"
    )

    db_size = settings.db_path.stat().st_size / 1024**2
    print(f"  база: {db_size:.0f} МБ\n")

    from backend.app.search import phrase
    from backend.app.search.query import Filters, search

    queries = [
        ("коротке", "шавуха"),
        ("фраза", "холодне і та шавуха яку я брала в четвер"),
        ("довга фраза", " ".join(WORDS[:12])),
        ("з фільтром", "шавуха"),
    ]

    print(f"{'запит':<14} {'медіана':>9} {'найгірше':>10} {'знайдено':>9}")
    print("-" * 46)
    for label, text in queries:
        filters = Filters(query=text, kinds=["video"] if label == "з фільтром" else [])
        # Перший прогін прогріває калібрування — його не міряємо.
        search(filters)
        times = []
        for _ in range(args.repeats):
            start = time.perf_counter()
            result = search(filters)
            times.append((time.perf_counter() - start) * 1000)
        times.sort()
        print(
            f"{label:<14} {times[len(times) // 2]:>8.0f}мс {times[-1]:>9.0f}мс "
            f"{result['total']:>9}"
        )

    print("\n--- окремо: нечітке зіставлення фрази ---")
    long_text = sentence(random.Random(1), 400)
    for label, needle in (("одне слово", "шавуха"), ("фраза з 8 слів", " ".join(WORDS[:8]))):
        start = time.perf_counter()
        for _ in range(100):
            phrase.similarity(long_text, needle)
        print(f"  {label:<16} {(time.perf_counter() - start) * 10:.2f} мс на фрагмент")

    print(f"\nТимчасова бібліотека лишилась у {tmp} — приберіть, коли не потрібна.")


if __name__ == "__main__":
    main()
