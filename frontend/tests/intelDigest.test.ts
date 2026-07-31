import assert from "node:assert/strict";
import test from "node:test";

import {
  buildDigestSourceRefs,
  buildDigestInputItems,
  shouldSaveDigest,
  digestStatusBadge,
  isSectorMatch,
} from "../src/lib/intelDigestView.ts";

test("buildDigestSourceRefs and buildDigestInputItems slice top 25 items", () => {
  const mockItems = Array.from({ length: 30 }, (_, i) => ({
    title: `Title ${i}`,
    source: `Source ${i}`,
    url: `https://example.com/${i}`,
    time: `2026-07-31 10:0${i % 10}`,
    zh: `中文 ${i}`,
  }));

  const refs = buildDigestSourceRefs(mockItems);
  assert.equal(refs.length, 25);
  assert.equal(refs[0].title, "中文 0");
  assert.equal(refs[0].url, "https://example.com/0");

  const inputs = buildDigestInputItems(mockItems);
  assert.equal(inputs.length, 25);
  assert.equal(inputs[0].published_at, "2026-07-31 10:00");
  assert.equal(inputs[0].title, "中文 0");
});

test("shouldSaveDigest rejects empty or whitespace-only texts", () => {
  assert.equal(shouldSaveDigest(""), false);
  assert.equal(shouldSaveDigest("   \n\t "), false);
  assert.equal(shouldSaveDigest(null), false);
  assert.equal(shouldSaveDigest(undefined), false);
  assert.equal(shouldSaveDigest("- Valid bullet point"), true);
});

test("digestStatusBadge formatting", () => {
  assert.deepEqual(digestStatusBadge(true, false), { text: "已保存", kind: "saved" });
  assert.deepEqual(digestStatusBadge(true, true), { text: "已去重", kind: "deduped" });
  assert.deepEqual(digestStatusBadge(false, false), { text: "", kind: "none" });
  assert.deepEqual(digestStatusBadge(undefined, undefined), { text: "", kind: "none" });
});

test("isSectorMatch detects sector switch race condition", () => {
  assert.equal(isSectorMatch("ai", "ai"), true);
  assert.equal(isSectorMatch("ai", "semiconductor"), false);
});

test("stream resolve contract: empty/aborted/errored stream does not trigger save", async () => {
  let savedCalled = false;
  const mockSaveApi = async () => {
    savedCalled = true;
    return { digest: null, deduped: false };
  };

  // 1. Errored stream throws -> save NOT called
  const erroredStream = async () => {
    throw new Error("Stream error");
  };

  try {
    const text = await erroredStream();
    if (shouldSaveDigest(text)) {
      await mockSaveApi();
    }
  } catch {
    /* expected stream error handling */
  }
  assert.equal(savedCalled, false);

  // 2. Empty stream -> save NOT called
  const emptyStream = async () => "";
  const emptyText = await emptyStream();
  if (shouldSaveDigest(emptyText)) {
    await mockSaveApi();
  }
  assert.equal(savedCalled, false);

  // 3. Normal stream -> save called after resolve
  const validStream = async () => "- Point 1\n- Point 2";
  const validText = await validStream();
  if (shouldSaveDigest(validText)) {
    await mockSaveApi();
  }
  assert.equal(savedCalled, true);
});
