import type {
  BackupList,
  ConvertResult,
  ItemDetail,
  Job,
  LibraryStats,
  RuntimeStatus,
  SearchFilters,
  SearchResponse,
  Tag,
  UserSettings,
} from "./types";

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    // Бек віддає причину текстом — показуємо саме її, а не код статусу.
    const detail = await response.text().catch(() => "");
    throw new ApiError(detail || response.statusText, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; data_dir: string }>("/health"),
  stats: () => request<LibraryStats>("/stats"),
  runtime: () => request<RuntimeStatus>("/runtime"),

  search: (filters: SearchFilters) =>
    request<SearchResponse>("/search", {
      method: "POST",
      body: JSON.stringify(filters),
    }),

  tags: () => request<Tag[]>("/tags"),
  createTag: (name: string) =>
    request<Tag>("/tags", { method: "POST", body: JSON.stringify({ name }) }),
  renameTag: (id: number, name: string) =>
    request<Tag>(`/tags/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),
  deleteTag: (id: number) => request<void>(`/tags/${id}`, { method: "DELETE" }),

  item: (id: number) => request<ItemDetail>(`/items/${id}`),
  patchItem: (id: number, payload: Partial<Pick<ItemDetail, "label" | "transcript" | "tags">>) =>
    request<ItemDetail>(`/items/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  /** Наскільки кожна ділянка тексту відповідає запиту: [початок, кінець, 0..1]. */
  itemHeat: (id: number, query: string) =>
    request<{ spans: [number, number, number][] }>(`/items/${id}/heat`, {
      method: "POST",
      body: JSON.stringify({ query }),
    }),
  deleteItem: (id: number) => request<void>(`/items/${id}`, { method: "DELETE" }),
  exportItem: (id: number, denoise: string) =>
    request<{ path: string; name: string; denoised: string }>(
      `/items/${id}/export`,
      { method: "POST", body: JSON.stringify({ denoise }) },
    ),
  /** Адреса обробленого звуку для прослуховування. */
  previewUrl: (id: number, level: string) =>
    `/api/media/preview/${id}?level=${encodeURIComponent(level)}`,
  reveal: (path: string) =>
    request<{ revealed: boolean }>("/reveal", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  createText: (text: string) =>
    request<{ item_id: number; duplicate: boolean }>("/items/text", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  convertFormats: () =>
    request<{
      formats: { id: string; suffix: string; lossy: boolean }[];
      bitrates: string[];
      default_bitrate: string;
      target_dir: string;
    }>("/convert/formats"),
  pickFiles: () => request<{ paths: string[] }>("/convert/pick", { method: "POST" }),
  convert: (paths: string[], format: string, bitrate: string) =>
    request<{ results: ConvertResult[] }>("/convert", {
      method: "POST",
      body: JSON.stringify({ paths, format, bitrate }),
    }),

  backups: () => request<BackupList>("/backups"),
  createBackup: () => request<void>("/backups", { method: "POST" }),
  restoreBackup: (name: string) =>
    request<{ pending_restore: string }>(
      `/backups/${encodeURIComponent(name)}/restore`,
      { method: "POST" },
    ),
  cancelRestore: () => request<void>("/backups/pending", { method: "DELETE" }),
  deleteBackup: (name: string) =>
    request<void>(`/backups/${encodeURIComponent(name)}`, { method: "DELETE" }),

  settings: () => request<UserSettings>("/settings"),
  saveSettings: (patch: Partial<UserSettings>) =>
    request<UserSettings>("/settings", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  pickFolder: () =>
    request<{ path: string | null }>("/settings/pick-folder", { method: "POST" }),
  reindex: () =>
    request<{ queued: number }>("/library/reindex", { method: "POST" }),

  jobs: () => request<Job[]>("/jobs"),
  retryJob: (id: number) => request<Job>(`/jobs/${id}/retry`, { method: "POST" }),
  cancelJob: (id: number) => request<void>(`/jobs/${id}`, { method: "DELETE" }),
  clearDoneJobs: () =>
    request<{ removed: number }>("/jobs/clear-done", { method: "POST" }),
  pauseJobs: (value: boolean) =>
    request<{ paused: boolean }>(`/jobs/pause?value=${value}`, { method: "POST" }),
};

export { ApiError };
