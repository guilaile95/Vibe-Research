import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, CheckCircle2, Loader2, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { usePortfolioAdviceTaskStore } from "@/stores/portfolioAdviceTaskStore";

function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function PortfolioAdviceTaskIndicator() {
  const status = usePortfolioAdviceTaskStore((s) => s.status);
  const startedAt = usePortfolioAdviceTaskStore((s) => s.startedAt);
  const error = usePortfolioAdviceTaskStore((s) => s.error);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (status !== "running") return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [status]);

  if (status === "idle") return null;

  const isRunning = status === "running";
  const isSuccess = status === "success";
  const isError = status === "error";
  const elapsedMs = isRunning && startedAt !== null ? now - startedAt : 0;

  return (
    <Link
      to="/portfolio"
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
            <p className="font-medium text-primary">持仓建议分析中</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              已运行 {formatDuration(elapsedMs)} · 点击返回我的持仓
            </p>
          </>
        )}
        {isSuccess && (
          <>
            <p className="font-medium text-success">持仓建议已生成</p>
            <p className="mt-0.5 text-xs text-muted-foreground">查看结果 →</p>
          </>
        )}
        {isError && (
          <>
            <p className="font-medium text-destructive">持仓建议生成失败</p>
            <p className="mt-0.5 text-xs text-muted-foreground">{error || "返回查看"}</p>
          </>
        )}
      </div>

      {isSuccess && <Sparkles className="h-4 w-4 shrink-0 text-success" />}
    </Link>
  );
}
