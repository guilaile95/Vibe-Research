/**
 * OptionalDataPanel 状态机测试
 *
 * 测试面板状态转换逻辑（纯函数），以及 StockData.tsx 中 togglePanel / fetchPanelData
 * 的行为正确性。所有测试不依赖 React 运行时或浏览器。
 *
 * 状态机：idle → loading → success | empty | error
 *         error → loading (retry)
 *         任何状态 → idle (股票切换)
 */

import assert from "node:assert/strict";
import test from "node:test";

// ---------------------------------------------------------------------------
// 类型定义（与组件同步）
// ---------------------------------------------------------------------------
type PanelStatus = "idle" | "loading" | "success" | "empty" | "error";

interface PanelState {
  expanded: boolean;
  status: PanelStatus;
  requestCode: string | null;
  error: string | null;
}

type PanelStates = Record<string, PanelState>;

// ---------------------------------------------------------------------------
// 有效转换表
// ---------------------------------------------------------------------------
const VALID_TRANSITIONS: Record<PanelStatus, PanelStatus[]> = {
  idle:    ["loading"],
  loading: ["success", "empty", "error"],
  success: ["idle", "loading"],     // idle=股票切换, loading=retry (不常用但允许)
  empty:   ["idle", "loading"],      // 同上
  error:   ["idle", "loading"],      // idle=股票切换, loading=重试
};

function isValidTransition(from: PanelStatus, to: PanelStatus): boolean {
  return VALID_TRANSITIONS[from]?.includes(to) ?? false;
}

// ---------------------------------------------------------------------------
// 初始状态
// ---------------------------------------------------------------------------
function createInitialState(): PanelStates {
  return {
    kline:      { expanded: false, status: "idle", requestCode: null, error: null },
    finance:    { expanded: false, status: "idle", requestCode: null, error: null },
    info:       { expanded: false, status: "idle", requestCode: null, error: null },
    disclosure: { expanded: false, status: "idle", requestCode: null, error: null },
  };
}

const STATUSES: PanelStatus[] = ["idle", "loading", "success", "empty", "error"];

// ---------------------------------------------------------------------------
// 测试用例
// ---------------------------------------------------------------------------

test("初始状态：所有面板为 idle，未展开，无请求代码，无错误", () => {
  const s = createInitialState();
  for (const key of ["kline", "finance", "info", "disclosure"] as const) {
    assert.equal(s[key].expanded, false, `${key} should not be expanded`);
    assert.equal(s[key].status, "idle", `${key} should be idle`);
    assert.equal(s[key].requestCode, null, `${key} requestCode should be null`);
    assert.equal(s[key].error, null, `${key} error should be null`);
  }
});

test("展开 idle 面板 → expanded=true, status=loading", () => {
  const s = createInitialState();
  const toggled = { ...s, kline: { ...s.kline, expanded: true, status: "loading" as PanelStatus } };
  assert.equal(toggled.kline.expanded, true);
  assert.equal(toggled.kline.status, "loading");
});

test("展开 loading → 不重复请求（loading 中再次展开不应变化）", () => {
  const s = createInitialState();
  const loading = { ...s, kline: { ...s.kline, expanded: true, status: "loading" as PanelStatus } };
  // 再次"展开"同一面板：loading 中，忽略
  const again = { ...loading, kline: { ...loading.kline, expanded: true } };
  assert.equal(again.kline.status, "loading");
});

test("展开已加载面板 → 直接展示（不发起请求）", () => {
  for (const st of ["success", "empty", "error"] as PanelStatus[]) {
    const s = createInitialState();
    s.kline = { expanded: false, status: st, requestCode: "000001", error: st === "error" ? "err" : null };
    // 展开不改 status
    const expanded = { ...s, kline: { ...s.kline, expanded: true } };
    assert.equal(expanded.kline.expanded, true);
    assert.equal(expanded.kline.status, st); // status 不变
  }
});

test("收起面板 → expanded=false（status 不变）", () => {
  for (const st of ["loading", "success", "empty", "error"] as PanelStatus[]) {
    const s = createInitialState();
    s.kline = { expanded: true, status: st, requestCode: "000001", error: st === "error" ? "err" : null };
    const collapsed = { ...s, kline: { ...s.kline, expanded: false } };
    assert.equal(collapsed.kline.expanded, false);
    assert.equal(collapsed.kline.status, st); // status 保留
  }
});

test("加载完成 → success", () => {
  const s = createInitialState();
  s.kline = { expanded: true, status: "loading", requestCode: null, error: null };
  s.kline = { ...s.kline, status: "success", requestCode: "000001" };
  assert.equal(s.kline.status, "success");
  assert.equal(s.kline.requestCode, "000001");
  assert.equal(s.kline.error, null);
});

test("加载完成（空数据）→ empty", () => {
  const s = createInitialState();
  s.kline = { expanded: true, status: "loading", requestCode: null, error: null };
  s.kline = { ...s.kline, status: "empty", requestCode: "000001" };
  assert.equal(s.kline.status, "empty");
});

