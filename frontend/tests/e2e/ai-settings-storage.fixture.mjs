// Synthetic-only contracts shared by offline checks and browser harness.
export const config = { provider: "openai-compatible", baseURL: "https://synthetic.invalid/v1", apiKey: "SYNTHETIC_MODEL_KEY", model: "SYNTHETIC_MODEL" };
export const chatKey = `vr-askai-chat:/my-reports#reports:synthetic-report@${config.provider}:${config.model}:${config.baseURL}`;
export const readPaths = ["/api/myreports", "/api/health", "/api/runtime-info", "/api/ai/credential-status", "/api/native-intel/filter/profile", "/api/native-intel/sources", "/api/native-intel/config"];
export function readReply(method, path, search = "") {
  if (method !== "GET") return null;
  if (path === "/api/myreports" && !search) return [{ id: "synthetic-report", name: "Synthetic report.pdf", title: "Synthetic report", size: 100, ts: 1791417600000, sector_keys: [], institution: "Synthetic", publish_date: "2026-10-08", text_index_status: "SEARCHABLE" }];
  if (path === "/api/health" && !search) return { ok: true, service: "vibe-research-api", version: "synthetic" };
  if (path === "/api/runtime-info" && !search) return { service: "vibe-research-api", version: "synthetic", git_sha: null, source_state: "unknown", source_directory: null, working_directory: null };
  if (path === "/api/ai/credential-status" && !search) return { configured: false, provider: null, scheduled_available: false };
  if (path === "/api/native-intel/filter/profile" && search === "?profile_id=default") return { profile_id: "default", method: "keyword", interests_text: "", min_score: 0.7, keyword_rules: { global_excludes: [], filter_terms: [], groups: [] }, tags: [] };
  if (path === "/api/native-intel/sources" && !search) return { sources: [] };
  if (path === "/api/native-intel/config" && !search) return { region_order: ["hotlist", "rss", "standalone"], regions_enabled: { hotlist: false, rss: false, standalone: false } };
  return null;
}
export function validSyntheticStream(method, path, body) {
  if (method !== "POST" || !["/api/chat", "/api/ai/connection-test"].includes(path)) return false;
  if (body?.llm?.baseURL !== config.baseURL || typeof body.llm.apiKey !== "string" || !body.llm.apiKey.startsWith("SYNTHETIC_") || typeof body.llm.model !== "string" || !body.llm.model.startsWith("SYNTHETIC_")) return false;
  return path === "/api/chat" ? body.report_ids?.length === 1 && body.report_ids[0] === "synthetic-report" && Array.isArray(body.messages)
    : Object.keys(body).length === 1;
}
export function observeSyntheticStreams() {
  window.__storageEvents = [];
  window.addEventListener("storage", event => window.__storageEvents.push({ key: event.key, local: event.storageArea === localStorage, trusted: event.isTrusted }));
  const nativeFetch = window.fetch.bind(window);
  window.__streams = [];
  window.fetch = async (input, init) => {
    const path = new URL(typeof input === "string" ? input : input.url, location.href).pathname;
    if (!["/api/chat", "/api/ai/connection-test"].includes(path)) return nativeFetch(input, init);
    const row = { path, aborted: Boolean(init?.signal?.aborted), chunks: 0, eof: false };
    window.__streams.push(row);
    init?.signal?.addEventListener("abort", () => { row.aborted = true; }, { once: true });
    // Deliberately keep only these synthetic HTTP streams alive after abort so
    // late bytes really reach production parsing and must be rejected by ownership.
    const response = await nativeFetch(input, { ...init, signal: undefined });
    const getReader = response.body.getReader.bind(response.body);
    response.body.getReader = (...args) => {
      const reader = getReader(...args), read = reader.read.bind(reader);
      reader.read = async (...readArgs) => {
        const result = await read(...readArgs);
        if (result.done) row.eof = true; else row.chunks++;
        return result;
      };
      return reader;
    };
    return response;
  };
}
