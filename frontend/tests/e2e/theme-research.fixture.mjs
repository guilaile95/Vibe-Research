import { readFileSync } from "node:fs";
export const dayA = "2026-09-30", dayB = "2026-09-29";
const golden = JSON.parse(readFileSync(new URL("../../../backend/tests/fixtures/theme-research-golden.json", import.meta.url), "utf8"));
export function themeReply(day, mode = "normal") {
  let result = structuredClone(golden);
  if (day === dayB) {
    const before = result.projection.sessions, after = ["2026-09-22", "2026-09-23", "2026-09-24", "2026-09-28", "2026-09-29"];
    const replace = v => typeof v === "string" ? (before.includes(v) ? after[before.indexOf(v)] : v) : Array.isArray(v) ? v.map(replace) : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, replace(x)])) : v;
    result = replace(result);
  }
  if (mode === "unconnected") return { ...result, status: "unavailable", reason_codes: ["ARCHIVE_NOT_CONNECTED"], message: "题材归档未连接", projection: null };
  if (mode === "partial") {
    result.status = result.projection.status = "partial";
    result.projection.rotation.forEach(r => {
      r.cells[0].count = r.cells[0].rank = r.cells[0].highest = null;
      r.observed_active_days = r.cells.filter(c => c.count !== null && c.count > 0).length;
      r.top3_days = r.cells.filter(c => c.rank !== null && c.rank <= 3).length;
      let streak = 0;
      for (const c of [...r.cells].reverse()) { if (c.count === null || c.count === 0) break; streak++; }
      r.streak = r.cells.at(-1).count === null ? null : streak;
      r.streak_lower_bound = streak > 0 && r.cells[r.cells.length - streak - 1]?.count === null;
    });
    Object.assign(result.projection.days[0], { available: false, complete: false, limit_up: null, covered: null, highest_board: null, broken_rate: null, concentration: null, concentration_numerator: null, concentration_denominator: null });
  }
  if (mode === "bad-source-date") result.projection.tree[0].members[0].theme_source_date = {};
  if (mode === "bad-seal") result.projection.tree[0].members[0].theme_first_seal = {};
  if (mode === "bad-basis") result.projection.lineage[0].adjustment_basis_id = {};
  if (mode === "bad-name") result.projection.lineage[0].name = {};
  return result;
}
export function validThemeQuery(method, pathname, search) {
  const q = new URLSearchParams(search);
  return method === "GET" && pathname === "/api/market/theme-research" && [...q.keys()].length === 1 && [dayA, dayB].includes(q.get("trade_date"));
}
export function observeThemeReads() {
  const original = window.fetch.bind(window);
  window.__themeReads = [];
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (url.pathname !== "/api/market/theme-research") return original(input, init);
    const record = { date: url.searchParams.get("trade_date"), aborted: false, parsed: false };
    window.__themeReads.push(record);
    init?.signal?.addEventListener("abort", () => { record.aborted = true; });
    const response = await original(input, { ...init, signal: undefined });
    const read = response.json.bind(response);
    response.json = async () => { const value = await read(); record.parsed = true; return value; };
    return response;
  };
}
