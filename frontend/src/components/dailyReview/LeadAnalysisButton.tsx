import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, Sparkles, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ApiError, streamNdjson } from "@/lib/api";
import { loadLlm } from "@/lib/llm";
import type { LeadAnalysisContext, LeadKind } from "@/lib/leadAnalysisContext";

const factLabels: Record<string, string> = {
  change_pct: "涨跌幅（%）", amount: "成交额（元）", price: "价格（元）", turnover_pct: "换手率（%）",
  zt_count: "涨停家数", dt_count: "跌停家数", max_boards: "最高连板数", seal_rate: "封板率（小数比率）",
  break_rate: "炸板率（小数比率）", lianban_count: "连板家数",
};

export function LeadAnalysisButton({ kind, subject = null, label }: { kind: LeadKind; subject?: string | null; label: string }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [complete, setComplete] = useState(false);
  const [content, setContent] = useState("");
  const [context, setContext] = useState<LeadAnalysisContext | null>(null);
  const [error, setError] = useState("");
  const [needsConfig, setNeedsConfig] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const active = useRef<AbortController | null>(null);

  useEffect(() => { if (open) dialog.current?.showModal(); }, [open]);
  useEffect(() => () => { active.current?.abort(); active.current = null; }, []);

  function close() {
    active.current?.abort();
    active.current = null;
    setLoading(false);
    setOpen(false);
  }

  async function analyze() {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setOpen(true); setLoading(true); setComplete(false); setContent(""); setContext(null); setError("");
    const llm = loadLlm();
    setNeedsConfig(!llm);
    if (!llm) { setLoading(false); active.current = null; return; }
    let receivedContext = false;
    let sourceError = "";
    const alive = () => active.current === controller && !controller.signal.aborted;
    try {
      const result = await streamNdjson("/daily-review/lead-analysis", { kind, subject, llm }, {
        onLeadContext: (value) => {
          if (!alive()) return;
          if (receivedContext || value.kind !== kind || value.subject.code !== subject) {
            sourceError = "返回的线索对象不一致，请刷新页面后重试";
            throw new ApiError(sourceError, 502);
          }
          receivedContext = true;
          setContext(value);
        },
        onDelta: (text) => {
          if (!alive()) return;
          if (!receivedContext) {
            sourceError = "未收到线索来源，分析已停止";
            throw new ApiError(sourceError, 502);
          }
          setContent((current) => current + text);
        },
      }, controller.signal);
      if (alive()) {
        if (!receivedContext || !result.content.trim()) throw new ApiError("分析未返回完整内容", 502);
        setComplete(true);
      }
    } catch (cause) {
      if (alive()) {
        setError(sourceError || (cause instanceof ApiError ? cause.message : "线索分析失败，请稍后重试"));
        controller.abort();
      }
    } finally {
      if (active.current === controller) { active.current = null; setLoading(false); }
    }
  }

  return <>
    <button type="button" className="inline-flex items-center gap-1 py-2 text-xs text-primary hover:underline" onClick={() => void analyze()} aria-label={`AI 梳理${label}`}><Sparkles className="h-3 w-3" />梳理线索</button>
    {open && <dialog ref={dialog} onCancel={(event) => { event.preventDefault(); close(); }} className="m-auto max-h-[90vh] w-[calc(100%-2rem)] max-w-2xl overflow-auto rounded-xl border border-border bg-background p-0 text-foreground shadow-xl backdrop:bg-black/50" aria-label={`${label}线索分析`} data-testid="lead-analysis-dialog">
      <div className="sticky top-0 flex items-center justify-between gap-3 border-b border-border bg-background p-4">
        <div><h2 className="font-semibold">{label} · AI 梳理</h2><p className="mt-1 text-xs text-muted-foreground">按本条线索整理事实、可能解释和待核对问题。</p></div>
        <button type="button" onClick={close} className="rounded p-2 hover:bg-muted" aria-label="关闭线索分析"><X className="h-4 w-4" /></button>
      </div>
      <div className="space-y-4 p-4">
        {needsConfig && <p className="text-sm">先在<Link to="/settings" onClick={close} className="text-primary hover:underline">设置中接入 AI</Link>，再分析这条线索。</p>}
        {context && <section className="rounded-lg border border-border bg-muted/30 p-3 text-xs" data-testid="lead-analysis-source">
          <p className="font-medium">分析对象：{context.subject.name}{context.subject.code ? `（${context.subject.code}）` : ""}</p>
          <p className="mt-1">来源状态：{({ normal: "数值可用", partial: "部分数据可用", stale: "历史结果", unavailable: "不可用", error: "读取失败" } as Record<string, string>)[context.source.status] || "未知"}</p>
          <p className="mt-1">源交易日 {context.source.trade_date || "未提供"} · 行情时间 {context.source.data_time || "未提供"}</p>
          {(context.cache_stale === true || context.source.is_stale === true) && <p className="mt-1 text-warning">使用上次结果 · 时效待核验</p>}
          <details className="mt-2"><summary className="cursor-pointer">核对实际输入与缺口</summary>
            <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
              {Object.entries(context.facts).map(([key, value]) => <div key={key} className="contents"><dt>{factLabels[key] || key}</dt><dd className="break-words">{value === null ? "未知" : String(value)}</dd></div>)}
            </dl>
            <ul className="mt-2 list-disc space-y-1 pl-4">{context.unknowns.map((item, index) => <li key={index}>{item}</li>)}</ul>
            <p className="mt-2 break-all text-muted-foreground">来源：{context.source.source || "未提供"} · 字段：{context.source_path}</p>
            <p className="mt-1">抓取时间 {context.source.fetched_at || "未提供"}；复盘生成 {context.review_generated_at || "未知"}。两者均不替代行情时间。</p>
          </details>
        </section>}
        {loading && <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />正在读取服务器线索并分析…<button type="button" className="ml-auto text-primary" onClick={() => { active.current?.abort(); active.current = null; setLoading(false); setError("已停止；当前片段不是完整分析。"); }}>停止</button></p>}
        {error && <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{error}</p>}
        {content && <div data-testid="lead-analysis-answer" data-state={complete ? "complete" : "incomplete"}>
          <p className="mb-2 text-xs text-muted-foreground">{complete ? "非正式 AI 草稿" : "未完成的分析片段"} · 不自动保存为研究证据或今日复盘</p>
          <div className="prose prose-sm max-w-none break-words dark:prose-invert"><ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown></div>
        </div>}
        {!loading && !needsConfig && <button type="button" onClick={() => void analyze()} className="rounded border border-border px-3 py-2 text-xs">重新读取并分析</button>}
      </div>
    </dialog>}
  </>;
}
