export type Kind = "image" | "video" | "audio" | "text";
export type ItemStatus = "pending" | "processing" | "ready" | "failed";
export type JobStatus = "queued" | "running" | "done" | "failed";

export interface Tag {
  id: number;
  name: string;
  usage_count: number;
}

export interface SearchHit {
  item_id: number;
  kind: Kind;
  label: string;
  /** Нормалізована схожість 0..100. Порівнювана між модальностями. */
  score: number;
  /** Чим саме запис заслужив місце у видачі. */
  source: "image" | "text" | "phrase";
  /** Наскільки точно збіглася фраза (лише для source="phrase"). */
  phrase_ratio: number | null;
  created_at: string;
  tags: string[];
  /** Прев'ю: картинка, кадр відео або null для аудіо й тексту. */
  thumb_url: string | null;
  /** Уривок тексту чи транскрибції з підсвіченим збігом. */
  snippet: string | null;
  snippet_highlight: [number, number] | null;
  duration_s: number | null;
  /** Момент у медіа, куди перемотувати. */
  match_ts_s: number | null;
  width: number | null;
  height: number | null;
  word_count: number | null;
}

export interface SearchResponse {
  hits: SearchHit[];
  total: number;
  took_ms: number;
  /** Скільки знайшлося б без фільтрів — для підказки в порожній видачі. */
  total_unfiltered: number;
}

export interface SearchFilters {
  query: string;
  kinds: Kind[];
  tags: string[];
  date_from: string | null;
  date_to: string | null;
}

export interface Job {
  id: number;
  item_id: number | null;
  kind: Kind;
  label: string;
  source_name: string;
  type: string;
  stage: string;
  status: JobStatus;
  progress: number;
  eta_s: number | null;
  error: string | null;
}

export interface LibraryStats {
  item_count: number;
  originals_bytes: number;
  frames_bytes: number;
  models_bytes: number;
  db_bytes: number;
  disk_free_bytes: number;
  disk_total_bytes: number;
  data_dir: string;
}

export interface RuntimeStatus {
  device: "cuda" | "cpu";
  asr_model: string;
  jobs_running: number;
  jobs_queued: number;
  jobs_failed: number;
  progress: number;
  paused: boolean;
}

export interface ItemDetail {
  id: number;
  kind: Kind;
  label: string;
  status: ItemStatus;
  created_at: string;
  added_at: string;
  mime: string | null;
  size_bytes: number | null;
  duration_s: number | null;
  width: number | null;
  height: number | null;
  text_content: string | null;
  transcript: string | null;
  transcript_lang: string | null;
  transcript_edited: boolean;
  tags: string[];
  frames: { id: number; ts_s: number; url: string }[];
  media_url: string | null;
  thumb_url: string | null;
}

export interface UserSettings {
  app_version: string;
  schema_version: number;
  asr_model: string;
  device: "auto" | "cuda" | "cpu";
  theme: "dark" | "light";
  max_frames_per_video: number;
  snippet_words: number;
  available: {
    asr_models: string[];
    devices: string[];
    themes: string[];
  };
}
