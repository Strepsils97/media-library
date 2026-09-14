"""Фаза 0: замір моделей крос-модального пошуку «текст українською → картинка».

Для кожного запиту з samples/queries.txt, що вказує на картинку, ранжує всі
зображення з samples/images і дивиться, на якому місці опинилася очікувана.

  python scripts/bench_image.py
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "samples" / "images"
QUERIES = ROOT / "samples" / "queries.txt"
OUT = ROOT / "samples" / "bench_image.json"

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")

# Кандидати. Звичайний CLIP розуміє лише англійську, тому в списку тільки
# мультимовні моделі. Поле `text_model` відрізняється від `image_model` там,
# де текстовий енкодер навчали окремо під той самий простір зображень.
CANDIDATES: dict[str, dict] = {
    "clip-b32-multilingual": {
        "image_model": "sentence-transformers/clip-ViT-B-32",
        "text_model": "sentence-transformers/clip-ViT-B-32-multilingual-v1",
        "trust_remote_code": False,
    },
    "jina-clip-v2": {
        "image_model": "jinaai/jina-clip-v2",
        "text_model": None,  # одна модель на обидві модальності
        "trust_remote_code": True,
    },
}


def load_queries() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in QUERIES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        query, target = (part.strip() for part in line.split("|", 1))
        if target.lower().endswith(IMAGE_SUFFIXES):
            pairs.append((query, target))
    return pairs


def evaluate(name: str, spec: dict, images: list[Path], queries: list[tuple[str, str]]) -> dict:
    from sentence_transformers import SentenceTransformer
    from PIL import Image
    import numpy as np

    print(f"{'=' * 70}\n{name}\n{'=' * 70}")

    load_start = time.perf_counter()
    image_model = SentenceTransformer(
        spec["image_model"], trust_remote_code=spec["trust_remote_code"]
    )
    text_model = (
        SentenceTransformer(spec["text_model"], trust_remote_code=spec["trust_remote_code"])
        if spec["text_model"]
        else image_model
    )
    load_s = time.perf_counter() - load_start

    pil_images = [Image.open(p).convert("RGB") for p in images]
    encode_start = time.perf_counter()
    image_vecs = image_model.encode(pil_images, normalize_embeddings=True, show_progress_bar=False)
    encode_s = time.perf_counter() - encode_start

    text_vecs = text_model.encode(
        [q for q, _ in queries], normalize_embeddings=True, show_progress_bar=False
    )

    dim = int(image_vecs.shape[1])
    sims = np.asarray(text_vecs) @ np.asarray(image_vecs).T  # косинус: вектори нормовані
    names = [p.name for p in images]

    ranks: list[int] = []
    details: list[dict] = []
    for i, (query, target) in enumerate(queries):
        order = np.argsort(-sims[i])
        ranked = [names[j] for j in order]
        rank = ranked.index(target) + 1 if target in ranked else len(ranked) + 1
        ranks.append(rank)
        details.append({
            "query": query,
            "expected": target,
            "rank": rank,
            "top3": ranked[:3],
            "score": round(float(sims[i][order[0]]), 4),
        })

    n = len(ranks)
    r1 = sum(r == 1 for r in ranks) / n
    r3 = sum(r <= 3 for r in ranks) / n
    mrr = sum(1 / r for r in ranks) / n

    print(f"  розмірність вектора: {dim}")
    print(f"  завантаження:        {load_s:.1f}s")
    print(f"  кодування {len(images)} картинок: {encode_s:.1f}s")
    print(f"  Recall@1:            {r1:.1%}")
    print(f"  Recall@3:            {r3:.1%}")
    print(f"  MRR:                 {mrr:.3f}")
    print("\n  --- промахи ---")
    for d in details:
        if d["rank"] > 1:
            print(f"  [{d['rank']:>2}] «{d['query']}» → чекали {d['expected']}, дали {d['top3']}")
    print()

    return {
        "dim": dim,
        "load_s": round(load_s, 2),
        "encode_s": round(encode_s, 2),
        "recall_at_1": round(r1, 4),
        "recall_at_3": round(r3, 4),
        "mrr": round(mrr, 4),
        "details": details,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=list(CANDIDATES))
    args = ap.parse_args()

    images = sorted(p for p in IMAGES.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    queries = load_queries()
    print(f"Картинок: {len(images)}, запитів: {len(queries)}\n")

    results = {}
    for name in args.models:
        try:
            results[name] = evaluate(name, CANDIDATES[name], images, queries)
        except Exception as exc:
            print(f"  ПОМИЛКА: {exc}\n")
            results[name] = {"error": str(exc)}

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Результати: {OUT}")


if __name__ == "__main__":
    main()
