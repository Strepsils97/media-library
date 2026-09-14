import { useEffect, useRef, useState } from "react";

import { SimilarityRing } from "../components/SimilarityRing";
import type { Kind, SearchHit } from "../types";

interface ItemDetail {
  id: number;
  kind: Kind;
  label: string;
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
  tags: string[];
  frames: { id: number; ts_s: number; url: string }[];
  media_url: string | null;
}

function formatTime(seconds: number): string {
  const total = Math.round(seconds);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function formatBytes(bytes: number): string {
  const units = ["Б", "КБ", "МБ", "ГБ"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1).replace(".", ",")} ${units[unit]}`;
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="font-mono text-[10px] font-semibold tracking-[0.14em] text-ink-faint uppercase">
        {label}
      </div>
      <div className="selectable mt-0.5 text-[12px] break-words text-ink-dim">
        {children}
      </div>
    </div>
  );
}

interface Props {
  hit: SearchHit;
  onBack: () => void;
  onDeleted: () => void;
}

export function ViewerScreen({ hit, onBack, onDeleted }: Props) {
  const [item, setItem] = useState<ItemDetail | null>(null);
  const mediaRef = useRef<HTMLVideoElement & HTMLAudioElement>(null);

  useEffect(() => {
    fetch(`/api/items/${hit.item_id}`)
      .then((r) => r.json())
      .then(setItem)
      .catch(() => undefined);
  }, [hit.item_id]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onBack();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onBack]);

  const seekToMatch = () => {
    if (mediaRef.current && hit.match_ts_s !== null) {
      mediaRef.current.currentTime = hit.match_ts_s;
      void mediaRef.current.play();
    }
  };

  const remove = async () => {
    await fetch(`/api/items/${hit.item_id}`, { method: "DELETE" });
    onDeleted();
  };

  if (!item) {
    return (
      <div className="flex h-full items-center justify-center">
        <span className="ml-pulse text-[12px] text-ink-faint">завантаження…</span>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-3 border-b border-line px-4 py-2.5">
        <button
          type="button"
          onClick={onBack}
          className="rounded border border-line bg-surface px-2.5 py-1 text-[12px] text-ink-dim hover:border-line-2 hover:text-ink"
        >
          ← До результатів
        </button>
        <h1 className="min-w-0 truncate text-[15px] font-semibold text-ink">
          {item.label}
        </h1>
        <SimilarityRing score={hit.score} size={26} />
        {hit.match_ts_s !== null && (item.kind === "video" || item.kind === "audio") && (
          <button
            type="button"
            onClick={seekToMatch}
            className="tnum rounded border border-line bg-surface px-2.5 py-1 text-[11px] text-accent hover:bg-surface-2"
          >
            До збігу {formatTime(hit.match_ts_s)}
          </button>
        )}
        <button
          type="button"
          onClick={remove}
          className="ml-auto rounded border border-line bg-surface px-2.5 py-1 text-[12px] text-ink-dim hover:border-error hover:text-error"
        >
          Видалити
        </button>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="grid min-w-0 flex-1 place-items-center bg-stage p-4">
          {item.kind === "image" && item.media_url && (
            <img
              src={item.media_url}
              alt={item.label}
              className="max-h-full max-w-full object-contain"
            />
          )}
          {item.kind === "video" && item.media_url && (
            <video ref={mediaRef} src={item.media_url} controls className="max-h-full max-w-full" />
          )}
          {item.kind === "audio" && item.media_url && (
            <audio ref={mediaRef} src={item.media_url} controls className="w-[70%]" />
          )}
          {item.kind === "text" && (
            <div className="selectable font-serif h-full w-full max-w-[680px] overflow-y-auto p-6 text-[13.5px] leading-[1.75] text-ink">
              {item.text_content}
            </div>
          )}
        </div>

        <aside className="w-[260px] shrink-0 space-y-4 overflow-y-auto border-l border-line bg-canvas p-4">
          <Meta label="Лейбл">{item.label}</Meta>
          <Meta label="Тип">
            {item.kind === "image" && `Зображення · ${item.width}×${item.height}`}
            {item.kind === "video" &&
              `Відео · ${formatTime(item.duration_s ?? 0)}`}
            {item.kind === "audio" &&
              `Аудіо · ${formatTime(item.duration_s ?? 0)}`}
            {item.kind === "text" && "Текст"}
            {item.size_bytes ? ` · ${formatBytes(item.size_bytes)}` : ""}
          </Meta>
          <Meta label="Додано">
            {new Date(item.added_at).toLocaleString("uk-UA")}
          </Meta>
          <Meta label="Теги">
            {item.tags.length === 0 ? (
              <span className="text-ink-faint">без тегів</span>
            ) : (
              <span className="flex flex-wrap gap-1">
                {item.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-sm bg-surface-3 px-1.5 py-[1px] text-[11px]"
                  >
                    {tag}
                  </span>
                ))}
              </span>
            )}
          </Meta>

          {item.frames.length > 0 && (
            <div>
              <div className="font-mono text-[10px] font-semibold tracking-[0.14em] text-ink-faint uppercase">
                Кадри
              </div>
              <div className="mt-1 grid grid-cols-2 gap-1">
                {item.frames.map((frame) => (
                  <button
                    key={frame.id}
                    type="button"
                    onClick={() => {
                      if (mediaRef.current) mediaRef.current.currentTime = frame.ts_s;
                    }}
                    className="text-left"
                  >
                    <img
                      src={frame.url}
                      alt=""
                      className="aspect-4/3 w-full rounded border border-line object-cover hover:border-accent"
                    />
                    <div className="tnum mt-0.5 text-[10px] text-ink-faint">
                      {formatTime(frame.ts_s)}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {item.transcript && (
            <div>
              <div className="font-mono text-[10px] font-semibold tracking-[0.14em] text-ink-faint uppercase">
                Транскрибція · {item.transcript_lang}
              </div>
              <p className="selectable mt-1 text-[12px] leading-[1.6] text-ink-dim">
                {item.transcript}
              </p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
