import clsx from "clsx";
import { useEffect, useRef, useState } from "react";

import { api } from "../api";
import type { Job, Kind, Tag } from "../types";

const KIND_LABEL: Record<Kind, string> = {
  image: "ІМГ",
  video: "ВІД",
  audio: "АУД",
  text: "ТХТ",
};

interface ItemDetail {
  id: number;
  kind: Kind;
  label: string;
  status: string;
  transcript: string | null;
  transcript_lang: string | null;
  transcript_edited: boolean;
  tags: string[];
  duration_s: number | null;
  size_bytes: number | null;
  frames: { id: number; ts_s: number; url: string }[];
}

function formatTime(seconds: number): string {
  const total = Math.round(seconds);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="font-mono text-[10px] font-semibold tracking-[0.14em] text-ink-faint uppercase">
      {children}
    </div>
  );
}

export function AddScreen({ onAdded }: { onAdded: () => void }) {
  const [mode, setMode] = useState<"file" | "text">("file");
  const [dragging, setDragging] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<ItemDetail | null>(null);
  const [tags, setTags] = useState<Tag[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.tags().then(setTags).catch(() => undefined);
  }, []);

  useEffect(() => {
    const load = () =>
      api
        .jobs()
        .then((all) => setJobs(all.filter((j) => j.status !== "done").slice(0, 40)))
        .catch(() => undefined);
    load();
    const timer = window.setInterval(load, 1500);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (selected === null) {
      setDetail(null);
      return;
    }
    const load = () =>
      fetch(`/api/items/${selected}`)
        .then((r) => r.json())
        .then(setDetail)
        .catch(() => undefined);
    load();
    // Транскрибція з'являється не одразу — поле має оживати саме.
    const timer = window.setInterval(load, 2000);
    return () => window.clearInterval(timer);
  }, [selected]);

  const upload = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (list.length === 0) return;
    setBusy(true);
    const form = new FormData();
    list.forEach((file) => form.append("files", file));
    try {
      const response = await fetch("/api/items/upload", { method: "POST", body: form });
      const created = (await response.json()) as { item_id?: number }[];
      const first = created.find((c) => c.item_id);
      if (first?.item_id) setSelected(first.item_id);
      onAdded();
    } finally {
      setBusy(false);
    }
  };

  const saveText = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      const created = await fetch("/api/items/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      }).then((r) => r.json());
      setText("");
      if (created.item_id) setSelected(created.item_id);
      onAdded();
    } finally {
      setBusy(false);
    }
  };

  const patch = async (payload: Record<string, unknown>) => {
    if (selected === null) return;
    const updated = await fetch(`/api/items/${selected}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then((r) => r.json());
    setDetail(updated);
  };

  return (
    <div
      className="flex h-full"
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        upload(e.dataTransfer.files);
      }}
    >
      <aside className="flex w-[280px] shrink-0 flex-col border-r border-line bg-canvas">
        <div className="flex items-baseline gap-2 px-3 py-3">
          <h2 className="text-[13px] font-semibold text-ink">Черга додавання</h2>
          <span className="tnum text-[11px] text-ink-faint">{jobs.length}</span>
        </div>

        <div className="px-3 pb-3">
          <div
            className={clsx(
              "grid place-items-center rounded-md border border-dashed py-6 text-center transition-colors",
              dragging ? "border-accent bg-surface-2" : "border-line-2",
            )}
          >
            <span className="text-[12px] text-ink-dim">Перетягніть файли у вікно</span>
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              className="mt-2 rounded border border-line bg-surface px-2.5 py-1 text-[12px] text-ink hover:bg-surface-2"
            >
              Вибрати файли…
            </button>
            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              onChange={(e) => e.target.files && upload(e.target.files)}
            />
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
          {jobs.map((job) => (
            <button
              key={job.id}
              type="button"
              onClick={() => job.item_id && setSelected(job.item_id)}
              className={clsx(
                "mb-1 flex w-full items-center gap-2 rounded px-2 py-1.5 text-left transition-colors",
                selected === job.item_id ? "bg-surface-3" : "hover:bg-surface-2",
              )}
            >
              <span className="tnum rounded-sm bg-surface-3 px-1 py-[1px] text-[9px] text-ink-faint">
                {KIND_LABEL[job.kind] ?? "—"}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[12px] text-ink">
                  {job.source_name}
                </span>
                <span
                  className={clsx(
                    "block truncate text-[11px]",
                    job.status === "failed" ? "text-error" : "text-ink-faint",
                  )}
                >
                  {job.status === "running"
                    ? `${Math.round(job.progress * 100)}% · ${job.stage}`
                    : job.status === "failed"
                      ? "помилка"
                      : "у черзі"}
                </span>
              </span>
            </button>
          ))}
        </div>
      </aside>

      <section className="min-w-0 flex-1 overflow-y-auto">
        <div className="flex gap-1 border-b border-line px-4 py-2">
          {(["file", "text"] as const).map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => setMode(id)}
              className={clsx(
                "rounded px-2.5 py-1 text-[12px] transition-colors",
                mode === id ? "bg-surface-3 text-ink" : "text-ink-dim hover:text-ink",
              )}
            >
              {id === "file" ? "Файл" : "Вставити текст"}
            </button>
          ))}
        </div>

        {mode === "text" ? (
          <div className="space-y-3 p-4">
            <SectionLabel>Текст</SectionLabel>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={14}
              placeholder="Вставте або напишіть нотатку…"
              className="selectable w-full resize-y rounded border border-line bg-surface p-3 text-[13px] leading-[1.6] text-ink placeholder:text-ink-faint focus:border-line-2 focus:outline-none"
            />
            <div className="flex items-center gap-3">
              <button
                type="button"
                disabled={busy || !text.trim()}
                onClick={saveText}
                className="rounded bg-accent px-3 py-1.5 text-[12px] font-medium text-ground disabled:opacity-40"
              >
                Зберегти запис
              </button>
              <span className="text-[11px] text-ink-faint">
                лейбл підставиться з перших слів
              </span>
            </div>
          </div>
        ) : !detail ? (
          <div className="flex h-[70%] items-center justify-center px-8 text-center">
            <p className="max-w-[420px] text-[13px] leading-[1.6] text-ink-dim">
              Перетягніть файли у вікно або виберіть їх. Після додавання тут
              зʼявиться форма запису: лейбл, теги й транскрибція.
            </p>
          </div>
        ) : (
          <div className="space-y-5 p-4">
            <div className="tnum text-[11px] text-ink-faint">
              {KIND_LABEL[detail.kind]}
              {detail.duration_s ? ` · ${formatTime(detail.duration_s)}` : ""}
              {detail.transcript_lang ? ` · ${detail.transcript_lang}` : ""}
              {" · "}
              {detail.status}
            </div>

            <div className="space-y-1.5">
              <SectionLabel>Лейбл</SectionLabel>
              <input
                value={detail.label}
                onChange={(e) => setDetail({ ...detail, label: e.target.value })}
                onBlur={() => patch({ label: detail.label })}
                className="selectable w-full max-w-[520px] rounded border border-line bg-surface px-2.5 py-1.5 text-[14px] text-ink focus:border-line-2 focus:outline-none"
              />
              <p className="text-[11px] text-ink-faint">
                автопідстановка: ім'я файлу без розширення
              </p>
            </div>

            <div className="space-y-1.5">
              <SectionLabel>Теги</SectionLabel>
              <div className="flex flex-wrap gap-1">
                {tags.length === 0 ? (
                  <span className="text-[11px] text-ink-faint">
                    словник порожній — наповніть його на вкладці «Теги»
                  </span>
                ) : (
                  tags.map((tag) => {
                    const active = detail.tags.includes(tag.name);
                    return (
                      <button
                        key={tag.id}
                        type="button"
                        onClick={() =>
                          patch({
                            tags: active
                              ? detail.tags.filter((t) => t !== tag.name)
                              : [...detail.tags, tag.name],
                          })
                        }
                        className={clsx(
                          "rounded-sm px-1.5 py-[2px] text-[11px] transition-colors",
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
              <p className="text-[11px] text-ink-faint">
                лише зі словника · довільні теги не створюються
              </p>
            </div>

            {(detail.kind === "audio" || detail.kind === "video") && (
              <div className="space-y-1.5">
                <SectionLabel>Транскрибція</SectionLabel>
                {detail.transcript === null ? (
                  <div className="ml-pulse rounded border border-line bg-surface p-3 text-[12px] text-ink-dim">
                    ще розпізнається…
                  </div>
                ) : (
                  <>
                    <textarea
                      value={detail.transcript}
                      onChange={(e) => setDetail({ ...detail, transcript: e.target.value })}
                      onBlur={() => patch({ transcript: detail.transcript })}
                      rows={8}
                      className="selectable w-full resize-y rounded border border-line bg-surface p-3 text-[13px] leading-[1.6] text-ink focus:border-line-2 focus:outline-none"
                    />
                    <p className="text-[11px] text-ink-faint">
                      текст машинний — правки зберігаються й одразу перебудовують пошук
                    </p>
                  </>
                )}
              </div>
            )}

            {detail.frames.length > 0 && (
              <div className="space-y-1.5">
                <SectionLabel>Кадри</SectionLabel>
                <div className="flex flex-wrap gap-1.5">
                  {detail.frames.map((frame) => (
                    <div key={frame.id} className="w-[104px]">
                      <img
                        src={frame.url}
                        alt=""
                        className="aspect-4/3 w-full rounded border border-line object-cover"
                      />
                      <div className="tnum mt-0.5 text-center text-[10px] text-ink-faint">
                        {formatTime(frame.ts_s)}
                      </div>
                    </div>
                  ))}
                </div>
                <p className="text-[11px] text-ink-faint">
                  відібрано по зміні сцени · оригінал скопійовано в теку бібліотеки
                </p>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
