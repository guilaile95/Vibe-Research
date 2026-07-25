import { create } from "zustand";
import {
  api,
  ApiError,
  type AiGeneratedResult,
  type PortfolioAdviceResult,
  type StreamLlmConfig,
} from "@/lib/api";
import { getPortfolioAdviceErrorMessage } from "@/lib/portfolioAdviceErrors";
import type { LlmConfig } from "@/lib/llm";
import {
  PortfolioAdviceRequestCoordinator,
  requirePersistedPortfolioAdvice,
} from "./portfolioAdviceRequestCoordinator";

export type PortfolioAdviceTaskStatus =
  | "idle"
  | "restoring"
  | "empty"
  | "restored"
  | "running"
  | "success"
  | "error"
  | "restore_error";

export interface PortfolioAdviceTaskState {
  status: PortfolioAdviceTaskStatus;
  result: PortfolioAdviceResult | null;
  resultMeta: AiGeneratedResult<PortfolioAdviceResult> | null;
  error: string | null;
  restoreError: string | null;
  startedAt: number | null;
  completedAt: number | null;
  requestText: string;
  restore: (tradeDate?: string | null) => Promise<void>;
  start: (llm: LlmConfig, requestText: string) => Promise<void>;
  invalidate: () => void;
  clear: () => void;
}

const requestCoordinator = new PortfolioAdviceRequestCoordinator();

function makeStreamLlmConfig(llm: LlmConfig): StreamLlmConfig {
  return {
    provider: llm.provider,
    baseURL: llm.baseURL,
    apiKey: llm.apiKey,
    model: llm.model,
  };
}

export { getPortfolioAdviceErrorMessage };

export const usePortfolioAdviceTaskStore = create<PortfolioAdviceTaskState>((set, get) => ({
  status: "idle",
  result: null,
  resultMeta: null,
  error: null,
  restoreError: null,
  startedAt: null,
  completedAt: null,
  requestText: "",

  restore: async (tradeDate?: string | null) => {
    const current = get();
    const requestToken = requestCoordinator.beginRestore(current.status === "running");
    if (requestToken === null) return;
    set({ status: "restoring", error: null, restoreError: null });
    try {
      const restored = await api.aiResult<PortfolioAdviceResult>(
        "portfolio_advice",
        tradeDate || null,
      );
      if (!requestCoordinator.canApplyRestore(requestToken, get().status === "running")) return;
      if (!restored) {
        set({ status: "empty", result: null, resultMeta: null, completedAt: Date.now() });
        return;
      }
      set({
        status: "restored",
        result: restored.payload,
        resultMeta: restored,
        restoreError: null,
        completedAt: Date.now(),
      });
    } catch (error) {
      if (!requestCoordinator.canApplyRestore(requestToken, get().status === "running")) return;
      set({
        status: "restore_error",
        result: current.result,
        resultMeta: current.resultMeta,
        restoreError: error instanceof ApiError ? error.message : "持仓建议恢复失败",
        completedAt: Date.now(),
      });
    }
  },

  start: async (llm: LlmConfig, requestText: string) => {
    const requestToken = requestCoordinator.beginGeneration(get().status === "running");
    if (requestToken === null) return;
    const normalizedRequest = requestText.trim();
    set({
      status: "running",
      error: null,
      restoreError: null,
      startedAt: Date.now(),
      completedAt: null,
      requestText: normalizedRequest,
    });
    try {
      const generated = await api.portfolioAdvice({
        user_request: normalizedRequest || null,
        llm: makeStreamLlmConfig(llm),
      });
      if (!requestCoordinator.canApplyGeneration(requestToken)) return;
      if (!generated.trade_date) {
        throw new Error("持仓建议权威结果读取失败");
      }
      const saved = requirePersistedPortfolioAdvice(
        await api.aiResult<PortfolioAdviceResult>(
          "portfolio_advice",
          generated.trade_date,
        ),
      );
      if (!requestCoordinator.canApplyGeneration(requestToken)) return;
      set({
        status: "success",
        result: saved.payload,
        resultMeta: saved,
        error: null,
        completedAt: Date.now(),
      });
    } catch (error) {
      if (!requestCoordinator.canApplyGeneration(requestToken)) return;
      set({
        status: "error",
        error: getPortfolioAdviceErrorMessage(error),
        completedAt: Date.now(),
      });
    }
  },

  invalidate: () => {
    requestCoordinator.invalidate();
    set({ status: "idle", error: null, restoreError: null });
  },

  clear: () => {
    requestCoordinator.invalidate();
    set({
      status: "idle",
      result: null,
      resultMeta: null,
      error: null,
      restoreError: null,
      startedAt: null,
      completedAt: null,
      requestText: "",
    });
  },
}));
