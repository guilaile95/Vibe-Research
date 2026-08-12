import type { TodayActions } from "@/lib/decisionCockpit";

export type DecisionPriorityKind = "holding-action" | "holding-flag" | "watchlist-flag";

export type DecisionPriorityItem = {
  key: string;
  kind: DecisionPriorityKind;
  code: string;
  name: string;
  label: string;
  detail: string;
  changePct: number | null;
  pnlPct: number | null;
  href: "/portfolio" | "/watchlist";
  score: number;
};

const PASSIVE_ACTIONS = new Set(["", "hold", "watch", "none", "保持", "持有", "观察", "观望"]);

function clean(value: string | null | undefined): string {
  return String(value || "").trim();
}

export function isExplicitAction(value: string | null | undefined): boolean {
  const action = clean(value);
  return action.length > 0 && !PASSIVE_ACTIONS.has(action.toLowerCase());
}

export function buildDecisionPriorities(data: TodayActions | null | undefined): DecisionPriorityItem[] {
  if (!data) return [];
  const items: Array<DecisionPriorityItem & { order: number }> = [];
  let order = 0;

  for (const holding of data.holdings || []) {
    const action = clean(holding.advice_action);
    const flags = (holding.flags || []).map(clean).filter(Boolean);
    if (isExplicitAction(action)) {
      items.push({
        key: `holding-action:${holding.code}`,
        kind: "holding-action",
        code: holding.code,
        name: holding.name,
        label: action,
        detail: flags.length ? flags.join(" · ") : holding.plan_signals_summary || "后端存在显式持仓动作",
        changePct: holding.change_pct ?? null,
        pnlPct: holding.pnl_pct ?? null,
        href: "/portfolio",
        score: 300 + Math.min(flags.length, 9),
        order: order++,
      });
      continue;
    }
    if (flags.length) {
      items.push({
        key: `holding-flag:${holding.code}`,
        kind: "holding-flag",
        code: holding.code,
        name: holding.name,
        label: "持仓提醒",
        detail: flags.join(" · "),
        changePct: holding.change_pct ?? null,
        pnlPct: holding.pnl_pct ?? null,
        href: "/portfolio",
        score: 200 + Math.min(flags.length, 9),
        order: order++,
      });
    }
  }

  for (const mover of data.watchlist_movers || []) {
    const flag = clean(mover.flag);
    if (!flag) continue;
    items.push({
      key: `watchlist:${mover.code}:${flag}`,
      kind: "watchlist-flag",
      code: mover.code,
      name: mover.name,
      label: "自选提醒",
      detail: flag,
      changePct: mover.change_pct ?? null,
      pnlPct: null,
      href: "/watchlist",
      score: 100,
      order: order++,
    });
  }

  return items
    .sort((a, b) => b.score - a.score || a.order - b.order)
    .map(({ order: _order, ...item }) => item);
}
