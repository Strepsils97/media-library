"""Наскрізна перевірка: інжест семплів через справжній пайплайн і пошук.

  python scripts/smoke_e2e.py --images 20 --audio 6
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.db import repo  # noqa: E402
from backend.app.db.connection import init_db  # noqa: E402
from backend.app.ingest import pipeline, storage  # noqa: E402
from backend.app.ml.asr import NoAudioTrack  # noqa: E402
from backend.app.search.query import Filters, search  # noqa: E402

SAMPLES = ROOT / "samples"


def ingest(path: Path) -> int | None:
    try:
        prepared = storage.prepare_file(path)
    except storage.UnsupportedFile as exc:
        print(f"  пропущено {path.name}: {exc}")
        return None

    existing = repo.find_by_hash(prepared.content_hash)
    if existing is not None:
        return int(existing["id"])

    item_id = repo.create_item(prepared)
    try:
        pipeline.PROCESSORS[prepared.kind](item_id)
        repo.update_item(item_id, status="ready")
    except NoAudioTrack as exc:
        print(f"  {path.name}: без звукової доріжки ({exc})")
        repo.update_item(item_id, status="ready")
    except Exception as exc:  # noqa: BLE001
        print(f"  ПОМИЛКА {path.name}: {exc}")
        repo.update_item(item_id, status="failed")
    return item_id


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", type=int, default=20)
    ap.add_argument("--audio", type=int, default=6)
    ap.add_argument("--search-only", action="store_true",
                    help="шукати по вже проіндексованій бібліотеці")
    args = ap.parse_args()

    settings = get_settings()
    settings.ensure_dirs()
    init_db()
    print(f"Бібліотека: {settings.data_dir}\n")

    images = [] if args.search_only else sorted((SAMPLES / "images").iterdir())[: args.images]
    audio = [] if args.search_only else sorted((SAMPLES / "audio").iterdir())[: args.audio]

    print(f"--- інжест {len(images)} картинок ---")
    start = time.perf_counter()
    for path in images:
        ingest(path)
    per_image = (time.perf_counter() - start) / max(1, len(images))
    print(f"  {time.perf_counter() - start:.1f}s ({per_image:.2f}s на картинку)\n")

    if audio:
        print(f"--- інжест {len(audio)} медіа зі звуком ---")
        start = time.perf_counter()
        for path in audio:
            ingest(path)
        print(f"  {time.perf_counter() - start:.1f}s\n")

    print(f"Записів у базі: {repo.count_items()}\n")

    queries = []
    for line in (SAMPLES / "queries.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "|" in line:
            queries.append(tuple(p.strip() for p in line.split("|", 1)))

    print("--- пошук ---")
    hits_at_1 = 0
    checked = 0
    for query, target in queries:
        result = search(Filters(query=query))
        if not result["hits"]:
            print(f"  ·  «{query:38}» -> нічого не знайдено")
            checked += 1
            continue

        top = result["hits"][0]
        # Лейбл за замовчуванням — ім'я файлу без розширення, тож із ним і звіряємо.
        expected = Path(target).stem
        correct = top["label"] == expected
        hits_at_1 += correct
        checked += 1
        print(
            f"  {'+' if correct else '-'}  «{query:38}» -> {top['label'][:30]:30} "
            f"{top['score']:5.1f}%  ({result['took_ms']} мс)"
        )

    print(f"\nRecall@1 на реальному пайплайні: {hits_at_1}/{checked}")


if __name__ == "__main__":
    main()
