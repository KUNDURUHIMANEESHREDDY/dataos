"use client";

import { useSpatialStore, ActivePanel } from "@/hooks/useSpatialStore";

const PANELS: { key: ActivePanel; label: string }[] = [
  { key: "inspector", label: "Inspector" },
  { key: "evidence", label: "Evidence" },
  { key: "lineage", label: "Lineage" },
  { key: "query", label: "Query" },
  { key: "analysis", label: "Analysis" },
  { key: "logs", label: "Logs" },
];

export default function BottomInspector() {
  const activePanel = useSpatialStore((s) => s.activePanel);
  const setActivePanel = useSpatialStore((s) => s.setActivePanel);
  const selectedIds = useSpatialStore((s) => s.selectedIds);
  const objects = useSpatialStore((s) => s.objects);

  const selectedObj = selectedIds.length === 1
    ? objects.find((o) => o.id === selectedIds[0])
    : null;

  return (
    <div className="glass-heavy border-t border-[var(--color-border-subtle)] flex flex-col h-48">
      <div className="flex items-center border-b border-[var(--color-border-subtle)] px-3">
        {PANELS.map((p) => (
          <button
            key={p.key}
            onClick={() => setActivePanel(p.key)}
            className={`px-3 py-2 text-xs font-medium transition-colors ${
              activePanel === p.key
                ? "text-[var(--color-dataset)] border-b-2 border-[var(--color-dataset)]"
                : "text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)]"
            }`}
          >
            {p.label}
          </button>
        ))}
        <div className="ml-auto text-[10px] text-[var(--color-text-tertiary)] font-mono">
          {selectedObj ? selectedObj.name : "No selection"}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {activePanel === "inspector" && <InspectorContent obj={selectedObj} />}
        {activePanel === "evidence" && <EvidenceContent obj={selectedObj} />}
        {activePanel === "lineage" && <LineageContent obj={selectedObj} />}
        {activePanel === "query" && <QueryContent />}
        {activePanel === "analysis" && <AnalysisContent obj={selectedObj} />}
        {activePanel === "logs" && <LogsContent />}
      </div>
    </div>
  );
}

function InspectorContent({ obj }: { obj: any }) {
  if (!obj) return <EmptyState message="Select an object to inspect" />;
  return (
    <div className="space-y-2 animate-fade-in">
      <div className="flex items-center gap-2 mb-3">
        <div
          className="w-3 h-3 rounded-full"
          style={{ background: `var(--color-${obj.type})` }}
        />
        <span className="font-display font-semibold text-sm">{obj.name}</span>
        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[rgba(0,0,0,0.04)] text-[var(--color-text-tertiary)]">
          {obj.type}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
        <div className="text-[var(--color-text-tertiary)]">ID</div>
        <div className="font-mono truncate">{obj.id.slice(0, 12)}...</div>
        {Object.entries(obj.properties || {}).slice(0, 10).map(([k, v]) => (
          <div key={k} className="contents">
            <div className="text-[var(--color-text-tertiary)] truncate">{k}</div>
            <div className="font-mono truncate">{String(v)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function EvidenceContent({ obj }: { obj: any }) {
  if (!obj) return <EmptyState message="Select an object to view evidence" />;
  const evidence = obj.properties?.evidence || obj.properties?.source_evidence || [];
  if (!Array.isArray(evidence) || evidence.length === 0) {
    return <EmptyState message="No evidence available" />;
  }
  return (
    <div className="space-y-2 animate-fade-in">
      {evidence.map((e: any, i: number) => (
        <div key={i} className="glass-inset rounded-lg p-2.5 text-xs">
          <div className="font-medium mb-1">{e.source || `Evidence ${i + 1}`}</div>
          <div className="text-[var(--color-text-secondary)]">{e.text || e.content || JSON.stringify(e)}</div>
          {e.confidence != null && (
            <div className="mt-1 text-[10px] text-[var(--color-text-tertiary)]">
              Confidence: {(e.confidence * 100).toFixed(1)}%
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function LineageContent({ obj }: { obj: any }) {
  if (!obj) return <EmptyState message="Select an object to view lineage" />;
  return (
    <div className="animate-fade-in text-xs text-[var(--color-text-secondary)]">
      <div className="glass-inset rounded-lg p-3">
        <div className="font-medium mb-2 text-[var(--color-text-primary)]">Lineage Graph</div>
        <div className="font-mono text-[10px] text-[var(--color-text-tertiary)]">
          Object: {obj.name} ({obj.id.slice(0, 8)})
          <br />
          Type: {obj.type}
          <br />
          Lineage tracing will show upstream sources and downstream consumers.
        </div>
      </div>
    </div>
  );
}

function QueryContent() {
  return (
    <div className="animate-fade-in">
      <div className="glass-inset rounded-lg p-3">
        <textarea
          className="w-full bg-transparent text-xs font-mono resize-none outline-none"
          placeholder="Enter SQL query..."
          rows={4}
        />
        <div className="flex justify-end mt-2">
          <button className="px-3 py-1 rounded-md bg-[var(--color-dataset)] text-white text-xs font-medium hover:opacity-90 transition-opacity">
            Run
          </button>
        </div>
      </div>
    </div>
  );
}

function AnalysisContent({ obj }: { obj: any }) {
  if (!obj) return <EmptyState message="Select an object for analysis" />;
  return (
    <div className="animate-fade-in text-xs text-[var(--color-text-secondary)]">
      <div className="glass-inset rounded-lg p-3">
        <div className="font-medium mb-1 text-[var(--color-text-primary)]">Analysis</div>
        <div className="font-mono text-[10px]">
          Schema matching, deduplication, and quality evaluation for: {obj.name}
        </div>
      </div>
    </div>
  );
}

function LogsContent() {
  return (
    <div className="animate-fade-in text-xs font-mono text-[var(--color-text-tertiary)] space-y-1">
      <div>[system] DataOS kernel initialized</div>
      <div>[system] Storage engine ready</div>
      <div>[system] Graph engine connected</div>
      <div>[info] Waiting for user interaction...</div>
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-full text-xs text-[var(--color-text-tertiary)]">
      {message}
    </div>
  );
}
