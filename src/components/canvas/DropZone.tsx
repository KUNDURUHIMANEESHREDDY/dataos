"use client";

import { useCallback, useState, useRef } from "react";
import { useSpatialStore } from "@/hooks/useSpatialStore";
import { api } from "@/lib/api";

export default function DropZone() {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const counter = useRef(0);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    counter.current++;
    setDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    counter.current--;
    if (counter.current === 0) setDragging(false);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    counter.current = 0;
    setDragging(false);

    const files = Array.from(e.dataTransfer.files);
    if (files.length === 0) return;

    setUploading(true);
    setLastResult(null);

    try {
      for (const file of files) {
        const text = await file.text();
        const res = await fetch("/api/ingest/universal", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({
            filename: file.name,
            content: text,
            discover_relations: "true",
          }),
        });
        const data = await res.json();
        setLastResult(`Ingested ${file.name}: ${data.objects_created || 0} objects, ${data.relations_created || 0} relations`);
      }
      // Refresh the store
      const objsRes = await api.listObjects({ limit: 200 });
      const relsRes = await api.listRelationships({ limit: 500 });
      const typeMap: Record<string, string> = {
        document: "dataset", dataset: "dataset", csv: "dataset",
        entity: "entity", relation: "relation", analysis: "analysis",
        notebook: "analysis", agent: "agent",
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
      useSpatialStore.getState().setObjects(objects);
      useSpatialStore.getState().setEdges(edges);
    } catch (err: any) {
      setLastResult(`Error: ${err.message}`);
    } finally {
      setUploading(false);
    }
  }, []);

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className="absolute inset-0 z-30 pointer-events-auto"
      style={{ pointerEvents: dragging ? "auto" : "none" }}
    >
      {dragging && (
        <div className="absolute inset-0 bg-[rgba(13,148,136,0.08)] backdrop-blur-sm border-2 border-dashed border-[var(--color-dataset)] rounded-lg m-2 flex items-center justify-center animate-fade-in">
          <div className="text-center">
            <div className="w-12 h-12 rounded-full bg-[var(--color-dataset-soft)] flex items-center justify-center mx-auto mb-3">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--color-dataset)" strokeWidth="2">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                <polyline points="17,8 12,3 7,8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
            </div>
            <div className="font-display font-semibold text-sm text-[var(--color-dataset)]">
              Drop files to ingest
            </div>
            <div className="text-xs text-[var(--color-text-secondary)] mt-1">
              CSV, JSON, Markdown, Notebooks, and more
            </div>
          </div>
        </div>
      )}

      {uploading && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-50">
          <div className="glass rounded-xl px-4 py-2 flex items-center gap-2 animate-slide-up">
            <div className="w-4 h-4 border-2 border-[var(--color-dataset)] border-t-transparent rounded-full animate-spin" />
            <span className="text-sm text-[var(--color-text-secondary)]">Ingesting...</span>
          </div>
        </div>
      )}

      {lastResult && !uploading && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-50">
          <div
            className="glass rounded-xl px-4 py-2 text-sm animate-slide-up cursor-pointer"
            onClick={() => setLastResult(null)}
          >
            {lastResult}
          </div>
        </div>
      )}
    </div>
  );
}
