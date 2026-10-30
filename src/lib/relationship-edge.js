/**
 * Normalize the backend Relationship.to_dict() contract into the edge shape
 * consumed by the Dataspace graph store.
 *
 * The canonical API fields are source/target. The source_id/target_id aliases
 * are retained for older persisted fixtures and integrations during migration.
 *
 * @param {unknown} relationship
 * @returns {{id: string, source: string, target: string, type: string, confidence: number} | null}
 */
function toGraphEdge(relationship) {
  if (!relationship || typeof relationship !== "object" || Array.isArray(relationship)) {
    return null;
  }

  const source = relationship.source ?? relationship.source_id;
  const target = relationship.target ?? relationship.target_id;
  if (
    typeof source !== "string" || source.length === 0
    || typeof target !== "string" || target.length === 0
  ) {
    return null;
  }

  const id = typeof relationship.id === "string" && relationship.id.length > 0
    ? relationship.id
    : `${source}-${target}`;
  const type = typeof relationship.relation_type === "string" && relationship.relation_type.length > 0
    ? relationship.relation_type
    : "related_to";
  const confidence = typeof relationship.confidence === "number" && Number.isFinite(relationship.confidence)
    ? relationship.confidence
    : 1.0;

  return { id, source, target, type, confidence };
}

module.exports = { toGraphEdge };
