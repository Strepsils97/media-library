import clsx from "clsx";

import type { Kind, SearchHit } from "../types";
import { SimilarityRing } from "./SimilarityRing";

const KIND_LABEL: Record<Kind, string> = {
  image: "ІМГ",
  video: "ВІД",
  audio: "АУД",
  text: "ТХТ",
};

function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleDateString("uk-UA", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function pluralWords(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return "слово";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "слова";
  return "слів";
}

/** Уривок із підсвіченим збігом. Позиції приходять із бекенда в символах. */
function Snippet({ hit }: { hit: SearchHit }) {
  if (!hit.snippet) return null;
  const range = hit.snippet_highlight;
  if (!range) {
    return <>{hit.snippet}</>;
  }
  const [from, to] = range;
  return (
    <>
      {hit.snippet.slice(0, from)}
      <mark className="bg-transparent text-accent">{hit.snippet.slice(from, to)}</mark>
      {hit.snippet.slice(to)}
    </>
  );
}

/** Хвиля для аудіо: детермінована за item_id, щоб картка не «дихала»
 *  при кожному перерендері, і однакова між сесіями. */
function Waveform({ seed, matchAt }: { seed: number; matchAt: number | null }) {
  const bars = 44;
  const values: number[] = [];
  let state = seed * 9301 + 49297;
  for (let i = 0; i < bars; i++) {
    state = (state * 9301 + 49297) % 233280;
    values.push(0.25 + (state / 233280) * 0.75);
  }
  const highlight = matchAt === null ? -1 : Math.floor(matchAt * bars);

  return (
    <div className="flex h-full items-center justify-center gap-[2px] px-3">
      {values.map((v, i) => (
        <div
          key={i}
          className={clsx(
            "w-[2px] rounded-full",
            i >= highlight - 3 && i <= highlight + 3 ? "bg-accent" : "bg-ink-faint/60",
          )}
          style={{ height: `${v * 62}%` }}
        />
      ))}
    </div>
  );
}

function Preview({ hit }: { hit: SearchHit }) {
  if (hit.thumb_url) {
    return (
      <>
        <img
          src={hit.thumb_url}
          alt=""
          loading="lazy"
          className="h-full w-full object-cover"
        />
        {hit.kind === "video" && hit.duration_s !== null && (
          <span className="tnum absolute bottom-1.5 left-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px] text-ink">
            ▶ {formatDuration(hit.duration_s)}
          </span>
        )}
        {/* Тонка риска показує, де в записі знайдено збіг. */}
        {hit.kind === "video" && hit.match_ts_s !== null && hit.duration_s ? (
          <span
            className="absolute bottom-0 h-[2px] w-[14%] bg-accent"
            style={{
              left: `${Math.min(86, (hit.match_ts_s / hit.duration_s) * 100)}%`,
            }}
          />
        ) : null}
      </>
    );
  }

  if (hit.kind === "audio") {
    return (
      <>
        <Waveform
          seed={hit.item_id}
          matchAt={
            hit.match_ts_s !== null && hit.duration_s
              ? hit.match_ts_s / hit.duration_s
              : null
          }
        />
        {hit.duration_s !== null && (
          <span className="tnum absolute bottom-1.5 left-1.5 text-[10px] text-ink-dim">
            {formatDuration(hit.duration_s)}
          </span>
        )}
      </>
    );
  }

  // Текст: прев'ю — сам текст набірним шрифтом.
  return (
    <p className="font-serif h-full overflow-hidden px-3 py-2.5 text-[11.5px] leading-[1.5] text-ink-dim">
      <Snippet hit={hit} />
    </p>
  );
}

interface Props {
  hit: SearchHit;
  onOpen: (hit: SearchHit) => void;
}

export function ResultCard({ hit, onOpen }: Props) {
  // Для картинки уривка немає — замість нього технічний рядок, інакше
  // висота картки стрибала б і сітка розсипалася.
  const meta =
    hit.kind === "image"
      ? `Зображення · ${hit.width ?? "?"}×${hit.height ?? "?"} · ${formatDate(hit.created_at)}`
      : hit.kind === "text"
        ? `Нотатка · ${hit.word_count ?? 0} ${pluralWords(hit.word_count ?? 0)} · ${formatDate(hit.created_at)}`
        : formatDate(hit.created_at);

  return (
    <button
      type="button"
      onClick={() => onOpen(hit)}
      className="group flex flex-col rounded-md border border-line bg-surface text-left transition-colors hover:border-line-2 hover:bg-surface-2 focus:outline-none focus-visible:border-accent"
    >
      <div className="relative aspect-4/3 overflow-hidden rounded-t-md bg-stage">
        <Preview hit={hit} />
        <span className="tnum absolute top-1.5 right-1.5 rounded bg-black/65 px-1 py-0.5 text-[9px] tracking-wider text-ink-dim">
          {KIND_LABEL[hit.kind]}
        </span>
      </div>

      <div className="flex gap-2 p-2.5">
        <SimilarityRing score={hit.score} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[14px] leading-tight font-medium text-ink">
            {hit.label}
          </div>

          {hit.kind !== "image" && hit.kind !== "text" && hit.snippet ? (
            <p className="mt-1 line-clamp-2 text-[12px] leading-[1.45] text-ink-dim">
              <Snippet hit={hit} />
            </p>
          ) : (
            <div className="mt-1 truncate text-[12px] text-ink-faint">{meta}</div>
          )}

          <div className="mt-1.5 flex flex-wrap gap-1">
            {hit.tags.length === 0 ? (
              <span className="text-[11px] text-ink-faint">без тегів</span>
            ) : (
              hit.tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded-sm bg-surface-3 px-1.5 py-[1px] text-[11px] text-ink-dim-2"
                >
                  {tag}
                </span>
              ))
            )}
          </div>
        </div>
      </div>
    </button>
  );
}
