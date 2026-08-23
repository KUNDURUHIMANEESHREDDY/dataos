"use client";

import { useSpatialStore } from "@/hooks/useSpatialStore";
import { api } from "@/lib/api";
import { useState } from "react";

export default function EmptyState() {
  const objects = useSpatialStore((s) => s.objects);
  const setObjects = useSpatialStore((s) => s.setObjects);
  const setEdges = useSpatialStore((s) => s.setEdges);
  const [ingesting, setIngesting] = useState(false);

  if (objects.length > 0) return null;

  async function loadSampleData() {
    setIngesting(true);
    try {
      // Create sample datasets
      const sampleCSV = `id,name,department,salary,join_date
1,Alice Johnson,Engineering,95000,2021-03-15
2,Bob Smith,Marketing,72000,2020-07-22
3,Carol Williams,Engineering,105000,2019-01-10
4,David Brown,Sales,68000,2022-05-30
5,Eva Davis,Marketing,78000,2021-11-04`;

      const sampleJSON = `{"product":"Widget A","category":"Electronics","price":29.99,"stock":150}`;

      const sampleMD = `# Q4 Revenue Report\n\nTotal revenue: $2.4M\nGrowth: +18% YoY\n\n## Key Drivers\n- New enterprise deals\n- Expansion in APAC region`;

      await Promise.all([
        fetch("/api/ingest/universal", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({ filename: "employees.csv", content: sampleCSV, discover_relations: "true" }),
        }),
        fetch("/api/ingest/universal", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({ filename: "products.json", content: sampleJSON, discover_relations: "true" }),
        }),
        fetch("/api/ingest/universal", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({ filename: "q4_report.md", content: sampleMD, discover_relations: "true" }),
        }),
      ]);

      // Refresh
      const [objsRes, relsRes] = await Promise.all([
        api.listObjects({ limit: 200 }),
        api.listRelationships({ limit: 500 }),
      ]);
      const typeMap: Record<string, string> = {
        document: "dataset", dataset: "dataset", csv: "dataset",
        entity: "entity", relation: "relation", analysis: "analysis",
        notebook: "analysis", agent: "agent",
      };
      const objs = (objsRes.objects || []).map((o: any) => ({
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
      setObjects(objs);
      setEdges(edges);
    } catch (err) {
      console.error("Failed to load sample data:", err);
    } finally {
      setIngesting(false);
    }
  }

  return (
    <div className="absolute inset-0 flex items-center justify-center z-20 pointer-events-none">
      <div className="glass-heavy rounded-2xl p-8 max-w-md text-center pointer-events-auto animate-scale-in">
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-[var(--color-dataset)] to-[var(--color-entity)] flex items-center justify-center mx-auto mb-5 shadow-lg">
          <span className="text-white text-2xl font-bold font-display">D</span>
        </div>

        <h2 className="font-display font-bold text-lg mb-2">Welcome to DataOS</h2>
        <p className="text-sm text-[var(--color-text-secondary)] mb-6 leading-relaxed">
          Your universal data operating system. Drag files onto the canvas to ingest them,
          or load sample data to explore.
        </p>

        <div className="space-y-3">
          <button
            onClick={loadSampleData}
            disabled={ingesting}
            className="w-full px-4 py-2.5 rounded-xl bg-gradient-to-r from-[var(--color-dataset)] to-[var(--color-entity)] text-white text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {ingesting ? (
              <>
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Loading sample data...
              </>
            ) : (
              <>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                  <polyline points="17,8 12,3 7,8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
                Load Sample Data
              </>
            )}
          </button>

          <div className="text-xs text-[var(--color-text-tertiary)]">
            or drag &amp; drop files onto the canvas
          </div>
        </div>

        <div className="mt-6 pt-4 border-t border-[var(--color-border-subtle)] grid grid-cols-3 gap-3 text-[10px] text-[var(--color-text-tertiary)]">
          <div>
            <div className="font-mono text-[var(--color-dataset)] mb-0.5">⌘K</div>
            Command palette
          </div>
          <div>
            <div className="font-mono text-[var(--color-entity)] mb-0.5">⌘I</div>
            AI chat
          </div>
          <div>
            <div className="font-mono text-[var(--color-analysis)] mb-0.5">Space</div>
            Toggle 2D/3D
          </div>
        </div>
      </div>
    </div>
  );
}
