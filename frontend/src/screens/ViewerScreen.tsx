import clsx from "clsx";
import { useEffect, useRef, useState } from "react";

import { api } from "../api";
import { SimilarityRing } from "../components/SimilarityRing";
import type { ItemDetail, SearchHit, Tag } from "../types";

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

function DeleteDialog({
  item,
  onCancel,
  onConfirm,
}: {
  item: ItemDetail;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-6">
      <div className="w-full max-w-[420px] rounded-lg border border-line bg-surface p-5">
        <h2 className="text-[15px] font-semibold text-ink">Видалити «{item.label}»?</h2>
        <p className="mt-2 text-[13px] leading-[1.6] text-ink-dim">
          Запис зникне з бібліотеки, і разом із ним буде видалено копію файлу в
          теці бібліотеки. Вихідний файл, з якого його додавали, не постраждає.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded border border-line bg-surface-2 px-3 py-1.5 text-[12px] text-ink-dim hover:text-ink"
          >
            Скасувати
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded bg-error px-3 py-1.5 text-[12px] font-medium text-ground"
          >
            Видалити
          </button>
        </div>
      </div>
    </div>
  );
}

interface Props {
  hits: SearchHit[];
  index: number;
  onIndex: (index: number) => void;
  onBack: () => void;
  onChanged: () => void;
  onDeleted: () => void;
}

