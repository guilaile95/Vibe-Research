// 持仓建议耗时估计：按 provider+model 记录成功样本，供等待体验 ETA 使用。

export type PortfolioAdviceDurationLlm = {
  provider: string;
  model: string;
};

export const PORTFOLIO_ADVICE_DURATION_STORAGE_KEY = "vr-portfolio-advice-duration-v1";
export const PORTFOLIO_ADVICE_DURATION_MAX_SAMPLES = 5;
export const PORTFOLIO_ADVICE_MIN_ESTIMATE_MS = 30_000;
export const PORTFOLIO_ADVICE_MAX_ESTIMATE_MS = 300_000;
export const PORTFOLIO_ADVICE_DEFAULT_API_MS = 90_000;
export const PORTFOLIO_ADVICE_DEFAULT_CLI_MS = 180_000;

export function getPortfolioAdviceProviderKey(llm: PortfolioAdviceDurationLlm): string {
  return `${llm.provider}:${llm.model}`;
}

export function median(nums: number[]): number {
  if (nums.length === 0) return 0;
  const sorted = [...nums].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function clamp(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), high);
}

export function loadPortfolioAdviceDurationSamples(
  storage: Pick<Storage, "getItem"> = localStorage,
  key: string = PORTFOLIO_ADVICE_DURATION_STORAGE_KEY,
): Record<string, number[]> {
  try {
    const raw = storage.getItem(key);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out: Record<string, number[]> = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (!Array.isArray(v)) continue;
      const samples = v.filter((n): n is number => typeof n === "number" && Number.isFinite(n) && n > 0);
      if (samples.length) out[k] = samples;
    }
    return out;
  } catch {
    return {};
  }
}

export function savePortfolioAdviceDurationSamples(
  samples: Record<string, number[]>,
  storage: Pick<Storage, "setItem"> = localStorage,
  key: string = PORTFOLIO_ADVICE_DURATION_STORAGE_KEY,
): void {
  try {
    storage.setItem(key, JSON.stringify(samples));
  } catch {
    // Optional timing history must never affect generation.
  }
}

export function getEstimatedPortfolioAdviceDuration(
  llm: PortfolioAdviceDurationLlm,
  storage: Pick<Storage, "getItem"> = localStorage,
): number {
  const history = loadPortfolioAdviceDurationSamples(storage)[getPortfolioAdviceProviderKey(llm)];
  if (history?.length) {
    return clamp(
      Math.round(median(history)),
      PORTFOLIO_ADVICE_MIN_ESTIMATE_MS,
      PORTFOLIO_ADVICE_MAX_ESTIMATE_MS,
    );
  }
  return llm.provider.startsWith("cli-")
    ? PORTFOLIO_ADVICE_DEFAULT_CLI_MS
    : PORTFOLIO_ADVICE_DEFAULT_API_MS;
}

export function recordSuccessfulPortfolioAdviceDuration(
  llm: PortfolioAdviceDurationLlm,
  elapsedMs: number,
  storage: Pick<Storage, "getItem" | "setItem"> = localStorage,
): void {
  if (!Number.isFinite(elapsedMs) || elapsedMs <= 0) return;
  const key = getPortfolioAdviceProviderKey(llm);
  const samples = loadPortfolioAdviceDurationSamples(storage);
  samples[key] = [...(samples[key] || []), elapsedMs].slice(-PORTFOLIO_ADVICE_DURATION_MAX_SAMPLES);
  savePortfolioAdviceDurationSamples(samples, storage);
}

export function isAbortError(error: unknown): boolean {
  return typeof error === "object"
    && error !== null
    && "name" in error
    && (error as { name: string }).name === "AbortError";
}
