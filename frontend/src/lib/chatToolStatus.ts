import type { ChatToolResult } from "./api/types.ts";

export interface ChatToolUse {
  name: string;
  arg: string;
  callId?: string;
  status: "pending" | "unknown" | ChatToolResult["status"];
  truncated: boolean;
}

export function parseChatToolResult(value: unknown): ChatToolResult | undefined {
  if (!value || typeof value !== "object") return undefined;
  const item = value as Record<string, unknown>;
  if (typeof item.call_id !== "string" || !item.call_id || item.call_id.length > 128 ||
      typeof item.tool !== "string" || !item.tool || item.tool.length > 128 ||
      !["success", "partial", "empty", "error"].includes(String(item.status)) ||
      typeof item.truncated !== "boolean") return undefined;
  return { call_id: item.call_id, tool: item.tool,
    status: item.status as ChatToolResult["status"], truncated: item.truncated };
}

/** Old transcripts recorded attempts only. Never hydrate them as successes. */
export function parseStoredChatTools(value: unknown): ChatToolUse[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item) => item && typeof item.name === "string" && typeof item.arg === "string")
    .slice(0, 100).map((item) => ({
      name: item.name, arg: item.arg,
      callId: typeof item.callId === "string" ? item.callId : undefined,
      status: ["success", "partial", "empty", "error"].includes(item.status) ? item.status : "unknown",
      truncated: item.truncated === true,
    }));
}

export function applyChatToolResult(tools: ChatToolUse[], result: ChatToolResult): ChatToolUse[] {
  return tools.map((tool) => tool.callId === result.call_id && tool.name === result.tool
    ? { ...tool, status: result.status, truncated: result.truncated } : tool);
}

export function chatToolStatusLabel(tool: ChatToolUse, active: boolean): string {
  const label = tool.status === "pending" ? (active ? "请求中" : "未确认完成")
    : tool.status === "success" ? "已返回"
    : tool.status === "partial" ? "返回受限"
    : tool.status === "empty" ? "无返回数据"
    : tool.status === "error" ? "获取失败" : "结果未知";
  return label + (tool.truncated ? " · 部分结果" : "");
}
