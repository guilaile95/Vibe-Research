// Module-scoped queue survives Settings unmount/remount. Generations are
// concurrency controls, not authentication or revocation of a provider key.
import { api } from "./api.ts";
import { clearLlm, loadLlm, saveLlm, type LlmConfig } from "./llm.ts";

export class CredentialMutationError extends Error {}

let queue: Promise<unknown> = Promise.resolve();
let intent = 0;
export const credentialIntentVersion = () => intent;
const budget = () => AbortSignal.timeout(10_000);
const revision = (value: unknown): value is string => typeof value === "string" && /^(0|[1-9][0-9]{0,18})$/.test(value) && BigInt(value) <= 9223372036854775807n;
function enqueue<T>(operation: () => Promise<T>): Promise<T> {
  const pending = queue.then(operation, operation);
  queue = pending.catch(() => undefined);
  return pending;
}

export function saveCredential(config: LlmConfig, expectedRevision = loadLlm()?.revision ?? "0"): Promise<boolean> {
  const owner = ++intent;
  // Freeze an already observed generation synchronously with the click. An
  // async GET started here might execute after another tab's clear and must
  // never supply a newer revision to an older save intent.
  return enqueue(async () => {
    if (owner !== intent) return false;
    const written = await api.putAiCredential({ provider: config.provider, model: config.model, baseURL: config.baseURL, apiKey: config.apiKey, expectedRevision }, budget());
    if (owner !== intent) return false;
    const after = await api.getAiCredentialStatus(budget());
    if (owner !== intent) return false;
    if (!written || !after || !written.configured || !after.configured || !revision(written.revision) || !revision(expectedRevision) || BigInt(written.revision) !== BigInt(expectedRevision) + 1n || after.revision !== written.revision) throw new Error("配置已变化，请刷新后重试");
    try { saveLlm({ ...config, revision: written.revision ?? undefined }); }
    catch { throw new CredentialMutationError("后台凭据已保存，但浏览器保存失败；请检查存储权限后重试"); }
    return true;
  });
}

export function clearCredential(): Promise<boolean> {
  const owner = ++intent; // Immediately invalidates every older save completion.
  const observedRevision = loadLlm()?.revision ?? "0";
  try { clearLlm(); } catch { /* Still clear backend authority, then verify local removal. */ }
  return enqueue(async () => {
    const cleared = await api.deleteAiCredential(observedRevision, budget());
    if (owner !== intent) return false;
    const after = await api.getAiCredentialStatus(budget());
    if (owner !== intent) return false;
    if (!cleared || !after || cleared.configured !== false || after.configured !== false || !revision(cleared.revision) || !revision(observedRevision) || BigInt(cleared.revision) <= BigInt(observedRevision) || after.revision !== cleared.revision) throw new Error("配置已变化，请刷新后重试");
    try { clearLlm(); }
    catch { throw new CredentialMutationError("后台凭据已清除，但浏览器凭据仍未清除；请检查存储权限后重试"); }
    return true;
  });
}
