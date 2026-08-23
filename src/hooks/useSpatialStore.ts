import { create } from "zustand";

export type ObjectType = "source" | "dataset" | "entity" | "relation" | "analysis" | "agent";

export interface CanvasObject {
  id: string;
  type: ObjectType;
  name: string;
  properties: Record<string, any>;
  x?: number;
  y?: number;
  z?: number;
}

export interface CanvasEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  confidence: number;
}

export type ViewMode = "2d" | "3d";
export type ActivePanel = "inspector" | "evidence" | "lineage" | "query" | "analysis" | "logs";
export type SidebarTab = "sources" | "datasets" | "entities" | "relations" | "agents";

interface SpatialState {
  objects: CanvasObject[];
  edges: CanvasEdge[];
  selectedIds: string[];
  hoveredId: string | null;
  viewMode: ViewMode;
  activePanel: ActivePanel;
  sidebarTab: SidebarTab;
  sidebarOpen: boolean;
  commandPaletteOpen: boolean;
  chatOpen: boolean;
  searchQuery: string;
  zoom: number;
  panX: number;
  panY: number;

  setObjects: (objects: CanvasObject[]) => void;
  setEdges: (edges: CanvasEdge[]) => void;
  selectObject: (id: string, multi?: boolean) => void;
  clearSelection: () => void;
  setHovered: (id: string | null) => void;
  setViewMode: (mode: ViewMode) => void;
  setActivePanel: (panel: ActivePanel) => void;
  setSidebarTab: (tab: SidebarTab) => void;
  toggleSidebar: () => void;
  setCommandPaletteOpen: (open: boolean) => void;
  setChatOpen: (open: boolean) => void;
  setSearchQuery: (query: string) => void;
  setZoom: (zoom: number) => void;
  setPan: (x: number, y: number) => void;
}

export const useSpatialStore = create<SpatialState>((set) => ({
  objects: [],
  edges: [],
  selectedIds: [],
  hoveredId: null,
  viewMode: "2d",
  activePanel: "inspector",
  sidebarTab: "datasets",
  sidebarOpen: true,
  commandPaletteOpen: false,
  chatOpen: false,
  searchQuery: "",
  zoom: 1,
  panX: 0,
  panY: 0,

  setObjects: (objects) => set({ objects }),
  setEdges: (edges) => set({ edges }),
  selectObject: (id, multi) =>
    set((s) => ({
      selectedIds: multi
        ? s.selectedIds.includes(id)
          ? s.selectedIds.filter((i) => i !== id)
          : [...s.selectedIds, id]
        : [id],
    })),
  clearSelection: () => set({ selectedIds: [] }),
  setHovered: (id) => set({ hoveredId: id }),
  setViewMode: (mode) => set({ viewMode: mode }),
  setActivePanel: (panel) => set({ activePanel: panel }),
  setSidebarTab: (tab) => set({ sidebarTab: tab }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),
  setChatOpen: (open) => set({ chatOpen: open }),
  setSearchQuery: (query) => set({ searchQuery: query }),
  setZoom: (zoom) => set({ zoom: Math.max(0.1, Math.min(3, zoom)) }),
  setPan: (x, y) => set({ panX: x, panY: y }),
}));
