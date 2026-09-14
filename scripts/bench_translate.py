"""Фаза 0: перевірка гіпотези «перекласти запит на англійську, тоді шукати».

Замір показав, що візуальна вежа SigLIP2 дає 90% Recall@1 на англійських
запитах і 29% на українських. Отже вузьке місце — мова, а не картинки.
Цей скрипт міряє, скільки з тих 90% лишиться після машинного перекладу.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoModelForSeq2SeqLM, AutoProcessor, AutoTokenizer

from scripts.bench_image import IMAGE_SUFFIXES, IMAGES, load_queries

def as_tensor(out):
    """transformers 5 повертає то тензор, то об'єкт виходу."""
    return out.pooler_output if hasattr(out, "pooler_output") else out


MT_CANDIDATES = ["Helsinki-NLP/opus-mt-uk-en", "Helsinki-NLP/opus-mt-mul-en"]
VISION = "google/siglip2-base-patch16-224"


def translate(model_name: str, texts: list[str]) -> tuple[list[str], float, float]:
    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_name).eval()
    params_m = sum(p.numel() for p in model.parameters()) / 1e6

    start = time.perf_counter()
    with torch.inference_mode():
        enc = tok(texts, return_tensors="pt", padding=True, truncation=True)
        out = model.generate(**enc, max_new_tokens=40, num_beams=2)
    elapsed = time.perf_counter() - start
    return tok.batch_decode(out, skip_special_tokens=True), elapsed, params_m


def main() -> None:
    queries = load_queries()
    texts = [q for q, _ in queries]
    images = sorted(p for p in IMAGES.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    names = [p.name for p in images]

    proc = AutoProcessor.from_pretrained(VISION)
    vision = AutoModel.from_pretrained(VISION).eval()
    with torch.inference_mode():
        pil = [Image.open(p).convert("RGB") for p in images]
        iv = as_tensor(vision.get_image_features(**proc(images=pil, return_tensors="pt")))
        iv = torch.nn.functional.normalize(iv, dim=-1).numpy()

    for mt_name in MT_CANDIDATES:
        print(f"\n{'=' * 70}\n{mt_name}\n{'=' * 70}")
        try:
            translated, elapsed, params_m = translate(mt_name, texts)
        except Exception as exc:
            print(f"  ПОМИЛКА: {exc}")
            continue

        print(f"  параметрів: {params_m:.0f}M")
        print(f"  переклад {len(texts)} запитів: {elapsed:.1f}s "
              f"({elapsed / len(texts) * 1000:.0f} мс на запит)\n")
        for src, dst in zip(texts, translated):
            print(f"    {src:44} -> {dst}")

        with torch.inference_mode():
            tv = as_tensor(vision.get_text_features(**proc(
                text=translated, padding="max_length", truncation=True, return_tensors="pt")))
            tv = torch.nn.functional.normalize(tv, dim=-1).numpy()

        sims = tv @ iv.T
        ranks, misses = [], []
        for i, (query, target) in enumerate(queries):
            order = np.argsort(-sims[i])
            ranked = [names[j] for j in order]
            rank = ranked.index(target) + 1 if target in ranked else len(ranked) + 1
            ranks.append(rank)
            if rank > 1:
                misses.append((rank, query, translated[i], target, ranked[:3]))

        n = len(ranks)
        print(f"\n  Recall@1: {sum(r == 1 for r in ranks) / n:.1%}")
        print(f"  Recall@3: {sum(r <= 3 for r in ranks) / n:.1%}")
        print(f"  MRR:      {sum(1 / r for r in ranks) / n:.3f}")
        print("  --- промахи ---")
        for rank, query, tr, target, top in misses:
            print(f"  [{rank:>2}] «{query}» -> «{tr}» | чекали {target}, дали {top}")


if __name__ == "__main__":
    main()
