import clsx from "clsx";

/** Три щаблі замість градієнта: сітка лишається спокійною, а верх видачі
 *  сам себе позначає. Межі — з дизайну. */
function tier(score: number): "strong" | "likely" | "weak" {
  if (score >= 80) return "strong";
  if (score >= 70) return "likely";
  return "weak";
}

const RING = {
  strong: "var(--color-accent)",
  likely: "var(--color-accent-soft)",
  weak: "var(--color-ink-faint)",
} as const;

const TEXT = {
  strong: "text-ink",
  likely: "text-ink-dim",
  weak: "text-ink-faint",
} as const;

interface Props {
  score: number;
  size?: number;
  className?: string;
}

export function SimilarityRing({ score, size = 30, className }: Props) {
  const level = tier(score);
  const stroke = 2;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(100, score));

  return (
    <div
      className={clsx("relative shrink-0", className)}
      style={{ width: size, height: size }}
      title={`Схожість ${Math.round(score)}%`}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--color-line)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={RING[level]}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - clamped / 100)}
        />
      </svg>
      <span
        className={clsx(
          "tnum absolute inset-0 flex items-center justify-center font-medium",
          TEXT[level],
        )}
        style={{ fontSize: size <= 30 ? 10 : 12 }}
      >
        {Math.round(clamped)}
      </span>
    </div>
  );
}
