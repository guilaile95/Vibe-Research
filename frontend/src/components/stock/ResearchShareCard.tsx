import { useState } from "react";
import { researchShareCard, researchShareSvg, type ShareMetric } from "@/lib/researchShareCard";
import type { Valuation } from "@/lib/api";

export function ResearchShareCard({ valuation }: { valuation: Valuation }) {
  const [selected, setSelected] = useState<ShareMetric[]>(["price"]);
  const [message, setMessage] = useState("");
  let card: ReturnType<typeof researchShareCard> | null = null;
  try { card = researchShareCard(valuation, selected); } catch { /* Invalid/empty selection stays disabled. */ }
  function download(format: "json" | "svg") {
    if (!card) return;
    const blob = new Blob([format === "json" ? JSON.stringify(card, null, 2) : researchShareSvg(card)], {
      type: format === "json" ? "application/json" : "image/svg+xml",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a"); link.href = url;
    link.download = `public-research-${card.security_code}.${format}`;
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    setMessage("已生成本地下载；未发布或上传");
  }
  return <details className="mt-3 rounded border border-border/50 p-3" data-testid="research-share-card">
    <summary className="cursor-pointer text-sm">导出公开研究卡</summary>
    <p className="mt-2 text-xs text-muted-foreground">只包含下方勾选的公开行情字段和来源日期。请核对预览后下载；不会包含账户、持仓、日志、研究正文或私人路径。</p>
    <div className="my-3 flex flex-wrap gap-4">{([["price", "报价"], ["pe_ttm", "PE-TTM"], ["mcap_yi", "总市值"]] as const).map(([key, label]) => <label key={key} className="text-sm">
      <input type="checkbox" checked={selected.includes(key)} onChange={e => { setSelected(values => e.target.checked ? [...values, key] : values.filter(v => v !== key)); setMessage(""); }} /> {label}
    </label>)}</div>
    <div aria-label="研究卡预览" className="space-y-1 break-words text-xs">
      <p>证券 {card?.security_code ?? "无效"} · {card?.data_kind} · 来源观察，未独立核验</p>
      {card?.facts.map(f => <p key={f.metric}>{f.label}：{f.value ?? "缺失"} {f.unit} · 来源 {f.source} {f.source_field} · as-of {f.as_of ?? "未知"}</p>)}
      <p>报价日期不代表估值日期；来源时间未知不能以下载时间代替。不是投资建议。</p>
    </div>
    <div className="mt-3 flex flex-wrap gap-2">
      <button type="button" disabled={!card} onClick={() => download("svg")} className="rounded border px-3 py-2 text-xs disabled:opacity-50">下载研究卡 SVG</button>
      <button type="button" disabled={!card} onClick={() => download("json")} className="rounded border px-3 py-2 text-xs disabled:opacity-50">下载公开数据 JSON</button>
    </div>
    {message && <p role="status" className="mt-2 text-xs">{message}</p>}
  </details>;
}
