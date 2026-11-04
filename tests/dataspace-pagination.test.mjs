import test from "node:test";
import assert from "node:assert/strict";
import paginate from "../src/lib/paginate.js";
import { toGraphEdge } from "../src/lib/relationship-edge.js";

const { loadAllPages, loadBoundedPages } = paginate;

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
    { limit: 2, offset: 0, signal: undefined },
    { limit: 2, offset: 2, signal: undefined },
    { limit: 2, offset: 4, signal: undefined },
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

test("forwards the abort signal and stops before requesting another page", async () => {
  const controller = new AbortController();
  const calls = [];

  await assert.rejects(
    () => loadAllPages(async ({ offset, signal }) => {
      calls.push({ offset, signal });
      controller.abort();
      return { total: 2, items: ["first"] };
    }, "items", 1, undefined, controller.signal),
    { name: "AbortError" },
  );

  assert.equal(calls.length, 1);
  assert.equal(calls[0].offset, 0);
  assert.equal(calls[0].signal, controller.signal);
});

test("does not start a page request when the signal is already aborted", async () => {
  const controller = new AbortController();
  const calls = [];
  controller.abort();

  await assert.rejects(
    () => loadAllPages(async (params) => {
      calls.push(params);
      return { total: 0, items: [] };
    }, "items", 1, undefined, controller.signal),
    { name: "AbortError" },
  );

  assert.deepEqual(calls, []);
});

test("caps collections using the server total and reports truncation", async () => {
  const calls = [];
  const pages = new Map([
    [0, { total: 5, items: ["a", "b"] }],
    [2, { total: 5, items: ["c", "d"] }],
  ]);

  const result = await loadBoundedPages(async (params) => {
    calls.push(params);
    return pages.get(params.offset);
  }, "items", 2, 3);

  assert.deepEqual(result, { items: ["a", "b", "c"], total: 5, truncated: true });
  assert.deepEqual(calls.map(({ limit, offset }) => ({ limit, offset })), [
    { limit: 2, offset: 0 },
    { limit: 2, offset: 2 },
  ]);
});

test("uses a one-record probe to distinguish an exact cap when total is omitted", async () => {
  const calls = [];
  const result = await loadBoundedPages(async (params) => {
    calls.push(params);
    return { items: params.offset === 0 ? ["a", "b"] : [] };
  }, "items", 2, 2);

  assert.deepEqual(result, { items: ["a", "b"], total: null, truncated: false });
  assert.deepEqual(calls.map(({ limit, offset }) => ({ limit, offset })), [
    { limit: 2, offset: 0 },
    { limit: 1, offset: 2 },
  ]);
});

test("reports truncation when the one-record probe finds more data", async () => {
  const calls = [];
  const result = await loadBoundedPages(async (params) => {
    calls.push(params);
    return { items: params.offset === 0 ? ["a", "b"] : ["c"] };
  }, "items", 2, 2);

  assert.deepEqual(result, { items: ["a", "b"], total: null, truncated: true });
  assert.deepEqual(calls.map(({ limit, offset }) => ({ limit, offset })), [
    { limit: 2, offset: 0 },
    { limit: 1, offset: 2 },
  ]);
});

test("forwards abort signals through bounded pagination", async () => {
  const controller = new AbortController();
  const calls = [];
  await assert.rejects(
    () => loadBoundedPages(async ({ offset, signal }) => {
      calls.push({ offset, signal });
      controller.abort();
      return { items: ["first"] };
    }, "items", 1, 2, controller.signal),
    { name: "AbortError" },
  );
  assert.equal(calls.length, 1);
  assert.equal(calls[0].signal, controller.signal);
});

test("rejects invalid bounded pagination limits", async () => {
  await assert.rejects(
    () => loadBoundedPages(async () => ({ items: [] }), "items", 2, 0),
    /maxItems/,
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
      id: JSON.stringify(["legacy-a", "legacy-b", "related_to"]),
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

test("clamps finite relationship confidence values to the API contract range", () => {
  assert.equal(toGraphEdge({ source: "a", target: "b", confidence: -0.01 }).confidence, 0);
  assert.equal(toGraphEdge({ source: "a", target: "b", confidence: 1.01 }).confidence, 1);
});

test("uses conservative zero confidence for malformed explicit values", () => {
  for (const confidence of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, "0.75"]) {
    assert.equal(toGraphEdge({ source: "a", target: "b", confidence }).confidence, 0);
  }
});

test("preserves relationship confidence at both valid contract boundaries", () => {
  assert.equal(toGraphEdge({ source: "a", target: "b", confidence: 0 }).confidence, 0);
  assert.equal(toGraphEdge({ source: "a", target: "b", confidence: 1 }).confidence, 1);
});


test("uses an unambiguous fallback identity for endpoint IDs containing delimiters", () => {
  const first = toGraphEdge({ source: "a-b", target: "c", relation_type: "depends_on" });
  const second = toGraphEdge({ source: "a", target: "b-c", relation_type: "depends_on" });
  const third = toGraphEdge({ source: "a-b", target: "c", relation_type: "related_to" });

  assert.notEqual(first.id, second.id);
  assert.notEqual(first.id, third.id);
  assert.equal(first.id, JSON.stringify(["a-b", "c", "depends_on"]));
});

test("keeps fallback relationship identities unique across paginated pages", async () => {
  const pages = new Map([
    [0, {
      total: 4,
      relationships: [
        { source: "a-b", target: "c", relation_type: "depends_on" },
        { source: "a", target: "b-c", relation_type: "depends_on" },
      ],
    }],
    [2, {
      total: 4,
      relationships: [
        { source: "a-b", target: "c", relation_type: "related_to" },
        { id: "explicit-1", source: "a-b", target: "c", relation_type: "related_to" },
      ],
    }],
  ]);

  const relationships = await loadAllPages(
    async ({ offset }) => pages.get(offset),
    "relationships",
    2,
  );
  const edges = relationships.map(toGraphEdge);

  assert.ok(edges.every(Boolean));
  const ids = edges.map((edge) => edge.id);
  assert.equal(new Set(ids).size, relationships.length);
  assert.equal(ids[3], "explicit-1");
});
