import { useEffect, useRef, useState } from "react";
import { api, type CampaignAIDraftGenerateResult } from "@/lib/api";
import { loadLlm, LLM_CHANGED_EVENT } from "@/lib/llm";

/** Consent is per invocation, bound to an exact local context and model snapshot. */
export function CampaignAIDraftButton({ campaignId, contextIdentity, disabled, onResult, onError, onBusyChange }: {
  campaignId: string; contextIdentity: string; disabled: boolean;
  onResult: (result: CampaignAIDraftGenerateResult) => void;
  onError: (message: string) => void; onBusyChange: (busy: boolean) => void;
}) {
  const [busy, setBusy] = useState(false);
  const active = useRef<AbortController | null>(null);
  const scope = JSON.stringify([campaignId, contextIdentity, disabled]);
  const latest = useRef(scope); latest.current = scope;
  useEffect(() => {
    const invalidate = () => { active.current?.abort(); active.current = null; setBusy(false); onBusyChange(false); };
    window.addEventListener("storage", invalidate);
    window.addEventListener(LLM_CHANGED_EVENT, invalidate);
    return () => { window.removeEventListener("storage", invalidate); window.removeEventListener(LLM_CHANGED_EVENT, invalidate); invalidate(); };
  }, [scope]);
  const generate = async () => {
    if (disabled || active.current) return;
    const llm = loadLlm();
    if (!llm || !campaignId) { onError("请先配置模型，并确保投资计划上下文可用。"); return; }
    let destination: string;
    try {
      if (llm.provider === "cli-codex") {
        destination = "OpenAI Codex Subscription（通过当前已登录的本地 runtime）";
      } else {
        const url = new URL(llm.baseURL);
        if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error("invalid");
        destination = url.origin + url.pathname;
      }
    } catch { onError("无法确认模型接收地址，请先检查模型设置。"); return; }
    const modelIdentity = JSON.stringify(llm);
    const owner = new AbortController(); active.current = owner; setBusy(true); onBusyChange(true); onError("");
    const owns = () => active.current === owner && !owner.signal.aborted && latest.current === scope && JSON.stringify(loadLlm()) === modelIdentity;
    try {
      const receipt = await api.previewCampaignAIDraftConsent(campaignId, owner.signal);
      if (!owns()) return;
      if (!receipt || typeof receipt !== "object" || Array.isArray(receipt)
        || Object.keys(receipt).sort().join(",") !== "campaign_id,context_fingerprint,scope"
        || typeof receipt.campaign_id !== "string" || receipt.campaign_id !== campaignId
        || receipt.scope !== "FULL_HOLDINGS_ACCOUNT_CAMPAIGN_THESIS_CRITICAL_DATA"
        || typeof receipt.context_fingerprint !== "string" || !/^[a-f0-9]{64}$/.test(receipt.context_fingerprint)) throw new Error("私人上下文确认回执无效，未调用模型。");
      if (!window.confirm(`生成本次 AI 草稿将向 ${destination}（${llm.provider} / ${llm.model}）发送当前完整持仓快照（全部证券、数量和成本）、账户资金与资产数据，以及投资计划 ${campaignId} 的当前投资逻辑、证据和风险上下文。范围包含整个账户，不仅是所选证券。数据将原样发送给你配置的模型服务；仅生成可编辑草稿，不创建正式决策。是否同意本次发送？`)) return;
      if (!owns()) return;
      const result = await api.generateCampaignAIDraft(campaignId, llm, receipt.context_fingerprint, owner.signal);
      if (owns()) onResult(result);
    } catch (error) {
      if (owns()) onError(error instanceof Error ? error.message : "AI 草稿生成失败。");
    } finally {
      if (active.current === owner) { active.current = null; setBusy(false); onBusyChange(false); }
    }
  };
  return <button type="button" disabled={disabled || busy} onClick={() => void generate()} className="inline-flex items-center gap-1.5 rounded-md border border-primary/50 px-3 py-2 text-xs font-medium hover:bg-muted disabled:opacity-50" data-testid="generate-ai-draft">{busy ? "正在核对 / 生成…" : "生成 AI 草稿"}</button>;
}
