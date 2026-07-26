/**
 * OptionalDataPanel 生产状态机单测：仅导入 optionalDataPanelState 纯函数。
 */

import assert from "node:assert/strict";
import test from "node:test";
import {
  type PanelId,
  type PanelState,
  type PanelStates,
  canApplyPanelResult,
  createInitialPanelStates,
  resetPanelStates,
  resolvePanelError,
  resolvePanelSuccess,
  retryPanelState,
  startPanelRequest,
  togglePanelState,
} from "../src/components/ui/optionalDataPanelState.ts";

const PANEL_IDS: PanelId[] = ["kline", "finance", "info", "disclosure"];

function loadingState(code = "000001"): PanelState {
  return { expanded: true, status: "loading", requestCode: code, error: null };
}

// 1. initial
test("1. initial: all panels idle collapsed", () => {
  const s = createInitialPanelStates();
  for (const key of PANEL_IDS) {
    assert.equal(s[key].expanded, false);
    assert.equal(s[key].status, "idle");
    assert.equal(s[key].requestCode, null);
    assert.equal(s[key].error, null);
  }
});

// 2. idle expand -> loading + shouldFetch
test("2. idle expand -> loading + shouldFetch true", () => {
  const s = createInitialPanelStates();
  const { states, shouldFetch } = togglePanelState(s, "kline");
  assert.equal(shouldFetch, true);
  assert.equal(states.kline.expanded, true);
  assert.equal(states.kline.status, "loading");
  assert.equal(states.kline.error, null);
});

// 3. loading collapse / re-expand no re-fetch
test("3. loading collapse then re-expand does not re-fetch", () => {
  let s = createInitialPanelStates();
  ({ states: s } = togglePanelState(s, "kline"));
  s = startPanelRequest(s, "kline", "000001");
  assert.equal(s.kline.status, "loading");

  let shouldFetch: boolean;
  ({ states: s, shouldFetch } = togglePanelState(s, "kline")); // collapse
  assert.equal(shouldFetch, false);
  assert.equal(s.kline.expanded, false);
  assert.equal(s.kline.status, "loading");

  ({ states: s, shouldFetch } = togglePanelState(s, "kline")); // re-expand
  assert.equal(shouldFetch, false);
  assert.equal(s.kline.expanded, true);
  assert.equal(s.kline.status, "loading");
});

// 4. success expand/collapse
test("4. success expand/collapse keeps status, no fetch", () => {
  let s = createInitialPanelStates();
  s = startPanelRequest(s, "kline", "000001");
  s = resolvePanelSuccess(s, "kline", "000001", false)!;
  assert.equal(s.kline.status, "success");

  let shouldFetch: boolean;
  ({ states: s, shouldFetch } = togglePanelState(s, "kline")); // collapse
  assert.equal(shouldFetch, false);
  assert.equal(s.kline.expanded, false);
  assert.equal(s.kline.status, "success");

  ({ states: s, shouldFetch } = togglePanelState(s, "kline")); // expand
  assert.equal(shouldFetch, false);
  assert.equal(s.kline.expanded, true);
  assert.equal(s.kline.status, "success");
});

// 5. empty
test("5. empty result sets empty status", () => {
  let s = createInitialPanelStates();
  s = startPanelRequest(s, "finance", "000001");
  const next = resolvePanelSuccess(s, "finance", "000001", true);
  assert.ok(next);
  assert.equal(next!.finance.status, "empty");
  assert.equal(next!.finance.error, null);
});

// 6. error
test("6. error result sets error status and message", () => {
  let s = createInitialPanelStates();
  s = startPanelRequest(s, "info", "000001");
  const next = resolvePanelError(s, "info", "000001", "网络错误");
  assert.ok(next);
  assert.equal(next!.info.status, "error");
  assert.equal(next!.info.error, "网络错误");
});

// 7. error retry
test("7. error retry -> loading + shouldFetch", () => {
  let s = createInitialPanelStates();
  s = startPanelRequest(s, "disclosure", "000001");
  s = resolvePanelError(s, "disclosure", "000001", "失败")!;

  const { states, shouldFetch } = retryPanelState(s, "disclosure");
  assert.equal(shouldFetch, true);
  assert.equal(states.disclosure.status, "loading");
  assert.equal(states.disclosure.error, null);
  assert.equal(states.disclosure.expanded, true);
});

