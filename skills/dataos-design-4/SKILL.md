---
name: dataos-design-4
description: "DataOS Frontend Option 4: Spatial OS — a 3D/2D hybrid interface using Three.js for data visualization, with a desktop metaphor (folders, windows, workspace). Best for visual thinkers and complex data exploration."
---

# Option 4: Spatial OS

A spatial interface where data lives in a 3D workspace. Objects are files on a desk, relationships are visible connections, and exploration happens by moving through space. Think: Figma meets a data lab.

## Design Philosophy
> "When you can see the shape of your data, you understand it faster."

## Visual Identity

- **Palette:** Neutral warm (#f8f7f4) workspace, charcoal (#2d2d2d) UI panels, teal (#0d9488) primary, coral (#f97066) for warnings, violet (#8b5cf6) for AI agents
- **Typography:** Plus Jakarta Sans for UI, Geist Mono for data. Rounded, friendly, accessible.
- **Layout:** Infinite canvas with floating panels. Windows are draggable, resizable, dockable.
- **Surfaces:** Soft shadows, rounded corners (12px), subtle gradients on interactive elements

## Core Screens

### 1. Workspace (Home)
```
┌─────────────────────────────────────────────────────────┐
│ ┌──────────┐                                            │
│ │ Explorer │  ┌──────────────────────────────────┐      │
│ │──────────│  │                                  │      │
│ │ 📁 Sales │  │    [3D scene with data objects]  │      │
│ │ 📁 Users │  │                                  │      │
│ │ 📁 Logs  │  │    ○ customer_1 ──○ order_42     │      │
│ │          │  │    │                            │      │
│ │          │  │    ○ product_7 ──○ ticket_99    │      │
│ │          │  │                                  │      │
│ └──────────┘  └──────────────────────────┬───────┘      │
│ ┌────────────────────────────────────────┘              │
│ │ [Detail panel: selected object properties]            │
│ └───────────────────────────────────────────────────────│
│                                                          │
│  Agent: "I found 3 new relationships in Sales data"     │
│  [Accept] [Review] [Dismiss]                            │
└─────────────────────────────────────────────────────────┘
```

### 2. 3D Data Scene
- Objects rendered as 3D cards/boxes in space
- Spatial clustering: related objects gravitate together
- Camera controls: orbit, zoom, pan (trackpad gestures)
- Click object → panel slides in from right
- Hover → tooltip with summary + connection lines highlight

### 3. Relationship Explorer
- 2D graph view as alternative to 3D scene
- Hierarchical layout option (tree view)
- Edge bundling for complex graphs
- Highlight path between two selected nodes
- Community detection with colored clusters

### 4. File System View
- Desktop metaphor: folders, files, trash
- Drag files into workspace to create scene
- Right-click context menu: open, preview, share, delete
- Grid/list view toggle
- Smart sorting: by type, by date, by size, by confidence

### 5. Agent Dashboard
- Floating agent cards with live status
- Agent activity feed (scrolling log)
- Agent proposals: suggested relationships, classifications, actions
- Accept/reject with explanation
- Resource usage per agent (CPU, memory, time)

## Component Patterns

### 3D Data Object
```jsx
// In Three.js / R3F
<mesh position={[x, y, z]}>
  <boxGeometry args={[width, height, 0.1]} />
  <meshStandardMaterial
    color={typeColor}
    transparent
    opacity={isSelected ? 1.0 : 0.7}
  />
  {/* Label sprite */}
  <sprite position={[0, height/2 + 0.3, 0]}>
    <spriteMaterial>
      <canvasTexture image={labelCanvas} />
    </spriteMaterial>
  </sprite>
</mesh>
```

### Floating Panel
```jsx
<div
  className="absolute bg-white rounded-xl shadow-2xl shadow-black/10 border border-gray-100
    overflow-hidden"
  style={{ transform: `translate(${x}px, ${y}px)`, width, height }}
  onMouseDown={startDrag}
>
  <div className="flex items-center justify-between px-3 py-2 bg-gray-50 border-b border-gray-100
    cursor-grab active:cursor-grabbing">
    <span className="text-sm font-medium">{title}</span>
    <div className="flex gap-1">
      <button className="w-3 h-3 rounded-full bg-gray-200" />
      <button className="w-3 h-3 rounded-full bg-gray-200" />
      <button className="w-3 h-3 rounded-full bg-red-300" />
    </div>
  </div>
  <div className="p-4 overflow-auto" style={{ height: height - 40 }}>
    {children}
  </div>
</div>
```

### Agent Proposal Card
```jsx
<div className="bg-violet-50 border border-violet-200 rounded-xl p-4 max-w-sm">
  <div className="flex items-center gap-2 mb-2">
    <Bot className="w-5 h-5 text-violet-500" />
    <span className="text-sm font-medium text-violet-700">Agent Discovery</span>
  </div>
  <p className="text-sm text-gray-700 mb-3">{proposal.description}</p>
  <div className="flex gap-2">
    <button className="flex-1 px-3 py-1.5 bg-violet-500 text-white text-sm rounded-lg
      hover:bg-violet-600 transition-colors">
      Accept
    </button>
    <button className="flex-1 px-3 py-1.5 bg-white text-gray-700 text-sm rounded-lg
      border border-gray-200 hover:bg-gray-50 transition-colors">
      Review
    </button>
  </div>
</div>
```

## Interactions
- **3D navigation:** orbit (left drag), zoom (scroll), pan (middle drag / two-finger)
- **Object selection:** click in scene or explorer tree
- **Drag to connect:** draw relationship between two objects
- **Double-click** object → open in detail panel
- **Space bar** → toggle between 3D scene and 2D graph
- **Cmd+click** → multi-select
- **Pinch to zoom** on trackpad

## Responsive
- Below 1024px: 3D scene becomes 2D graph, panels stack
- Below 768px: single panel mode, swipe between views
- Below 480px: simplified explorer, tap to navigate
- No 3D on mobile — use 2D graph view

## Motion
- 3D camera: smooth damping on orbit/zoom (0.1 lerp factor)
- Object selection: scale pulse (1.0 → 1.05 → 1.0, 300ms spring)
- Panel open/close: spring (damping 1.0, response 0.3)
- Graph layout: force simulation with animated transitions
- Agent proposals: slide in from right with spring
