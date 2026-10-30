/**
 * Normalize the backend Relationship.to_dict() contract into the edge shape
 * consumed by the Dataspace graph store.
 *
 * The canonical API fields are source/target. The source_id/target_id aliases
 * are retained for older persisted fixtures and integrations during migration.
 *
 * @param {Record<string, unknown> | null | undefined} relationship
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
  // Relationship.confidence is a contract value in the inclusive [0, 1]
  // range. Corrupt/legacy payloads must not leak invalid values into graph
  // styling, where out-of-range opacity can hide or distort an edge.
  const rawConfidence = relationship.confidence;
  const confidence = typeof rawConfidence === "number"
    && Number.isFinite(rawConfidence)
    && rawConfidence >= 0
    && rawConfidence <= 1
    ? rawConfidence
    : 1.0;

  return { id, source, target, type, confidence };
}

module.exports = { toGraphEdge };
