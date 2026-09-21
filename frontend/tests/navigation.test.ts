import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  NAV_ENTRIES,
  NAV_GROUPS,
  ROUTE_OWNERS,
  SECTION_NAVS,
  activeSectionItem,
  entriesInGroup,
  matchRoute,
  sectionNavsOf,
} from "../src/lib/navigation.ts";

/** 直接读取路由声明，避免「加了路由但忘了归属」悄悄溜过去。 */
const routerSource = readFileSync(new URL("../src/router.tsx", import.meta.url), "utf8");
const declaredRoutes = [...routerSource.matchAll(/path:\s*"([^"]+)"/g)].map((match) => match[1]);

test("router declarations are fully and uniquely owned", () => {
  assert.equal(declaredRoutes.length, 37, `router.tsx 应声明 37 条路由，实际 ${declaredRoutes.length}`);

  const patterns = ROUTE_OWNERS.map((item) => item.pattern);
  assert.equal(new Set(patterns).size, patterns.length, "归属表存在重复 pattern");

  for (const path of declaredRoutes) {
    const owned = ROUTE_OWNERS.filter((item) => item.pattern === path);
    assert.equal(owned.length, 1, `路由 ${path} 应恰好有一个归属，实际 ${owned.length}`);
  }
  for (const item of ROUTE_OWNERS) {
    assert.ok(
      declaredRoutes.includes(item.pattern),
      `归属表里的 ${item.pattern} 不在 router.tsx 中声明`,
    );
  }
});

test("navigation exposes exactly the ten approved entries in group order", () => {
  assert.deepEqual(
    NAV_ENTRIES.map((entry) => `${entry.label}=${entry.to}`),
    [
      "今天=/daily-review",
      "决策待办=/decision-inbox",
      "自选股=/watchlist",
      "投资研究=/screener",
      "研究资料=/thesis",
      "我的持仓=/portfolio",
      "交易记录=/trades",
      "决策复盘=/decision-performance",
      "数据健康=/data-health",
      "设置=/settings",
    ],
  );
  assert.deepEqual(NAV_GROUPS.map((group) => group.label), ["工作", "研究", "账户与复盘", "系统"]);
  assert.deepEqual(entriesInGroup("work").map((entry) => entry.label), ["今天", "决策待办"]);
  assert.deepEqual(entriesInGroup("research").map((entry) => entry.label), ["自选股", "投资研究", "研究资料"]);
  assert.deepEqual(entriesInGroup("account").map((entry) => entry.label), ["我的持仓", "交易记录", "决策复盘"]);
  assert.deepEqual(entriesInGroup("system").map((entry) => entry.label), ["数据健康", "设置"]);
});

test("every route resolves to its approved owner and name", () => {
  const cases: [string, string, string][] = [
    ["/", "today", "今天"],
    ["/daily-review", "today", "今天"],
    ["/market-cloud", "today", "市场全景"],
    ["/market-history", "today", "北向成交额历史"],
    ["/decision-inbox", "decision", "决策待办"],
    ["/campaigns/campaign_abc/decision-proposal", "decision", "正式决策"],
    ["/watchlist", "watchlist", "自选股"],
    ["/screener", "research", "市场发现"],
    ["/stock-data", "research", "个股数据"],
    ["/candidates/600519", "research", "候选研究"],
    ["/sectors", "research", "板块研究"],
    ["/sectors/humanoid", "research", "板块研究"],
    ["/sectors/humanoid/overview", "research", "板块研究"],
    ["/intel", "research", "资讯中心"],
    ["/signals", "research", "产业信号"],
    ["/signals/gpu", "research", "产业信号"],
    ["/debate", "research", "多空辩论"],
    ["/portfolio", "portfolio", "我的持仓"],
    ["/trades", "trades", "交易记录"],
    ["/performance-attribution", "trades", "收益归因"],
    ["/decision-performance", "review", "决策复盘"],
    ["/thesis", "library", "投资逻辑"],
    ["/thesis/new", "library", "新建投资逻辑"],
    ["/thesis/th_1", "library", "投资逻辑详情"],
    ["/thesis/th_1/revision/3", "library", "投资逻辑历史版本"],
    ["/evidence", "library", "证据库"],
    ["/evidence/new", "library", "新建证据"],
    ["/evidence/ev_1", "library", "证据详情"],
    ["/my-reports", "library", "我的研报"],
    ["/notes", "library", "研究笔记"],
    ["/decision-evidence", "library", "建议依据追踪（旧版）"],
    ["/decision-feedback", "library", "建议采纳反馈（旧版）"],
    ["/signal-ledger", "library", "建议信号账本（旧版）"],
    ["/cockpit", "library", "决策驾驶舱（旧版）"],
    ["/data-health", "health", "数据健康"],
    ["/settings", "settings", "设置"],
    ["/account-policy", "settings", "执行参数"],
  ];
  for (const [path, owner, name] of cases) {
    const matched = matchRoute(path);
    assert.ok(matched, `${path} 未匹配到任何归属`);
    assert.equal(matched.owner, owner, `${path} 归属应为 ${owner}`);
    assert.equal(matched.name, name, `${path} 名称应为 ${name}`);
  }
});

