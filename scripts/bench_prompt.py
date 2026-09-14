"""Фаза 0: вплив шаблону запиту та якості перекладу на пошук по картинках."""
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

from scripts.bench_image import IMAGE_SUFFIXES, IMAGES, QUERIES_EN, load_queries

VISION = "google/siglip2-base-patch16-224"
NLLB = "facebook/nllb-200-distilled-600M"
TEMPLATE = "a photo of {}."


def as_tensor(out):
    return out.pooler_output if hasattr(out, "pooler_output") else out


def score(vision, proc, iv, names, queries, texts, label):
    with torch.inference_mode():
        tv = as_tensor(vision.get_text_features(**proc(
            text=texts, padding="max_length", truncation=True, return_tensors="pt")))
        tv = torch.nn.functional.normalize(tv, dim=-1).numpy()
    sims = tv @ iv.T
    ranks = []
    for i, (_, target) in enumerate(queries):
        ranked = [names[j] for j in np.argsort(-sims[i])]
        ranks.append(ranked.index(target) + 1 if target in ranked else len(ranked) + 1)
    n = len(ranks)
    print(f"  {label:38} R@1 {sum(r == 1 for r in ranks) / n:5.1%}   "
          f"R@3 {sum(r <= 3 for r in ranks) / n:5.1%}   "
          f"MRR {sum(1 / r for r in ranks) / n:.3f}")
    return ranks


def main() -> None:
    queries_uk = load_queries()
    queries_en = load_queries(QUERIES_EN)
    uk_texts = [q for q, _ in queries_uk]
    en_texts = [q for q, _ in queries_en]

    proc = AutoProcessor.from_pretrained(VISION)
    vision = AutoModel.from_pretrained(VISION).eval()
    images = sorted(p for p in IMAGES.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    names = [p.name for p in images]
    with torch.inference_mode():
        pil = [Image.open(p).convert("RGB") for p in images]
        iv = as_tensor(vision.get_image_features(**proc(images=pil, return_tensors="pt")))
        iv = torch.nn.functional.normalize(iv, dim=-1).numpy()

    print("\n--- вплив шаблону, без перекладу ---")
    score(vision, proc, iv, names, queries_uk, uk_texts, "українською, як є")
    score(vision, proc, iv, names, queries_uk,
          [TEMPLATE.format(t.lower()) for t in uk_texts], "українською + шаблон")
    score(vision, proc, iv, names, queries_en, en_texts, "англійською вручну, як є")
    score(vision, proc, iv, names, queries_en,
          [TEMPLATE.format(t.lower()) for t in en_texts], "англійською вручну + шаблон")

    print(f"\n--- машинний переклад: {NLLB} ---")
    tok = AutoTokenizer.from_pretrained(NLLB, src_lang="ukr_Cyrl")
    mt = AutoModelForSeq2SeqLM.from_pretrained(NLLB).eval()
    print(f"  параметрів: {sum(p.numel() for p in mt.parameters()) / 1e6:.0f}M")

    start = time.perf_counter()
    with torch.inference_mode():
        enc = tok(uk_texts, return_tensors="pt", padding=True, truncation=True)
        out = mt.generate(**enc, forced_bos_token_id=tok.convert_tokens_to_ids("eng_Latn"),
                          max_new_tokens=48, num_beams=4)
    translated = tok.batch_decode(out, skip_special_tokens=True)
    elapsed = time.perf_counter() - start
    print(f"  переклад {len(uk_texts)} запитів: {elapsed:.1f}s "
          f"({elapsed / len(uk_texts) * 1000:.0f} мс на запит)\n")
    for src, dst in zip(uk_texts, translated):
        print(f"    {src:44} -> {dst}")
    print()
    score(vision, proc, iv, names, queries_uk, translated, "NLLB, як є")
    score(vision, proc, iv, names, queries_uk,
          [TEMPLATE.format(t.lower()) for t in translated], "NLLB + шаблон")


if __name__ == "__main__":
    main()
