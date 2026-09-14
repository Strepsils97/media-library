"""Фоновий воркер: по одній задачі за раз, зі станом у базі.

Стан лежить у таблиці jobs, а не в пам'яті, тому перезапуск застосунку не
губить чергу, а інтерфейс може показувати прогрес, нічого не підписуючись.
"""

from __future__ import annotations

import logging
import threading
import time

from ..db import repo
from ..ingest import pipeline
from ..ml.asr import NoAudioTrack

log = logging.getLogger(__name__)

STAGE_LABELS = {
    "image": "Ембедінг зображення",
    "text": "Ембедінг тексту",
    "audio": "Розпізнавання мовлення",
    "video": "Відбір кадрів → мовлення",
}

_thread: threading.Thread | None = None
_stop = threading.Event()
_paused = threading.Event()


def _run_job(job) -> None:
    job_id = job["id"]
    item_id = job["item_id"]
    kind = job["type"]

    repo.update_job(job_id, status="running", progress=0.0, error=None)
    repo.update_item(item_id, status="processing")

    def on_progress(value: float) -> None:
        repo.update_job(job_id, progress=max(0.0, min(1.0, value)))

    try:
        processor = pipeline.PROCESSORS[kind]
        if kind in ("audio", "video"):
            processor(item_id, on_progress=on_progress)
        else:
            processor(item_id)
    except NoAudioTrack:
        # Для відео кадри вже проіндексовані, тож запис придатний до пошуку.
        # Для аудіо шукати нема чого — але запис усе одно лишається в бібліотеці.
        message = (
            "У файлі немає звукової доріжки — транскрибувати нічого. "
            "Запис збережено: пошук працюватиме "
            + ("лише по кадрах." if kind == "video" else "лише по метаданих.")
        )
        repo.update_job(job_id, status="failed", error=message)
        repo.update_item(item_id, status="ready")
        log.info("Задача %s: %s", job_id, message)
        return
    except Exception as exc:  # noqa: BLE001 — будь-який збій має лишитися видимим
        log.exception("Задача %s впала", job_id)
        repo.update_job(job_id, status="failed", error=str(exc))
        repo.update_item(item_id, status="failed")
        return

    repo.update_job(job_id, status="done", progress=1.0)
    repo.update_item(item_id, status="ready")


def _loop() -> None:
    repo.reset_running_jobs()
    while not _stop.is_set():
        if _paused.is_set():
            time.sleep(0.4)
            continue
        job = repo.next_queued_job()
        if job is None:
            time.sleep(0.5)
            continue
        _run_job(job)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="media-library-worker", daemon=True)
    _thread.start()
    log.info("Воркер запущено")


def stop() -> None:
    _stop.set()


def pause(value: bool) -> None:
    _paused.set() if value else _paused.clear()


def is_paused() -> bool:
    return _paused.is_set()
