---
name: dataos-design-1
description: "DataOS Frontend Option 1: Command Center — dark, data-dense dashboard with real-time metrics, monospace typography, and a military/mission-control aesthetic. Best for power users who want maximum information density."
---

# Option 1: Command Center

A dark, data-dense interface inspired by mission control and NOC dashboards. Every pixel carries information. Zero decorative elements.

## Design Philosophy
> "The screen is a window into the system. Fill it with signal, not noise."

## Visual Identity

- **Palette:** Near-black backgrounds (#0a0a0f), electric blue (#00d4ff) primary, amber (#ffb800) warnings, red (#ff3b5c) errors, muted gray (#6b7280) secondary text
- **Typography:** JetBrains Mono for data/numbers, Inter for labels. Monospace everywhere numbers appear. Tabular lining figures for alignment.
- **Layout:** Fixed 12-column grid, no rounded corners below 4px, 1px borders using rgba(255,255,255,0.06)
- **Density:** Compact spacing (8px base), no wasted whitespace. Tables over cards. Data over decoration.

## Core Screens

### 1. System Overview (Home)
```
┌─────────────────────────────────────────────────────────┐
│ DATASPACE > Command Center              [status: LIVE] │
├──────────┬──────────┬──────────┬────────────────────────┤
│ OBJECTS  │ QUERIES  │ AGENTS   │ ALERTS                 │
│ 12,847   │ 1,203/hr │ 7 active │ 2 warnings             │
│ ▲ 3.2%   │ ▼ 0.8%  │ 3 idle   │                        │
├──────────┴──────────┴──────────┴────────────────────────┤
│ [Live query feed scrolling]                             │
│ 14:32:01 SELECT * FROM sales WHERE region = 'west'  23ms│
│ 14:32:01 INSERT INTO staging (id, data) VALUES ...  8ms │
│ 14:32:00 VACUUM ANALYZE completed                   1.2s│
├─────────────────────────────────────────────────────────┤
│ [System metrics sparklines: CPU | MEM | DISK | NET]     │
│ ▁▂▃▄▅▆▇█▇▆▅▄▃▂▁▂▃▄▅▆▇█▇▆▅▄▃▂▁▂▃▄▅▆▇█▇▆▅▄▃▂▁       │
└─────────────────────────────────────────────────────────┘
```

### 2. Object Explorer
- Three-panel: tree navigation | object detail | raw JSON/code
- Keyboard-first: `j/k` navigate, `Enter` opens, `Esc` closes, `/` searches
- Inline editing with vim-style modes (normal/insert)
- Diff view for version history with line-level highlighting

### 3. Query Console
- Split pane: SQL editor left, results table right, provenance graph below
- Auto-complete for table/column names from the catalog
- Query history sidebar with search
- Execution plan visualization (tree format, not graphical)
- Results export: CSV, JSON, Parquet with one click

### 4. Relationship Graph
- Force-directed layout with D3, zoomable
- Nodes: colored by object type, sized by relationship count
- Edges: labeled with relationship type, width = confidence
- Click node → sidebar shows full object detail
- Filter by type, confidence threshold, relationship type

### 5. Agent Monitor
- Real-time agent status grid
- Each agent card shows: role, current task, last action, resource usage
- Execution timeline (horizontal bars, like a Gantt chart)
- Click agent → full trace view with step-by-step provenance

## Component Patterns

### Status Badge
```jsx
<span className="inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-mono
  bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded">
  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
  ACTIVE
</span>
```

### Metric Card
```jsx
<div className="border border-white/6 bg-white/[0.02] p-3">
  <div className="text-[10px] uppercase tracking-widest text-gray-500 mb-1">Objects</div>
  <div className="text-2xl font-mono tabular-nums text-white">12,847</div>
  <div className="text-xs font-mono text-emerald-400 mt-1">▲ 3.2% from yesterday</div>
</div>
```

### Data Table
```jsx
<table className="w-full text-xs font-mono">
  <thead className="border-b border-white/6">
    <tr className="text-gray-500 uppercase tracking-wider">
      <th className="text-left py-2 px-3">ID</th>
      <th className="text-left py-2 px-3">TYPE</th>
      <th className="text-right py-2 px-3">SIZE</th>
    </tr>
  </thead>
  <tbody className="divide-y divide-white/[0.03]">
    {/* rows */}
  </tbody>
</table>
```

## Interactions
- **No modals.** Panels slide in from right (300ms spring, damping 1.0)
- **Keyboard shortcuts** visible in tooltips, `Cmd+K` command palette
- **Toast notifications** for background operations, bottom-right, auto-dismiss
- **Hover previews** for object references (like GitHub link previews)
- **No pagination** — infinite scroll with virtual list for large datasets

## Responsive
- Below 1024px: single-panel with breadcrumb navigation
- Below 768px: bottom sheet for details, swipe to dismiss
- No mobile-specific layout — this is a power-user tool

## Motion
- Sparkline animations: 200ms ease-out on data updates
- Panel transitions: spring with damping 1.0, response 0.3
- Number counters: animate from previous value over 300ms
- Graph layout: force simulation settles in 500ms
