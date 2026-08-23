"use client";

import { useCallback, useRef, useState, useEffect } from "react";
import { useSpatialStore, CanvasObject } from "@/hooks/useSpatialStore";

const NODE_RADIUS = 28;
const TYPE_COLORS: Record<string, string> = {
  source: "#0d9488",
  dataset: "#0d9488",
  entity: "#8b5cf6",
  relation: "#f59e0b",
  analysis: "#3b82f6",
  agent: "#ec4899",
};

interface NodePos {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

export default function SpatialCanvas() {
  const objects = useSpatialStore((s) => s.objects);
  const edges = useSpatialStore((s) => s.edges);
  const selectedIds = useSpatialStore((s) => s.selectedIds);
  const hoveredId = useSpatialStore((s) => s.hoveredId);
  const selectObject = useSpatialStore((s) => s.selectObject);
  const setHovered = useSpatialStore((s) => s.setHovered);
  const clearSelection = useSpatialStore((s) => s.clearSelection);
  const zoom = useSpatialStore((s) => s.zoom);
  const setZoom = useSpatialStore((s) => s.setZoom);
  const panX = useSpatialStore((s) => s.panX);
  const panY = useSpatialStore((s) => s.panY);
  const setPan = useSpatialStore((s) => s.setPan);

  const svgRef = useRef<SVGSVGElement>(null);
  const [nodePositions, setNodePositions] = useState<Record<string, NodePos>>({});
  const [isPanning, setIsPanning] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [draggingNode, setDraggingNode] = useState<string | null>(null);
  const animFrame = useRef<number>(0);

  // Force-directed layout
  useEffect(() => {
    if (objects.length === 0) return;

    const positions: Record<string, NodePos> = {};
    const w = 800;
    const h = 600;
    objects.forEach((obj, i) => {
      const angle = (i / objects.length) * Math.PI * 2;
      const r = Math.min(w, h) * 0.3;
      positions[obj.id] = {
        x: w / 2 + Math.cos(angle) * r,
        y: h / 2 + Math.sin(angle) * r,
        vx: 0,
        vy: 0,
      };
    });

    let iterations = 0;
    const maxIterations = 150;

    function step() {
      if (iterations >= maxIterations) return;
      iterations++;

      for (let i = 0; i < objects.length; i++) {
        for (let j = i + 1; j < objects.length; j++) {
          const a = positions[objects[i].id];
          const b = positions[objects[j].id];
          let dx = b.x - a.x;
          let dy = b.y - a.y;
          let dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = 8000 / (dist * dist);
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          a.vx -= fx;
          a.vy -= fy;
          b.vx += fx;
          b.vy += fy;
        }
      }

      edges.forEach((edge) => {
        const a = positions[edge.source];
        const b = positions[edge.target];
        if (!a || !b) return;
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = (dist - 120) * 0.005;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      });

      const cx = w / 2;
      const cy = h / 2;
      objects.forEach((obj) => {
        const p = positions[obj.id];
        p.vx += (cx - p.x) * 0.001;
        p.vy += (cy - p.y) * 0.001;
        p.vx *= 0.85;
        p.vy *= 0.85;
        p.x += p.vx;
        p.y += p.vy;
        p.x = Math.max(40, Math.min(w - 40, p.x));
        p.y = Math.max(40, Math.min(h - 40, p.y));
      });

      setNodePositions({ ...positions });
      animFrame.current = requestAnimationFrame(step);
    }

    animFrame.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(animFrame.current);
  }, [objects, edges]);

  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      const delta = -e.deltaY * 0.001;
      setZoom(zoom + delta);
    },
    [zoom, setZoom]
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === svgRef.current || (e.target as SVGElement).tagName === "rect") {
        setIsPanning(true);
        setDragStart({ x: e.clientX - panX, y: e.clientY - panY });
        clearSelection();
      }
    },
    [panX, panY, clearSelection]
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (draggingNode) {
        const svg = svgRef.current;
        if (!svg) return;
        const rect = svg.getBoundingClientRect();
        const x = (e.clientX - rect.left) / zoom - panX / zoom;
        const y = (e.clientY - rect.top) / zoom - panY / zoom;
        setNodePositions((prev) => ({
          ...prev,
          [draggingNode]: { ...prev[draggingNode], x, y, vx: 0, vy: 0 },
        }));
      } else if (isPanning) {
        setPan(e.clientX - dragStart.x, e.clientY - dragStart.y);
      }
    },
    [draggingNode, isPanning, dragStart, zoom, panX, panY, setPan]
  );

  const handleMouseUp = useCallback(() => {
    setIsPanning(false);
    setDraggingNode(null);
  }, []);

  const handleNodeClick = useCallback(
    (e: React.MouseEvent, id: string) => {
      e.stopPropagation();
      selectObject(id, e.metaKey || e.ctrlKey);
    },
    [selectObject]
  );

  return (
    <svg
      ref={svgRef}
      className="w-full h-full"
      style={{ background: "var(--color-canvas-bg)" }}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      <defs>
        <pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse">
          <circle cx="12" cy="12" r="0.5" fill="var(--color-canvas-grid)" />
        </pattern>
        <filter id="node-shadow" x="-50%" y="-50%" width="200%" height="200%">
          <feDropShadow dx="0" dy="2" stdDeviation="4" floodOpacity="0.1" />
        </filter>
        <filter id="node-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feDropShadow dx="0" dy="0" stdDeviation="8" floodOpacity="0.3" />
        </filter>
        <marker
          id="arrowhead"
          markerWidth="8"
          markerHeight="6"
          refX="8"
          refY="3"
          orient="auto"
        >
          <path d="M0,0 L8,3 L0,6" fill="rgba(0,0,0,0.2)" />
        </marker>
      </defs>

      <rect width="100%" height="100%" fill="url(#grid)" />

      <g transform={`translate(${panX},${panY}) scale(${zoom})`}>
        {edges.map((edge) => {
          const s = nodePositions[edge.source];
          const t = nodePositions[edge.target];
          if (!s || !t) return null;
          const isSelected =
            selectedIds.includes(edge.source) || selectedIds.includes(edge.target);
          return (
            <line
              key={edge.id}
              x1={s.x}
              y1={s.y}
              x2={t.x}
              y2={t.y}
              stroke={isSelected ? "rgba(13,148,136,0.6)" : "rgba(0,0,0,0.12)"}
              strokeWidth={isSelected ? 2 : 1}
              strokeDasharray={isSelected ? "none" : "4,4"}
              markerEnd="url(#arrowhead)"
              style={{ transition: "stroke 200ms, stroke-width 200ms" }}
            />
          );
        })}

        {objects.map((obj) => {
          const pos = nodePositions[obj.id];
          if (!pos) return null;
          const isSelected = selectedIds.includes(obj.id);
          const isHovered = hoveredId === obj.id;
          const color = TYPE_COLORS[obj.type] || "#666";
          return (
            <g
              key={obj.id}
              transform={`translate(${pos.x},${pos.y})`}
              onClick={(e) => handleNodeClick(e, obj.id)}
              onMouseEnter={() => setHovered(obj.id)}
              onMouseLeave={() => setHovered(null)}
              onMouseDown={(e) => {
                e.stopPropagation();
                setDraggingNode(obj.id);
              }}
              style={{ cursor: "grab" }}
            >
              <circle
                r={NODE_RADIUS}
                fill={color}
                opacity={isSelected ? 1 : 0.85}
                filter={isSelected ? "url(#node-glow)" : "url(#node-shadow)"}
                style={{
                  transition: "r 150ms, opacity 150ms",
                  r: isHovered ? NODE_RADIUS + 3 : NODE_RADIUS,
                }}
              />
              <text
                textAnchor="middle"
                dominantBaseline="middle"
                fill="white"
                fontSize="10"
                fontWeight="600"
                fontFamily="var(--font-display)"
                style={{ pointerEvents: "none" }}
              >
                {obj.name.slice(0, 4).toUpperCase()}
              </text>
              <text
                textAnchor="middle"
                y={NODE_RADIUS + 12}
                fill="var(--color-text-secondary)"
                fontSize="9"
                fontFamily="var(--font-body)"
                style={{ pointerEvents: "none" }}
              >
                {obj.name.length > 16 ? obj.name.slice(0, 14) + "..." : obj.name}
              </text>
              {isSelected && (
                <circle
                  r={NODE_RADIUS + 6}
                  fill="none"
                  stroke={color}
                  strokeWidth="2"
                  opacity="0.4"
                  style={{ animation: "pulse 2s infinite" }}
                />
              )}
            </g>
          );
        })}
      </g>
    </svg>
  );
}
