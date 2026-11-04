"use client";

import { useEffect, useState, lazy, Suspense } from "react";
import { useSpatialStore, type ObjectType } from "@/hooks/useSpatialStore";
import { api } from "@/lib/api";
import paginate from "@/lib/paginate.js";
import { toGraphEdge } from "@/lib/relationship-edge.js";
import { useKeyboard } from "@/hooks/useKeyboard";
import TopBar from "@/components/layout/TopBar";
import Sidebar from "@/components/layout/Sidebar";
import KnowledgeRAGPanel from "@/components/ai/KnowledgeRAGPanel";
import SpatialCanvas from "@/components/canvas/SpatialCanvas";
import CanvasControls from "@/components/canvas/CanvasControls";
import NodePopover from "@/components/canvas/NodePopover";
import DropZone from "@/components/canvas/DropZone";
import EmptyState from "@/components/canvas/EmptyState";
import CommandPalette from "@/components/ai/CommandPalette";

const SpatialCanvas3D = lazy(() => import("@/components/canvas/SpatialCanvas3D"));
const { loadBoundedPages } = paginate;

const MAX_GRAPH_OBJECTS = 10_000;
const MAX_GRAPH_RELATIONSHIPS = 20_000;

function Canvas3DFallback() {
  return (
    <div className="w-full h-full flex items-center justify-center" style={{ background: "linear-gradient(180deg, #f8f8fc 0%, #eeeeee 100%)" }}>
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-[var(--color-entity)] border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <div className="text-sm text-[var(--color-text-secondary)]">Loading 3D engine...</div>
      </div>
    </div>
  );
}

async function loadAllObjects(signal: AbortSignal) {
  const result = await loadBoundedPages<any>(
    ({ limit, offset, signal: requestSignal }) => api.listObjects(
      { limit, offset },
      requestSignal ? { signal: requestSignal } : undefined,
    ),
    "objects",
    500,
    MAX_GRAPH_OBJECTS,
    signal,
  );
  return { objects: result.items, total: result.total, truncated: result.truncated };
}

async function loadAllRelationships(signal: AbortSignal) {
  // The API caps each relationship page at 1,000 rows. Fetch bounded pages
  // rather than requesting 5,000 in one call or accumulating an unbounded graph.
  const result = await loadBoundedPages<any>(
    ({ limit, offset, signal: requestSignal }) => api.listRelationships(
      { limit, offset },
      requestSignal ? { signal: requestSignal } : undefined,
    ),
    "relationships",
    1000,
    MAX_GRAPH_RELATIONSHIPS,
    signal,
  );
  return { relationships: result.items, total: result.total, truncated: result.truncated };
}

function buildGraphNotice(
  objects: { objects: unknown[]; total: number | null; truncated: boolean },
  relationships: { relationships: unknown[]; total: number | null; truncated: boolean },
) {
  const limits: string[] = [];
  if (objects.truncated) {
    const total = objects.total === null
      ? "at least " + (objects.objects.length + 1).toLocaleString()
      : objects.total.toLocaleString();
    limits.push(objects.objects.length.toLocaleString() + " of " + total + " objects");
  }
  if (relationships.truncated) {
    const total = relationships.total === null
      ? "at least " + (relationships.relationships.length + 1).toLocaleString()
      : relationships.total.toLocaleString();
    limits.push(relationships.relationships.length.toLocaleString() + " of " + total + " relationships");
  }
  if (limits.length === 0) return null;
  return "Graph view is bounded to " + limits.join(" and ")
    + " to protect browser memory and rendering performance. All records remain in storage; use search to locate specific objects.";
}

export default function DataspacePage() {
  const setObjects = useSpatialStore((s) => s.setObjects);
  const setEdges = useSpatialStore((s) => s.setEdges);
  const viewMode = useSpatialStore((s) => s.viewMode);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);

  useKeyboard();

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    async function load() {
      setLoading(true);
      setError(null);
      setNotice(null);
      try {
        const [objsRes, relsRes] = await Promise.all([
          loadAllObjects(controller.signal),
          loadAllRelationships(controller.signal),
        ]);

        if (!active) return;

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

        const objects = (objsRes.objects || []).map((o: any) => ({
          id: o.id,
          type: typeMap[o.type] || "dataset",
          name: o.properties?.filename || o.properties?.name || o.id.slice(0, 8),
          properties: o.properties || {},
        }));

        const edges = (relsRes.relationships || []).flatMap((relationship: any) => {
          const edge = toGraphEdge(relationship);
          return edge ? [edge] : [];
        });

        setObjects(objects);
        setEdges(edges);
        setNotice(buildGraphNotice(objsRes, relsRes));
      } catch (err) {
        if (!active || controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "An unknown error occurred while loading the workspace.");
      } finally {
        if (active) setLoading(false);
      }
    }

    load();
    return () => {
      active = false;
      controller.abort();
    };
  }, [setObjects, setEdges, reloadKey]);

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <TopBar />
      <div className="flex-1 flex min-h-0">
        <Sidebar />
        <main className="flex-1 flex flex-col min-w-0 relative">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center z-10" role="status" aria-live="polite">
              <div className="glass rounded-xl px-6 py-4 flex items-center gap-3 animate-fade-in">
                <div className="w-5 h-5 border-2 border-[var(--color-dataset)] border-t-transparent rounded-full animate-spin" />
                <span className="text-sm text-[var(--color-text-secondary)]">Loading workspace...</span>
              </div>
            </div>
          )}

          {error && (
            <div className="absolute inset-0 flex items-center justify-center z-10" role="alert">
              <div className="glass rounded-xl px-6 py-5 max-w-md animate-fade-in">
                <div className="text-sm font-medium text-red-500 mb-1">Connection Error</div>
                <div className="text-xs text-[var(--color-text-secondary)]">{error}</div>
                <div className="text-[10px] text-[var(--color-text-tertiary)] mt-2">
                  Make sure the DataOS backend is running: python -m uvicorn backend.app:app --reload
                </div>
                <button
                  type="button"
                  onClick={() => setReloadKey((current) => current + 1)}
                  className="mt-4 inline-flex items-center justify-center rounded-lg px-4 py-2 text-xs font-semibold bg-[var(--color-entity)] text-white transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-entity)]"
                >
                  Try again
                </button>
              </div>
            </div>
          )}

          <div className="flex-1 relative overflow-hidden">
            {notice && (
              <div
                className="absolute top-3 left-3 right-3 z-20 mx-auto max-w-3xl glass rounded-lg px-4 py-3 text-xs text-[var(--color-text-secondary)] shadow-lg"
                role="status"
                aria-live="polite"
              >
                {notice}
              </div>
            )}
            {viewMode === "2d" ? <SpatialCanvas /> : (
              <Suspense fallback={<Canvas3DFallback />}>
                <SpatialCanvas3D />
              </Suspense>
            )}
            <NodePopover />
            <DropZone />
            <EmptyState />
            <CanvasControls />
          </div>

          <div className="h-[280px] shrink-0 min-h-0"><KnowledgeRAGPanel /></div>
        </main>
      </div>

      <CommandPalette />
    </div>
  );
}
