import { ApiError, get } from "./api.ts";

export interface BackendRuntimeInfo {
  service: "vibe-research-api";
  version: string;
  git_sha: string | null;
  source_state: "clean" | "modified" | "unknown";
  source_directory: string | null;
  working_directory: string | null;
}

export interface BackendRuntimeCheck {
  connected: boolean;
  version: string | null;
  runtime: BackendRuntimeInfo | null;
  infoStatus: "available" | "unsupported" | "auth_required" | "unavailable";
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function parseRuntime(value: unknown): BackendRuntimeInfo | null {
  const data = record(value);
  if (data?.service !== "vibe-research-api" || !text(data.version)) return null;
  const sha = typeof data.git_sha === "string" && /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(data.git_sha)
    ? data.git_sha : null;
  const sourceState = data.source_state === "clean" || data.source_state === "modified"
    ? data.source_state : "unknown";
  return {
    service: "vibe-research-api",
    version: data.version as string,
    git_sha: sourceState === "unknown" ? null : sha,
    source_state: sha ? sourceState : "unknown",
    source_directory: text(data.source_directory),
    working_directory: text(data.working_directory),
  };
}

export async function readBackendRuntime(): Promise<BackendRuntimeCheck> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    // 复用相对 /api 路径、现有代理与访问密钥；不直连 8900/8911。
    const [healthResult, runtimeResult] = await Promise.allSettled([
      get<unknown>("/health", { signal: controller.signal }),
      get<unknown>("/runtime-info", { signal: controller.signal }),
    ]);
    const health = healthResult.status === "fulfilled" ? record(healthResult.value) : null;
    const healthy = health?.ok === true && health?.service === "vibe-research-api";
    const runtime = runtimeResult.status === "fulfilled" ? parseRuntime(runtimeResult.value) : null;
    const errorStatus = runtimeResult.status === "rejected" && runtimeResult.reason instanceof ApiError
      ? runtimeResult.reason.status : null;
    return {
      connected: healthy || runtime !== null,
      version: runtime?.version ?? (healthy ? text(health?.version) : null),
      runtime,
      infoStatus: runtime ? "available"
        : errorStatus === 401 || errorStatus === 403 ? "auth_required"
        : errorStatus === 404 ? "unsupported" : "unavailable",
    };
  } finally {
    clearTimeout(timer);
  }
}
