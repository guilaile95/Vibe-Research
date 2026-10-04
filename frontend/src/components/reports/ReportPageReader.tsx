import { reportPageReasons as reasons } from "@/lib/reportPageLabels";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { useEffect, useRef, useState } from "react";
import { api, type MyReport, type ReportPageReadResult, type ReportPageReadStatus } from "@/lib/api";

const labels: Record<ReportPageReadStatus, string> = {
  readable: "已返回正文", omitted: "预算省略", invalid: "无效页", unreadable: "正文不可用", error: "读取失败",
};


export function ReportPageReader({ reports }: { reports: MyReport[] }) {
  const [chosenId, setChosenId] = useState("");
  const [from, setFrom] = useState("1");
  const [to, setTo] = useState("1");
  const report = reports.find(r => r.id === chosenId) ?? reports[0];
  const scope = reports.map(r => `${r.id}:${r.file_sha256 ?? ""}`).sort().join(",");
  const key = `${scope}|${report?.id}|${from}|${to}`;
  const [state, setState] = useState<{ key: string; busy?: boolean; error?: string; result?: ReportPageReadResult }>({ key: "" });
  const generation = useRef(0);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => { generation.current++; abort.current?.abort(); }, [key]);
  const current = state.key === key ? state : undefined;
  const start = Number(from), end = Number(to);
  const validRange = /^\d+$/.test(from) && /^\d+$/.test(to) && Number.isSafeInteger(start) && Number.isSafeInteger(end)
    && start >= 1 && end <= 1000000 && end >= start && end - start < 200;
  const hasVersion = /^[0-9a-f]{64}$/.test(report?.file_sha256 ?? "");
  async function read() {
    if (!report || !validRange || !hasVersion || current?.busy) return;
    abort.current?.abort();
    const controller = new AbortController(); abort.current = controller;
    const id = ++generation.current;
    setState({ key, busy: true });
    try {
      const result = await api.readReportPages({ report_id: report.id, selected_report_ids: reports.map(r => r.id),
        expected_file_sha256: report.file_sha256!, page_from: start, page_to: end }, controller.signal);
      if (generation.current === id) setState({ key, result });
    } catch {
      if (generation.current === id) setState({ key, error: "读取失败，请检查页码范围或重试。" });
    }
  }
  if (!report) return null;
  return <details className="mb-4 rounded-lg border border-border/50 p-3" data-testid="report-page-reader">
    <summary className="cursor-pointer text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">读取所选资料指定页</summary>
    <p className="mt-2 text-xs text-muted-foreground">只读索引页文本，不代表读完整份报告或验证结论；不自动加入 AI 上下文。只有明确点击指定页 AI 入口并发送问题后，才重新校验并提供这些页的文本。每次请求最多 200 页，返回最多 8 页、12000 字符，每页最多 6000 字符。</p>
    <div className="my-3 flex flex-wrap items-end gap-2">
      <label className="min-w-0 flex-1 text-xs">所选报告<select aria-label="指定页报告" value={report.id} onChange={e => setChosenId(e.target.value)} className="mt-1 block w-full rounded border bg-background p-2">
        {reports.map(r => <option key={r.id} value={r.id}>{r.title || r.name}</option>)}
      </select></label>
      <label className="text-xs">起始页<input aria-label="起始页" inputMode="numeric" value={from} onChange={e => setFrom(e.target.value)} className="mt-1 block w-20 rounded border bg-background p-2" /></label>
      <label className="text-xs">结束页<input aria-label="结束页" inputMode="numeric" value={to} onChange={e => setTo(e.target.value)} className="mt-1 block w-20 rounded border bg-background p-2" /></label>
      <button type="button" onClick={read} disabled={!validRange || !hasVersion || current?.busy} className="rounded border px-3 py-2 text-sm disabled:opacity-50">{current?.busy ? "读取中…" : "读取指定页"}</button>
    </div>
    {!validRange && <p role="alert" className="text-xs text-destructive">请输入连续 1–200 页的正整数范围。</p>}
    {!hasVersion && <p className="text-xs text-muted-foreground">缺少已确认文件版本，请先建立正文索引并刷新列表。</p>}
    {current?.error && <p role="alert">{current.error}</p>}
    {current?.result && <section aria-label="指定页读取结果" className="space-y-3 text-xs">
      <p className="break-all">源 SHA256：{current.result.file_sha256} · 返回 {current.result.returned_chars} 个 Unicode 字符</p>
      <p>{Object.entries(current.result.coverage).map(([status, pages]) => `${labels[status as ReportPageReadStatus]} ${pages.length} 页`).join(" · ")}</p>
      {current.result.coverage.readable.length > 0 && current.result.coverage.error.length === 0 && <div className="rounded border border-border/50 p-2">
        <p className="mb-2">可选择只用当前这份报告第 {start}–{end} 页问 AI；其他已选报告不会自动加入。沿用现有模型配置，可能消耗其额度。</p>
        <AskAiButton
          label="用这些指定页问 AI"
          context="用户明确选择当前报告的指定页。仅使用服务端重新校验后提供的页文本；区分事实、冲突与推断。"
          scopeKey="explicit-report-pages"
          reportIds={[report.id]}
          reportPageContext={{ report_id: report.id, expected_file_sha256: report.file_sha256!, page_from: start, page_to: end }}
          suggestions={["概括这些指定页，并说明未覆盖范围", "检查这些页是否包含更正、冲突或反证"]}
        />
      </div>}
      {current.result.items.map(item => <article key={item.page} className="rounded border border-border/40 p-2">
        <h3 className="font-medium">第 {item.page} 页 · {labels[item.status]}{item.truncated ? " · 部分正文" : ""}</h3>
        <p className="text-muted-foreground">{reasons[item.reason] ?? "正文不可用，请检查原始文件"}{item.returned_chars != null ? `（${item.returned_chars}/${item.indexed_chars} 字符）` : ""}</p>
        {item.text && <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words font-sans text-sm">{item.text}</pre>}
      </article>)}
    </section>}
  </details>;
}
