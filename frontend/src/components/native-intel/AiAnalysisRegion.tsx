import React, { useState } from "react";
import { Sparkles, RefreshCw, Loader2, AlertCircle, FileText, BarChart3, ShieldAlert, BookOpen, Layers, Newspaper } from "lucide-react";
import { api } from "../../lib/api";
import type { NativeIntelAiAnalysisResponse, NativeIntelConfig } from "../../lib/api/types";

interface AiAnalysisRegionProps {
  mode?: "current" | "daily" | "incremental";
  scope?: "all" | "my_interests";
  config?: NativeIntelConfig | null;
}

const SECTION_TABS = [
  { id: "core_trends", label: "核心热点态势", icon: FlameTabIcon },
  { id: "sentiment_controversy", label: "舆情风向与争议", icon: ShieldAlert },
  { id: "signals", label: "异动与弱信号", icon: BarChart3 },
  { id: "rss_insights", label: "RSS深度洞察", icon: BookOpen },
  { id: "outlook_strategy", label: "观察与研判推演", icon: FileText },
  { id: "standalone_summaries", label: "独立源摘要", icon: Layers },
] as const;

function FlameTabIcon(props: React.SVGProps<SVGSVGElement>) {
  return <Newspaper {...props} />;
}

function formatSectionContent(val: unknown, fallback: string): string {
  if (!val) return fallback;
  if (typeof val === "string") return val;
  if (Array.isArray(val)) {
    return val
      .map((item) => {
        if (typeof item === "string") return item;
        if (typeof item === "object" && item !== null) {
          const dict = item as Record<string, any>;
          const title = dict.trend_name || dict.signal_name || dict.source_id || "";
          const desc = dict.significance || dict.evidence || dict.insight || dict.impact || dict.summary || "";
          const extra = dict.driver ? ` (驱动: ${dict.driver})` : dict.impact ? ` (影响: ${dict.impact})` : "";
          return title ? `• ${title}：${desc}${extra}` : JSON.stringify(item);
        }
        return String(item);
      })
      .join("\n\n");
  }
  if (typeof val === "object") {
    const parts: string[] = [];
    for (const [k, v] of Object.entries(val as Record<string, any>)) {
      if (Array.isArray(v)) {
        if (v.length > 0) parts.push(`【${k}】\n` + v.map((x) => `• ${x}`).join("\n"));
      } else if (v) {
        parts.push(`【${k}】: ${v}`);
      }
    }
    return parts.join("\n\n") || fallback;
  }
  return String(val);
}

