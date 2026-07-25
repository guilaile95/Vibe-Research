import { create } from "zustand";
import {
  api,
  ApiError,
  type AiGeneratedResult,
  type PortfolioAdviceResult,
  type StreamLlmConfig,
} from "@/lib/api";
import { getPortfolioAdviceErrorMessage } from "@/lib/portfolioAdviceErrors";
import {
  getEstimatedPortfolioAdviceDuration,
  getPortfolioAdviceProviderKey,
  isAbortError,
  recordSuccessfulPortfolioAdviceDuration,
} from "@/lib/portfolioAdviceDuration";
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
  estimatedDurationMs: number;
  providerKey: string | null;
  requestText: string;
  restore: (tradeDate?: string | null) => Promise<void>;
  start: (llm: LlmConfig, requestText: string) => Promise<void>;
  cancel: () => void;
  invalidate: () => void;
  clear: () => void;
}

const requestCoordinator = new PortfolioAdviceRequestCoordinator();
let activeController: AbortController | null = null;

function makeStreamLlmConfig(llm: LlmConfig): StreamLlmConfig {
  return {
    provider: llm.provider,
    baseURL: llm.baseURL,
    apiKey: llm.apiKey,
    model: llm.model,
  };
}

function statusAfterCancel(hasResult: boolean): PortfolioAdviceTaskStatus {
  return hasResult ? "restored" : "idle";
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
  estimatedDurationMs: 0,
  providerKey: null,
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
      if (isAbortError(error)) return;
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

    // Abort any leftover in-flight request (defensive; beginGeneration already blocks re-entry).
    activeController?.abort();
    const controller = new AbortController();
    activeController = controller;

    const normalizedRequest = requestText.trim();
    const durationMs = getEstimatedPortfolioAdviceDuration(llm);
    set({
      status: "running",
      error: null,
      restoreError: null,
      startedAt: Date.now(),
      completedAt: null,
      estimatedDurationMs: durationMs,
      providerKey: getPortfolioAdviceProviderKey(llm),
      requestText: normalizedRequest,
    });
    try {
      const generated = await api.portfolioAdvice(
        {
          user_request: normalizedRequest || null,
          llm: makeStreamLlmConfig(llm),
        },
        controller.signal,
      );
      if (!requestCoordinator.canApplyGeneration(requestToken)) return;
      if (!generated.trade_date) {
        throw new Error("持仓建议权威结果读取失败");
      }
      const saved = requirePersistedPortfolioAdvice(
        await api.aiResult<PortfolioAdviceResult>(
          "portfolio_advice",
          generated.trade_date,
          controller.signal,
        ),
      );
      if (!requestCoordinator.canApplyGeneration(requestToken)) return;
      const startedAt = get().startedAt;
      if (startedAt !== null) {
        recordSuccessfulPortfolioAdviceDuration(llm, Date.now() - startedAt);
      }
      set({
        status: "success",
        result: saved.payload,
        resultMeta: saved,
        error: null,
        completedAt: Date.now(),
      });
    } catch (error) {
      if (!requestCoordinator.canApplyGeneration(requestToken)) return;
      // Cancel / abort: keep previous result, never surface as failure.
      if (isAbortError(error)) {
        const { result } = get();
        set({
          status: statusAfterCancel(result !== null),
          error: null,
          completedAt: Date.now(),
        });
        return;
      }
      set({
        status: "error",
        error: getPortfolioAdviceErrorMessage(error),
        completedAt: Date.now(),
      });
    } finally {
      if (activeController === controller) activeController = null;
    }
  },

  cancel: () => {
    const current = get();
    if (current.status !== "running") return;
    requestCoordinator.invalidate();
    activeController?.abort();
    activeController = null;
    set({
      status: statusAfterCancel(current.result !== null),
      error: null,
      completedAt: Date.now(),
    });
  },

  invalidate: () => {
    requestCoordinator.invalidate();
    activeController?.abort();
    activeController = null;
    set({ status: "idle", error: null, restoreError: null });
  },

  clear: () => {
    requestCoordinator.invalidate();
    activeController?.abort();
    activeController = null;
    set({
      status: "idle",
      result: null,
      resultMeta: null,
      error: null,
      restoreError: null,
      startedAt: null,
      completedAt: null,
      estimatedDurationMs: 0,
      providerKey: null,
      requestText: "",
    });
  },
}));
