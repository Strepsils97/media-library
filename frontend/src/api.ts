import type {
  Job,
  LibraryStats,
  RuntimeStatus,
  SearchFilters,
  SearchResponse,
  Tag,
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

  jobs: () => request<Job[]>("/jobs"),
  retryJob: (id: number) => request<Job>(`/jobs/${id}/retry`, { method: "POST" }),
  cancelJob: (id: number) => request<void>(`/jobs/${id}`, { method: "DELETE" }),
};

export { ApiError };
