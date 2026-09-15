"""Чи виграє поєднання кількох моделей у кожної окремо.

Окремі заміри показали, що моделі помиляються на різних запитах: siglip2
губить «Солдат» і «Зубну пасту», nllb-siglip — «Ікру» й «Ніж з кс». Коли
помилки не збігаються, сума думок зазвичай точніша за будь-яку окрему.

Оцінки моделей напряму непорівнювані (у кожної свій діапазон косинусів), тож
перед складанням вони зводяться до z-оцінок у межах видачі кожної моделі —
тим самим прийомом, що й у пошуку між модальностями.

  python scripts/bench_ensemble.py
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402

from scripts.bench_image import IMAGE_SUFFIXES, IMAGES, QUERIES_EN, load_queries  # noqa: E402
from scripts.bench_multilingual import CANDIDATES, normalize  # noqa: E402

MEMBERS = ["siglip2-large+шаблон", "siglip2-so400m+шаблон", "nllb-siglip-base"]


def similarity_matrix(build, images, texts) -> np.ndarray:
    encode_images, encode_texts = build()
    pil = [Image.open(p).convert("RGB") for p in images]
    vectors = []
    for start in range(0, len(pil), 8):
        vectors.append(encode_images(pil[start : start + 8]))
    image_vecs = normalize(np.vstack(vectors))
    text_vecs = normalize(encode_texts(texts))
    del encode_images, encode_texts
    torch.cuda.empty_cache()
    return text_vecs @ image_vecs.T


def zscore(sims: np.ndarray) -> np.ndarray:
    """Оцінки кожної моделі — у спільну шкалу, по рядку (по запиту)."""
    mean = sims.mean(axis=1, keepdims=True)
    std = sims.std(axis=1, keepdims=True)
    return (sims - mean) / np.clip(std, 1e-6, None)


def metrics(sims: np.ndarray, names, queries) -> dict:
    ranks = []
    for i, (_, target) in enumerate(queries):
        ranked = [names[j] for j in np.argsort(-sims[i])]
        ranks.append(ranked.index(target) + 1 if target in ranked else len(ranked) + 1)
    n = len(ranks)
    return {
        "recall_at_1": sum(r == 1 for r in ranks) / n,
        "recall_at_3": sum(r <= 3 for r in ranks) / n,
        "mrr": sum(1 / r for r in ranks) / n,
        "ranks": ranks,
    }


def main() -> None:
    images = sorted(p for p in IMAGES.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    names = [p.name for p in images]
    queries_uk = load_queries()
    queries_en = load_queries(QUERIES_EN)
    uk_texts = [q for q, _ in queries_uk]

    print(f"Картинок: {len(images)} · запитів: {len(queries_uk)}\n")

    sims: dict[str, np.ndarray] = {}
    for name in MEMBERS:
        started = time.perf_counter()
        sims[name] = similarity_matrix(CANDIDATES[name], images, uk_texts)
        m = metrics(sims[name], names, queries_uk)
        print(
            f"  {m['recall_at_1']:6.1%}  R@3 {m['recall_at_3']:5.1%}  "
            f"MRR {m['mrr']:.3f}  {name}  ({time.perf_counter() - started:.0f}s)"
        )

    print("\n--- поєднання (рівні ваги) ---")
    results = {}
    for size in (2, 3):
        for combo in itertools.combinations(MEMBERS, size):
            merged = sum(zscore(sims[name]) for name in combo) / len(combo)
            m = metrics(merged, names, queries_uk)
            key = " + ".join(c.replace("+шаблон", "") for c in combo)
            results[key] = {k: round(v, 4) for k, v in m.items() if k != "ranks"}
            print(
                f"  {m['recall_at_1']:6.1%}  R@3 {m['recall_at_3']:5.1%}  "
                f"MRR {m['mrr']:.3f}  {key}"
            )

    print("\n--- ваги для найкращої пари ---")
    best_pair = max(
        (c for c in itertools.combinations(MEMBERS, 2)),
        key=lambda c: metrics(
            (zscore(sims[c[0]]) + zscore(sims[c[1]])) / 2, names, queries_uk
        )["recall_at_1"],
    )
    for w in (0.3, 0.4, 0.5, 0.6, 0.7):
        merged = w * zscore(sims[best_pair[0]]) + (1 - w) * zscore(sims[best_pair[1]])
        m = metrics(merged, names, queries_uk)
        print(
            f"  {w:.1f}/{1 - w:.1f}  R@1 {m['recall_at_1']:5.1%}  "
            f"R@3 {m['recall_at_3']:5.1%}  MRR {m['mrr']:.3f}"
        )
    print(f"  пара: {' + '.join(best_pair)}")

    (ROOT / "samples" / "bench_ensemble.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
