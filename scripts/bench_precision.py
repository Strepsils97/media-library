"""Порівняння fp16-ваг застосунку з fp32-заміром Фази 0.

Метрика й дані ті самі, що в scripts/bench_vision.py, тому число прямо
порівнюване з тим, що записано в PLAN.md для fp32.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from backend.app.ml.registry import get_image_embedder  # noqa: E402
from scripts.bench_image import IMAGE_SUFFIXES, IMAGES, load_queries  # noqa: E402

FP32_REFERENCE = {"recall_at_1": 0.762, "recall_at_3": 0.857, "mrr": 0.825}


def main() -> None:
    queries = load_queries()
    images = sorted(p for p in IMAGES.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    names = [p.name for p in images]

    embedder = get_image_embedder()
    print(f"пристрій: {embedder.device} · розмірність: {embedder.dim}")
    print(f"картинок: {len(images)} · запитів: {len(queries)}\n")

    # Батчами, бо саме так працює інжест — щоб міряти те, що реально діє.
    vectors = []
    for start in range(0, len(images), 8):
        batch = [Image.open(p).convert("RGB") for p in images[start : start + 8]]
        vectors.append(embedder.encode_images(batch))
    image_vecs = np.vstack(vectors)

    text_vecs = embedder.encode_queries([q for q, _ in queries])
    sims = text_vecs @ image_vecs.T

    ranks = []
    misses = []
    for i, (query, target) in enumerate(queries):
        ranked = [names[j] for j in np.argsort(-sims[i])]
        rank = ranked.index(target) + 1 if target in ranked else len(ranked) + 1
        ranks.append(rank)
        if rank > 1:
            misses.append((rank, query, target, ranked[:3]))

    n = len(ranks)
    got = {
        "recall_at_1": sum(r == 1 for r in ranks) / n,
        "recall_at_3": sum(r <= 3 for r in ranks) / n,
        "mrr": sum(1 / r for r in ranks) / n,
    }

    print(f"{'метрика':<12} {'fp32':>8} {'fp16':>8} {'різниця':>10}")
    for key, label in [("recall_at_1", "Recall@1"), ("recall_at_3", "Recall@3"), ("mrr", "MRR")]:
        ref, cur = FP32_REFERENCE[key], got[key]
        fmt = (lambda v: f"{v:.1%}") if key != "mrr" else (lambda v: f"{v:.3f}")
        print(f"{label:<12} {fmt(ref):>8} {fmt(cur):>8} {cur - ref:>+10.3f}")

    print("\n--- промахи fp16 ---")
    for rank, query, target, top in misses:
        print(f"  [{rank:>2}] «{query}» → чекали {target}, дали {top}")

    (ROOT / "samples" / "bench_precision.json").write_text(
        json.dumps({"fp32": FP32_REFERENCE, "fp16": got}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
