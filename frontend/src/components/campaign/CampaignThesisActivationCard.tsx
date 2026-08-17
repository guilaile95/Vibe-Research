import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { BookOpen, Loader2, PlusCircle, RefreshCw } from "lucide-react";
import {
  api,
  ApiError,
  type CampaignCurrentThesis,
  type CampaignStrategy,
  type CampaignThesisBinding,
  type InvestmentThesis,
} from "@/lib/api";
import { selectCampaignThesisCandidates } from "@/lib/campaignThesis";

const FORMAL_LABELS: Record<string, string> = {
  draft: "Formal 草稿",
  confirmed: "已确认，待冻结",
  frozen: "已冻结",
};

function fmt(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

function contextQuery(
  campaignId: string,
  securityCode: string,
  strategy: CampaignStrategy,
): string {
  return new URLSearchParams({
    campaign_id: campaignId,
    security_code: securityCode,
    strategy,
    return_to: "/decision-inbox",
  }).toString();
}

export function CampaignThesisActivationCard({
  campaignId,
  securityCode,
  strategy,
  reloadEpoch,
}: {
  campaignId: string;
  securityCode: string;
  strategy: CampaignStrategy;
  reloadEpoch: number;
}) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [binding, setBinding] = useState<CampaignThesisBinding | null>(null);
  const [current, setCurrent] = useState<CampaignCurrentThesis | null>(null);
  const [boundThesis, setBoundThesis] = useState<InvestmentThesis | null>(null);
  const [candidates, setCandidates] = useState<InvestmentThesis[]>([]);
  const loadGeneration = useRef(0);

  const load = useCallback(async () => {
    const generation = ++loadGeneration.current;
    setLoading(true);
    setError("");
    try {
      let nextBinding: CampaignThesisBinding | null = null;
      try {
        nextBinding = await api.getCampaignThesisBinding(campaignId);
      } catch (err) {
        if (!(err instanceof ApiError) || err.status !== 404) throw err;
      }
      if (generation !== loadGeneration.current) return;

      if (nextBinding) {
        const [projection, aggregate] = await Promise.all([
          api.getCampaignCurrentThesis(campaignId),
          api.thesisGet(nextBinding.thesis_id),
        ]);
        if (generation !== loadGeneration.current) return;
        setBinding(nextBinding);
        setCurrent(projection);
        setBoundThesis(aggregate.thesis);
        setCandidates([]);
      } else {
        const result = await api.thesisList({
          subject_type: "stock",
          subject_id: securityCode,
          limit: 200,
        });
        if (generation !== loadGeneration.current) return;
        setBinding(null);
        setCurrent(null);
        setBoundThesis(null);
        setCandidates(selectCampaignThesisCandidates(result.items, securityCode));
      }
    } catch (err) {
      if (generation !== loadGeneration.current) return;
      setError(err instanceof ApiError ? err.message : "Current Thesis 状态读取失败");
    } finally {
      if (generation === loadGeneration.current) setLoading(false);
    }
  }, [campaignId, securityCode]);

  useEffect(() => {
    void load();
    return () => {
      loadGeneration.current += 1;
    };
  }, [load, reloadEpoch]);

  const query = contextQuery(campaignId, securityCode, strategy);

  return (
    <div className="rounded-lg border border-border/60 bg-background/35 p-3" data-campaign-thesis={campaignId}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-1.5 text-xs font-semibold">
            <BookOpen className="h-3.5 w-3.5 text-primary" />
            Current Thesis
          </h3>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            Campaign 策略 {strategy}；Formal Thesis 的确认、冻结和绑定都需要你显式执行。
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="rounded border border-border/50 p-1 text-muted-foreground hover:text-foreground disabled:opacity-50"
          aria-label="刷新 Current Thesis"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {loading ? (
        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground" aria-busy="true">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> 正在读取 Thesis 状态…
        </div>
      ) : error ? (
        <p className="mt-3 text-xs text-destructive" role="alert">{error}</p>
      ) : binding && boundThesis && current ? (
        <div className="mt-3 space-y-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded bg-success/15 px-1.5 py-0.5 text-success">已绑定</span>
            <span className="font-medium">{boundThesis.title}</span>
            <span className="font-mono text-muted-foreground">v{boundThesis.current_revision}</span>
          </div>
          <div className="grid gap-1 text-muted-foreground sm:grid-cols-2">
            <p>Formal 状态：{FORMAL_LABELS[boundThesis.formal_state ?? ""] ?? "未开始"}</p>
            <p>冻结版本：{boundThesis.frozen_revision ? `v${boundThesis.frozen_revision}` : "—"}</p>
            <p>Current 状态：{current.ready ? current.effective_state : current.formal_status}</p>
            <p>更新时间：{fmt(boundThesis.updated_at)}</p>
          </div>
          <Link to={`/thesis/${boundThesis.id}?${query}`} className="inline-flex text-primary hover:underline">
            查看 Current Thesis →
          </Link>
          {current.ready && (
            <Link
              to={`/campaigns/${encodeURIComponent(campaignId)}/decision-proposal`}
              className="ml-3 inline-flex text-primary hover:underline"
              data-action="open-decision-proposal"
            >
              进入 Formal Decision Review →
            </Link>
          )}
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="rounded bg-warning/15 px-1.5 py-0.5 text-warning">尚未绑定</span>
            <span className="text-muted-foreground">请选择已有逻辑继续设置，或创建新的 Formal Thesis 草稿。</span>
          </div>

          {candidates.length > 0 && (
            <div className="space-y-1.5">
              {candidates.map((thesis) => (
                <div key={thesis.id} className="flex flex-wrap items-center gap-2 rounded border border-border/50 px-2.5 py-2 text-xs">
                  <span className="min-w-0 flex-1 truncate font-medium">{thesis.title}</span>
                  <span className="text-muted-foreground">
                    {FORMAL_LABELS[thesis.formal_state ?? ""] ?? "未开始 Formal 化"}
                    {thesis.strategy ? ` · ${thesis.strategy}` : ""}
                    {` · v${thesis.current_revision}`}
                  </span>
                  {thesis.strategy && thesis.strategy !== strategy && (
                    <span className="text-warning">策略不一致</span>
                  )}
                  <Link to={`/thesis/${thesis.id}?${query}`} className="text-primary hover:underline">
                    继续设置
                  </Link>
                </div>
              ))}
            </div>
          )}

          <Link
            to={`/thesis/new?subject_type=stock&subject_id=${encodeURIComponent(securityCode)}&${query}`}
            className="inline-flex items-center gap-1.5 rounded bg-primary px-2.5 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            <PlusCircle className="h-3.5 w-3.5" />
            新建 Formal Thesis 草稿
          </Link>
        </div>
      )}
    </div>
  );
}
