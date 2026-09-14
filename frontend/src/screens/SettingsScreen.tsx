import clsx from "clsx";
import { useEffect, useState } from "react";

import { formatBytes } from "../components/AppShell";
import type { LibraryStats, RuntimeStatus } from "../types";

/** Цифри — з реального заміру на цій машині (Фаза 0, 36 файлів, 596 с аудіо). */
const ASR_MODELS = [
  {
    id: "small",
    size: "466 МБ",
    speed: "RTF 0.32 на CPU",
    note: "для цього контенту замало: розпізнало 3-4 запити з 13",
    weak: true,
  },
  {
    id: "medium",
    size: "1,5 ГБ",
    speed: "не заміряно",
    note: "проміжний варіант",
    weak: false,
  },
  {
    id: "large-v3-turbo",
    size: "1,6 ГБ",
    speed: "RTF 0.06 на GPU · година аудіо ≈ 3,7 хв",
    note: "обрано за результатом заміру: ~9 запитів із 13",
    weak: false,
  },
];

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="font-mono text-[10px] font-semibold tracking-[0.14em] text-ink-faint uppercase">
      {children}
    </div>
  );
}

interface Props {
  stats: LibraryStats | null;
  runtime: RuntimeStatus | null;
}

export function SettingsScreen({ stats, runtime }: Props) {
  const [model, setModel] = useState("large-v3-turbo");
  const [device, setDevice] = useState<"auto" | "cuda" | "cpu">("auto");

  useEffect(() => {
    if (runtime) setModel(runtime.asr_model);
  }, [runtime]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-[760px] space-y-7 p-5">
        <div className="space-y-2">
          <SectionLabel>Розпізнавання мовлення</SectionLabel>
          <p className="text-[11px] text-ink-faint">
            компроміс швидкість / якість · заміри на цій машині
          </p>
          <div className="space-y-1.5">
            {ASR_MODELS.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setModel(item.id)}
                className={clsx(
                  "flex w-full items-center gap-3 rounded border px-3 py-2.5 text-left transition-colors",
                  model === item.id
                    ? "border-accent bg-surface-2"
                    : "border-line bg-surface hover:border-line-2",
                )}
              >
                <span className="w-[130px] shrink-0 text-[13px] text-ink">{item.id}</span>
                <span className="tnum w-[70px] shrink-0 text-[11px] text-ink-dim">
                  {item.size}
                </span>
                <span className="tnum w-[190px] shrink-0 text-[11px] text-ink-dim">
                  {item.speed}
                </span>
                <span
                  className={clsx(
                    "min-w-0 flex-1 truncate text-[11px]",
                    item.weak ? "text-error" : "text-ink-faint",
                  )}
                >
                  {item.note}
                </span>
                {model === item.id && (
                  <span className="font-mono shrink-0 text-[9px] tracking-[0.14em] text-accent uppercase">
                    обрано
                  </span>
                )}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-ink-faint">
            зміна моделі вимагає переіндексації вже доданих записів
          </p>
        </div>

        <div className="space-y-2">
          <SectionLabel>Пристрій обчислень</SectionLabel>
          <div className="flex gap-1.5">
            {(
              [
                ["auto", "Автоматично", "обирає відеокарту, якщо доступна"],
                ["cuda", "Відеокарта", "швидше приблизно вп'ятеро"],
                ["cpu", "Процесор", "повільніше, але без вимог до драйвера"],
              ] as const
            ).map(([id, title, note]) => (
              <button
                key={id}
                type="button"
                onClick={() => setDevice(id)}
                className={clsx(
                  "flex-1 rounded border px-3 py-2.5 text-left transition-colors",
                  device === id
                    ? "border-accent bg-surface-2"
                    : "border-line bg-surface hover:border-line-2",
                )}
              >
                <div className="text-[13px] text-ink">{title}</div>
                <div className="mt-0.5 text-[11px] text-ink-faint">{note}</div>
              </button>
            ))}
          </div>
          {runtime && (
            <p className="tnum text-[11px] text-ink-faint">
              зараз використовується: {runtime.device === "cuda" ? "відеокарта" : "процесор"}
            </p>
          )}
        </div>

        <div className="space-y-2">
          <SectionLabel>Мови розпізнавання</SectionLabel>
          <div className="flex gap-1.5">
            {["українська", "російська", "німецька"].map((lang) => (
              <span
                key={lang}
                className="rounded-sm bg-surface-3 px-2 py-1 text-[12px] text-ink-dim"
              >
                {lang}
              </span>
            ))}
          </div>
          <p className="text-[11px] text-ink-faint">
            список фіксований: без нього визначення мови зривається на польську,
            іспанську чи грецьку — перевірено заміром
          </p>
        </div>

        <div className="space-y-2">
          <SectionLabel>Тека бібліотеки</SectionLabel>
          <div className="selectable tnum rounded border border-line bg-surface px-3 py-2 text-[12px] text-ink">
            {stats?.data_dir ?? "…"}
          </div>
          <p className="text-[11px] text-ink-faint">
            оригінали копіюються сюди · переміщення вихідних файлів бібліотеку не ламає
          </p>
        </div>

        <div className="space-y-2">
          <SectionLabel>Місце на диску</SectionLabel>
          {stats ? (
            <>
              <div className="flex gap-4">
                {[
                  ["оригінали", stats.originals_bytes],
                  ["кадри", stats.frames_bytes],
                  ["моделі", stats.models_bytes],
                  ["база", stats.db_bytes],
                ].map(([label, value]) => (
                  <div key={label as string}>
                    <div className="tnum text-[13px] text-ink">
                      {formatBytes(value as number)}
                    </div>
                    <div className="text-[11px] text-ink-faint">{label as string}</div>
                  </div>
                ))}
              </div>
              <p className="tnum text-[11px] text-ink-faint">
                вільно {formatBytes(stats.disk_free_bytes)} з{" "}
                {formatBytes(stats.disk_total_bytes)}
              </p>
            </>
          ) : (
            <p className="text-[12px] text-ink-faint">…</p>
          )}
        </div>
      </div>
    </div>
  );
}
