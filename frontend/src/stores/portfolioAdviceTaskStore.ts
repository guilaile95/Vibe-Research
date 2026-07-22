import { create } from "zustand";
import { api, ApiError, type PortfolioAdviceResult, type StreamLlmConfig } from "@/lib/api";
import type { LlmConfig } from "@/lib/llm";

export type PortfolioAdviceTaskStatus =
  | "idle"
  | "running"
  | "success"
  | "error";

export interface PortfolioAdviceTaskState {
  status: PortfolioAdviceTaskStatus;
  result: PortfolioAdviceResult | null;
  error: string | null;
  startedAt: number | null;
  completedAt: number | null;
  requestText: string;
  invalidated: boolean;

  start: (llm: LlmConfig, requestText: string) => Promise<void>;
  invalidate: () => void;
  clear: () => void;
}

let activeRequestId = 0;

function makeStreamLlmConfig(llm: LlmConfig): StreamLlmConfig {
  return {
    provider: llm.provider,
    baseURL: llm.baseURL,
    apiKey: llm.apiKey,
    model: llm.model,
  };
}

function getPortfolioAdviceErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 409) {
      return e.message || "当前没有持仓，无法生成持仓操作建议";
    }
    if (e.status === 503) {
      return e.message || "市场核心数据暂不可用，无法生成可靠的持仓操作建议";
    }
    if (e.status === 502) {
      const detail = e.message || "";
      if (detail === "持仓建议模型调用失败" || detail === "持仓建议模型输出无效") {
        return detail;
      }
      return "持仓建议生成失败，请重试";
    }
    if (e.status === 500) {
      return "持仓操作建议生成失败";
    }
    if (e.status === 400 && e.message.includes("接入")) {
      return "请先在“接入 AI”中配置模型";
    }
    return e.message || "持仓建议生成失败，请重试";
  }
  return "持仓建议生成失败，请重试";
}

export const usePortfolioAdviceTaskStore = create<PortfolioAdviceTaskState>((set, get) => ({
  status: "idle",
  result: null,
  error: null,
  startedAt: null,
  completedAt: null,
  requestText: "",
  invalidated: false,

  start: async (llm: LlmConfig, requestText: string) => {
    const state = get();
    if (state.status === "running") return;

    const normalizedRequest = requestText.trim();
    const requestId = activeRequestId + 1;
    activeRequestId = requestId;

    set({
      status: "running",
      result: null,
      error: null,
      startedAt: Date.now(),
      completedAt: null,
      requestText: normalizedRequest,
      invalidated: false,
    });

    try {
      const result = await api.portfolioAdvice({
        user_request: normalizedRequest || null,
        llm: makeStreamLlmConfig(llm),
      });

      const finishedState = get();
      if (requestId !== activeRequestId || finishedState.invalidated) {
        set({
          status: "idle",
          result: null,
          error: null,
          completedAt: Date.now(),
          invalidated: false,
        });
        return;
      }

      set({
        status: "success",
        result,
        error: null,
        completedAt: Date.now(),
        invalidated: false,
      });
    } catch (e: unknown) {
      const finishedState = get();
      if (requestId !== activeRequestId || finishedState.invalidated) {
        set({
          status: "idle",
          result: null,
          error: null,
          completedAt: Date.now(),
          invalidated: false,
        });
        return;
      }

      set({
        status: "error",
        result: null,
        error: getPortfolioAdviceErrorMessage(e),
        completedAt: Date.now(),
        invalidated: false,
      });
    }
  },

  invalidate: () => {
    const state = get();
    if (state.status === "running") {
      set({
        result: null,
        error: null,
        invalidated: true,
      });
      return;
    }

    set({
      status: "idle",
      result: null,
      error: null,
      startedAt: null,
      completedAt: null,
      invalidated: false,
    });
  },

  clear: () => {
    activeRequestId += 1;
    set({
      status: "idle",
      result: null,
      error: null,
      startedAt: null,
      completedAt: null,
      requestText: "",
      invalidated: false,
    });
  },
}));
