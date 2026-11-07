export interface FileDropHandlers {
  onDragStateChange: (dragging: boolean) => void;
  onFilesDrop: (files: File[]) => void;
}

export function attachFileDropEvents(
  target: HTMLElement,
  handlers: FileDropHandlers,
): () => void;
