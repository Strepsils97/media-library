# PyInstaller: збірка застосунку в один каталог із exe.
#
# Режим onedir, а не onefile: у збірці гігабайти ваг і CUDA-бібліотек, і
# onefile розпаковував би їх у тимчасову теку при кожному запуску — десятки
# секунд очікування на старті й подвійне місце на диску.

import shutil
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH)
VENV = ROOT / ".venv" / "Lib" / "site-packages"

datas = []
binaries = []
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "webview.platforms.edgechromium",
    "backend.app.ml.embedders",
    "backend.app.ingest.pipeline",
    # transformers вантажить архітектури ліниво, через рядкові імена, тож
    # статичний аналіз PyInstaller їх не бачить.
    "transformers.models.siglip2",
    "transformers.models.siglip2.modeling_siglip2",
    "transformers.models.siglip2.processing_siglip2",
    "transformers.models.xlm_roberta",
    "transformers.models.xlm_roberta.modeling_xlm_roberta",
    "transformers.models.gemma",
    "open_clip",
    "open_clip.factory",
    "open_clip.tokenizer",
]

# --- фронтенд -------------------------------------------------------------
frontend = ROOT / "frontend" / "dist"
if not frontend.exists():
    raise SystemExit("Спершу зберіть фронтенд: npm run build у frontend/")
datas.append((str(frontend), "frontend/dist"))

# --- ресурси бекенда ------------------------------------------------------
# PyInstaller тягне лише .py; схема бази — звичайний файл поруч із кодом.
datas.append((str(ROOT / "backend" / "app" / "db" / "schema.sql"), "backend/app/db"))

# --- знак ------------------------------------------------------------------
# Іконку вікна Windows бере з екзешника, а от pywebview у режимі розробки —
# ні, тому файл їде і всередину: там його ставить main.
datas.append((str(ROOT / "brand" / "media-library.ico"), "brand"))

# --- sqlite-vec -----------------------------------------------------------
# Розширення шукається поруч із пакетом, тому кладемо його тим самим шляхом.
datas.append((str(VENV / "sqlite_vec" / "vec0.dll"), "sqlite_vec"))

# --- ffmpeg ---------------------------------------------------------------
# Потрібен для декодування аудіо, метаданих і нарізки кадрів. Свого
# декодера в застосунку немає, тож без нього відео й аудіо не працюють.
def _real_binary(tool: str) -> str:
    """Справжній виконуваний файл, а не shim.

    chocolatey кладе в PATH заглушки на 400 КБ, які лише знаходять справжній
    файл за фіксованим шляхом. Запакувати заглушку означає зібрати застосунок,
    який працює тільки на цій машині.
    """
    found = shutil.which(tool)
    if not found:
        raise SystemExit(f"{tool} не знайдено в PATH — його треба покласти у збірку")

    real = Path(found)
    if real.stat().st_size < 5_000_000:  # шім, а не ffmpeg
        for candidate in Path("C:/ProgramData/chocolatey/lib").glob(
            f"ffmpeg*/tools/**/bin/{tool}.exe"
        ):
            return str(candidate)
        print(f"УВАГА: {found} схожий на shim, справжній {tool} не знайдено")
    return str(real)


for tool in ("ffmpeg", "ffprobe"):
    binaries.append((_real_binary(tool), "."))

# --- DeepFilterNet ----------------------------------------------------------
# Окремий виконуваний файл, а не pip-пакет: той тягне torchaudio, якого під
# наш torch не існує. Модель уже всередині, тож нічого більше не потрібно.
_deep_filter = ROOT / "tools" / "deep-filter.exe"
if _deep_filter.exists():
    binaries.append((str(_deep_filter), "."))
else:
    raise SystemExit(
        "Немає tools/deep-filter.exe — без нього не працюватиме прибирання шуму"
    )

# --- CUDA -----------------------------------------------------------------
# CTranslate2 шукає ці DLL звичайним завантажувачем Windows, тому вони мають
# лежати поруч із exe (backend/app/ml/cuda.py реєструє теку при старті).
for package in ("cublas", "cudnn", "cuda_nvrtc"):
    bin_dir = VENV / "nvidia" / package / "bin"
    if bin_dir.is_dir():
        for dll in bin_dir.glob("*.dll"):
            binaries.append((str(dll), "cuda"))

# --- моделі ---------------------------------------------------------------
# Ваги свідомо НЕ передаються PyInstaller, хоч і потрапляють у збірку.
# Це майже 4 ГБ незмінних файлів: проганяючи їх через аналіз і власне
# копіювання PyInstaller, ми лише роздували пік пам'яті — збірку вбивало.
# Їх кладе поруч scripts/build.py після того, як PyInstaller завершив.

# --- пакети з даними ------------------------------------------------------
# ctranslate2 — нативна бібліотека; без її DLL розпізнавання не стартує.
# open_clip несе поруч із кодом словник BPE і конфіги архітектур — без них
# він падає ще на імпорті.
for package in ("faster_whisper", "transformers", "tokenizers", "av",
                "ctranslate2", "open_clip", "timm"):
    datas += collect_data_files(package)
    binaries += collect_dynamic_libs(package)

datas += collect_data_files("torch", include_py_files=False)

# torchvision реєструє власні оператори (nms та інші) з .pyd-розширень.
# Без них transformers падає на імпорті AutoProcessor із повідомленням
# «Could not import module», яке про справжню причину не говорить нічого.
import torchvision as _tv

_tv_dir = Path(_tv.__file__).parent
for pattern in ("*.pyd", "*.dll"):
    for lib in _tv_dir.glob(pattern):
        binaries.append((str(lib), "torchvision"))
binaries += collect_dynamic_libs("torchvision")
hiddenimports += ["torchvision", "torchvision.ops", "torchvision.transforms"]


a = Analysis(
    ["run_app.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Важкі й непотрібні в рантаймі залежності розробки.
    # Виключати тут можна лише те, чого справді ніхто не імпортує.
    # sympy.plotting і scipy довелося повернути: перше тягне torch, друге —
    # transformers, і без них падає імпорт AutoModel із геть невиразною
    # помилкою «Could not import module 'AutoModel'».
    excludes=["tkinter", "matplotlib", "pytest", "IPython", "notebook"],
    noarchive=False,
)

# --- наш код окремими файлами ------------------------------------------------
# Решта бібліотек лишається в архіві всередині екзешника, а backend/ їде поруч
# звичайними .py. Причина не в естетиці: зміна на два рядки в нашому коді
# інакше вимагає повної перезбірки, у якій PyInstaller щоразу переписує шість
# гігабайтів torch і CUDA. Так виправлення бекенда стає копіюванням файлів —
# тим самим оновленням «замінив і працює», яке вже є для інтерфейсу.
#
# Analysis лишається недоторканою: саме вона, йдучи по наших імпортах,
# знаходить fastapi, transformers і решту. Ми тільки прибираємо наші модулі з
# архіву — вже після того, як вона зробила свою роботу.
a.pure = [
    entry for entry in a.pure
    if not (entry[0] == "backend" or entry[0].startswith("backend."))
]
a.datas += [
    (
        str(Path("backend") / path.relative_to(ROOT / "backend")),
        str(path),
        "DATA",
    )
    for path in (ROOT / "backend").rglob("*.py")
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="media-library",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "brand" / "media-library.ico"),
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="media-library",
)
