const API_BASE = "";

const pathSegment = (value: string): string => {
  if (value.length === 0 || value === "." || value === "..") {
    throw new TypeError("DataOS resource IDs must be non-empty and cannot be dot path segments.");
  }
  return encodeURIComponent(value);
};

async function apiFetch(path: string, options?: RequestInit): Promise<any> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

export const api = {
  health: () => apiFetch("/api/catalog/health"),

  listObjects: (
    params?: { object_type?: string; limit?: number; offset?: number },
    options?: Pick<RequestInit, "signal">,
  ) => {
    const qs = new URLSearchParams();
    if (params?.object_type) qs.set("object_type", params.object_type);
    if (params?.limit !== undefined) qs.set("limit", String(params.limit));
    if (params?.offset !== undefined) qs.set("offset", String(params.offset));
    return apiFetch(`/api/objects/?${qs}`, options);
  },

  getObject: (id: string) => apiFetch(`/api/objects/${pathSegment(id)}`),

  createObject: (data: any) =>
    apiFetch("/api/objects/", { method: "POST", body: JSON.stringify(data) }),

  deleteObject: (id: string) =>
    apiFetch(`/api/objects/${pathSegment(id)}`, { method: "DELETE" }),

  listRelationships: (
    params?: { source_id?: string; target_id?: string; limit?: number; offset?: number },
    options?: Pick<RequestInit, "signal">,
  ) => {
    const qs = new URLSearchParams();
    if (params?.source_id) qs.set("source_id", params.source_id);
    if (params?.target_id) qs.set("target_id", params.target_id);
    if (params?.limit !== undefined) qs.set("limit", String(params.limit));
    if (params?.offset !== undefined) qs.set("offset", String(params.offset));
    return apiFetch(`/api/relationships/?${qs}`, options);
  },

  createRelationship: (data: any) =>
    apiFetch("/api/relationships/", { method: "POST", body: JSON.stringify(data) }),

  getNeighbors: (id: string, direction?: string) => {
    const qs = new URLSearchParams({ direction: direction ?? "both" });
    return apiFetch(`/api/graph/neighbors/${pathSegment(id)}?${qs}`);
  },

  traverse: (id: string, maxHops?: number) => {
    const qs = new URLSearchParams({ max_hops: String(maxHops ?? 3) });
    return apiFetch(`/api/graph/traverse/${pathSegment(id)}?${qs}`);
  },

  graphAnalytics: (algorithm?: string) => {
    const qs = new URLSearchParams({ algorithm: algorithm ?? "pagerank" });
    return apiFetch(`/api/graph/analytics?${qs}`);
  },

  search: (q: string, limit?: number) => {
    const qs = new URLSearchParams({ q, limit: String(limit ?? 20) });
    return apiFetch(`/api/search/?${qs}`);
  },

  askDataOS: (query: string) =>
    apiFetch("/api/ask", { method: "POST", body: JSON.stringify({ query }) }),

  lineage: (id: string, direction?: string) => {
    const qs = new URLSearchParams({ direction: direction ?? "upstream" });
    return apiFetch(`/api/provenance/lineage/${pathSegment(id)}?${qs}`);
  },

  why: (id: string) => apiFetch(`/api/objects/${pathSegment(id)}/why`),
  impact: (id: string) => apiFetch(`/api/objects/${pathSegment(id)}/impact`),

  executeSQL: (query: string) =>
    apiFetch("/api/compute/sql", { method: "POST", body: JSON.stringify({ query }) }),

  executePython: (code: string, inputIds?: string[]) =>
    apiFetch("/api/compute/python", {
      method: "POST",
      body: JSON.stringify({ code, input_object_ids: inputIds || [] }),
    }),

  profile: (id: string) => apiFetch(`/api/profiling/${pathSegment(id)}`),

  duplicates: (id?: string) => {
    const qs = new URLSearchParams();
    if (id) qs.set("object_id", id);
    const query = qs.toString();
    return apiFetch(`/api/governance/duplicates${query ? `?${query}` : ""}`);
  },

  recommendations: (id: string) =>
    apiFetch(`/api/recommendations/connections/${pathSegment(id)}`),

  queryKnowledge: (data: { query: string; selected_file_ids: string[]; include_related?: boolean; max_related_files?: number; min_confidence?: number }) =>
    apiFetch("/api/knowledge/query", { method: "POST", body: JSON.stringify(data) }),
};
