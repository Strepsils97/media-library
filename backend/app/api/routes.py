"""HTTP-інтерфейс застосунку."""

from __future__ import annotations

import logging
import shutil
import time
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import settings_store
from ..config import get_settings
from ..db import backup, repo
from ..ingest import export, storage
from ..ingest.pipeline import index_text
from ..ml.cuda import resolve_device
from ..search.query import Filters, search
from ..worker import queue

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

STAGE_LABELS = queue.STAGE_LABELS


# --- моделі запитів -------------------------------------------------------


class SearchRequest(BaseModel):
    query: str = ""
    kinds: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None


class TagRequest(BaseModel):
    name: str


class TextItemRequest(BaseModel):
    text: str
    label: str | None = None


class SettingsPatch(BaseModel):
    # Поля мають збігатися з settings_store.EDITABLE: чого немає тут, те
    # pydantic мовчки викине ще до білого списку. Саме так і сталося з текою
    # завантажень — вона була скрізь, крім цього місця, і перемикач у
    # налаштуваннях не робив нічого. Тепер за збігом стежить тест.
    asr_model: str | None = None
    device: str | None = None
    theme: str | None = None
    max_frames_per_video: int | None = None
    snippet_words: int | None = None
    download_dir: str | None = None


class ExportRequest(BaseModel):
    # Назва рівня з export.DENOISE_LEVELS або порожньо — без обробки.
    denoise: str = ""


class RevealRequest(BaseModel):
    path: str


class ItemPatch(BaseModel):
    label: str | None = None
    transcript: str | None = None
    tags: list[str] | None = None


# --- службове -------------------------------------------------------------


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


# Розміри тек рахувалися обходом файлів на кожен запит, а інтерфейс питає
# статистику кожні дві секунди. На бібліотеці в сім тисяч записів це
# одинадцять гігабайтів оригіналів, дев'яносто тисяч кадрів і ваги моделей —
# шість секунд дискової роботи в циклі, через які гальмувало геть усе,
# включно з відкриттям відео.
#
# Оригінали тепер рахує база: розмір кожного файлу в ній уже є. Кадри —
# обхід із коротким кешем. Ваги за час роботи не змінюються взагалі.
_CACHE_TTL_S = 60.0
_sizes: dict[str, tuple[float, int]] = {}


def _cached_dir_size(path: Path, key: str, ttl: float = _CACHE_TTL_S) -> int:
    now = time.monotonic()
    cached = _sizes.get(key)
    if cached and now - cached[0] < ttl:
        return cached[1]
    value = _dir_size(path)
    _sizes[key] = (now, value)
    return value


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "data_dir": str(settings.data_dir)}


@router.get("/stats")
def stats() -> dict:
    settings = get_settings()
    usage = shutil.disk_usage(settings.data_dir)
    return {
        "item_count": repo.count_items(),
        "originals_bytes": repo.originals_bytes(),
        "frames_bytes": _cached_dir_size(settings.frames_dir, "frames"),
        # Ваги за час роботи застосунку не міняються — рахуємо раз.
        "models_bytes": _cached_dir_size(settings.models_dir, "models", ttl=float("inf")),
        "db_bytes": settings.db_path.stat().st_size if settings.db_path.exists() else 0,
        "disk_free_bytes": usage.free,
        "disk_total_bytes": usage.total,
        "data_dir": str(settings.data_dir),
    }


@router.get("/runtime")
def runtime() -> dict:
    settings = get_settings()
    device, _ = resolve_device(settings.device)
    counts = repo.job_counts()
    running = counts.get("running", 0)

    progress = 0.0
    if running:
        rows = [j for j in repo.list_jobs(20) if j["status"] == "running"]
        if rows:
            progress = sum(float(r["progress"]) for r in rows) / len(rows)

    return {
        "device": device,
        "asr_model": settings.asr_model,
        "jobs_running": running,
        "jobs_queued": counts.get("queued", 0),
        "jobs_failed": counts.get("failed", 0),
        "progress": progress,
        "paused": queue.is_paused(),
    }


@router.get("/settings")
def get_user_settings() -> dict:
    return settings_store.current()


