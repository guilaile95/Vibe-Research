/** Closed public-observation projection. Never serialize an incoming object. */
export type ShareMetric = "price" | "pe_ttm" | "mcap_yi";
const METRICS: ShareMetric[] = ["price", "pe_ttm", "mcap_yi"];
export function researchShareCard(input: unknown, selected: readonly ShareMetric[]) {
  if (!input || typeof input !== "object") throw new Error("资料无效");
  const data = input as Record<string, unknown>;
  if (typeof data.code !== "string" || !/^\d{6}$/.test(data.code)) throw new Error("仅支持已确认六位证券代码");
  if (!selected.length || selected.length > 3 || selected.some(k => !METRICS.includes(k))) throw new Error("请选择公开数据字段");
  const date = (value: unknown): string | null => {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
    const parsed = new Date(`${value}T00:00:00Z`);
    return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : null;
  };
  const numeric = (value: unknown, key: ShareMetric): number | null => typeof value === "number" && Number.isFinite(value)
    && Math.abs(value) <= 1e12 && (key === "pe_ttm" || value > 0) ? value : null;
  const definitions = {
    price: { label: "报价", unit: "CNY", source: data.quote_source === "tencent" ? "Tencent quote" : "UNKNOWN", as_of: date(data.quote_trade_date), source_field: "price" },
    pe_ttm: { label: "PE-TTM", unit: "ratio", source: "Eastmoney", as_of: null, source_field: "f115" },
    mcap_yi: { label: "总市值", unit: "CNY 100 million", source: "Eastmoney", as_of: null, source_field: "f20 / 1e8" },
  };
  return {
    schema: "vibe-public-research-card-v1", security_code: data.code,
    data_kind: data.fixture === true || data.data_kind === "FIXTURE" ? "FIXTURE" : "SOURCE_OBSERVATION",
    scope: "PUBLIC_MARKET_OBSERVATIONS_ONLY", verification: "PROVIDER_OBSERVATION_NOT_INDEPENDENTLY_VERIFIED",
    facts: [...new Set(selected)].map(key => {
      const value = numeric(data[key], key);
      return { metric: key, ...definitions[key], value, status: value === null ? "MISSING" : "OBSERVED" };
    }),
    limitations: ["只导出用户勾选的公开市场观察字段；不含研究正文、账户、持仓、日志、路径或凭据", "报价交易日只适用于报价；估值指标来源时间未知，不以下载时间代替", "来源观察不代表事实核验、实时行情或投资建议；测试数据需保持其测试身份"],
  };
}
export type ResearchShareCard = ReturnType<typeof researchShareCard>;
const escapeXml = (value: string) => value.replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" })[char]!);
export function researchShareSvg(card: ResearchShareCard): string {
  // Re-project before rendering, even if a consumer supplied a forged card.
  const checked = researchShareCard({ code: card.security_code, data_kind: card.data_kind,
    ...Object.fromEntries(card.facts.map(f => [f.metric, f.value])),
    quote_source: card.facts.find(f => f.metric === "price")?.source === "Tencent quote" ? "tencent" : null,
    quote_trade_date: card.facts.find(f => f.metric === "price")?.as_of,
  }, card.facts.map(f => f.metric));
  const lines = ["公开研究观察 · " + checked.security_code, `来源观察 / 未独立核验 / ${checked.data_kind}`, ...checked.facts.flatMap(f => [
    `${f.label}: ${f.value ?? "缺失"} ${f.unit} · ${f.status}`,
    `来源 ${f.source} ${f.source_field} · as-of ${f.as_of ?? "未知"}`,
  ]), "来源时间未知不能替换为下载时间；不是投资建议"];
  return `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="${120 + lines.length * 38}" viewBox="0 0 800 ${120 + lines.length * 38}"><rect width="100%" height="100%" fill="#101827"/>${lines.map((line, index) => `<text x="32" y="${64 + index * 38}" fill="${index === 0 ? "#ffffff" : "#cbd5e1"}" font-family="sans-serif" font-size="${index === 0 ? 26 : 18}">${escapeXml(line)}</text>`).join("")}</svg>`;
}
