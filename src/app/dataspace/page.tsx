"use client";

import { useEffect, useState, lazy, Suspense } from "react";
import { useSpatialStore } from "@/hooks/useSpatialStore";
import { api } from "@/lib/api";
import { useKeyboard } from "@/hooks/useKeyboard";
import TopBar from "@/components/layout/TopBar";
import Sidebar from "@/components/layout/Sidebar";
import BottomInspector from "@/components/layout/BottomInspector";
import SpatialCanvas from "@/components/canvas/SpatialCanvas";
import CanvasControls from "@/components/canvas/CanvasControls";
import NodePopover from "@/components/canvas/NodePopover";
import DropZone from "@/components/canvas/DropZone";
import EmptyState from "@/components/canvas/EmptyState";
import CommandPalette from "@/components/ai/CommandPalette";
import ChatPanel from "@/components/ai/ChatPanel";

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

  useKeyboard();

  useEffect(() => {
    async function load() {
      try {
        const [objsRes, relsRes] = await Promise.all([
          api.listObjects({ limit: 200 }),
          api.listRelationships({ limit: 500 }),
        ]);

        const typeMap: Record<string, string> = {
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

        const edges = (relsRes.relationships || []).map((r: any) => ({
          id: r.id || `${r.source_id}-${r.target_id}`,
          source: r.source_id,
          target: r.target_id,
          type: r.relation_type || "related_to",
          confidence: r.confidence || 1.0,
        }));

        setObjects(objects);
        setEdges(edges);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [setObjects, setEdges]);

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <TopBar />
      <div className="flex-1 flex min-h-0">
        <Sidebar />
        <main className="flex-1 flex flex-col min-w-0 relative">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center z-10">
              <div className="glass rounded-xl px-6 py-4 flex items-center gap-3 animate-fade-in">
                <div className="w-5 h-5 border-2 border-[var(--color-dataset)] border-t-transparent rounded-full animate-spin" />
                <span className="text-sm text-[var(--color-text-secondary)]">Loading workspace...</span>
              </div>
            </div>
          )}

          {error && (
            <div className="absolute inset-0 flex items-center justify-center z-10">
              <div className="glass rounded-xl px-6 py-4 max-w-md animate-fade-in">
                <div className="text-sm font-medium text-red-500 mb-1">Connection Error</div>
                <div className="text-xs text-[var(--color-text-secondary)]">{error}</div>
                <div className="text-[10px] text-[var(--color-text-tertiary)] mt-2">
                  Make sure the DataOS backend is running: python -m uvicorn backend.app:app --reload
                </div>
              </div>
            </div>
          )}

          <div className="flex-1 relative overflow-hidden">
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

          <BottomInspector />
        </main>
      </div>

      <CommandPalette />
      <ChatPanel />
    </div>
  );
}
