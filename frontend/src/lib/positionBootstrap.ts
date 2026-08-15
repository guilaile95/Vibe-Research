// 账户初始化（P0-AB2）纯展示逻辑。全部只读、零副作用。
//
// 铁律（与 backend position_reality_service 对齐）：
// - legacy portfolio 只作为 BOOTSTRAP INPUT SUGGESTION：绝不自动 commit、
//   绝不修改 portfolio.json、绝不自动转换数据库；
// - LEGACY_POSITION_OPENING != BUY：绝不把现有持仓描述成历史买入；
// - PRE-VIBE 历史保持 UNKNOWN：不反推历史买入时间、不重建历史交易；
// - Preview 零写；Commit 必须复用「产生当前 Preview 的同一份 input payload」；
// - 409 冲突绝不提供 overwrite / reset 动作。

import type {
  PortfolioData,
  PositionBootstrapInput,
  PositionBootstrapPosition,
  PositionBootstrapPreview,
} from "./api/types";

export const POSITION_LEDGER_NOT_BOOTSTRAPPED =
  "POSITION_LEDGER_NOT_BOOTSTRAPPED";

/** legacy portfolio → 初始化持仓行（仅建议输入，用户必须再确认）。 */
export interface BootstrapPositionRow {
  code: string;
  name: string;
  shares: string;
  cost_basis: string;
}

/** 表单输入（数值均以字符串承载，允许中间态为空）。 */
export interface BootstrapFormState {
  ledger_start_at: string;
  opening_cash: string;
  note: string;
  positions: BootstrapPositionRow[];
}

export const PREFILL_NOTICE =
  "以下内容从当前持仓预填，仅作为初始化输入，请确认后再提交。";

export const ANTI_BUY_NOTICE =
  "这不是历史买入记录，不会把现有持仓伪造成 BUY。";

export const CONFIRM_CHECKBOX_LABEL =
  "我确认这些是 Vibe 启用时的实际持仓快照；此前交易历史保持未知，不重建为历史 BUY。";

/** 是否显示 Bootstrap Activation Card：canonical=false 且原因精确为
 *  POSITION_LEDGER_NOT_BOOTSTRAPPED；其它 noncanonical 原因绝不显示。 */
export function shouldShowBootstrapCard(snapshot: {
  canonical: boolean;
  reason_codes: readonly string[];
}): boolean {
  return (
    snapshot.canonical === false
    && snapshot.reason_codes.includes(POSITION_LEDGER_NOT_BOOTSTRAPPED)
  );
}

/** legacy portfolio holdings → 表单预填行。只做映射，绝不写任何状态。 */
export function prefillPositionsFromPortfolio(
  portfolio: PortfolioData | null | undefined,
): BootstrapPositionRow[] {
  if (!portfolio || !Array.isArray(portfolio.holdings)) return [];
  return portfolio.holdings
    .filter((holding) => holding && typeof holding.code === "string")
    .map((holding) => ({
      code: String(holding.code),
      name: typeof holding.name === "string" ? holding.name : "",
      shares:
        typeof holding.shares === "number" && Number.isFinite(holding.shares)
          ? String(holding.shares)
          : "",
      cost_basis:
        typeof holding.cost === "number" && Number.isFinite(holding.cost)
          ? String(holding.cost)
          : "",
    }));
}

/**
 * 表单 → 归一化 bootstrap input payload。
 * 任何不完整/非法字段 → null（Preview 被拒绝；backend 仍是最终校验权威）。
 */
