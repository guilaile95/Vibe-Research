import { create } from "zustand";
import { dailyReviewAnalyzeStream, ApiError, type StreamLlmConfig } from "@/lib/api";
import type { LlmConfig } from "@/lib/llm";

export type DailyReviewAiTaskStatus =
  | "idle"
  | "running"
  | "success"
  | "error";

export interface DailyReviewAiTaskState {
  status: DailyReviewAiTaskStatus;
  content: string;
  error: string | null;
  startedAt: number | null;
  completedAt: number | null;
  estimatedDurationMs: number;
  providerKey: string | null;

  start: (llm: LlmConfig) => Promise<void>;
  clear: () => void;
}

const DURATION_STORAGE_KEY = "vr-daily-review-duration-v1";
const MAX_SAMPLES = 5;
const MIN_ESTIMATE_MS = 30_000;
const MAX_ESTIMATE_MS = 300_000;
const DEFAULT_API_MS = 90_000;
const DEFAULT_CLI_MS = 180_000;

function getProviderKey(llm: LlmConfig): string {
  return `${llm.provider}:${llm.model}`;
}

function isCliProviderId(provider: string): boolean {
  return provider.startsWith("cli-");
}

function median(nums: number[]): number {
  const sorted = [...nums].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(Math.max(v, lo), hi);
}

function loadDurationSamples(): Record<string, number[]> {
  try {
    const raw = localStorage.getItem(DURATION_STORAGE_KEY);
    if (!raw) return {};
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function saveDurationSamples(samples: Record<string, number[]>): void {
  try {
    localStorage.setItem(DURATION_STORAGE_KEY, JSON.stringify(samples));
  } catch {
    // localStorage full or unavailable — silently ignore
  }
}

export function getEstimatedDuration(llm: LlmConfig): number {
  const key = getProviderKey(llm);
  const samples = loadDurationSamples();
  const history = samples[key];
  if (history && history.length > 0) {
    return clamp(Math.round(median(history)), MIN_ESTIMATE_MS, MAX_ESTIMATE_MS);
  }
  const base = isCliProviderId(llm.provider) ? DEFAULT_CLI_MS : DEFAULT_API_MS;
  return clamp(base, MIN_ESTIMATE_MS, MAX_ESTIMATE_MS);
}

export function recordSuccessfulDuration(llm: LlmConfig, elapsedMs: number): void {
  const key = getProviderKey(llm);
  const samples = loadDurationSamples();
  const list = samples[key] || [];
  list.push(elapsedMs);
  samples[key] = list.slice(-MAX_SAMPLES);
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

export const useDailyReviewAiTaskStore = create<DailyReviewAiTaskState>((set, get) => ({
  status: "idle",
  content: "",
  error: null,
  startedAt: null,
  completedAt: null,
  estimatedDurationMs: 0,
  providerKey: null,

  start: async (llm: LlmConfig) => {
    const state = get();
    if (state.status === "running") return;

    const durationMs = getEstimatedDuration(llm);
    const providerKey = getProviderKey(llm);

    set({
      status: "running",
      content: "",
      error: null,
      startedAt: Date.now(),
      completedAt: null,
      estimatedDurationMs: durationMs,
      providerKey,
    });

    const streamConfig = makeStreamLlmConfig(llm);

    try {
      await dailyReviewAnalyzeStream(
        { user_request: null, llm: streamConfig },
        {
          onDelta: (text: string) => {
            set((s) => ({ content: s.content + text }));
          },
        },
      );

      const finishedState = get();
      if (finishedState.status === "running") {
        const elapsed = Date.now() - finishedState.startedAt!;
        recordSuccessfulDuration(llm, elapsed);
        set({ status: "success", completedAt: Date.now() });
      }
    } catch (e: unknown) {
      const msg = e instanceof ApiError ? e.message : "复盘失败";
      set(() => ({
        status: "error",
        error: msg,
        // Keep partial content
        completedAt: Date.now(),
      }));
    }
  },

  clear: () => {
    set({
      status: "idle",
      content: "",
      error: null,
      startedAt: null,
      completedAt: null,
      estimatedDurationMs: 0,
      providerKey: null,
    });
  },
}));
