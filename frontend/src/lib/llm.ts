// 用户 LLM 配置（只存本地 localStorage，不上传、不进仓库）+ 系统 AI 对话调用。

import { ApiError, streamNdjson, type NdjsonStreamResult } from "./api.ts";
import { isCliProvider, type ProviderId } from "./ai-models.ts";

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

export type ChatResult = NdjsonStreamResult;

const KEY = "vr-llm";

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
  localStorage.setItem(KEY, JSON.stringify(cfg));
}

export function clearLlm() {
  localStorage.removeItem(KEY);
}

export function hasLlm(): boolean {
  return loadLlm() !== null;
}

export interface ChatHandlers {
  onDelta?: (text: string) => void;             // 答案逐块吐字
  onTool?: (tool: string, args: Record<string, unknown>) => void; // AI 调了某数据工具
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
): Promise<ChatResult> {
  const llm = loadLlm();
  if (!llm) throw new ApiError("尚未接入 AI，请先在「接入 AI」里配置", 400);
  return streamNdjson("/chat", { messages, context, llm }, handlers, signal);
}

// 非流式便捷包装（不需要逐字 UI 的调用方用它）。
export function chat(messages: ChatMsg[], context: string): Promise<ChatResult> {
  return chatStream(messages, context);
}
