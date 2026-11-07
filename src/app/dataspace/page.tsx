"use client";

import { useEffect, useState, lazy, Suspense, useRef } from "react";
import { useSpatialStore } from "@/hooks/useSpatialStore";
import { loadDataspaceGraph } from "@/lib/dataspace-graph";
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

export default function DataspacePage() {
  const setObjects = useSpatialStore((s) => s.setObjects);
  const setEdges = useSpatialStore((s) => s.setEdges);
  const viewMode = useSpatialStore((s) => s.viewMode);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const canvasSurfaceRef = useRef<HTMLDivElement>(null);

  useKeyboard();

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    async function load() {
      setLoading(true);
      setError(null);
      setNotice(null);
      try {
        const graph = await loadDataspaceGraph(controller);
        if (!active) return;

        setObjects(graph.objects);
        setEdges(graph.edges);
        setNotice(graph.notice);
      } catch (err) {
        if (!active) return;
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

          <div ref={canvasSurfaceRef} className="flex-1 relative overflow-hidden">
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
            <DropZone targetRef={canvasSurfaceRef} />
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