test("dynamic detail routes win over their list route", () => {
  assert.equal(matchRoute("/thesis/new")?.name, "新建投资逻辑");
  assert.equal(matchRoute("/thesis/th_9")?.name, "投资逻辑详情");
  assert.equal(matchRoute("/thesis/th_9/revision/2")?.name, "投资逻辑历史版本");
  assert.equal(matchRoute("/signals/gpu")?.name, "产业信号", "带参数的 tab 与列表同名");
  assert.equal(matchRoute("/candidates/600519")?.owner, "research");
  assert.equal(matchRoute("/unknown-route"), null);
});

test("legacy analytical tools stay reachable in the research library", () => {
  const groups = sectionNavsOf("library");
  const legacy = groups.find((group) => group.label === "旧版分析工具");
  assert.ok(legacy, "研究资料应保留「旧版分析工具」目录");
  assert.deepEqual(
    legacy.items.map((item) => item.to),
    ["/decision-evidence", "/decision-feedback", "/signal-ledger", "/cockpit"],
  );
  for (const item of legacy.items) {
    assert.match(item.label, /（旧版）$/, `${item.to} 的旧版标识应在名称中`);
  }
});

test("watchlist is a top-level entry, not hidden inside research", () => {
  assert.equal(NAV_ENTRIES.find((entry) => entry.id === "watchlist")?.to, "/watchlist");
  for (const groups of Object.values(SECTION_NAVS)) {
    for (const group of groups) {
      assert.ok(
        !group.items.some((item) => item.to.startsWith("/watchlist")),
        "自选股不得出现在任何二级导航里",
      );
    }
  }
});

test("section activation prefers exact match then longest prefix", () => {
  const library = sectionNavsOf("library");
  assert.equal(activeSectionItem("/thesis", library), "/thesis");
  assert.equal(activeSectionItem("/thesis/new", library), "/thesis");
  assert.equal(activeSectionItem("/thesis/th_1", library), "/thesis");
  assert.equal(activeSectionItem("/evidence/ev_2", library), "/evidence");
  assert.equal(activeSectionItem("/cockpit", library), "/cockpit");
  assert.equal(activeSectionItem("/unknown", library), null);

  const research = sectionNavsOf("research");
  assert.equal(activeSectionItem("/screener", research), "/screener");
  assert.equal(activeSectionItem("/sectors/humanoid", research), "/sectors");
  assert.equal(activeSectionItem("/signals/gpu", research), "/signals");
  assert.equal(activeSectionItem("/debate", research), "/debate", "研究工具组的项同样激活");
  assert.equal(activeSectionItem("/candidates/600519", research), null, "候选研究不伪装成二级项");

  const trades = sectionNavsOf("trades");
  assert.equal(activeSectionItem("/trades", trades), "/trades");
  assert.equal(activeSectionItem("/performance-attribution", trades), "/performance-attribution");

  const settings = sectionNavsOf("settings");
  assert.equal(activeSectionItem("/settings", settings), "/settings");
  assert.equal(activeSectionItem("/account-policy", settings), "/account-policy");

  assert.deepEqual(sectionNavsOf("today"), []);
  assert.deepEqual(sectionNavsOf(null), []);
});
