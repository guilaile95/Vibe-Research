import { useEffect, useState } from "react";
import { KeyRound, Sparkles, ShieldCheck, Check, Trash2, Terminal, Loader2, RefreshCw, Rss, Plus, SlidersHorizontal, Tag, Globe, Layers, ArrowUp, ArrowDown } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { toast } from "sonner";
import {
  clearLlm,
  getAgentRuntimeStatus,
  loadLlm,
  saveLlm,
  startAgentRuntimeLogin,
  type AgentRuntimeStatus,
} from "@/lib/llm";
import { api, ApiError, loadAccessKey, saveAccessKey, type NativeIntelSourceRecord, type FilterProfile, type FilterMethod, type InterestTag, type KeywordGroup } from "@/lib/api";
import { subscriptionModels, apiModels, PROVIDER_BASE, isCliProvider, aiModels, type ProviderId } from "@/lib/ai-models";

export function Settings() {
  const existing = loadLlm();
  const existingIsCli = existing ? isCliProvider(existing.provider) : false;

  const [mode, setMode] = useState<"api" | "subscription">(existing && existingIsCli ? "subscription" : "api");
  // 订阅：固定为 Codex model id
  const [cliId, setCliId] = useState(existing && existingIsCli ? existing.model : "");
  // API：选中的模型 id + 可编辑的 baseURL / model / key
  const firstApi = apiModels[0];
  const [apiId, setApiId] = useState(existing && !existingIsCli ? existing.model : firstApi.id);
  const [baseURL, setBaseURL] = useState(existing && !existingIsCli ? existing.baseURL : (PROVIDER_BASE[firstApi.provider] || ""));
  const [modelName, setModelName] = useState(existing && !existingIsCli ? existing.model : firstApi.id);
  const [apiKey, setApiKey] = useState(existing && !existingIsCli ? existing.apiKey : "");
  // 后端访问密钥（对应部署时的 VR_API_KEY）；本机自用不设鉴权时留空
  const [accessKey, setAccessKey] = useState(loadAccessKey());
  const [runtimeStatus, setRuntimeStatus] = useState<AgentRuntimeStatus | null>(null);
  const [runtimeBusy, setRuntimeBusy] = useState(false);

  const providerOf = (id: string): ProviderId => aiModels.find((m) => m.id === id)?.provider ?? "openai-compatible";

  const refreshRuntime = async () => {
    setRuntimeBusy(true);
    try {
      setRuntimeStatus(await getAgentRuntimeStatus());
    } catch {
      setRuntimeStatus({
        runtime: "Codex Subscription",
        installed: false,
        authenticated: false,
        available: false,
        status: "runtime_unavailable",
        version: null,
      });
    } finally {
      setRuntimeBusy(false);
    }
  };

  useEffect(() => {
    if (mode === "subscription") void refreshRuntime();
  }, [mode]);

  useEffect(() => {
    if (runtimeStatus?.status !== "login_pending") return;
    const timer = window.setInterval(() => void refreshRuntime(), 1500);
    return () => window.clearInterval(timer);
  }, [runtimeStatus?.status]);

  const pickApiModel = (id: string) => {
    const m = apiModels.find((x) => x.id === id);
    if (!m) return;
    setApiId(id);
    setModelName(id);
    setBaseURL(PROVIDER_BASE[m.provider] || "");
  };

  const saveApi = () => {
    if (!baseURL.trim() || !apiKey.trim() || !modelName.trim()) {
      toast.error("请填完 Base URL、API Key、Model");
      return;
    }
    saveLlm({ provider: providerOf(apiId), baseURL: baseURL.trim(), apiKey: apiKey.trim(), model: modelName.trim() });
    toast.success("已保存到本地，全站 AI 功能现在可用");
  };

  const saveSubscription = () => {
    const m = subscriptionModels.find((x) => x.id === cliId);
    if (!m) {
      toast.error("请选择 Codex Subscription");
      return;
    }
    if (m.provider === "cli-codex" && !runtimeStatus?.available) {
      toast.error("Codex Subscription 尚未连接，请先完成登录");
      return;
    }
    saveLlm({ provider: m.provider, baseURL: "", apiKey: "", model: m.id });
    toast.success(`已选「${m.name}」订阅，全站 AI 功能将调用 ${runtimeStatus?.runtime || m.name}`);
  };

  const loginCodex = async () => {
    setRuntimeBusy(true);
    try {
      await startAgentRuntimeLogin();
      setRuntimeStatus((current) => current ? { ...current, status: "login_pending", available: false } : current);
      toast.success("已打开 Codex 登录流程，请在浏览器中完成连接");
    } catch {
      toast.error("无法启动 Codex 登录；请确认 Agent Runtime 已启动");
    } finally {
      setRuntimeBusy(false);
    }
  };

  const forget = () => {
    clearLlm();
    setApiKey("");
    setCliId("");
    toast.success("已清除本地配置");
  };

  const saveAccess = () => {
    const k = accessKey.trim();
    saveAccessKey(k);
    setAccessKey(k);
    toast.success(k ? "已保存后端访问密钥（存本地）" : "已清除后端访问密钥");
  };

  return (
    <div>
      <PageHeader title="接入 AI" subtitle="配置一次，全站所有 AI 功能统一使用 Codex Subscription 或 API Compatible" />

      <div className="mb-4 flex items-start gap-2 rounded-lg border border-success/25 bg-success/5 p-3 text-xs text-muted-foreground">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" />
        <span>API key <b className="text-foreground">只存在你本地浏览器</b>，仅在你提问时发给你自己的后端去调模型，不上传、不进仓库。</span>
      </div>

      {/* 两种接入方式 */}
      <div className="mb-4 grid gap-3 sm:grid-cols-2">
        <GlassCard glow={mode === "subscription"} onClick={() => setMode("subscription")}
          className={mode === "subscription" ? "ring-1 ring-primary/40" : "opacity-80"}>
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            <h3 className="font-semibold">订阅接入</h3>
            {mode === "subscription" && <Check className="ml-auto h-4 w-4 text-primary" />}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">使用产品独立登录的 Codex / ChatGPT 订阅，<b className="text-foreground">免 API key</b>。所有 AI 功能统一走 Codex。</p>
        </GlassCard>

        <GlassCard glow={mode === "api"} onClick={() => setMode("api")}
          className={mode === "api" ? "ring-1 ring-primary/40" : "opacity-80"}>
          <div className="flex items-center gap-2">
            <KeyRound className="h-5 w-5 text-primary" />
            <h3 className="font-semibold">API 接入</h3>
            {mode === "api" && <Check className="ml-auto h-4 w-4 text-primary" />}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">粘贴 API key，支持 DeepSeek / 豆包 / MiniMax / OpenAI / OpenRouter / 任意兼容端点。<b className="text-foreground">现已可用。</b></p>
        </GlassCard>
      </div>

      <GlassCard>
        {mode === "subscription" ? (
          <div className="space-y-3 text-sm">
            <p className="text-xs text-muted-foreground">
              Codex 使用 Vibe 自己的数据目录保存登录态；账号信息和 Token 不进入 Vibe 数据库或日志。
              <span className="text-muted-foreground/60"> Agent 只能接收当前页面上下文，没有 Shell、磁盘读取、网页搜索、MCP 或正式写权限。</span>
            </p>
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/20 p-3 text-xs">
              <span className={runtimeStatus?.available ? "text-success" : "text-muted-foreground"}>
                Runtime：{runtimeStatus?.runtime || "Codex Subscription"} · {
                  runtimeStatus?.status === "ready" ? "已连接" :
                  runtimeStatus?.status === "login_pending" ? "等待登录" :
                  runtimeStatus?.status === "login_failed" ? "登录未完成" :
                  runtimeStatus?.status === "not_authenticated" ? "未连接" : "Runtime 未启动"
                }
                {runtimeStatus?.version ? ` · ${runtimeStatus.version}` : ""}
              </span>
              <button
                type="button"
                onClick={() => void refreshRuntime()}
                disabled={runtimeBusy}
                className="ml-auto inline-flex items-center gap-1 rounded-md px-2 py-1 text-muted-foreground hover:bg-muted disabled:opacity-50"
              >
                {runtimeBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                检查
              </button>
              {!runtimeStatus?.available && runtimeStatus?.status !== "login_pending" && (
                <button
                  type="button"
                  onClick={() => void loginCodex()}
                  disabled={runtimeBusy || runtimeStatus?.status === "runtime_unavailable"}
                  className="rounded-md bg-primary/15 px-2 py-1 font-medium text-primary disabled:opacity-40"
                >
                  连接 Codex
                </button>
              )}
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {subscriptionModels.map((m) => {
                const on = cliId === m.id;
                return (
                  <button key={m.id} onClick={() => setCliId(m.id)}
                    className={`flex items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left transition-colors ${
                      on
                        ? "border-primary/50 bg-primary/10"
                        : "border-border hover:bg-muted/40"
                    }`}>
                    <Terminal className={`h-4 w-4 shrink-0 ${on ? "text-primary" : "text-muted-foreground"}`} />
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 font-medium">
                        {m.name}
                        {on && <Check className="h-3.5 w-3.5 text-primary" />}
                      </div>
                      <div className="truncate text-[11px] text-muted-foreground">{m.description}</div>
                    </div>
                  </button>
                );
              })}
            </div>
            <div className="flex items-center gap-2 pt-1">
              <button onClick={saveSubscription} className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25">
                保存
              </button>
              {existing && (
                <button onClick={forget} className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:text-destructive">
                  <Trash2 className="h-4 w-4" /> 清除
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-4 text-sm">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">选择模型</label>
              <select value={apiId} onChange={(e) => pickApiModel(e.target.value)}
                className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50">
                {apiModels.map((m) => (
                  <option key={m.id} value={m.id}>{m.name} —— {m.description}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Base URL</label>
              <input value={baseURL} onChange={(e) => setBaseURL(e.target.value)} placeholder="https://api.deepseek.com"
                className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50" />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Model</label>
              <input value={modelName} onChange={(e) => setModelName(e.target.value)} placeholder="模型名称（豆包填 ep-… 接入点 ID）"
                className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50" />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">API Key</label>
              <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-…"
                className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50" />
            </div>

            <div className="flex items-center gap-2">
              <button onClick={saveApi} className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25">
                保存（存本地）
              </button>
              {existing && (
                <button onClick={forget} className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:text-destructive">
                  <Trash2 className="h-4 w-4" /> 清除
                </button>
              )}
            </div>
          </div>
        )}
      </GlassCard>

      {/* 后端访问密钥：仅当后端部署时设置了 VR_API_KEY（公网防蹭用）才需要填 */}
      <GlassCard className="mt-4">
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <KeyRound className="h-4 w-4 text-primary" /> 后端访问密钥（可选）
        </h3>
        <p className="mb-3 text-xs text-muted-foreground">
          仅当后端部署时设置了 <code className="rounded bg-muted/50 px-1">VR_API_KEY</code>（公网部署防蹭用）才需要填，填后端同一个值；
          本机自用没设鉴权就留空。同样只存本地浏览器。
        </p>
        <div className="flex items-center gap-2">
          <input type="password" value={accessKey} onChange={(e) => setAccessKey(e.target.value)} placeholder="与后端 VR_API_KEY 保持一致"
            className="flex-1 rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50" />
          <button onClick={saveAccess} className="rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary hover:bg-primary/25">
            保存
          </button>
        </div>
      </GlassCard>

      {/* 资讯兴趣与智能筛选（TREND-PARITY Wave 2） */}
      <NativeIntelFilterSettingsSection />

      {/* 资讯来源管理（NATIVE-INTEL1 / TREND-PARITY Wave 1） */}
      <SourceRegistrySection />

      {/* 资讯展示与抓取高级控制（TREND-PARITY Wave 3） */}
      <NativeIntelDisplayAndProxySection />
    </div>
  );
}

function SourceRegistrySection() {
  const [sources, setSources] = useState<NativeIntelSourceRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [newHint, setNewHint] = useState("macro");
  const [submitting, setSubmitting] = useState(false);

  const fetchSources = async () => {
    try {
      const res = await api.nativeIntelSources();
      setSources(res.sources || []);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "获取来源列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchSources();
  }, []);

  const handleToggle = async (source: NativeIntelSourceRecord) => {
    try {
      await api.updateNativeIntelSource(source.source_id, { enabled: !source.enabled });
      toast.success(source.enabled ? `已停用 ${source.name}` : `已启用 ${source.name}`);
      await fetchSources();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "切换来源状态失败");
    }
  };

  const handleAddUserSource = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim() || !newUrl.trim()) {
      toast.error("请完整填写来源名称与 URL");
      return;
    }
    setSubmitting(true);
    try {
      await api.createNativeIntelSource({
        name: newName.trim(),
        url: newUrl.trim(),
        hint: newHint.trim() || "macro",
        enabled: true,
      });
      toast.success("成功添加自定义 RSS 源");
      setNewName("");
      setNewUrl("");
      await fetchSources();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "添加来源失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteUserSource = async (sourceId: string, name: string) => {
    try {
      await api.deleteNativeIntelSource(sourceId);
      toast.success(`已删除自定义来源 ${name}`);
      await fetchSources();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "删除来源失败");
    }
  };

  const handleUpdateFreshness = async (sourceId: string, maxAgeDays: number | null) => {
    try {
      await api.updateNativeIntelSource(sourceId, { max_age_days: maxAgeDays });
      toast.success("已更新新鲜度设置");
      await fetchSources();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "更新新鲜度失败");
    }
  };

  return (
    <GlassCard className="mt-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
          <Rss className="h-4 w-4 text-primary" /> 资讯源与热榜管理
        </h3>
        <button
          type="button"
          onClick={() => void fetchSources()}
          disabled={loading}
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
          刷新
        </button>
      </div>
      <p className="text-xs text-muted-foreground mb-4">
        管理原生资讯与热榜采集清单。系统预设源支持启停（禁止删除），自定义 RSS 源保存在本地数据库中。
      </p>

      {/* 新增用户自定义 RSS 源表单 */}
      <form onSubmit={handleAddUserSource} className="mb-4 rounded-lg border border-border/70 bg-background/50 p-3 text-xs space-y-2.5">
        <div className="font-medium text-foreground flex items-center gap-1">
          <Plus className="h-3.5 w-3.5 text-primary" /> 新增自定义 RSS 资讯源
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="来源名称（例如：自选科技博客）"
            className="rounded border border-border bg-black/20 px-2.5 py-1.5 text-xs outline-none focus:border-primary/50"
          />
          <input
            type="url"
            value={newUrl}
            onChange={(e) => setNewUrl(e.target.value)}
            placeholder="RSS / Atom 地址 (https://...)"
            className="rounded border border-border bg-black/20 px-2.5 py-1.5 text-xs outline-none focus:border-primary/50 sm:col-span-2"
          />
        </div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">分类标签:</span>
            <select
              value={newHint}
              onChange={(e) => setNewHint(e.target.value)}
              className="rounded border border-border bg-black/20 px-2 py-1 text-xs outline-none"
            >
              <option value="macro">宏观 / 综合</option>
              <option value="tech">科技 / 算力</option>
              <option value="finance">金融 / 市场</option>
              <option value="industry">行业 / 产业</option>
            </select>
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="rounded bg-primary/15 px-3 py-1 text-xs font-medium text-primary hover:bg-primary/25 disabled:opacity-50"
          >
            {submitting ? "添加中…" : "添加源"}
          </button>
        </div>
      </form>

      {/* 来源列表 */}
      <div className="max-h-80 overflow-y-auto divide-y divide-border/30 rounded-lg border border-border/60 bg-background/40">
        {loading && sources.length === 0 ? (
          <div className="p-4 text-center text-xs text-muted-foreground">
            <Loader2 className="mr-1.5 inline h-3.5 w-3.5 animate-spin" />
            读取来源中…
          </div>
        ) : sources.length === 0 ? (
          <div className="p-4 text-center text-xs text-muted-foreground">暂无可用来源</div>
        ) : (
          sources.map((src) => (
            <div
              key={src.source_id}
              className="flex items-center justify-between p-2.5 text-xs hover:bg-muted/20"
            >
              <div className="min-w-0 flex-1 pr-3">
                <div className="flex items-center gap-2">
                  <span className={`font-medium ${src.enabled ? "text-foreground" : "text-muted-foreground line-through"}`}>
                    {src.name}
                  </span>
                  <span className="rounded bg-muted px-1.5 py-0.2 text-[10px] text-muted-foreground">
                    {src.source_type}
                  </span>
                  {src.origin === "system" ? (
                    <span className="rounded bg-blue-500/10 text-blue-500 text-[10px] px-1">系统</span>
                  ) : (
                    <span className="rounded bg-emerald-500/10 text-emerald-500 text-[10px] px-1">自定义</span>
                  )}
                  {src.has_real_rank && (
                    <span className="rounded bg-amber-500/10 text-amber-500 text-[10px] px-1">真实排名</span>
                  )}
                </div>
                <div className="mt-0.5 truncate text-[10px] text-muted-foreground/70 font-mono">
                  {src.url}
                </div>
                {src.source_type === "rss" && (
                  <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                    <span>时效过滤:</span>
                    <select
                      data-testid={`source-freshness-select-${src.source_id}`}
                      value={
                        src.max_age_days === null || src.max_age_days === undefined
                          ? "inherit"
                          : src.max_age_days === 0
                          ? "disabled"
                          : "custom"
                      }
                      onChange={(e) => {
                        const val = e.target.value;
                        if (val === "inherit") {
                          void handleUpdateFreshness(src.source_id, null);
                        } else if (val === "disabled") {
                          void handleUpdateFreshness(src.source_id, 0);
                        } else {
                          void handleUpdateFreshness(src.source_id, 1);
                        }
                      }}
                      className="rounded border border-border bg-black/20 px-1.5 py-0.5 text-xs outline-none"
                    >
                      <option value="inherit">继承全局</option>
                      <option value="disabled">不过滤 (0)</option>
                      <option value="custom">自定义天数</option>
                    </select>
                    {src.max_age_days !== null && src.max_age_days !== undefined && src.max_age_days > 0 && (
                      <div className="inline-flex items-center gap-1">
                        <input
                          type="number"
                          min={1}
                          max={365}
                          data-testid={`source-freshness-input-${src.source_id}`}
                          defaultValue={src.max_age_days}
                          onBlur={(e) => {
                            const v = parseInt(e.target.value, 10);
                            if (!isNaN(v) && v > 0) {
                              void handleUpdateFreshness(src.source_id, v);
                            }
                          }}
                          className="w-14 rounded border border-border bg-black/20 px-1.5 py-0.5 text-xs outline-none"
                        />
                        <span>天</span>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => void handleToggle(src)}
                  className={`rounded px-2 py-1 text-[11px] font-medium border ${
                    src.enabled
                      ? "border-border text-muted-foreground hover:text-foreground"
                      : "border-primary/40 text-primary bg-primary/10"
                  }`}
                >
                  {src.enabled ? "停用" : "启用"}
                </button>

                {src.origin === "user" && (
                  <button
                    type="button"
                    onClick={() => void handleDeleteUserSource(src.source_id, src.name)}
                    className="rounded p-1 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                    title="删除自定义源"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </GlassCard>
  );
}


function NativeIntelFilterSettingsSection() {
  const [profile, setProfile] = useState<FilterProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [updatingTags, setUpdatingTags] = useState(false);
  const [classifying, setClassifying] = useState(false);

  const [method, setMethod] = useState<FilterMethod>("keyword");
  const [interestsText, setInterestsText] = useState("");
  const [minScore, setMinScore] = useState(0.7);
  const [globalExcludes, setGlobalExcludes] = useState<string[]>([]);
  const [filterTerms, setFilterTerms] = useState<string[]>([]);
  const [groups, setGroups] = useState<KeywordGroup[]>([]);
  const [tags, setTags] = useState<InterestTag[]>([]);

  const fetchProfile = async () => {
    try {
      const res = await api.nativeIntelFilterProfile();
      setProfile(res);
      setMethod(res.method || "keyword");
      setInterestsText(res.interests_text || "");
      setMinScore(res.min_score ?? 0.7);
      setGlobalExcludes(res.keyword_rules?.global_excludes || []);
      setFilterTerms(res.keyword_rules?.filter_terms || []);
      setGroups(
        (res.keyword_rules?.groups || []).map((g) => ({
          name: g.name || "",
          includes: g.includes || [],
          required: g.required || [],
          excludes: g.excludes || [],
          max_count: g.max_count ?? null,
        }))
      );
      setTags(res.tags || []);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "读取筛选配置失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchProfile();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      const isInterestsChanged =
        method === "ai" &&
        interestsText.trim() !== (profile?.interests_text || "").trim();

      if (isInterestsChanged) {
        const llm = loadLlm();
        if (!llm) {
          toast.error("尚未接入 AI，请先到「接入 AI」配置。");
          setSaving(false);
          return;
        }
        const res = await api.applyNativeIntelInterestUpdate({
          profile_id: profile?.profile_id || "default",
          interests_text: interestsText,
          ai_config: llm,
          min_score: minScore,
        });
        setProfile(res.profile);
        setTags(res.profile.tags || []);
        toast.success(`资讯筛选偏好已更新（${res.decision === "INCREMENTAL" ? "增量更新" : "全量重算"}）`);
      } else {
        const updated = await api.updateNativeIntelFilterProfile({
          name: profile?.name || "默认关注",
          method,
          interests_text: interestsText,
          min_score: minScore,
          keyword_rules: {
            global_excludes: globalExcludes,
            filter_terms: filterTerms,
            groups,
          },
          tags,
        });
        setProfile(updated);
        toast.success("资讯筛选偏好已保存");
      }
      await fetchProfile();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "保存筛选配置失败");
    } finally {
      setSaving(false);
    }
  };

  const handleExtractTags = async () => {
    const llm = loadLlm();
    if (!llm) {
      toast.error("尚未接入 AI，请先到「接入 AI」配置。");
      return;
    }
    if (!interestsText.trim()) {
      toast.error("请先填写个人兴趣描述");
      return;
    }
    setExtracting(true);
    try {
      const res = await api.extractNativeIntelFilterTags(interestsText, llm);
      setTags(res.tags || []);
      toast.success(`成功提取 ${res.tags.length} 个分类标签`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "AI 提取标签失败");
    } finally {
      setExtracting(false);
    }
  };

  const handleUpdateTags = async () => {
    const llm = loadLlm();
    if (!llm) {
      toast.error("尚未接入 AI，请先到「接入 AI」配置。");
      return;
    }
    if (!interestsText.trim()) {
      toast.error("请先填写新的兴趣描述");
      return;
    }
    setUpdatingTags(true);
    try {
      const res = await api.applyNativeIntelInterestUpdate({
        profile_id: profile?.profile_id || "default",
        interests_text: interestsText,
        ai_config: llm,
        min_score: minScore,
      });
      setProfile(res.profile);
      setTags(res.profile.tags || []);
      const modeText = res.decision === "INCREMENTAL" ? "增量更新" : "全量重算";
      toast.success(
        `增量更新完成（${modeText}，变动率 ${Math.round(res.change_ratio * 100)}%，保留 ${res.keep?.length ?? 0}，新增 ${res.add?.length ?? 0}，移除 ${res.remove?.length ?? 0}）`
      );
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "增量更新标签失败");
    } finally {
      setUpdatingTags(false);
    }
  };

  const handleSaveAndClassify = async () => {
    const llm = loadLlm();
    if (!llm) {
      toast.error("尚未接入 AI，请先到「接入 AI」配置。");
      return;
    }
    setClassifying(true);
    try {
      let canonicalProfile: FilterProfile;
      const isInterestsChanged =
        interestsText.trim() !== (profile?.interests_text || "").trim();

      if (isInterestsChanged) {
        const updateRes = await api.applyNativeIntelInterestUpdate({
          profile_id: profile?.profile_id || "default",
          interests_text: interestsText,
          ai_config: llm,
          min_score: minScore,
        });
        canonicalProfile = updateRes.profile;
        setProfile(canonicalProfile);
        setTags(canonicalProfile.tags || []);
      } else {
        canonicalProfile = await api.updateNativeIntelFilterProfile({
          name: profile?.name || "默认关注",
          method,
          interests_text: interestsText,
          min_score: minScore,
          keyword_rules: {
            global_excludes: globalExcludes,
            filter_terms: filterTerms,
            groups,
          },
          tags,
        });
        setProfile(canonicalProfile);
      }

      if (!canonicalProfile?.tags || canonicalProfile.tags.length === 0) {
        toast.error("请先提取或配置分类标签");
        setClassifying(false);
        return;
      }

      const res = await api.classifyNativeIntelItems({
        profile_id: canonicalProfile.profile_id || "default",
        limit: 100,
        ai_config: llm,
      });
      toast.success(`AI 批量分类完成：新分类 ${res.newly_classified ?? 0} 条，共计 ${res.classified ?? 0} 条`);
      await fetchProfile();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "保存并执行分类失败");
    } finally {
      setClassifying(false);
    }
  };

  const addGroup = () => {
    setGroups([...groups, { name: "新分组", includes: [""], required: [], excludes: [], max_count: null }]);
  };

  const updateGroupName = (idx: number, name: string) => {
    const updated = [...groups];
    updated[idx].name = name;
    setGroups(updated);
  };

  const updateGroupIncludes = (idx: number, text: string) => {
    const updated = [...groups];
    updated[idx].includes = text
      .split(/[,，\n]/)
      .map((s) => s.trim())
      .filter(Boolean);
    setGroups(updated);
  };

  const updateGroupRequired = (idx: number, text: string) => {
    const updated = [...groups];
    updated[idx].required = text
      .split(/[,，\n]/)
      .map((s) => s.trim())
      .filter(Boolean);
    setGroups(updated);
  };

  const updateGroupExcludes = (idx: number, text: string) => {
    const updated = [...groups];
    updated[idx].excludes = text
      .split(/[,，\n]/)
      .map((s) => s.trim())
      .filter(Boolean);
    setGroups(updated);
  };

  const updateGroupMaxCount = (idx: number, val: string) => {
    const updated = [...groups];
    const trimmed = val.trim();
    const num = trimmed === "" ? null : parseInt(trimmed, 10);
    updated[idx].max_count = num != null && !isNaN(num) ? num : null;
    setGroups(updated);
  };

  const removeGroup = (idx: number) => {
    setGroups(groups.filter((_, i) => i !== idx));
  };

  const removeTag = (idx: number) => {
    setTags(tags.filter((_, i) => i !== idx));
  };

  return (
    <GlassCard className="mt-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/40 pb-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <SlidersHorizontal className="h-4 w-4 text-primary" />
            资讯兴趣与智能筛选
            <span className="rounded bg-primary/10 px-1.5 py-0.2 text-[10px] text-primary font-mono">
              TREND-PARITY Wave 2
            </span>
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            支持本地关键词/正则规则与 AI 语义多标签过滤双轨并行，独立配置并存，无缝切换。
          </p>
        </div>

        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={saving || loading}
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
        >
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
          保存筛选设置
        </button>
      </div>

      {loading ? (
        <div className="py-8 text-center text-xs text-muted-foreground">
          <Loader2 className="mr-1.5 inline h-3.5 w-3.5 animate-spin" />
          读取筛选配置中…
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          {/* 模式选择 */}
          <div>
            <label className="block text-xs font-medium text-foreground mb-1.5">筛选引擎模式</label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setMethod("keyword")}
                className={`rounded-lg border p-2.5 text-left transition-all ${
                  method === "keyword"
                    ? "border-primary bg-primary/10 text-foreground ring-1 ring-primary"
                    : "border-border bg-background/50 text-muted-foreground hover:border-border/80"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-xs">本地关键词 / 正则过滤</span>
                  {method === "keyword" && <Check className="h-3.5 w-3.5 text-primary" />}
                </div>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  零模型依赖，支持多分组、全局排除与 /regex/
                </p>
              </button>

              <button
                type="button"
                onClick={() => setMethod("ai")}
                className={`rounded-lg border p-2.5 text-left transition-all ${
                  method === "ai"
                    ? "border-primary bg-primary/10 text-foreground ring-1 ring-primary"
                    : "border-border bg-background/50 text-muted-foreground hover:border-border/80"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-xs flex items-center gap-1">
                    <Sparkles className="h-3 w-3 text-amber-500" />
                    AI 智能语义过滤
                  </span>
                  {method === "ai" && <Check className="h-3.5 w-3.5 text-primary" />}
                </div>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  自然语言描述提取标签，批量分类与置信度过滤
                </p>
              </button>
            </div>
          </div>

          {/* 关键词模式 */}
          {method === "keyword" && (
            <div className="space-y-3 rounded-lg border border-border/50 bg-background/30 p-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">
                    全局排除词（[GLOBAL_FILTER] 命中即排）：
                  </label>
                  <input
                    type="text"
                    data-testid="settings-filter-global-excludes"
                    placeholder="如：震惊, /赌博|博彩/, 广告"
                    value={globalExcludes.join(", ")}
                    onChange={(e) =>
                      setGlobalExcludes(
                        e.target.value
                          .split(/[,，]/)
                          .map((s) => s.trim())
                          .filter(Boolean)
                      )
                    }
                    className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-foreground focus:border-primary focus:outline-none font-mono"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">
                    全局过滤词（!过滤词 filter_terms）：
                  </label>
                  <input
                    type="text"
                    data-testid="settings-filter-terms"
                    placeholder="如：推广, 虚假, /辟谣/"
                    value={filterTerms.join(", ")}
                    onChange={(e) =>
                      setFilterTerms(
                        e.target.value
                          .split(/[,，]/)
                          .map((s) => s.trim())
                          .filter(Boolean)
                      )
                    }
                    className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-foreground focus:border-primary focus:outline-none font-mono"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-foreground">兴趣分组列表</span>
                  <button
                    type="button"
                    onClick={addGroup}
                    className="inline-flex items-center gap-1 text-xs text-primary hover:underline font-medium"
                  >
                    <Plus className="h-3 w-3" />
                    添加分组
                  </button>
                </div>

                {groups.map((grp, idx) => (
                  <div
                    key={idx}
                    className="rounded-md border border-border/40 bg-card/60 p-2.5 space-y-1.5 text-xs"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <input
                        type="text"
                        placeholder="分组名称"
                        value={grp.name}
                        onChange={(e) => updateGroupName(idx, e.target.value)}
                        className="flex-1 font-semibold text-foreground bg-transparent border-b border-border/50 pb-0.5 focus:border-primary focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => removeGroup(idx)}
                        className="text-muted-foreground hover:text-destructive p-0.5"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      <div>
                        <span className="text-[11px] text-muted-foreground">包含词 (OR):</span>
                        <input
                          type="text"
                          data-testid={`settings-group-includes-${idx}`}
                          placeholder="逗号分隔，如：芯片, 半导体, /gpu/"
                          value={grp.includes.join(", ")}
                          onChange={(e) => updateGroupIncludes(idx, e.target.value)}
                          className="mt-0.5 w-full rounded border border-border/50 bg-background px-2 py-1 text-xs font-mono text-foreground focus:border-primary focus:outline-none"
                        />
                      </div>

                      <div>
                        <span className="text-[11px] text-muted-foreground">必须词 (+必须词 AND):</span>
                        <input
                          type="text"
                          data-testid={`settings-group-required-${idx}`}
                          placeholder="逗号分隔，如：GPU, 算力"
                          value={grp.required?.join(", ") || ""}
                          onChange={(e) => updateGroupRequired(idx, e.target.value)}
                          className="mt-0.5 w-full rounded border border-border/50 bg-background px-2 py-1 text-xs font-mono text-foreground focus:border-primary focus:outline-none"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      <div>
                        <span className="text-[11px] text-muted-foreground">组内排除词:</span>
                        <input
                          type="text"
                          data-testid={`settings-group-excludes-${idx}`}
                          placeholder="逗号分隔"
                          value={grp.excludes.join(", ")}
                          onChange={(e) => updateGroupExcludes(idx, e.target.value)}
                          className="mt-0.5 w-full rounded border border-border/50 bg-background px-2 py-1 text-xs font-mono text-foreground focus:border-primary focus:outline-none"
                        />
                      </div>

                      <div>
                        <span className="text-[11px] text-muted-foreground">最大条数上限 (@N):</span>
                        <input
                          type="number"
                          min={1}
                          max={100}
                          data-testid={`settings-group-max-count-${idx}`}
                          placeholder="留空不限，如：5"
                          value={grp.max_count ?? ""}
                          onChange={(e) => updateGroupMaxCount(idx, e.target.value)}
                          className="mt-0.5 w-full rounded border border-border/50 bg-background px-2 py-1 text-xs font-mono text-foreground focus:border-primary focus:outline-none"
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* AI 模式 */}
          {method === "ai" && (
            <div className="space-y-3 rounded-lg border border-border/50 bg-background/30 p-3">
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs font-medium text-foreground">
                    自然语言兴趣描述
                  </label>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => void handleExtractTags()}
                      disabled={extracting}
                      className="inline-flex items-center gap-1 rounded bg-primary/10 px-2 py-0.5 text-xs text-primary hover:bg-primary/20 font-medium disabled:opacity-50"
                    >
                      {extracting ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Sparkles className="h-3.5 w-3.5" />
                      )}
                      AI 提取标签
                    </button>
                    {tags.length > 0 && (
                      <button
                        type="button"
                        onClick={() => void handleUpdateTags()}
                        disabled={updatingTags}
                        className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground font-medium disabled:opacity-50"
                      >
                        {updatingTags && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                        增量对比更新
                      </button>
                    )}
                  </div>
                </div>
                <textarea
                  rows={3}
                  value={interestsText}
                  onChange={(e) => setInterestsText(e.target.value)}
                  placeholder="输入你的关注领域..."
                  className="w-full rounded-md border border-border bg-background p-2 text-xs text-foreground focus:border-primary focus:outline-none"
                />
              </div>

              <div>
                <span className="text-xs font-medium text-foreground flex items-center gap-1 mb-1">
                  <Tag className="h-3.5 w-3.5 text-primary" />
                  分类标签 ({tags.length})
                </span>
                {tags.length === 0 ? (
                  <p className="rounded border border-dashed border-border p-2.5 text-center text-xs text-muted-foreground">
                    尚未提取标签
                  </p>
                ) : (
                  <div className="max-h-36 overflow-y-auto divide-y divide-border/30 rounded border border-border bg-card/40">
                    {tags.map((t, idx) => (
                      <div key={idx} className="flex items-start justify-between p-2 text-xs gap-2">
                        <div>
                          <span className="font-medium text-primary">{t.tag}</span>
                          <p className="text-[11px] text-muted-foreground mt-0.5">{t.description}</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => removeTag(idx)}
                          className="text-muted-foreground hover:text-destructive p-0.5"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="font-medium text-foreground">相关度阈值 (min_score):</span>
                  <span className="font-mono font-bold text-primary">
                    {Math.round(minScore * 100)}%
                  </span>
                </div>
                <input
                  type="range"
                  data-testid="settings-filter-min-score-slider"
                  min="0.1"
                  max="1.0"
                  step="0.05"
                  value={minScore}
                  onChange={(e) => setMinScore(parseFloat(e.target.value))}
                  className="w-full accent-primary h-1.5 bg-muted rounded cursor-pointer"
                />
              </div>

              <button
                type="button"
                data-testid="settings-save-and-classify-button"
                onClick={() => void handleSaveAndClassify()}
                disabled={classifying || tags.length === 0}
                className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg border border-border bg-background py-1.5 text-xs font-medium text-foreground hover:bg-muted transition-colors disabled:opacity-50"
              >
                {classifying ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5 text-purple-400" />
                )}
                保存并执行 AI 分类
              </button>
            </div>
          )}
        </div>
      )}
    </GlassCard>
  );
}


function NativeIntelDisplayAndProxySection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [sources, setSources] = useState<NativeIntelSourceRecord[]>([]);

  const [rssFreshnessEnabled, setRssFreshnessEnabled] = useState(false);
  const [rssGlobalMaxAgeDays, setRssGlobalMaxAgeDays] = useState(1);

  const [crawlerProxyEnabled, setCrawlerProxyEnabled] = useState(false);
  const [crawlerProxyUrl, setCrawlerProxyUrl] = useState("");
  const [rssProxyEnabled, setRssProxyEnabled] = useState(false);
  const [rssProxyUrl, setRssProxyUrl] = useState("");

  const [standaloneEnabled, setStandaloneEnabled] = useState(true);
  const [standaloneSourceIds, setStandaloneSourceIds] = useState<string[]>([]);
  const [standaloneMaxItems, setStandaloneMaxItems] = useState(20);

  const [regionOrder, setRegionOrder] = useState<string[]>(["hotlist", "rss", "standalone"]);
  const [regionsEnabled, setRegionsEnabled] = useState<Record<string, boolean>>({
    hotlist: true,
    rss: true,
    standalone: true,
    new_items: false,
    ai_analysis: false,
  });
  const [aiAnalysisEnabled, setAiAnalysisEnabled] = useState(false);
  const [aiAnalysisProvider, setAiAnalysisProvider] = useState("cli-codex");
  const [aiAnalysisModel, setAiAnalysisModel] = useState("gpt-5-codex");
  const [aiAnalysisMaxNews, setAiAnalysisMaxNews] = useState(50);
  const [aiAnalysisIncludeRss, setAiAnalysisIncludeRss] = useState(true);
  const [aiAnalysisIncludeStandalone, setAiAnalysisIncludeStandalone] = useState(false);
  const [aiTranslationEnabled, setAiTranslationEnabled] = useState(false);
  const [aiTranslationTargetLanguage, setAiTranslationTargetLanguage] = useState("English");

  const loadConfig = async () => {
    setLoading(true);
    try {
      const [cfg, srcRes] = await Promise.all([
        api.nativeIntelConfig(),
        api.nativeIntelSources(),
      ]);
      setSources(srcRes.sources || []);
      setRssFreshnessEnabled(Boolean(cfg.rss_freshness_enabled));
      setRssGlobalMaxAgeDays(Number(cfg.rss_global_max_age_days ?? 1));
      setCrawlerProxyEnabled(Boolean(cfg.crawler_proxy_enabled));
      setCrawlerProxyUrl(cfg.crawler_proxy_url || "");
      setRssProxyEnabled(Boolean(cfg.rss_proxy_enabled));
      setRssProxyUrl(cfg.rss_proxy_url || "");
      setStandaloneEnabled(cfg.standalone_enabled !== false);
      setStandaloneSourceIds(cfg.standalone_source_ids || []);
      setStandaloneMaxItems(Number(cfg.standalone_max_items ?? 20));
      if (Array.isArray(cfg.region_order) && cfg.region_order.length > 0) {
        setRegionOrder(cfg.region_order);
      }
      if (cfg.regions_enabled) {
        setRegionsEnabled(cfg.regions_enabled);
      }
      setAiAnalysisEnabled(Boolean(cfg.ai_analysis_enabled));
      setAiAnalysisProvider(cfg.ai_analysis_provider || "cli-codex");
      setAiAnalysisModel(cfg.ai_analysis_model || "gpt-5-codex");
      setAiAnalysisMaxNews(Number(cfg.ai_analysis_max_news ?? 50));
      setAiAnalysisIncludeRss(cfg.ai_analysis_include_rss !== false);
      setAiAnalysisIncludeStandalone(Boolean(cfg.ai_analysis_include_standalone));
      setAiTranslationEnabled(Boolean(cfg.ai_translation_enabled));
      setAiTranslationTargetLanguage(cfg.ai_translation_target_language || "English");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "读取展示与抓取配置失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadConfig();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateNativeIntelConfig({
        rss_freshness_enabled: rssFreshnessEnabled,
        rss_global_max_age_days: rssGlobalMaxAgeDays,
        crawler_proxy_enabled: crawlerProxyEnabled,
        crawler_proxy_url: crawlerProxyUrl.trim(),
        rss_proxy_enabled: rssProxyEnabled,
        rss_proxy_url: rssProxyUrl.trim(),
        standalone_enabled: standaloneEnabled,
        standalone_source_ids: standaloneSourceIds,
        standalone_max_items: standaloneMaxItems,
        region_order: regionOrder,
        regions_enabled: regionsEnabled,
        ai_analysis_enabled: aiAnalysisEnabled,
        ai_analysis_provider: aiAnalysisProvider,
        ai_analysis_model: aiAnalysisModel,
        ai_analysis_max_news: aiAnalysisMaxNews,
        ai_analysis_include_rss: aiAnalysisIncludeRss,
        ai_analysis_include_standalone: aiAnalysisIncludeStandalone,
        ai_translation_enabled: aiTranslationEnabled,
        ai_translation_target_language: aiTranslationTargetLanguage,
      });
      toast.success("已保存展示与抓取高级设置");
      await loadConfig();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "保存配置失败");
    } finally {
      setSaving(false);
    }
  };

  const toggleStandaloneSource = (sid: string) => {
    setStandaloneSourceIds((prev) =>
      prev.includes(sid) ? prev.filter((id) => id !== sid) : [...prev, sid],
    );
  };

  const moveRegion = (index: number, direction: "up" | "down") => {
    const targetIndex = direction === "up" ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= regionOrder.length) return;
    const nextOrder = [...regionOrder];
    const temp = nextOrder[index];
    nextOrder[index] = nextOrder[targetIndex];
    nextOrder[targetIndex] = temp;
    setRegionOrder(nextOrder);
  };

  const regionNames: Record<string, string> = {
    hotlist: "实时热榜 (hotlist)",
    rss: "RSS 资讯 (rss)",
    standalone: "重点独立展示区 (standalone)",
    new_items: "新出现资讯 (new_items)",
    ai_analysis: "AI 深度分析与研报 (ai_analysis)",
  };

  return (
    <GlassCard className="mt-4" data-testid="native-intel-wave3-settings">
      <div className="flex items-center justify-between mb-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
          <Layers className="h-4 w-4 text-primary" /> 资讯展示与抓取高级控制 (Wave 3)
        </h3>
        <button
          type="button"
          onClick={() => void loadConfig()}
          disabled={loading}
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
          刷新配置
        </button>
      </div>
      <p className="text-xs text-muted-foreground mb-4">
        配置 RSS 新鲜度过滤阈值、抓取网络代理通道、重点免过滤独立展示区以及板面区域开关与渲染顺序。
      </p>

      {loading ? (
        <div className="p-6 text-center text-xs text-muted-foreground">
          <Loader2 className="mr-1.5 inline h-4 w-4 animate-spin" />
          正在读取配置…
        </div>
      ) : (
        <div className="space-y-5">
          {/* 1. RSS 全局新鲜度过滤 */}
          <div className="rounded-lg border border-border/70 bg-background/50 p-3 text-xs space-y-2.5">
            <div className="font-medium text-foreground flex items-center gap-1">
              <Rss className="h-3.5 w-3.5 text-primary" /> RSS 全局时效过滤 (Freshness Policy)
            </div>
            <p className="text-muted-foreground text-[11px]">
              根据文章发布时间过滤陈旧历史资讯；未声明发布时间的文章自动保留，绝不因缺少时间而误丢弃。
            </p>
            <div className="flex flex-wrap items-center gap-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  data-testid="wave3-rss-freshness-enabled"
                  checked={rssFreshnessEnabled}
                  onChange={(e) => setRssFreshnessEnabled(e.target.checked)}
                  className="rounded border-border accent-primary"
                />
                <span className="font-medium">启用全局 RSS 新鲜度过滤</span>
              </label>

              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground">全局最大文章年龄:</span>
                <input
                  type="number"
                  min={0}
                  max={365}
                  data-testid="wave3-rss-global-max-age"
                  value={rssGlobalMaxAgeDays}
                  onChange={(e) => setRssGlobalMaxAgeDays(Math.max(0, parseInt(e.target.value, 10) || 0))}
                  className="w-16 rounded border border-border bg-black/20 px-2 py-1 text-xs outline-none focus:border-primary/50"
                />
                <span>天 (0 表示不过滤)</span>
              </div>
            </div>
          </div>

          {/* 2. 网络代理设置 */}
          <div className="rounded-lg border border-border/70 bg-background/50 p-3 text-xs space-y-2.5">
            <div className="font-medium text-foreground flex items-center gap-1">
              <Globe className="h-3.5 w-3.5 text-primary" /> 网络抓取代理通道 (Crawler & RSS Proxy)
            </div>
            <p className="text-muted-foreground text-[11px]">
              支持配置 HTTP/HTTPS 网络代理通道。代理仅存本地，密码脱敏防泄露，代理失败严格记录独立源错误不伪造成功。
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              {/* 爬虫代理 */}
              <div className="space-y-1.5 rounded border border-border/40 p-2.5 bg-card/30">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    data-testid="wave3-crawler-proxy-enabled"
                    checked={crawlerProxyEnabled}
                    onChange={(e) => setCrawlerProxyEnabled(e.target.checked)}
                    className="rounded border-border accent-primary"
                  />
                  <span className="font-medium">热榜爬虫代理通道</span>
                </label>
                <input
                  type="text"
                  data-testid="wave3-crawler-proxy-url"
                  value={crawlerProxyUrl}
                  onChange={(e) => setCrawlerProxyUrl(e.target.value)}
                  placeholder="http://127.0.0.1:7890"
                  className="w-full rounded border border-border bg-black/20 px-2.5 py-1 text-xs outline-none focus:border-primary/50"
                />
                <span className="text-[10px] text-muted-foreground block">
                  应用于 11 个公开热榜平台的数据抓取通道
                </span>
              </div>

              {/* RSS 代理 */}
              <div className="space-y-1.5 rounded border border-border/40 p-2.5 bg-card/30">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    data-testid="wave3-rss-proxy-enabled"
                    checked={rssProxyEnabled}
                    onChange={(e) => setRssProxyEnabled(e.target.checked)}
                    className="rounded border-border accent-primary"
                  />
                  <span className="font-medium">RSS 抓取代理通道</span>
                </label>
                <input
                  type="text"
                  data-testid="wave3-rss-proxy-url"
                  value={rssProxyUrl}
                  onChange={(e) => setRssProxyUrl(e.target.value)}
                  placeholder="留空时自动复用热榜爬虫代理"
                  className="w-full rounded border border-border bg-black/20 px-2.5 py-1 text-xs outline-none focus:border-primary/50"
                />
                <span className="text-[10px] text-muted-foreground block">
                  留空且启用时，自动回退使用爬虫代理 URL
                </span>
              </div>
            </div>
          </div>

          {/* 3. 重点独立展示区 (Standalone) */}
          <div className="rounded-lg border border-border/70 bg-background/50 p-3 text-xs space-y-2.5">
            <div className="font-medium text-foreground flex items-center gap-1">
              <Sparkles className="h-3.5 w-3.5 text-primary" /> 重点独立展示区 (display.standalone)
            </div>
            <p className="text-muted-foreground text-[11px]">
              选中的重点资讯源条目将绕过个人兴趣与关键词过滤完整呈现；Hotlist 保持真实排名与异动轨迹，RSS 依然遵守新鲜度时效。
            </p>
            <div className="flex flex-wrap items-center gap-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  data-testid="wave3-standalone-enabled"
                  checked={standaloneEnabled}
                  onChange={(e) => setStandaloneEnabled(e.target.checked)}
                  className="rounded border-border accent-primary"
                />
                <span className="font-medium">启用重点独立展示区</span>
              </label>

              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground">每来源最多展示:</span>
                <input
                  type="number"
                  min={1}
                  max={200}
                  data-testid="wave3-standalone-max-items"
                  value={standaloneMaxItems}
                  onChange={(e) => setStandaloneMaxItems(Math.max(1, parseInt(e.target.value, 10) || 20))}
                  className="w-16 rounded border border-border bg-black/20 px-2 py-1 text-xs outline-none focus:border-primary/50"
                />
                <span>条</span>
              </div>
            </div>

            <div>
              <span className="text-muted-foreground block mb-1">选择纳入独立展示区的来源:</span>
              <div className="max-h-36 overflow-y-auto grid grid-cols-2 sm:grid-cols-3 gap-1.5 rounded border border-border/60 bg-card/40 p-2">
                {sources.map((s) => (
                  <label
                    key={s.source_id}
                    className="flex items-center gap-1.5 text-[11px] hover:text-foreground cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      data-testid={`wave3-standalone-source-${s.source_id}`}
                      checked={standaloneSourceIds.includes(s.source_id)}
                      onChange={() => toggleStandaloneSource(s.source_id)}
                      className="rounded border-border accent-primary"
                    />
                    <span className="truncate font-mono text-[10px]">{s.source_id}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>

          {/* 4. 资讯展示区域开关与排序 */}
          <div className="rounded-lg border border-border/70 bg-background/50 p-3 text-xs space-y-2.5">
            <div className="font-medium text-foreground flex items-center gap-1">
              <Layers className="h-3.5 w-3.5 text-primary" /> 资讯板面区域开关与排序 (Display Regions)
            </div>
            <p className="text-muted-foreground text-[11px]">
              控制板面上各区域的显示与上下排列顺序。全部关闭时诚实显示已关闭提示。
            </p>

            <div className="flex flex-wrap gap-4 py-1">
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  data-testid="wave3-region-toggle-hotlist"
                  checked={regionsEnabled.hotlist !== false}
                  onChange={(e) =>
                    setRegionsEnabled((prev) => ({ ...prev, hotlist: e.target.checked }))
                  }
                  className="rounded border-border accent-primary"
                />
                <span>实时热榜 (hotlist)</span>
              </label>

              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  data-testid="wave3-region-toggle-rss"
                  checked={regionsEnabled.rss !== false}
                  onChange={(e) =>
                    setRegionsEnabled((prev) => ({ ...prev, rss: e.target.checked }))
                  }
                  className="rounded border-border accent-primary"
                />
                <span>RSS 资讯 (rss)</span>
              </label>

              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  data-testid="wave3-region-toggle-standalone"
                  checked={regionsEnabled.standalone !== false}
                  onChange={(e) =>
                    setRegionsEnabled((prev) => ({ ...prev, standalone: e.target.checked }))
                  }
                  className="rounded border-border accent-primary"
                />
                <span>重点独立区 (standalone)</span>
              </label>

              <label className="flex items-center gap-1.5 cursor-pointer">
                <input type="checkbox" data-testid="wave4-region-toggle-new_items"
                  checked={regionsEnabled.new_items === true}
                  onChange={(e) => {
                    setRegionsEnabled((prev) => ({ ...prev, new_items: e.target.checked }));
                    if (e.target.checked) setRegionOrder((prev) => prev.includes("new_items") ? prev : [...prev, "new_items"]);
                  }} className="rounded border-border accent-primary" />
                <span>新出现资讯 (new_items)</span>
              </label>

              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  data-testid="wave5-region-toggle-ai_analysis"
                  checked={regionsEnabled.ai_analysis === true}
                  onChange={(e) => {
                    setRegionsEnabled((prev) => ({ ...prev, ai_analysis: e.target.checked }));
                    if (e.target.checked) setRegionOrder((prev) => prev.includes("ai_analysis") ? prev : [...prev, "ai_analysis"]);
                  }}
                  className="rounded border-border accent-primary"
                />
                <span>AI 深度分析 (ai_analysis)</span>
              </label>
            </div>

            {/* 区域排序列表 */}
            <div>
              <span className="text-muted-foreground block mb-1">区域从上到下排列顺序:</span>
              <div
                data-testid="wave3-region-order-list"
                className="space-y-1.5 rounded border border-border/60 bg-card/40 p-2 max-w-md"
              >
                {regionOrder
                  .filter((r) => ["hotlist", "rss", "standalone", "new_items", "ai_analysis"].includes(r))
                  .map((r, idx, arr) => (
                    <div
                      key={r}
                      className="flex items-center justify-between rounded bg-background/80 px-2.5 py-1.5 border border-border/40 text-xs"
                    >
                      <span className="font-medium text-foreground">
                        {idx + 1}. {regionNames[r] || r}
                      </span>
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          disabled={idx === 0}
                          data-testid={`wave3-move-up-${r}`}
                          onClick={() => moveRegion(regionOrder.indexOf(r), "up")}
                          className="rounded p-1 hover:bg-muted text-muted-foreground hover:text-foreground disabled:opacity-30"
                          title="上移"
                        >
                          <ArrowUp className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          disabled={idx === arr.length - 1}
                          data-testid={`wave3-move-down-${r}`}
                          onClick={() => moveRegion(regionOrder.indexOf(r), "down")}
                          className="rounded p-1 hover:bg-muted text-muted-foreground hover:text-foreground disabled:opacity-30"
                          title="下移"
                        >
                          <ArrowDown className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          </div>

          {/* 5. AI 深度分析与多语言翻译 (Wave 5) */}
          <div className="rounded-lg border border-border/70 bg-background/50 p-3 text-xs space-y-3" data-testid="wave5-ai-settings-section">
            <div className="font-medium text-foreground flex items-center gap-1">
              <Sparkles className="h-3.5 w-3.5 text-primary" /> AI 深度分析与多语言翻译 (Wave 5)
            </div>
            <p className="text-muted-foreground text-[11px]">
              统一接入 Codex 或 OpenAI 兼容大模型，支持实时/全天/增量资讯 6 大板块深度研报生成，以及多语言翻译。
            </p>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-2 rounded border border-border/40 p-2.5 bg-card/30">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    data-testid="wave5-ai-analysis-enabled"
                    checked={aiAnalysisEnabled}
                    onChange={(e) => setAiAnalysisEnabled(e.target.checked)}
                    className="rounded border-border accent-primary"
                  />
                  <span className="font-medium">启用 AI 深度分析研报</span>
                </label>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <span className="text-[11px] text-muted-foreground block mb-1">提供商</span>
                    <select
                      data-testid="wave5-ai-analysis-provider"
                      value={aiAnalysisProvider}
                      onChange={(e) => setAiAnalysisProvider(e.target.value)}
                      className="w-full rounded border border-border bg-black/20 px-2 py-1 text-xs outline-none focus:border-primary/50"
                    >
                      <option value="cli-codex">Codex CLI / 订阅</option>
                      <option value="openai-compatible">OpenAI Compatible</option>
                    </select>
                  </div>
                  <div>
                    <span className="text-[11px] text-muted-foreground block mb-1">模型名称</span>
                    <input
                      type="text"
                      data-testid="wave5-ai-analysis-model"
                      value={aiAnalysisModel}
                      onChange={(e) => setAiAnalysisModel(e.target.value)}
                      className="w-full rounded border border-border bg-black/20 px-2 py-1 text-xs outline-none focus:border-primary/50"
                      placeholder="gpt-5-codex"
                    />
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-muted-foreground">分析最大资讯数:</span>
                  <input
                    type="number"
                    min={1}
                    max={200}
                    data-testid="wave5-ai-analysis-max-news"
                    value={aiAnalysisMaxNews}
                    onChange={(e) => setAiAnalysisMaxNews(Math.max(1, Math.min(200, parseInt(e.target.value, 10) || 50)))}
                    className="w-16 rounded border border-border bg-black/20 px-2 py-1 text-xs outline-none focus:border-primary/50"
                  />
                </div>

                <div className="flex items-center gap-3 pt-1">
                  <label className="flex items-center gap-1.5 cursor-pointer text-[11px]">
                    <input
                      type="checkbox"
                      data-testid="wave5-ai-include-rss"
                      checked={aiAnalysisIncludeRss}
                      onChange={(e) => setAiAnalysisIncludeRss(e.target.checked)}
                      className="rounded border-border accent-primary"
                    />
                    <span>纳入 RSS</span>
                  </label>
                  <label className="flex items-center gap-1.5 cursor-pointer text-[11px]">
                    <input
                      type="checkbox"
                      data-testid="wave5-ai-include-standalone"
                      checked={aiAnalysisIncludeStandalone}
                      onChange={(e) => setAiAnalysisIncludeStandalone(e.target.checked)}
                      className="rounded border-border accent-primary"
                    />
                    <span>纳入独立源摘要</span>
                  </label>
                </div>
              </div>

              <div className="space-y-2 rounded border border-border/40 p-2.5 bg-card/30">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    data-testid="wave5-ai-translation-enabled"
                    checked={aiTranslationEnabled}
                    onChange={(e) => setAiTranslationEnabled(e.target.checked)}
                    className="rounded border-border accent-primary"
                  />
                  <span className="font-medium">启用 AI 多语言翻译</span>
                </label>

                <div>
                  <span className="text-[11px] text-muted-foreground block mb-1">默认目标语言</span>
                  <input
                    type="text"
                    data-testid="wave5-ai-translation-target-lang"
                    value={aiTranslationTargetLanguage}
                    onChange={(e) => setAiTranslationTargetLanguage(e.target.value)}
                    className="w-full rounded border border-border bg-black/20 px-2 py-1 text-xs outline-none focus:border-primary/50"
                    placeholder="English / Chinese / Japanese"
                  />
                </div>
                <span className="text-[10px] text-muted-foreground block">
                  资讯条目可一键翻译标题与摘要，支持单条与批量，严格保持编号映射。
                </span>
              </div>
            </div>
          </div>

          {/* 保存按钮 */}
          <button
            type="button"
            data-testid="wave3-save-config-btn"
            onClick={() => void handleSave()}
            disabled={saving}
            className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-xs font-medium text-primary-foreground shadow-sm hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            {saving ? "保存中…" : "保存展示与抓取设置"}
          </button>
        </div>
      )}
    </GlassCard>
  );
}
