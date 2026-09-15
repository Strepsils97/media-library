"""Чи справляється DeepFilterNet із шумом краще за спектральний фільтр.

Попередні заміри показали неприємне: будь-яка обробка на цих записах знижує
розбірливість, а нейромережевий arnndn виявився гіршим за простий фільтр.
DeepFilterNet — суттєво новіша архітектура, і в нього є важіль сили
(--atten-lim-db), тож перевіряється не лише «на повну», а й помірні режими.

Метрика та сама: чи знаходить розпізнавання слова, які в записі точно є.
«Стало тихіше» тут ні про що не свідчить — затиснути можна разом із голосом.

  python scripts/bench_deepfilter.py
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.ingest.export import DENOISE_FILTER  # noqa: E402
from backend.app.ingest.media_tools import run  # noqa: E402
from scripts.bench_denoise import EXPECTED, found, noise_floor  # noqa: E402

BINARY = ROOT / "tools" / "deep-filter.exe"

# Сила придушення. 100 — на повну, менші значення підмішують оригінал назад.
ATTENUATIONS = (100, 30, 15)


def to_wav(source: Path, target: Path) -> bool:
    """DeepFilterNet працює з WAV 48 кГц моно."""
    return run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-vn", "-ac", "1", "-ar", "48000", str(target),
    ]).returncode == 0 and target.exists()


def deep_filter(source: Path, out_dir: Path, atten: int) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = run([
        str(BINARY), "-D", "-a", str(atten), "-o", str(out_dir), str(source)
    ])
    if result.returncode != 0:
        print(f"    deep-filter: {result.stderr.strip()[:120]}")
        return None
    produced = list(out_dir.glob("*.wav"))
    return produced[0] if produced else None


def ffmpeg_chain(source: Path, target: Path, chain: str) -> bool:
    return run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-af", chain, str(target),
    ]).returncode == 0 and target.exists()


def main() -> None:
    if not BINARY.exists():
        raise SystemExit(f"Немає {BINARY} — завантажте бінарник DeepFilterNet")

    from backend.app.ml import asr

    samples = [ROOT / "samples" / "audio" / name for name in EXPECTED]
    samples = [p for p in samples if p.exists()]

    labels = ["без обробки (wav)", "спектральний"] + [
        f"DeepFilterNet a={a}" for a in ATTENUATIONS
    ]
    totals = {label: {"знайдено": 0, "усього": 0, "шум": 0.0} for label in labels}

    print(f"записів: {len(samples)} · варіантів: {len(labels)}\n")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for sample in samples:
            expected = EXPECTED[sample.name]
            print(f"--- {sample.name} ({', '.join(expected)}) ---")

            # Усе порівнюємо на однаковому WAV: пересемплювання саме по собі
            # трохи змінює результат розпізнавання, і змішувати це з ефектом
            # фільтра означало б міряти не те.
            plain = work / f"{sample.stem}.wav"
            if not to_wav(sample, plain):
                print("  не вдалося підготувати wav")
                continue

            candidates: dict[str, Path | None] = {"без обробки (wav)": plain}

            spectral = work / f"{sample.stem}-spectral.wav"
            candidates["спектральний"] = (
                spectral if ffmpeg_chain(plain, spectral, DENOISE_FILTER) else None
            )

            for atten in ATTENUATIONS:
                out_dir = work / f"df{atten}-{sample.stem}"
                candidates[f"DeepFilterNet a={atten}"] = deep_filter(plain, out_dir, atten)

            for label, path in candidates.items():
                if path is None:
                    print(f"  {label:<22} не оброблено")
                    continue
                transcript = asr.transcribe(path).text
                hits = found(transcript, expected)
                floor = noise_floor(path)
                totals[label]["знайдено"] += hits
                totals[label]["усього"] += len(expected)
                totals[label]["шум"] += floor
                print(f"  {label:<22} слів {hits}/{len(expected)} · шум {floor:6.1f} дБ")
            print()

    print("=" * 66)
    print(f"{'варіант':<24} {'розбірливість':>14} {'середній шум':>14}")
    print("-" * 66)
    for label, data in sorted(
        totals.items(), key=lambda kv: -(kv[1]["знайдено"] / max(1, kv[1]["усього"]))
    ):
        share = data["знайдено"] / max(1, data["усього"])
        print(
            f"{label:<24} {data['знайдено']:>5.0f}/{data['усього']:<4.0f} {share:>6.0%} "
            f"{data['шум'] / max(1, len(samples)):>13.1f} дБ"
        )


if __name__ == "__main__":
    main()
