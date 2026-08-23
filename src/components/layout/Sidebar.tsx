"use client";

import React from "react";
import { useSpatialStore, ObjectType, SidebarTab } from "@/hooks/useSpatialStore";

const TABS: { key: SidebarTab; label: string; icon: React.ReactNode }[] = [
  {
    key: "sources",
    label: "Sources",
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <ellipse cx="12" cy="5" rx="9" ry="3" />
        <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
        <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
      </svg>
    ),
  },
  {
    key: "datasets",
    label: "Datasets",
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <path d="M3 9h18" />
        <path d="M3 15h18" />
        <path d="M9 3v18" />
      </svg>
    ),
  },
  {
    key: "entities",
    label: "Entities",
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="3" />
        <circle cx="5" cy="6" r="2" />
        <circle cx="19" cy="6" r="2" />
        <circle cx="5" cy="18" r="2" />
        <circle cx="19" cy="18" r="2" />
        <line x1="10" y1="10" x2="6.5" y2="7" />
        <line x1="14" y1="10" x2="17.5" y2="7" />
        <line x1="10" y1="14" x2="6.5" y2="17" />
        <line x1="14" y1="14" x2="17.5" y2="17" />
      </svg>
    ),
  },
  {
    key: "relations",
    label: "Relations",
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" />
        <path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" />
      </svg>
    ),
  },
  {
    key: "agents",
    label: "Agents",
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 2a4 4 0 014 4v2a4 4 0 01-8 0V6a4 4 0 014-4z" />
        <path d="M16 14H8a4 4 0 00-4 4v2h16v-2a4 4 0 00-4-4z" />
        <circle cx="12" cy="6" r="1" fill="currentColor" />
      </svg>
    ),
  },
];

const TYPE_COLORS: Record<ObjectType, string> = {
  source: "var(--color-dataset)",
  dataset: "var(--color-dataset)",
  entity: "var(--color-entity)",
  relation: "var(--color-relationship)",
  analysis: "var(--color-analysis)",
  agent: "var(--color-agent)",
};

const TYPE_SOFT_COLORS: Record<ObjectType, string> = {
  source: "var(--color-dataset-soft)",
  dataset: "var(--color-dataset-soft)",
  entity: "var(--color-entity-soft)",
  relation: "var(--color-relationship-soft)",
  analysis: "var(--color-analysis-soft)",
  agent: "var(--color-agent-soft)",
};

export default function Sidebar() {
  const sidebarOpen = useSpatialStore((s) => s.sidebarOpen);
  const sidebarTab = useSpatialStore((s) => s.sidebarTab);
  const setSidebarTab = useSpatialStore((s) => s.setSidebarTab);
  const objects = useSpatialStore((s) => s.objects);
  const selectedIds = useSpatialStore((s) => s.selectedIds);
  const selectObject = useSpatialStore((s) => s.selectObject);
  const toggleSidebar = useSpatialStore((s) => s.toggleSidebar);

  if (!sidebarOpen) return null;

  const tabObjects = objects.filter((o) => {
    if (sidebarTab === "sources") return o.type === "source";
    if (sidebarTab === "datasets") return o.type === "dataset";
    if (sidebarTab === "entities") return o.type === "entity";
    if (sidebarTab === "relations") return o.type === "relation";
    if (sidebarTab === "agents") return o.type === "agent";
    return true;
  });

  return (
    <aside className="glass w-56 flex flex-col border-r border-[var(--color-border-subtle)] shrink-0">
      <div className="flex border-b border-[var(--color-border-subtle)]">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setSidebarTab(tab.key)}
            className={`flex-1 py-2 flex flex-col items-center gap-0.5 text-[10px] transition-colors ${
              sidebarTab === tab.key
                ? "text-[var(--color-dataset)] border-b-2 border-[var(--color-dataset)]"
                : "text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)]"
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
        {tabObjects.length === 0 && (
          <div className="text-center text-xs text-[var(--color-text-tertiary)] py-8">
            No {sidebarTab} found
          </div>
        )}
        {tabObjects.map((obj) => (
          <button
            key={obj.id}
            onClick={() => selectObject(obj.id)}
            className={`w-full text-left px-2.5 py-2 rounded-lg text-sm transition-all ${
              selectedIds.includes(obj.id)
                ? "bg-[rgba(0,0,0,0.06)] font-medium"
                : "hover:bg-[rgba(0,0,0,0.03)]"
            }`}
          >
            <div className="flex items-center gap-2">
              <div
                className="w-2 h-2 rounded-full shrink-0"
                style={{ background: TYPE_COLORS[obj.type] }}
              />
              <span className="truncate">{obj.name}</span>
            </div>
            {obj.properties?.schema && (
              <div className="text-[10px] text-[var(--color-text-tertiary)] mt-0.5 ml-4 font-mono truncate">
                {obj.properties.schema}
              </div>
            )}
          </button>
        ))}
      </div>

      <div className="p-2 border-t border-[var(--color-border-subtle)]">
        <div className="text-[10px] text-[var(--color-text-tertiary)] text-center font-mono">
          {objects.length} objects · {tabObjects.length} shown
        </div>
      </div>
    </aside>
  );
}
