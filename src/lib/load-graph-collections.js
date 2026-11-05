/**
 * Load both graph collections with a shared cancellation boundary.
 *
 * If either request fails, stop the other collection's in-flight pagination
 * before propagating the original failure. This prevents a failed object or
 * relationship request from leaving the other loader fetching thousands of
 * records after the page has already entered its error state.
 *
 * @template Objects, Relationships
 * @param {AbortController} controller
 * @param {(signal: AbortSignal) => Promise<Objects>} loadObjects
 * @param {(signal: AbortSignal) => Promise<Relationships>} loadRelationships
 * @returns {Promise<[Objects, Relationships]>}
 */
export async function loadGraphCollections(controller, loadObjects, loadRelationships) {
  if (!controller || !controller.signal || typeof controller.abort !== "function") {
    throw new TypeError("controller must be an AbortController");
  }
  if (typeof loadObjects !== "function" || typeof loadRelationships !== "function") {
    throw new TypeError("both graph collection loaders must be functions");
  }

  try {
    return await Promise.all([
      loadObjects(controller.signal),
      loadRelationships(controller.signal),
    ]);
  } catch (error) {
    if (!controller.signal.aborted) controller.abort();
    throw error;
  }
}
