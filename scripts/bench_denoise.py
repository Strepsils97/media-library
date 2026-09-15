"""Порівняння способів прибирання шуму на реальних записах.

Поточний фільтр (спектральне віднімання) добре бере стаціонарний шум — гул,
шипіння, кондиціонер. Дорога позаду, машини, чужі голоси — шум
нестаціонарний, і з ним спектральне віднімання справляється погано.

Тут перевіряються нейромережеві варіанти. Міряється не «чи стало тихіше» —
затиснути можна будь-що, разом із голосом, — а чи мовлення лишилося
розбірливим: чи знаходить розпізнавання ті слова, які там точно є.

  python scripts/bench_denoise.py
"""

from __future__ import annotations

import re
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.ingest.export import DENOISE_FILTER  # noqa: E402
from backend.app.ingest.media_tools import run  # noqa: E402

MODELS = Path(tempfile.gettempdir()) / "rnnn"

# Слова, які в цих записах точно звучать. Ground truth не ідеальний — це те,
# що чутно людині, — але саме він і потрібен: чи почує це розпізнавання.
EXPECTED = {
    "1.mp3": ["aldi", "netto", "знаходиться", "евро"],
    "2.mp3": ["наивная", "помидор", "название"],
    "3.mp3": ["грейпфрут", "штуки", "скидки"],
    "5.mp4": ["кока", "евро", "цукор", "булки"],
    "6.mp3": ["погода", "кафе"],
    "17.mp4": ["кросовки", "энергия", "сухое"],
    "35.mp4": ["немеччина", "дети", "захистом"],
}


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    table = str.maketrans({"і": "и", "ї": "и", "ы": "и", "є": "е", "э": "е", "ё": "е"})
    return re.sub(r"[^\w\s]", " ", text.translate(table))


def found(transcript: str, words: list[str]) -> int:
    folded = fold(transcript)
    return sum(1 for word in words if fold(word) in folded)


def noise_floor(path: Path) -> float:
    out = run(["ffmpeg", "-hide_banner", "-i", str(path),
               "-af", "astats=metadata=1:reset=0", "-f", "null", "-"]).stderr
    values = [float(v) for v in re.findall(r"Noise floor dB:\s*(-?[\d.]+)", out)]
    return values[-1] if values else 0.0


def apply_filter(source: Path, target: Path, chain: str) -> bool:
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    if source.suffix == ".mp4":
        args += ["-c:v", "copy", "-af", chain, "-c:a", "aac", "-b:a", "192k"]
    else:
        args += ["-af", chain]
    args.append(str(target))
    return run(args).returncode == 0 and target.exists()


def model_arg(path: Path) -> str:
    """Шлях до моделі всередині виразу фільтра.

    Двокрапка розділяє параметри фільтра, тож у C:/... її треба екранувати —
    причому двома зворотними скісними: одну з'їдає розбір самого виразу,
    друга доходить до розбору параметра. І саме без лапок: у лапках ffmpeg
    шлях розібрати не може.
    """
    return "arnndn=m=" + path.as_posix().replace(":", r"\\:")


def variants() -> dict[str, str]:
    """Кожна складова окремо — щоб побачити, що саме допомагає, а що шкодить."""
    chains = {
        "без обробки": "",
        "highpass 90": "highpass=f=90",
        "highpass 120": "highpass=f=120",
        "hp + afftdn -20": "highpass=f=90,afftdn=nf=-20:tn=1",
        "hp + afftdn -25": "highpass=f=90,afftdn=nf=-25:tn=1",
        "hp + afftdn -20 + рівень": "highpass=f=90,afftdn=nf=-20:tn=1,dynaudnorm=f=200:g=15:p=0.7",
        "нинішній ланцюжок": DENOISE_FILTER,
    }
    best = MODELS / "sh.rnnn"
    if best.exists():
        chains["rnnoise sh"] = model_arg(best)
        chains["hp + rnnoise sh"] = f"highpass=f=90,{model_arg(best)}"
    return chains


def main() -> None:
    from backend.app.ml import asr

    samples = [ROOT / "samples" / "audio" / name for name in EXPECTED]
    if "--quick" in sys.argv:
        samples = samples[:4]
    samples = [p for p in samples if p.exists()]
    chains = variants()

    print(f"записів: {len(samples)} · варіантів: {len(chains)}\n")

    totals: dict[str, dict[str, float]] = {
        name: {"знайдено": 0, "усього": 0, "шум": 0.0} for name in chains
    }

    with tempfile.TemporaryDirectory() as tmp:
        for sample in samples:
            expected = EXPECTED[sample.name]
            print(f"--- {sample.name} (шукаємо: {', '.join(expected)}) ---")

            for label, chain in chains.items():
                if chain:
                    target = Path(tmp) / f"{sample.stem}-{label}{sample.suffix}"
                    if not apply_filter(sample, target, chain):
                        print(f"  {label:<18} не оброблено")
                        continue
                else:
                    target = sample

                transcript = asr.transcribe(target).text
                hits = found(transcript, expected)
                floor = noise_floor(target)

                totals[label]["знайдено"] += hits
                totals[label]["усього"] += len(expected)
                totals[label]["шум"] += floor

                print(f"  {label:<26} слів {hits}/{len(expected)} · шум {floor:6.1f} дБ")
            print()

    print("=" * 72)
    print(f"{'варіант':<28} {'розбірливість':>14} {'середній шум':>14}")
    print("-" * 72)
    for label, data in sorted(
        totals.items(), key=lambda kv: -(kv[1]["знайдено"] / max(1, kv[1]["усього"]))
    ):
        share = data["знайдено"] / max(1, data["усього"])
        print(
            f"{label:<28} {data['знайдено']:>5.0f}/{data['усього']:<4.0f} {share:>6.0%} "
            f"{data['шум'] / max(1, len(samples)):>13.1f} дБ"
        )


if __name__ == "__main__":
    main()
