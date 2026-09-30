import { loadLlm, LLM_CHANGED_EVENT } from "./llm.ts";
import { loadNotesState, NOTES_CHANGED_EVENT } from "./notes.ts";

export interface FirstResearchLocalState {
  provider: string | null;
  noteCount: number;
  notesReadable: boolean;
}

export interface CredentialMirrorStatus {
  configured: boolean;
  provider: string | null;
}

// Project only the evidence needed by the UI; never retain keys or note contents.
export function readFirstResearchLocalState(): FirstResearchLocalState {
  const config = loadLlm();
  const notes = loadNotesState();
  return { provider: config?.provider ?? null, noteCount: notes.notes.length, notesReadable: !notes.error };
}

export function subscribeFirstResearchState(onChange: () => void): () => void {
  const events = [LLM_CHANGED_EVENT, NOTES_CHANGED_EVENT, "storage", "focus"];
  events.forEach((event) => window.addEventListener(event, onChange));
  return () => events.forEach((event) => window.removeEventListener(event, onChange));
}

export function firstResearchStatus(local: FirstResearchLocalState, mirror: CredentialMirrorStatus | null) {
  return {
    browser: local.provider ? "已读取到保存的配置" : "未读取到完整配置，请在下方配置并保存",
    mirror: mirror === null ? "状态未知，请确认后端连接后重新保存"
      : !mirror.configured ? "尚未保存，请在下方保存配置"
      : local.provider && mirror.provider !== local.provider ? "与浏览器的接入方式不同，请重新保存以同步"
      : "后台已有配置（不代表与浏览器配置完全一致）",
    model: "本页未验证模型调用；保存配置或登录成功不代表模型已成功回答",
    capability: local.provider === "cli-codex"
      ? "Codex 订阅基于当前页面上下文回答，不提供 Shell、磁盘、网页搜索或正式写入能力。"
      : local.provider?.startsWith("cli-")
        ? "检测到旧版 CLI 配置，能力与可用性取决于对应运行时；请在下方重新选择当前支持的接入方式。"
      : local.provider
        ? "API 对话可使用产品提供的受控查询工具；是否支持工具调用仍取决于所选模型与端点。"
        : "选择接入方式后可查看相应能力边界。",
    research: !local.notesReadable ? "无法读取本地研究记录，请到研究笔记检查或恢复备份"
      : local.noteCount > 0 ? `本机浏览器已有 ${local.noteCount} 条研究记录`
      : "尚无本地研究记录，可从个股数据开始并保存一条研究笔记",
  };
}
