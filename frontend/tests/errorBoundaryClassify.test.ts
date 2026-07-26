/**
 * ErrorBoundary 错误分类纯函数单测
 */

import assert from "node:assert/strict";
import test from "node:test";
import {
  classifyError,
  isChunkLoadError,
} from "../src/components/common/errorBoundaryUtils.ts";

test("ChunkLoadError name is chunk", () => {
  const err = new Error("Loading failed");
  err.name = "ChunkLoadError";
  assert.equal(classifyError(err), "chunk");
  assert.equal(isChunkLoadError(err), true);
});

test("Failed to fetch dynamically imported module is chunk", () => {
  const err = new Error("Failed to fetch dynamically imported module: /assets/x.js");
  assert.equal(classifyError(err), "chunk");
});

test("Importing a module script failed is chunk", () => {
  const err = new Error("Importing a module script failed.");
  assert.equal(classifyError(err), "chunk");
});

test("Loading chunk failed is chunk", () => {
  const err = new Error("Loading chunk 5 failed.");
  assert.equal(classifyError(err), "chunk");
});

test("Loading chunk * failed pattern is chunk", () => {
  const err = new Error("Loading chunk foo-bar failed");
  assert.equal(classifyError(err), "chunk");
});

test("normal render error is render", () => {
  const err = new Error("Cannot read properties of undefined");
  assert.equal(classifyError(err), "render");
  assert.equal(isChunkLoadError(err), false);
});

test("null/undefined error is render", () => {
  assert.equal(classifyError(null), "render");
  assert.equal(classifyError(undefined), "render");
});
