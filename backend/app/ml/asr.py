"""Розпізнавання мовлення через faster-whisper (CTranslate2)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings
from .cuda import resolve_device

log = logging.getLogger(__name__)

# За спекою мов лише три. Без цього обмеження Whisper на двомовних записах
# регулярно визначає польську, іспанську чи грецьку — заміряно на Фазі 0.
ALLOWED_LANGUAGES = ("uk", "ru", "de")


class NoAudioTrack(Exception):
    """У файлі немає звукової доріжки — транскрибувати нічого."""


@dataclass(slots=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(slots=True)
class Transcript:
    text: str
    language: str
    language_probability: float
    segments: list[Segment]


_lock = threading.Lock()
_model = None
_model_key: tuple[str, str] | None = None


def _get_model():
    global _model, _model_key
    settings = get_settings()
    device, compute = resolve_device(settings.device)
    if settings.asr_compute_type != "auto":
        compute = settings.asr_compute_type
    key = (settings.asr_model, f"{device}/{compute}")

    with _lock:
        if _model is None or _model_key != key:
            from faster_whisper import WhisperModel

            log.info("Завантаження ASR %s (%s, %s)", settings.asr_model, device, compute)
            _model = WhisperModel(
                settings.asr_model,
                device=device,
                compute_type=compute,
                download_root=str(settings.models_dir),
            )
            _model_key = key
        return _model


def _pick_language(model, audio) -> tuple[str, float]:
    _, _, all_probs = model.detect_language(audio=audio, vad_filter=True)
    return max(
        ((code, prob) for code, prob in all_probs if code in ALLOWED_LANGUAGES),
        key=lambda pair: pair[1],
    )


def transcribe(
    path: Path,
    on_progress: Callable[[float], None] | None = None,
) -> Transcript:
    """Розпізнає мовлення у файлі.

    Кидає NoAudioTrack, якщо доріжки немає — це найчастіший реальний збій
    (німе відео), і користувачу треба показати саме причину, а не стек.
    """
    from faster_whisper.audio import decode_audio

    model = _get_model()

    try:
        audio = decode_audio(str(path), sampling_rate=16000)
    except Exception as exc:  # noqa: BLE001 — av кидає різні типи
        raise NoAudioTrack(str(exc)) from exc

    if audio is None or len(audio) == 0:
        raise NoAudioTrack("У файлі немає звукової доріжки")

    language, probability = _pick_language(model, audio)

    segments_iter, info = model.transcribe(
        audio,
        language=language,
        vad_filter=True,
        beam_size=5,
        # Обидва — проти галюцинацій на тиші й у кінці кліпу.
        condition_on_previous_text=False,
        hallucination_silence_threshold=2.0,
    )

    total = info.duration or 0.0
    segments: list[Segment] = []
    for segment in segments_iter:
        text = segment.text.strip()
        if text:
            segments.append(Segment(segment.start, segment.end, text))
        if on_progress and total:
            on_progress(min(1.0, segment.end / total))

    return Transcript(
        text=" ".join(s.text for s in segments).strip(),
        language=language,
        language_probability=probability,
        segments=segments,
    )


def unload() -> None:
    global _model, _model_key
    with _lock:
        _model = None
        _model_key = None
