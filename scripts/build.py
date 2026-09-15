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

    # PyInstaller із --noconfirm зносить теку призначення цілком, разом із
    # бібліотекою користувача. Відкладаємо її вбік на час збірки: перезбірка
    # на місці не має коштувати даних.
    stash = ROOT / "dist" / ".data-stash"
    data = DIST / "data"
    if data.exists():
        if stash.exists():
            shutil.rmtree(stash)
        data.rename(stash)
        print(f"   бібліотеку відкладено: {stash.name}")

    print("1/4 PyInstaller…")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "media-library.spec",
         "--noconfirm", "--distpath", "dist", "--workpath", "build"],
        cwd=ROOT, check=False,
    )
    if stash.exists():
        DIST.mkdir(parents=True, exist_ok=True)
        if data.exists():
            shutil.rmtree(data)
        stash.rename(data)
        print("   бібліотеку повернено на місце")

    if result.returncode != 0:
        raise SystemExit(f"PyInstaller завершився з кодом {result.returncode}")

    print("2/4 копіювання ваг моделей…")
    source = ROOT / "data" / "models"
    if not source.is_dir():
        raise SystemExit("data/models не існує — спершу python scripts/prepare_models.py")

    target = INTERNAL / "models"
    if target.exists():
        shutil.rmtree(target)
    # Кеш HuggingFace копіюємо без службових тек із блобами: у збірці потрібні
    # лише самі знімки, а blobs дублювали б їх ще раз.
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("blobs", ".locks"))

    print("3/4 підпис…")
    sign = ROOT / "scripts" / "sign.ps1"
    signed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(sign)],
        cwd=ROOT, capture_output=True, text=True, check=False, encoding="utf-8",
        errors="replace",
    )
    if signed.returncode == 0:
        for line in signed.stdout.splitlines():
            if line.strip():
                print("  " + line.strip())
    else:
        # Підпис не критичний: exe працює й без нього, просто Windows
        # показуватиме «Невідомий видавець».
        print("  УВАГА: підписати не вдалося —", signed.stderr.strip()[:200])

    print("4/4 перевірка…")
    checks = {
        "exe": DIST / "media-library.exe",
        "фронтенд": INTERNAL / "frontend" / "dist" / "index.html",
        "схема БД": INTERNAL / "backend" / "app" / "db" / "schema.sql",
        "sqlite-vec": INTERNAL / "sqlite_vec" / "vec0.dll",
        "ffmpeg": INTERNAL / "ffmpeg.exe",
        "deep-filter": INTERNAL / "deep-filter.exe",
        "знак": INTERNAL / "brand" / "media-library.ico",
        "CUDA": INTERNAL / "cuda" / "cublas64_12.dll",
        "SigLIP": target / "local" / "siglip" / "config.json",
        "NLLB-CLIP": target / "local" / "nllbclip" / "open_clip_pytorch_model.bin",
        # Токенізатор NLLB тягнеться окремо від ваг, і без нього друга
        # візуальна модель у офлайновій збірці просто не стартує.
        "токенізатор NLLB": target / "models--facebook--nllb-200-distilled-600M",
        "E5": target / "local" / "e5" / "config.json",
        "ASR": target / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo",
    }
    missing = [name for name, path in checks.items() if not path.exists()]
    for name, path in checks.items():
        print(f"  {'OK  ' if path.exists() else 'НЕМА'} {name}")

    if missing:
        raise SystemExit("Збірка неповна: " + ", ".join(missing))

    print(f"\nГотово: {DIST}  ({human(tree_size(DIST))})")


if __name__ == "__main__":
    main()
