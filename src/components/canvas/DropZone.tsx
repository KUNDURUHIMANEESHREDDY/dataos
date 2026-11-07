"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { useSpatialStore } from "@/hooks/useSpatialStore";
import { ingestFiles } from "@/lib/ingestion";
import { loadDataspaceGraph } from "@/lib/dataspace-graph";
import { attachFileDropEvents } from "@/lib/file-drop-events.mjs";

interface DropZoneProps {
  targetRef: RefObject<HTMLDivElement | null>;
}

export default function DropZone({ targetRef }: DropZoneProps) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [lastResultIsError, setLastResultIsError] = useState(false);
  const inFlight = useRef(false);

  const processFiles = useCallback(async (files: File[]) => {
    if (inFlight.current || files.length === 0) return;

    inFlight.current = true;
    setUploading(true);
    setLastResult(null);
    setLastResultIsError(false);

    let successfulFiles = 0;
    let objectsCreated = 0;
    let relationsCreated = 0;
    const failures: string[] = [];
    const notices: string[] = [];

    try {
      const outcomes = await ingestFiles(
        files.map((file) => ({ filename: file.name, size: file.size, read: () => file.text() })),
      );
      for (const outcome of outcomes) {
        if (outcome.ok === true) {
          successfulFiles += 1;
          objectsCreated += outcome.objectsCreated;
          relationsCreated += outcome.relationsCreated;
        } else {
          failures.push(`${outcome.filename}: ${outcome.error}`);
        }
      }

      if (successfulFiles > 0) {
        try {
          const graph = await loadDataspaceGraph(new AbortController());
          useSpatialStore.getState().setObjects(graph.objects);
          useSpatialStore.getState().setEdges(graph.edges);
          if (graph.notice) notices.push(graph.notice);
        } catch (err) {
          failures.push(`Catalog refresh: ${err instanceof Error ? err.message : "request failed"}`);
        }
      }

      const summary = `Ingested ${successfulFiles} of ${files.length} files (${objectsCreated} objects, ${relationsCreated} relations).`;
      const details = [...failures, ...notices];
      setLastResult(details.length > 0 ? `${summary} ${details.join(" ")}` : summary);
      setLastResultIsError(failures.length > 0 || successfulFiles === 0);
    } catch (err) {
      setLastResult(err instanceof Error ? err.message : "File ingestion failed.");
      setLastResultIsError(true);
    } finally {
      inFlight.current = false;
      setUploading(false);
    }
  }, []);

  useEffect(() => {
    const target = targetRef.current;
    if (!target) return;

    return attachFileDropEvents(target, {
      onDragStateChange: setDragging,
      onFilesDrop: (files) => {
        void processFiles(files);
      },
    });
  }, [targetRef, processFiles]);

  return (
    <>
      <div
        className="absolute inset-0 z-30"
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
                CSV, JSON, Markdown, Notebooks, and more. Maximum 5 MiB per file.
              </div>
            </div>
          </div>
        )}
      </div>

      {uploading && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-50 pointer-events-auto">
          <div className="glass rounded-xl px-4 py-2 flex items-center gap-2 animate-slide-up">
            <div className="w-4 h-4 border-2 border-[var(--color-dataset)] border-t-transparent rounded-full animate-spin" />
            <span className="text-sm text-[var(--color-text-secondary)]">Ingesting...</span>
          </div>
        </div>
      )}

      {lastResult && !uploading && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-50 max-w-[min(90vw,40rem)] pointer-events-auto">
          <div
            role={lastResultIsError ? "alert" : "status"}
            aria-live={lastResultIsError ? "assertive" : "polite"}
            className="glass rounded-xl px-4 py-2 text-sm animate-slide-up flex items-center gap-3"
          >
            <span>{lastResult}</span>
            <button
              type="button"
              aria-label="Dismiss upload result"
              onClick={() => setLastResult(null)}
              className="shrink-0 rounded px-1 hover:bg-black/10 focus-visible:outline focus-visible:outline-2"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </>
  );
}