export function ViewerScreen({
  hits,
  index,
  onIndex,
  onBack,
  onChanged,
  onDeleted,
}: Props) {
  const hit = hits[index];
  const [item, setItem] = useState<ItemDetail | null>(null);
  const [tags, setTags] = useState<Tag[]>([]);
  const [editing, setEditing] = useState(false);
  const [draftLabel, setDraftLabel] = useState("");
  const [draftTags, setDraftTags] = useState<string[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mediaRef = useRef<HTMLVideoElement & HTMLAudioElement>(null);

  useEffect(() => {
    setItem(null);
    setEditing(false);
    setError(null);
    api.item(hit.item_id).then(setItem).catch((e) => setError((e as Error).message));
  }, [hit.item_id]);

  useEffect(() => {
    api.tags().then(setTags).catch(() => undefined);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (confirmDelete) setConfirmDelete(false);
        else if (editing) setEditing(false);
        else onBack();
        return;
      }
      // Гортання результатів стрілками. Поки запис редагується, стрілки
      // належать полю вводу, а не навігації.
      if (editing || confirmDelete) return;
      if (event.key === "ArrowLeft" && index > 0) onIndex(index - 1);
      if (event.key === "ArrowRight" && index < hits.length - 1) onIndex(index + 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onBack, editing, confirmDelete, index, hits.length, onIndex]);

  const startEditing = () => {
    if (!item) return;
    setDraftLabel(item.label);
    setDraftTags(item.tags);
    setEditing(true);
  };

  const saveEdits = async () => {
    if (!item) return;
    try {
      const updated = await api.patchItem(item.id, {
        label: draftLabel,
        tags: draftTags,
      });
      setItem(updated);
      setEditing(false);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const seekToMatch = () => {
    if (mediaRef.current && hit.match_ts_s !== null) {
      mediaRef.current.currentTime = hit.match_ts_s;
      void mediaRef.current.play();
    }
  };

  if (!item) {
    return (
      <div className="flex h-full items-center justify-center">
        <span className={clsx("text-[12px]", error ? "text-error" : "ml-pulse text-ink-faint")}>
          {error ?? "завантаження…"}
        </span>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-ground">
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

        {hits.length > 1 && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={index === 0}
              onClick={() => onIndex(index - 1)}
              className="rounded border border-line bg-surface px-1.5 py-1 text-[12px] text-ink-dim hover:text-ink disabled:opacity-30"
              title="Попередній результат (←)"
            >
              ←
            </button>
            <span className="tnum text-[11px] text-ink-faint">
              {index + 1} з {hits.length}
            </span>
            <button
              type="button"
              disabled={index === hits.length - 1}
              onClick={() => onIndex(index + 1)}
              className="rounded border border-line bg-surface px-1.5 py-1 text-[12px] text-ink-dim hover:text-ink disabled:opacity-30"
              title="Наступний результат (→)"
            >
              →
            </button>
          </div>
        )}
        {hit.match_ts_s !== null && (item.kind === "video" || item.kind === "audio") && (
          <button
            type="button"
            onClick={seekToMatch}
            className="tnum rounded border border-line bg-surface px-2.5 py-1 text-[11px] text-accent hover:bg-surface-2"
          >
            До збігу {formatTime(hit.match_ts_s)}
          </button>
        )}

        <div className="ml-auto flex items-center gap-2">
          {error && <span className="text-[11px] text-error">{error}</span>}
          <button
            type="button"
            onClick={editing ? saveEdits : startEditing}
            className={clsx(
              "rounded px-2.5 py-1 text-[12px]",
              editing
                ? "bg-accent font-medium text-ground"
                : "border border-line bg-surface text-ink-dim hover:border-line-2 hover:text-ink",
            )}
          >
            {editing ? "Зберегти" : "Редагувати"}
          </button>
          {editing && (
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded border border-line bg-surface px-2.5 py-1 text-[12px] text-ink-dim hover:text-ink"
            >
              Скасувати
            </button>
          )}
          <button
            type="button"
            onClick={() => setConfirmDelete(true)}
            className="rounded border border-line bg-surface px-2.5 py-1 text-[12px] text-ink-dim hover:border-error hover:text-error"
          >
            Видалити
          </button>
        </div>
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
            <video
              ref={mediaRef}
              src={item.media_url}
              controls
              className="max-h-full max-w-full"
            />
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
          <div>
            <div className="font-mono text-[10px] font-semibold tracking-[0.14em] text-ink-faint uppercase">
              Лейбл
            </div>
            {editing ? (
              <input
                value={draftLabel}
                onChange={(e) => setDraftLabel(e.target.value)}
                className="selectable mt-1 w-full rounded border border-accent bg-surface px-2 py-1 text-[12px] text-ink focus:outline-none"
              />
            ) : (
              <div className="selectable mt-0.5 text-[12px] break-words text-ink-dim">
                {item.label}
              </div>
            )}
          </div>

          <Meta label="Тип">
            {item.kind === "image" && `Зображення · ${item.width}×${item.height}`}
            {item.kind === "video" && `Відео · ${formatTime(item.duration_s ?? 0)}`}
            {item.kind === "audio" && `Аудіо · ${formatTime(item.duration_s ?? 0)}`}
            {item.kind === "text" && "Текст"}
            {item.size_bytes ? ` · ${formatBytes(item.size_bytes)}` : ""}
          </Meta>

          <Meta label="Додано">{new Date(item.added_at).toLocaleString("uk-UA")}</Meta>

          <div>
            <div className="font-mono text-[10px] font-semibold tracking-[0.14em] text-ink-faint uppercase">
              Теги
            </div>
            {editing ? (
              <div className="mt-1 flex flex-wrap gap-1">
                {tags.length === 0 ? (
                  <span className="text-[11px] text-ink-faint">словник порожній</span>
                ) : (
                  tags.map((tag) => {
                    const active = draftTags.includes(tag.name);
                    return (
                      <button
                        key={tag.id}
                        type="button"
                        onClick={() =>
                          setDraftTags(
                            active
                              ? draftTags.filter((t) => t !== tag.name)
                              : [...draftTags, tag.name],
                          )
                        }
                        className={clsx(
                          "rounded-sm px-1.5 py-[1px] text-[11px] transition-colors",
                          active
                            ? "bg-accent text-ground"
                            : "bg-surface-3 text-ink-dim-2 hover:text-ink",
                        )}
                      >
                        {tag.name}
                      </button>
                    );
                  })
                )}
              </div>
            ) : (
              <div className="mt-0.5 flex flex-wrap gap-1">
                {item.tags.length === 0 ? (
                  <span className="text-[11px] text-ink-faint">без тегів</span>
                ) : (
                  item.tags.map((tag) => (
                    <span
                      key={tag}
                      className="rounded-sm bg-surface-3 px-1.5 py-[1px] text-[11px] text-ink-dim"
                    >
                      {tag}
                    </span>
                  ))
                )}
              </div>
            )}
          </div>

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
              <p className="mt-1 text-[11px] text-ink-faint">
                {item.transcript_edited
                  ? "виправлено вручну"
                  : "машинний текст · правиться на екрані «Додати»"}
              </p>
            </div>
          )}
        </aside>
      </div>

      {confirmDelete && (
        <DeleteDialog
          item={item}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={async () => {
            await api.deleteItem(item.id);
            onDeleted();
          }}
        />
      )}
    </div>
  );
}
