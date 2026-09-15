"""Пошук: три векторні простори, нечіткий пошук фрази, злиття оцінок.

Запис може знайтися трьома різними шляхами, і кожен із них має власну шкалу:

* **зображення** — дві моделі незалежно оцінюють кадр або картинку;
* **текст** — смисловий збіг із транскрипцією чи нотаткою;
* **фраза** — лексичний збіг із допуском на помилки розпізнавання.

Щоб їх можна було порівнювати, кожна шкала зводиться до однієї спільної
(див. calibration.py): оцінка означає «наскільки цей збіг незвичний для свого
простору», а не сирий косинус, у якого в кожної моделі свій діапазон.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field

from ..config import get_settings
from ..db import repo
from ..db.connection import IMAGE_SPACES, TEXT_SPACE, get_connection, knn, similarities
from ..ingest.text import snippet, word_count
from ..ml.registry import get_image_embedder, get_text_embedder
from . import calibration, phrase
from .highlight import find_span

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Filters:
    query: str
    kinds: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None


@dataclass(slots=True)
class Evidence:
    """Чим саме запис заслужив своє місце у видачі."""

    score: float
    source: str  # image | text | phrase
    meta: sqlite3.Row | None = None
    phrase_ratio: float | None = None


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


def _meta_by_rowid(
    conn: sqlite3.Connection, space: str, vec_rowids: list[int]
) -> dict[int, sqlite3.Row]:
    result: dict[int, sqlite3.Row] = {}
    for start in range(0, len(vec_rowids), 400):
        chunk = vec_rowids[start : start + 400]
        rows = conn.execute(
            "SELECT * FROM embeddings WHERE space = ? "  # noqa: S608
            f"AND vec_rowid IN ({','.join('?' * len(chunk))})",
            (space, *chunk),
        ).fetchall()
        for row in rows:
            result[int(row["vec_rowid"])] = row
    return result


def _cosine(distance: float) -> float:
    """Вектори нормовані, тож cos = 1 − d²/2."""
    return 1.0 - (distance * distance) / 2.0


def _image_evidence(
    conn: sqlite3.Connection,
    queries: dict[str, list[float]],
    allowed: set[int] | None,
    limit: int,
) -> dict[int, Evidence]:
    """Оцінка зображень як спільна думка всіх візуальних моделей.

    Кадр, який потрапив у видачу однієї моделі, але не втрапив у межі kNN
    іншої, не викидається: його схожість у другому просторі дораховується
    точно. Інакше кандидат, знайдений лише однією моделлю, мав би штучно
    занижене середнє й програвав би тим, кого знайшли обидві.
    """
    # (item_id, frame_id) -> {space: cos}
    scores: dict[tuple[int, int | None], dict[str, float]] = defaultdict(dict)
    # (item_id, frame_id) -> рядок embeddings (для кадру й моменту)
    meta_by_key: dict[tuple[int, int | None], sqlite3.Row] = {}
    # space -> {(item_id, frame_id): vec_rowid}
    rowid_by_key: dict[str, dict[tuple[int, int | None], int]] = {}

    for space in IMAGE_SPACES:
        restrict = _vec_rowids_for_items(conn, space, allowed)
        if restrict is not None and not restrict:
            continue

        rows = knn(conn, space, queries[space], limit, restrict)
        if not rows:
            continue

        metas = _meta_by_rowid(conn, space, [int(r["rowid"]) for r in rows])
        for row in rows:
            meta = metas.get(int(row["rowid"]))
            if meta is None:
                continue
            key = (int(meta["item_id"]), meta["frame_id"])
            scores[key][space] = _cosine(float(row["distance"]))
            meta_by_key.setdefault(key, meta)

    if not scores:
        return {}

    # Добираємо те, чого бракує, точним обчисленням.
    for space in IMAGE_SPACES:
        missing = [key for key, got in scores.items() if space not in got]
        if not missing:
            continue

        if space not in rowid_by_key:
            rowid_by_key[space] = {}
            placeholders = ",".join("?" * len({k[0] for k in scores}))
            rows = conn.execute(
                "SELECT item_id, frame_id, vec_rowid FROM embeddings "  # noqa: S608
                f"WHERE space = ? AND item_id IN ({placeholders})",
                (space, *{k[0] for k in scores}),
            ).fetchall()
            for row in rows:
                rowid_by_key[space][(int(row["item_id"]), row["frame_id"])] = int(
                    row["vec_rowid"]
                )

        wanted = {key: rowid_by_key[space][key] for key in missing if key in rowid_by_key[space]}
        if not wanted:
            continue
        exact = similarities(conn, space, queries[space], wanted.values())
        for key, vec_rowid in wanted.items():
            if vec_rowid in exact:
                scores[key][space] = exact[vec_rowid]

    calibrations = {space: calibration.get(space) for space in IMAGE_SPACES}

    best: dict[int, Evidence] = {}
    for key, per_space in scores.items():
        values = [
            calibration.to_score(cos, calibrations[space])
            for space, cos in per_space.items()
        ]
        score = sum(values) / len(values)
        item_id = key[0]
        if item_id not in best or score > best[item_id].score:
            best[item_id] = Evidence(score, "image", meta_by_key[key])

    return best


def _text_evidence(
    conn: sqlite3.Connection, query: list[float], allowed: set[int] | None, limit: int
) -> tuple[dict[int, Evidence], set[int]]:
    """Смисловий збіг із текстами. Другим значенням — які фрагменти дивилися:
    вони ж потім ідуть у фразовий прохід як додаткові кандидати."""
    restrict = _vec_rowids_for_items(conn, TEXT_SPACE, allowed)
    if restrict is not None and not restrict:
        return {}, set()

    rows = knn(conn, TEXT_SPACE, query, limit, restrict)
    if not rows:
        return {}, set()

    metas = _meta_by_rowid(conn, TEXT_SPACE, [int(r["rowid"]) for r in rows])
    cal = calibration.get(TEXT_SPACE)

    best: dict[int, Evidence] = {}
    for row in rows:
        meta = metas.get(int(row["rowid"]))
        if meta is None:
            continue
        score = calibration.to_score(_cosine(float(row["distance"])), cal)
        item_id = int(meta["item_id"])
        if item_id not in best or score > best[item_id].score:
            best[item_id] = Evidence(score, "text", meta)

    return best, {int(meta["id"]) for meta in metas.values()}


def search(filters: Filters) -> dict:
    started = time.perf_counter()
    settings = get_settings()
    conn = get_connection()

    total_unfiltered = repo.count_items()
    if not filters.query.strip():
        return {"hits": [], "total": 0, "took_ms": 0, "total_unfiltered": total_unfiltered}

    allowed = _filtered_item_ids(conn, filters)
    limit = settings.knn_candidates

    # Запит кодується кожним енкодером окремо — простори різні.
    image_queries = {
        space: vectors[0].tolist()
        for space, vectors in get_image_embedder().encode_queries([filters.query]).items()
    }
    text_query = get_text_embedder().encode_queries([filters.query])[0].tolist()

    evidence: dict[int, Evidence] = {}

    def offer(item_id: int, candidate: Evidence) -> None:
        # Запис лишається у видачі один раз — за найсильнішим зі своїх збігів.
        # Відео, знайдене і кадром, і транскрипцією, не має дублюватися.
        current = evidence.get(item_id)
        if current is None or candidate.score > current.score:
            evidence[item_id] = candidate

    for item_id, found in _image_evidence(conn, image_queries, allowed, limit).items():
        offer(item_id, found)
    text_found, text_chunks = _text_evidence(conn, text_query, allowed, limit)
    for item_id, found in text_found.items():
        offer(item_id, found)

    words = phrase.word_count(filters.query)
    for item_id, (ratio, row) in phrase.find(
        conn, filters.query, allowed, text_chunks
    ).items():
        offer(item_id, Evidence(phrase.to_score(ratio, words), "phrase", row, ratio))

    hits = []
    for item_id, found in sorted(evidence.items(), key=lambda kv: -kv[1].score):
        item = repo.get_item(item_id)
        if item is None:
            continue
        hits.append(_build_hit(item, found, filters.query))

    return {
        "hits": hits,
        "total": len(hits),
        "took_ms": int((time.perf_counter() - started) * 1000),
        "total_unfiltered": total_unfiltered,
    }


def _pick_frame(frames: list[sqlite3.Row], meta: sqlite3.Row | None) -> sqlite3.Row:
    """Кадр, який найкраще пояснює збіг.

    Збіг по кадру вказує на конкретний кадр. Збіг по транскрипції чи фразі
    кадру не має, але має момент — тоді беремо найближчий до нього кадр:
    показувати перший-ліпший, коли відомо, на якій хвилині прозвучала фраза,
    було б просто неправдою про результат.
    """
    if meta is None:
        return frames[0]

    if meta["frame_id"] is not None:
        return next((f for f in frames if f["id"] == meta["frame_id"]), frames[0])

    ts = meta["ts_s"]
    if ts is None:
        return frames[0]
    return min(frames, key=lambda f: abs(float(f["ts_s"]) - float(ts)))


def _build_hit(item: sqlite3.Row, found: Evidence, query: str) -> dict:
    kind = item["kind"]
    meta = found.meta
    thumb_url: str | None = None

    if kind == "image":
        thumb_url = f"/api/media/thumb/{item['id']}"
    elif kind == "video":
        frames = repo.list_frames(item["id"])
        if frames:
            chosen = _pick_frame(frames, meta)
            thumb_url = f"/api/media/frame/{chosen['id']}"

    body = ""
    if meta is not None and meta["chunk_text"]:
        body = meta["chunk_text"]
    else:
        body = item["transcript"] or item["text_content"] or ""

    text_snippet = snippet(body) if body else None
    span = find_span(text_snippet, query) if text_snippet else None

    return {
        "item_id": item["id"],
        "kind": kind,
        "label": item["label"],
        "score": round(found.score, 1),
        "source": found.source,
        "phrase_ratio": round(found.phrase_ratio, 2) if found.phrase_ratio else None,
        "created_at": item["created_at"],
        "tags": repo.tags_for_item(item["id"]),
        "thumb_url": thumb_url,
        "snippet": text_snippet,
        "snippet_highlight": span,
        "duration_s": item["duration_s"],
        "match_ts_s": meta["ts_s"] if meta is not None else None,
        "width": item["width"],
        "height": item["height"],
        "word_count": word_count(item["text_content"]) if item["text_content"] else None,
    }
