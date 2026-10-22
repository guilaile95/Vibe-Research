import type { EvidenceRecord, MyReport, ReportPageReadResult } from "./api/types.ts";
import type { ResearchCalculation, ResearchCalculationInput, ResearchMaterial } from "./researchWorkflow.ts";
import { materialKey } from "./researchWorkflow.ts";
import { validateReportPageOcrResponse } from "./localReportOcr.ts";

/** A manual worksheet, not an extractor or semantic source verifier. */
export interface CheckOperand {
  materialKey: string;
  sourceExcerpt: string;
  subject: string;
  metric: string;
  periodStart: string;
  periodEnd: string;
  periodType: string;
  currency: string;
  unit: string;
  basis: string;
  valueType: "forecast" | "actual" | "";
  low: string;
  high: string;
  confirmed: boolean;
}
export type ComparisonMode = "actual" | "revision";
export const blankOperand = (): CheckOperand => ({ materialKey: "", sourceExcerpt: "", subject: "", metric: "", periodStart: "", periodEnd: "", periodType: "", currency: "", unit: "", basis: "", valueType: "", low: "", high: "", confirmed: false });

export function safeSourceUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null; }
  catch { return null; }
}
export async function contentDigest(value: string): Promise<string> {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, "0")).join("");
}
export async function evidenceMaterial(record: EvidenceRecord, securityCode: string): Promise<ResearchMaterial> {
  if (record.subject_type !== "stock" || record.subject_id !== securityCode || record.deleted) throw new Error("材料不属于当前股票或已删除。");
  const sourceUrl = safeSourceUrl(record.source_url);
  const version = await contentDigest(JSON.stringify([record.claim, record.source_title, record.source_url, record.source_date, record.updated_at, record.classification, record.confidence]));
  return { id: `evidence:${record.id}`, version, securityCode, title: record.source_title || "已有证据摘录", content: record.claim,
    sourceUrl, sourceKind: "evidence_excerpt", sourceHash: null, publishedAt: record.source_date, capturedAt: Date.now(),
    availability: record.claim.trim() ? "partial" : sourceUrl ? "link_only" : "unavailable",
    readRange: { pages: [], totalPages: null, truncated: false, ocr: false, description: `仅保存已有摘录，不代表读取原链接全文。分类：${record.classification}；置信度：${record.confidence}；记录更新：${record.updated_at}` } };
}
export async function reportPageMaterials(report: MyReport, result: ReportPageReadResult, securityCode: string, start: number, end: number): Promise<ResearchMaterial[]> {
  validateReportPageOcrResponse(result, report.id, report.file_sha256 || "", start, end);
  const description = JSON.stringify({ scope: result.scope, full_report_read: false, requested: result.requested, coverage: result.coverage, complete_requested_text: result.complete_requested_text, extraction: result.extraction ?? null });
  return Promise.all(result.items.map(async item => ({
    id: `report:${report.id}:page:${item.page}`, version: await contentDigest(JSON.stringify([result.file_sha256, item, result.extraction ?? null])),
    securityCode, title: `${report.title || report.name} · 第 ${item.page} 页`, content: item.status === "readable" ? item.text || "" : "",
    sourceUrl: safeSourceUrl(report.source_url), sourceKind: "report_pages" as const, sourceHash: result.file_sha256,
    publishedAt: report.publish_date || null, capturedAt: Date.now(),
    provenance: JSON.parse(JSON.stringify({ report: { id: report.id, title: report.title || report.name, source_url: report.source_url || null, file_sha256: result.file_sha256, imported_at: report.imported_at || null }, page_receipt: result, security_assignment: { code: securityCode, basis: "USER_CONFIRMED_FROM_ORIGINAL_PAGE", automatically_verified: false } })),
    availability: item.status === "readable" && item.text?.trim() ? "partial" as const : "unavailable" as const,
    readRange: { pages: item.status === "readable" ? [item.page] : [], totalPages: report.page_count ?? null, truncated: item.truncated === true, ocr: Boolean(result.extraction), description: `${item.status} / ${item.reason}；本次实际返回 ${item.returned_chars ?? 0}/${item.indexed_chars ?? 0} 字符。${description}` },
  })));
}
export function reportIdFromMaterial(material: ResearchMaterial): string | null {
  if (material.sourceKind !== "report_pages") return null;
  return /^report:(.*):page:\d+$/.exec(material.id)?.[1] || null;
}

