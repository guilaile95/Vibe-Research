/**
 * R5：Campaign 已提交正式决定的只读入口（放在 Decision Inbox 的
 * 「正在建立的 Campaign」卡片内）。展示不激活 Campaign、不产生持仓；
 * 内容来自不可变 Frozen Decision 读取接口，读取失败如实显示为失败。
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, listCommittedDecisions, type CommittedDecisionsListResult } from "@/lib/api";

export function CampaignCommittedDecisionsCard({ campaignId }: { campaignId: string }) {
  const [state, setState] = useState<{
    loading: boolean;
    error: string | null;
    data: CommittedDecisionsListResult | null;
  }>({ loading: true, error: null, data: null });

  useEffect(() => {
    let active = true;
    setState({ loading: true, error: null, data: null });
    listCommittedDecisions(campaignId)
      .then((result) => {
        if (active) setState({ loading: false, error: null, data: result });
      })
      .catch((cause) => {
        if (!active) return;
        setState({
          loading: false,
          error: cause instanceof ApiError ? cause.message : "已提交决定读取失败",
          data: null,
        });
      });
    return () => { active = false; };
  }, [campaignId]);

  if (state.loading) return null;
  if (state.error) {
    return (
      <div
        role="alert"
        data-testid={`campaign-committed-decisions-error-${campaignId}`}
        className="rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-1.5 text-xs text-destructive"
      >
        已提交决定读取失败：{state.error}。这不代表没有已提交决定。
      </div>
    );
  }
  if (!state.data || state.data.items.length === 0) return null;

  return (
    <div
      data-testid={`campaign-committed-decisions-${campaignId}`}
      className="rounded-lg border border-border/60 bg-background/35 p-3 text-xs space-y-2"
    >
      <p className="text-sm font-semibold">已提交的正式决定（{state.data.total}）</p>
      <p className="text-muted-foreground">
        「已作决定」≠「已发生交易」：以下决定尚未记录对应成交，Campaign 也未因此激活。
        打开详情可查看决定提交时的完整依据。
      </p>
      <ul className="space-y-1.5">
        {state.data.items.map((item) => (
          <li key={item.decision_id} className="rounded bg-muted/30 px-2 py-1.5 space-y-0.5">
            <p className="font-mono">{item.decision_id}</p>
            <p className="text-muted-foreground">
              提交时间：{item.committed_at || "未知"}
              {item.review_by ? ` · 复核期限：${item.review_by}` : ""}
              {item.next_best_action ? ` · 当时结论：${item.next_best_action}` : ""}
              {item.validity_status_at_commit ? ` · 提交时有效性：${item.validity_status_at_commit}` : ""}
            </p>
            <Link
              className="inline-block text-primary underline"
              to={`/campaigns/${campaignId}/decision-proposal`}
            >
              查看详情（含当时依据）→
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
