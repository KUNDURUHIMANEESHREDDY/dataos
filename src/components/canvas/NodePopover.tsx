"use client";

import { useSpatialStore } from "@/hooks/useSpatialStore";

const TYPE_COLORS: Record<string, string> = {
  source: "#0d9488",
  dataset: "#0d9488",
  entity: "#8b5cf6",
  relation: "#f59e0b",
  analysis: "#3b82f6",
  agent: "#ec4899",
};

const TYPE_LABELS: Record<string, string> = {
  source: "Source",
  dataset: "Dataset",
  entity: "Entity",
  relation: "Relation",
  analysis: "Analysis",
  agent: "Agent",
};

export default function NodePopover() {
  const hoveredId = useSpatialStore((s) => s.hoveredId);
  const objects = useSpatialStore((s) => s.objects);
  const edges = useSpatialStore((s) => s.edges);

  if (!hoveredId) return null;
  const obj = objects.find((o) => o.id === hoveredId);
  if (!obj) return null;

  const connections = edges.filter((e) => e.source === obj.id || e.target === obj.id);
  const color = TYPE_COLORS[obj.type] || "#666";

  return (
    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-40 pointer-events-none animate-slide-down">
      <div className="glass-heavy rounded-xl px-4 py-3 min-w-[240px] max-w-[320px]">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-3 h-3 rounded-full" style={{ background: color }} />
          <span className="font-display font-semibold text-sm">{obj.name}</span>
          <span
            className="text-[10px] font-mono px-1.5 py-0.5 rounded-full"
            style={{ background: `${color}18`, color }}
          >
            {TYPE_LABELS[obj.type] || obj.type}
          </span>
        </div>

        <div className="space-y-1 text-xs text-[var(--color-text-secondary)]">
          <div className="flex justify-between">
            <span>ID</span>
            <span className="font-mono text-[10px]">{obj.id.slice(0, 10)}...</span>
          </div>
          <div className="flex justify-between">
            <span>Connections</span>
            <span className="font-mono">{connections.length}</span>
          </div>
          {obj.properties?.schema && (
            <div className="flex justify-between">
              <span>Schema</span>
              <span className="font-mono text-[10px] truncate ml-2">{obj.properties.schema}</span>
            </div>
          )}
          {obj.properties?.row_count != null && (
            <div className="flex justify-between">
              <span>Rows</span>
              <span className="font-mono">{obj.properties.row_count}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
