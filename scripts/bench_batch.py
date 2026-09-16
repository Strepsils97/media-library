"""Скільки коштує кодувати кадри по одному замість пачки.

Обробка відео ембедить кожен кадр окремим викликом. Відеокарта при цьому
здебільшого простоює: на 384-піксельну картинку роботи менше, ніж на накладні
витрати виклику. Тут перевіряється, чи справді пачка виграє, наскільки, і що
при цьому стається з пам'яттю — бо саме через пам'ять записи обробляються по
одному, і вилізти за 8 ГБ заради цього прискорення було б поганим обміном.

  python scripts/bench_batch.py --frames "C:/Users/didyk/media-library/data/frames"
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BATCHES = (1, 2, 4, 6, 12)


def vram_gb() -> float:
    import torch

    if not torch.cuda.is_available():
        return 0.0
    return torch.cuda.max_memory_allocated() / 1024**3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", required=True, help="тека з кадрами (.webp)")
    parser.add_argument("--count", type=int, default=12, help="скільки кадрів брати")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    from PIL import Image

    paths = sorted(Path(args.frames).rglob("*.webp"))[: args.count]
    if len(paths) < 2:
        raise SystemExit(f"У {args.frames} замало кадрів: {len(paths)}")

    from backend.app.ml.registry import get_image_embedder

    embedder = get_image_embedder()
    images = [Image.open(p).convert("RGB") for p in paths]
    print(f"кадрів: {len(images)} · пристрій: {embedder.device}\n")

    # Перший прогін розігріває ядра CUDA — його час ні про що не говорить.
    embedder.encode_images(images[:1])

    import torch

    print(f"{'пачка':>6} {'час на кадр':>13} {'усього':>10} {'пік пам.яті':>13}")
    print("-" * 46)
    baseline = None
    for size in BATCHES:
        if size > len(images):
            continue
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()

        times = []
        for _ in range(args.repeats):
            start = time.perf_counter()
            for offset in range(0, len(images), size):
                embedder.encode_images(images[offset : offset + size])
            times.append(time.perf_counter() - start)

        best = min(times)
        per_frame = best / len(images) * 1000
        baseline = baseline or best
        print(
            f"{size:>6} {per_frame:>11.0f} мс {best:>8.2f} с "
            f"{vram_gb():>10.2f} ГБ"
            + ("" if size == 1 else f"   ×{baseline / best:.2f}")
        )


if __name__ == "__main__":
    main()
