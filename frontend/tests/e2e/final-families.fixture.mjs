export const syntheticLlm = { provider: "cli-codex", model: "SYNTHETIC_OFFLINE" };
export const plan = rounds => rounds >= 2 ? ["bull", "bear", "bull_rebut", "bear_rebut", "referee"] : ["bull", "bear", "referee"];
export const encode = events => events.map(event => JSON.stringify(event)).join("\n") + "\n";
export function debateEvents(rounds, mode = "complete") {
  const stages = plan(rounds).map(stage => ({ stage, content: `SYNTHETIC_${stage}` }));
  const events = stages.flatMap(({ stage, content }) => [{ type: "stage", stage, label: stage }, { type: "delta", stage, text: content }, { type: "stage_done", stage, label: stage, content }]);
  if (mode === "bull-eof") return events.slice(0, 3);
  if (mode === "all-eof") return events;
  return [...events, { type: "done", code: "600519", stages }];
}
export function ancillaryReply(method, path, search = "") {
  if (method !== "GET") return null;
  const common = {
    "/api/daily-review": { data: { schema_version: "daily-review-v0.1", trade_date: "2026-10-08", generated_at: "2026-10-08 16:00:00", status: "normal", warnings: [], data_health: { components: {} }, market_environment: { indices: { status: "normal", data: [] }, global_indices: { status: "normal", data: [] }, breadth: { status: "unavailable", data: {} } }, sector_rotation: { industry: { status: "normal", list: [] }, concept: { status: "normal", list: [] }, region: { status: "normal", list: [] }, highlights: {} }, short_term_emotion: { status: "unavailable", data: {} }, capital_activity: { amount_top: [], high_turnover: [], turnover_top: [] } }, cache_meta: { stale: false, refreshing: false } },
    "/api/market/northbound": { status: "unavailable", data: null, limitations: [], warnings: [] },
    "/api/watchlist": { data: { status: "valid", data: { codes: [], updated_at: "synthetic" }, etag: "synthetic" } },
    "/api/native-intel/status": { status: "normal", sources: [], store: { item_count: 0 } },
    "/api/radar": { data: { industries: [], stats: { total_sources: 0 }, generated_at: null } },
    "/api/decision-inbox": { data: { schema_version: "decision_inbox_runtime.v0.1", as_of: "2026-10-08T00:00:00Z", evaluation_status: "EVALUATED", canonical: true, reason_codes: [], holding_setup_items: [], campaign_items: [], total_holdings: 0, total_campaign_items: 0 } },
    "/api/campaigns": { data: [] },
  };
  if (!search && Object.hasOwn(common, path)) return common[path];
  if (path === "/api/market/bk11-history" && search === "?days=5") return { status: "empty", latest: null, items: [], limitations: [] };
  if (path === "/api/native-intel/items" && search === "?limit=40&order_by=last_seen") return { status: "normal", items: [] };
  if (path === "/api/native-intel/trending" && search === "?window_hours=24&top_n=20") return { status: "normal", entities: [] };
  return null;
}
export function realRouteAllowed(method, path, scenario) {
  if (scenario === "report-upload") return path === "/api/myreports" && ["GET", "POST"].includes(method);
  if (scenario.startsWith("history-")) return method === "GET" && path === "/api/daily-review/history";
  if (scenario === "calendar-422") return method === "GET" && path === "/api/research-events";
  return false;
}
export function observeHistoryReads() {
  const nativeFetch = window.fetch.bind(window); window.__historyReads = [];
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (url.pathname !== "/api/daily-review/history") return nativeFetch(input, init);
    const row = { path: url.pathname + url.search, parsed: false, status: null }; window.__historyReads.push(row);
    const response = await nativeFetch(input, init); row.status = response.status;
    const json = response.json.bind(response);
    response.json = async () => { const body = await json(); row.parsed = true; return body; };
    return response;
  };
}
