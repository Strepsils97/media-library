"""Збірка застосунку: PyInstaller, потім ваги моделей поруч.

Ваги (близько 4 ГБ) копіюються окремо, а не через datas у спеці: пропускаючи
їх через PyInstaller, ми лише піднімали пік споживання пам'яті на збірці, не
отримуючи нічого натомість — це незмінні файли, які просто мають лежати поруч.

  python scripts/build.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "media-library"
INTERNAL = DIST / "_internal"


def human(size: int) -> str:
    return f"{size / 1024 ** 3:.2f} ГБ"


def tree_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def main() -> None:
    frontend = ROOT / "frontend" / "dist"
    if not frontend.exists():
        raise SystemExit("Спершу зберіть фронтенд: npm run build у frontend/")

    print("1/3 PyInstaller…")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "media-library.spec",
         "--noconfirm", "--distpath", "dist", "--workpath", "build"],
        cwd=ROOT, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller завершився з кодом {result.returncode}")

    print("2/3 копіювання ваг моделей…")
    source = ROOT / "data" / "models"
    if not source.is_dir():
        raise SystemExit("data/models не існує — спершу python scripts/prepare_models.py")

    target = INTERNAL / "models"
    if target.exists():
        shutil.rmtree(target)
    # Кеш HuggingFace копіюємо без службових тек із блобами: у збірці потрібні
    # лише самі знімки, а blobs дублювали б їх ще раз.
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("blobs", ".locks"))

    print("3/3 перевірка…")
    checks = {
        "exe": DIST / "media-library.exe",
        "фронтенд": INTERNAL / "frontend" / "dist" / "index.html",
        "схема БД": INTERNAL / "backend" / "app" / "db" / "schema.sql",
        "sqlite-vec": INTERNAL / "sqlite_vec" / "vec0.dll",
        "ffmpeg": INTERNAL / "ffmpeg.exe",
        "CUDA": INTERNAL / "cuda" / "cublas64_12.dll",
        "SigLIP": target / "local" / "siglip" / "config.json",
        "E5": target / "local" / "e5" / "config.json",
    }
    missing = [name for name, path in checks.items() if not path.exists()]
    for name, path in checks.items():
        print(f"  {'OK  ' if path.exists() else 'НЕМА'} {name}")

    if missing:
        raise SystemExit("Збірка неповна: " + ", ".join(missing))

    print(f"\nГотово: {DIST}  ({human(tree_size(DIST))})")


if __name__ == "__main__":
    main()
