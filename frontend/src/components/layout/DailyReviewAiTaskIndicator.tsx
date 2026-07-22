import { useEffect, useState, useRef } from "react";
import { Link } from "react-router-dom";
import { Loader2, CheckCircle2, AlertCircle, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDailyReviewAiTaskStore } from "@/stores/dailyReviewAiTaskStore";

function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

export function DailyReviewAiTaskIndicator() {
  const status = useDailyReviewAiTaskStore((s) => s.status);
  const startedAt = useDailyReviewAiTaskStore((s) => s.startedAt);
  const estimatedDurationMs = useDailyReviewAiTaskStore((s) => s.estimatedDurationMs);
  const content = useDailyReviewAiTaskStore((s) => s.content);
  const error = useDailyReviewAiTaskStore((s) => s.error);

  const [now, setNow] = useState(Date.now());
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (status === "running") {
      setNow(Date.now());
      intervalRef.current = setInterval(() => setNow(Date.now()), 1000);
    }
    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [status]);

  if (status === "idle") return null;

  const isRunning = status === "running";
  const isSuccess = status === "success";
  const isError = status === "error";

  let remainingMs = 0;
  let overTimeMs = 0;
  let eta: Date | null = null;

  if (isRunning && startedAt !== null) {
    const elapsed = now - startedAt;
    remainingMs = Math.max(0, estimatedDurationMs - elapsed);
    overTimeMs = Math.max(0, elapsed - estimatedDurationMs);
    eta = new Date(startedAt + estimatedDurationMs);
  }

  return (
    <Link
      to="/daily-review"
      className={cn(
        "mb-4 flex items-center gap-3 rounded-lg border px-4 py-3 text-sm transition-colors",
        isRunning && "border-primary/30 bg-primary/5",
        isSuccess && "border-success/30 bg-success/5",
        isError && "border-destructive/30 bg-destructive/5",
      )}
    >
      {isRunning && <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />}
      {isSuccess && <CheckCircle2 className="h-4 w-4 shrink-0 text-success" />}
      {isError && <AlertCircle className="h-4 w-4 shrink-0 text-destructive" />}

      <div className="flex-1">
        {isRunning && (
          <>
            <p className="font-medium text-primary">AI 复盘生成中</p>
            {eta && (
              <p className="mt-0.5 text-xs text-muted-foreground">
                {overTimeMs > 0
                  ? `已超过预计时间 ${formatDuration(overTimeMs)}，仍在生成`
                  : `预计 ${formatTime(eta)} 完成 · 剩余 ${formatDuration(remainingMs)}`}
              </p>
            )}
          </>
        )}
        {isSuccess && (
          <>
            <p className="font-medium text-success">AI 复盘已完成</p>
            {content && <p className="mt-0.5 text-xs text-muted-foreground">查看结果 →</p>}
          </>
        )}
        {isError && (
          <>
            <p className="font-medium text-destructive">AI 复盘失败</p>
            {error && <p className="mt-0.5 text-xs text-muted-foreground">{error}</p>}
          </>
        )}
      </div>

      {isSuccess && <Sparkles className="h-4 w-4 shrink-0 text-success" />}
    </Link>
  );
}
