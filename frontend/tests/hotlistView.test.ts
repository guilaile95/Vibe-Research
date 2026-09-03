import test from "node:test";
import assert from "node:assert/strict";
import {
  filterHotlistItems,
  formatRankDelta,
  formatStateBadge,
} from "../src/lib/hotlistView.ts";
import type { NativeIntelHotlistItem } from "../src/lib/api/types.ts";

test("formatRankDelta formats up, down, flat, and new arrivals honestly", () => {
  assert.deepEqual(formatRankDelta(undefined, null), { text: "新上榜", type: "new" });
  assert.deepEqual(formatRankDelta(null, null), { text: "新上榜", type: "new" });
  assert.deepEqual(formatRankDelta(0, 5), { text: "-", type: "flat" });
  assert.deepEqual(formatRankDelta(null, 5), { text: "-", type: "flat" });
  assert.deepEqual(formatRankDelta(3, 8), { text: "+3", type: "up" });
  assert.deepEqual(formatRankDelta(-4, 2), { text: "-4", type: "down" });
});

test("filterHotlistItems handles cls, wallstreetcn, rising, and new arrivals", () => {
  const sampleItems: NativeIntelHotlistItem[] = [
    {
      item_id: 1,
      title: "财联社热门第一条",
      url: "https://cls.cn/1",
      source_id: "hotlist-cls-hot",
      source_name: "财联社热门",
      hint: "macro",
      first_seen_at: "2026-09-03T10:00:00Z",
      last_seen_at: "2026-09-03T10:00:00Z",
      observation_count: 2,
      rank: 1,
      previous_rank: 3,
      rank_delta: 2,
      current_state: "ON_LIST",
    },
    {
      item_id: 2,
      title: "华尔街见闻头条",
      url: "https://wallstreetcn.com/2",
      source_id: "hotlist-wallstreetcn-hot",
      source_name: "华尔街见闻",
      hint: "macro",
      first_seen_at: "2026-09-03T10:00:00Z",
      last_seen_at: "2026-09-03T10:00:00Z",
      observation_count: 1,
      rank: 5,
      previous_rank: null,
      rank_delta: null,
      current_state: "ON_LIST",
    },
    {
      item_id: 3,
      title: "财联社下降条目",
      url: "https://cls.cn/3",
      source_id: "hotlist-cls-hot",
      source_name: "财联社热门",
      hint: "macro",
      first_seen_at: "2026-09-03T09:00:00Z",
      last_seen_at: "2026-09-03T10:00:00Z",
      observation_count: 2,
      rank: 10,
      previous_rank: 6,
      rank_delta: -4,
      current_state: "OFF_LIST",
    },
  ];

  assert.equal(filterHotlistItems(sampleItems, "all").length, 3);
  assert.equal(filterHotlistItems(sampleItems, "cls").length, 2);
  assert.equal(filterHotlistItems(sampleItems, "wallstreetcn").length, 1);
  assert.equal(filterHotlistItems(sampleItems, "rising").length, 1);
  assert.equal(filterHotlistItems(sampleItems, "rising")[0].item_id, 1);
  assert.equal(filterHotlistItems(sampleItems, "new").length, 1);
  assert.equal(filterHotlistItems(sampleItems, "new")[0].item_id, 2);
});

test("formatStateBadge maps all 4 rank states correctly", () => {
  assert.equal(formatStateBadge("ON_LIST").label, "在榜");
  assert.equal(formatStateBadge("OFF_LIST").label, "已掉榜");
  assert.equal(formatStateBadge("UNKNOWN").label, "源失败/未知");
  assert.equal(formatStateBadge("NO_RANK_SEMANTICS").label, "无排名");
});
