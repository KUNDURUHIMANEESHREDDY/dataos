"use client";

import { useCallback, useState, useRef } from "react";
import { useSpatialStore } from "@/hooks/useSpatialStore";
import { api } from "@/lib/api";
import { ingestFiles } from "@/lib/ingestion";

export default function DropZone() {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [lastResultIsError, setLastResultIsError] = useState(false);
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
    setLastResultIsError(false);

    let successfulFiles = 0;
    let objectsCreated = 0;
    let relationsCreated = 0;
    const failures: string[] = [];

    try {
      const outcomes = await ingestFiles(
        files.map((file) => ({ filename: file.name, read: () => file.text() })),
      );
      for (const outcome of outcomes) {
        if (outcome.ok) {
          successfulFiles += 1;
          objectsCreated += outcome.objectsCreated;
          relationsCreated += outcome.relationsCreated;
        } else {
          failures.push(`${outcome.filename}: ${outcome.error}`);
        }
      }

      // Refresh after all files have settled so successful uploads remain visible
      // even when another file in the same drop was rejected.
      try {
        const [objsRes, relsRes] = await Promise.all([
          api.listObjects({ limit: 200 }),
          api.listRelationships({ limit: 500 }),
        ]);
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
      } catch (err) {
        failures.push(`Catalog refresh: ${err instanceof Error ? err.message : "request failed"}`);
      }

      const summary = `Ingested ${successfulFiles} of ${files.length} files (${objectsCreated} objects, ${relationsCreated} relations).`;
      setLastResult(failures.length > 0 ? `${summary} Failed: ${failures.join("; ")}` : summary);
      setLastResultIsError(failures.length > 0 || successfulFiles === 0);
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
        <div
          role={lastResultIsError ? "alert" : "status"}
          aria-live={lastResultIsError ? "assertive" : "polite"}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 z-50 max-w-[min(90vw,40rem)] glass rounded-xl px-4 py-2 text-sm animate-slide-up flex items-center gap-3"
        >
          <span>{lastResult}</span>
          <button
            type="button"
            aria-label="Dismiss upload result"
            onClick={() => setLastResult(null)}
            className="shrink-0 rounded px-1 hover:bg-black/10 focus-visible:outline focus-visible:outline-2"
          >
            ×
          </button>
        </div>
      )}
    </div>
  );
}
