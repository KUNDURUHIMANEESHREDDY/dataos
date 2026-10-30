import test from "node:test";
import assert from "node:assert/strict";
import paginate from "../src/lib/paginate.js";
import { toGraphEdge } from "../src/lib/relationship-edge.js";

const { loadAllPages } = paginate;

test("loads every page using bounded offsets and the reported total", async () => {
  const calls = [];
  const pages = new Map([
    [0, { total: 5, relationships: ["a", "b"] }],
    [2, { total: 5, relationships: ["c", "d"] }],
    [4, { total: 5, relationships: ["e"] }],
  ]);

  const result = await loadAllPages(
    async (params) => {
      calls.push(params);
      return pages.get(params.offset);
    },
    "relationships",
    2,
  );

  assert.deepEqual(result, ["a", "b", "c", "d", "e"]);
  assert.deepEqual(calls, [
    { limit: 2, offset: 0 },
    { limit: 2, offset: 2 },
    { limit: 2, offset: 4 },
  ]);
});

test("stops on a short page when the API omits total", async () => {
  const calls = [];
  const result = await loadAllPages(async ({ limit, offset }) => {
    calls.push({ limit, offset });
    return { objects: offset === 0 ? ["a", "b"] : ["c"] };
  }, "objects", 2);

  assert.deepEqual(result, ["a", "b", "c"]);
  assert.equal(calls.length, 2);
});

test("rejects a short page before the reported total instead of silently truncating", async () => {
  const calls = [];
  await assert.rejects(
    () => loadAllPages(async ({ offset }) => {
      calls.push(offset);
      return { total: 5, items: offset === 0 ? ["a"] : ["b"] };
    }, "items", 2),
    /short page at offset 0 before the reported total of 5 records/,
  );
  assert.deepEqual(calls, [0]);
});

test("rejects missing collection payloads and invalid totals", async () => {
  await assert.rejects(
    () => loadAllPages(async () => ({ total: 0 }), "items", 2),
    /must contain an array named items/,
  );
  await assert.rejects(
    () => loadAllPages(async () => ({ total: -1, items: [] }), "items", 2),
    /total must be a non-negative safe integer/,
  );
});

test("rejects invalid page sizes and offset bounds", async () => {
  await assert.rejects(() => loadAllPages(async () => ({}), "items", 0), /pageSize/);
  await assert.rejects(() => loadAllPages(async () => ({}), "items", 1, -1), /maxOffset/);
});

test("fails explicitly when more records exist beyond the API offset limit", async () => {
  const calls = [];
  await assert.rejects(
    () => loadAllPages(async ({ limit, offset }) => {
      calls.push({ limit, offset });
      return { total: 6, items: [offset, offset + 1] };
    }, "items", 2, 2),
    /offset limit of 2/,
  );
  assert.deepEqual(calls, [
    { limit: 2, offset: 0 },
    { limit: 2, offset: 2 },
  ]);
});

test("propagates page-fetch failures without returning partial results", async () => {
  await assert.rejects(
    () => loadAllPages(async ({ offset }) => {
      if (offset > 0) throw new Error("upstream unavailable");
      return { total: 3, items: [1, 2] };
    }, "items", 2),
    /upstream unavailable/,
  );
});


test("maps canonical backend Relationship.to_dict source and target fields", () => {
  assert.deepEqual(
    toGraphEdge({
      id: "rel-1",
      source: "object-a",
      target: "object-b",
      relation_type: "depends_on",
      confidence: 0.75,
    }),
    {
      id: "rel-1",
      source: "object-a",
      target: "object-b",
      type: "depends_on",
      confidence: 0.75,
    },
  );
});

test("accepts legacy source_id and target_id aliases during migration", () => {
  assert.deepEqual(
    toGraphEdge({ source_id: "legacy-a", target_id: "legacy-b" }),
    {
      id: "legacy-a-legacy-b",
      source: "legacy-a",
      target: "legacy-b",
      type: "related_to",
      confidence: 1,
    },
  );
});

test("drops malformed relationships instead of creating undefined graph edges", () => {
  assert.equal(toGraphEdge({ id: "missing-target", source: "object-a" }), null);
  assert.equal(toGraphEdge({ source: "", target: "object-b" }), null);
  assert.equal(toGraphEdge(null), null);
});
