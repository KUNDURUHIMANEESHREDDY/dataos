"use client";

import { useSpatialStore } from "@/hooks/useSpatialStore";

export default function CanvasControls() {
  const zoom = useSpatialStore((s) => s.zoom);
  const setZoom = useSpatialStore((s) => s.setZoom);
  const setPan = useSpatialStore((s) => s.setPan);
  const viewMode = useSpatialStore((s) => s.viewMode);
  const setViewMode = useSpatialStore((s) => s.setViewMode);
  const objects = useSpatialStore((s) => s.objects);

  return (
    <div className="absolute bottom-4 right-4 flex flex-col items-center gap-1 animate-slide-up">
      <div className="glass rounded-xl p-1 flex flex-col gap-0.5">
        <button
          onClick={() => setZoom(zoom + 0.15)}
          className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--color-text-secondary)] hover:bg-[rgba(0,0,0,0.05)] transition-colors text-lg"
          title="Zoom in"
        >
          +
        </button>
        <div className="text-[10px] text-center text-[var(--color-text-tertiary)] font-mono py-0.5">
          {Math.round(zoom * 100)}%
        </div>
        <button
          onClick={() => setZoom(zoom - 0.15)}
          className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--color-text-secondary)] hover:bg-[rgba(0,0,0,0.05)] transition-colors text-lg"
          title="Zoom out"
        >
          −
        </button>
        <div className="border-t border-[var(--color-border-subtle)] my-0.5" />
        <button
          onClick={() => {
            setZoom(1);
            setPan(0, 0);
          }}
          className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--color-text-secondary)] hover:bg-[rgba(0,0,0,0.05)] transition-colors"
          title="Reset view"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M15 3h6v6" />
            <path d="M9 21H3v-6" />
            <path d="M21 3l-7 7" />
            <path d="M3 21l7-7" />
          </svg>
        </button>
      </div>

      <div className="glass rounded-xl p-1 mt-1 flex flex-col gap-0.5">
        <button
          onClick={() => setViewMode("2d")}
          className={`w-8 h-8 rounded-lg flex items-center justify-center text-[10px] font-mono transition-colors ${
            viewMode === "2d"
              ? "bg-[var(--color-dataset)] text-white"
              : "text-[var(--color-text-secondary)] hover:bg-[rgba(0,0,0,0.05)]"
          }`}
          title="2D view"
        >
          2D
        </button>
        <button
          onClick={() => setViewMode("3d")}
          className={`w-8 h-8 rounded-lg flex items-center justify-center text-[10px] font-mono transition-colors ${
            viewMode === "3d"
              ? "bg-[var(--color-entity)] text-white"
              : "text-[var(--color-text-secondary)] hover:bg-[rgba(0,0,0,0.05)]"
          }`}
          title="3D view"
        >
          3D
        </button>
      </div>

      <div className="glass rounded-xl px-2 py-1 mt-1 text-[10px] text-[var(--color-text-tertiary)] font-mono">
        {objects.length} nodes
      </div>
    </div>
  );
}
