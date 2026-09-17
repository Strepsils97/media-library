import clsx from "clsx";
import { useEffect, useState } from "react";

import { api } from "../api";
import type { ConvertResult } from "../types";

/** По скільки файлів за раз. Пачками — щоб було видно поступ і щоб один
 *  збій не забирав із собою всю сотню. */
const BATCH = 8;

interface Formats {
  formats: { id: string; suffix: string; lossy: boolean }[];
  bitrates: string[];
  default_bitrate: string;
  target_dir: string;
}

function basename(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

export function ConvertScreen() {
  const [meta, setMeta] = useState<Formats | null>(null);
  const [format, setFormat] = useState("mp3");
  const [bitrate, setBitrate] = useState("192k");
  const [queue, setQueue] = useState<string[]>([]);
  const [results, setResults] = useState<ConvertResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    api
      .convertFormats()
      .then((m) => {
        setMeta(m);
        setBitrate(m.default_bitrate);
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  const lossy = meta?.formats.find((f) => f.id === format)?.lossy ?? true;

  const pick = async () => {
    setError(null);
    try {
      const { paths } = await api.pickFiles();
      if (paths.length === 0) return;
      setQueue((current) => [...new Set([...current, ...paths])]);
      setResults([]);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  /** Перетягнуті файли доводиться відправляти вмістом: шляху до них у
   *  вікна немає. Обрані через діалог ідуть шляхами й нікуди не копіюються. */
  const dropped = async (files: FileList) => {
    const list = [...files];
    if (list.length === 0) return;
    setBusy(true);
    setError(null);
    setResults([]);

    const done: ConvertResult[] = [];
    for (let start = 0; start < list.length; start += BATCH) {
      const chunk = list.slice(start, start + BATCH);
      setProgress(`${start} з ${list.length}`);
      const form = new FormData();
      chunk.forEach((file) => form.append("files", file));
      form.append("format", format);
      form.append("bitrate", bitrate);
      try {
        const response = await fetch("/api/convert/upload", { method: "POST", body: form });
        if (!response.ok) throw new Error((await response.text()).slice(0, 200));
        const payload = (await response.json()) as { results: ConvertResult[] };
        done.push(...payload.results);
      } catch (e) {
        done.push(
          ...chunk.map((file) => ({
            source: file.name,
            path: null,
            name: null,
            error: (e as Error).message,
          })),
        );
      }
      setResults([...done]);
    }
    setProgress(null);
    setBusy(false);
  };

  const run = async () => {
    if (queue.length === 0) return;
    setBusy(true);
    setError(null);
    const done: ConvertResult[] = [];
    for (let start = 0; start < queue.length; start += BATCH) {
      setProgress(`${start} з ${queue.length}`);
      try {
        const { results: batch } = await api.convert(
          queue.slice(start, start + BATCH),
          format,
          bitrate,
        );
        done.push(...batch);
      } catch (e) {
        setError((e as Error).message);
        break;
      }
      setResults([...done]);
    }
    setProgress(null);
    setBusy(false);
    setQueue([]);
  };

  const failed = results.filter((r) => r.error);
  const ready = results.filter((r) => !r.error);

  return (
    <div
      className="flex h-full min-h-0 flex-col"
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        void dropped(e.dataTransfer.files);
      }}
    >
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
        <span className="font-mono text-[10px] font-semibold tracking-[0.14em] text-ink-faint uppercase">
          Формат
        </span>
        {meta?.formats.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setFormat(f.id)}
            className={clsx(
              "rounded px-2.5 py-1 text-[12px] transition-colors",
              format === f.id ? "bg-accent text-ground" : "text-ink-dim hover:text-ink",
            )}
          >
            {f.id}
          </button>
        ))}

        {lossy && (
          <>
            <span className="ml-3 font-mono text-[10px] font-semibold tracking-[0.14em] text-ink-faint uppercase">
              Якість
            </span>
            {meta?.bitrates.map((b) => (
              <button
                key={b}
                type="button"
                onClick={() => setBitrate(b)}
                className={clsx(
                  "tnum rounded px-2 py-1 text-[12px] transition-colors",
                  bitrate === b ? "bg-surface-3 text-ink" : "text-ink-dim hover:text-ink",
                )}
              >
                {b}
              </button>
            ))}
          </>
        )}

        {error && (
          <span className="ml-auto truncate text-[11px] text-error">{error}</span>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div
          className={clsx(
            "grid place-items-center rounded-md border border-dashed py-10 text-center transition-colors",
            dragging ? "border-accent bg-surface-2" : "border-line-2",
          )}
        >
          <p className="text-[13px] text-ink-dim">
            {busy
              ? `переганяємо… ${progress ?? ""}`
              : "Перетягніть файли сюди — або виберіть їх"}
          </p>
          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={pick}
              className="rounded border border-line bg-surface px-3 py-1.5 text-[12px] text-ink hover:bg-surface-2 disabled:opacity-40"
            >
              Вибрати файли…
            </button>
            {queue.length > 0 && (
              <button
                type="button"
                disabled={busy}
                onClick={run}
                className="rounded bg-accent px-3 py-1.5 text-[12px] font-medium text-ground disabled:opacity-40"
              >
                Перегнати {queue.length} у {format}
              </button>
            )}
          </div>
          {meta && (
            <p className="mt-3 text-[11px] text-ink-faint">
              готове лягає в {meta.target_dir} · теку змінюють у налаштуваннях
            </p>
          )}
        </div>

        {queue.length > 0 && !busy && (
          <div className="mt-4">
            <div className="font-mono text-[10px] font-semibold tracking-[0.14em] text-ink-faint uppercase">
              Обрано {queue.length}
            </div>
            <div className="mt-1.5 space-y-0.5">
              {queue.slice(0, 40).map((path) => (
                <div key={path} className="truncate text-[12px] text-ink-dim">
                  {basename(path)}
                </div>
              ))}
              {queue.length > 40 && (
                <div className="text-[11px] text-ink-faint">
                  …і ще {queue.length - 40}
                </div>
              )}
            </div>
          </div>
        )}

        {results.length > 0 && (
          <div className="mt-5">
            <div className="font-mono text-[10px] font-semibold tracking-[0.14em] text-ink-faint uppercase">
              Готово {ready.length}
              {failed.length > 0 && ` · не вийшло ${failed.length}`}
            </div>
            <div className="mt-1.5 space-y-0.5">
              {results.map((r, index) => (
                <div
                  key={`${r.source}-${index}`}
                  className="flex items-baseline gap-2 text-[12px]"
                >
                  <span
                    className={clsx(
                      "min-w-0 flex-1 truncate",
                      r.error ? "text-error" : "text-ink",
                    )}
                  >
                    {r.name ?? basename(r.source)}
                  </span>
                  {r.error && (
                    <span className="shrink-0 text-[11px] text-error">{r.error}</span>
                  )}
                </div>
              ))}
            </div>
            {ready.length > 0 && ready[0].path && (
              <button
                type="button"
                onClick={() => api.reveal(ready[0].path as string).catch(() => undefined)}
                className="mt-3 rounded border border-line bg-surface px-3 py-1.5 text-[12px] text-ink hover:bg-surface-2"
              >
                Показати в теці
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
