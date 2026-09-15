-- Схема бібліотеки. Векторні таблиці створюються окремо (див. connection.py):
-- vec0 вимагає фіксованої розмірності на момент створення, а вона залежить
-- від обраних моделей.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS items (
    id                INTEGER PRIMARY KEY,
    kind              TEXT    NOT NULL CHECK (kind IN ('image', 'video', 'audio', 'text')),
    label             TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending', 'processing', 'ready', 'failed')),

    -- Дата створення оригіналу (EXIF / метадані контейнера / mtime), UTC ISO-8601.
    created_at        TEXT    NOT NULL,
    added_at          TEXT    NOT NULL,

    stored_path       TEXT,               -- відносно data/originals; NULL для вставленого тексту
    source_path       TEXT,               -- звідки взяли, довідково
    content_hash      TEXT,               -- sha256 вмісту, для дедуплікації
    mime              TEXT,
    size_bytes        INTEGER,

    duration_s        REAL,
    width             INTEGER,
    height            INTEGER,

    text_content      TEXT,               -- для kind='text'
    transcript        TEXT,               -- для kind IN ('audio','video')
    transcript_lang   TEXT,
    transcript_edited INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_items_hash ON items(content_hash)
    WHERE content_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_items_kind    ON items(kind);
CREATE INDEX IF NOT EXISTS idx_items_created ON items(created_at);
CREATE INDEX IF NOT EXISTS idx_items_status  ON items(status);

CREATE TABLE IF NOT EXISTS tags (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS item_tags (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (item_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_item_tags_tag ON item_tags(tag_id);

CREATE TABLE IF NOT EXISTS frames (
    id      INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    ts_s    REAL    NOT NULL,
    path    TEXT    NOT NULL           -- відносно data/frames
);

CREATE INDEX IF NOT EXISTS idx_frames_item ON frames(item_id);

-- Міст між записами та векторними таблицями.
-- Один item може мати багато векторів: кадри відео плюс транскрибція.
CREATE TABLE IF NOT EXISTS embeddings (
    id         INTEGER PRIMARY KEY,
    item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    space      TEXT    NOT NULL CHECK (space IN ('image_a', 'image_b', 'text')),
    frame_id   INTEGER REFERENCES frames(id) ON DELETE CASCADE,
    chunk_ix   INTEGER,                -- порядковий номер фрагмента для довгих текстів
    chunk_text TEXT,                   -- сам фрагмент, щоб підсвітити його у видачі
    ts_s       REAL,                   -- момент у медіа, куди перемотувати
    vec_rowid  INTEGER NOT NULL        -- rowid у vec_image / vec_text
);

CREATE INDEX IF NOT EXISTS idx_emb_item      ON embeddings(item_id);
CREATE INDEX IF NOT EXISTS idx_emb_space_row ON embeddings(space, vec_rowid);

-- Повнотекстовий індекс над фрагментами транскрипцій і текстів.
-- Векторний пошук знаходить сенс, але не вміє знайти конкретну фразу,
-- надто якщо розпізнавання її трохи спотворило. FTS дає швидкий відбір
-- кандидатів, які далі переоцінюються нечітким зіставленням.
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    chunk_text,
    tokenize = "unicode61 remove_diacritics 2"
);

CREATE TABLE IF NOT EXISTS jobs (
    id         INTEGER PRIMARY KEY,
    item_id    INTEGER REFERENCES items(id) ON DELETE CASCADE,
    type       TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'queued'
                       CHECK (status IN ('queued', 'running', 'done', 'failed')),
    progress   REAL    NOT NULL DEFAULT 0.0,
    error      TEXT,
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

-- Калібрування оцінок схожості (Фаза 9): по одному рядку на простір.
CREATE TABLE IF NOT EXISTS score_calibration (
    space      TEXT PRIMARY KEY,
    mean       REAL NOT NULL,
    stddev     REAL NOT NULL,
    sample_n   INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
