import type { NoteGeneration } from "@/lib/noteGeneration";
import { basisComponents, basisStatuses } from "@/lib/dailyReviewBasis";

export function NoteGenerationDetails({ generation }: { generation?: NoteGeneration }) {
  if (!generation) return <p className="mb-3 text-xs text-muted-foreground">历史记录未保存此信息：原结果身份、生成时间、模型及输入覆盖；保存时间不代表生成时间。</p>;
  const g = generation;
  const b = g.inputBasis;
  return <details className="mb-3 rounded border border-border/50 p-3 text-xs" data-testid="note-generation">
    <summary>原生成依据 · {g.tradeDate} · {g.generatedAt}</summary>
    <div className="mt-2 space-y-1 break-words">
      <p>结果身份线索（非服务唯一 ID）：{g.resultType} / {g.resultSchemaVersion} / {g.tradeDate} / {g.generatedAt}</p>
      <p>模型：{g.modelProvider} / {g.modelName}</p>
      <p>依据截止：{g.sourceDataCutoff ?? "未提供"}；原复盘生成：{g.sourceReviewGeneratedAt}</p>
      <p>保存时旧结果标记：{g.staleAtSave ? "是" : "否"}（不代表现在仍新鲜）</p>
      {b ? <>
        <p>输入覆盖：{basisStatuses[b.review_status]}；省略 {b.omitted_component_count} 项 / 警告 {b.warning_count} 项 / 未知 {b.unknown_count} 项</p>
        <p>{Object.entries(b.component_statuses).map(([key, status]) => `${basisComponents[key as keyof typeof basisComponents]}：${basisStatuses[status]}`).join("；")}</p>
        <p>上下文版本：{b.context_schema_version}；复盘版本：{b.review_schema_version ?? "未提供"}</p>
        <p>原输入 SHA-256：{b.context_sha256}</p>
      </> : <p>原结果未提供可校验的输入覆盖快照，不能认定输入完整。</p>}
      <p>此处为保存时的本地依据快照。原结果可能已被替换或删除，未检查其是否仍可访问；不会自动跳转到最新结果。身份线索及输入摘要不证明正文事实正确。</p>
    </div>
  </details>;
}
