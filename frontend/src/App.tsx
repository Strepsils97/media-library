import { useEffect, useState } from "react";

type Health = { status: string; data_dir: string; db: boolean };

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="flex h-full flex-col items-center justify-center gap-3">
      <h1 className="text-2xl font-semibold">media-library</h1>
      {error && <p className="text-red-400">Бекенд недоступний: {error}</p>}
      {health && (
        <p className="text-sm text-[var(--color-ink-dim)]">
          Бібліотека: {health.data_dir} · база {health.db ? "готова" : "порожня"}
        </p>
      )}
    </div>
  );
}
