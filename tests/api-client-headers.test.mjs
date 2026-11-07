import test from "node:test";
import assert from "node:assert/strict";
import { mergeApiHeaders } from "../src/lib/api-headers.mjs";

test("API headers keep the JSON content type when caller headers are supplied", () => {
  const headers = mergeApiHeaders({ Authorization: "Bearer test-token", Accept: "application/json" });
  assert.equal(headers.get("content-type"), "application/json");
  assert.equal(headers.get("authorization"), "Bearer test-token");
  assert.equal(headers.get("accept"), "application/json");
});

test("API headers preserve an explicit caller content type case-insensitively", () => {
  const headers = mergeApiHeaders({ "content-type": "text/plain", "X-Request-ID": "request-1" });
  assert.equal(headers.get("Content-Type"), "text/plain");
  assert.equal(headers.get("x-request-id"), "request-1");
});

test("API header merging accepts Headers and tuple HeadersInit forms", () => {
  const source = new Headers([["Authorization", "Bearer tuple-token"]]);
  const fromHeaders = mergeApiHeaders(source);
  const fromTuples = mergeApiHeaders([["X-Client", "dataspace"], ["Accept", "application/json"]]);
  assert.equal(fromHeaders.get("authorization"), "Bearer tuple-token");
  assert.equal(fromHeaders.get("content-type"), "application/json");
  assert.equal(fromTuples.get("x-client"), "dataspace");
  assert.equal(fromTuples.get("content-type"), "application/json");
});

test("API header merging does not mutate the caller's header object", () => {
  const source = { Authorization: "Bearer immutable" };
  mergeApiHeaders(source);
  assert.deepEqual(source, { Authorization: "Bearer immutable" });
});
