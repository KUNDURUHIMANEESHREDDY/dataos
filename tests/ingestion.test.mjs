import test from "node:test";
import assert from "node:assert/strict";
import { ingestFiles } from "../src/lib/ingestion.ts";

const jsonResponse = (body, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { "content-type": "application/json" },
});

const ingested = (createdObjects = 0, discoveredRelations = 0) => ({
  status: "ingested",
  created_objects_count: createdObjects,
  discovered_relations_count: discoveredRelations,
});

test("maps the backend ingestion response fields to user-visible counts", async () => {
  let request;
  const outcomes = await ingestFiles([
    { filename: "employees.csv", read: async () => "id,name\\n1,Alice" },
  ], async (url, init) => {
    request = { url, init };
    return jsonResponse(ingested(2, 3));
  });

  assert.equal(request.url, "/api/ingest/universal");
  assert.equal(request.init.method, "POST");
  assert.equal(request.init.headers["Content-Type"], "application/x-www-form-urlencoded");
  const body = new URLSearchParams(request.init.body);
  assert.equal(body.get("filename"), "employees.csv");
  assert.equal(body.get("content"), "id,name\\n1,Alice");
  assert.equal(body.get("discover_relations"), "true");
  assert.deepEqual(outcomes, [{
    filename: "employees.csv", ok: true, objectsCreated: 2, relationsCreated: 3,
  }]);
});

test("isolates an HTTP failure and continues processing later files", async () => {
  const requested = [];
  const outcomes = await ingestFiles([
    { filename: "rejected.csv", read: async () => "bad" },
    { filename: "accepted.json", read: async () => "{}" },
  ], async (_url, init) => {
    const filename = new URLSearchParams(init.body).get("filename");
    requested.push(filename);
    return filename === "rejected.csv"
      ? new Response("upstream error", { status: 503 })
      : jsonResponse(ingested(1, 0));
  });

  assert.deepEqual(requested, ["rejected.csv", "accepted.json"]);
  assert.deepEqual(outcomes, [
    { filename: "rejected.csv", ok: false, error: "HTTP 503" },
    { filename: "accepted.json", ok: true, objectsCreated: 1, relationsCreated: 0 },
  ]);
});

test("keeps file reads and requests sequential to bound concurrent upload memory", async () => {
  const order = [];
  await ingestFiles([
    { filename: "first.csv", read: async () => { order.push("read:first"); return "1"; } },
    { filename: "second.csv", read: async () => { order.push("read:second"); return "2"; } },
  ], async (_url, init) => {
    const filename = new URLSearchParams(init.body).get("filename");
    order.push(`post:${filename}`);
    return jsonResponse(ingested());
  });

  assert.deepEqual(order, [
    "read:first", "post:first.csv", "read:second", "post:second.csv",
  ]);
});

test("isolates file-read failures without issuing a request for unreadable files", async () => {
  const requested = [];
  const outcomes = await ingestFiles([
    { filename: "unreadable.csv", read: async () => { throw new Error("local path detail"); } },
    { filename: "readable.csv", read: async () => "ok" },
  ], async (_url, init) => {
    requested.push(new URLSearchParams(init.body).get("filename"));
    return jsonResponse(ingested());
  });

  assert.deepEqual(requested, ["readable.csv"]);
  assert.deepEqual(outcomes, [
    { filename: "unreadable.csv", ok: false, error: "unable to read file" },
    { filename: "readable.csv", ok: true, objectsCreated: 0, relationsCreated: 0 },
  ]);
});

test("isolates network failures and continues with the next file", async () => {
  const outcomes = await ingestFiles([
    { filename: "offline.csv", read: async () => "offline" },
    { filename: "online.csv", read: async () => "online" },
  ], async (_url, init) => {
    const filename = new URLSearchParams(init.body).get("filename");
    if (filename === "offline.csv") throw new Error("transport details are not exposed");
    return jsonResponse(ingested(1, 0));
  });

  assert.deepEqual(outcomes, [
    { filename: "offline.csv", ok: false, error: "request failed" },
    { filename: "online.csv", ok: true, objectsCreated: 1, relationsCreated: 0 },
  ]);
});

test("rejects malformed JSON, non-object payloads and missing backend counts", async () => {
  const outcomes = await ingestFiles([
    { filename: "malformed.json", read: async () => "{" },
    { filename: "array.json", read: async () => "[]" },
    { filename: "missing-counts.json", read: async () => "{}" },
  ], async (_url, init) => {
    const filename = new URLSearchParams(init.body).get("filename");
    if (filename === "malformed.json") {
      return new Response("{", { status: 200, headers: { "content-type": "application/json" } });
    }
    if (filename === "array.json") return jsonResponse([]);
    return jsonResponse({ status: "ingested" });
  });

  assert.deepEqual(outcomes, [
    { filename: "malformed.json", ok: false, error: "invalid ingestion response" },
    { filename: "array.json", ok: false, error: "invalid ingestion response" },
    { filename: "missing-counts.json", ok: false, error: "invalid ingestion response" },
  ]);
});

test("rejects legacy field names and invalid backend count values", async () => {
  const outcomes = await ingestFiles([
    { filename: "legacy.json", read: async () => "{}" },
    { filename: "negative.json", read: async () => "{}" },
    { filename: "fractional.json", read: async () => "{}" },
  ], async (_url, init) => {
    const filename = new URLSearchParams(init.body).get("filename");
    if (filename === "legacy.json") {
      return jsonResponse({ status: "ingested", objects_created: 5, relations_created: 2 });
    }
    if (filename === "negative.json") return jsonResponse(ingested(-1, 0));
    return jsonResponse(ingested(1.5, 0));
  });

  assert.deepEqual(outcomes, [
    { filename: "legacy.json", ok: false, error: "invalid ingestion response" },
    { filename: "negative.json", ok: false, error: "invalid ingestion response" },
    { filename: "fractional.json", ok: false, error: "invalid ingestion response" },
  ]);
});

test("returns an empty result for an empty batch", async () => {
  assert.deepEqual(await ingestFiles([]), []);
});
