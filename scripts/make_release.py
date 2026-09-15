"""Пакує зібраний застосунок у zip для оновлення.

Тека `data` у архів не потрапляє свідомо: саме вона переживає оновлення.
Користувач розпаковує архів поверх наявної теки, `data` лишається на місці,
а база доводиться до нової схеми при першому запуску (backend/app/db/migrations.py).
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.version import APP_VERSION  # noqa: E402

DIST = ROOT / "dist" / "media-library"
EXCLUDE_TOP = {"data", "run.log"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="показати, що потрапить в архів, нічого не пишучи")
    args = parser.parse_args()

    if not (DIST / "media-library.exe").exists():
        raise SystemExit("Спершу зберіть застосунок: python scripts/build.py")

    target = ROOT / "dist" / f"media-library-{APP_VERSION}.zip"
    if target.exists():
        target.unlink()

    files = [
        p
        for p in DIST.rglob("*")
        if p.is_file() and p.relative_to(DIST).parts[0] not in EXCLUDE_TOP
    ]
    total = sum(f.stat().st_size for f in files)
    print(f"Файлів: {len(files)} · {total / 1024**3:.2f} ГБ до стиснення")

    if args.dry_run:
        tops: dict[str, int] = {}
        for f in files:
            tops[f.relative_to(DIST).parts[0]] = tops.get(f.relative_to(DIST).parts[0], 0) + 1
        for name, count in sorted(tops.items()):
            print(f"  {name}: {count}")
        excluded = [p.name for p in DIST.iterdir() if p.name in EXCLUDE_TOP]
        print(f"  не входить: {', '.join(excluded) or '—'}")
        return

    # ZIP_STORED, а не DEFLATED: усередині майже все — уже стиснуті ваги
    # моделей і DLL, і стиснення дало б відсотки за десятки хвилин.
    with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
        for index, path in enumerate(files, 1):
            archive.write(path, path.relative_to(DIST))
            if index % 500 == 0:
                print(f"  {index}/{len(files)}")

    print(f"\nГотово: {target}  ({target.stat().st_size / 1024**3:.2f} ГБ)")
    print("Оновлення: розпакувати поверх наявної теки, «data» не чіпати.")


if __name__ == "__main__":
    main()
