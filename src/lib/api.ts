import { mergeApiHeaders } from "./api-headers.mjs";

const API_BASE = "";

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiFetch(path: string, options?: RequestInit): Promise<any> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "same-origin",
    cache: "no-store",
    headers: mergeApiHeaders(options?.headers),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new ApiError(res.status, `API ${res.status}: ${text}`);
  }
  if (res.status === 204) return undefined;
  return res.json();
}

export const api = {
  authMe: () => apiFetch("/api/auth/me"),
  login: (login: string, password: string) =>
    apiFetch("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ login, password }),
    }),
  register: (data: { username: string; email: string; password: string }) =>
    apiFetch("/api/auth/register", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  logout: () => apiFetch("/api/auth/logout", { method: "POST" }),
  health: () => apiFetch("/api/catalog/health"),

  listObjects: (params?: { object_type?: string; limit?: number; offset?: number }, options?: RequestInit) => {
    const qs = new URLSearchParams();
    if (params?.object_type) qs.set("object_type", params.object_type);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.offset !== undefined) qs.set("offset", String(params.offset));
    return apiFetch(`/api/objects/?${qs}`, options);
  },

  getObject: (id: string) => apiFetch(`/api/objects/${id}`),

  createObject: (data: any) =>
    apiFetch("/api/objects/", { method: "POST", body: JSON.stringify(data) }),

  deleteObject: (id: string) =>
    apiFetch(`/api/objects/${id}`, { method: "DELETE" }),

  listRelationships: (params?: { source_id?: string; target_id?: string; limit?: number; offset?: number }, options?: RequestInit) => {
    const qs = new URLSearchParams();
    if (params?.source_id) qs.set("source_id", params.source_id);
    if (params?.target_id) qs.set("target_id", params.target_id);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.offset !== undefined) qs.set("offset", String(params.offset));
    return apiFetch(`/api/relationships/?${qs}`, options);
  },

  createRelationship: (data: any) =>
    apiFetch("/api/relationships/", { method: "POST", body: JSON.stringify(data) }),

  getNeighbors: (id: string, direction?: string) =>
    apiFetch(`/api/graph/neighbors/${id}?direction=${direction || "both"}`),

  traverse: (id: string, maxHops?: number) =>
    apiFetch(`/api/graph/traverse/${id}?max_hops=${maxHops || 3}`),

  graphAnalytics: (algorithm?: string) =>
    apiFetch(`/api/graph/analytics?algorithm=${algorithm || "pagerank"}`),

  search: (q: string, limit?: number) =>
    apiFetch(`/api/search/?q=${encodeURIComponent(q)}&limit=${limit || 20}`),

  askDataOS: (query: string) =>
    apiFetch("/api/ask", { method: "POST", body: JSON.stringify({ query }) }),

  lineage: (id: string, direction?: string) =>
    apiFetch(`/api/provenance/lineage/${id}?direction=${direction || "upstream"}`),

  why: (id: string) => apiFetch(`/api/objects/${id}/why`),
  impact: (id: string) => apiFetch(`/api/objects/${id}/impact`),

  executeSQL: (query: string) =>
    apiFetch("/api/compute/sql", { method: "POST", body: JSON.stringify({ query }) }),

  executePython: (code: string, inputIds?: string[]) =>
    apiFetch("/api/compute/python", {
      method: "POST",
      body: JSON.stringify({ code, input_object_ids: inputIds || [] }),
    }),

  profile: (id: string) => apiFetch(`/api/profiling/${id}`),

  duplicates: (id?: string) =>
    apiFetch(`/api/governance/duplicates${id ? `?object_id=${id}` : ""}`),

  recommendations: (id: string) =>
    apiFetch(`/api/recommendations/connections/${id}`),
  queryKnowledge: (data: { query: string; selected_file_ids: string[]; include_related?: boolean; max_related_files?: number; min_confidence?: number }) =>
    apiFetch("/api/knowledge/query", { method: "POST", body: JSON.stringify(data) }),
};
