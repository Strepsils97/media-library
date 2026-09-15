import clsx from "clsx";
import { useEffect, useState } from "react";

import { api } from "../api";
import { formatBytes } from "../components/AppShell";
import { BackupsPanel } from "../components/BackupsPanel";
import type { LibraryStats, RuntimeStatus, UserSettings } from "../types";

/** Цифри — з реального заміру на цій машині (Фаза 0: 36 файлів, 596 с аудіо). */
const ASR_NOTES: Record<string, { size: string; speed: string; note: string; weak?: boolean }> = {
  tiny: { size: "75 МБ", speed: "найшвидше", note: "для цього контенту надто грубо", weak: true },
  base: { size: "142 МБ", speed: "дуже швидко", note: "помітно більше помилок", weak: true },
  small: {
    size: "466 МБ",
    speed: "RTF 0.32 на процесорі",
    note: "замало: розпізнало 3-4 запити з 13",
    weak: true,
  },
  medium: { size: "1,5 ГБ", speed: "не заміряно", note: "проміжний варіант" },
  "large-v3-turbo": {
    size: "1,6 ГБ",
    speed: "RTF 0.06 на відеокарті · година аудіо ≈ 3,7 хв",
    note: "обрано за заміром: ~9 запитів із 13",
  },
};

const DEVICE_LABELS: Record<string, { title: string; note: string }> = {
  auto: { title: "Автоматично", note: "відеокарта, якщо доступна" },
  cuda: { title: "Відеокарта", note: "швидше приблизно вп'ятеро" },
  cpu: { title: "Процесор", note: "повільніше, але без вимог до драйвера" },
};

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
  onSettings: (settings: UserSettings) => void;
}

