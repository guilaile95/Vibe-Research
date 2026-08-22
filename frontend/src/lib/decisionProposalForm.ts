// Formal Decision Review 三视图结构化输入（P1-DF1）。
//
// 目的：普通用户不写 JSON 也能完成 Preview → Confirm → Freeze。
// 铁律：
// - backend contract 不变：asset_view / trade_view / portfolio_view 仍是
//   opaque JSON object（frozen_decision_service._validate_json_object），
//   下游（formal_trade_attribution / Decision Inbox）不解析其内部字段；
// - 生成的 object 保持既有页面模板骨架（{view, stance, note} /
//   {view, constraint}），不新增第二套 Decision model；
// - 表单只提供输入控件，绝不替用户决定 NBA / Asset / Trade / Portfolio 判断。
// - 选填字段留空时省略键（opaque object 允许任意键集），必不伪造空内容。

export const VIEW_STANCE_OPTIONS = ["WAIT", "SUPPORT", "OPPOSE"] as const;

export type ViewStance = (typeof VIEW_STANCE_OPTIONS)[number];

export const VIEW_STANCE_LABELS: Record<ViewStance, string> = {
  WAIT: "观望（默认，尚未形成倾向）",
  SUPPORT: "支持",
  OPPOSE: "反对",
};

const VIEW_NAMES = ["ASSET", "TRADE"] as const;

/** Asset / Trade View 共用结构：{view, stance[, note]}。 */
export function buildJudgedView(
  view: (typeof VIEW_NAMES)[number],
  stance: ViewStance,
  note: string,
): Record<string, unknown> {
  const trimmed = note.trim();
  return trimmed ? { view, stance, note: trimmed } : { view, stance };
}

/** Portfolio View 结构：{view[, constraint]}。 */
export function buildPortfolioView(constraint: string): Record<string, unknown> {
  const trimmed = constraint.trim();
  return trimmed ? { view: "PORTFOLIO", constraint: trimmed } : { view: "PORTFOLIO" };
}
