export const PUBLIC_SOURCES = {
  public_polymarket: "Polymarket 事件定价", public_kalshi: "Kalshi 事件定价",
  tw_monthly_revenue: "台湾月营收", dram_spot_thermo: "DRAM / NAND 现货",
  cn_commodity_futures: "大宗连续期货", hiring_anchor_signal: "公开招聘信号",
} as const;
export type PublicSource = keyof typeof PUBLIC_SOURCES;
export type PublicRow = Record<string, unknown> & {
  id: string; title: string; value: number | null; currency: string | null; unit: string;
  source_date: string | null; source_time: string | null; status: string; stale: boolean; missing: string[];
};
export interface PublicBlock {
  subject: string; status: string; rows: PublicRow[]; reason_codes: string[]; captured_at: string;
  fixture: boolean; license_status: string; source_url: string;
  evidence: { observation_id: string; raw_payload_hash: string; locally_received_at: string; normalizer_version: string; point_in_time_claim: string };
}
export interface PublicResearch {
  schema_version: string; source_id: PublicSource; label: string; status: string; message: string;
  reason_codes: string[]; blocks: PublicBlock[]; missing_subjects: string[]; guard: string;
  fixture: boolean; ingestion_enabled: false; schedule_enabled: false; research_only: true;
}
const statuses = new Set(["normal", "partial", "missing", "unavailable", "closed", "stale"]);
const object = (x: unknown): x is Record<string, unknown> => !!x && typeof x === "object" && !Array.isArray(x);
const str = (x: unknown): x is string => typeof x === "string" && x.length <= 2048;
const strings = (x: unknown): x is string[] => Array.isArray(x) && x.length <= 500 && x.every(str);
const nullableText = (x: unknown) => x === null || str(x);
function finiteTree(x: unknown, depth = 0, budget = { nodes: 250000, characters: 16 * 1024 * 1024 }): boolean {
  if (depth > 8 || --budget.nodes < 0) return false;
  if (typeof x === "number") return Number.isFinite(x);
  if (typeof x === "string") { budget.characters -= x.length; return budget.characters >= 0; }
  if (x === null || typeof x === "boolean") return true;
  if (Array.isArray(x)) return x.length <= 5000 && x.every(v => finiteTree(v, depth + 1, budget));
  if (!object(x)) return false;
  const keys = Object.keys(x);
  budget.characters -= keys.reduce((sum, key) => sum + key.length, 0);
  return keys.length <= 100 && budget.characters >= 0 && Object.values(x).every(v => finiteTree(v, depth + 1, budget));
}
const SUBJECTS: Record<PublicSource, string[]> = {
  public_polymarket: ["markets"], public_kalshi: ["markets"],
  tw_monthly_revenue: ["2383", "6274", "2368", "3081"], dram_spot_thermo: ["DDR5", "NAND_TLC", "DDR4"],
  cn_commodity_futures: ["CU0", "SN0", "AL0", "NI0", "SI0"],
  hiring_anchor_signal: ["greenhouse:lightmatter", "greenhouse:asteralabs", "ashby:cerebras", "ashby:openai", "greenhouse:xai", "greenhouse:anthropic"],
};
function validDate(x: unknown): x is string {
  if (typeof x !== "string" || !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(x)) return false;
  const d = new Date(x + "T00:00:00Z");
  return Number.isFinite(d.getTime()) && d.toISOString().slice(0, 10) === x;
}
function instant(x: unknown): number {
  if (typeof x !== "string" || !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(x) || !validDate(x.slice(0, 10))) throw new Error("Invalid source timestamp");
  // Exact integer microseconds within the current provider-year range.
  const value = Date.parse(x), fractional = x.match(/\.(\d{1,6})/);
  const microseconds = value * 1000 + Number((fractional?.[1] || "").padEnd(6, "0").slice(3));
  if (!Number.isSafeInteger(microseconds)) throw new Error("Timestamp outside safe range");
  return microseconds;
}
function sourceUrl(source: PublicSource, subject: string): string {
  if (source === "public_polymarket") return "https://gamma-api.polymarket.com/markets?limit=100&active=true&closed=false&order=volume24hr&ascending=false";
  if (source === "public_kalshi") return "https://api.elections.kalshi.com/trade-api/v2/markets?limit=200&status=open";
  if (source === "tw_monthly_revenue") return `https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMonthRevenue&data_id=${subject}&start_date=2020-01-01`;
  if (source === "dram_spot_thermo") return subject === "DDR4" ? "https://raw.githubusercontent.com/titled-agent-001/ddr4-pricing-log/main/ddr4-pricing.json" : "https://raw.githubusercontent.com/nlee756525/dram-prices/main/history.json";
  if (source === "cn_commodity_futures") return `https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_V21052021_4_12=/InnerFuturesNewService.getDailyKLine?symbol=${subject}&type=2021_04_12`;
  const [ats, board] = subject.split(":");
  return ats === "greenhouse" ? `https://boards-api.greenhouse.io/v1/boards/${board}/jobs` : `https://api.ashbyhq.com/posting-api/job-board/${board}`;
}
export function parsePublicResearch(value: unknown, source: PublicSource): PublicResearch {
  if (!object(value) || value.schema_version !== "public-research.v1" || value.source_id !== source
    || !str(value.label) || !str(value.message) || !str(value.guard) || !statuses.has(String(value.status))
    || !strings(value.reason_codes) || !strings(value.missing_subjects) || typeof value.fixture !== "boolean"
    || value.ingestion_enabled !== false || value.schedule_enabled !== false || value.research_only !== true || value.selection_mode !== "CURRENT_ARCHIVED_POSTHOC"
    || !Array.isArray(value.blocks) || value.blocks.length > 10 || !finiteTree(value)) throw new Error("Invalid public research response");
  const identities = new Set<string>();
  for (const block of value.blocks) {
    if (!object(block) || !str(block.subject) || identities.has(block.subject) || !statuses.has(String(block.status))
      || !strings(block.reason_codes) || !str(block.captured_at) || block.license_status !== "PROVIDER_TERMS_NOT_VERIFIED"
      || typeof block.fixture !== "boolean" || block.fixture !== value.fixture || !str(block.source_url)
      || !Array.isArray(block.rows) || block.rows.length > 500 || !object(block.evidence)
      || !str(block.evidence.observation_id) || !str(block.evidence.normalizer_version)
      || !str(block.evidence.locally_received_at) || block.evidence.point_in_time_claim !== "NONE"
      || typeof block.evidence.raw_payload_hash !== "string" || !/^sha256:[a-f0-9]{64}$/.test(block.evidence.raw_payload_hash)) throw new Error("Invalid public research block");
    if (!SUBJECTS[source].includes(block.subject) || block.schema_version !== "public-research.v1" || block.source_id !== source
      || block.source_url !== sourceUrl(source, block.subject) || block.evidence.normalizer_version !== "public-research-adapter.v1"
      || instant(block.captured_at) > instant(block.evidence.locally_received_at)
      || instant(block.evidence.locally_received_at) > Date.now() * 1000) throw new Error("Invalid receipt identity or time");
    identities.add(block.subject);
    const rows = new Set<string>();
    for (const row of block.rows) {
      if (!object(row) || !str(row.id) || rows.has(row.id) || !str(row.title) || !str(row.unit)
        || !nullableText(row.currency) || !(row.value === null || typeof row.value === "number" && Number.isFinite(row.value))
        || !nullableText(row.source_date) || !nullableText(row.source_time) || !strings(row.missing)
        || !statuses.has(String(row.status)) || typeof row.stale !== "boolean") throw new Error("Invalid public research row");
      if (source.startsWith("public_") && (!["contract_id", "outcome_id", "outcome", "price_convention", "market_status", "resolution_status"].every(k => str(row[k])) || !nullableText(row.question_id) || row.objective_probability !== null)) throw new Error("Invalid market identity");
      if (row.source_date !== null && (!validDate(row.source_date) || row.source_date > block.captured_at.slice(0, 10))) throw new Error("Invalid source date");
      if (row.source_time !== null && instant(row.source_time) > instant(block.captured_at)) throw new Error("Future source time");
      for (const key of Object.keys(FIELD_LABELS)) {
        if (key in row && !(row[key] === null || ["string", "number", "boolean"].includes(typeof row[key]))) throw new Error("Malformed detail field");
      }
      if (source === "hiring_anchor_signal") {
        if (!Array.isArray(row.listings) || row.listings.length > 5000 || row.listing_count !== row.listings.length
          || row.value !== row.listing_count || !Number.isSafeInteger(row.deduplicated_count) || Number(row.deduplicated_count) < 0) throw new Error("Invalid listing count");
        const ids = new Set<string>();
        for (const job of row.listings) {
          if (!object(job) || !str(job.listing_id) || !str(job.title) || ids.has(job.listing_id)
            || job.time_semantics !== (block.subject.startsWith("greenhouse:") ? "updated_at" : "publishedAt")
            || !(job.source_time === null || typeof job.source_time === "string")
            || job.source_time !== null && instant(job.source_time) > instant(block.captured_at)) throw new Error("Invalid listing");
          ids.add(job.listing_id);
        }
      }
      const equal = (key: string, expected: unknown) => { if (row[key] !== expected) throw new Error(`Invalid ${key} contract`); };
      const price = (x: unknown) => x === null || typeof x === "number" && Number.isFinite(x) && x >= 0 && x <= 1;
      if (source.startsWith("public_")) {
        if (![row.value, row.bid, row.ask].every(price) || typeof row.bid === "number" && typeof row.ask === "number" && row.bid > row.ask) throw new Error("Invalid event price");
        equal("currency", "USD");
        if (source === "public_polymarket") {
          equal("unit", "USD-equivalent per outcome share"); equal("price_convention", "provider_outcome_price_0_to_1");
          equal("bid", null); equal("ask", null); equal("volume_unit", "USD-equivalent");
        } else {
          equal("unit", "USD per YES contract"); equal("outcome", "Yes"); equal("volume_unit", "contracts");
          equal("settlement_currency", "USD"); equal("outcome_id", `${row.contract_id}:yes`);
          const closedState = ["closed", "settled", "finalized", "determined"].includes(String(row.market_status));
          if (typeof row.bid === "number" && typeof row.ask === "number" && (row.ask > 0 || closedState)) {
            equal("price_convention", "yes_bid_ask_midpoint_dollars"); equal("value", (row.bid + row.ask) / 2);
          } else {
            equal("price_convention", row.value === null ? "unquoted" : "yes_last_trade_dollars");
            if (!row.missing.includes("AMBIGUOUS_OR_MISSING_BOOK") || row.value === 0 && !closedState) throw new Error("Ambiguous open book presented as price");
          }
        }
      } else if (source === "tw_monthly_revenue") {
        equal("issuer", block.subject); equal("currency", "TWD"); equal("unit", "TWD"); equal("yoy_pct", null);
        equal("revision_id", null); equal("consolidation_scope", "not disclosed by source");
        if (typeof row.reporting_period !== "string" || !validDate(row.reporting_period + "-01")
          || typeof row.comparison_period !== "string" || row.comparison_period !== `${Number(row.reporting_period.slice(0, 4)) - 1}${row.reporting_period.slice(4)}`
          || typeof row.value !== "number" || row.value < 0
          || !(row.comparison_value === null || typeof row.comparison_value === "number" && row.comparison_value >= 0)) throw new Error("Invalid revenue basis");
        if (row.comparison_value === null || row.comparison_value === 0) equal("source_series_yoy_pct", null);
        else equal("source_series_yoy_pct", (row.value / Number(row.comparison_value) - 1) * 100);
      } else if (source === "dram_spot_thermo") {
        equal("is_hbm_price", false); equal("currency", "USD"); equal("unit", "USD per chip (community convention)");
        equal("price_convention", "community_transcribed_session_average");
        equal("unit_verification", "community convention; official primary source not verified");
        if (!(row.grade === null || str(row.grade)) || typeof row.value !== "number" || row.value <= 0) throw new Error("Invalid DRAM grade/price");
      } else if (source === "cn_commodity_futures") {
        equal("contract_id", block.subject); equal("currency", "CNY"); equal("unit", "CNY per metric tonne");
        equal("exchange", block.subject === "SI0" ? "GFEX" : "SHFE"); equal("contract_kind", "continuous");
        equal("delivery_month", null); equal("active_delivery_contract", null); equal("change_pct", null);
        equal("roll_adjustment", "not disclosed"); equal("price_convention", "continuous_series_daily_close");
        if (typeof row.value !== "number" || row.value <= 0) throw new Error("Invalid commodity price");
      } else if (source === "hiring_anchor_signal") {
        const [ats, board] = block.subject.split(":");
        equal("ats", ats); equal("board", board); equal("fulfilled_hires", null); equal("currency", null);
        equal("unit", "unique public listing IDs"); equal("observation_date", block.captured_at.slice(0, 10));
      }
      rows.add(row.id);
    }
  }
  const missingSubjects = value.missing_subjects;
  if (missingSubjects.some(s => !SUBJECTS[source].includes(s) || identities.has(s))
    || new Set(missingSubjects).size !== missingSubjects.length
    || SUBJECTS[source].some(s => !identities.has(s) && !missingSubjects.includes(s))) throw new Error("Invalid subject coverage");
  return value as unknown as PublicResearch;
}
export const FIELD_LABELS: Record<string, string> = {
  question_id: "问题 / 事件 ID", question_id_semantics: "问题标识语义", market_id: "市场 ID", contract_id: "合约 ID", outcome_id: "结果 ID", outcome: "结果",
  price_convention: "报价口径", bid: "买价", ask: "卖价", market_status: "市场状态", resolution_status: "结算状态",
  settlement_currency: "结算币种", volume_24h: "24h 成交量", volume_unit: "成交量单位", open_interest: "未平仓量", close_time: "截止时刻",
  issuer: "发行人", reporting_period: "报告月份", comparison_period: "去年同月基期", comparison_value: "基期营收 TWD",
  source_series_yoy_pct: "同源序列变化 %（未核实合并/修订口径）", yoy_pct: "可比口径同比 %", comparable_basis: "比较基础",
  consolidation_scope: "合并口径", revision_id: "源修订 ID", revision_semantics: "修订语义",
  grade: "精确规格", unit_verification: "单位核实状态", is_hbm_price: "是否 HBM 价格",
  exchange: "交易所", delivery_month: "交割月份", contract_kind: "合约类型", active_delivery_contract: "当前交割合约",
  roll_adjustment: "换月调整口径", change_pct: "可比涨跌 %", ats: "招聘系统", board: "公司招聘板",
  listing_count: "去重岗位数", deduplicated_count: "重复条数", observation_date: "观察日期（非发布日期）",
  source_date_semantics: "岗位日期语义", fulfilled_hires: "已聘人数",
};
