"""Пошук кращої моделі для українських запитів до картинок.

Поточна (siglip2-large + англійський шаблон) дає 76.2% Recall@1 при стелі
95.2% на ручному перекладі. Розрив — плата за те, що модель навчали переважно
на англійській. Тут перевіряються моделі, які робилися саме під мультимовність.

  python scripts/bench_multilingual.py
  python scripts/bench_multilingual.py --models nllb-siglip-large
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402

from scripts.bench_image import IMAGE_SUFFIXES, IMAGES, QUERIES_EN, load_queries  # noqa: E402

TEMPLATE = "a photo of {}."
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def as_tensor(out):
    return out.pooler_output if hasattr(out, "pooler_output") else out


# --- реалізації ------------------------------------------------------------


def siglip2(model_id: str, use_template: bool):
    """SigLIP2 через transformers. Шаблон вмикається окремо — саме він дав
    поточній моделі стрибок з 28.6% до 76.2%."""

    def build():
        from transformers import AutoModel, AutoProcessor

        processor = AutoProcessor.from_pretrained(model_id)
        model = AutoModel.from_pretrained(model_id, dtype=torch.float16).eval().to(DEVICE)

        def encode_images(images):
            with torch.inference_mode():
                batch = processor(images=images, return_tensors="pt").to(DEVICE)
                return as_tensor(model.get_image_features(**batch)).float().cpu().numpy()

        def encode_texts(texts):
            prepared = [TEMPLATE.format(t.lower()) for t in texts] if use_template else texts
            with torch.inference_mode():
                batch = processor(
                    text=prepared, padding="max_length", truncation=True, return_tensors="pt"
                ).to(DEVICE)
                return as_tensor(model.get_text_features(**batch)).float().cpu().numpy()

        return encode_images, encode_texts

    return build


def open_clip_model(model_name: str, pretrained: str | None):
    """Моделі з екосистеми open_clip — там живуть nllb-clip та подібні."""

    def build():
        import open_clip

        model, _, preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained
        )
        model = model.eval().to(DEVICE)
        tokenizer = open_clip.get_tokenizer(model_name)

        def encode_images(images):
            batch = torch.stack([preprocess(img) for img in images]).to(DEVICE)
            with torch.inference_mode():
                return model.encode_image(batch).float().cpu().numpy()

        def encode_texts(texts):
            tokens = tokenizer(texts).to(DEVICE)
            with torch.inference_mode():
                return model.encode_text(tokens).float().cpu().numpy()

        return encode_images, encode_texts

    return build


def mclip(text_id: str, image_name: str, pretrained: str):
    """M-CLIP: багатомовний текстовий енкодер, донавчений під простір CLIP."""

    def build():
        import open_clip
        from multilingual_clip import pt_multilingual_clip
        from transformers import AutoTokenizer

        text_model = pt_multilingual_clip.MultilingualCLIP.from_pretrained(text_id)
        text_model = text_model.eval().to(DEVICE)
        tokenizer = AutoTokenizer.from_pretrained(text_id)

        image_model, _, preprocess = open_clip.create_model_and_transforms(
            image_name, pretrained=pretrained
        )
        image_model = image_model.eval().to(DEVICE)

        def encode_images(images):
            batch = torch.stack([preprocess(img) for img in images]).to(DEVICE)
            with torch.inference_mode():
                return image_model.encode_image(batch).float().cpu().numpy()

        def encode_texts(texts):
            with torch.inference_mode():
                return text_model.forward(texts, tokenizer).float().cpu().numpy()

        return encode_images, encode_texts

    return build


CANDIDATES = {
    "siglip2-large+шаблон": siglip2("google/siglip2-large-patch16-256", True),
    "siglip2-so400m+шаблон": siglip2("google/siglip2-so400m-patch16-384", True),
    "nllb-siglip-large": open_clip_model("nllb-clip-large-siglip", "v1"),
    "nllb-siglip-base": open_clip_model("nllb-clip-base-siglip", "v1"),
    "mclip-xlmr-L+ViT-L-14": mclip(
        "M-CLIP/XLM-Roberta-Large-Vit-L-14", "ViT-L-14", "openai"
    ),
}


def normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    return v / np.clip(np.linalg.norm(v, axis=1, keepdims=True), 1e-9, None)


def evaluate(name: str, build, images, names, queries_uk, queries_en) -> dict:
    print(f"\n{'=' * 74}\n{name}\n{'=' * 74}")
    started = time.perf_counter()
    encode_images, encode_texts = build()
    print(f"  завантаження: {time.perf_counter() - started:.1f}s · {DEVICE}")

    pil = [Image.open(p).convert("RGB") for p in images]
    started = time.perf_counter()
    vectors = []
    for start in range(0, len(pil), 8):
        vectors.append(encode_images(pil[start : start + 8]))
    image_vecs = normalize(np.vstack(vectors))
    encode_s = time.perf_counter() - started
    print(f"  кодування {len(pil)} картинок: {encode_s:.1f}s · розмірність {image_vecs.shape[1]}")

    result = {"dim": int(image_vecs.shape[1]), "encode_s": round(encode_s, 2)}

    for label, queries in (("uk", queries_uk), ("en", queries_en)):
        text_vecs = normalize(encode_texts([q for q, _ in queries]))
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
        metrics = {
            "recall_at_1": sum(r == 1 for r in ranks) / n,
            "recall_at_3": sum(r <= 3 for r in ranks) / n,
            "mrr": sum(1 / r for r in ranks) / n,
        }
        result[label] = {k: round(v, 4) for k, v in metrics.items()}
        print(
            f"  {'українською' if label == 'uk' else 'англійською (стеля)'}: "
            f"R@1 {metrics['recall_at_1']:5.1%}  R@3 {metrics['recall_at_3']:5.1%}  "
            f"MRR {metrics['mrr']:.3f}"
        )
        if label == "uk":
            for rank, query, target, top in misses:
                print(f"      [{rank:>2}] «{query}» → чекали {target}, дали {top}")

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=list(CANDIDATES))
    args = parser.parse_args()

    images = sorted(p for p in IMAGES.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    names = [p.name for p in images]
    queries_uk = load_queries()
    queries_en = load_queries(QUERIES_EN)
    print(f"Картинок: {len(images)} · запитів: {len(queries_uk)}")

    results = {}
    for name in args.models:
        try:
            results[name] = evaluate(
                name, CANDIDATES[name], images, names, queries_uk, queries_en
            )
        except Exception as exc:  # noqa: BLE001 — кандидат може просто не завестися
            print(f"  ПОМИЛКА: {exc}")
            traceback.print_exc(limit=2)
            results[name] = {"error": str(exc)}

    out = ROOT / "samples" / "bench_multilingual.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'=' * 74}\nПідсумок (Recall@1 українською)\n{'=' * 74}")
    ranked = sorted(
        ((n, r) for n, r in results.items() if "uk" in r),
        key=lambda kv: -kv[1]["uk"]["recall_at_1"],
    )
    for name, r in ranked:
        print(
            f"  {r['uk']['recall_at_1']:6.1%}  (стеля {r['en']['recall_at_1']:5.1%})  "
            f"dim {r['dim']:>4}  {name}"
        )


if __name__ == "__main__":
    main()
