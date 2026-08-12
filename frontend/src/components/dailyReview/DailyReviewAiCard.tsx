import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, Loader2, Sparkles } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { LazyMarkdownContent } from "@/components/ui/LazyMarkdownContent";
import { SaveNoteButton } from "@/components/ui/SaveNoteButton";
import { loadLlm } from "@/lib/llm";
import { useDailyReviewAiTaskStore } from "@/stores/dailyReviewAiTaskStore";

const formatDuration = (ms: number): string => {
  const totalSeconds = Math.max(0, Math.ceil(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes} 分 ${seconds} 秒` : `${seconds} 秒`;
};

const formatTime = (date: Date): string =>
  date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

interface DailyReviewAiCardProps {
  tradeDate: string | null | undefined;
  fallbackDate: string;
}

function DailyReviewAiProgress() {
  const status = useDailyReviewAiTaskStore((state) => state.status);
  const startedAt = useDailyReviewAiTaskStore((state) => state.startedAt);
  const estimatedDurationMs = useDailyReviewAiTaskStore((state) => state.estimatedDurationMs);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (status !== "running") return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [status]);

  if (status !== "running" || startedAt === null) return null;
  const elapsed = now - startedAt;
  const remaining = Math.max(0, estimatedDurationMs - elapsed);
  const overtime = Math.max(0, elapsed - estimatedDurationMs);
  const eta = new Date(startedAt + estimatedDurationMs);

  return (
    <div className="mt-3 flex items-start gap-2 rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm text-primary">
      <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" />
      <div>
        <p className="font-medium">AI 复盘正在生成</p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {overtime > 0
            ? `已超过预计时间 ${formatDuration(overtime)}，仍在生成`
            : `预计 ${formatTime(eta)} 完成 · 剩余 ${formatDuration(remaining)}`}
        </p>
      </div>
    </div>
  );
}

export function DailyReviewAiCard({ tradeDate, fallbackDate }: DailyReviewAiCardProps) {
  const status = useDailyReviewAiTaskStore((state) => state.status);
  const content = useDailyReviewAiTaskStore((state) => state.content);
  const streamContent = useDailyReviewAiTaskStore((state) => state.streamContent);
  const resultMeta = useDailyReviewAiTaskStore((state) => state.resultMeta);
  const error = useDailyReviewAiTaskStore((state) => state.error);
  const restoreError = useDailyReviewAiTaskStore((state) => state.restoreError);
  const [needConfig, setNeedConfig] = useState(false);

  useEffect(() => {
    if (!tradeDate) return;
    void useDailyReviewAiTaskStore.getState().restore(tradeDate);
  }, [tradeDate]);

  const runReview = async () => {
    setNeedConfig(false);
    const llm = loadLlm();
    if (!llm) {
      setNeedConfig(true);
      return;
    }
    if (!tradeDate) return;
    await useDailyReviewAiTaskStore.getState().start(llm, tradeDate);
  };

  return (
    <GlassCard glow className="mb-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 font-semibold"><Sparkles className="h-4 w-4 text-primary" /> AI 当日复盘</h3>
        {status === "running" ? (
          <button type="button" disabled className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow disabled:opacity-50">
            <Loader2 className="h-4 w-4 animate-spin" /> AI 复盘生成中
          </button>
        ) : (
          <button type="button" onClick={runReview} disabled={!tradeDate || status === "restoring"} className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50">
            <Sparkles className="h-4 w-4" /> {content ? "重新复盘" : "让 AI 复盘今天"}
          </button>
        )}
      </div>
      {status === "restoring" && <p className="mt-3 inline-flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> 正在恢复已保存的 AI 复盘…</p>}
      {status === "empty" && <p className="mt-3 text-sm text-muted-foreground">今日尚未生成 AI 复盘，不会自动调用模型。</p>}
      {restoreError && <div className="mt-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"><AlertCircle className="h-4 w-4 shrink-0" /> 恢复失败：{restoreError}</div>}
      {needConfig && <div className="mt-3 flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm text-muted-foreground"><AlertCircle className="h-4 w-4 shrink-0 text-warning" />还没接入 AI。<Link to="/settings" className="text-primary">先去接入你的 AI</Link>，之后一键出复盘。</div>}
      <DailyReviewAiProgress />
      {error && <div className="mt-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"><AlertCircle className="h-4 w-4 shrink-0" />{content ? `重新生成失败，继续显示旧结果：${error}` : error}</div>}
      {resultMeta && <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground"><span>结果交易日：{resultMeta.trade_date}</span><span>生成时间：{resultMeta.generated_at}</span><span>模型：{resultMeta.model_provider} / {resultMeta.model_name}</span><span>依据数据时间：{resultMeta.payload.source_data_cutoff || resultMeta.payload.source_review_generated_at}</span></div>}
      {content ? <><LazyMarkdownContent content={content} className="prose prose-sm prose-invert mt-4 max-w-none text-foreground" />{(status === "success" || status === "restored") && <div className="mt-3"><SaveNoteButton kind="复盘" title={`每日复盘 ${tradeDate || fallbackDate}`} content={content} /></div>}</> : !needConfig && status === "idle" ? <p className="mt-3 text-sm text-muted-foreground">点上方按钮，由服务器聚合当日数据并按事实/推断/建议结构生成复盘。</p> : null}
      {status === "running" && streamContent && <div className="mt-4 rounded-lg border border-primary/20 bg-primary/5 p-3"><p className="mb-2 text-xs font-medium text-primary">新结果临时预览（完成并保存后才会替换旧结果）</p><LazyMarkdownContent content={streamContent} className="prose prose-sm prose-invert max-w-none text-foreground/90" /></div>}
    </GlassCard>
  );
}
