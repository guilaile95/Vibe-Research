// P1-TRUX1：Trade 创建 → 归属续接的行为测试（页面源码契约断言）。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function createSubmitRegion(source: string): string {
  const start = source.indexOf("const handleCreateSubmit");
  const end = source.indexOf("// 作废操作");
  assert.ok(start > -1 && end > start, "handleCreateSubmit region must exist");
  return source.slice(start, end);
}

test("创建成功后使用真实 TradeRecord 关闭表单并自动选中", () => {
  const source = readFileSync(new URL("../src/pages/Trades.tsx", import.meta.url), "utf8");
  const region = createSubmitRegion(source);
  assert.match(region, /const created = await api\.createTrade\(payload\)/);
  assert.match(region, /setIsCreateOpen\(false\)/);
  assert.match(region, /setSelectedTradeId\(created\.trade_id\)/);
});

test("创建续接路径不自动归属、不自动 UNPLANNED、不自动写引用", () => {
  const source = readFileSync(new URL("../src/pages/Trades.tsx", import.meta.url), "utf8");
  const region = createSubmitRegion(source);
  assert.doesNotMatch(region, /attributeTrade|markTradeUnplanned/);
  // advice_ref / thesis_ref 只允许来自用户显式勾选的 draft（三元透传），不允许构造新引用
  assert.doesNotMatch(region, /advice_ref: \{|thesis_ref: \{/);
});

test("持久化成功但读取失败时保持诚实错误展示，不伪装创建失败", () => {
  const source = readFileSync(new URL("../src/pages/Trades.tsx", import.meta.url), "utf8");
  assert.match(source, /获取交易详情失败/);
  assert.match(source, /对账状态加载失败/);
  assert.match(source, /归属候选加载失败/);
  // 成功消息在创建 resolve 后立即设置，与后续读取结果无关
  assert.match(source, /交易流水创建成功，已打开该笔交易详情/);
});
