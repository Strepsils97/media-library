import { useEffect, useState } from "react";

import { api } from "../api";
import type { Tag } from "../types";

function pluralRecords(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return "запис";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "записи";
  return "записів";
}

function DeleteDialog({
  tag,
  onCancel,
  onConfirm,
}: {
  tag: Tag;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-6">
      <div className="w-full max-w-[420px] rounded-lg border border-line bg-surface p-5">
        <h2 className="text-[15px] font-semibold text-ink">
          Видалити тег «{tag.name}»?
        </h2>
        <p className="mt-2 text-[13px] leading-[1.6] text-ink-dim">
          <span className="tnum text-ink">
            {tag.usage_count} {pluralRecords(tag.usage_count)}
          </span>{" "}
          втратять цей тег. Самі записи та файли лишаються — зміниться тільки
          фільтрація за тегом.
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
            Видалити тег
          </button>
        </div>
      </div>
    </div>
  );
}

export function TagsScreen() {
  const [tags, setTags] = useState<Tag[]>([]);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<{ id: number; name: string } | null>(null);
  const [deleting, setDeleting] = useState<Tag | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => api.tags().then(setTags).catch(() => undefined);
  useEffect(() => {
    load();
  }, []);

  const add = async () => {
    const name = draft.trim();
    if (!name) return;
    try {
      await api.createTag(name);
      setDraft("");
      setError(null);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const saveRename = async () => {
    if (!editing) return;
    try {
      await api.renameTag(editing.id, editing.name);
      setEditing(null);
      setError(null);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-line px-4 py-3">
        <div className="flex items-baseline gap-3">
          <h1 className="text-[15px] font-semibold text-ink">Словник тегів</h1>
          <span className="tnum text-[11px] text-ink-faint">
            {tags.length} тегів · теги проставляються лише з цього списку
          </span>
        </div>
        <div className="mt-3 flex gap-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
            placeholder="Новий тег…"
            className="selectable w-[240px] rounded border border-line bg-surface px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-faint focus:border-line-2 focus:outline-none"
          />
          <button
            type="button"
            onClick={add}
            className="rounded border border-line bg-surface px-3 py-1.5 text-[12px] text-ink hover:border-line-2 hover:bg-surface-2"
          >
            Додати
          </button>
          {error && <span className="self-center text-[12px] text-error">{error}</span>}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <table className="w-full border-collapse">
          <thead className="sticky top-0 bg-canvas">
            <tr className="font-mono text-[10px] tracking-[0.14em] text-ink-faint uppercase">
              <th className="px-4 py-2 text-left font-semibold">Тег</th>
              <th className="px-2 py-2 text-left font-semibold">Використань</th>
              <th className="px-4 py-2 text-right font-semibold">Дії</th>
            </tr>
          </thead>
          <tbody>
            {tags.map((tag) => (
              <tr key={tag.id} className="border-t border-line">
                <td className="px-4 py-2.5">
                  {editing?.id === tag.id ? (
                    <input
                      autoFocus
                      value={editing.name}
                      onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") saveRename();
                        if (e.key === "Escape") setEditing(null);
                      }}
                      className="selectable rounded border border-accent bg-surface-2 px-2 py-1 text-[13px] text-ink focus:outline-none"
                    />
                  ) : (
                    <span className="text-[13px] text-ink">{tag.name}</span>
                  )}
                </td>
                <td className="tnum px-2 py-2.5 text-[12px] text-ink-dim">
                  {tag.usage_count}
                </td>
                <td className="px-4 py-2.5 text-right text-[12px]">
                  {editing?.id === tag.id ? (
                    <>
                      <button
                        type="button"
                        onClick={saveRename}
                        className="text-accent hover:underline"
                      >
                        Зберегти
                      </button>
                      <span className="mx-1.5 text-ink-faint">·</span>
                      <button
                        type="button"
                        onClick={() => setEditing(null)}
                        className="text-ink-dim hover:text-ink"
                      >
                        Скасувати
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => setEditing({ id: tag.id, name: tag.name })}
                        className="text-ink-dim hover:text-ink"
                      >
                        Перейменувати
                      </button>
                      <span className="mx-1.5 text-ink-faint">·</span>
                      <button
                        type="button"
                        onClick={() => setDeleting(tag)}
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

        <p className="px-4 py-3 text-[11px] text-ink-faint">
          перейменування зберігає теги на всіх записах · видалення знімає тег із
          записів, самі записи лишаються
        </p>
      </div>

      {deleting && (
        <DeleteDialog
          tag={deleting}
          onCancel={() => setDeleting(null)}
          onConfirm={async () => {
            await api.deleteTag(deleting.id);
            setDeleting(null);
            load();
          }}
        />
      )}
    </div>
  );
}
