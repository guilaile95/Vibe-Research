// Synthetic readback only. Actual archive/HTTP identity tests live in Python.
export const dayA = "2026-07-30";
export const dayB = "2026-07-29";

export function sealReply(date, mode = "normal") {
  const base = {
    schema_version: "short-term-seal-quality-archive-v0.1", trade_date: date,
    status: "normal", reason_codes: [], message: "已读取所选本地发布绑定的归档观测；不是实时行情、收盘定稿或可成交性证明。",
    archive_only: true, ingestion_enabled: false,
    selection: { selection_mode: "local_latest", selection_basis: "local_vintage_sequence", point_in_time_claim: "NONE", provider_revision_claim: "NONE" },
    archive_identity: { publication_id: `synthetic-publication-${date}`, source_observation_id: `synthetic-observation-${date}`, raw_payload_hash: `sha256:${"a".repeat(64)}`, captured_at: `${date}T07:05:00Z` },
    projection: {
      status: "normal", source_trade_date: date, sample_count: 2, excluded_universe_count: 1,
      finality: "NOT_ESTABLISHED", canonical_authority: false,
      metrics: { never_broken_count: 1, never_broken_ratio: 0.5, reopened_count: 1, ever_opened_ratio: 0.5,
        average_broken_times: 1, first_seal_by_0935_count: 1, late_seal_count: 1 },
      coverage: Object.fromEntries(["first_seal", "last_seal", "broken_times"].map(key => [key, { known_count: 2, unknown_count: 0, complete: true }])),
      rows: [
        { stock_code: "000001", lbc: 1, zt_stat: null, first_seal: "093000", last_seal: "093000", broken_times: 0, field_issues: {} },
        { stock_code: "600001", lbc: 2, zt_stat: "3/2", first_seal: "100000", last_seal: "143000", broken_times: 2, field_issues: {} },
      ], limitations: ["Synthetic observation only"],
    },
  };
  if (mode === "unconnected") return { ...base, status: "unavailable", reason_codes: ["ARCHIVE_NOT_CONNECTED"],
    message: "封板质量归档证据未连接；不会自动启用采集或请求行情。", selection: null, archive_identity: null, projection: null };
  if (mode === "partial") {
    base.status = base.projection.status = "partial";
    base.reason_codes = ["QUALITY_FIELDS_INCOMPLETE"];
    for (const field of ["never_broken_count", "never_broken_ratio", "reopened_count", "ever_opened_ratio", "average_broken_times"]) base.projection.metrics[field] = null;
    base.projection.coverage.broken_times = { known_count: 1, unknown_count: 1, complete: false };
    base.projection.rows[1].broken_times = null;
    base.projection.rows[1].field_issues = { broken_times: ["MISSING_SOURCE_FIELD"] };
  }
  return base;
}

export function validSealQuery(method, pathname, search) {
  const query = new URLSearchParams(search);
  return method === "GET" && pathname === "/api/market/seal-quality"
    && [...query.keys()].length === 1 && [dayA, dayB].includes(query.get("trade_date"));
}

// Deliver a superseded response despite AbortSignal to prove the component's
// own request ownership guard, while recording that it really requested abort.
export function observeSealReads() {
  const original = window.fetch.bind(window);
  window.__sealReads = [];
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (url.pathname !== "/api/market/seal-quality") return original(input, init);
    const record = { date: url.searchParams.get("trade_date"), aborted: false, parsed: false };
    window.__sealReads.push(record);
    init?.signal?.addEventListener("abort", () => { record.aborted = true; });
    const response = await original(input, { ...init, signal: undefined });
    const read = response.json.bind(response);
    response.json = async () => { const value = await read(); record.parsed = true; return value; };
    return response;
  };
}
