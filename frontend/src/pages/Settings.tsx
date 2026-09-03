import { useEffect, useState } from "react";
import { KeyRound, Sparkles, ShieldCheck, Check, Trash2, Terminal, Loader2, RefreshCw } from "lucide-react";
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
import { loadAccessKey, saveAccessKey } from "@/lib/api";
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
    </div>
  );
}
