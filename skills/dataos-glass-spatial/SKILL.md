---
name: dataos-glass-spatial
description: "DataOS Frontend — Unified Glass Studio + Spatial OS design. Translucent glass UI over a spatial data canvas. Intelligent view switching. Command palette + AI chat layer."
---

# DataOS Frontend: Glass + Spatial

The canonical frontend design. Combines Glass Studio visual language with Spatial OS interaction paradigm, plus Command Center power-user tools and Conversational AI layer.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ TopBar: logo | breadcrumbs | search (Cmd+K) | AI status    │
├──────────────┬───────────────────────────────────────────────┤
│              │                                               │
│  Sidebar     │              SPATIAL CANVAS                   │
│  (glass)     │                                               │
│              │       ╭──────────╮       ╭──────────╮        │
│  Sources     │       │ Dataset  │──────▶│ Dataset  │        │
│  Datasets    │       ╰──────────╯       ╰──────────╯        │
│  Entities    │              │                    │           │
│  Relations   │              ▼                    ▼           │
│  Agents      │       ╭──────────╮       ╭──────────╮        │
│              │       │ Entity   │       │ Analysis │        │
│              │       ╰──────────╯       ╰──────────╯        │
│              │                                               │
├──────────────┴───────────────────────────────────────────────┤
│ Bottom Inspector (collapsible):                              │
│ [Inspector] [Evidence] [Lineage] [Query] [Analysis] [Logs]  │
└──────────────────────────────────────────────────────────────┘
```

## View Switching Intelligence

The canvas changes representation based on what's selected:

| Selection | Canvas Shows | Inspector Shows |
|-----------|-------------|-----------------|
| Nothing | Overview: all objects, force-directed | System status |
| Dataset | Table preview + connected entities | Schema, columns, stats |
| Entity | Entity neighborhood graph | Properties, provenance |
| Relationship | Highlighted path + evidence | Evidence cards, confidence |
| Analysis/Query | Notebook view | Code, results, lineage |
| Multiple objects | Comparison view | Diff, schema alignment |
| Search result | Highlighted matches | Match context |

## Design Tokens

```css
:root {
  /* Surfaces */
  --glass-bg: rgba(255, 255, 255, 0.72);
  --glass-border: rgba(255, 255, 255, 0.18);
  --glass-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);

  /* Canvas */
  --canvas-bg: #f5f5f0;
  --canvas-grid: rgba(0, 0, 0, 0.03);

  /* Object colors */
  --color-dataset: #0d9488;
  --color-entity: #8b5cf6;
  --color-relationship: #f59e0b;
  --color-analysis: #3b82f6;
  --color-agent: #ec4899;

  /* Type */
  --font-display: 'Plus Jakarta Sans', sans-serif;
  --font-body: 'Inter', sans-serif;
  --font-mono: 'Geist Mono', monospace;

  /* Motion */
  --spring-default: cubic-bezier(0.22, 1, 0.36, 1);
  --duration-fast: 150ms;
  --duration-normal: 300ms;
}
```

## Component Map

```
src/
├── app/
│   ├── layout.tsx              # Root layout with providers
│   ├── page.tsx                # Entry redirect
│   └── dataspace/
│       └── page.tsx            # Main workspace
├── components/
│   ├── layout/
│   │   ├── TopBar.tsx          # Glass top bar
│   │   ├── Sidebar.tsx         # Collapsible glass sidebar
│   │   └── BottomInspector.tsx # Tabbed bottom panel
│   ├── canvas/
│   │   ├── SpatialCanvas.tsx   # Main canvas (2D force graph)
│   │   ├── CanvasNode.tsx      # Node rendering
│   │   ├── CanvasEdge.tsx      # Edge rendering
│   │   └── CanvasControls.tsx  # Zoom, fit, layout controls
│   ├── views/
│   │   ├── TableView.tsx       # Dataset table preview
│   │   ├── EntityView.tsx      # Entity detail
│   │   ├── GraphView.tsx       # Relationship graph
│   │   ├── NotebookView.tsx    # Analysis/query notebook
│   │   └── ComparisonView.tsx  # Multi-object diff
│   ├── inspector/
│   │   ├── InspectorPanel.tsx  # Tab container
│   │   ├── InspectorTab.tsx    # Object properties
│   │   ├── EvidenceTab.tsx     # Source evidence
│   │   ├── LineageTab.tsx      # Provenance graph
│   │   └── LogsTab.tsx         # Activity logs
│   ├── ai/
│   │   ├── CommandPalette.tsx  # Cmd+K palette
│   │   ├── ChatPanel.tsx       # AI conversation
│   │   └── AgentStatus.tsx     # Background agent indicators
│   └── ui/
│       ├── GlassCard.tsx       # Frosted glass card
│       ├── GlassButton.tsx     # Glass-styled button
│       ├── GlassInput.tsx      # Glass input field
│       ├── Badge.tsx           # Status/type badges
│       ├── Tooltip.tsx         # Hover tooltips
│       └── AnimatedNumber.tsx  # Count-up number display
├── hooks/
│   ├── useSpatialStore.ts      # Zustand store for canvas state
│   ├── useKeyboard.ts          # Keyboard shortcuts
│   └── useDataOS.ts            # API client hook
├── lib/
│   ├── api.ts                  # DataOS Python backend client
│   ├── graph-layout.ts         # Force-directed layout
│   └── view-switching.ts       # Intelligent view selection
└── styles/
    └── globals.css             # Tailwind + glass utilities
```

## Key Interactions

### Canvas
- **Scroll** = zoom (trackpad/pinch aware)
- **Drag** = pan canvas
- **Click node** = select → view switch + inspector update
- **Double-click** = expand into full view
- **Cmd+click** = multi-select
- **Hover** = tooltip preview + connection highlight

### Command Palette (Cmd+K)
- Search objects, run queries, switch views
- Recent actions, keyboard shortcuts
- Fuzzy matching with ranked results

### AI Chat
- Floating panel, toggle with `Cmd+I`
- Ask questions about data
- Get answers with evidence cards
- Execute queries from natural language

### Keyboard Shortcuts
- `Cmd+K` — command palette
- `Cmd+I` — AI chat
- `Cmd+/` — toggle sidebar
- `Cmd+Shift+P` — query console
- `Space` — toggle 2D/3D view
- `Esc` — deselect / close panel
- `J/K` — navigate nodes
- `Enter` — expand selected
- `Delete` — remove from canvas