// 8. stock switch full reset
test("8. stock switch full reset via resetPanelStates", () => {
  let s = createInitialPanelStates();
  s = startPanelRequest(s, "kline", "000001");
  s = resolvePanelSuccess(s, "kline", "000001", false)!;
  s = startPanelRequest(s, "finance", "000001");
  s = resolvePanelError(s, "finance", "000001", "err")!;

  const reset = resetPanelStates();
  for (const key of PANEL_IDS) {
    assert.equal(reset[key].expanded, false);
    assert.equal(reset[key].status, "idle");
    assert.equal(reset[key].requestCode, null);
    assert.equal(reset[key].error, null);
  }
  // 与 initial 一致
  assert.deepEqual(reset, createInitialPanelStates());
});

// 9. input change without query: wrong activeCode rejected by canApply
test("9. input change without query: canApply rejects wrong activeCode", () => {
  const state = loadingState("000001");
  // 用户改了输入框但未查询：activeCode 仍是 000001；若误用输入 code 则守卫拒绝
  assert.equal(
    canApplyPanelResult(state, "000002", "000001", 1, 1),
    false,
    "requestCode 与 activeCode 不一致应拒绝",
  );
  assert.equal(
    canApplyPanelResult(state, "000001", "000001", 1, 1),
    true,
    "匹配 activeCode 应允许",
  );
});

// 10. old activeCode response rejected
test("10. old activeCode response rejected", () => {
  const state = loadingState("000002"); // 已切到新股并启动请求
  assert.equal(canApplyPanelResult(state, "000001", "000002", 2, 2), false);
  assert.equal(resolvePanelSuccess(
    { ...createInitialPanelStates(), kline: state },
    "kline",
    "000001",
    false,
  ), null);
});

// 11. old generation rejected
test("11. old generation rejected", () => {
  const state = loadingState("000001");
  assert.equal(canApplyPanelResult(state, "000001", "000001", 1, 2), false);
  assert.equal(canApplyPanelResult(state, "000001", "000001", 2, 2), true);
});

// 12. same panel previous request late return rejected
test("12. previous request late return rejected via requestCode mismatch", () => {
  let s = createInitialPanelStates();
  s = startPanelRequest(s, "kline", "000001");
  // 重试后绑定新 code（同股但新请求也可理解为新 binding；这里用不同 requestCode 模拟）
  s = startPanelRequest(s, "kline", "000001-retry");
  // 旧 request 回填
  assert.equal(resolvePanelSuccess(s, "kline", "000001", false), null);
  assert.equal(resolvePanelError(s, "kline", "000001", "late"), null);
  // 新 request 可回填
  const ok = resolvePanelSuccess(s, "kline", "000001-retry", false);
  assert.ok(ok);
  assert.equal(ok!.kline.status, "success");
});

// 13. four panels independent
test("13. four panels independent", () => {
  let s = createInitialPanelStates();
  let shouldFetch: boolean;

  ({ states: s, shouldFetch } = togglePanelState(s, "kline"));
  assert.equal(shouldFetch, true);
  s = startPanelRequest(s, "kline", "000001");
  s = resolvePanelSuccess(s, "kline", "000001", false)!;

  ({ states: s, shouldFetch } = togglePanelState(s, "finance"));
  assert.equal(shouldFetch, true);
  s = startPanelRequest(s, "finance", "000001");

  s = {
    ...s,
    info: { expanded: false, status: "idle", requestCode: null, error: null },
    disclosure: { expanded: false, status: "empty", requestCode: "000001", error: null },
  };

  assert.equal(s.kline.status, "success");
  assert.equal(s.finance.status, "loading");
  assert.equal(s.info.status, "idle");
  assert.equal(s.disclosure.status, "empty");

  // 只收起 finance 不影响 kline
  ({ states: s, shouldFetch } = togglePanelState(s, "finance"));
  assert.equal(s.finance.expanded, false);
  assert.equal(s.kline.expanded, true);
  assert.equal(s.kline.status, "success");
});

// resolve ignores non-loading
test("resolve ignores when panel not loading", () => {
  const s: PanelStates = createInitialPanelStates();
  assert.equal(resolvePanelSuccess(s, "kline", "000001", false), null);
  assert.equal(resolvePanelError(s, "kline", "000001", "x"), null);
});

// canApply requires loading status
test("canApply requires loading status and matching requestCode", () => {
  const success: PanelState = {
    expanded: true,
    status: "success",
    requestCode: "000001",
    error: null,
  };
  assert.equal(canApplyPanelResult(success, "000001", "000001", 1, 1), false);

  const loading: PanelState = loadingState("000001");
  assert.equal(canApplyPanelResult(loading, "000001", "000001", 1, 1), true);
  assert.equal(canApplyPanelResult(loading, "000002", "000002", 1, 1), false); // state.requestCode mismatch
});
