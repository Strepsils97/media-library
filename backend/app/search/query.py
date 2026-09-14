"""Пошук: kNN у двох просторах, фільтри, нормалізація та злиття оцінок."""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field

import numpy as np

from ..config import get_settings
from ..db.connection import get_connection, knn
from ..db import repo
from ..ingest.text import snippet, word_count
from ..ml.registry import get_image_embedder, get_text_embedder
from . import calibration

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Filters:
    query: str
    kinds: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None


def _filtered_item_ids(conn: sqlite3.Connection, filters: Filters) -> set[int] | None:
    """Множина id, що проходять фільтри. None означає «фільтрів немає»."""
    clauses: list[str] = []
    params: list[object] = []

    if filters.kinds:
        clauses.append(f"kind IN ({','.join('?' * len(filters.kinds))})")
        params.extend(filters.kinds)
    if filters.date_from:
        clauses.append("created_at >= ?")
        params.append(filters.date_from)
    if filters.date_to:
        clauses.append("created_at <= ?")
        params.append(filters.date_to)
    if filters.tags:
        clauses.append(
            "id IN (SELECT it.item_id FROM item_tags it JOIN tags t ON t.id = it.tag_id "
            f"WHERE t.name IN ({','.join('?' * len(filters.tags))}))"
        )
        params.extend(filters.tags)

    if not clauses:
        return None

    rows = conn.execute(
        f"SELECT id FROM items WHERE {' AND '.join(clauses)}",  # noqa: S608 — клаузи з коду
        params,
    ).fetchall()
    return {int(row["id"]) for row in rows}


def _vec_rowids_for_items(
    conn: sqlite3.Connection, space: str, item_ids: set[int] | None
) -> list[int] | None:
    if item_ids is None:
        return None
    if not item_ids:
        return []
    placeholders = ",".join("?" * len(item_ids))
    rows = conn.execute(
        f"SELECT vec_rowid FROM embeddings WHERE space = ? AND item_id IN ({placeholders})",  # noqa: S608
        (space, *item_ids),
    ).fetchall()
    return [int(row["vec_rowid"]) for row in rows]


def search(filters: Filters) -> dict:
    started = time.perf_counter()
    settings = get_settings()
    conn = get_connection()

    total_unfiltered = repo.count_items()
    if not filters.query.strip():
        return {"hits": [], "total": 0, "took_ms": 0, "total_unfiltered": total_unfiltered}

    allowed = _filtered_item_ids(conn, filters)

    # Запит кодується двічі — під кожен простір своїм енкодером.
    image_query = get_image_embedder().encode_queries([filters.query])[0]
    text_query = get_text_embedder().encode_queries([filters.query])[0]

    # item_id -> (оцінка, рядок embeddings)
    best: dict[int, tuple[float, sqlite3.Row]] = {}

    for space, vector in (("image", image_query), ("text", text_query)):
        restrict = _vec_rowids_for_items(conn, space, allowed)
        if restrict is not None and not restrict:
            continue

        rows = knn(conn, space, vector.tolist(), settings.knn_candidates, restrict)
        if not rows:
            continue

        # Вектори нормовані, тож cos = 1 - d²/2.
        cal = calibration.get(space)
        scores = [
            calibration.to_score(1.0 - (float(row["distance"]) ** 2) / 2.0, cal)
            for row in rows
        ]
        for row, score in zip(rows, scores, strict=True):
            meta = conn.execute(
                "SELECT * FROM embeddings WHERE space = ? AND vec_rowid = ?",
                (space, int(row["rowid"])),
            ).fetchone()
            if meta is None:
                continue
            item_id = int(meta["item_id"])
            # Відео, що збіглося і кадром, і транскрибцією, не має з'являтися
            # двічі — лишаємо найкращий збіг по запису.
            if item_id not in best or score > best[item_id][0]:
                best[item_id] = (score, meta)

    hits = []
    for item_id, (score, meta) in sorted(best.items(), key=lambda kv: -kv[1][0]):
        item = repo.get_item(item_id)
        if item is None:
            continue
        hits.append(_build_hit(item, score, meta))

    return {
        "hits": hits,
        "total": len(hits),
        "took_ms": int((time.perf_counter() - started) * 1000),
        "total_unfiltered": total_unfiltered,
    }


def _build_hit(item: sqlite3.Row, score: float, meta: sqlite3.Row) -> dict:
    kind = item["kind"]
    thumb_url: str | None = None

    if kind == "image":
        thumb_url = f"/api/media/thumb/{item['id']}"
    elif kind == "video":
        frame_id = meta["frame_id"]
        frames = repo.list_frames(item["id"])
        if frames:
            chosen = next((f for f in frames if f["id"] == frame_id), frames[0])
            thumb_url = f"/api/media/frame/{chosen['id']}"

    body = meta["chunk_text"] or item["transcript"] or item["text_content"] or ""
    text_snippet = snippet(body) if body else None

    return {
        "item_id": item["id"],
        "kind": kind,
        "label": item["label"],
        "score": round(score, 1),
        "created_at": item["created_at"],
        "tags": repo.tags_for_item(item["id"]),
        "thumb_url": thumb_url,
        "snippet": text_snippet,
        "snippet_highlight": None,
        "duration_s": item["duration_s"],
        "match_ts_s": meta["ts_s"],
        "width": item["width"],
        "height": item["height"],
        "word_count": word_count(item["text_content"]) if item["text_content"] else None,
    }