// Exact decimal normalization: never compare IEEE-754 money values.
const SCALE = 12;
function decimal(value: string): bigint {
  const text = value.trim();
  if (!/^[+-]?\d{1,24}(?:\.\d{1,12})?$/.test(text)) throw new Error("数值须为普通十进制，最多 24 位整数、12 位小数；亏损须明确填负号。");
  const negative = text.startsWith("-");
  const [whole, fractional = ""] = text.replace(/^[+-]/, "").split(".");
  const result = BigInt(whole) * 10n ** BigInt(SCALE) + BigInt(fractional.padEnd(SCALE, "0"));
  return negative ? -result : result;
}
function money(value: string, unit: string): bigint {
  const multiplier = { "元": 1n, "万元": 10000n, "亿元": 100000000n }[unit];
  if (!multiplier) throw new Error("单位未知或不是可换算的元 / 万元 / 亿元。");
  return decimal(value) * multiplier;
}
function display(value: bigint): string {
  const sign = value < 0n ? "-" : "";
  const absolute = value < 0n ? -value : value;
  const digits = absolute.toString().padStart(SCALE + 1, "0");
  const fraction = digits.slice(-SCALE).replace(/0+$/, "");
  return sign + digits.slice(0, -SCALE) + (fraction ? `.${fraction}` : "");
}
function isDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
}
const excerptHasValue = (excerpt: string, value: string) => {
  const target = decimal(value); const absolute = target < 0n ? -target : target;
  // Check a number token, not a substring (1 must not match 11). Sign still needs
  // manual confirmation: Chinese loss language need not print a literal minus.
  const tokens = excerpt.replace(/[,，](?=\d{3}(?:\D|$))/g, "").match(/[+-]?\d+(?:\.\d+)?/g) || [];
  return tokens.some(token => { try { const n = decimal(token); return (n < 0n ? -n : n) === absolute; } catch { return false; } });
};