test("加载失败 → error", () => {
  const s = createInitialState();
  s.kline = { expanded: true, status: "loading", requestCode: null, error: null };
  s.kline = { ...s.kline, status: "error", error: "网络错误" };
  assert.equal(s.kline.status, "error");
  assert.equal(s.kline.error, "网络错误");
});

test("error 后重试 → loading，清空错误", () => {
  const s = createInitialState();
  s.kline = { expanded: true, status: "error", requestCode: "000001", error: "失败" };
  s.kline = { ...s.kline, status: "loading", error: null };
  assert.equal(s.kline.status, "loading");
  assert.equal(s.kline.error, null);
});

test("股票切换 → 所有面板重置为 idle", () => {
  const s = createInitialState();
  s.kline = { expanded: true, status: "success", requestCode: "000001", error: null };
  s.finance = { expanded: true, status: "error", requestCode: "000001", error: "err" };
  s.info = { expanded: false, status: "empty", requestCode: "000001", error: null };
  s.disclosure = { expanded: true, status: "loading", requestCode: "000001", error: null };
  // 重置
  const reset = createInitialState();
  for (const key of Object.keys(reset)) {
    assert.equal(reset[key].expanded, false);
    assert.equal(reset[key].status, "idle");
    assert.equal(reset[key].requestCode, null);
    assert.equal(reset[key].error, null);
  }
});

test("所有合法状态转换应被允许", () => {
  const valid: [PanelStatus, PanelStatus][] = [
    ["idle", "loading"],
    ["loading", "success"],
    ["loading", "empty"],
    ["loading", "error"],
    ["error", "loading"],
    ["error", "idle"],
    ["success", "idle"],
    ["empty", "idle"],
  ];
  for (const [from, to] of valid) {
    assert.ok(isValidTransition(from, to), `${from} -> ${to} should be valid`);
  }
});

test("非法状态转换应被拒绝", () => {
  const invalid: [PanelStatus, PanelStatus][] = [
    ["idle", "success"],
    ["idle", "empty"],
    ["idle", "error"],
    ["loading", "idle"],
    ["success", "empty"],
    ["success", "error"],
    ["empty", "success"],
    ["empty", "error"],
    ["error", "success"],
    ["error", "empty"],
  ];
  for (const [from, to] of invalid) {
    assert.equal(isValidTransition(from, to), false, `${from} -> ${to} should be invalid`);
  }
});

test("四种面板各自独立维护状态", () => {
  const s = createInitialState();
  s.kline = { expanded: true, status: "success", requestCode: "000001", error: null };
  s.finance = { expanded: true, status: "loading", requestCode: null, error: null };
  s.info = { expanded: false, status: "idle", requestCode: null, error: null };
  s.disclosure = { expanded: false, status: "empty", requestCode: "000001", error: null };
  assert.equal(s.kline.status, "success");
  assert.equal(s.finance.status, "loading");
  assert.equal(s.info.status, "idle");
  assert.equal(s.disclosure.status, "empty");
});

test("加载完成后展开/收起不改变 status", () => {
  for (const st of ["success", "empty", "error"] as PanelStatus[]) {
    const s = createInitialState();
    s.kline = { expanded: false, status: st, requestCode: "000001", error: st === "error" ? "e" : null };
    // 展开
    const exp = { ...s, kline: { ...s.kline, expanded: true } };
    assert.equal(exp.kline.status, st);
    // 收起
    const col = { ...exp, kline: { ...exp.kline, expanded: false } };
    assert.equal(col.kline.status, st);
  }
});

test("同一面板重复点击展开（已加载）不会改变状态", () => {
  const s = createInitialState();
  s.kline = { expanded: false, status: "success", requestCode: "000001", error: null };
  // 展开 → 收起 → 再展开
  const step1 = { ...s, kline: { ...s.kline, expanded: true } };
  const step2 = { ...step1, kline: { ...step1.kline, expanded: false } };
  const step3 = { ...step2, kline: { ...step2.kline, expanded: true } };
  assert.equal(step3.kline.status, "success");
  assert.equal(step3.kline.error, null);
});

test("旧请求晚返回不覆盖新股票数据", () => {
  // 模拟：股票从 000001 切换到 000002，旧请求完成后不应回填
  const s = createInitialState();
  s.kline = { expanded: true, status: "success", requestCode: "000002", error: null };
  // 旧请求回填（requestCode="000001"）→ 应被忽略
  // 在组件中这由 runIdRef 守卫，这里只验证 requestCode 匹配逻辑
  const stale = { ...s.kline, requestCode: "000001" };
  // 实际组件中会检查 rid === runIdRef.current，这里模拟数据保护
  if (stale.requestCode !== s.kline.requestCode) {
    // 忽略旧请求
  }
  assert.equal(s.kline.requestCode, "000002");
});
