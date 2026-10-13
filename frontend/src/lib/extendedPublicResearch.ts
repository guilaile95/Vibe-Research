export type ExtendedKind = "market" | "company";
export interface ExtendedSelection { kind: ExtendedKind; asOf: string; market?: string; symbol?: string }
export interface ExtendedBlock {
  source_id: string; subject: string; label: string; status: string; guard: string; captured_at: string;
  source_url: string; rows: Record<string, any>[]; reason_codes: string[]; fixture: boolean;
  archive_stale?: boolean; counters?: Record<string, number>;
  evidence: { observation_id: string; raw_payload_hash: string; locally_received_at: string; point_in_time_claim: "NONE" };
}
export interface ExtendedPublicResearch {
  schema_version: "extended-public-research.v1"; kind: ExtendedKind; requested_as_of: string; market: string; symbol: string | null;
  status: string; message: string; fixture: boolean; blocks: ExtendedBlock[]; missing_sources: { source_id: string; subject: string }[];
  reason_codes: string[]; turnover?: { rows: { date: string; sh: number | null; sz_composite: number | null; total: number | null; currency: "CNY"; unit: "CNY" }[]; ma20: number | null; ma60: number | null; basis: string };
}
const isObject = (x: unknown): x is Record<string, any> => !!x && typeof x === "object" && !Array.isArray(x);
const finite = (x: unknown) => x === null || typeof x === "number" && Number.isFinite(x);
const text = (x: unknown): x is string => typeof x === "string" && x.length < 4096;
export function validResearchDate(x: unknown): x is string {
  if (typeof x !== "string" || !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(x)) return false;
  const d = new Date(x + "T00:00:00Z"); return Number.isFinite(d.getTime()) && d.toISOString().slice(0, 10) === x;
}
function instant(x: unknown): number {
  if (typeof x !== "string" || !validResearchDate(x.slice(0, 10)) || !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\.\d{6}Z$/.test(x)) throw Error("Invalid timestamp");
  const n = Date.parse(x) * 1000 + Number(x.slice(23, 26)); if (!Number.isSafeInteger(n)) throw Error("Unsafe timestamp"); return n;
}
function tree(x: unknown, depth = 0, budget = { nodes: 200000, chars: 8000000 }): boolean {
  if (--budget.nodes < 0 || depth > 12) return false;
  if (x === null || typeof x === "boolean") return true;
  if (typeof x === "number") return Number.isFinite(x);
  if (typeof x === "string") return (budget.chars -= x.length) >= 0;
  if (Array.isArray(x)) return x.length <= 1000 && x.every(v => tree(v, depth + 1, budget));
  if (!isObject(x) || Object.keys(x).length > 100) return false;
  return Object.entries(x).every(([k, v]) => (budget.chars -= k.length) >= 0 && tree(v, depth + 1, budget));
}
const INDEX_KEYS = ["sh000001", "sz399001", "sz399006", "sh000300", "sh000905", "sh000852", "sh000688", "bj899050", "sz399106"];
const GLOBAL = ["global_quote_ref", "global_financials_pit", "yahoo_consensus"];
const CN = ["cn_quote_ref", "cn_financials_ytd", "cn_consensus"];
function expect(value: unknown, wanted: unknown) { if (value !== wanted) throw Error("Source contract mismatch"); }
function fields(row: Record<string, any>, names: string[]) { for (const key of names) if (!finite(row[key])) throw Error("Invalid numeric field"); }
function scalarFields(row: Record<string, any>) {
  const nested = new Set(["metrics", "windows", "ytd_window", "amount_window", "amount_rows", "missing", "quote", "benchmark"]);
  for (const [key, value] of Object.entries(row)) if (!nested.has(key) && value !== null && !["string", "number", "boolean"].includes(typeof value)) throw Error("Non-scalar display field");
}
function coverage(w: any, cutoff: string) {
  if (!isObject(w)) throw Error("Invalid coverage");
  const expected = dates(w.expected_dates, cutoff), observed = dates(w.observed_dates, cutoff), missing = dates(w.missing_dates, cutoff);
  if (observed.some(d => !expected.includes(d) || missing.includes(d)) || missing.some(d => !expected.includes(d)) || observed.length + missing.length !== expected.length) throw Error("Coverage mismatch");
  return { expected, observed, missing };
}
function dates(list: unknown, cutoff: string): string[] {
  if (!Array.isArray(list) || !list.every(d => validResearchDate(d) && d <= cutoff) || list.some((d, i) => i && list[i - 1] >= d)) throw Error("Invalid date coverage");
  return list;
}
function expectedSourceUrl(source: string, subject: string): string {
  const [key, cutoff] = subject.split("@"); const [market, symbol] = key.split(":");
  const qs = (v: Record<string,string>) => new URLSearchParams(v).toString();
  if (source === "em_market_trend") return "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + qs({secid:(key.startsWith("sh")?"1.":"0.")+key.slice(2),fields1:"f1,f2,f3",fields2:"f51,f53,f57",klt:"101",fqt:"0",end:cutoff.replace(/-/g,""),lmt:"600"});
  if (source === "index_valuation") return "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/indicator/000300indicator.xls";
  if (source === "chinabond_yield_curve") return "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/historyQuery?" + qs({startDate:cutoff,endDate:cutoff,gjqx:"0",qxId:"hzsylqx",locale:"cn_ZH"});
  const prefix = /^(60|68)/.test(symbol)?"sh":/^(43|83|87|88|92)/.test(symbol)?"bj":"sz";
  if (["global_quote_ref","cn_quote_ref"].includes(source)) return "https://qt.gtimg.cn/q="+(market==="US"?`us${symbol},usINX`:market==="HK"?`r_hk${symbol},hkHSI`:`${prefix}${symbol},sh000001`);
  if (["global_financials_pit","cn_financials_ytd"].includes(source)) {
    const field=market==="US"?"SECURITY_CODE":"SECUCODE", value=market==="US"?symbol.replace(/\./g,"_"):symbol+(market==="HK"?".HK":"."+prefix.toUpperCase());
    return "https://datacenter-web.eastmoney.com/api/data/v1/get?"+qs({reportName:source==="cn_financials_ytd"?"RPT_DMSK_FN_INCOME":`RPT_${market}F10_FN_GMAININDICATOR`,columns:"ALL",filter:`(${field}="${value}")`,pageSize:"60",pageNumber:"1",sortColumns:"REPORT_DATE",sortTypes:"-1"});
  }
  if (source === "yahoo_consensus") return "https://query2.finance.yahoo.com/v10/finance/quoteSummary/"+(market==="US"?symbol.replace(/\./g,"-"):String(Number(symbol)).padStart(4,"0")+".HK")+"?modules=earningsTrend,earnings,price";
  return `https://basic.10jqka.com.cn/new/${symbol}/worth.html`;
}
export function parseExtendedResearch(value: unknown, selected: ExtendedSelection): ExtendedPublicResearch {
  if (!tree(value) || !isObject(value) || !validResearchDate(selected.asOf)) throw Error("Invalid response");
  expect(value.schema_version, "extended-public-research.v1"); expect(value.kind, selected.kind); expect(value.requested_as_of, selected.asOf);
  expect(value.market, selected.kind === "market" ? "CN" : selected.market); expect(value.symbol, selected.kind === "market" ? null : selected.symbol);
  expect(value.selection_mode, "CURRENT_ARCHIVED_POSTHOC"); expect(value.point_in_time_claim, "NONE"); expect(value.ingestion_enabled, false); expect(value.schedule_enabled, false);
  if (!text(value.message) || typeof value.fixture !== "boolean" || !["partial", "missing", "unavailable"].includes(value.status) || !Array.isArray(value.blocks) || value.blocks.length > 11 || !Array.isArray(value.missing_sources) || !Array.isArray(value.reason_codes) || !value.reason_codes.every(text)) throw Error("Invalid source envelope");
  if (selected.kind === "company" && "turnover" in value) throw Error("Company response cannot carry market turnover");
  const expected = selected.kind === "market" ? INDEX_KEYS.map(k => `em_market_trend|${k}@${selected.asOf}`).concat([`index_valuation|000300@${selected.asOf}`, `chinabond_yield_curve|treasury@${selected.asOf}`]) : (selected.market === "A" ? CN : GLOBAL).map(s => `${s}|${selected.market}:${selected.symbol}@${selected.asOf}`);
  const seen = new Set<string>();
  for (const block of value.blocks) {
    if (!isObject(block) || !expected.includes(`${block.source_id}|${block.subject}`) || seen.has(`${block.source_id}|${block.subject}`)) throw Error("Unexpected block identity");
    seen.add(`${block.source_id}|${block.subject}`); expect(block.schema_version, "public-research.v1"); expect(block.fixture, value.fixture);
    expect(block.normalizer_version, "public-research-adapter.v1"); expect(block.point_in_time_claim, "NONE"); expect(block.selection_mode, "CURRENT_ARCHIVED_POSTHOC"); expect(block.requested_as_of, selected.asOf);
    expect(block.source_url, expectedSourceUrl(block.source_id, block.subject));
    expect(block.source_revision, null); expect(block.source_publication_time, null); expect(block.license_status, "PROVIDER_TERMS_NOT_VERIFIED");
    if (!["partial", "missing", "unavailable"].includes(block.status) || typeof block.archive_stale !== "boolean" || !finite(block.archive_age_seconds) || block.archive_age_seconds < 0 || !isObject(block.counters) || !Object.values(block.counters).every(n => Number.isSafeInteger(n) && Number(n) >= 0)) throw Error("Block qualification");
    if (!text(block.label) || !text(block.guard) || !text(block.source_url) || !Array.isArray(block.rows) || block.rows.length > 500 || !Array.isArray(block.reason_codes) || !block.reason_codes.every(text) || !isObject(block.evidence)) throw Error("Invalid block");
    if (instant(block.captured_at) > instant(block.evidence.locally_received_at) || instant(block.evidence.locally_received_at) > Date.now() * 1000) throw Error("Future receipt");
    expect(block.evidence.point_in_time_claim, "NONE"); expect(block.evidence.normalizer_version, "public-research-adapter.v1"); expect(block.evidence.provider_revision, null);
    if (!text(block.evidence.raw_payload_hash) || !/^sha256:[a-f0-9]{64}$/.test(block.evidence.raw_payload_hash) || !text(block.evidence.observation_id)) throw Error("Invalid provenance");
    if (block.status === "unavailable" && (block.rows.length || JSON.stringify(block.reason_codes) !== JSON.stringify(["HTTP_OR_NORMALIZATION_FAILED"]))) throw Error("Failed source variant");
    const identities = new Set<string>();
    for (const row of block.rows) {
      if (!isObject(row) || !text(row.id) || identities.has(row.id)) throw Error("Invalid row"); identities.add(row.id); scalarFields(row);
      if (block.source_id === "em_market_trend") {
        expect(row.id, block.subject.split("@")[0]); expect(row.index_code, row.id.slice(2)); expect(row.date, selected.asOf);
        expect(row.adjustment, "UNADJUSTED"); expect(row.unit, "index points"); expect(row.amount_currency, "CNY"); expect(row.source_vintage, "SINGLE_RAW_RECEIPT");
        if (!text(row.name) || typeof row.provisional !== "boolean") throw Error("Trend label");
        expect(row.exchange, row.id.startsWith("sh") ? "SSE" : row.id.startsWith("sz") ? "SZSE" : "BSE"); expect(row.currency, null); expect(row.amount_unit, "CNY");
        fields(row, ["close"]); if (!isObject(row.metrics) || !isObject(row.windows) || !isObject(row.amount_window)) throw Error("Trend contract");
        if (Object.keys(row.windows).sort().join() !== ["20", "250", "5", "60"].join()) throw Error("Unexpected windows");
        fields(row.metrics, ["return_5d_pct", "return_20d_pct", "return_60d_pct", "return_250d_pct", "ytd_pct", "ma20", "ma60", "ma250", "high250", "low250", "off_high250_pct"]);
        if (row.metrics.ytd_basis_date !== null && (!validResearchDate(row.metrics.ytd_basis_date) || row.metrics.ytd_basis_date.slice(0,4) !== String(Number(selected.asOf.slice(0,4))-1))) throw Error("YTD basis");
        const ytd = coverage(row.ytd_window, selected.asOf); coverage(row.amount_window, selected.asOf);
        if ((ytd.missing.length || !row.metrics.ytd_basis_date) && row.metrics.ytd_pct !== null) throw Error("YTD gap");
        for (const n of [5, 20, 60, 250]) {
          const w = row.windows[String(n)]; if (!isObject(w)) throw Error("Missing window");
          const expectedDates = dates(w.expected_dates, selected.asOf), observed = dates(w.observed_dates, selected.asOf), missing = dates(w.missing_dates, selected.asOf);
          if (observed.some(d => !expectedDates.includes(d) || missing.includes(d)) || missing.some(d => !expectedDates.includes(d)) || observed.length + missing.length !== expectedDates.length) throw Error("Coverage mismatch");
          if (!finite(row.metrics[`return_${n}d_pct`]) || (missing.length > 0 || expectedDates.length !== n + 1) && row.metrics[`return_${n}d_pct`] !== null) throw Error("Gap-skipping return");
        }
        if (!Array.isArray(row.amount_rows) || row.amount_rows.length > 60) throw Error("Amount budget");
        for (const p of row.amount_rows) { if (!isObject(p) || !validResearchDate(p.date) || p.date > selected.asOf) throw Error("Amount date"); fields(p, ["amount", "close"]); if (p.amount !== null && p.amount < 0 || p.close !== null && p.close <= 0) throw Error("Amount domain"); }
        dates(row.amount_rows.map((p: any) => p.date), selected.asOf);
      } else if (block.source_id === "index_valuation") {
        expect(row.id, row.date); expect(row.calculation_method, "provider total-share vs calculation-share bases"); expect(row.index_code, "000300"); expect(row.universe, "CSI300"); expect(row.pe_unit, "times"); expect(row.dividend_unit, "percent"); expect(row.pb, null);
        if (!validResearchDate(row.date) || row.date > selected.asOf) throw Error("Valuation date"); fields(row, ["pe_total", "pe_calculation", "dividend_yield_total_pct", "dividend_yield_calculation_pct"]);
        expect(row.pe_interpretation, "nonpositive PE is loss/undefined, never cheapness rank");
      } else if (block.source_id === "chinabond_yield_curve") {
        expect(row.id, `${row.date}:${row.tenor}`); expect(row.date, selected.asOf); expect(row.curve, "treasury"); expect(row.currency, "CNY"); expect(row.unit, "percent yield"); expect(row.price, null); expect(row.holding_return, null);
        if (!["3m", "6m", "1y", "3y", "5y", "7y", "10y", "30y"].includes(row.tenor) || !finite(row.yield_pct) || row.yield_pct !== null && Math.abs(row.yield_pct) > 100) throw Error("Yield contract");
      } else {
        expect(row.market, selected.market); expect(row.symbol, selected.symbol);
        if (["global_quote_ref", "cn_quote_ref"].includes(block.source_id)) {
          expect(row.id, `${selected.market}:${selected.symbol}`); expect(row.requested_cutoff, selected.asOf);
          if (typeof row.source_stale !== "boolean" || typeof row.after_requested_date !== "boolean" || !["pre_open_by_clock", "regular_hours_by_clock", "post_close_by_clock", "midday_break_by_clock", "weekend_by_clock"].includes(row.clock_phase)) throw Error("Quote qualification");
          fields(row, ["quote_age_seconds_at_capture", "benchmark_age_seconds_at_capture"]);
          expect(row.same_response, true); expect(row.session_calendar_confirmed, false);
          for (const key of ["quote", "benchmark"]) {
            const q = row[key]; if (!isObject(q) || !text(q.symbol) || !validResearchDate(q.session_date) || instant(q.source_time) > instant(block.captured_at)) throw Error("Quote clock");
            scalarFields(q); if (!text(q.name) || !text(q.key)) throw Error("Quote name");
            fields(q, ["price", "prev_close", "volume"]);
            if (!(typeof q.price === "number" && q.price > 0 && typeof q.prev_close === "number" && q.prev_close > 0) || q.volume !== null && q.volume < 0) throw Error("Quote domain");
            expect(row[`${key}_age_seconds_at_capture`], (instant(block.captured_at) - instant(q.source_time)) / 1000000); expect(q.timezone, selected.market === "US" ? "America/New_York" : selected.market === "HK" ? "Asia/Hong_Kong" : "Asia/Shanghai");
          }
          expect(row.after_requested_date, row.quote.session_date > selected.asOf || row.benchmark.session_date > selected.asOf);
          expect(row.benchmark.symbol, selected.market === "US" ? "INX" : selected.market === "HK" ? "HSI" : "000001"); expect(row.benchmark.key, selected.market === "US" ? "usINX" : selected.market === "HK" ? "hkHSI" : "sh000001");
          expect(row.quote.key, (selected.market === "US" ? "us" : selected.market === "HK" ? "r_hk" : /^(60|68)/.test(selected.symbol || "") ? "sh" : /^(43|83|87|88|92)/.test(selected.symbol || "") ? "bj" : "sz") + selected.symbol); expect(row.quote.unit, "quote currency per share");
          expect(row.quote.symbol, selected.symbol); expect(row.quote.currency, selected.market === "US" ? "USD" : selected.market === "HK" ? "HKD" : "CNY"); expect(row.benchmark.currency, null); expect(row.benchmark.unit, "index points");
          expect(row.source_stale, row.quote.session_date < row.benchmark.session_date || row.quote.volume === 0 && row.quote.price === row.quote.prev_close);
          expect(row.reference_session_date, row.benchmark.session_date); expect(row.freshness_qualification, "ARCHIVED_SNAPSHOT_NOT_LIVE_FRESHNESS_CERTIFICATION");
        } else if (["global_financials_pit", "cn_financials_ytd"].includes(block.source_id)) {
          if (![row.start, row.end, row.notice_date].every(d => validResearchDate(d) && d <= selected.asOf) || row.start > row.end || !["ytd", "annual_ytd", "quarter"].includes(row.period_kind)) throw Error("Fiscal date contract");
          expect(row.id, `${row.start}..${row.end}`);
          if (!text(row.returned_secucode) || row.consolidation_scope !== null && !text(row.consolidation_scope)) throw Error("Financial identity");
          const code = (selected.symbol || "").replace(/\./g,"_");
          const suffix = selected.market === "HK" ? ".HK" : /^(60|68)/.test(code) ? ".SH" : /^(43|83|87|88|92)/.test(code) ? ".BJ" : ".SZ";
          if (!(selected.market === "US" ? [".O",".N",".A"].map(v=>code+v) : [code+suffix]).includes(row.returned_secucode)) throw Error("Returned financial issuer");
          const periodDays = (Date.parse(row.end) - Date.parse(row.start)) / 86400000 + 1;
          expect(row.period_days, periodDays); expect(row.period_months, Math.round(periodDays / 30.44));
          if (![3,6,9,12].includes(row.period_months) || row.period_kind === "quarter" && row.period_months !== 3 || row.period_kind === "annual_ytd" && row.period_months !== 12) throw Error("Fiscal duration");
          if (selected.market === "A") { expect(row.currency, "CNY"); expect(row.period_code, "CN_STANDARD_REPORT_END"); expect(row.start, row.end.slice(0,4)+"-01-01"); }
          if (selected.market !== "A") {
            const periods: Record<string,[string,number]> = {"001":["annual_ytd",12],"002":["ytd",6],"003":["ytd",3],"004":["ytd",9],"006":["quarter",3],"007":["quarter",3],"008":["quarter",3]};
            const period=periods[row.period_code]; if (!period || row.period_kind !== period[0] || row.period_months !== period[1]) throw Error("Fiscal code");
          }
          expect(row.eps_unit, "reporting currency per share"); expect(row.vintage, "CURRENT_STORED_POSTHOC"); expect(row.point_in_time_claim, "NONE"); expect(row.revision_id, null); expect(row.amount_unit, "PROVIDER_RAW_SCALE_UNVERIFIED"); expect(row.amount_scale_to_currency_units, null);
          if (![null, "USD", "HKD", "CNY"].includes(row.currency)) throw Error("Financial currency"); fields(row, ["revenue", "net_profit_parent", "net_profit_deducted", "eps_basic", "eps_diluted"]);
        } else {
          expect(row.source_update_time, null);
          if (row.currency !== null && !["USD", "HKD", "CNY", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "TWD", "KRW"].includes(row.currency)) throw Error("Consensus currency");
          if (!validResearchDate(row.fiscal_end)) throw Error("Fiscal end unknown"); expect(row.fiscal_label, "FY" + row.fiscal_end.slice(0, 4)); expect(row.period_kind, "annual_estimate"); expect(row.rating, null);
          fields(row, ["eps_avg", "eps_low", "eps_high", "analyst_count"]);
          if (row.analyst_count !== null && (!Number.isSafeInteger(row.analyst_count) || row.analyst_count < 0) || [row.eps_avg, row.eps_low, row.eps_high].every(x => x !== null) && !(row.eps_low <= row.eps_avg && row.eps_avg <= row.eps_high)) throw Error("Consensus coverage/bounds");
          if (block.source_id === "cn_consensus") { expect(row.currency, "CNY"); expect(row.eps_unit, "CNY per share"); expect(row.fiscal_end, row.id+"-12-31"); expect(row.returned_identity_basis, "HTML page title"); expect(row.fiscal_end_basis, "CN statutory calendar fiscal year"); }
          else {
            if (!["0y", "+1y"].includes(row.horizon)) throw Error("Annual horizon");
            expect(row.id, row.horizon); expect(row.revision_id, null); expect(row.eps_unit, "reporting currency per share"); expect(row.revenue_unit, "reporting currency units"); fields(row, ["revenue_estimate"]);
            expect(row.returned_symbol, selected.market === "US" ? selected.symbol?.replace(".", "-") : String(Number(selected.symbol)).padStart(4,"0")+".HK");
            expect(row.quote_currency, selected.market === "US" ? "USD" : selected.market === "HK" ? "HKD" : "CNY");
          }
        }
      }
    }
  }
  for (const missing of value.missing_sources) { if (!isObject(missing) || !expected.includes(`${missing.source_id}|${missing.subject}`) || seen.has(`${missing.source_id}|${missing.subject}`)) throw Error("Invalid missing coverage"); seen.add(`${missing.source_id}|${missing.subject}`); }
  if (expected.some(k => !seen.has(k))) throw Error("Undisclosed missing source");
  if (selected.kind === "market") {
    const t = value.turnover; if (!isObject(t) || !Array.isArray(t.rows) || t.rows.length > 60 || !text(t.basis)) throw Error("Turnover shape");
    fields(t, ["ma20", "ma60"]);
    const expectedTurnover = dates(t.expected_dates, selected.asOf); dates(t.rows.map((r: any) => r?.date), selected.asOf);
    expect(JSON.stringify(t.rows.map((r: any) => r.date)), JSON.stringify(expectedTurnover));
    expect(JSON.stringify(t.missing_dates), JSON.stringify(t.rows.filter((r: any) => r.total === null).map((r: any) => r.date)));
    for (const n of [20,60]) {
      const rows = t.rows.slice(-n); expect(t[`ma${n}`], rows.length === n && rows.every((r: any) => r.total !== null) ? rows.reduce((v: number, r: any) => v+r.total,0)/n : null);
    }
    for (const row of t.rows) { if (!isObject(row) || !validResearchDate(row.date) || row.date > selected.asOf) throw Error("Turnover date"); expect(row.currency, "CNY"); expect(row.unit, "CNY"); fields(row, ["sh", "sz_composite", "total"]); expect(row.total, row.sh === null || row.sz_composite === null ? null : row.sh + row.sz_composite); }
  }
  return value as ExtendedPublicResearch;
}
