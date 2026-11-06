import assert from "node:assert/strict";
import test from "node:test";

import { safeNextPath } from "./auth-navigation.mjs";

test("keeps valid dataspace return paths and query state", () => {
  assert.equal(safeNextPath("/dataspace?view=3d#canvas"), "/dataspace?view=3d#canvas");
  assert.equal(safeNextPath("/dataspace/objects/123"), "/dataspace/objects/123");
});

test("rejects external, protocol-relative, and non-workspace redirects", () => {
  for (const value of [
    "https://attacker.example",
    "//attacker.example",
    "/login",
    "/register",
    "/settings",
    "/dataspace/../login",
    "/dataspace%2f..%2flogin",
    "/\\\\attacker.example",
  ]) {
    assert.equal(safeNextPath(value), "/dataspace", `unsafe redirect: ${value}`);
  }
});

test("uses the workspace as the default for missing or malformed input", () => {
  assert.equal(safeNextPath(null), "/dataspace");
  assert.equal(safeNextPath(undefined), "/dataspace");
  assert.equal(safeNextPath(""), "/dataspace");
});
