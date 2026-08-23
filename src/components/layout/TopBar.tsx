"use client";

import { useSpatialStore } from "@/hooks/useSpatialStore";

const TYPE_ICONS: Record<string, string> = {
  source: "🗄",
  dataset: "📊",
  entity: "🔮",
  relation: "🔗",
  analysis: "🧪",
  agent: "🤖",
};

export default function TopBar() {
  const setCommandPaletteOpen = useSpatialStore((s) => s.setCommandPaletteOpen);
  const setChatOpen = useSpatialStore((s) => s.setChatOpen);
  const viewMode = useSpatialStore((s) => s.viewMode);
  const setViewMode = useSpatialStore((s) => s.setViewMode);
  const selectedIds = useSpatialStore((s) => s.selectedIds);
  const objects = useSpatialStore((s) => s.objects);
  const objects_count = useSpatialStore((s) => s.objects.length);
  const edges_count = useSpatialStore((s) => s.edges.length);

  const selectedObj = selectedIds.length === 1 ? objects.find((o) => o.id === selectedIds[0]) : null;

  return (
    <header className="glass-heavy h-12 flex items-center px-4 gap-3 z-50 border-b border-[var(--color-border-subtle)]">
      {/* Logo */}
      <div className="flex items-center gap-2 shrink-0">
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[var(--color-dataset)] to-[var(--color-entity)] flex items-center justify-center shadow-sm">
          <span className="text-white text-xs font-bold font-display">D</span>
        </div>
        <span className="font-display font-semibold text-sm tracking-tight hidden sm:block">DataOS</span>
      </div>

      {/* Breadcrumbs */}
      <div className="hidden md:flex items-center gap-1 text-xs text-[var(--color-text-tertiary)] shrink-0">
        <span className="hover:text-[var(--color-text-secondary)] cursor-pointer transition-colors">Dataspace</span>
        {selectedObj && (
          <>
            <span className="opacity-40">/</span>
            <span className="text-[var(--color-text-secondary)]">
              {TYPE_ICONS[selectedObj.type] || ""} {selectedObj.name}
            </span>
          </>
        )}
      </div>

      {/* Search */}
      <div className="flex-1 max-w-md mx-auto">
        <button
          onClick={() => setCommandPaletteOpen(true)}
          className="w-full glass-input rounded-lg px-3 py-1.5 text-left text-sm text-[var(--color-text-tertiary)] cursor-pointer flex items-center gap-2 hover:border-[rgba(0,0,0,0.12)] transition-colors"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <path d="M21 21l-4.35-4.35" />
          </svg>
          <span>Search or ask a question...</span>
          <span className="ml-auto text-[10px] opacity-40 font-mono px-1.5 py-0.5 rounded bg-[rgba(0,0,0,0.04)]">⌘K</span>
        </button>
      </div>

      {/* Right controls */}
      <div className="flex items-center gap-1 shrink-0">
        {/* Stats pill */}
        <div className="hidden lg:flex items-center gap-2 text-[10px] font-mono text-[var(--color-text-tertiary)] px-2 py-1 rounded-md bg-[rgba(0,0,0,0.03)] mr-1">
          <span>{objects_count} obj</span>
          <span className="opacity-30">·</span>
          <span>{edges_count} rel</span>
        </div>

        {/* 2D/3D toggle */}
        <button
          onClick={() => setViewMode(viewMode === "2d" ? "3d" : "2d")}
          className="px-2 py-1 rounded-md text-xs font-mono text-[var(--color-text-secondary)] hover:bg-[rgba(0,0,0,0.04)] transition-colors"
          title={`Switch to ${viewMode === "2d" ? "3D" : "2D"} view (Space)`}
        >
          {viewMode === "2d" ? "2D" : "3D"}
        </button>

        {/* AI Chat */}
        <button
          onClick={() => setChatOpen(true)}
          className="p-1.5 rounded-md hover:bg-[rgba(0,0,0,0.04)] transition-colors text-[var(--color-text-secondary)]"
          title="AI Chat (⌘I)"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
          </svg>
        </button>
      </div>
    </header>
  );
}
