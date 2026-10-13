/** Local-only table parsing. Never sends file contents or personal columns to a model/provider. */
export const MAX_IMPORT_BYTES = 64 * 1024;
export const MAX_IMPORT_ROWS = 500;
export const MAX_WATCHLIST_CODES = 50;
export type ImportRow = { row: number; code: string | null; market: string | null; status: "new" | "existing" | "duplicate" | "invalid"; reason: string };
export type ImportPreview = { rows: ImportRow[]; additions: string[]; next: string[]; errors: string[]; baseCodes: string[]; baseEtag: string | null };
const CODE_HEADERS = new Set(["code", "symbol", "ticker", "代码", "证券代码", "股票代码"]);
const MARKET_HEADERS = new Set(["market", "exchange", "市场", "交易所"]);
const normalHeader = (s: string) => s.trim().toLowerCase();

function cells(raw: string): string[][] {
  // Only unquoted separators in the first record determine the table dialect.
  let inQuotes = false; let delimiter = ",";
  for (let i = 0; i < raw.length; i++) {
    if (raw[i] === '"') { if (inQuotes && raw[i + 1] === '"') i++; else inQuotes = !inQuotes; }
    else if (!inQuotes && raw[i] === "\t") { delimiter = "\t"; break; }
    else if (!inQuotes && (raw[i] === "\n" || raw[i] === "\r")) break;
  }
  const rows: string[][] = []; let row: string[] = []; let cell = ""; let quoted = false; let endedQuote = false;
  const pushCell = () => { row.push(cell.trim()); cell = ""; endedQuote = false; };
  const pushRow = () => { pushCell(); if (row.some(Boolean)) rows.push(row); row = []; if (rows.length > MAX_IMPORT_ROWS + 1) throw new Error(`最多预览 ${MAX_IMPORT_ROWS} 行`); };
  for (let i = 0; i < raw.length; i++) {
    const c = raw[i];
    if (quoted) {
      if (c === '"') { if (raw[i + 1] === '"') { cell += '"'; i++; } else { quoted = false; endedQuote = true; } }
      else cell += c;
    } else if (c === '"') {
      if (cell.trim() || endedQuote) throw new Error("CSV 引号格式无效");
      cell = ""; quoted = true;
    } else if (c === delimiter) pushCell();
    else if (c === "\n" || c === "\r") { if (c === "\r" && raw[i + 1] === "\n") i++; pushRow(); }
    else { if (endedQuote && c.trim()) throw new Error("CSV 引号后有额外内容"); cell += c; }
  }
  if (quoted) throw new Error("CSV 引号未闭合");
  if (cell || row.length) pushRow();
  return rows;
}
function inferredMarket(code: string): string | null {
  if (/^(600|601|603|605|688|689)\d{3}$/.test(code)) return "SH";
  if (/^(000|001|002|003|300|301)\d{3}$/.test(code)) return "SZ";
  if (/^(?:[48]\d{5}|920\d{3})$/.test(code)) return "BJ";
  return null;
}
function canonicalMarket(raw: string): string | null {
  return ({ SH: "SH", SSE: "SH", XSHG: "SH", 沪: "SH", 上海: "SH", SZ: "SZ", SZSE: "SZ", XSHE: "SZ", 深: "SZ", 深圳: "SZ", BJ: "BJ", BSE: "BJ", 北: "BJ", 北京: "BJ" } as Record<string, string>)[raw.trim().toUpperCase()] ?? null;
}
function identity(raw: string, declared?: string): { code: string; market: string } | null {
  const token = raw.trim().toUpperCase();
  const match = /^(?:(SH|SZ|BJ)[:.]?)?(\d{6})(?:\.(SH|SZ|BJ))?$/.exec(token);
  if (!match) return null;
  const code = match[2], market = inferredMarket(code);
  if (!market || (match[1] && match[1] !== market) || (match[3] && match[3] !== market)) return null;
  if (declared?.trim() && canonicalMarket(declared) !== market) return null;
  return { code, market };
}
export function previewWatchlistImport(raw: string, existing: string[], etag: string | null): ImportPreview {
  const result: ImportPreview = { rows: [], additions: [], next: [...existing], errors: [], baseCodes: [...existing], baseEtag: etag };
  if (new TextEncoder().encode(raw).length > MAX_IMPORT_BYTES) { result.errors.push("文件/文本超过 64 KiB 上限"); return result; }
  let table: string[][];
  try { table = cells(raw.replace(/^\uFEFF/, "")); } catch (e) { result.errors.push((e as Error).message); return result; }
  if (!table.length) { result.errors.push("请输入代码或带代码表头的 CSV/TSV 表格"); return result; }
  const headers = table[0].map(normalHeader);
  const codeIndexes = headers.flatMap((h, i) => CODE_HEADERS.has(h) ? [i] : []);
  const marketIndexes = headers.flatMap((h, i) => MARKET_HEADERS.has(h) ? [i] : []);
  if (codeIndexes.length > 1 || marketIndexes.length > 1) { result.errors.push("代码/市场列不唯一，请保留一列"); return result; }
  const hasHeader = codeIndexes.length === 1;
  if (!hasHeader && table.some(r => r.length !== 1)) { result.errors.push("多列表格必须有代码表头（代码 / code / symbol）"); return result; }
  const body = hasHeader ? table.slice(1) : table;
  if (!body.length || body.length > MAX_IMPORT_ROWS) { result.errors.push(`需要 1–${MAX_IMPORT_ROWS} 行数据`); return result; }
  const seen = new Set<string>(); const current = new Set(existing);
  body.forEach((row, index) => {
    const parsed = hasHeader && row.length !== headers.length ? null : identity(row[hasHeader ? codeIndexes[0] : 0] ?? "", marketIndexes.length ? row[marketIndexes[0]] : undefined);
    const item: ImportRow = { row: index + (hasHeader ? 2 : 1), code: parsed?.code ?? null, market: parsed?.market ?? null, status: "invalid", reason: "代码格式、A股市场或列数不匹配；不会导入" };
    if (parsed) {
      item.status = current.has(parsed.code) ? "existing" : seen.has(parsed.code) ? "duplicate" : "new";
      item.reason = item.status === "existing" ? "已在自选中" : item.status === "duplicate" ? "本表重复" : "新增；代码格式校验通过，上市身份未经在线核验";
      seen.add(parsed.code);
      if (item.status === "new") result.additions.push(parsed.code);
    }
    result.rows.push(item);
  });
  result.next.push(...result.additions);
  if (result.rows.some(r => r.status === "invalid")) result.errors.push("存在无效行，请修正后重新预览；不会部分导入");
  if (result.next.length > MAX_WATCHLIST_CODES) result.errors.push(`合并后 ${result.next.length} 只，超过自选上限 ${MAX_WATCHLIST_CODES}；请删减后重新预览`);
  return result;
}
export function importPreviewCurrent(preview: ImportPreview, codes: string[], etag: string | null): boolean {
  return preview.baseEtag === etag && JSON.stringify(preview.baseCodes) === JSON.stringify(codes);
}