@router.patch("/settings")
def patch_user_settings(request: SettingsPatch) -> dict:
    try:
        return settings_store.update(request.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# --- резервні копії ---------------------------------------------------------


def _backup_payload(item: backup.Backup) -> dict:
    return {
        "name": item.name,
        "created_at": item.created_at,
        "size_bytes": item.size_bytes,
        "reason": item.reason,
    }


@router.get("/backups")
def get_backups() -> dict:
    return {
        "backups": [_backup_payload(b) for b in backup.listing()],
        "keep": backup.KEEP,
        "pending_restore": backup.pending_restore_source(),
    }


@router.post("/backups")
def post_backup() -> dict:
    created = backup.create("manual")
    if created is None:
        raise HTTPException(400, "Немає чого копіювати: база ще порожня")
    return _backup_payload(created)


@router.post("/backups/{name}/restore")
def restore_backup(name: str) -> dict:
    try:
        backup.schedule_restore(name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"pending_restore": name}


@router.delete("/backups/pending")
def cancel_restore() -> dict:
    return {"cancelled": backup.cancel_restore()}


@router.delete("/backups/{name}")
def delete_backup(name: str) -> dict:
    item = next((b for b in backup.listing() if b.name == name), None)
    if item is None:
        raise HTTPException(404, "Копію не знайдено")
    item.path.unlink(missing_ok=True)
    return {"deleted": name}


@router.post("/settings/pick-folder")
def pick_folder() -> dict:
    """Показує системний діалог вибору теки для завантажень."""
    from ..main import pick_folder as show_dialog

    chosen = show_dialog()
    if chosen is None:
        # Скасували або запущено без вікна (режим розробки) — не помилка.
        return {"path": None}
    return {"path": chosen}


@router.post("/library/reindex")
def reindex() -> dict:
    """Ставить усі записи в чергу на повторну обробку.

    Потрібно після зміни моделі розпізнавання: транскрипції старих записів
    інакше лишилися б від попередньої моделі, і бібліотека стала б різнорідною.
    """
    queued = repo.requeue_all()
    return {"queued": queued}


# --- пошук ----------------------------------------------------------------


@router.post("/search")
def do_search(request: SearchRequest) -> dict:
    return search(Filters(**request.model_dump()))


# --- записи ---------------------------------------------------------------


def _item_payload(item: sqlite3.Row) -> dict:
    frames = repo.list_frames(item["id"])
    return {
        "id": item["id"],
        "kind": item["kind"],
        "label": item["label"],
        "status": item["status"],
        "created_at": item["created_at"],
        "added_at": item["added_at"],
        "mime": item["mime"],
        "size_bytes": item["size_bytes"],
        "duration_s": item["duration_s"],
        "width": item["width"],
        "height": item["height"],
        "text_content": item["text_content"],
        "transcript": item["transcript"],
        "transcript_lang": item["transcript_lang"],
        "transcript_edited": bool(item["transcript_edited"]),
        "stored_path": item["stored_path"],
        "tags": repo.tags_for_item(item["id"]),
        "frames": [
            {"id": f["id"], "ts_s": f["ts_s"], "url": f"/api/media/frame/{f['id']}"}
            for f in frames
        ],
        "media_url": f"/api/media/original/{item['id']}" if item["stored_path"] else None,
        "thumb_url": f"/api/media/thumb/{item['id']}" if item["kind"] == "image" else None,
    }


@router.get("/items/{item_id}")
def get_item(item_id: int) -> dict:
    item = repo.get_item(item_id)
    if item is None:
        raise HTTPException(404, "Запис не знайдено")
    return _item_payload(item)


@router.post("/items/upload")
async def upload(files: list[UploadFile]) -> list[dict]:
    """Приймає файли, копіює в бібліотеку й ставить у чергу обробки."""
    settings = get_settings()
    inbox = settings.data_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    created: list[dict] = []
    for upload_file in files:
        temp = inbox / (upload_file.filename or "file")
        with temp.open("wb") as handle:
            shutil.copyfileobj(upload_file.file, handle)

        try:
            prepared = storage.prepare_file(temp)
        except storage.UnsupportedFile as exc:
            created.append({"filename": upload_file.filename, "error": str(exc)})
            temp.unlink(missing_ok=True)
            continue
        finally:
            upload_file.file.close()

        existing = repo.find_by_hash(prepared.content_hash)
        if existing is not None:
            created.append({
                "filename": upload_file.filename,
                "item_id": existing["id"],
                "duplicate": True,
            })
            temp.unlink(missing_ok=True)
            continue

        item_id = repo.create_item(prepared)
        repo.create_job(item_id, prepared.kind)
        created.append({
            "filename": upload_file.filename,
            "item_id": item_id,
            "kind": prepared.kind,
            "label": prepared.label,
            "duplicate": False,
        })
        temp.unlink(missing_ok=True)

    return created


@router.post("/items/text")
def create_text_item(request: TextItemRequest) -> dict:
    try:
        prepared = storage.prepare_text(request.text, request.label)
    except storage.UnsupportedFile as exc:
        raise HTTPException(400, str(exc)) from exc

    existing = repo.find_by_hash(prepared.content_hash)
    if existing is not None:
        return {"item_id": existing["id"], "duplicate": True}

    item_id = repo.create_item(prepared)
    repo.create_job(item_id, "text")
    return {"item_id": item_id, "kind": "text", "label": prepared.label, "duplicate": False}


@router.patch("/items/{item_id}")
def patch_item(item_id: int, request: ItemPatch) -> dict:
    item = repo.get_item(item_id)
    if item is None:
        raise HTTPException(404, "Запис не знайдено")

    if request.label is not None:
        repo.update_item(item_id, label=request.label.strip() or item["label"])

    if request.tags is not None:
        repo.set_item_tags(item_id, request.tags)

    if request.transcript is not None and request.transcript != item["transcript"]:
        repo.update_item(item_id, transcript=request.transcript, transcript_edited=1)
        # Правка транскрипції змінює те, за чим шукається запис, тому вектори
        # перебудовуються одразу — інакше пошук лишився б на старому тексті.
        index_text(item_id, request.transcript)

    return _item_payload(repo.get_item(item_id))


@router.post("/items/{item_id}/export")
def export_item(item_id: int, request: ExportRequest) -> dict:
    """Кладе копію запису в теку завантажень, за потреби — з очищеним звуком."""
    item = repo.get_item(item_id)
    if item is None:
        raise HTTPException(404, "Запис не знайдено")

    try:
        path = export.export_item(item, denoise=request.denoise)
    except export.ExportFailed as exc:
        raise HTTPException(400, str(exc)) from exc

    return {"path": str(path), "name": path.name, "denoised": request.denoise}


@router.get("/denoise-levels")
def denoise_levels() -> dict:
    return {"levels": list(export.DENOISE_LEVELS), "default": export.DEFAULT_LEVEL}


@router.post("/reveal")
def reveal_file(request: RevealRequest) -> dict:
    """Показує щойно збережений файл у провіднику."""
    path = Path(request.path)
    target_dir = export.default_target_dir().resolve()

    # Шлях приходить від клієнта, тож показуємо лише те, що самі й зберегли:
    # відкривати провідник на будь-якому шляху з мережевого запиту не варто.
    try:
        inside = path.resolve().is_relative_to(target_dir)
    except OSError:
        inside = False
    if not inside:
        raise HTTPException(400, "Показати можна лише збережений цим застосунком файл")

    return {"revealed": export.reveal(path)}


class HeatRequest(BaseModel):
    query: str = ""


@router.post("/items/{item_id}/heat")
def item_heat(item_id: int, request: HeatRequest) -> dict:
    """Наскільки кожна ділянка тексту відповідає запиту.

    Окремим запитом, а не разом із записом: це секунда роботи моделі, і
    потрібна вона лише тоді, коли запис відкрили саме з пошуку.
    """
    item = repo.get_item(item_id)
    if item is None:
        raise HTTPException(404, "Запис не знайдено")

    text = item["transcript"] or item["text_content"] or ""
    if not text or not request.query.strip():
        return {"spans": []}

    from ..ml.registry import get_text_embedder
    from ..search.heat import word_heat

    spans = word_heat(text, request.query, get_text_embedder())
    return {"spans": [[start, end, value] for start, end, value in spans]}


@router.delete("/items/{item_id}")
def remove_item(item_id: int) -> dict:
    settings = get_settings()
    item = repo.delete_item(item_id)
    if item is None:
        raise HTTPException(404, "Запис не знайдено")

    # Видалення запису прибирає й скопійований оригінал: бібліотека не має
    # накопичувати файли, на які вже ніщо не посилається.
    if item["stored_path"]:
        (settings.originals_dir / item["stored_path"]).unlink(missing_ok=True)
    if item["content_hash"]:
        thumb = settings.thumbs_dir / item["content_hash"][:2] / f"{item['content_hash']}.webp"
        thumb.unlink(missing_ok=True)
        # Оброблений звук у кеші прослуховування теж лишається без господаря.
        for cached in (settings.data_dir / "cache" / "denoise").glob(
            f"{item['content_hash']}-*.mp3"
        ):
            cached.unlink(missing_ok=True)
    return {"deleted": item_id}


# --- медіа ----------------------------------------------------------------


@router.get("/media/original/{item_id}")
def media_original(item_id: int) -> FileResponse:
    settings = get_settings()
    item = repo.get_item(item_id)
    if item is None or not item["stored_path"]:
        raise HTTPException(404, "Файл не знайдено")
    path = settings.originals_dir / item["stored_path"]
    if not path.exists():
        raise HTTPException(404, "Файл не знайдено на диску")
    return FileResponse(path, media_type=item["mime"] or "application/octet-stream")


@router.get("/media/thumb/{item_id}")
def media_thumb(item_id: int) -> FileResponse:
    settings = get_settings()
    item = repo.get_item(item_id)
    if item is None or not item["content_hash"]:
        raise HTTPException(404, "Прев'ю не знайдено")
    path = settings.thumbs_dir / item["content_hash"][:2] / f"{item['content_hash']}.webp"
    if not path.exists():
        raise HTTPException(404, "Прев'ю ще не готове")
    return FileResponse(path, media_type="image/webp")


@router.get("/media/preview/{item_id}")
def media_preview(item_id: int, level: str) -> FileResponse:
    """Звук, оброблений обраним рівнем — щоб послухати до завантаження."""
    item = repo.get_item(item_id)
    if item is None or item["kind"] not in export.AUDIBLE:
        raise HTTPException(404, "Для цього запису обробка звуку не застосовна")

    try:
        path = export.preview_path(item, level)
    except export.ExportFailed as exc:
        raise HTTPException(400, str(exc)) from exc

    return FileResponse(path, media_type="audio/mpeg")


@router.get("/media/frame/{frame_id}")
def media_frame(frame_id: int) -> FileResponse:
    settings = get_settings()
    row = repo.get_frame(frame_id)
    if row is None:
        raise HTTPException(404, "Кадр не знайдено")
    path = settings.frames_dir / row["path"]
    if not path.exists():
        raise HTTPException(404, "Кадр не знайдено на диску")
    return FileResponse(path, media_type="image/webp")


# --- теги -----------------------------------------------------------------


@router.get("/tags")
def get_tags() -> list[dict]:
    return [
        {"id": row["id"], "name": row["name"], "usage_count": row["usage_count"]}
        for row in repo.list_tags()
    ]


@router.post("/tags")
def post_tag(request: TagRequest) -> dict:
    name = request.name.strip()
    if not name:
        raise HTTPException(400, "Порожня назва тега")
    try:
        row = repo.create_tag(name)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, f"Тег «{name}» уже існує") from exc
    return {"id": row["id"], "name": row["name"], "usage_count": 0}


