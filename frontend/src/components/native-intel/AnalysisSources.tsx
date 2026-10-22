import type { NativeIntelAiAnalysisResponse, NativeIntelAnalysisCoverage } from "../../lib/api/types";
import { safeAnalysisSourceUrl, analysisCoverageReason } from "../../lib/analysisSources";

const sectionNames = { hotlist: "热榜", rss: "RSS", standalone: "独立展示区" };

/** A persisted input snapshot, not claim-level citations or verification evidence. */
export function AnalysisSources({ analysis }: { analysis: NativeIntelAiAnalysisResponse }) {
  const snapshot = analysis.input_sources;
  if (!snapshot || snapshot.version !== 1 || snapshot.status !== "CAPTURED") {
    return <div className="text-xs text-muted-foreground" data-testid="analysis-sources-unknown">历史记录未保存本次来源清单，实际输入来源未知；不会用最新资讯补填。</div>;
  }
  const successful = analysis.status === "SUCCESS" && snapshot.submission_status === "RESPONSE_RECEIVED";
  return <details className="rounded-lg border border-border p-3 text-xs" data-testid="analysis-sources">
    <summary className="cursor-pointer font-medium">{successful ? "本次实际纳入来源清单" : "本次准备输入的来源清单"} · {snapshot.items.length} 条</summary>
    <p className="my-2 text-muted-foreground">{successful
      ? "这些条目的标题、摘要等可用字段纳入了首次分析输入；如有格式修复，仅处理原输出。不代表已读取原文、核实事实或为每条结论提供支持。"
      : snapshot.submission_status === "RESPONSE_RECEIVED"
        ? "模型已返回，但本次分析未成功完成；以下仅为输入快照，不是有效分析结论。"
        : "尚不能确认模型收到这些输入；以下仅为已准备的来源快照。"}</p>
    <p className="mb-2 text-muted-foreground">覆盖范围仅为本次报告候选与独立来源返回；源侧过滤、过期排除和采集限制不计为本次预算截断。</p>
    <ul className="mb-3 space-y-1 text-muted-foreground">
      {Object.entries(sectionNames).map(([key, label]) => {
        const coverage = snapshot.coverage[key as keyof typeof sectionNames] as NativeIntelAnalysisCoverage;
        return <li key={key}>{label}：纳入 {coverage.included} / {coverage.available ?? "未知"} 条；未纳入 {coverage.omitted ?? "未知"} 条（{analysisCoverageReason(coverage.reason)}）</li>;
      })}
    </ul>
    {snapshot.items.length === 0 && <p>本次输入没有资讯条目，不能据此判断市场无异常。</p>}
    <ol className="max-h-80 space-y-3 overflow-y-auto">
      {snapshot.items.map((item, index) => {
        const url = safeAnalysisSourceUrl(item.original_url);
        return <li key={`${item.section}:${item.id}:${index}`} className="break-words">
          <div>{index + 1}. {item.title || "标题未提供"}</div>
          <div className="text-muted-foreground">{sectionNames[item.section]} · {item.source_name || "来源未知"} · 源时间：{item.published_at || "未提供"}</div>
          <div className="text-muted-foreground">条目身份：{item.id}</div>
          {url ? <a className="text-primary underline" href={url} target="_blank" rel="noopener noreferrer">打开原文</a> : <span className="text-muted-foreground">未提供安全原文链接</span>}
        </li>;
      })}
    </ol>
  </details>;
}
