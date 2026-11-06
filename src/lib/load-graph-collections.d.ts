export function loadGraphCollections<Objects, Relationships>(
  controller: AbortController,
  loadObjects: (signal: AbortSignal) => Promise<Objects>,
  loadRelationships: (signal: AbortSignal) => Promise<Relationships>,
): Promise<[Objects, Relationships]>;
