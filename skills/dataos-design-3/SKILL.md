---
name: dataos-design-3
description: "DataOS Frontend Option 3: Notebook Canvas — Jupyter-inspired, cell-based interface where every interaction is a document. Code, data, visualization, and narrative coexist. Best for data scientists and analysts."
---

# Option 3: Notebook Canvas

A notebook-first interface where data exploration happens in documents, not dashboards. Every query, visualization, and analysis lives in a shareable, versionable notebook cell.

## Design Philosophy
> "The best interface for data is a document you can think in."

## Visual Identity

- **Palette:** Warm white (#fefdf8) background, rich black (#1a1a1a) text, indigo (#4f46e5) primary, amber (#d97706) for execution state, green (#16a34a) for outputs
- **Typography:** Literata for prose/markdown cells, JetBrains Mono for code, IBM Plex Sans for UI chrome. Distinct typographic roles for each cell type.
- **Layout:** Centered column (720px max), generous vertical rhythm (24px between cells), sidebar for navigation
- **Surfaces:** Minimal — paper metaphor. Subtle left border for cell state (blue = editing, green = executed, amber = running)

## Core Screens

### 1. Notebook View (Primary)
```
┌─────────────────────────────────────────────────────────┐
│ ▸ Notebooks / sales-analysis-q4 / v3           [Share] │
├──────┬──────────────────────────────────────────────────┤
│      │                                                  │
│  ◉   │  # Q4 Sales Analysis                            │
│      │  Sales grew 15% YoY across all regions...       │
│  ○   │                                                  │
│      │  ──────────────────────────────────────────────  │
│  ○   │  ▸ [Code Cell] Ingest data                      │
│      │    dataos.ingest("sales_q4.csv")                │
│  ◉   │    ✓ 2,400 rows ingested (0.3s)                 │
│      │                                                  │
│  ○   │  ──────────────────────────────────────────────  │
│      │  ▸ [SQL Cell] Revenue by region                  │
│  ○   │    SELECT region, SUM(revenue) as total          │
│      │    FROM sales GROUP BY region                    │
│      │    ┌────────┬──────────┐                         │
│      │    │ region │ total    │                         │
│      │    ├────────┼──────────┤                         │
│      │    │ West   │ $1.2M    │                         │
│      │    │ East   │ $980K    │                         │
│      │    └────────┴──────────┘                         │
│      │                                                  │
│  ○   │  ──────────────────────────────────────────────  │
│      │  ▸ [Viz Cell] Bar chart                          │
│      │    [Rendered bar chart]                          │
│      │                                                  │
└──────┴──────────────────────────────────────────────────┘
```

### 2. Cell Types
- **Markdown:** Prose, headings, LaTeX, embedded images. Edit in-place with preview.
- **Code:** Python execution with DataOS API. Syntax highlighting, auto-complete, error diffs.
- **SQL:** Direct query against registered datasets. Results as inline tables.
- **Visualization:** Declarative chart specs. Auto-suggest chart type based on data shape.
- **Evidence:** Linked source objects with inline previews and provenance chains.
- **Output:** Streaming text output (like Jupyter stdout), error tracebacks, execution logs.

### 3. Object Browser (Sidebar)
- Hierarchical tree: by type, by source, by date
- Drag objects into notebook as reference cells
- Preview on hover, full detail on click
- Search with type-ahead filtering

### 4. Version History
- Timeline view on right sidebar
- Each version shows diff summary
- Click to view full notebook at that version
- Restore/branch/compare actions
- Git-style commit messages

### 5. Share & Publish
- Share with specific users or teams
- Read-only mode for viewers
- Export as: notebook (.ipynb), HTML report, PDF, Markdown
- Public link with time-limited access
- Comments on individual cells

## Component Patterns

### Cell Container
```jsx
<div className={`group relative border-l-2 pl-4 ${
  state === 'editing' ? 'border-indigo-500' :
  state === 'running' ? 'border-amber-500 animate-pulse' :
  state === 'success' ? 'border-green-500' :
  'border-transparent hover:border-gray-200'
}`}>
  <div className="absolute -left-3 top-1 opacity-0 group-hover:opacity-100 transition-opacity">
    <GripVertical className="w-4 h-4 text-gray-300 cursor-grab" />
  </div>
  {children}
</div>
```

### Code Cell
```jsx
<div className="bg-gray-50 rounded-lg border border-gray-200 overflow-hidden">
  <div className="flex items-center justify-between px-3 py-1.5 border-b border-gray-200
    bg-gray-100/50">
    <span className="text-xs text-gray-400 font-mono">python</span>
    <button className="text-xs text-indigo-500 hover:text-indigo-600">▶ Run</button>
  </div>
  <pre className="p-3 text-sm font-mono overflow-x-auto">
    <code>{code}</code>
  </pre>
</div>
```

### Results Table
```jsx
<div className="overflow-x-auto border border-gray-200 rounded-lg">
  <table className="w-full text-sm">
    <thead className="bg-gray-50 text-left">
      <tr>{columns.map(col => <th key={col} className="px-3 py-2 font-medium">{col}</th>)}</tr>
    </thead>
    <tbody className="divide-y divide-gray-100">
      {rows.map((row, i) => (
        <tr key={i} className="hover:bg-gray-50/50">
          {columns.map(col => <td key={col} className="px-3 py-1.5 font-mono text-xs">{row[col]}</td>)}
        </tr>
      ))}
    </tbody>
  </table>
</div>
```

## Interactions
- **Cell editing:** click to focus, `Shift+Enter` to run and move down, `Cmd+Enter` to run in place
- **Cell operations:** `M` for markdown, `Y` for code, `A`/`B` to insert above/below (vim-style)
- **Drag to reorder** cells with visual feedback
- **Command palette:** `Cmd+Shift+P` for all cell operations
- **Auto-save** every 5 seconds, manual save with `Cmd+S`
- **Inline results** — no separate results panel, everything renders in the cell

## Responsive
- Below 1024px: sidebar collapses to icons
- Below 768px: full-width cells, bottom toolbar
- Below 480px: simplified cell toolbar, swipe to delete

## Motion
- Cell execution: amber pulse during run, green flash on success
- Results appear: fade-in with slight downward slide (150ms)
- Cell reorder: smooth drag with spring snap (damping 1.0)
- Version diff: cross-fade between versions (200ms)
