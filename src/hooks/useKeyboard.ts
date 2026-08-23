import { useEffect } from "react";
import { useSpatialStore } from "./useSpatialStore";

export function useKeyboard() {
  const setCommandPaletteOpen = useSpatialStore((s) => s.setCommandPaletteOpen);
  const setChatOpen = useSpatialStore((s) => s.setChatOpen);
  const toggleSidebar = useSpatialStore((s) => s.toggleSidebar);
  const setViewMode = useSpatialStore((s) => s.setViewMode);
  const viewMode = useSpatialStore((s) => s.viewMode);
  const clearSelection = useSpatialStore((s) => s.clearSelection);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const isMod = e.metaKey || e.ctrlKey;
      if (isMod && e.key === "k") {
        e.preventDefault();
        setCommandPaletteOpen(true);
      }
      if (isMod && e.key === "i") {
        e.preventDefault();
        setChatOpen(true);
      }
      if (isMod && e.key === "/") {
        e.preventDefault();
        toggleSidebar();
      }
      if (e.key === "Escape") {
        clearSelection();
        setCommandPaletteOpen(false);
        setChatOpen(false);
      }
      if (e.key === " " && !isMod) {
        e.preventDefault();
        setViewMode(viewMode === "2d" ? "3d" : "2d");
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [setCommandPaletteOpen, setChatOpen, toggleSidebar, setViewMode, viewMode, clearSelection]);
}