export function parseBootstrapInput(
  form: BootstrapFormState,
): PositionBootstrapInput | null {
  const ledgerStart = form.ledger_start_at.trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(ledgerStart)) return null;

  const positions: PositionBootstrapPosition[] = [];
  for (const row of form.positions) {
    const code = row.code.trim();
    if (!/^[0-9]{6}$/.test(code)) return null;
    const shares = Number(row.shares);
    if (!Number.isInteger(shares) || shares < 1) return null;
    const name = row.name.trim() || undefined;
    let costBasis: number | undefined;
    const costText = row.cost_basis.trim();
    if (costText !== "") {
      const cost = Number(costText);
      if (!Number.isFinite(cost) || cost < 0) return null;
      costBasis = cost;
    }
    // 固定键序（与类型字段序一致），保证 payload 相等性判断确定性。
    positions.push({
      code,
      ...(name ? { name } : {}),
      shares,
      ...(costBasis !== undefined ? { cost_basis: costBasis } : {}),
    });
  }

  let openingCash: number | undefined;
  const openingText = form.opening_cash.trim();
  if (openingText !== "") {
    const opening = Number(openingText);
    if (!Number.isFinite(opening) || opening < 0) return null;
    openingCash = opening;
  }
  const note = form.note.trim() || undefined;

  return {
    ledger_start_at: ledgerStart,
    ...(openingCash !== undefined ? { opening_cash: openingCash } : {}),
    ...(note ? { note } : {}),
    positions,
  };
}

/** 两个归一化 payload 是否完全一致（决定 PREVIEW_INVALIDATED 与 commit 门）。 */
export function bootstrapInputsEqual(
  a: PositionBootstrapInput | null,
  b: PositionBootstrapInput | null,
): boolean {
  if (a === null || b === null) return a === b;
  return JSON.stringify(a) === JSON.stringify(b);
}

export interface BootstrapGateState {
  /** 最近一次成功的 preview 结果。 */
  preview: PositionBootstrapPreview | null;
  /** 产生当前 preview 的那份归一化 input payload。 */
  previewedInput: PositionBootstrapInput | null;
  /** 当前表单的归一化 payload。 */
  currentInput: PositionBootstrapInput | null;
  /** 用户显式勾选确认。 */
  confirmed: boolean;
}

/** Preview 成功后表单有任何修改 → PREVIEW_INVALIDATED=YES（必须重新 Preview）。 */
export function previewInvalidated(state: BootstrapGateState): boolean {
  return (
    state.preview !== null
    && !bootstrapInputsEqual(state.previewedInput, state.currentInput)
  );
}

/** 显式 Commit 门：PREVIEW_SUCCESS + 当前输入 == 已预览输入 + 用户确认。 */
export function canCommitBootstrap(state: BootstrapGateState): boolean {
  return (
    state.preview !== null
    && state.currentInput !== null
    && bootstrapInputsEqual(state.previewedInput, state.currentInput)
    && state.confirmed
  );
}

/** Preview 门：归一化 payload 可用即可发起（ledger_start_at 为空 → null → 禁用）。 */
export function canPreviewBootstrap(input: PositionBootstrapInput | null): boolean {
  return input !== null;
}

/** Commit 实际发送的 payload：必须等于产生当前 Preview 的同一份 input。 */
export function commitPayload(
  state: BootstrapGateState,
): PositionBootstrapInput | null {
  if (!canCommitBootstrap(state)) return null;
  return state.previewedInput;
}

export interface BootstrapErrorDescription {
  message: string;
  /** true = 409 已初始化冲突：只提示 + 重新读取，绝不提供覆盖/重置。 */
  conflict: boolean;
}

/** 409 提示不包含任何 overwrite/reset 动作文案。 */
export const BOOTSTRAP_CONFLICT_MESSAGE =
  "账户事实已经初始化，请重新查看最新状态。";

export function describeBootstrapCommitError(err: unknown): BootstrapErrorDescription {
  if (
    err !== null
    && typeof err === "object"
    && "status" in err
    && (err as { status: unknown }).status === 409
  ) {
    return { conflict: true, message: BOOTSTRAP_CONFLICT_MESSAGE };
  }
  if (err instanceof Error && err.message) {
    return { conflict: false, message: err.message };
  }
  return { conflict: false, message: "初始化失败，请重试" };
}
