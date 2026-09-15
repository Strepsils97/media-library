// Згенеровано scripts/make_icon.py — правити там, не тут.
//
// Знак застосунку. До 28 px монограма зливається в пляму, тому дрібні
// розміри малюються крапкою — те саме правило, що і в іконці екзешника.

interface Props {
  size?: number;
  className?: string;
}

export function Mark({ size = 21, className }: Props) {
  const dot = size < 28;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 128 128"
      className={className}
      aria-hidden="true"
    >
      <path
        d="M 64.00 14.00 A 50 50 0 1 1 15.56 51.62"
        fill="none"
        stroke="currentColor"
        strokeWidth={dot ? 15 : 13}
        strokeLinecap="round"
      />
      {dot ? (
        <circle cx="64" cy="64" r="15" fill="currentColor" />
      ) : (
        <>
          <path d="M 58.67 65.44 58.97 58.03 58.63 58.03 53.69 71.68 48.75 58.03 48.41 58.03 48.71 65.44 48.71 77.26 43.77 77.26 43.77 50.74 50.50 50.74 53.77 59.67 54.07 59.67 57.34 50.74 63.61 50.74 63.61 77.26 58.67 77.26 Z" fill="currentColor" />
          <path d="M 67.09 77.26 67.09 50.74 72.83 50.74 72.83 72.59 84.23 72.59 84.23 77.26 Z" fill="currentColor" />
        </>
      )}
    </svg>
  );
}
