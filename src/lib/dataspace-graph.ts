import { api } from "./api";
import paginate from "./paginate.js";
import { loadGraphCollections } from "./load-graph-collections.js";
import { toGraphEdge } from "./relationship-edge.js";
import type { ObjectType } from "../hooks/useSpatialStore";

const { loadBoundedPages } = paginate;

export const MAX_GRAPH_OBJECTS = 10_000;
export const MAX_GRAPH_RELATIONSHIPS = 20_000;

const typeMap: Record<string, ObjectType> = {
  document: "dataset",
  dataset: "dataset",
  csv: "dataset",
  entity: "entity",
  relation: "relation",
  analysis: "analysis",
  notebook: "analysis",
  agent: "agent",
};

function buildGraphNotice(
  objects: { items: unknown[]; total: number | null; truncated: boolean },
  relationships: { items: unknown[]; total: number | null; truncated: boolean },
): string | null {
  const limits: string[] = [];
  if (objects.truncated) {
    const total = objects.total === null
      ? `at least ${(objects.items.length + 1).toLocaleString()}`
      : objects.total.toLocaleString();
    limits.push(`${objects.items.length.toLocaleString()} of ${total} objects`);
  }
  if (relationships.truncated) {
    const total = relationships.total === null
      ? `at least ${(relationships.items.length + 1).toLocaleString()}`
      : relationships.total.toLocaleString();
    limits.push(`${relationships.items.length.toLocaleString()} of ${total} relationships`);
  }
  if (limits.length === 0) return null;
  return `Graph view is bounded to ${limits.join(" and ")} to protect browser memory and rendering performance. All records remain in storage; use search to locate specific objects.`;
}

export async function loadDataspaceGraph(controller: AbortController) {
  const [objectsResult, relationshipsResult] = await loadGraphCollections(
    controller,
    (signal: AbortSignal) => loadBoundedPages<any>(
      ({ limit, offset, signal: requestSignal }) => api.listObjects(
        { limit, offset },
        requestSignal ? { signal: requestSignal } : undefined,
      ),
      "objects",
      500,
      MAX_GRAPH_OBJECTS,
      signal,
    ),
    (signal: AbortSignal) => loadBoundedPages<any>(
      ({ limit, offset, signal: requestSignal }) => api.listRelationships(
        { limit, offset },
        requestSignal ? { signal: requestSignal } : undefined,
      ),
      "relationships",
      1000,
      MAX_GRAPH_RELATIONSHIPS,
      signal,
    ),
  );

  const objects = objectsResult.items.map((object: any) => ({
    id: object.id,
    type: (typeMap[object.type] || "dataset") as ObjectType,
    name: object.properties?.filename || object.properties?.name || String(object.id).slice(0, 8),
    properties: object.properties || {},
  }));
  const edges = relationshipsResult.items.flatMap((relationship: unknown) => {
    const edge = toGraphEdge(relationship as Record<string, unknown>);
    return edge ? [edge] : [];
  });

  return {
    objects,
    edges,
    notice: buildGraphNotice(objectsResult, relationshipsResult),
  };
}
