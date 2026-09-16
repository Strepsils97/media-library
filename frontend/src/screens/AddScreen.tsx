import clsx from "clsx";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api";
import type { ItemDetail, Job, Kind, Tag } from "../types";

const KIND_LABEL: Record<Kind, string> = {
  image: "ІМГ",
  video: "ВІД",
  audio: "АУД",
  text: "ТХТ",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "у черзі",
  processing: "обробляється",
  ready: "готово",
  failed: "з помилкою",
};

/** Поля, які користувач редагує вручну. Решту можна спокійно перезаписувати
 *  свіжими даними з сервера. */
type EditableField = "label" | "transcript";

/** Запис, доданий у цьому сеансі. Лишається в списку назавжди — доки вікно
 *  відкрите, — навіть коли обробка давно скінчилася. */
interface Added {
  item_id: number;
  name: string;
  kind: string;
}

/** По скільки файлів за раз. Одним запитом на сотню відео браузер спершу
 *  збирає в пам'яті все тіло, а потім будь-яка помилка губить усю пачку —
 *  тому відправляємо частинами. */
const UPLOAD_BATCH = 4;

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
  const [added, setAdded] = useState<Added[]>([]);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [batch, setBatch] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<ItemDetail | null>(null);
  const [tags, setTags] = useState<Tag[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  // Які поля користувач уже правив. Без цього фонове оновлення (воно тягне
  // транскрибцію, щойно та доготується) затирало б набраний текст просто
  // посеред редагування.
  const edited = useRef<Set<EditableField>>(new Set());
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    api.tags().then(setTags).catch(() => undefined);
  }, []);

  useEffect(() => {
    // Готові завдання теж потрібні: саме з них беруться відсотки й статус для
    // списку доданих, а зникати після завершення записи не мають.
    const load = () =>
      api
        .jobs()
        .then((all) => setJobs(Array.isArray(all) ? all.slice(0, 200) : []))
        .catch(() => undefined);
    load();
    const timer = window.setInterval(load, 1500);
    return () => window.clearInterval(timer);
  }, []);

  /** Зливає свіжі дані сервера з тим, що користувач уже встиг наредагувати. */
  const applyFromServer = useCallback((incoming: ItemDetail) => {
    setDetail((current) => {
      if (!current || current.id !== incoming.id) {
        edited.current = new Set();
        setDirty(false);
        return incoming;
      }
      return {
        ...incoming,
        label: edited.current.has("label") ? current.label : incoming.label,
        transcript: edited.current.has("transcript")
          ? current.transcript
          : incoming.transcript,
      };
    });
  }, []);

  useEffect(() => {
    if (selected === null) {
      setDetail(null);
      edited.current = new Set();
      setDirty(false);
      return;
    }

    let stopped = false;
    const load = async () => {
      try {
        const incoming = await api.item(selected);
        if (stopped) return;
        applyFromServer(incoming);
        // Поки запис обробляється, треба чекати на транскрибцію. Щойно він
        // готовий — опитувати нема чого, і будь-який зайвий запит тільки
        // ризикує зіштовхнутися з правками користувача.
        if (incoming.status === "ready" || incoming.status === "failed") {
          window.clearInterval(timer);
        }
      } catch {
        /* мережевий збій — спробуємо на наступному такті */
      }
    };

    const timer = window.setInterval(load, 2000);
    void load();
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [selected, applyFromServer]);

  type Created = {
    filename?: string;
    item_id?: number;
    kind?: string;
    label?: string;
    error?: string;
    duplicate?: boolean;
  };

  /** Відправляє одну пачку. Кидає помилку з причиною, а не з кодом статусу. */
  const sendBatch = async (chunk: File[]): Promise<Created[]> => {
    const form = new FormData();
    chunk.forEach((file) => form.append("files", file));
    const response = await fetch("/api/items/upload", { method: "POST", body: form });

    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(text.slice(0, 300) || `сервер відповів ${response.status}`);
    }
    const payload: unknown = await response.json().catch(() => null);
    // Сервер може віддати й не список — наприклад, {detail: …} при збої.
    // Раніше на цьому весь екран падав із «filter is not a function».
    if (!Array.isArray(payload)) {
      throw new Error("Несподівана відповідь сервера при додаванні");
    }
    return payload as Created[];
  };

  const upload = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (list.length === 0) return;
    setBusy(true);
    setError(null);
    setProgress(list.length > UPLOAD_BATCH ? `0 з ${list.length}` : null);

    const created: Created[] = [];
    const problems: string[] = [];

    for (let start = 0; start < list.length; start += UPLOAD_BATCH) {
      const chunk = list.slice(start, start + UPLOAD_BATCH);
      try {
        created.push(...(await sendBatch(chunk)));
      } catch (e) {
        // Одна невдала пачка не має зупиняти решту: у людини може бути сотня
        // файлів, і починати все спочатку через один збій — знущання.
        problems.push(`${chunk.map((f) => f.name).join(", ")}: ${(e as Error).message}`);
      }
      if (list.length > UPLOAD_BATCH) {
        setProgress(`${Math.min(start + UPLOAD_BATCH, list.length)} з ${list.length}`);
      }
    }

    const fresh = created.filter((c) => c.item_id && !c.duplicate);
    setAdded((current) => [
      ...fresh.map((c) => ({
        item_id: c.item_id as number,
        name: c.label || c.filename || "запис",
        kind: c.kind || "",
      })),
      ...current.filter((a) => !fresh.some((c) => c.item_id === a.item_id)),
    ]);

    const failed = created.filter((c) => c.error).map((c) => `${c.filename}: ${c.error}`);
    const skipped = created.filter((c) => c.duplicate).length;
    const notes = [...problems, ...failed];
    if (skipped) notes.push(`${skipped} уже були в бібліотеці`);
    setError(notes.length ? notes.join("; ") : null);

    if (fresh.length) setSelected(fresh[0].item_id as number);
    setProgress(null);
    setBusy(false);
    onAdded();
  };

  const saveText = async () => {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.createText(text);
      const name = text.trim().split(/\s+/).slice(0, 6).join(" ");
      setAdded((current) => [
        { item_id: created.item_id, name, kind: "text" },
        ...current.filter((a) => a.item_id !== created.item_id),
      ]);
      setText("");
      setSelected(created.item_id);
      if (created.duplicate) setError("Такий текст уже є в бібліотеці.");
      onAdded();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  /** Зберігає всі правки запису одним запитом. */
  const save = async () => {
    if (!detail) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.patchItem(detail.id, {
        label: detail.label,
        tags: detail.tags,
        ...(detail.transcript !== null ? { transcript: detail.transcript } : {}),
      });
      edited.current = new Set();
      setDirty(false);
      setSavedAt(Date.now());
      applyFromServer(updated);
      onAdded();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const editField = (field: EditableField, value: string) => {
    edited.current.add(field);
    setDirty(true);
    setSavedAt(null);
    setDetail((current) => (current ? { ...current, [field]: value } : current));
  };

  /** Рядки списку: додане в цьому сеансі плюс те, що ще обробляється.
   *
   *  Раніше список показував лише незавершені завдання, і запис зникав із
   *  нього рівно тоді, коли ставав придатним для редагування: транскрибція
   *  доготувалася — рядок пропав, і виправити текст уже нічим.
   */
  const rows: Added[] = (() => {
    const seen = new Set(added.map((a) => a.item_id));
    const pending = jobs
      .filter((j) => j.item_id && j.status !== "done" && !seen.has(j.item_id))
      .map((j) => ({ item_id: j.item_id as number, name: j.source_name, kind: j.kind }));
    return [...added, ...pending];
  })();

  const jobByItem = new Map(jobs.filter((j) => j.item_id).map((j) => [j.item_id, j]));

  const toggleChecked = (id: number) =>
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const allChecked = rows.length > 0 && rows.every((r) => checked.has(r.item_id));

  /** Додає теги всім позначеним записам, не чіпаючи вже проставлені. */
  const applyTagsToChecked = async (name: string) => {
    const ids = rows.map((r) => r.item_id).filter((id) => checked.has(id));
    if (ids.length === 0) return;
    setBatch(`${name}: 0 з ${ids.length}`);
    setError(null);
    let done = 0;
    for (const id of ids) {
      try {
        const current = await api.item(id);
        if (!current.tags.includes(name)) {
          await api.patchItem(id, { tags: [...current.tags, name] });
        }
        done += 1;
        setBatch(`${name}: ${done} з ${ids.length}`);
      } catch (e) {
        setError((e as Error).message);
      }
    }
    setBatch(null);
    if (selected !== null && ids.includes(selected)) {
      api.item(selected).then(applyFromServer).catch(() => undefined);
    }
    onAdded();
  };

  const toggleTag = (name: string) => {
    if (!detail) return;
    setDirty(true);
    setSavedAt(null);
    setDetail({
      ...detail,
      tags: detail.tags.includes(name)
        ? detail.tags.filter((t) => t !== name)
        : [...detail.tags, name],
    });
  };

  // Ctrl+S — звична для десктопа комбінація; без неї єдиний спосіб зберегти
  // великий відредагований текст це тягнутися мишею вниз сторінки.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        if (dirty && !saving) void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

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
        void upload(e.dataTransfer.files);
      }}
    >
      <aside className="flex w-[280px] shrink-0 flex-col border-r border-line bg-canvas">
        <div className="flex items-baseline gap-2 px-3 py-3">
          <h2 className="text-[13px] font-semibold text-ink">Додані</h2>
          <span className="tnum text-[11px] text-ink-faint">{rows.length}</span>
          {rows.length > 0 && (
            <button
              type="button"
              onClick={() =>
                setChecked(allChecked ? new Set() : new Set(rows.map((r) => r.item_id)))
              }
              className="ml-auto text-[11px] text-ink-dim hover:text-ink"
            >
              {allChecked ? "зняти всі" : "вибрати всі"}
            </button>
          )}
        </div>

        <div className="px-3 pb-3">
          <div
            className={clsx(
              "grid place-items-center rounded-md border border-dashed py-6 text-center transition-colors",
              dragging ? "border-accent bg-surface-2" : "border-line-2",
            )}
          >
            <span className="text-[12px] text-ink-dim">
              {busy ? (progress ? `додаємо · ${progress}` : "додаємо…") : "Перетягніть файли у вікно"}
            </span>
            <button
              type="button"
              disabled={busy}
              onClick={() => fileInput.current?.click()}
              className="mt-2 rounded border border-line bg-surface px-2.5 py-1 text-[12px] text-ink hover:bg-surface-2 disabled:opacity-40"
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

        {checked.size > 0 && (
          <div className="mx-3 mb-2 rounded border border-line-2 bg-surface p-2">
            <div className="flex items-baseline justify-between">
              <span className="text-[11px] text-ink-dim">
                позначено {checked.size}
              </span>
              <button
                type="button"
                onClick={() => setChecked(new Set())}
                className="text-[11px] text-ink-faint hover:text-ink"
              >
                зняти
              </button>
            </div>
            {tags.length === 0 ? (
              <p className="mt-1.5 text-[11px] text-ink-faint">
                щоб проставити теги гуртом, спершу наповніть словник на вкладці «Теги»
              </p>
            ) : (
              <>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {tags.map((tag) => (
                    <button
                      key={tag.id}
                      type="button"
                      disabled={batch !== null}
                      onClick={() => void applyTagsToChecked(tag.name)}
                      className="rounded-sm bg-surface-3 px-1.5 py-[1px] text-[11px] text-ink-dim-2 hover:text-ink disabled:opacity-40"
                    >
                      + {tag.name}
                    </button>
                  ))}
                </div>
                <p className="mt-1.5 text-[11px] text-ink-faint">
                  {batch ?? "тег проставиться всім позначеним"}
                </p>
              </>
            )}
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
          {rows.length === 0 && (
            <p className="px-2 text-[11px] text-ink-faint">поки нічого не додано</p>
          )}
          {rows.map((row) => {
            const job = jobByItem.get(row.item_id);
            const status = !job
              ? "готово"
              : job.status === "running"
                ? `${Math.round(job.progress * 100)}% · ${job.stage}`
                : job.status === "failed"
                  ? "помилка"
                  : job.status === "done"
                    ? "готово"
                    : "у черзі";
            return (
              <div
                key={row.item_id}
                className={clsx(
                  "mb-1 flex w-full items-center gap-2 rounded px-2 py-1.5 transition-colors",
                  selected === row.item_id ? "bg-surface-3" : "hover:bg-surface-2",
                )}
              >
                <input
                  type="checkbox"
                  checked={checked.has(row.item_id)}
                  onChange={() => toggleChecked(row.item_id)}
                  className="size-3 shrink-0 accent-[var(--color-accent)]"
                />
                <button
                  type="button"
                  onClick={() => setSelected(row.item_id)}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                >
                  <span className="tnum rounded-sm bg-surface-3 px-1 py-[1px] text-[9px] text-ink-faint">
                    {KIND_LABEL[row.kind as Kind] ?? "—"}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12px] text-ink">{row.name}</span>
                    <span
                      className={clsx(
                        "block truncate text-[11px]",
                        job?.status === "failed" ? "text-error" : "text-ink-faint",
                      )}
                    >
                      {status}
                    </span>
                  </span>
                </button>
              </div>
            );
          })}
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 gap-1 border-b border-line px-4 py-2">
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
          {error && (
            <span className="ml-auto self-center truncate text-[11px] text-error">
              {error}
            </span>
          )}
        </div>

        {mode === "text" ? (
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
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
          <div className="flex flex-1 items-center justify-center px-8 text-center">
            <p className="max-w-[420px] text-[13px] leading-[1.6] text-ink-dim">
              Перетягніть файли у вікно або виберіть їх. Після додавання тут
              зʼявиться форма запису: лейбл, теги й транскрибція.
            </p>
          </div>
        ) : (
          <>
            <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
              <div className="tnum text-[11px] text-ink-faint">
                {KIND_LABEL[detail.kind]}
                {detail.duration_s ? ` · ${formatTime(detail.duration_s)}` : ""}
                {detail.transcript_lang ? ` · ${detail.transcript_lang}` : ""}
                {` · ${STATUS_LABEL[detail.status] ?? detail.status}`}
              </div>

              <div className="space-y-1.5">
                <SectionLabel>Лейбл</SectionLabel>
                <input
                  value={detail.label}
                  onChange={(e) => editField("label", e.target.value)}
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
                          onClick={() => toggleTag(tag.name)}
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
                        onChange={(e) => editField("transcript", e.target.value)}
                        rows={8}
                        className="selectable w-full resize-y rounded border border-line bg-surface p-3 text-[13px] leading-[1.6] text-ink focus:border-line-2 focus:outline-none"
                      />
                      <p className="text-[11px] text-ink-faint">
                        текст машинний — після збереження пошук перебудується на
                        виправлений
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

            {/* Панель збереження закріплена внизу: форма буває довгою, і кнопка
                не має ховатися за транскрибцією на пів екрана. */}
            <div className="flex shrink-0 items-center gap-3 border-t border-line bg-canvas px-4 py-2.5">
              <button
                type="button"
                onClick={save}
                disabled={!dirty || saving}
                className="rounded bg-accent px-3 py-1.5 text-[12px] font-medium text-ground disabled:opacity-40"
              >
                {saving ? "Зберігаємо…" : "Зберегти запис"}
              </button>
              <span className="text-[11px] text-ink-faint">
                {dirty
                  ? "є незбережені зміни · Ctrl+S"
                  : savedAt
                    ? "збережено"
                    : "запис уже в бібліотеці — правки застосуються після збереження"}
              </span>
              <button
                type="button"
                onClick={() => setSelected(null)}
                className="ml-auto rounded border border-line bg-surface px-2.5 py-1.5 text-[12px] text-ink-dim hover:text-ink"
              >
                {dirty ? "Відкинути" : "Готово"}
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
