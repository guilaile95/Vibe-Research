import type { AiGeneratedResult, DailyReviewAiPayload } from "@/lib/api/types";
import { basisComponents, basisStatuses, validatedReviewBasis } from "@/lib/dailyReviewBasis";

export function DailyReviewAiBasis({ result, currentTradeDate, currentCutoff }: {
  result: AiGeneratedResult<DailyReviewAiPayload>;
  currentTradeDate: string | null;
  currentCutoff: string | null;
}) {
  const basis = validatedReviewBasis(result);
  const legacy = result.schema_version === "daily_review_ai.v1" && !result.payload.input_basis;
  const different = result.trade_date !== currentTradeDate || result.payload.source_data_cutoff !== currentCutoff;
  return <details className="mt-3 rounded-lg border border-border/60 p-3 text-xs text-muted-foreground" data-testid="daily-review-ai-basis">
    <summary className="cursor-pointer font-medium">生成输入依据与缺口</summary>
    <p className="mt-2">结果格式：{result.schema_version}</p>
    <p>当前页面交易日：{currentTradeDate || "未知"} · 当前页面数据截止：{currentCutoff || "未知"}</p>
    {different && <p className="mt-1 text-amber-700 dark:text-amber-300">当前页面与结果依据日期或截止时间不同；当前页面数据不能为旧结果补证。</p>}
    {!basis ? <p className="mt-2">{legacy ? "此历史版本未记录生成输入的组件状态和缺口快照，无法从当前页面追溯补齐。" : "生成输入依据不可核对；不使用当前页面替代，不将此结果标为已验证事实。"}</p> : <>
      <p className="mt-2">输入格式：{basis.context_schema_version} · 复盘数据格式：{basis.review_schema_version || "未记录"}</p>
      <p>生成时整体状态：{basisStatuses[basis.review_status]} · 输入警告 {basis.warning_count} 条 · 未知项 {basis.unknown_count} 条</p>
      <ul className="mt-2 grid gap-x-4 gap-y-1 sm:grid-cols-2">
        {Object.entries(basisComponents).map(([key, label]) => <li key={key}>{label}：{basisStatuses[basis.component_statuses[key]]}</li>)}
      </ul>
      {basis.omitted_component_count > 0 && <p>另有 {basis.omitted_component_count} 项未识别组件，仅计数，未保存任意名称。</p>}
      <p className="mt-2 break-all">上下文身份 SHA-256：{basis.context_sha256}</p>
      <p className="mt-2">快照仅来自本次实际生成输入。警告与未知项只保存数量，不保存原始错误文本；未记录逐供应商来源。哈希不证明数据真实、完整或结论正确，也不覆盖完整提示词和用户请求。</p>
    </>}
  </details>;
}
