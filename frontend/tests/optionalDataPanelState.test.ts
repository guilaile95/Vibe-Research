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

function loadingState(code = "000001", requestId = 1): PanelState {
  return {
    expanded: true,
    status: "loading",
    requestCode: code,
    requestId,
    error: null,
  };
}

// 1. initial
test("1. initial: all panels idle collapsed", () => {
  const s = createInitialPanelStates();
  for (const key of PANEL_IDS) {
    assert.equal(s[key].expanded, false);
    assert.equal(s[key].status, "idle");
    assert.equal(s[key].requestCode, null);
    assert.equal(s[key].requestId, null);
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
  // toggle 不发明 requestId
  assert.equal(states.kline.requestId, null);
});

// 3. loading collapse / re-expand no re-fetch
test("3. loading collapse then re-expand does not re-fetch", () => {
  let s = createInitialPanelStates();
  ({ states: s } = togglePanelState(s, "kline"));
  s = startPanelRequest(s, "kline", "000001", 1);
  assert.equal(s.kline.status, "loading");
  assert.equal(s.kline.requestId, 1);

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
  s = startPanelRequest(s, "kline", "000001", 1);
  s = resolvePanelSuccess(s, "kline", "000001", 1, false)!;
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
  s = startPanelRequest(s, "finance", "000001", 1);
  const next = resolvePanelSuccess(s, "finance", "000001", 1, true);
  assert.ok(next);
  assert.equal(next!.finance.status, "empty");
  assert.equal(next!.finance.error, null);
});

// 6. error
test("6. error result sets error status and message", () => {
  let s = createInitialPanelStates();
  s = startPanelRequest(s, "info", "000001", 1);
  const next = resolvePanelError(s, "info", "000001", 1, "网络错误");
  assert.ok(next);
  assert.equal(next!.info.status, "error");
  assert.equal(next!.info.error, "网络错误");
});

// 7. error retry
test("7. error retry -> loading + shouldFetch", () => {
  let s = createInitialPanelStates();
  s = startPanelRequest(s, "disclosure", "000001", 1);
  s = resolvePanelError(s, "disclosure", "000001", 1, "失败")!;

  const { states, shouldFetch } = retryPanelState(s, "disclosure");
  assert.equal(shouldFetch, true);
  assert.equal(states.disclosure.status, "loading");
  assert.equal(states.disclosure.error, null);
  assert.equal(states.disclosure.expanded, true);
  // retry 不发明新 requestId（仍为旧 id，直至 startPanelRequest）
  assert.equal(states.disclosure.requestId, 1);
});

// 8. stock switch full reset
test("8. stock switch full reset via resetPanelStates", () => {
  let s = createInitialPanelStates();
  s = startPanelRequest(s, "kline", "000001", 1);
  s = resolvePanelSuccess(s, "kline", "000001", 1, false)!;
  s = startPanelRequest(s, "finance", "000001", 2);
  s = resolvePanelError(s, "finance", "000001", 2, "err")!;

  const reset = resetPanelStates();
  for (const key of PANEL_IDS) {
    assert.equal(reset[key].expanded, false);
    assert.equal(reset[key].status, "idle");
    assert.equal(reset[key].requestCode, null);
    assert.equal(reset[key].requestId, null);
    assert.equal(reset[key].error, null);
  }
  // 与 initial 一致
  assert.deepEqual(reset, createInitialPanelStates());
});

// 9. input change without query: wrong activeCode rejected by canApply
test("9. input change without query: canApply rejects wrong activeCode", () => {
  const state = loadingState("000001", 1);
  // 用户改了输入框但未查询：activeCode 仍是 000001；若误用输入 code 则守卫拒绝
  assert.equal(
    canApplyPanelResult(state, "000002", "000001", 1, 1, 1),
    false,
    "requestCode 与 activeCode 不一致应拒绝",
  );
  assert.equal(
    canApplyPanelResult(state, "000001", "000001", 1, 1, 1),
    true,
    "匹配 activeCode 应允许",
  );
});

// 10. old activeCode response rejected
test("10. old activeCode response rejected", () => {
  const state = loadingState("000002", 2); // 已切到新股并启动请求
  assert.equal(canApplyPanelResult(state, "000001", "000002", 2, 2, 2), false);
  assert.equal(resolvePanelSuccess(
    { ...createInitialPanelStates(), kline: state },
    "kline",
    "000001",
    1,
    false,
  ), null);
});

// 11. old generation rejected
test("11. old generation rejected", () => {
  const state = loadingState("000001", 1);
  assert.equal(canApplyPanelResult(state, "000001", "000001", 1, 2, 1), false);
  assert.equal(canApplyPanelResult(state, "000001", "000001", 2, 2, 1), true);
});

// 12. same stock, two requestIds: stale id rejected, latest wins
test("12. same activeCode two requestIds: resolve id=1 null, id=2 success", () => {
  let s = createInitialPanelStates();
  s = startPanelRequest(s, "kline", "000001", 1);
  assert.equal(s.kline.requestId, 1);
  // 同股再次请求（如 retry / StrictMode 二次调度），绑定新 requestId
  s = startPanelRequest(s, "kline", "000001", 2);
  assert.equal(s.kline.requestCode, "000001");
  assert.equal(s.kline.requestId, 2);
  assert.equal(s.kline.status, "loading");

  // 旧 requestId=1 回填必须拒绝
  assert.equal(resolvePanelSuccess(s, "kline", "000001", 1, false), null);
  assert.equal(resolvePanelError(s, "kline", "000001", 1, "late"), null);

  // 新 requestId=2 可回填
  const ok = resolvePanelSuccess(s, "kline", "000001", 2, false);
  assert.ok(ok);
  assert.equal(ok!.kline.status, "success");
  assert.equal(ok!.kline.requestId, 2);
});

// 12b. canApply rejects stale requestId even when code/generation/activeCode match
test("12b. canApply rejects stale requestId when code/generation match", () => {
  const state = loadingState("000001", 2); // 当前绑定 id=2
  assert.equal(
    canApplyPanelResult(state, "000001", "000001", 1, 1, 1),
    false,
    "stale requestId=1 must be rejected",
  );
  assert.equal(
    canApplyPanelResult(state, "000001", "000001", 1, 1, 2),
    true,
    "current requestId=2 must be allowed",
  );
});

// 12c. delayed A then B: only B applied (A delayed success returns null)
test("12c. delayed A after B success: only B applied, A returns null", () => {
  let s = createInitialPanelStates();
  // start A (id=1)
  s = startPanelRequest(s, "kline", "000001", 1);
  // start B (id=2) — supersedes A
  s = startPanelRequest(s, "kline", "000001", 2);
  // B success
  const afterB = resolvePanelSuccess(s, "kline", "000001", 2, false);
  assert.ok(afterB);
  assert.equal(afterB!.kline.status, "success");
  assert.equal(afterB!.kline.requestId, 2);
  s = afterB!;
  // A delayed success → null; state remains B's success
  assert.equal(resolvePanelSuccess(s, "kline", "000001", 1, false), null);
  assert.equal(s.kline.status, "success");
  assert.equal(s.kline.requestId, 2);
});

// 13. four panels independent
test("13. four panels independent", () => {
  let s = createInitialPanelStates();
  let shouldFetch: boolean;

  ({ states: s, shouldFetch } = togglePanelState(s, "kline"));
  assert.equal(shouldFetch, true);
  s = startPanelRequest(s, "kline", "000001", 1);
  s = resolvePanelSuccess(s, "kline", "000001", 1, false)!;

  ({ states: s, shouldFetch } = togglePanelState(s, "finance"));
  assert.equal(shouldFetch, true);
  s = startPanelRequest(s, "finance", "000001", 2);

  s = {
    ...s,
    info: { expanded: false, status: "idle", requestCode: null, requestId: null, error: null },
    disclosure: {
      expanded: false,
      status: "empty",
      requestCode: "000001",
      requestId: 3,
      error: null,
    },
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
  assert.equal(resolvePanelSuccess(s, "kline", "000001", 1, false), null);
  assert.equal(resolvePanelError(s, "kline", "000001", 1, "x"), null);
});

// canApply requires loading status
test("canApply requires loading status and matching requestCode/requestId", () => {
  const success: PanelState = {
    expanded: true,
    status: "success",
    requestCode: "000001",
    requestId: 1,
    error: null,
  };
  assert.equal(canApplyPanelResult(success, "000001", "000001", 1, 1, 1), false);

  const loading: PanelState = loadingState("000001", 1);
  assert.equal(canApplyPanelResult(loading, "000001", "000001", 1, 1, 1), true);
  assert.equal(canApplyPanelResult(loading, "000002", "000002", 1, 1, 1), false); // state.requestCode mismatch
});
