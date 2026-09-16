"""Куди йде час при обробці відео.

Обробка йде по одному запису за раз, і перш ніж це міняти, варто знати, що
саме в тому записі триває найдовше. Здогади тут погані порадники: кодування
кадрів пачкою здавалося очевидним виграшем, а дало вісімдесят мілісекунд.

  python scripts/bench_stages.py <файл.mp4> [ще файли]
"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TIMES: dict[str, float] = {}


@contextmanager
def stage(name: str):
    start = time.perf_counter()
    yield
    TIMES[name] = TIMES.get(name, 0.0) + time.perf_counter() - start


def main() -> None:
    files = [Path(a) for a in sys.argv[1:]]
    files = [f for f in files if f.exists()]
    if not files:
        raise SystemExit("Вкажіть хоч один файл відео")

    from PIL import Image

    from backend.app.ingest import frames as frames_mod
    from backend.app.ingest.media_tools import ffprobe, run
    from backend.app.ml import asr
    from backend.app.ml.registry import get_image_embedder, get_text_embedder

    image_embedder = get_image_embedder()
    text_embedder = get_text_embedder()
    # Прогрів: перший виклик кожної моделі платить за ініціалізацію ядер.
    image_embedder.encode_images([Image.new("RGB", (384, 384))])
    text_embedder.encode_texts(["проба"])

    total_duration = 0.0
    for path in files:
        out = run([ffprobe(), "-v", "error", "-show_entries", "format=duration",
                   "-of", "default=nw=1:nk=1", str(path)]).stdout.strip()
        duration = float(out) if out else 0.0
        total_duration += duration
        print(f"--- {path.name} · {duration:.0f} с ---")

        with stage("пошук сцен (ffmpeg, CPU)"):
            timestamps = frames_mod.pick_timestamps(path, duration)

        with stage("нарізка кадрів (ffmpeg, CPU)"):
            saved = frames_mod.extract(path, timestamps, f"bench{path.stem}")

        with stage("ембедінг кадрів (GPU)"):
            from backend.app.config import get_settings
            from backend.app.ingest.pipeline import _embed_frames

            # Через справжню функцію конвеєра, а не через власну петлю:
            # інакше замір показував би не те, що застосунок насправді робить.
            # Запис у базу глушимо: тут міряється модель, а не SQLite.
            from backend.app.db import repo as _repo
            from backend.app.ingest import pipeline as _pipeline

            _pipeline.repo = type("_", (), {"add_embedding": staticmethod(lambda *a, **k: None)})
            _embed_frames(
                item_id=0,
                paths=[get_settings().frames_dir / relative for _, relative in saved],
                frame_ids=[None] * len(saved),
                stamps=[None] * len(saved),
            )

            _pipeline.repo = _repo

        with stage("розпізнавання мовлення (GPU)"):
            transcript = asr.transcribe(path)

        with stage("ембедінг транскрипції (GPU)"):
            from backend.app.ingest.text import chunk_segments

            chunks = chunk_segments(transcript.segments)
            if chunks:
                text_embedder.encode_texts([c.text for c in chunks])

        print(f"  кадрів {len(saved)} · символів у транскрипції {len(transcript.text)}")

    print()
    total = sum(TIMES.values())
    print(f"{'етап':<30} {'час':>8} {'частка':>8}")
    print("-" * 48)
    for name, spent in sorted(TIMES.items(), key=lambda kv: -kv[1]):
        print(f"{name:<30} {spent:>6.1f} с {spent / total:>7.0%}")
    print("-" * 48)
    print(f"{'разом':<30} {total:>6.1f} с")
    if total_duration:
        print(f"\nна хвилину відео: {total / total_duration * 60:.0f} с обробки")


if __name__ == "__main__":
    main()
