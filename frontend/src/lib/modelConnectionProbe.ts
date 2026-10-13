import type { LlmConfig } from "./llm.ts";

export type ProbeState = { status: "idle" | "pending" | "success" | "cancelled" | "error"; message: string };
const IDLE: ProbeState = { status: "idle", message: "" };

/** Ephemeral generation ownership: no credentials, fingerprints or results are persisted. */
export function createModelConnectionProbe(
  run: (config: LlmConfig, signal: AbortSignal) => Promise<unknown>,
  publish: (state: ProbeState) => void,
  timeoutMs = 15_000,
) {
  let generation = 0;
  let active: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  function stop(state: ProbeState | null) {
    generation += 1;
    active?.abort();
    active = null;
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
    if (state) publish(state);
  }
  return {
    invalidate: () => stop(IDLE),
    dispose: () => stop(null),
    cancel: () => stop({ status: "cancelled", message: "已停止等待；服务商仍可能计费。" }),
    async start(config: LlmConfig) {
      if (active) return;
      if (config.provider.startsWith("cli-")) {
        publish({ status: "error", message: "订阅或旧版 CLI 暂不支持此限额连接测试。" });
        return;
      }
      const ac = new AbortController();
      active = ac;
      const mine = ++generation;
      publish({ status: "pending", message: "正在测试当前表单配置…" });
      timer = setTimeout(() => {
        if (generation === mine) stop({ status: "error", message: "已超过 15 秒，停止等待；服务商仍可能计费。" });
      }, timeoutMs);
      try {
        await run({ ...config }, ac.signal);
        if (generation === mine && !ac.signal.aborted) publish({
          status: "success",
          message: "本次收到完整响应；仅验证当前表单配置的调用，不验证模型质量、工具能力或研究结论，也不代表配置已保存。",
        });
      } catch (error) {
        if (generation === mine && !ac.signal.aborted) {
          const backendAuth = typeof error === "object" && error !== null && "status" in error && error.status === 401;
          publish({ status: "error", message: backendAuth
            ? "后端访问鉴权失败，请检查并保存下方的后端访问密钥。"
            : "模型连接测试未完成，请检查当前配置或稍后重试。" });
        }
      } finally {
        if (generation === mine) {
          if (timer !== undefined) clearTimeout(timer);
          timer = undefined;
          active = null;
        }
      }
    },
  };
}

export function canonicalModelProbeURL(baseURL: string): string | null {
  // Browser and Python URL parsers disagree on backslashes and hidden controls.
  // Send the same canonical URL whose origin is disclosed to the user.
  if (/[\\\x00-\x20\x7f]/.test(baseURL) || baseURL.includes("?") || baseURL.includes("#")) return null;
  try {
    const url = new URL(baseURL);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password && !url.search && !url.hash
      ? url.href.replace(/\/$/, "") : null;
  } catch { return null; }
}

export function modelProbeDestination(baseURL: string): string | null {
  const canonical = canonicalModelProbeURL(baseURL);
  return canonical ? new URL(canonical).origin : null;
}
