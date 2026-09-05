import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2, PlusCircle, RefreshCw } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, ApiError, type CampaignNextActions, type CampaignRecord, type CampaignStrategy } from "@/lib/api";
import { CAMPAIGN_STRATEGIES, CAMPAIGN_STRATEGY_LABELS, errorMessage } from "@/lib/decisionInbox";
import { selectCandidateCampaigns } from "@/lib/candidateCampaign";
import { CampaignLifecycleCard } from "./CampaignLifecycleCard";
import { CampaignThesisActivationCard } from "./CampaignThesisActivationCard";
import { ResearchContinuityCard } from "./ResearchContinuityCard";

/**
 * StockData 的候选研究 continuation。
 *
 * 这里只消费 Campaign list / next-actions / transition 既有契约：创建由用户显式
 * 选择策略并点击，状态推进由 CampaignLifecycleCard 显式调用 transition API。
 * 本组件不创建 Thesis、不自动迁移、不生成 PRE-ENTRY/BUY 或评分。
 */
export function CandidateCampaignPanel({
  code,
  workspace = false,
  returnTo = "/decision-inbox",
}: {
  code: string;
  workspace?: boolean;
  returnTo?: string;
}) {
  const [campaigns, setCampaigns] = useState<CampaignRecord[]>([]);
  const [nextActions, setNextActions] = useState<Record<string, CampaignNextActions | null>>({});
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [selectedStrategy, setSelectedStrategy] = useState<CampaignStrategy | null>(null);
  const [error, setError] = useState("");
  const [nextActionWarning, setNextActionWarning] = useState("");
  const loadGeneration = useRef(0);

  const load = useCallback(async () => {
    const generation = ++loadGeneration.current;
    if (!/^\d{6}$/.test(code)) return;
    setLoading(true);
    setError("");
    setNextActionWarning("");
    try {
      const records = await api.listCampaigns({ security_code: code });
      if (generation !== loadGeneration.current) return;
      const candidates = selectCandidateCampaigns(records, code);
      setCampaigns(candidates);

      const results = await Promise.all(
        candidates.map(async (campaign) => {
          try {
            return [campaign.campaign_id, await api.getCampaignNextActions(campaign.campaign_id)] as const;
          } catch {
            return [campaign.campaign_id, null] as const;
          }
        }),
      );
      if (generation !== loadGeneration.current) return;
      const actions: Record<string, CampaignNextActions | null> = {};
      for (const [campaignId, value] of results) actions[campaignId] = value;
      setNextActions(actions);
      if (results.some(([, value]) => value === null)) {
        setNextActionWarning("部分投资计划的下一步读取失败；系统没有猜测可执行操作，请刷新后重试。");
      }
    } catch (err: unknown) {
      if (generation !== loadGeneration.current) return;
      setCampaigns([]);
      setNextActions({});
      setError(err instanceof ApiError ? err.message : "候选投资计划读取失败");
    } finally {
      if (generation === loadGeneration.current) setLoading(false);
    }
  }, [code]);

  useEffect(() => {
    setSelectedStrategy(null);
    void load();
    return () => {
      loadGeneration.current += 1;
    };
  }, [load]);

  const createCandidate = async () => {
    if (!selectedStrategy || creating) return;
    setCreating(true);
    setError("");
    try {
      const created = await api.createCampaign(code, selectedStrategy);
      if (created.status !== "DRAFT") {
        setError(`创建结果为 ${created.status}，不是预期的草稿状态；已停止继续操作。`);
        return;
      }
      setSelectedStrategy(null);
      await load();
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  };

  return (
    <GlassCard className="mt-4" data-testid="candidate-campaign-panel" data-security-code={code}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">
            {workspace ? "步骤 2 · 建立候选投资计划" : "候选研究 · 入场前"}
          </h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            这里只显示该证券尚未生效的草稿、研究中和待入场计划。每一步都需要你明确选择；这里不会自动创建投资逻辑、推进状态或产生买入动作。
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading || creating}
          className="rounded border border-border/50 p-1.5 text-muted-foreground hover:text-foreground disabled:opacity-50"
          aria-label="刷新候选投资计划"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {loading && (
        <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground" aria-busy="true">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> 正在读取投资计划和可执行的下一步…
        </div>
      )}

      {error && !loading && (
        <div className="mt-4 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive" role="alert">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {nextActionWarning && !loading && (
        <p className="mt-3 text-xs text-warning" role="status">{nextActionWarning}</p>
      )}

      {!loading && campaigns.length > 0 && (
        <div className="mt-4 space-y-3">
          {campaigns.map((campaign) => (
            <div key={campaign.campaign_id} className="space-y-3">
              <CampaignLifecycleCard
                campaignId={campaign.campaign_id}
                securityCode={campaign.security_code}
                strategy={campaign.strategy}
                status={campaign.status}
                nextActions={nextActions[campaign.campaign_id] ?? null}
                setupContext
                researchContext
                onChanged={() => void load()}
              />
              <ResearchContinuityCard campaignId={campaign.campaign_id} />
              {workspace && (
                <section className="space-y-2" data-testid="candidate-thesis-decision-step">
                  <div>
                    <h4 className="text-sm font-semibold">步骤 3 · 固化投资逻辑，再进入正式决策</h4>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
                      先确认并冻结正式投资逻辑；满足必要条件后才会开放正式决策。
                    </p>
                  </div>
                  <CampaignThesisActivationCard
                    campaignId={campaign.campaign_id}
                    securityCode={campaign.security_code}
                    strategy={campaign.strategy}
                    reloadEpoch={0}
                    returnTo={returnTo}
                  />
                </section>
              )}
            </div>
          ))}
        </div>
      )}

      {!loading && campaigns.length === 0 && !error && (
        <div className="mt-4 space-y-3 rounded-lg border border-dashed border-border/70 bg-background/30 p-4">
          <div>
            <p className="text-sm font-medium">暂无候选投资计划</p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              请选择研究策略，然后明确创建一个草稿投资计划。创建不会绑定投资逻辑，也不会自动推进到研究中。
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="候选投资计划策略">
            {CAMPAIGN_STRATEGIES.map((strategy) => (
              <label
                key={strategy}
                className={`cursor-pointer rounded-md border px-3 py-2 text-center text-xs transition-colors ${
                  selectedStrategy === strategy
                    ? "border-primary bg-primary/5 text-primary"
                    : "border-border/60 hover:border-primary/40"
                }`}
              >
                <input
                  type="radio"
                  name={`candidate-campaign-strategy-${code}`}
                  value={strategy}
                  checked={selectedStrategy === strategy}
                  onChange={() => setSelectedStrategy(strategy)}
                  className="sr-only"
                />
                {strategy} · {CAMPAIGN_STRATEGY_LABELS[strategy]}
              </label>
            ))}
          </div>
          <button
            type="button"
            onClick={() => void createCandidate()}
            disabled={!selectedStrategy || creating}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            data-testid="create-candidate-campaign"
          >
            {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlusCircle className="h-3.5 w-3.5" />}
            创建候选投资计划
          </button>
        </div>
      )}
    </GlassCard>
  );
}
