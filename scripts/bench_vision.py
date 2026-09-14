"""Фаза 0: вибір візуальної вежі та способу формулювання запиту."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor

from scripts.bench_image import IMAGE_SUFFIXES, IMAGES, QUERIES_EN, load_queries

# Ансамбль шаблонів — стандартний прийом для CLIP-подібних моделей: усереднення
# кількох формулювань стабільніше за одне.
TEMPLATES = [
    "a photo of {}.",
    "a picture of {}.",
    "an image showing {}.",
    "{}.",
]

VISIONS = {
    "siglip2-base": "google/siglip2-base-patch16-224",
    "siglip2-large": "google/siglip2-large-patch16-256",
    "siglip2-so400m": "google/siglip2-so400m-patch16-384",
}


def as_tensor(out):
    return out.pooler_output if hasattr(out, "pooler_output") else out


def encode_text(vision, proc, texts):
    with torch.inference_mode():
        out = as_tensor(vision.get_text_features(**proc(
            text=texts, padding="max_length", truncation=True, return_tensors="pt")))
        return torch.nn.functional.normalize(out, dim=-1).numpy()


def metrics(sims, names, queries):
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


def report(label, m):
    print(f"  {label:34} R@1 {m['recall_at_1']:5.1%}   "
          f"R@3 {m['recall_at_3']:5.1%}   MRR {m['mrr']:.3f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["siglip2-base", "siglip2-large"])
    args = ap.parse_args()

    queries_uk = load_queries()
    queries_en = load_queries(QUERIES_EN)
    uk = [q for q, _ in queries_uk]
    en = [q for q, _ in queries_en]

    images = sorted(p for p in IMAGES.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    names = [p.name for p in images]
    pil = [Image.open(p).convert("RGB") for p in images]

    results = {}
    for key in args.models:
        name = VISIONS[key]
        print(f"\n{'=' * 72}\n{key}  ({name})\n{'=' * 72}")

        t0 = time.perf_counter()
        proc = AutoProcessor.from_pretrained(name)
        vision = AutoModel.from_pretrained(name).eval()
        load_s = time.perf_counter() - t0
        params_m = sum(p.numel() for p in vision.parameters()) / 1e6

        t0 = time.perf_counter()
        with torch.inference_mode():
            iv = as_tensor(vision.get_image_features(**proc(images=pil, return_tensors="pt")))
            iv = torch.nn.functional.normalize(iv, dim=-1).numpy()
        encode_s = time.perf_counter() - t0

        print(f"  параметрів: {params_m:.0f}M · розмірність: {iv.shape[1]} · "
              f"завантаження {load_s:.1f}s · {len(images)} картинок за {encode_s:.1f}s\n")

        entry = {"params_m": round(params_m), "dim": int(iv.shape[1]),
                 "encode_s": round(encode_s, 2), "variants": {}}

        plain_uk = metrics(encode_text(vision, proc, uk) @ iv.T, names, queries_uk)
        report("українською, як є", plain_uk)

        tpl_uk = metrics(
            encode_text(vision, proc, [TEMPLATES[0].format(t.lower()) for t in uk]) @ iv.T,
            names, queries_uk)
        report("українською + один шаблон", tpl_uk)

        # Ансамбль: середнє нормованих векторів по всіх формулюваннях.
        stack = np.stack([
            encode_text(vision, proc, [tpl.format(t.lower()) for t in uk])
            for tpl in TEMPLATES
        ])
        ens = stack.mean(axis=0)
        ens /= np.linalg.norm(ens, axis=1, keepdims=True)
        ens_uk = metrics(ens @ iv.T, names, queries_uk)
        report("українською + ансамбль шаблонів", ens_uk)

        ceil_en = metrics(encode_text(vision, proc, en) @ iv.T, names, queries_en)
        report("англійською вручну (стеля)", ceil_en)

        for label, m in [("plain_uk", plain_uk), ("template_uk", tpl_uk),
                         ("ensemble_uk", ens_uk), ("ceiling_en", ceil_en)]:
            entry["variants"][label] = {k: round(v, 4) for k, v in m.items() if k != "ranks"}
        results[key] = entry
        del vision

    out = ROOT / "samples" / "bench_vision.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nРезультати: {out}")


if __name__ == "__main__":
    main()
