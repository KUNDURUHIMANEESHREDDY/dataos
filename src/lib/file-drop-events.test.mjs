import assert from "node:assert/strict";
import test from "node:test";

import { attachFileDropEvents } from "./file-drop-events.mjs";

class FakeTarget {
  listeners = new Map();

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) ?? new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type, listener) {
    this.listeners.get(type)?.delete(listener);
  }

  dispatch(type, event) {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

function fileEvent(files = []) {
  let prevented = false;
  return {
    dataTransfer: { types: ["Files"], files, dropEffect: "none" },
    preventDefault() { prevented = true; },
    get defaultPrevented() { return prevented; },
  };
}

test("initial file dragenter activates the overlay on the canvas parent", () => {
  const target = new FakeTarget();
  const states = [];
  const cleanup = attachFileDropEvents(target, {
    onDragStateChange: (value) => states.push(value),
    onFilesDrop: () => assert.fail("dragenter must not drop files"),
  });
  const event = fileEvent();

  target.dispatch("dragenter", event);

  assert.equal(event.defaultPrevented, true);
  assert.deepEqual(states, [true]);
  cleanup();
});

test("non-file drags do not activate the file drop target", () => {
  const target = new FakeTarget();
  const states = [];
  const cleanup = attachFileDropEvents(target, {
    onDragStateChange: (value) => states.push(value),
    onFilesDrop: () => assert.fail("non-file drag must not drop files"),
  });
  target.dispatch("dragenter", {
    dataTransfer: { types: ["text/plain"], files: [] },
    preventDefault() { assert.fail("non-file drag must not be prevented"); },
  });

  assert.deepEqual(states, []);
  cleanup();
});

test("nested dragleave events clear the overlay only after leaving the surface", () => {
  const target = new FakeTarget();
  const states = [];
  const cleanup = attachFileDropEvents(target, {
    onDragStateChange: (value) => states.push(value),
    onFilesDrop: () => assert.fail("dragleave must not drop files"),
  });
  target.dispatch("dragenter", fileEvent());
  target.dispatch("dragenter", fileEvent());
  target.dispatch("dragleave", fileEvent());
  assert.deepEqual(states, [true, true]);
  target.dispatch("dragleave", fileEvent());
  assert.deepEqual(states, [true, true, false]);
  cleanup();
});

test("drop prevents navigation, clears the overlay and forwards files once", () => {
  const target = new FakeTarget();
  const states = [];
  const files = [{ name: "data.csv" }];
  let received;
  const cleanup = attachFileDropEvents(target, {
    onDragStateChange: (value) => states.push(value),
    onFilesDrop: (value) => { received = value; },
  });
  target.dispatch("dragenter", fileEvent(files));
  const event = fileEvent(files);
  target.dispatch("drop", event);

  assert.equal(event.defaultPrevented, true);
  assert.deepEqual(states, [true, false]);
  assert.deepEqual(received, files);
  cleanup();
});

test("cleanup removes all registered drag listeners", () => {
  const target = new FakeTarget();
  const cleanup = attachFileDropEvents(target, {
    onDragStateChange: () => {},
    onFilesDrop: () => {},
  });
  cleanup();

  assert.deepEqual([...target.listeners.values()].map((set) => set.size), [0, 0, 0, 0]);
});