export function AiAnalysisRegion({ mode = "current", scope = "all", config }: AiAnalysisRegionProps) {
  const [loading, setLoading] = useState(false);
  const [analysis, setAnalysis] = useState<NativeIntelAiAnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<typeof SECTION_TABS[number]["id"]>("core_trends");

  const handleGenerate = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.nativeIntelAiAnalysis({
        mode: mode.toUpperCase(),
        scope,
        max_news: config?.ai_analysis_max_news ?? 50,
        include_rss: config?.ai_analysis_include_rss !== false,
        include_standalone: Boolean(config?.ai_analysis_include_standalone),
      });
      setAnalysis(res);
      if (res.status === "ERROR") {
        setError(res.error || "AI 分析返回异常");
      }
    } catch (err: any) {
      setError(err?.message || "请求 AI 深度分析服务失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      data-testid="display-region-ai_analysis"
      className="rounded-xl border border-border/60 bg-card/50 overflow-hidden shadow-sm"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between border-b border-border/40 p-3 bg-muted/20 gap-2">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-purple-400" />
          <h3 className="font-semibold text-sm">AI 深度分析与研报</h3>
          <span className="rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20 px-2 py-0.5 text-[10px]">
            Wave 5
          </span>
          {analysis && (
            <span className="text-[11px] text-muted-foreground font-mono">
              {analysis.provider} / {analysis.model}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {analysis?.cached && (
            <span
              data-testid="wave5-ai-cached-badge"
              className="rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 text-[10px] font-medium"
            >
              已缓存 (指纹命中)
            </span>
          )}
          <button
            type="button"
            data-testid="wave5-generate-ai-analysis"
            onClick={handleGenerate}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground shadow-sm hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            {loading ? "分析研判中…" : (analysis ? "重新生成研报" : "生成 AI 研报")}
          </button>
        </div>
      </div>

      {/* Counts and Meta Bar */}
      {analysis && (
        <div
          data-testid="wave5-ai-counts"
          className="flex flex-wrap items-center justify-between border-b border-border/30 px-3 py-1.5 bg-background/40 text-[11px] text-muted-foreground gap-2"
        >
          <div className="flex items-center gap-3">
            <span>总输入条目: <strong className="text-foreground">{analysis.counts?.total_news ?? 0}</strong></span>
            <span>实际分析: <strong className="text-foreground">{analysis.counts?.analyzed_news ?? 0}</strong></span>
            <span>热榜: {analysis.counts?.hotlist_analyzed ?? 0}/{analysis.counts?.hotlist_count ?? 0}</span>
            <span>RSS: {analysis.counts?.rss_analyzed ?? 0}/{analysis.counts?.rss_count ?? 0}</span>
          </div>
          <div className="text-[10px] font-mono">
            生成时间: {analysis.generated_at?.replace("T", " ").replace("Z", "")}
          </div>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="p-4 m-3 rounded-lg border border-rose-500/30 bg-rose-500/10 text-rose-300 text-xs flex items-start gap-2">
          <AlertCircle className="h-4 w-4 shrink-0 text-rose-400 mt-0.5" />
          <div>
            <p className="font-semibold">AI 分析未能顺利完成</p>
            <p className="mt-0.5 text-rose-400/90">{error}</p>
          </div>
        </div>
      )}

      {/* Empty / Unanalyzed Prompt */}
      {!analysis && !loading && !error && (
        <div className="p-8 text-center text-xs text-muted-foreground space-y-2">
          <Sparkles className="mx-auto h-8 w-8 text-muted-foreground/40" />
          <p className="font-medium text-foreground">当前时段尚未生成 AI 宏观研报</p>
          <p className="text-[11px] text-muted-foreground/80">
            点击右上角“生成 AI 研报”按钮，系统将基于当前时段热榜及 RSS 事实提炼核心态势、舆情风向、异动信号与前瞻研判。
          </p>
        </div>
      )}

      {/* Loading state */}
      {loading && !analysis && (
        <div className="p-12 text-center text-xs text-muted-foreground space-y-3">
          <Loader2 className="mx-auto h-6 w-6 animate-spin text-primary" />
          <p>正在调度 AI 模型进行多维度研判提炼，请稍候…</p>
        </div>
      )}

      {/* Analysis Content Tabs */}
      {analysis && (
        <div className="p-3 space-y-3">
          {/* Section Tabs */}
          <div className="flex flex-wrap gap-1.5 border-b border-border/40 pb-2">
            {SECTION_TABS.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  data-testid={`wave5-tab-${tab.id}`}
                  onClick={() => setActiveTab(tab.id)}
                  className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors ${
                    isActive
                      ? "bg-primary text-primary-foreground font-medium shadow-sm"
                      : "bg-muted/40 text-muted-foreground hover:bg-muted hover:text-foreground"
                  }`}
                >
                  <Icon className="h-3 w-3" />
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* Tab Content Display */}
          <div className="rounded-lg border border-border/40 bg-background/60 p-3.5 min-h-[120px]">
            {activeTab === "core_trends" && (
              <div data-testid="wave5-section-core_trends" className="space-y-1.5">
                <h4 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                  <FlameTabIcon className="h-3.5 w-3.5 text-amber-400" /> 核心热点态势
                </h4>
                <p className="text-xs leading-relaxed text-foreground/90 whitespace-pre-wrap">
                  {formatSectionContent(analysis.core_trends, "暂无显著热点态势")}
                </p>
              </div>
            )}

            {activeTab === "sentiment_controversy" && (
              <div data-testid="wave5-section-sentiment_controversy" className="space-y-1.5">
                <h4 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                  <ShieldAlert className="h-3.5 w-3.5 text-rose-400" /> 舆情风向与争议焦点
                </h4>
                <p className="text-xs leading-relaxed text-foreground/90 whitespace-pre-wrap">
                  {formatSectionContent(analysis.sentiment_controversy, "暂无显著舆情争议")}
                </p>
              </div>
            )}

            {activeTab === "signals" && (
              <div data-testid="wave5-section-signals" className="space-y-1.5">
                <h4 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                  <BarChart3 className="h-3.5 w-3.5 text-blue-400" /> 异动与弱信号捕捉
                </h4>
                <p className="text-xs leading-relaxed text-foreground/90 whitespace-pre-wrap">
                  {formatSectionContent(analysis.signals, "暂无异常异动信号")}
                </p>
              </div>
            )}

            {activeTab === "rss_insights" && (
              <div data-testid="wave5-section-rss_insights" className="space-y-1.5">
                <h4 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                  <BookOpen className="h-3.5 w-3.5 text-emerald-400" /> RSS 深度洞察与硬核增量
                </h4>
                <p className="text-xs leading-relaxed text-foreground/90 whitespace-pre-wrap">
                  {formatSectionContent(analysis.rss_insights, "暂无 RSS 深度增量")}
                </p>
              </div>
            )}

            {activeTab === "outlook_strategy" && (
              <div data-testid="wave5-section-outlook_strategy" className="space-y-1.5">
                <h4 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                  <FileText className="h-3.5 w-3.5 text-purple-400" /> 观察与研判推演 (分角色前瞻)
                </h4>
                <p className="text-xs leading-relaxed text-foreground/90 whitespace-pre-wrap">
                  {formatSectionContent(analysis.outlook_strategy, "暂无推演内容")}
                </p>
              </div>
            )}

            {activeTab === "standalone_summaries" && (
              <div data-testid="wave5-section-standalone_summaries" className="space-y-2">
                <h4 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                  <Layers className="h-3.5 w-3.5 text-cyan-400" /> 重点独立源逐源摘要
                </h4>
                {analysis.standalone_summaries && Object.keys(analysis.standalone_summaries).length > 0 ? (
                  <div className="grid gap-2 sm:grid-cols-2">
                    {Object.entries(analysis.standalone_summaries).map(([source, summary]) => (
                      <div key={source} className="rounded border border-border/40 p-2 bg-card/40 text-xs">
                        <span className="font-semibold text-primary block mb-0.5">{source}</span>
                        <p className="text-muted-foreground leading-snug">{summary}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">本次未纳入独立源摘要，可在配置中开启。</p>
                )}
              </div>
            )}
          </div>

          {/* Watermark Disclaimer */}
          <div
            data-testid="wave5-disclaimer-watermark"
            className="flex items-center gap-1.5 text-[10px] text-muted-foreground/70 bg-muted/20 px-2.5 py-1 rounded border border-border/30"
          >
            <AlertCircle className="h-3 w-3 shrink-0 text-amber-400/80" />
            <span>{analysis.disclaimer || "研报与标签仅供宏观情报参考，不构成投资建议"}</span>
          </div>
        </div>
      )}
    </div>
  );
}
