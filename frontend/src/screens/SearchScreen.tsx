import clsx from "clsx";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api";
import { ResultCard } from "../components/ResultCard";
import type { Kind, SearchFilters, SearchHit, SearchResponse, Tag } from "../types";

const KINDS: { id: Kind; short: string; label: string }[] = [
  { id: "image", short: "ІМГ", label: "Картинки" },
  { id: "video", short: "ВІД", label: "Відео" },
  { id: "audio", short: "АУД", label: "Аудіо" },
  { id: "text", short: "ТХТ", label: "Текст" },
];

const EMPTY: SearchFilters = {
  query: "",
  kinds: [],
  tags: [],
  date_from: null,
  date_to: null,
};

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="font-mono text-[10px] font-semibold tracking-[0.14em] text-ink-faint uppercase">
      {children}
    </div>
  );
}

function Skeleton() {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(168px,1fr))] gap-2.5">
      {Array.from({ length: 14 }).map((_, i) => (
        <div
          key={i}
          className="ml-pulse overflow-hidden rounded-md border border-line bg-surface"
          style={{ animationDelay: `${i * 60}ms` }}
        >
          <div className="aspect-4/3 bg-surface-3" />
          <div className="space-y-1.5 p-2.5">
            <div className="h-3 w-3/4 rounded-sm bg-surface-3" />
            <div className="h-2.5 w-1/2 rounded-sm bg-surface-3" />
          </div>
        </div>
      ))}
    </div>
  );
}

function LibraryEmpty() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-8 text-center">
      <div className="grid h-16 w-16 place-items-center rounded-lg border border-dashed border-line-2 font-mono text-[11px] tracking-[0.14em] text-ink-faint">
        DROP
      </div>
      <h2 className="mt-5 text-[15px] font-semibold text-ink">Бібліотека порожня</h2>
      <p className="mt-2 max-w-[440px] text-[13px] leading-[1.6] text-ink-dim">
        Перетягніть картинки, відео, аудіо або текстові файли просто у вікно — вони
        скопіюються в теку бібліотеки й проіндексуються.
      </p>
    </div>
  );
}

function NothingFound({
  unfiltered,
  hasFilters,
  onReset,
  exact,
}: {
  unfiltered: number;
  hasFilters: boolean;
  onReset: () => void;
  exact?: string;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-8 text-center">
      <h2 className="text-[15px] font-semibold text-ink">Нічого не знайшлось</h2>
      <p className="mt-2 max-w-[460px] text-[13px] leading-[1.6] text-ink-dim">
        {exact
          ? `Дослівно «${exact}» у бібліотеці немає. Заберіть лапки — тоді пошук знайде і за змістом, і з поправкою на помилки розпізнавання.`
          : hasFilters
            ? "Фільтри відсікають більшу частину бібліотеки. Спробуйте зняти їх або описати запис іншими словами — пошук шукає за змістом, а не за іменем файлу."
            : "Спробуйте описати запис іншими словами — пошук шукає за змістом, а не за іменем файлу."}
      </p>
      {hasFilters && (
        <>
          <button
            type="button"
            onClick={onReset}
            className="mt-4 rounded border border-line bg-surface px-3 py-1.5 text-[12px] text-ink transition-colors hover:border-line-2 hover:bg-surface-2"
          >
            Зняти всі фільтри
          </button>
          {unfiltered > 0 && (
            <p className="tnum mt-2 text-[11px] text-ink-faint">
              без фільтрів знайшлось би {unfiltered} записів
            </p>
          )}
        </>
      )}
    </div>
  );
}

interface Props {
  libraryEmpty: boolean;
  // Запит їде в переглядач: там він потрібен, щоб підсвітити в тексті саме
  // те, за що запис потрапив у видачу.
  onOpen: (hits: SearchHit[], index: number, query: string) => void;
}

