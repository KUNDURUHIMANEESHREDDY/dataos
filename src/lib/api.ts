const API_BASE = "";

const MAX_ERROR_BODY_BYTES = 4096;
const MAX_ERROR_DETAIL_CHARS = 1000;

const truncateText = (value: string, maxChars = MAX_ERROR_DETAIL_CHARS): string =>
  value.length > maxChars ? `${value.slice(0, maxChars - 1)}…` : value;

const pathSegment = (value: string): string => {
  if (value.length === 0 || value === "." || value === "..") {
    throw new TypeError("DataOS resource IDs must be non-empty and cannot be dot path segments.");
  }
  return encodeURIComponent(value);
};

async function readBoundedErrorBody(response: Response): Promise<string> {
  const reader = response.body?.getReader();
  if (!reader) return "";

  const decoder = new TextDecoder();
  let text = "";
  let bytesRead = 0;
  let truncated = false;

  try {
    while (bytesRead < MAX_ERROR_BODY_BYTES) {
      const { done, value } = await reader.read();
      if (done) break;

      const remaining = MAX_ERROR_BODY_BYTES - bytesRead;
      const chunk = value.subarray(0, remaining);
      text += decoder.decode(chunk, { stream: true });
      bytesRead += chunk.byteLength;

      if (chunk.byteLength < value.byteLength) {
        truncated = true;
        await reader.cancel().catch(() => undefined);
        break;
      }
    }

    if (bytesRead === MAX_ERROR_BODY_BYTES) {
      truncated = true;
      await reader.cancel().catch(() => undefined);
    }

    text += decoder.decode();
    return truncated ? `${text}…` : text;
  } finally {
    reader.releaseLock();
  }
}

function errorDetail(body: string, contentType: string, statusText: string): string {
  const fallback = statusText || "Request failed";
  if (!body) return fallback;

  if (contentType.includes("json")) {
    try {
      const payload: unknown = JSON.parse(body);
      if (payload && typeof payload === "object") {
        const record = payload as Record<string, unknown>;
        const detail = record.detail ?? record.message ?? record.error;
        if (typeof detail === "string" && detail.trim()) return truncateText(detail.trim());
        if (detail !== undefined) return truncateText(JSON.stringify(detail));
      }
    } catch {
      return fallback;
    }
    return fallback;
  }

  // Never surface an upstream HTML error page or an unbounded response body
  // in the application UI. Plain-text API errors remain useful when bounded.
  if (contentType.includes("text/plain")) {
    const safeText = body.replace(/[\\u0000-\\u0008\\u000B\\u000C\\u000E-\\u001F\\u007F]/g, "").trim();
    return truncateText(safeText) || fallback;
  }
  return fallback;
}

async function apiFetch(path: string, options?: RequestInit): Promise<any> {
  const headers = new Headers({ "Content-Type": "application/json" });
  new Headers(options?.headers).forEach((value, name) => headers.set(name, value));

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });
  if (!res.ok) {
    const contentType = (res.headers.get("content-type") || "").toLowerCase();
    const body = await readBoundedErrorBody(res);
    throw new Error(`API ${res.status}: ${errorDetail(body, contentType, res.statusText)}`);
  }
  if (res.status === 204 || res.status === 205) return undefined;

  const contentType = (res.headers.get("content-type") || "").toLowerCase();
  if (contentType && !contentType.includes("json")) {
    if (res.body) await res.body.cancel().catch(() => undefined);
    throw new Error(`API ${res.status}: expected a JSON response`);
  }
  try {
    return await res.json();
  } catch {
    throw new Error(`API ${res.status}: invalid or empty JSON response`);
  }
}

type ReadOptions = Pick<RequestInit, "signal" | "headers">;

export const api = {
  health: () => apiFetch("/api/catalog/health"),

  listObjects: (
    params?: { object_type?: string; limit?: number; offset?: number },
    options?: ReadOptions,
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
    options?: ReadOptions,
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
