import { useCallback, useEffect, useState } from "react";

import { api } from "../api";
import type { BackupList } from "../types";
import { formatBytes } from "./AppShell";

const REASONS: Record<string, string> = {
  manual: "вручну",
  startup: "при запуску",
};

function describe(reason: string): string {
  if (reason.startsWith("before-migration")) {
    return `перед оновленням схеми (${reason.split("-").pop()})`;
  }
  return REASONS[reason] ?? reason;
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="font-mono text-[10px] font-semibold tracking-[0.14em] text-ink-faint uppercase">
      {children}
    </div>
  );
}

export function BackupsPanel({ dataDir }: { dataDir: string | null }) {
  const [state, setState] = useState<BackupList | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  const load = useCallback(() => {
    api.backups().then(setState).catch((e) => setError((e as Error).message));
  }, []);

  useEffect(load, [load]);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!state) {
    return (
      <div className="space-y-2">
        <SectionLabel>Резервні копії</SectionLabel>
        <p className="text-[12px] text-ink-faint">{error ?? "…"}</p>
      </div>
    );
  }

  const originalsPath = dataDir ? `${dataDir}\\originals` : "originals";

  return (
    <div className="space-y-2">
      <SectionLabel>Резервні копії</SectionLabel>
      <p className="text-[11px] leading-[1.6] text-ink-faint">
        Копіюється база: теги, лейбли, виправлені транскрипції та індекс пошуку —
        усе, чого немає в самих файлах. Знімається при запуску раз на добу й
        обов'язково перед оновленням схеми. Зберігається останніх {state.keep}.
      </p>

      {state.pending_restore && (
        <div className="rounded border border-accent bg-surface-2 p-3">
          <p className="text-[12px] leading-[1.6] text-ink">
            Базу буде відновлено з{" "}
            <span className="tnum">{state.pending_restore}</span> при наступному
            запуску. Поточна збережеться поруч — відкотитися буде до чого.
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={() => run(api.cancelRestore)}
            className="mt-2 rounded border border-line bg-surface px-2.5 py-1 text-[12px] text-ink-dim hover:text-ink"
          >
            Скасувати відновлення
          </button>
        </div>
      )}

      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => run(api.createBackup)}
          className="rounded border border-line bg-surface px-3 py-1.5 text-[12px] text-ink hover:border-line-2 hover:bg-surface-2 disabled:opacity-40"
        >
          Зробити копію зараз
        </button>
        {error && <span className="text-[11px] text-error">{error}</span>}
      </div>

      {state.backups.length === 0 ? (
        <p className="text-[11px] text-ink-faint">копій ще немає</p>
      ) : (
        <table className="w-full border-collapse">
          <tbody>
            {state.backups.map((item) => (
              <tr key={item.name} className="border-t border-line">
                <td className="tnum py-1.5 pr-2 text-[12px] text-ink">
                  {new Date(item.created_at).toLocaleString("uk-UA")}
                </td>
                <td className="py-1.5 pr-2 text-[11px] text-ink-faint">
                  {describe(item.reason)}
                </td>
                <td className="tnum py-1.5 pr-2 text-right text-[11px] text-ink-dim">
                  {formatBytes(item.size_bytes)}
                </td>
                <td className="py-1.5 text-right text-[12px] whitespace-nowrap">
                  {confirming === item.name ? (
                    <>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          run(async () => {
                            await api.restoreBackup(item.name);
                            setConfirming(null);
                          })
                        }
                        className="text-accent hover:underline"
                      >
                        Підтвердити
                      </button>
                      <span className="mx-1.5 text-ink-faint">·</span>
                      <button
                        type="button"
                        onClick={() => setConfirming(null)}
                        className="text-ink-dim hover:text-ink"
                      >
                        Ні
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => setConfirming(item.name)}
                        className="text-ink-dim hover:text-ink"
                      >
                        Відновити
                      </button>
                      <span className="mx-1.5 text-ink-faint">·</span>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => run(() => api.deleteBackup(item.name))}
                        className="text-ink-dim hover:text-error"
                      >
                        Видалити
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Найчастіша хибна думка про резервні копії — що вони рятують усе.
          Краще сказати прямо, чого в них немає. */}
      <p className="text-[11px] leading-[1.6] text-ink-faint">
        <span className="text-ink-dim">Оригінали медіа сюди не входять.</span> Вони
        можуть важити сотні гігабайтів, тож копіювати їх щодня було б безглуздо.
        Якщо вихідних файлів у вас більше немає, скопіюйте теку{" "}
        <span className="tnum selectable">{originalsPath}</span> окремо, куди вам
        зручно.
      </p>
    </div>
  );
}