export function SearchScreen({ libraryEmpty, onOpen }: Props) {
  const [filters, setFilters] = useState<SearchFilters>(EMPTY);
  const [tags, setTags] = useState<Tag[]>([]);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.tags().then(setTags).catch(() => setTags([]));
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const run = useCallback((next: SearchFilters) => {
    if (!next.query.trim()) {
      setResult(null);
      return;
    }
    setLoading(true);
    setError(null);
    api
      .search(next)
      .then(setResult)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Пошук іде по натисканню Enter, а не на кожен символ: кожен запит — це
  // прогін моделі, і посимвольний debounce тут дав би чергу зайвих обрахунків.
  const submit = () => run(filters);

  const toggleKind = (kind: Kind) => {
    const next = {
      ...filters,
      kinds: filters.kinds.includes(kind)
        ? filters.kinds.filter((k) => k !== kind)
        : [...filters.kinds, kind],
    };
    setFilters(next);
    if (result) run(next);
  };

  const setDate = (field: "date_from" | "date_to", value: string) => {
    // <input type="date"> дає YYYY-MM-DD, а в базі created_at — ISO-8601.
    // Верхню межу розтягуємо до кінця доби, інакше «до 5 травня» відсікало б
    // усе, зняте того самого дня після опівночі.
    const iso =
      value === ""
        ? null
        : field === "date_from"
          ? `${value}T00:00:00+00:00`
          : `${value}T23:59:59+00:00`;
    const next = { ...filters, [field]: iso };
    setFilters(next);
    if (result) run(next);
  };

  const toggleTag = (name: string) => {
    const next = {
      ...filters,
      tags: filters.tags.includes(name)
        ? filters.tags.filter((t) => t !== name)
        : [...filters.tags, name],
    };
    setFilters(next);
    if (result) run(next);
  };

  const reset = () => {
    const next = { ...EMPTY, query: filters.query };
    setFilters(next);
    run(next);
  };

  const hasFilters =
    filters.kinds.length > 0 ||
    filters.tags.length > 0 ||
    filters.date_from !== null ||
    filters.date_to !== null;

  if (libraryEmpty) return <LibraryEmpty />;

  return (
    <div className="flex h-full">
      <aside className="flex w-[196px] shrink-0 flex-col gap-5 overflow-y-auto border-r border-line bg-canvas px-3 py-4">
        <div className="space-y-2">
          <SectionLabel>Тип</SectionLabel>
          <div className="space-y-0.5">
            {KINDS.map((kind) => {
              const active = filters.kinds.includes(kind.id);
              return (
                <button
                  key={kind.id}
                  type="button"
                  onClick={() => toggleKind(kind.id)}
                  className={clsx(
                    "flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-[12px] transition-colors",
                    active
                      ? "bg-surface-3 text-ink"
                      : "text-ink-dim hover:bg-surface-2 hover:text-ink",
                  )}
                >
                  <span
                    className={clsx(
                      "tnum rounded-sm px-1 py-[1px] text-[9px] tracking-wider",
                      active ? "bg-accent text-ground" : "bg-surface-3 text-ink-faint",
                    )}
                  >
                    {kind.short}
                  </span>
                  {kind.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="space-y-2">
          <SectionLabel>Дата створення</SectionLabel>
          <div className="space-y-1">
            {(
              [
                ["date_from", "від"],
                ["date_to", "до"],
              ] as const
            ).map(([field, label]) => (
              <label key={field} className="flex items-center gap-2">
                <span className="w-5 text-[11px] text-ink-faint">{label}</span>
                <input
                  type="date"
                  value={filters[field]?.slice(0, 10) ?? ""}
                  onChange={(e) => setDate(field, e.target.value)}
                  className="tnum min-w-0 flex-1 rounded border border-line bg-surface px-1.5 py-1 text-[11px] text-ink focus:border-line-2 focus:outline-none"
                />
              </label>
            ))}
          </div>
        </div>

        <div className="space-y-2">
          <SectionLabel>Теги</SectionLabel>
          {tags.length === 0 ? (
            <p className="text-[11px] text-ink-faint">словник порожній</p>
          ) : (
            <div className="flex flex-wrap gap-1">
              {tags.map((tag) => {
                const active = filters.tags.includes(tag.name);
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
              })}
            </div>
          )}
        </div>

        {hasFilters && (
          <button
            type="button"
            onClick={reset}
            className="self-start text-[11px] text-ink-faint underline-offset-2 hover:text-ink hover:underline"
          >
            Скинути
          </button>
        )}
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center gap-2 border-b border-line px-4 py-3">
          <input
            ref={inputRef}
            value={filters.query}
            onChange={(e) => setFilters({ ...filters, query: e.target.value })}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="Опишіть, що шукаєте — своїми словами, у лапках — дослівно"
            className="selectable min-w-0 flex-1 bg-transparent text-[14px] text-ink placeholder:text-ink-faint focus:outline-none"
          />
          {result?.exact && !loading && (
            <span className="shrink-0 rounded-sm bg-accent/15 px-1.5 py-[1px] font-mono text-[10px] font-semibold tracking-[0.1em] text-accent uppercase">
              дослівно
            </span>
          )}
          {result && !loading && (
            <span className="tnum shrink-0 text-[11px] text-ink-faint">
              {result.took_ms} мс
            </span>
          )}
          <button
            type="button"
            onClick={submit}
            className="tnum shrink-0 rounded border border-line bg-surface px-2 py-1 text-[11px] text-ink-dim transition-colors hover:border-line-2 hover:text-ink"
          >
            ⏎
          </button>
        </div>

        {result && !loading && result.hits.length > 0 && (
          <div className="flex shrink-0 items-baseline gap-2 px-4 pt-3">
            <span className="tnum text-[12px] text-ink">{result.total} записів</span>
            <span className="text-[11px] text-ink-faint">
              за релевантністю · схожість нормалізована в межах модальності
            </span>
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {error ? (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <p className="text-[13px] text-error">{error}</p>
              <button
                type="button"
                onClick={submit}
                className="mt-3 rounded border border-line bg-surface px-3 py-1.5 text-[12px] text-ink hover:bg-surface-2"
              >
                Повторити
              </button>
            </div>
          ) : loading ? (
            <Skeleton />
          ) : !result ? (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <p className="max-w-[420px] text-[13px] leading-[1.6] text-ink-dim">
                Пошук за змістом, а не за іменем файлу. Опишіть запис так, як
                запам'ятали його.
              </p>
            </div>
          ) : result.hits.length === 0 ? (
            <NothingFound
              unfiltered={result.total_unfiltered}
              hasFilters={hasFilters}
              onReset={reset}
              exact={result.exact}
            />
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(168px,1fr))] gap-2.5">
              {result.hits.map((hit, index) => (
                <ResultCard
                  key={hit.item_id}
                  hit={hit}
                  onOpen={() => onOpen(result.hits, index, filters.query)}
                />
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
