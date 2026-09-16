"""Збірка застосунку: PyInstaller, потім ваги моделей поруч.

Ваги (близько 4 ГБ) копіюються окремо, а не через datas у спеці: пропускаючи
їх через PyInstaller, ми лише піднімали пік споживання пам'яті на збірці, не
отримуючи нічого натомість — це незмінні файли, які просто мають лежати поруч.

  python scripts/build.py           повна збірка (десь чверть години)
  python scripts/build.py --ui      лише інтерфейс, секунди
  python scripts/build.py --code    інтерфейс і бекенд, теж секунди
  python scripts/build.py --code --to "C:/Users/.../media-library"

Повна збірка довга не через наш код: PyInstaller щоразу переписує в dist
близько шести гігабайтів torch і CUDA. Тому наш код їде поруч із екзешником
звичайними файлами — і фронтенд, і backend/. Оновити його означає замінити
файли; повна збірка потрібна лише коли змінюється склад залежностей: torch,
ffmpeg, DeepFilterNet, ваги моделей.

Теку build/ між збірками видаляти не треба: у ній лежить розбір залежностей,
і без неї PyInstaller починає його спочатку.
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


def build_frontend() -> Path:
    """Збирає інтерфейс. Повертає теку з результатом."""
    result = subprocess.run(
        ["npm", "run", "build"], cwd=ROOT / "frontend", check=False, shell=True
    )
    if result.returncode != 0:
        raise SystemExit("npm run build не впорався")
    return ROOT / "frontend" / "dist"


def sync_backend(dist_root: Path) -> int:
    """Кладе свіжий код бекенда у вже зібраний застосунок.

    Зайві .py прибираються теж: лишений від старої версії модуль — це
    найнеприємніший різновид помилки, бо імпортується він мовчки.
    """
    target = dist_root / "_internal" / "backend"
    if not target.is_dir():
        raise SystemExit(
            f"У {dist_root} немає _internal/backend — цей застосунок зібрано "
            "старою спекою, з кодом усередині екзешника. Потрібна повна збірка."
        )

    source = ROOT / "backend"
    wanted = {path.relative_to(source) for path in source.rglob("*.py")}
    copied = mirror(source, target, skip=("__pycache__",))

    stale = 0
    for path in sorted(target.rglob("*.py"), reverse=True):
        if path.relative_to(target) not in wanted:
            path.unlink()
            stale += 1
    for junk in sorted(target.rglob("__pycache__"), reverse=True):
        shutil.rmtree(junk, ignore_errors=True)

    print(f"   бекенд оновлено: {copied} файлів" + (f", прибрано {stale}" if stale else ""))
    return copied


def sync_frontend(dist_root: Path) -> None:
    """Кладе свіжий інтерфейс у вже зібраний застосунок."""
    target = dist_root / "_internal" / "frontend" / "dist"
    if not target.parent.parent.is_dir():
        raise SystemExit(f"Це не схоже на зібраний застосунок: {dist_root}")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(ROOT / "frontend" / "dist", target)
    print(f"   інтерфейс оновлено: {target}")


def mirror(source: Path, target: Path, *, skip: tuple[str, ...] = ()) -> int:
    """Копіює лише те, чого бракує або що змінилося. Повертає кількість файлів.

    Ваги — п'ять гігабайтів незмінних файлів, і зносити їх щоразу заради
    побайтово тієї самої копії означає дарувати кілька хвилин кожній збірці.
    """
    copied = 0
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if any(part in skip for part in relative.parts):
            continue
        destination = target / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        if destination.exists() and destination.stat().st_size == path.stat().st_size:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied += 1
    return copied


def main() -> None:
    if "--ui" in sys.argv or "--code" in sys.argv:
        # Швидкий шлях: у застосунку змінився лише інтерфейс. PyInstaller тут
        # ні до чого — фронтенд лежить звичайними файлами поруч із екзешником.
        build_frontend()
        where = sys.argv[sys.argv.index("--to") + 1] if "--to" in sys.argv else str(DIST)
        sync_frontend(Path(where))
        if "--code" in sys.argv:
            sync_backend(Path(where))
        return

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

    print("2/4 ваги моделей…")
    source = ROOT / "data" / "models"
    if not source.is_dir():
        raise SystemExit("data/models не існує — спершу python scripts/prepare_models.py")

    # Кеш HuggingFace копіюємо без службових тек із блобами: у збірці потрібні
    # лише самі знімки, а blobs дублювали б їх ще раз.
    target = INTERNAL / "models"
    copied = mirror(source, target, skip=("blobs", ".locks"))
    print(f"   скопійовано файлів: {copied}" if copied else "   уже на місці")

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
        # Код має лежати файлами, а не в архіві: інакше --code нікуди класти.
        "код бекенда": INTERNAL / "backend" / "app" / "main.py",
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
