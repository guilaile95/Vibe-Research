import { create } from "zustand";
import {
  api,
  dailyReviewAnalyzeStream,
  ApiError,
  type AiGeneratedResult,
  type DailyReviewAiPayload,
  type StreamLlmConfig,
} from "@/lib/api";
import type { LlmConfig } from "@/lib/llm";
import { getDailyReviewAiRestoreTradeDate } from "@/stores/dailyReviewAiResultMetadata";

export type DailyReviewAiTaskStatus =
  | "idle"
  | "restoring"
  | "empty"
  | "restored"
  | "running"
  | "success"
  | "error"
  | "restore_error";

export interface DailyReviewAiTaskState {
  status: DailyReviewAiTaskStatus;
  content: string;
  streamContent: string;
  resultMeta: AiGeneratedResult<DailyReviewAiPayload> | null;
  error: string | null;
  restoreError: string | null;
  startedAt: number | null;
  completedAt: number | null;
  estimatedDurationMs: number;
  providerKey: string | null;
  restore: (tradeDate: string) => Promise<void>;
  start: (llm: LlmConfig, tradeDate: string) => Promise<void>;
  clear: () => void;
}

const DURATION_STORAGE_KEY = "vr-daily-review-duration-v1";
const MAX_SAMPLES = 5;
const MIN_ESTIMATE_MS = 30_000;
const MAX_ESTIMATE_MS = 300_000;
const DEFAULT_API_MS = 90_000;
const DEFAULT_CLI_MS = 180_000;

let activeRequestId = 0;
let activeController: AbortController | null = null;

function getProviderKey(llm: LlmConfig): string {
  return `${llm.provider}:${llm.model}`;
}

function median(nums: number[]): number {
  const sorted = [...nums].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), high);
}

function loadDurationSamples(): Record<string, number[]> {
  try {
    const raw = localStorage.getItem(DURATION_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveDurationSamples(samples: Record<string, number[]>): void {
  try {
    localStorage.setItem(DURATION_STORAGE_KEY, JSON.stringify(samples));
  } catch {
    // Optional timing history must never affect generation.
  }
}

export function getEstimatedDuration(llm: LlmConfig): number {
  const history = loadDurationSamples()[getProviderKey(llm)];
  if (history?.length) {
    return clamp(Math.round(median(history)), MIN_ESTIMATE_MS, MAX_ESTIMATE_MS);
  }
  return llm.provider.startsWith("cli-") ? DEFAULT_CLI_MS : DEFAULT_API_MS;
}

export function recordSuccessfulDuration(llm: LlmConfig, elapsedMs: number): void {
  const key = getProviderKey(llm);
  const samples = loadDurationSamples();
  samples[key] = [...(samples[key] || []), elapsedMs].slice(-MAX_SAMPLES);
  saveDurationSamples(samples);
}

export function makeStreamLlmConfig(llm: LlmConfig): StreamLlmConfig {
  return {
    provider: llm.provider,
    baseURL: llm.baseURL,
    apiKey: llm.apiKey,
    model: llm.model,
  };
}

function isAbort(error: unknown): boolean {
  return typeof error === "object" && error !== null && "name" in error && error.name === "AbortError";
}

export const useDailyReviewAiTaskStore = create<DailyReviewAiTaskState>((set, get) => ({
  status: "idle",
  content: "",
  streamContent: "",
  resultMeta: null,
  error: null,
  restoreError: null,
  startedAt: null,
  completedAt: null,
  estimatedDurationMs: 0,
  providerKey: null,

  restore: async (tradeDate: string) => {
    if (!tradeDate) return;
    const requestId = ++activeRequestId;
    activeController?.abort();
    const controller = new AbortController();
    activeController = controller;
    const current = get();
    const sameDate = current.resultMeta?.trade_date === tradeDate;
    set({
      status: "restoring",
      content: sameDate ? current.content : "",
      streamContent: "",
      resultMeta: sameDate ? current.resultMeta : null,
      error: null,
      restoreError: null,
    });
    try {
      const restored = await api.aiResult<DailyReviewAiPayload>("daily_review_ai", tradeDate);
      if (requestId !== activeRequestId) return;
      if (!restored) {
        set({ status: "empty", content: "", resultMeta: null, restoreError: null });
        return;
      }
      set({
        status: "restored",
        content: restored.payload.markdown,
        resultMeta: restored,
        restoreError: null,
        completedAt: Date.now(),
      });
    } catch (error) {
      if (requestId !== activeRequestId || isAbort(error)) return;
      set({
        status: "restore_error",
        restoreError: error instanceof ApiError ? error.message : "每日复盘 AI 结果恢复失败",
      });
    } finally {
      if (requestId === activeRequestId) activeController = null;
    }
  },

  start: async (llm: LlmConfig, _tradeDate: string) => {
    if (get().status === "running") return;
    const requestId = ++activeRequestId;
    activeController?.abort();
    const controller = new AbortController();
    activeController = controller;
    const durationMs = getEstimatedDuration(llm);
    set({
      status: "running",
      streamContent: "",
      error: null,
      restoreError: null,
      startedAt: Date.now(),
      completedAt: null,
      estimatedDurationMs: durationMs,
      providerKey: getProviderKey(llm),
    });
    try {
      const streamed = await dailyReviewAnalyzeStream(
        { user_request: null, llm: makeStreamLlmConfig(llm) },
        {
          onDelta: (text) => {
            if (requestId !== activeRequestId) return;
            set((state) => ({ streamContent: state.streamContent + text }));
          },
        },
        controller.signal,
      );
      const restoreTradeDate = getDailyReviewAiRestoreTradeDate(streamed.result);
      if (!restoreTradeDate) throw new ApiError("生成完成但缺少已保存结果元数据", 502);
      const saved = await api.aiResult<DailyReviewAiPayload>("daily_review_ai", restoreTradeDate);
      if (!saved) throw new ApiError("生成完成但未能恢复已保存结果", 502);
      if (requestId !== activeRequestId) return;
      const startedAt = get().startedAt;
      if (startedAt !== null) recordSuccessfulDuration(llm, Date.now() - startedAt);
      set({
        status: "success",
        content: saved.payload.markdown || streamed.content,
        streamContent: "",
        resultMeta: saved,
        error: null,
        completedAt: Date.now(),
      });
    } catch (error) {
      if (requestId !== activeRequestId || isAbort(error)) return;
      set({
        status: "error",
        streamContent: "",
        error: error instanceof ApiError ? error.message : "复盘失败",
        completedAt: Date.now(),
      });
    } finally {
      if (requestId === activeRequestId) activeController = null;
    }
  },

  clear: () => {
    ++activeRequestId;
    activeController?.abort();
    activeController = null;
    set({
      status: "idle",
      content: "",
      streamContent: "",
      resultMeta: null,
      error: null,
      restoreError: null,
      startedAt: null,
      completedAt: null,
      estimatedDurationMs: 0,
      providerKey: null,
    });
  },
}));
