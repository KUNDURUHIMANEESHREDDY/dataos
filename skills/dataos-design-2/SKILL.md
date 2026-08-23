---
name: dataos-design-2
description: "DataOS Frontend Option 2: Glass Studio — Apple-inspired translucent glassmorphism with fluid motion, generous whitespace, and editorial typography. Best for non-technical stakeholders and executive views."
---

# Option 2: Glass Studio

An Apple-inspired interface that feels like information floating in space. Translucent layers, fluid motion, and editorial typography. Data as a design material.

## Design Philosophy
> "Data should feel like it lives in the room with you, not behind a screen."

## Visual Identity

- **Palette:** Light mode primary — soft white (#fafafa) to warm gray (#f5f5f0), accent blue (#007AFF), success green (#34C759), system orange (#FF9500). Dark mode: deep navy (#1a1a2e) with frosted overlays.
- **Typography:** SF Pro Display (or Inter as web fallback) for headings — optical sizing, tight leading. SF Mono for code/data. Large display sizes (48-72px) for hero metrics.
- **Layout:** Fluid grid, generous margins (24-48px), card-based with frosted glass surfaces
- **Surfaces:** `backdrop-filter: blur(20px) saturate(180%)` with subtle borders and shadows

## Core Screens

### 1. Overview Dashboard
```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   Good morning. Your dataspace is healthy.              │
│                                                         │
│   ┌─────────────┐ ┌─────────────┐ ┌─────────────┐     │
│   │ ░░░░░░░░░░░ │ │ ░░░░░░░░░░░ │ │ ░░░░░░░░░░░ │     │
│   │ ░ 12,847  ░ │ │ ░  99.7%   ░ │ │ ░  142ms   ░ │     │
│   │ ░ objects ░ │ │ ░ uptime   ░ │ │ ░ avg query░ │     │
│   │ ░░░░░░░░░░░ │ │ ░░░░░░░░░░░ │ │ ░░░░░░░░░░░ │     │
│   └─────────────┘ └─────────────┘ └─────────────┘     │
│                                                         │
│   Recent Activity                                       │
│   ─────────────────────────────────────                 │
│   📊 sales_q4.csv ingested — 2,400 rows                │
│   🔗 3 new relationships discovered                     │
│   🤖 Agent completed data quality scan                  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 2. Object Detail
- Hero section: object name in large type, type badge, last modified
- Translucent card sections for properties, content preview, relationships
- Relationship cards: mini-graph thumbnail + linked objects
- Version timeline: vertical, with diff previews on hover

### 3. Natural Language Query (Ask DataOS)
- Large centered input: "Ask anything about your data..."
- Streaming response with typewriter effect
- Evidence cards below answer: source objects with inline previews
- Follow-up suggestions as pill buttons
- Full provenance chain: expandable from any claim

### 4. Knowledge Graph
- Clean force-directed graph with frosted node cards
- Smooth zoom/pan with momentum
- Sidebar: selected node detail with animated transitions
- Filter chips at top for entity types
- Double-click to expand neighborhood

### 5. File Manager
- Grid view with large file type icons + thumbnails
- List view alternative
- Drag-and-drop upload zone with animated border
- Preview panel: renders content inline (CSV table, code syntax, markdown)
- Smart folders: "Recently ingested", "Needs review", "High confidence"

## Component Patterns

### Glass Card
```jsx
<div className="backdrop-blur-xl bg-white/60 dark:bg-white/5 border border-white/20
  rounded-2xl p-6 shadow-lg shadow-black/5">
  {/* content */}
</div>
```

### Metric Hero
```jsx
<div className="text-center">
  <div className="text-6xl font-semibold tracking-tight tabular-nums">
    12,847
  </div>
  <div className="text-sm text-gray-500 mt-2 tracking-wide">objects in dataspace</div>
</div>
```

### Activity Feed Item
```jsx
<div className="flex items-start gap-3 py-3 border-b border-gray-100 last:border-0">
  <div className="w-8 h-8 rounded-full bg-blue-50 flex items-center justify-center shrink-0">
    <Icon className="w-4 h-4 text-blue-500" />
  </div>
  <div>
    <p className="text-sm text-gray-900">{action}</p>
    <p className="text-xs text-gray-400 mt-0.5">{time}</p>
  </div>
</div>
```

### Evidence Card
```jsx
<div className="bg-white/80 backdrop-blur rounded-xl border border-gray-200/60 p-4
  hover:shadow-md transition-shadow">
  <div className="flex items-center gap-2 mb-2">
    <FileIcon className="w-4 h-4 text-gray-400" />
    <span className="text-xs text-gray-500">{source}</span>
  </div>
  <p className="text-sm text-gray-700 leading-relaxed">{excerpt}</p>
  <div className="mt-2 text-xs text-blue-500">View full object →</div>
</div>
```

## Interactions
- **Everything animates.** Cards enter with spring (damping 1.0, response 0.4). Panels slide with velocity handoff.
- **Pull-to-refresh** on data views (rubber-band at edge)
- **Haptic-like feedback:** subtle scale pulse on successful actions (0.97 → 1.0)
- **Context menus** on right-click or long-press, frosted glass style
- **Smooth scrolling** with momentum, snap-to-section on scroll spy

## Responsive
- Below 1024px: single column, cards stack vertically
- Below 768px: bottom sheet for details, swipe gestures
- Below 480px: full-screen views, bottom tab navigation
- iPad: split view with slide-over for details

## Motion
- Page transitions: cross-fade (200ms) for same-level, slide-left/right for hierarchy
- Card hover: lift with shadow (150ms ease-out)
- Number changes: count-up animation (400ms, ease-out)
- Graph: force simulation with dampened physics
- Pull-to-refresh: rubber-band resistance curve
