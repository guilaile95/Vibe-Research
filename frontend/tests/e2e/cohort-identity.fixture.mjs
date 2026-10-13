// Synthetic two-date member readback only. Service/archive identity is verified
// independently in Python; these fixtures claim neither live market evidence nor rates.
export const COHORT_PATH = "/api/market/cohort-identity";
export const COHORT_DAY_A = "2026-07-30";
export const COHORT_DAY_B = "2026-07-29";
export const COHORT_CLOCK = "2026-07-30T08:00:00Z";
const priorDays = { [COHORT_DAY_A]: COHORT_DAY_B, [COHORT_DAY_B]: "2026-07-28" };

export function cohortUnavailable(date, previousDate = null) {
  return {
    schema_version: "archived-cohort-identity.v0.1", trade_date: date,
    previous_trade_date: previousDate, status: "unavailable", reason_codes: ["ARCHIVE_MISSING"],
    message: "缺少完整的两日名单归档，无法进行对照",
    selection_mode: "CURRENT_STORED_POSTHOC", point_in_time_claim: "NONE", research_only: true,
    projection: null, evidence: null,
  };
}

export function cohortReply(date, mode = "normal") {
  const previousDate = priorDays[date];
  if (!previousDate) throw new Error("Synthetic cohort date is not whitelisted");
  if (mode === "unavailable") return cohortUnavailable(date, previousDate);
  const side = (day, hash, rowCount) => ({
    trade_date: day, source_ids: [`synthetic-source-${day}`], fetched_at: `${day}T07:00:00Z`,
    snapshot_at: `${day}T07:01:00Z`, stored_at: `${day}T07:02:00Z`,
    envelope_sha256: hash.repeat(64), row_count: rowCount,
  });
  return {
    ...cohortUnavailable(date, previousDate), status: "normal", reason_codes: [],
    message: "已读取两个相邻交易日当前存储的归档名单，仅供逐只对照",
    projection: { rows: [
      { stock_code: "000001", previous_source_code: "000001", current_source_code: null,
        previous_boards: 2, current_boards: null, present_today: false },
      { stock_code: "600001", previous_source_code: "600001", current_source_code: "600001",
        previous_boards: 1, current_boards: 2, present_today: true },
    ] },
    evidence: { previous: side(previousDate, "a", 2), current: side(date, "b", 1) },
  };
}

export function validCohortQuery(method, pathname, search) {
  return method === "GET" && pathname === COHORT_PATH
    && [COHORT_DAY_A, COHORT_DAY_B].some(day => search === `?trade_date=${day}`);
}

export function validCohortStaticRequest(method, pathname, search) {
  return method === "GET" && search === ""
    && (["/", "/index.html", "/favicon.ico"].includes(pathname)
      || /^\/assets\/[A-Za-z0-9_.-]+\.(?:js|css)$/.test(pathname));
}

// Deliberately deliver a superseded response despite AbortSignal. The fixture
// records the real abort and actual JSON parse, so race coverage cannot pass by
// merely cancelling transport before the production ownership guard sees it.
export function observeCohortReads() {
  const original = window.fetch.bind(window);
  window.__cohortReads = [];
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (url.pathname !== "/api/market/cohort-identity") return original(input, init);
    const record = { date: url.searchParams.get("trade_date"), aborted: false, parsed: false };
    window.__cohortReads.push(record);
    init?.signal?.addEventListener("abort", () => { record.aborted = true; });
    const response = await original(input, { ...init, signal: undefined });
    const read = response.json.bind(response);
    response.json = async () => { const value = await read(); record.parsed = true; return value; };
    return response;
  };
}
