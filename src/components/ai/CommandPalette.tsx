"use client";

import { useState, useEffect, useRef } from "react";
import { useSpatialStore } from "@/hooks/useSpatialStore";
import { api } from "@/lib/api";

export default function CommandPalette() {
  const open = useSpatialStore((s) => s.commandPaletteOpen);
  const setOpen = useSpatialStore((s) => s.setCommandPaletteOpen);
  const objects = useSpatialStore((s) => s.objects);
  const selectObject = useSpatialStore((s) => s.selectObject);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<any[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setResults([]);
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      return;
    }
    const q = query.toLowerCase();
    const matched = objects
      .filter(
        (o) =>
          o.name.toLowerCase().includes(q) ||
          o.type.toLowerCase().includes(q) ||
          o.id.toLowerCase().includes(q)
      )
      .slice(0, 8);
    setResults(matched);
    setSelectedIndex(0);
  }, [query, objects]);

  function handleSelect(obj: any) {
    selectObject(obj.id);
    setOpen(false);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      setOpen(false);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && results[selectedIndex]) {
      handleSelect(results[selectedIndex]);
    }
  }

  if (!open) return null;

  const TYPE_COLORS: Record<string, string> = {
    source: "var(--color-dataset)",
    dataset: "var(--color-dataset)",
    entity: "var(--color-entity)",
    relation: "var(--color-relationship)",
    analysis: "var(--color-analysis)",
    agent: "var(--color-agent)",
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh]"
      onClick={() => setOpen(false)}
    >
      <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" />
      <div
        className="glass-heavy rounded-2xl w-full max-w-lg overflow-hidden animate-scale-in relative"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--color-border-subtle)]">
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--color-text-tertiary)"
            strokeWidth="2"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="M21 21l-4.35-4.35" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search objects, run commands..."
            className="flex-1 bg-transparent outline-none text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)]"
          />
          <span className="text-[10px] font-mono text-[var(--color-text-tertiary)] px-1.5 py-0.5 rounded bg-[rgba(0,0,0,0.04)]">
            ESC
          </span>
        </div>

        {results.length > 0 && (
          <div className="max-h-64 overflow-y-auto py-1">
            {results.map((obj, i) => (
              <button
                key={obj.id}
                onClick={() => handleSelect(obj)}
                className={`w-full text-left px-4 py-2.5 flex items-center gap-3 transition-colors ${
                  i === selectedIndex
                    ? "bg-[rgba(0,0,0,0.05)]"
                    : "hover:bg-[rgba(0,0,0,0.03)]"
                }`}
              >
                <div
                  className="w-2.5 h-2.5 rounded-full shrink-0"
                  style={{ background: TYPE_COLORS[obj.type] }}
                />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{obj.name}</div>
                  <div className="text-[10px] text-[var(--color-text-tertiary)] font-mono">
                    {obj.type} · {obj.id.slice(0, 8)}
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}

        {query && results.length === 0 && (
          <div className="px-4 py-6 text-center text-sm text-[var(--color-text-tertiary)]">
            No results for &ldquo;{query}&rdquo;
          </div>
        )}

        {!query && (
          <div className="px-4 py-4 text-xs text-[var(--color-text-tertiary)]">
            <div className="font-medium mb-2 text-[var(--color-text-secondary)]">Quick actions</div>
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-[rgba(0,0,0,0.04)]">⌘/</span>
                <span>Toggle sidebar</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-[rgba(0,0,0,0.04)]">⌘I</span>
                <span>Open AI chat</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-[rgba(0,0,0,0.04)]">Space</span>
                <span>Toggle 2D/3D view</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
