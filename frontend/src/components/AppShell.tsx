import clsx from "clsx";
import type { ReactNode } from "react";

import type { LibraryStats, RuntimeStatus } from "../types";
import { Mark } from "./Mark";

export type Screen = "search" | "add" | "queue" | "tags" | "convert" | "settings";

const TABS: { id: Screen; label: string }[] = [
  { id: "search", label: "Пошук" },
  { id: "add", label: "Додати" },
  { id: "queue", label: "Черга" },
  { id: "tags", label: "Теги" },
  { id: "convert", label: "Конвертація" },
  { id: "settings", label: "Налаштування" },
];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  const units = ["КБ", "МБ", "ГБ", "ТБ"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 || unit === 0 ? 0 : 1).replace(".", ",")} ${units[unit]}`;
}

function formatCount(n: number): string {
  return n.toLocaleString("uk-UA").replace(/ /g, " ");
}

interface Props {
  screen: Screen;
  onScreen: (screen: Screen) => void;
  stats: LibraryStats | null;
  runtime: RuntimeStatus | null;
  children: ReactNode;
}

export function AppShell({ screen, onScreen, stats, runtime, children }: Props) {
  const queued = runtime ? runtime.jobs_running + runtime.jobs_queued : 0;

  return (
    <div className="flex h-full flex-col bg-ground">
      <header className="flex shrink-0 items-center gap-1 border-b border-line bg-canvas px-3">
        <div className="mr-3 flex items-center gap-2 py-2.5">
          <Mark size={21} className="text-accent" />
          <span className="text-[13px] font-semibold tracking-tight text-ink">
            media-library
          </span>
        </div>

        <nav className="flex items-center gap-0.5">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => onScreen(tab.id)}
              className={clsx(
                "relative rounded px-2.5 py-1.5 text-[13px] transition-colors",
                screen === tab.id
                  ? "bg-surface-3 text-ink"
                  : "text-ink-dim hover:bg-surface-2 hover:text-ink",
              )}
            >
              {tab.label}
              {tab.id === "queue" && queued > 0 && (
                <span className="tnum ml-1.5 rounded-sm bg-accent px-1 text-[10px] font-semibold text-ground">
                  {queued}
                </span>
              )}
            </button>
          ))}
        </nav>

        <div className="tnum ml-auto flex items-center gap-3 text-[11px] text-ink-faint">
          {stats && <span>{formatCount(stats.item_count)} записів</span>}
          {runtime && runtime.jobs_running > 0 && (
            <span className="text-ink-dim">{runtime.jobs_running} в обробці</span>
          )}
          <kbd className="rounded border border-line bg-surface px-1.5 py-0.5 text-[10px] text-ink-faint">
            ⌘K
          </kbd>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-hidden">{children}</main>

      <footer className="tnum flex shrink-0 items-center gap-3 border-t border-line bg-canvas px-3 py-1.5 text-[11px] text-ink-faint">
        {stats ? (
          <span className="truncate">
            {stats.data_dir} · {formatCount(stats.item_count)} записів ·{" "}
            {formatBytes(stats.originals_bytes)}
          </span>
        ) : (
          <span>бібліотека завантажується…</span>
        )}

        <span className="ml-auto flex items-center gap-3">
          {runtime && runtime.jobs_running > 0 && (
            <span className="text-ink-dim">
              Обробка: {runtime.jobs_running}{" "}
              {runtime.jobs_running === 1 ? "задача" : "задачі"} ·{" "}
              {Math.round(runtime.progress * 100)}%
            </span>
          )}
          {runtime && runtime.jobs_failed > 0 && (
            <span className="text-error">
              {runtime.jobs_failed}{" "}
              {runtime.jobs_failed === 1 ? "помилка" : "помилки"}
            </span>
          )}
          {runtime && (
            <span>
              {runtime.device === "cuda" ? "GPU" : "CPU"} · {runtime.asr_model}
              {queued === 0 && " · черга порожня"}
            </span>
          )}
        </span>
      </footer>
    </div>
  );
}

export { formatBytes, formatCount };
