"""Фаза 0: замір моделей розпізнавання мовлення.

Міряє швидкість і розмір на диску для кількох моделей faster-whisper, а також
друкує транскрипції файлів, згаданих у samples/queries.txt, щоб можна було
оцінити якість очима.

  python scripts/bench_asr.py --models small large-v3-turbo --device auto
"""

from __future__ import annotations

import argparse
import json
import sys
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples" / "audio"
QUERIES = ROOT / "samples" / "queries.txt"
OUT = ROOT / "samples" / "bench_asr.json"
ALLOWED_LANGS = {"uk", "ru", "de"}


def duration_s(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=False,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def referenced_files() -> set[str]:
    """Файли, згадані у queries.txt — саме їх якість нас цікавить найбільше."""
    names: set[str] = set()
    if not QUERIES.exists():
        return names
    for line in QUERIES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        target = line.split("|", 1)[1].strip()
        if target.endswith((".mp3", ".mp4", ".wav", ".m4a")):
            names.add(target)
    return names


def dir_size_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["small", "large-v3-turbo"])
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--compute-type", default=None)
    ap.add_argument("--limit", type=int, default=0, help="взяти лише N файлів")
    ap.add_argument("--restrict", action="store_true",
                    help="обмежити визначення мови до uk/ru/de")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT))
    from backend.app.ml.cuda import resolve_device

    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio

    files = sorted(SAMPLES.iterdir())
    if args.limit:
        files = files[: args.limit]
    durations = {f.name: duration_s(f) for f in files}
    audio_total = sum(durations.values())
    interesting = referenced_files()

    print(f"Файлів: {len(files)}, загальна тривалість: {audio_total:.0f}s\n")

    results: dict[str, dict] = {}

    for model_name in args.models:
        device, compute = resolve_device(args.device)
        compute = args.compute_type or compute

        print(f"{'=' * 70}\n{model_name}  ({device}, {compute})\n{'=' * 70}")

        load_start = time.perf_counter()
        try:
            model = WhisperModel(model_name, device=device, compute_type=compute)
        except Exception as exc:  # носій CUDA-бібліотек може бути відсутній
            print(f"  ПОМИЛКА завантаження: {exc}\n")
            results[model_name] = {"error": str(exc), "device": device}
            continue
        load_s = time.perf_counter() - load_start

        transcripts: dict[str, dict] = {}
        infer_start = time.perf_counter()

        for path in files:
            source: object = str(path)
            language = None
            lang_prob = 0.0

            if args.restrict:
                # Whisper визначає мову з-поміж сотні, і на двомовному записі
                # регулярно зупиняється на польській чи іспанській. За спекою
                # мов лише три, тож обираємо найкращу саме з них.
                audio = decode_audio(str(path), sampling_rate=16000)
                source = audio
                _, _, all_probs = model.detect_language(audio=audio, vad_filter=True)
                language, lang_prob = max(
                    ((code, p) for code, p in all_probs if code in ALLOWED_LANGS),
                    key=lambda pair: pair[1],
                )

            segments, info = model.transcribe(
                source,
                language=language,
                vad_filter=True,         # відсікає тишу; на коротких кліпах критично
                beam_size=5,
                # Обидва — проти галюцинацій на тиші та в кінці кліпу.
                condition_on_previous_text=False,
                hallucination_silence_threshold=2.0,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            transcripts[path.name] = {
                "text": text,
                "lang": language or info.language,
                "lang_prob": round(lang_prob or info.language_probability, 3),
                "duration": round(durations[path.name], 1),
            }

        infer_s = time.perf_counter() - infer_start
        rtf = infer_s / audio_total if audio_total else 0

        cache = Path.home() / ".cache" / "huggingface" / "hub"
        size_mb = 0.0
        for d in cache.glob(f"*{model_name}*"):
            size_mb += dir_size_mb(d)

        print(f"  завантаження моделі: {load_s:.1f}s")
        print(f"  розпізнавання:       {infer_s:.1f}s на {audio_total:.0f}s аудіо")
        print(f"  RTF:                 {rtf:.3f}  (година аудіо ≈ {rtf * 60:.1f} хв)")
        print(f"  розмір на диску:     {size_mb:.0f} МБ")

        langs: dict[str, int] = {}
        for t in transcripts.values():
            langs[t["lang"]] = langs.get(t["lang"], 0) + 1
        print(f"  визначені мови:      {langs}")

        print("\n  --- транскрипції файлів із queries.txt ---")
        for name in sorted(interesting):
            if name in transcripts:
                t = transcripts[name]
                print(f"  [{name}] ({t['lang']} {t['lang_prob']}, {t['duration']}s)")
                print(f"    {t['text'][:300]}")
        print()

        results[model_name] = {
            "device": device,
            "compute_type": compute,
            "load_s": round(load_s, 2),
            "infer_s": round(infer_s, 2),
            "audio_s": round(audio_total, 1),
            "rtf": round(rtf, 4),
            "size_mb": round(size_mb),
            "languages": langs,
            "transcripts": transcripts,
        }
        del model

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Результати: {OUT}")


if __name__ == "__main__":
    main()