export function SettingsScreen({ stats, runtime, onSettings }: Props) {
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmReindex, setConfirmReindex] = useState(false);

  useEffect(() => {
    api.settings().then(setSettings).catch((e) => setError((e as Error).message));
  }, []);

  const apply = async (patch: Partial<UserSettings>) => {
    setError(null);
    try {
      const updated = await api.saveSettings(patch);
      setSettings(updated);
      onSettings(updated);
      setStatus("збережено");
      window.setTimeout(() => setStatus(null), 2000);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const reindex = async () => {
    setConfirmReindex(false);
    try {
      const { queued } = await api.reindex();
      setStatus(`у черзі на переобробку: ${queued}`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!settings) {
    return (
      <div className="flex h-full items-center justify-center">
        <span className="ml-pulse text-[12px] text-ink-faint">
          {error ?? "завантаження…"}
        </span>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-[760px] space-y-7 p-5">
        <div className="flex h-5 items-center gap-3">
          {status && <span className="text-[11px] text-accent">{status}</span>}
          {error && <span className="text-[11px] text-error">{error}</span>}
        </div>

        <div className="space-y-2">
          <SectionLabel>Розпізнавання мовлення</SectionLabel>
          <p className="text-[11px] text-ink-faint">
            компроміс швидкість / якість · заміри на цій машині
          </p>
          <div className="space-y-1.5">
            {settings.available.asr_models.map((id) => {
              const info = ASR_NOTES[id] ?? { size: "—", speed: "—", note: "" };
              const active = settings.asr_model === id;
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => apply({ asr_model: id })}
                  className={clsx(
                    "flex w-full items-center gap-3 rounded border px-3 py-2.5 text-left transition-colors",
                    active
                      ? "border-accent bg-surface-2"
                      : "border-line bg-surface hover:border-line-2",
                  )}
                >
                  <span className="w-[130px] shrink-0 text-[13px] text-ink">{id}</span>
                  <span className="tnum w-[70px] shrink-0 text-[11px] text-ink-dim">
                    {info.size}
                  </span>
                  <span className="tnum w-[210px] shrink-0 text-[11px] text-ink-dim">
                    {info.speed}
                  </span>
                  <span
                    className={clsx(
                      "min-w-0 flex-1 truncate text-[11px]",
                      info.weak ? "text-error" : "text-ink-faint",
                    )}
                  >
                    {info.note}
                  </span>
                  {active && (
                    <span className="font-mono shrink-0 text-[9px] tracking-[0.14em] text-accent uppercase">
                      обрано
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          <p className="text-[11px] text-ink-faint">
            нова модель діє на записи, додані після зміни · щоб звести стару
            бібліотеку до неї, запустіть переіндексацію нижче
          </p>
        </div>

        <div className="space-y-2">
          <SectionLabel>Пристрій обчислень</SectionLabel>
          <div className="flex gap-1.5">
            {settings.available.devices.map((id) => {
              const info = DEVICE_LABELS[id] ?? { title: id, note: "" };
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => apply({ device: id as UserSettings["device"] })}
                  className={clsx(
                    "flex-1 rounded border px-3 py-2.5 text-left transition-colors",
                    settings.device === id
                      ? "border-accent bg-surface-2"
                      : "border-line bg-surface hover:border-line-2",
                  )}
                >
                  <div className="text-[13px] text-ink">{info.title}</div>
                  <div className="mt-0.5 text-[11px] text-ink-faint">{info.note}</div>
                </button>
              );
            })}
          </div>
          {runtime && (
            <p className="tnum text-[11px] text-ink-faint">
              зараз використовується:{" "}
              {runtime.device === "cuda" ? "відеокарта" : "процесор"} · моделі
              перезавантажуються при зміні
            </p>
          )}
        </div>

        <div className="space-y-2">
          <SectionLabel>Вигляд</SectionLabel>
          <div className="flex gap-1.5">
            {(
              [
                ["dark", "Темна", "основна: не сперечається з медіа"],
                ["light", "Світла", "другорядна"],
              ] as const
            ).map(([id, title, note]) => (
              <button
                key={id}
                type="button"
                onClick={() => apply({ theme: id })}
                className={clsx(
                  "flex-1 rounded border px-3 py-2.5 text-left transition-colors",
                  settings.theme === id
                    ? "border-accent bg-surface-2"
                    : "border-line bg-surface hover:border-line-2",
                )}
              >
                <div className="text-[13px] text-ink">{title}</div>
                <div className="mt-0.5 text-[11px] text-ink-faint">{note}</div>
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-2">
          <SectionLabel>Обробка й видача</SectionLabel>
          <div className="flex gap-4">
            {(
              [
                ["max_frames_per_video", "Кадрів на відео", 1, 40,
                 "більше кадрів — точніший пошук по картинці, більше місця"],
                ["snippet_words", "Слів в уривку", 5, 80,
                 "довжина тексту в картці результату"],
              ] as const
            ).map(([field, title, min, max, note]) => (
              <label key={field} className="flex-1">
                <div className="text-[12px] text-ink">{title}</div>
                <input
                  type="number"
                  min={min}
                  max={max}
                  value={settings[field]}
                  onChange={(e) => {
                    const value = Number(e.target.value);
                    if (value >= min && value <= max) apply({ [field]: value });
                  }}
                  className="tnum mt-1 w-full rounded border border-line bg-surface px-2 py-1 text-[12px] text-ink focus:border-line-2 focus:outline-none"
                />
                <div className="mt-0.5 text-[11px] text-ink-faint">{note}</div>
              </label>
            ))}
          </div>
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
          <SectionLabel>Куди зберігати файли</SectionLabel>
          <div className="flex gap-2">
            <div className="selectable tnum min-w-0 flex-1 truncate rounded border border-line bg-surface px-3 py-2 text-[12px] text-ink">
              {settings.download_dir_effective}
            </div>
            <button
              type="button"
              onClick={async () => {
                const { path } = await api.pickFolder();
                if (path) apply({ download_dir: path });
              }}
              className="shrink-0 rounded border border-line bg-surface px-3 py-2 text-[12px] text-ink hover:border-line-2 hover:bg-surface-2"
            >
              Обрати…
            </button>
            {settings.download_dir && (
              <button
                type="button"
                onClick={() => apply({ download_dir: "" })}
                className="shrink-0 rounded border border-line bg-surface px-3 py-2 text-[12px] text-ink-dim hover:text-ink"
              >
                Скинути
              </button>
            )}
          </div>
          <p className="text-[11px] text-ink-faint">
            сюди потрапляють записи, збережені кнопкою «Завантажити»
            {!settings.download_dir && " · зараз це стандартна тека завантажень"}
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
                {(
                  [
                    ["оригінали", stats.originals_bytes],
                    ["кадри", stats.frames_bytes],
                    ["моделі", stats.models_bytes],
                    ["база", stats.db_bytes],
                  ] as const
                ).map(([label, value]) => (
                  <div key={label}>
                    <div className="tnum text-[13px] text-ink">{formatBytes(value)}</div>
                    <div className="text-[11px] text-ink-faint">{label}</div>
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

        <div className="border-t border-line pt-5">
          <BackupsPanel dataDir={stats?.data_dir ?? null} />
        </div>

        <div className="space-y-2 border-t border-line pt-5">
          <SectionLabel>Переіндексація</SectionLabel>
          {confirmReindex ? (
            <div className="rounded border border-line bg-surface p-3">
              <p className="text-[12px] leading-[1.6] text-ink-dim">
                Усі {stats?.item_count ?? 0} записів буде оброблено заново:
                розпізнавання мовлення, кадри, ембедінги. Файли й теги не
                постраждають, але на відеокарті це займе помітний час, і доти
                бібліотека шукатиметься частково.
              </p>
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  onClick={reindex}
                  className="rounded bg-accent px-3 py-1.5 text-[12px] font-medium text-ground"
                >
                  Запустити
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmReindex(false)}
                  className="rounded border border-line bg-surface-2 px-3 py-1.5 text-[12px] text-ink-dim hover:text-ink"
                >
                  Скасувати
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmReindex(true)}
              disabled={!stats?.item_count}
              className="rounded border border-line bg-surface px-3 py-1.5 text-[12px] text-ink hover:border-line-2 hover:bg-surface-2 disabled:opacity-40"
            >
              Переіндексувати бібліотеку
            </button>
          )}
          <p className="text-[11px] text-ink-faint">
            потрібно після зміни моделі розпізнавання
          </p>
        </div>

        <div className="tnum border-t border-line pt-4 text-[11px] text-ink-faint">
          media-library {settings.app_version} · схема бази{" "}
          {settings.schema_version}
          <br />
          оновлення: замініть файли застосунку, теку «data» лишіть на місці —
          база доведеться до нової версії сама
        </div>
      </div>
    </div>
  );
}
