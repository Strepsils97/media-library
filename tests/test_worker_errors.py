"""Помилки обробки мають лишатися зрозумілими людині."""

from unittest.mock import patch

from backend.app.db import repo
from backend.app.db.connection import init_db
from backend.app.ingest.storage import Prepared
from backend.app.worker import queue


def _job(kind: str = "image") -> tuple[int, int]:
    init_db()
    item_id = repo.create_item(
        Prepared(kind=kind, label="запис", stored_path="ab/x.jpg", source_path=None,
                 content_hash="x", mime=None, size_bytes=1,
                 created_at="2026-01-01T00:00:00+00:00")
    )
    return item_id, repo.create_job(item_id, kind)


def _job_row(job_id: int):
    return next(j for j in repo.list_jobs() if j["id"] == job_id)


def test_out_of_memory_explains_what_to_do(library):
    item_id, job_id = _job()
    boom = RuntimeError("CUDA out of memory. Tried to allocate 512.00 MiB")

    with patch.dict(queue.pipeline.PROCESSORS, {"image": lambda _: (_ for _ in ()).throw(boom)}):
        queue._run_job(_job_row(job_id))

    error = _job_row(job_id)["error"]
    assert "пам'яті відеокарти" in error
    assert "процесор" in error, "людина має дізнатися, що робити далі"
    assert "CUDA out of memory" not in error, "англомовний стек нікому не допоможе"


def test_other_errors_keep_their_message(library):
    item_id, job_id = _job()

    with patch.dict(
        queue.pipeline.PROCESSORS,
        {"image": lambda _: (_ for _ in ()).throw(ValueError("файл битий"))},
    ):
        queue._run_job(_job_row(job_id))

    assert _job_row(job_id)["error"] == "файл битий"
    assert repo.get_item(item_id)["status"] == "failed"


def test_recognises_out_of_memory_variants():
    assert queue._is_out_of_memory(RuntimeError("CUDA out of memory"))
    assert queue._is_out_of_memory(RuntimeError("cublas failed: OUT OF MEMORY"))
    assert not queue._is_out_of_memory(RuntimeError("file not found"))
