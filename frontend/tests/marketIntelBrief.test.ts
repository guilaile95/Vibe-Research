import assert from "node:assert/strict";
import test from "node:test";
import type { NativeIntelItem } from "../src/lib/api/types.ts";
import { selectResearchSourceItems } from "../src/lib/marketIntelBrief.ts";

function item(item_id: number, hint: string, title = "资讯标题"): NativeIntelItem {
  return {
    item_id, hint, title, url: `https://example.test/${item_id}`,
    source_id: `source-${item_id}`, first_seen_at: "2026-09-22T08:00:00+08:00",
    last_seen_at: "2026-09-22T09:00:00+08:00", observation_count: 1,
  };
}

test("brief selects explicit industry source hints without inferring relevance from titles", () => {
  const input = [
    item(1, "macro", "半导体股票大涨"), item(2, "semi"),
    item(3, "", "机器人上市公司"), item(4, "ai"), item(5, "unknown"),
  ];
  assert.deepEqual(selectResearchSourceItems(input).map((entry) => entry.item_id), [2, 4]);
});

test("brief preserves source order and objects, bounds results at four and leaves input untouched", () => {
  const input = [item(6, "tech"), item(3, "bio"), item(8, "energy"), item(1, "robot"), item(5, "space")];
  const original = [...input];
  const result = selectResearchSourceItems(input);
  assert.deepEqual(result.map((entry) => entry.item_id), [6, 3, 8, 1]);
  assert.equal(result[0], input[0]);
  assert.deepEqual(input, original);
});

test("general or unclassified feeds do not masquerade as research selections", () => {
  assert.deepEqual(selectResearchSourceItems([]), []);
  assert.deepEqual(selectResearchSourceItems([item(1, "macro"), item(2, "rss"), item(3, "AI")]), []);
});
