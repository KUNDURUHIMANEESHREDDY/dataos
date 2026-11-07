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
    name: "ApiError",
    message: "API 404: Object not found",
  });
});

test("does not expose HTML error pages to callers", async (t) => {
  withFetch(t, async () => new Response(
    "<html><body>internal proxy stack trace</body></html>",
    { status: 502, statusText: "Bad Gateway", headers: { "content-type": "text/html" } },
  ));

  await assert.rejects(api.health(), {
    name: "ApiError",
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
    name: "ApiError",
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
    name: "ApiError",
    message: "API 200: invalid or empty JSON response",
  });
});


test("merges caller headers without dropping the default JSON content type", async (t) => {
  let requestHeaders;
  withFetch(t, async (_input, init) => {
    requestHeaders = new Headers(init?.headers);
    return new Response("[]", {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });

  await api.listObjects(undefined, {
    headers: new Headers([
      ["authorization", "Bearer test-token"],
      ["x-request-id", "request-123"],
    ]),
  });

  assert.equal(requestHeaders.get("content-type"), "application/json");
  assert.equal(requestHeaders.get("authorization"), "Bearer test-token");
  assert.equal(requestHeaders.get("x-request-id"), "request-123");
});

test("strips control characters from plain-text API errors", async (t) => {
  withFetch(t, async () => new Response(
    "safe\u0000text\u0007tail",
    { status: 502, headers: { "content-type": "text/plain" } },
  ));

  await assert.rejects(api.health(), (error) => {
    assert.equal(error.message, "API 502: safetexttail");
    return true;
  });
});
