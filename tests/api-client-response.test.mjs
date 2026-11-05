import test from "node:test";
import assert from "node:assert/strict";
import { api } from "../src/lib/api.ts";

function withFetch(t, handler) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = handler;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
}

test("returns undefined for an explicit no-content success", async (t) => {
  withFetch(t, async () => new Response(null, { status: 204 }));

  assert.equal(await api.health(), undefined);
});

test("preserves JSON API error details", async (t) => {
  withFetch(t, async () => new Response(
    JSON.stringify({ detail: "Object not found" }),
    { status: 404, headers: { "content-type": "application/json" } },
  ));

  await assert.rejects(api.health(), {
    name: "Error",
    message: "API 404: Object not found",
  });
});

test("does not expose HTML error pages to callers", async (t) => {
  withFetch(t, async () => new Response(
    "<html><body>internal proxy stack trace</body></html>",
    { status: 502, statusText: "Bad Gateway", headers: { "content-type": "text/html" } },
  ));

  await assert.rejects(api.health(), {
    name: "Error",
    message: "API 502: Bad Gateway",
  });
});

test("bounds plain-text error response reads and displayed details", async (t) => {
  let cancelled = false;
  const payload = "x".repeat(20_000);
  withFetch(t, async () => new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(payload));
    },
    cancel() {
      cancelled = true;
    },
  }), {
    status: 503,
    statusText: "Service Unavailable",
    headers: { "content-type": "text/plain" },
  }));

  await assert.rejects(api.health(), (error) => {
    assert.match(error.message, /^API 503: x+/);
    assert.ok(error.message.length <= 1_020);
    assert.ok(error.message.endsWith("…"));
    return true;
  });
  assert.equal(cancelled, true);
});

test("cancels successful non-JSON response bodies before reporting a contract error", async (t) => {
  let cancelled = false;
  withFetch(t, async () => new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode("upstream diagnostic page"));
    },
    cancel() {
      cancelled = true;
    },
  }), {
    status: 200,
    headers: { "content-type": "text/html" },
  }));

  await assert.rejects(api.health(), {
    name: "Error",
    message: "API 200: expected a JSON response",
  });
  assert.equal(cancelled, true);
});

test("rejects malformed JSON success responses with a stable error", async (t) => {
  withFetch(t, async () => new Response(
    "{not-json",
    { status: 200, headers: { "content-type": "application/json" } },
  ));

  await assert.rejects(api.health(), {
    name: "Error",
    message: "API 200: invalid or empty JSON response",
  });
});