export function compareForecast(securityCode: string, mode: ComparisonMode, forecast: CheckOperand, comparison: CheckOperand, materials: ResearchMaterial[], allowUnitConversion = false): ResearchCalculation {
  const inputs: ResearchCalculationInput[] = [];
  const refused = (reason: string): ResearchCalculation => ({ kind: "interval_contains", inputs, formula: "", result: "不能比较", comparable: false, reason });
  try {
    if (mode !== "actual" && mode !== "revision") return refused("未知核对类型，不能比较。");
    for (const [index, operand] of [forecast, comparison].entries()) {
      const label = index === 0 ? "原预告" : mode === "actual" ? "实际业绩" : "修订预告";
      const material = materials.find(item => materialKey(item) === operand.materialKey);
      if (!material || material.securityCode !== securityCode || !material.content.trim() || ["link_only", "unavailable"].includes(material.availability)) return refused(`${label}缺少本轮已保存的实际原文 / 摘录；仅有链接不能计算。`);
      if (!operand.sourceExcerpt.trim() || !material.content.includes(operand.sourceExcerpt.trim())) return refused(`${label}的原文引句必须逐字来自所选材料。`);
      if (!operand.confirmed) return refused(`${label}仍为手工录入 / 待核；请核对原页表头、单位和符号后确认。`);
      if (operand.subject !== securityCode) return refused(`${label}证券主体未知或错股，不能比较。`);
      if (!operand.metric || !["归母净利润", "扣非归母净利润"].includes(operand.metric) || operand.currency !== "CNY"
        || !["consolidated", "parent"].includes(operand.basis) || !["annual", "YTD", "quarter"].includes(operand.periodType)
        || !isDate(operand.periodStart) || !isDate(operand.periodEnd) || operand.periodStart > operand.periodEnd) return refused(`${label}指标、期间、币种或合并口径尚未确认。`);
      const expected = index === 0 || mode === "revision" ? "forecast" : "actual";
      if (operand.valueType !== expected) return refused(`${label}预测 / 实际属性不匹配；修订预告不能当作实际业绩。`);
      const values = expected === "forecast" ? [operand.low, operand.high] : [operand.low];
      for (const [i, value] of values.entries()) {
        money(value, operand.unit);
        if (!excerptHasValue(operand.sourceExcerpt, value)) return refused(`${label}数值未出现在所选引句中；请保留数值、表头和单位再核对。`);
        inputs.push({ label: `${label}${expected === "forecast" ? `端点${i + 1}` : "值"}`, value: value.trim().replace(/^\+/, ""), unit: operand.unit, currency: operand.currency,
          period: `${operand.periodStart}/${operand.periodEnd}|${operand.periodType}`, subject: operand.subject, metric: operand.metric, basis: operand.basis,
          valueType: expected, materialKey: operand.materialKey, page: material.readRange.pages[0] ?? null, sourceExcerpt: operand.sourceExcerpt.trim(), confirmed: true });
      }
    }
    for (const key of ["subject", "metric", "periodStart", "periodEnd", "periodType", "currency", "basis"] as const) {
      if (forecast[key] !== comparison[key]) return refused(`比较口径不一致：${({ subject: "主体", metric: "指标", periodStart: "期间开始", periodEnd: "期间结束", periodType: "全年 / 累计 / 单季", currency: "币种", basis: "合并 / 母公司" })[key]}。`);
    }
    if (forecast.unit !== comparison.unit && !allowUnitConversion) return refused("原单位不一致；请核对原文并明确允许元 / 万元 / 亿元换算，或改为同单位材料。");
    const bounds = (operand: CheckOperand) => [money(operand.low, operand.unit), money(operand.high, operand.unit)].sort((a, b) => a < b ? -1 : a > b ? 1 : 0);
    const [low, high] = bounds(forecast);
    const note = "只检验手工确认输入的算式，不自动核实数字含义、审计质量或增长原因。";
    if (mode === "actual") {
      const actual = money(comparison.low, comparison.unit), within = actual >= low && actual <= high;
      return { kind: "interval_contains", inputs, comparable: true, unitConversionConfirmed: allowUnitConversion, formula: `${display(low)} ≤ ${display(actual)} ≤ ${display(high)}（统一为元，${forecast.currency}）`,
        result: within ? "实际值落在所选预告区间内" : "实际值未落在所选预告区间内", reason: note };
    }
    const [nextLow, nextHigh] = bounds(comparison);
    const overlap = nextLow <= high && low <= nextHigh;
    return { kind: "interval_contains", inputs, comparable: true, unitConversionConfirmed: allowUnitConversion, formula: `原预告 [${display(low)}, ${display(high)}]；修订预告 [${display(nextLow)}, ${display(nextHigh)}]（统一为元，${forecast.currency}）`,
      result: `两个预测区间${overlap ? "有重叠" : "不重叠"}；修订预告不是实际业绩，不能判断兑现`, reason: note };
  } catch (cause) { return refused(cause instanceof Error ? cause.message : "输入无效，不能计算。"); }
}

/** Replay the frozen manual worksheet. This validates the calculation, not the filing's truth. */
export function replayResearchCalculation(securityCode: string, calculation: ResearchCalculation, materials: ResearchMaterial[]): ResearchCalculation {
  if (calculation.kind !== "interval_contains" || ![3, 4].includes(calculation.inputs.length)) throw new Error("不支持的区间核对输入结构");
  const [a, b, c, d] = calculation.inputs;
  const sameDimensions = (left: ResearchCalculationInput, right: ResearchCalculationInput) =>
    (["unit", "currency", "period", "subject", "metric", "basis", "valueType", "materialKey", "page", "sourceExcerpt", "confirmed"] as const).every(key => left[key] === right[key]);
  if (!sameDimensions(a, b) || a.valueType !== "forecast" || (d && (!sameDimensions(c, d) || c.valueType !== "forecast")) || (!d && c.valueType !== "actual")) throw new Error("原区间端点或预测 / 实际属性不匹配");
  function operand(first: ResearchCalculationInput, second?: ResearchCalculationInput): CheckOperand {
    const match = /^(\d{4}-\d{2}-\d{2})\/(\d{4}-\d{2}-\d{2})\|(annual|YTD|quarter)$/.exec(first.period);
    if (!match) throw new Error("原期间格式无效");
    return { materialKey: first.materialKey, sourceExcerpt: first.sourceExcerpt, subject: first.subject, metric: first.metric,
      periodStart: match[1], periodEnd: match[2], periodType: match[3], currency: first.currency, unit: first.unit, basis: first.basis,
      valueType: first.valueType, low: first.value, high: second?.value || "", confirmed: first.confirmed };
  }
  return compareForecast(securityCode, d ? "revision" : "actual", operand(a, b), operand(c, d), materials, calculation.unitConversionConfirmed === true);
}
