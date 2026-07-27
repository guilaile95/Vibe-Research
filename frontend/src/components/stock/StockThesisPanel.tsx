import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronUp, BookOpen, Plus, Loader2, AlertCircle } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, ApiError, type InvestmentThesis } from "@/lib/api";
import { cn } from "@/lib/utils";

interface StockThesisPanelProps {
  /** 规范化股票代码（如 600519） */
  code: string;
}

const STATUS_LABEL: Record<string, string> = {
  active: "活跃",
  weakened: "减弱",
  invalidated: "失效",
  archived: "归档",
};

const STATUS_COLOR: Record<string, string> = {
  active: "bg-success/15 text-success",
  weakened: "bg-warning/15 text-warning",
  invalidated: "bg-danger/15 text-danger",
  archived: "bg-muted/50 text-muted-foreground",
};

function fmtDate(s: string) {
  try {
    return new Date(s).toLocaleDateString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
  } catch {
    return s;
  }
}

/**
 * 个股投资逻辑面板
 * - 查询当前股票的 thesis 列表
 * - 显示最近更新的 1-3 条
 * - 提供新建和列表入口
 * - 加载失败不影响个股页其他模块
 * - 默认折叠，用户点击展开后懒加载
 */
export function StockThesisPanel({ code }: StockThesisPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [theses, setTheses] = useState<InvestmentThesis[]>([]);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    if (!expanded || !code) return;

    let cancelled = false;
    setLoading(true);
    setErr(null);

    api
      .thesisList({ subject_type: "stock", subject_id: code, limit: 3 })
      .then((res) => {
        if (cancelled) return;
        setTheses(res.items);
        setTotal(res.total);
      })
      .catch((e) => {
        if (cancelled) return;
        setErr(e instanceof ApiError ? e.message : "加载投资逻辑失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [expanded, code]);

  const toggleExpand = () => setExpanded((prev) => !prev);

  return (
    <GlassCard className="mt-4">
      <button
        onClick={toggleExpand}
        className="flex w-full items-center justify-between text-left"
      >
        <div className="flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">投资逻辑</h3>
          {total > 0 && !expanded && (
            <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs text-primary">
              {total}
            </span>
          )}
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        )}
      </button>

      {expanded && (
        <div className="mt-3 space-y-3 border-t border-border/30 pt-3">
          {loading && (
            <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              加载中…
            </div>
          )}

          {err && !loading && (
            <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm text-warning">
              <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <p>{err}</p>
            </div>
          )}

          {!loading && !err && theses.length === 0 && (
            <div className="py-6 text-center text-sm text-muted-foreground">
              暂无投资逻辑记录
            </div>
          )}

          {!loading && !err && theses.length > 0 && (
            <div className="space-y-2">
              {theses.map((thesis) => (
                <Link
                  key={thesis.id}
                  to={`/thesis/${thesis.id}`}
                  className="block rounded-lg border border-border/50 bg-background/50 p-3 transition-colors hover:border-primary/40 hover:bg-background"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <h4 className="truncate text-sm font-medium">{thesis.title}</h4>
                        <span
                          className={cn(
                            "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium",
                            STATUS_COLOR[thesis.status] ?? "bg-muted/50 text-muted-foreground"
                          )}
                        >
                          {STATUS_LABEL[thesis.status] ?? thesis.status}
                        </span>
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                        {thesis.summary}
                      </p>
                    </div>
                    <div className="flex-shrink-0 text-right text-xs text-muted-foreground">
                      <div className="font-mono">v{thesis.current_revision}</div>
                      <div className="mt-0.5">{fmtDate(thesis.updated_at)}</div>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}

          <div className="flex items-center gap-2 pt-2">
            <Link
              to={`/thesis/new?subject_type=stock&subject_id=${encodeURIComponent(code)}`}
              className="inline-flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/5 px-3 py-1.5 text-sm text-primary transition-colors hover:bg-primary/10"
            >
              <Plus className="h-3.5 w-3.5" />
              新建逻辑
            </Link>
            {total > 0 && (
              <Link
                to={`/thesis?subject_type=stock&subject_id=${encodeURIComponent(code)}`}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border/50 px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
              >
                <BookOpen className="h-3.5 w-3.5" />
                查看全部 ({total})
              </Link>
            )}
          </div>
        </div>
      )}
    </GlassCard>
  );
}
