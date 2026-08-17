import { ShieldAlert, ShieldCheck, ShieldQuestion, Info } from "lucide-react";
import type { DecisionInboxCampaignItem } from "@/lib/api/types";
import {
  hardRiskDisplay,
  type HardRiskTone,
} from "@/lib/hardRiskViewModel";
import { reasonCodeLabel } from "@/lib/decisionInbox";

/**
 * P0-HR1 HardRiskPanel：Decision Inbox Campaign 卡片的 Hard Risk 展示区。
 *
 * - 只消费 Hard Risk 专属 payload 字段（hard_risk_state /
 *   hard_risk_evaluation / hard_risk_reason_codes / hard_risk_authority_refs）。
 * - 严禁使用 item.reason_codes（Campaign-level generic）充当 Hard Risk
 *   reasons；严禁使用 item.authority_refs / explainability.authority_refs
 *   （generic projection provenance）充当 Hard Risk positive proof。
 * - 唯一绿色安全态 = backend 显式 positive-proof CLEAR；missing / null /
 *   UNKNOWN / NOT_EVALUATED / ERROR / 证据不足一律不绿。
 * - CONFIRMED 只表达「需要重新审查 Decision / Action Envelope」，
 *   绝不出现卖出 / 退出 / 清仓 / EXIT 文案，也不产生任何交易动作。
 */

const TONE_CLASS: Record<HardRiskTone, string> = {
  danger: "border-destructive/40 bg-destructive/5",
  safe: "border-success/40 bg-success/5",
  unknown: "border-warning/40 bg-warning/5",
  muted: "border-border/60 bg-muted/20",
};

const BADGE_CLASS: Record<HardRiskTone, string> = {
  danger: "bg-destructive/15 text-destructive",
  safe: "bg-success/15 text-success",
  unknown: "bg-warning/15 text-warning",
  muted: "bg-muted text-muted-foreground",
};

function ToneIcon({ tone }: { tone: HardRiskTone }) {
  if (tone === "danger") return <ShieldAlert className="h-3.5 w-3.5 shrink-0" />;
  if (tone === "safe") return <ShieldCheck className="h-3.5 w-3.5 shrink-0" />;
  return <ShieldQuestion className="h-3.5 w-3.5 shrink-0" />;
}

export function HardRiskPanel({ item }: { item: DecisionInboxCampaignItem }) {
  // 只把 Hard Risk 专属字段交给 view-model；generic reason/authority
  // （item.reason_codes / item.authority_refs / item.explainability）严禁传入。
  const view = hardRiskDisplay({
    hard_risk_state: item.hard_risk_state,
    hard_risk_evaluation: item.hard_risk_evaluation,
    hard_risk_reason_codes: item.hard_risk_reason_codes,
    hard_risk_authority_refs: item.hard_risk_authority_refs,
  });

  return (
    <section
      className={`rounded-lg border p-3 space-y-2 ${TONE_CLASS[view.tone]}`}
      data-hard-risk-state={item.hard_risk_state ?? "MISSING"}
      data-hard-risk-tone={view.tone}
      data-hard-risk-safe={view.showSafeGreen ? "true" : "false"}
      data-hard-risk-campaign={item.campaign_id}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">Hard Risk</span>
        <span
          className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium ${BADGE_CLASS[view.tone]}`}
        >
          <ToneIcon tone={view.tone} />
          {view.statusLabel}
          <span className="sr-only">{item.hard_risk_state ?? "MISSING"}</span>
        </span>
        {view.evaluationLabel && (
          <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
            {view.evaluationLabel}
          </span>
        )}
      </div>

      <p className="text-xs leading-5 text-foreground/90">{view.description}</p>

      {view.reasonCodes.length > 0 && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer select-none hover:text-foreground">
            评估说明（{view.reasonCodes.length}）
          </summary>
          <ul className="mt-1 space-y-0.5 font-mono text-[11px]">
            {view.reasonCodes.map((code) => (
              <li key={code}>
                {code}
                {reasonCodeLabel(code) !== code ? ` · ${reasonCodeLabel(code)}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}

      {view.authorityRefs.length > 0 && (
        <div className="text-xs text-muted-foreground">
          <p className="text-[11px]">Authority 引用：</p>
          <ul className="mt-0.5 space-y-0.5 font-mono text-[11px]">
            {view.authorityRefs.map((ref) => (
              <li key={ref}>{ref}</li>
            ))}
          </ul>
        </div>
      )}

      {view.tone === "safe" && (
        <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
          <Info className="h-3 w-3" aria-hidden="true" />
          显示为安全仅因为 backend 明确给出 positive-proof CLEAR。
        </p>
      )}
    </section>
  );
}
