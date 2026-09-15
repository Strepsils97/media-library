import clsx from "clsx";
import { Fragment, useEffect, useState } from "react";

import { api } from "../api";
import type { Job, Kind } from "../types";

const KIND_LABEL: Record<Kind, string> = {
  image: "ІМГ",
  video: "ВІД",
  audio: "АУД",
  text: "ТХТ",
};

const STATUS_TEXT: Record<Job["status"], string> = {
  running: "обробляється",
  queued: "у черзі",
  done: "готово",
  failed: "помилка",
};

function Progress({ job }: { job: Job }) {
  if (job.status === "done") {
    return <span className="tnum text-[11px] text-ink-dim">100</span>;
  }
  if (job.status === "queued" || job.status === "failed") {
    return <span className="text-[11px] text-ink-faint">—</span>;
  }
  return (
    <div className="flex items-center gap-2">
      <div className="h-[3px] w-24 overflow-hidden rounded-full bg-surface-3">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-500"
          style={{ width: `${Math.round(job.progress * 100)}%` }}
        />
      </div>
      <span className="tnum text-[11px] text-ink-dim">
        {Math.round(job.progress * 100)}%
      </span>
    </div>
  );
}

export function QueueScreen() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [paused, setPaused] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.jobs().then(setJobs).catch(() => undefined);
    // Пауза — стан воркера, а не компонента: після переходу між екранами
    // перемикач має показувати те, що насправді робить бекенд.
    api.runtime().then((r) => setPaused(r.paused)).catch(() => undefined);
  };

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 1500);
    return () => window.clearInterval(timer);
  }, []);

  const counts = {
    running: jobs.filter((j) => j.status === "running").length,
    queued: jobs.filter((j) => j.status === "queued").length,
    failed: jobs.filter((j) => j.status === "failed").length,
    done: jobs.filter((j) => j.status === "done").length,
  };

  const togglePause = async () => {
    try {
      const { paused: now } = await api.pauseJobs(!paused);
      setPaused(now);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const clearDone = async () => {
    try {
      await api.clearDoneJobs();
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-baseline gap-3 border-b border-line px-4 py-3">
        <h1 className="text-[15px] font-semibold text-ink">Черга обробки</h1>
        <span className="tnum text-[11px] text-ink-faint">
          {counts.running} обробляються · {counts.queued} у черзі · {counts.failed}{" "}
          {counts.failed === 1 ? "помилка" : "помилки"} · {counts.done} готово
          {paused && " · на паузі"}
        </span>
        <div className="ml-auto flex items-center gap-2">
          {error && <span className="text-[11px] text-error">{error}</span>}
          <button
            type="button"
            onClick={togglePause}
            className="rounded border border-line bg-surface px-2.5 py-1 text-[12px] text-ink-dim hover:border-line-2 hover:text-ink"
          >
            {paused ? "Продовжити" : "Пауза"}
          </button>
          <button
            type="button"
            onClick={clearDone}
            disabled={counts.done === 0}
            className="rounded border border-line bg-surface px-2.5 py-1 text-[12px] text-ink-dim hover:border-line-2 hover:text-ink disabled:opacity-40"
          >
            Прибрати готові
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {jobs.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-[13px] text-ink-faint">Черга порожня</p>
          </div>
        ) : (
          <table className="w-full border-collapse">
            <thead className="sticky top-0 bg-canvas">
              <tr className="font-mono text-[10px] tracking-[0.14em] text-ink-faint uppercase">
                <th className="px-4 py-2 text-left font-semibold">Тип</th>
                <th className="px-2 py-2 text-left font-semibold">Запис</th>
                <th className="px-2 py-2 text-left font-semibold">Етап</th>
                <th className="px-2 py-2 text-left font-semibold">Прогрес</th>
                <th className="px-2 py-2 text-left font-semibold">Статус</th>
                <th className="px-4 py-2 text-right font-semibold">Дія</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <Fragment key={job.id}>
                  <tr className="border-t border-line align-middle">
                    <td className="px-4 py-2.5">
                      <span className="tnum rounded-sm bg-surface-3 px-1 py-[1px] text-[9px] tracking-wider text-ink-faint">
                        {KIND_LABEL[job.kind] ?? "—"}
                      </span>
                    </td>
                    <td className="max-w-[260px] px-2 py-2.5">
                      <div className="truncate text-[13px] text-ink">{job.label}</div>
                      <div className="truncate text-[11px] text-ink-faint">
                        {job.source_name}
                      </div>
                    </td>
                    <td className="px-2 py-2.5 text-[12px] text-ink-dim">{job.stage}</td>
                    <td className="px-2 py-2.5">
                      <Progress job={job} />
                    </td>
                    <td
                      className={clsx(
                        "px-2 py-2.5 text-[12px]",
                        job.status === "failed" ? "text-error" : "text-ink-dim",
                      )}
                    >
                      {STATUS_TEXT[job.status]}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      {job.status === "failed" ? (
                        <button
                          type="button"
                          onClick={() => api.retryJob(job.id).then(load)}
                          className="text-[12px] text-accent hover:underline"
                        >
                          Повторити
                        </button>
                      ) : job.status === "done" ? (
                        <span className="text-[12px] text-ink-faint">—</span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => api.cancelJob(job.id).then(load)}
                          className="text-[12px] text-ink-dim hover:text-ink"
                        >
                          {job.status === "running" ? "Скасувати" : "Прибрати"}
                        </button>
                      )}
                    </td>
                  </tr>
                  {job.error && (
                    <tr className="bg-surface">
                      <td />
                      <td colSpan={5} className="px-2 pb-3">
                        {/* Причина завжди явна текстом — ніяких кодів без пояснення. */}
                        <p className="selectable max-w-[640px] text-[12px] leading-[1.55] text-ink-dim">
                          {job.error}
                        </p>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
