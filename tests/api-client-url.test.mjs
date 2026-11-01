import test from "node:test";
import assert from "node:assert/strict";
import { api } from "../src/lib/api.ts";

function captureRequests(t) {
  const requests = [];
  const originalFetch = globalThis.fetch;

  globalThis.fetch = async (input, init) => {
    requests.push({ url: String(input), init });
    return new Response("{}", {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  t.after(() => {
    globalThis.fetch = originalFetch;
  });

  return requests;
}

test("encodes resource identifiers as one URL path segment", async (t) => {
  const requests = captureRequests(t);
  const id = "folder/a ?b#c";
  const encoded = encodeURIComponent(id);

  await api.getObject(id);
  await api.deleteObject(id);
  await api.getNeighbors(id);
  await api.traverse(id);
  await api.lineage(id);
  await api.why(id);
  await api.impact(id);
  await api.profile(id);
  await api.recommendations(id);

  assert.deepEqual(
    requests.map(({ url }) => url),
    [
      `/api/objects/${encoded}`,
      `/api/objects/${encoded}`,
      `/api/graph/neighbors/${encoded}?direction=both`,
      `/api/graph/traverse/${encoded}?max_hops=3`,
      `/api/provenance/lineage/${encoded}?direction=upstream`,
      `/api/objects/${encoded}/why`,
      `/api/objects/${encoded}/impact`,
      `/api/profiling/${encoded}`,
      `/api/recommendations/connections/${encoded}`,
    ],
  );
});

test("encodes query values without allowing delimiters to change parameters", async (t) => {
  const requests = captureRequests(t);

  await api.getNeighbors("node", "up stream&raw");
  await api.graphAnalytics("pagerank&raw");
  await api.lineage("node", "down stream&raw");
  await api.duplicates("folder/a ?b#c");

  assert.deepEqual(
    requests.map(({ url }) => url),
    [
      "/api/graph/neighbors/node?direction=up+stream%26raw",
      "/api/graph/analytics?algorithm=pagerank%26raw",
      "/api/provenance/lineage/node?direction=down+stream%26raw",
      "/api/governance/duplicates?object_id=folder%2Fa+%3Fb%23c",
    ],
  );
});

test("preserves explicitly supplied zero values instead of replacing them with defaults", async (t) => {
  const requests = captureRequests(t);

  await api.listObjects({ limit: 0, offset: 0 });
  await api.listRelationships({ limit: 0, offset: 0 });
  await api.traverse("node", 0);
  await api.search("query", 0);

  assert.deepEqual(
    requests.map(({ url }) => url),
    [
      "/api/objects/?limit=0&offset=0",
      "/api/relationships/?limit=0&offset=0",
      "/api/graph/traverse/node?max_hops=0",
      "/api/search/?q=query&limit=0",
    ],
  );
});
