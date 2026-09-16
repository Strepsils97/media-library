"""Чи варто вмикати пакетний режим faster-whisper.

Розпізнавання — найдорожча частина обробки (56% часу після того, як кадри
навчилися нарізатися паралельно). Пакетний режим обіцяє кратне прискорення:
VAD ріже запис на шматки мовлення, і вони йдуть у модель разом, а не один за
одним.

Але швидкість тут нічого не варта без перевірки тексту. Тому міряється і те,
й інше: час — і наскільки результат збігається з нинішнім. За взірець беруться
транскрипції з живої бібліотеки, зроблені поточним режимом.

  python scripts/bench_asr_batched.py --library "C:/Users/didyk/media-library/data" --count 8
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BATCH_SIZES = (4, 8, 16)


def samples(library: Path, count: int) -> list[tuple[Path, str]]:
    """Записи з готовою транскрипцією — вони ж і взірець для порівняння."""
    conn = sqlite3.connect(library / "library.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT stored_path, transcript FROM items
        WHERE kind IN ('audio', 'video')
          AND transcript IS NOT NULL AND length(transcript) > 40
          AND transcript_edited = 0
        ORDER BY length(transcript) DESC LIMIT ?
        """,
        (count,),
    ).fetchall()
    conn.close()
    return [(library / "originals" / r["stored_path"], r["transcript"]) for r in rows]


def agreement(left: str, right: str) -> float:
    return SequenceMatcher(None, left.split(), right.split()).ratio()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", required=True)
    parser.add_argument("--count", type=int, default=8)
    args = parser.parse_args()

    from faster_whisper import BatchedInferencePipeline
    from faster_whisper.audio import decode_audio

    from backend.app.ml import asr

    files = [(p, t) for p, t in samples(Path(args.library), args.count) if p.exists()]
    if not files:
        raise SystemExit("У бібліотеці не знайшлося записів із транскрипцією")

    model = asr._get_model()
    batched = BatchedInferencePipeline(model=model)

    audios = {path: decode_audio(str(path), sampling_rate=16000) for path, _ in files}
    seconds = sum(len(a) for a in audios.values()) / 16000
    print(f"записів: {len(files)} · звуку: {seconds:.0f} с\n")

    def run(label: str, fn) -> None:
        start = time.perf_counter()
        scores = []
        for path, reference in files:
            text = fn(audios[path], asr._pick_language(model, audios[path])[0])
            scores.append(agreement(reference, text))
        spent = time.perf_counter() - start
        print(
            f"{label:<22} {spent:>6.1f} с · ×{seconds / spent:>4.1f} реального часу"
            f" · збіг {sum(scores) / len(scores):>5.0%}"
        )

    def current(audio, language: str) -> str:
        segments, _ = model.transcribe(
            audio, language=language, vad_filter=True, beam_size=5,
            condition_on_previous_text=False, hallucination_silence_threshold=2.0,
        )
        return " ".join(s.text.strip() for s in segments).strip()

    def in_batches(size: int):
        def fn(audio, language: str) -> str:
            segments, _ = batched.transcribe(
                audio, language=language, beam_size=5, batch_size=size,
                condition_on_previous_text=False,
            )
            return " ".join(s.text.strip() for s in segments).strip()

        return fn

    # Прогрів: перший прогін платить за ініціалізацію ядер.
    current(audios[files[0][0]], "uk")

    run("нинішній режим", current)
    for size in BATCH_SIZES:
        run(f"пакетами по {size}", in_batches(size))


if __name__ == "__main__":
    main()
