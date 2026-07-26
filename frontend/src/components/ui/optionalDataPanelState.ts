// 可选扩展面板状态机（纯函数，可单测）
// idle → loading → success | empty | error
// error → loading（仅 retryPanelState）
// 任意状态 → idle（resetPanelStates / 换股）

export type PanelId = "kline" | "finance" | "info" | "disclosure";

export type PanelStatus = "idle" | "loading" | "success" | "empty" | "error";

export interface PanelState {
  expanded: boolean;
  status: PanelStatus;
  /** 发起请求时绑定的股票代码，用于结果回填校验 */
  requestCode: string | null;
  error: string | null;
}

export type PanelStates = Record<PanelId, PanelState>;

const EMPTY_PANEL: PanelState = {
  expanded: false,
  status: "idle",
  requestCode: null,
  error: null,
};

export function createInitialPanelStates(): PanelStates {
  return {
    kline: { ...EMPTY_PANEL },
    finance: { ...EMPTY_PANEL },
    info: { ...EMPTY_PANEL },
    disclosure: { ...EMPTY_PANEL },
  };
}

/** 换股时全量重置 */
export function resetPanelStates(): PanelStates {
  return createInitialPanelStates();
}

/**
 * 展开/收起：
 * - idle 展开 → loading + shouldFetch
 * - success/empty/error 展开 → 仅 expanded，不 fetch
 * - loading 再展开 → 不 fetch
 * - 任意状态收起 → expanded=false，status 不变
 */
export function togglePanelState(
  states: PanelStates,
  key: PanelId,
): { states: PanelStates; shouldFetch: boolean } {
  const current = states[key];

  if (current.expanded) {
    return {
      states: {
        ...states,
        [key]: { ...current, expanded: false },
      },
      shouldFetch: false,
    };
  }

  if (current.status === "idle") {
    return {
      states: {
        ...states,
        [key]: {
          ...current,
          expanded: true,
          status: "loading",
          error: null,
        },
      },
      shouldFetch: true,
    };
  }

  // loading / success / empty / error：只展开，不重新请求
  return {
    states: {
      ...states,
      [key]: { ...current, expanded: true },
    },
    shouldFetch: false,
  };
}

/** 正式发起请求前写入 binding（expanded + loading + requestCode） */
export function startPanelRequest(
  states: PanelStates,
  key: PanelId,
  requestCode: string,
): PanelStates {
  return {
    ...states,
    [key]: {
      ...states[key],
      expanded: true,
      status: "loading",
      requestCode,
      error: null,
    },
  };
}

/** 成功回填；requestCode 与面板当前绑定不一致则忽略 */
export function resolvePanelSuccess(
  states: PanelStates,
  key: PanelId,
  requestCode: string,
  isEmpty: boolean,
): PanelStates | null {
  const current = states[key];
  if (current.status !== "loading" || current.requestCode !== requestCode) {
    return null;
  }
  return {
    ...states,
    [key]: {
      ...current,
      status: isEmpty ? "empty" : "success",
      error: null,
    },
  };
}

/** 失败回填；code 不匹配则忽略 */
export function resolvePanelError(
  states: PanelStates,
  key: PanelId,
  requestCode: string,
  error: string,
): PanelStates | null {
  const current = states[key];
  if (current.status !== "loading" || current.requestCode !== requestCode) {
    return null;
  }
  return {
    ...states,
    [key]: {
      ...current,
      status: "error",
      error,
    },
  };
}

/** 仅从 error 显式重试 */
export function retryPanelState(
  states: PanelStates,
  key: PanelId,
): { states: PanelStates; shouldFetch: boolean } {
  const current = states[key];
  return {
    states: {
      ...states,
      [key]: {
        ...current,
        expanded: true,
        status: "loading",
        error: null,
      },
    },
    shouldFetch: true,
  };
}

/**
 * 竞态守卫：generation 一致 + 请求 code 等于当前 activeCode +
 * 面板仍处于 loading 且 requestCode 匹配本次请求。
 */
export function canApplyPanelResult(
  state: PanelState,
  requestCode: string,
  activeCode: string,
  requestGeneration: number,
  currentGeneration: number,
): boolean {
  return (
    requestGeneration === currentGeneration &&
    requestCode === activeCode &&
    state.status === "loading" &&
    state.requestCode === requestCode
  );
}
