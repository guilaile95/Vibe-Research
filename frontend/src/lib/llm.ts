// 用户 LLM 配置（只存本地 localStorage，不上传、不进仓库）+ 系统 AI 对话调用。

import { ApiError, request, streamNdjson, type NdjsonStreamResult, type ReportChatSource } from "./api.ts";
import { isCliProvider, type ProviderId } from "./ai-models.ts";
import { storageSet, storageRemove } from "./storage.ts";

export interface LlmConfig {
  provider: ProviderId;
  baseURL: string; // CLI 订阅时留空
  apiKey: string;  // CLI 订阅时留空
  model: string;
}

export interface ChatMsg {
  role: "user" | "assistant";
  content: string;
}

export type ChatReportSource = ReportChatSource;

export type ChatResult = NdjsonStreamResult;

const KEY = "vr-llm";
export const LLM_CHANGED_EVENT = "vr-llm-change";

function notifyLlmChanged() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(LLM_CHANGED_EVENT));
}

export function loadLlm(): LlmConfig | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const c = JSON.parse(raw) as LlmConfig;
    // 订阅(CLI)：有 model 即可，免 key；API：需 baseURL + key + model。
    const ok = c.model && (isCliProvider(c.provider) || (c.baseURL && c.apiKey));
    return ok ? c : null;
  } catch {
    return null;
  }
}

export function saveLlm(cfg: LlmConfig) {
  storageSet(KEY, JSON.stringify(cfg));
  notifyLlmChanged();
}

export function clearLlm() {
  storageRemove(KEY);
  notifyLlmChanged();
}

export function hasLlm(): boolean {
  return loadLlm() !== null;
}

export interface ChatHandlers {
  onDelta?: (text: string) => void;             // 答案逐块吐字
  onTool?: (tool: string, args: Record<string, unknown>) => void; // AI 调了某数据工具
  onSources?: (items: ChatReportSource[]) => void;
}

export interface AgentRuntimeStatus {
  runtime: "Codex Subscription";
  installed: boolean;
  authenticated: boolean;
  available: boolean;
  status: "ready" | "not_authenticated" | "login_pending" | "login_failed" | "runtime_unavailable";
  version: string | null;
}

export function llmIdentity(cfg: LlmConfig | null = loadLlm()): string {
  return cfg ? `${cfg.provider}:${cfg.model}:${cfg.baseURL}` : "none";
}

export function runtimeLabel(cfg: LlmConfig | null = loadLlm()): string {
  if (!cfg) return "未配置 Runtime";
  return cfg.provider === "cli-codex" ? "Codex Subscription" : `API Compatible / ${cfg.model}`;
}

export function chatSessionId(key: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < key.length; index += 1) {
    hash ^= key.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  const slug = key.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^[^A-Za-z0-9]+/, "").slice(0, 40);
  return `p${hash.toString(36)}-${slug || "page"}`.slice(0, 64);
}

export function getAgentRuntimeStatus(signal?: AbortSignal): Promise<AgentRuntimeStatus> {
  return request<AgentRuntimeStatus>("/agent-runtime/status", "GET", undefined, { unwrapData: false, signal });
}

export function startAgentRuntimeLogin(): Promise<{ runtime: string; state: string }> {
  return request("/agent-runtime/login", "POST", {}, { unwrapData: false });
}

// 流式调后端 /api/chat（NDJSON：每行一个事件 {type: tool|delta|done|error}）。
// 边流边回调 onDelta/onTool；返回累积的最终 {content, trace, rounds}。
// signal：调用方可传 AbortController.signal，用户关面板/换问题时中止请求（省订阅/API 额度）。
// 解析逻辑复用 api.streamNdjson，行为与抽取前一致。
export async function chatStream(
  messages: ChatMsg[],
  context: string,
  handlers: ChatHandlers = {},
  signal?: AbortSignal,
  session?: string,
  reportIds: string[] = [],
): Promise<ChatResult> {
  const llm = loadLlm();
  if (!llm) throw new ApiError("尚未接入 AI，请先在「接入 AI」里配置", 400);
  return streamNdjson(
    "/chat",
    { messages, context, session: session || "", report_ids: reportIds, llm },
    handlers,
    signal,
  );
}

// 非流式便捷包装（不需要逐字 UI 的调用方用它）。
export function chat(messages: ChatMsg[], context: string): Promise<ChatResult> {
  return chatStream(messages, context);
}