@router.patch("/tags/{tag_id}")
def patch_tag(tag_id: int, request: TagRequest) -> dict:
    name = request.name.strip()
    if not name:
        raise HTTPException(400, "Порожня назва тега")
    try:
        repo.rename_tag(tag_id, name)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, f"Тег «{name}» уже існує") from exc
    return {"id": tag_id, "name": name}


@router.delete("/tags/{tag_id}")
def remove_tag(tag_id: int) -> dict:
    repo.delete_tag(tag_id)
    return {"deleted": tag_id}


# --- черга ----------------------------------------------------------------


@router.get("/jobs")
def get_jobs() -> list[dict]:
    result = []
    for row in repo.list_jobs():
        result.append({
            "id": row["id"],
            "item_id": row["item_id"],
            "kind": row["kind"] or row["type"],
            "label": row["label"] or "—",
            "source_name": Path(row["stored_path"]).name if row["stored_path"] else "вставлений текст",
            "type": row["type"],
            "stage": STAGE_LABELS.get(row["type"], row["type"]),
            "status": row["status"],
            "progress": float(row["progress"]),
            "eta_s": None,
            "error": row["error"],
        })
    return result


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int) -> dict:
    repo.update_job(job_id, status="queued", progress=0.0, error=None)
    return {"id": job_id, "status": "queued"}


@router.delete("/jobs/{job_id}")
def cancel_job(job_id: int) -> dict:
    """Знімає задачу з черги або перериває ту, що виконується."""
    job = next((j for j in repo.list_jobs(500) if j["id"] == job_id), None)
    if job is None:
        raise HTTPException(404, "Задачу не знайдено")

    if job["status"] == "running":
        # Модель не вміє зупинятися посеред виклику — воркер перевірить
        # прапорець на наступному кроці й перерве обробку сам.
        queue.request_cancel(job_id)
        return {"cancelled": job_id, "pending": True}

    repo.update_job(job_id, status="done", error="Знято з черги")
    return {"cancelled": job_id, "pending": False}


@router.post("/jobs/clear-done")
def clear_done() -> dict:
    return {"removed": repo.clear_done_jobs()}


@router.post("/jobs/pause")
def pause_jobs(value: bool = True) -> dict:
    queue.pause(value)
    return {"paused": queue.is_paused()}
