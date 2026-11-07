/**
 * Attach bounded file-drag handlers to the canvas surface. Listening on the
 * parent keeps the first dragenter observable even while the visual overlay
 * has pointer-events disabled.
 */
export function attachFileDropEvents(target, handlers) {
  let depth = 0;

  const isFileDrag = (event) => {
    const types = event.dataTransfer?.types;
    return Boolean(
      (types && Array.from(types).includes("Files"))
      || (event.dataTransfer?.files?.length ?? 0) > 0
    );
  };

  const onDragEnter = (event) => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    depth += 1;
    handlers.onDragStateChange(true);
  };

  const onDragLeave = (event) => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    depth = Math.max(0, depth - 1);
    if (depth === 0) handlers.onDragStateChange(false);
  };

  const onDragOver = (event) => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  };

  const onDrop = (event) => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    depth = 0;
    handlers.onDragStateChange(false);
    handlers.onFilesDrop(Array.from(event.dataTransfer?.files ?? []));
  };

  target.addEventListener("dragenter", onDragEnter);
  target.addEventListener("dragleave", onDragLeave);
  target.addEventListener("dragover", onDragOver);
  target.addEventListener("drop", onDrop);

  return () => {
    target.removeEventListener("dragenter", onDragEnter);
    target.removeEventListener("dragleave", onDragLeave);
    target.removeEventListener("dragover", onDragOver);
    target.removeEventListener("drop", onDrop);
    depth = 0;
  };
}
