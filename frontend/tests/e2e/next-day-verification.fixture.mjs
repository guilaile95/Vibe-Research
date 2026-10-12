/** Golden payloads are verified against the real Python journal service in CI. */
import { readFileSync } from "node:fs";
import { isDeepStrictEqual } from "node:util";

export const golden = JSON.parse(readFileSync(new URL("../fixtures/next-day-verification.json", import.meta.url), "utf8"));
export const DAY = "2026-07-31";
export const CLOCK = "2026-08-03T00:00:00Z";
export const JOURNAL_VIEWPORTS = Object.freeze([
  Object.freeze({ label: "desktop-1440", width: 1440, height: 1000 }),
  Object.freeze({ label: "mobile-390", width: 390, height: 844 }),
]);
export const json = (body, status = 200) => ({ kind: "json", status, body });
const copy = (value) => structuredClone(value);

export function createFixture(origin, { withSealQuality = false } = {}) {
  const requests = [];
  const violations = [];
  const writes = [];
  const expectedWrites = [];
  const views = new Map([[DAY, "open_empty"], ["2026-08-03", "cold"], ["2026-07-30", "older"], ["2026-12-31", "calendar_unknown"]]);
  const getErrors = new Map();
  const deny = (reason) => { violations.push(reason); return { kind: "deny", reason }; };
  return {
    requests, violations, writes, expectedWrites,
    setView: (day, key) => views.set(day, key),
    failGet: (day) => getErrors.set(day, true),
    expectSave: (body, responseKey, status = 200) => expectedWrites.push({ body, responseKey, status }),
    handle(rawUrl, method = "GET", body) {
      let url;
      try { url = new URL(rawUrl); } catch { return deny("malformed URL"); }
      requests.push({ url: rawUrl, method, body });
      if (url.origin !== origin) return deny(`wrong origin ${url.origin}`);
      const pathname = url.pathname;
      if (method !== "GET") {
        if (method !== "PUT" || pathname !== `/api/next-day-verification/${DAY}` || url.search) return deny(`unexpected write ${method} ${pathname}`);
        const expected = expectedWrites.shift();
        if (!expected || !isDeepStrictEqual(expected.body, body)) return deny("write outside explicit expected click/payload/revision");
        writes.push(copy(body));
        if (expected.responseKey) views.set(DAY, expected.responseKey);
        return expected.status === 200
          ? json({ data: copy(golden[expected.responseKey]) })
          : json({ detail: expected.status === 409 ? "记录已改变，请重新读取后再保存" : "验证记录不可写入，未保存修改" }, expected.status);
      }
      if (pathname.startsWith("/api/next-day-verification/")) {
        const day = pathname.slice("/api/next-day-verification/".length);
        if (url.search || !views.has(day)) return deny(`unexpected journal GET ${day}${url.search}`);
        if (getErrors.get(day)) { getErrors.delete(day); return json({ detail: "验证记录不可读取，已停止操作" }, 503); }
        return json({ data: copy(golden[views.get(day)]) });
      }
      if (pathname === "/api/market/seal-quality") {
        if (!withSealQuality || url.search !== `?trade_date=${DAY}`) return deny("unexpected seal-quality request");
        // Exact unavailable archive response from accepted seal-quality slice.
        return json({ data: { schema_version: "short-term-seal-quality-archive-v0.1", trade_date: DAY,
          status: "unavailable", reason_codes: ["ARCHIVE_NOT_CONNECTED"],
          message: "封板质量归档证据未连接；不会自动启用采集或请求行情。",
          selection: null, archive_identity: null, projection: null, archive_only: true, ingestion_enabled: false } });
      }
      const expectedQueries = {
        "/api/daily-review": [""], "/api/daily-review/history": ["?limit=20&offset=0"],
        "/api/watchlist": [""], "/api/radar": [""], "/api/market/northbound": [""],
        "/api/market/bk11-history": ["?days=5"], "/api/market/cloud": ["?scope=all&period=today"],
        "/api/native-intel/status": [""], "/api/native-intel/items": ["?limit=40&order_by=last_seen"],
        "/api/native-intel/trending": ["?window_hours=24&top_n=20"],
        "/api/ai-results/daily_review_ai": ["", `?trade_date=${DAY}`],
        "/api/ai-results/portfolio_advice": ["", `?trade_date=${DAY}`],
      };
      if (expectedQueries[pathname] && !expectedQueries[pathname].includes(url.search)) return deny(`unexpected query ${pathname}${url.search}`);
      if (pathname === "/api/daily-review") return json({ data: {
        schema_version: "daily-review-v0.1", status: "partial", trade_date: DAY,
        generated_at: CLOCK, data_cutoff: null, warnings: [], data_health: { components: {} },
      }, cache_meta: { source: "persisted", stale: false, refreshing: false } });
      if (pathname === "/api/daily-review/history") return json({ data: { items: [], count: 0, limit: 20, offset: 0 } });
      if (pathname === "/api/watchlist") return json({ data: { status: "valid", data: { codes: [], updated_at: CLOCK }, etag: "synthetic" } });
      if (["/api/ai-results/daily_review_ai", "/api/ai-results/portfolio_advice"].includes(pathname)) return json({ data: null });
      if (pathname === "/api/radar") return json({ data: { generated_at: CLOCK, industries: [], stats: { total_sources: 0, failed_sources: 0, industries: 0 } } });
      if (pathname === "/api/native-intel/status") return json({ status: "unavailable", generated_at: CLOCK, store: { readable: false }, error: "synthetic unavailable" });
      if (pathname === "/api/native-intel/items") return json({ status: "unavailable", items: [], total: 0, limit: 40, offset: 0, error: "synthetic unavailable" });
      if (pathname === "/api/native-intel/trending") return json({ status: "unavailable", items: [], entities: [], item_count: 0, error: "synthetic unavailable" });
      if (["/api/market/northbound", "/api/market/bk11-history", "/api/market/cloud"].includes(pathname)) return json({ detail: "Synthetic source is intentionally unavailable" }, 503);
      if (pathname.startsWith("/api/")) return deny(`unexpected API GET ${pathname}`);
      if (url.search) return deny(`unexpected static query ${pathname}`);
      if (pathname === "/daily-review" || pathname === "/" || pathname === "/index.html" || pathname === "/favicon.svg" || /^\/assets\/[A-Za-z0-9_.-]+\.(?:js|css|woff2|svg|png)$/.test(pathname)) return { kind: "static" };
      return deny(`unexpected static request ${pathname}`);
    },
  };
}
