function strictTimestamp(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-](\d{2}):(\d{2}))$/.exec(value);
  if (!match || Number(match[1].slice(0, 4)) < 1 || Number(match[2]) > 23 || Number(match[3]) > 59 || Number(match[4]) > 59) return false;
  if (match[5] !== "Z" && (Number(match[6]) > 14 || Number(match[7]) > 59 || (Number(match[6]) === 14 && Number(match[7]) !== 0))) return false;
  const day = new Date(`${match[1]}T00:00:00Z`);
  return Number.isFinite(day.getTime()) && day.toISOString().slice(0, 10) === match[1] && Number.isFinite(Date.parse(value));
}

export function parseLocalReportIdentity(value: unknown, reportId: string, extension: string): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("OCR 原文件身份无效");
  const result = value as Record<string, unknown>;
  if (Object.keys(result).sort().join("|") !== ["report_id", "file_sha256", "extension", "writes"].sort().join("|")
    || result.report_id !== reportId || result.extension !== extension || result.writes !== 0
    || typeof result.file_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(result.file_sha256)) throw new Error("OCR 原文件身份不匹配");
  return result.file_sha256;
}

export interface LocalReportOcrReceipt {
  schema_version: "local_ocr_report_receipt.v1"; report_id: string; file_sha256: string;
  status: "SEARCHABLE"; indexed_at: string;
  extraction: { schema_version: "local_ocr_preview.v1"; status: "OCR_UNVERIFIED"; source_sha256: string;
    engine: "local-tesseract"; language: "eng" | "chi_sim+eng"; source_truth_verified: false; limitations: string[];
    pages: { page_number: number; source_sha256: string; image_sha256: string; text_sha256: string; mean_word_confidence: number | null }[] };
}
export function parseLocalReportOcrReceipt(value: unknown, reportId: string, sourceHash: string, language: string): LocalReportOcrReceipt {
  const object = (v: unknown): Record<string, unknown> => { if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error("OCR 回执格式无效"); return v as Record<string, unknown>; };
  const keys = (v: Record<string, unknown>, expected: string[]) => { if (Object.keys(v).sort().join("|") !== [...expected].sort().join("|")) throw new Error("OCR 回执字段无效"); };
  const hash = (v: unknown) => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
  const receipt = object(value), extraction = object(receipt.extraction);
  keys(receipt, ["schema_version", "report_id", "file_sha256", "status", "indexed_at", "extraction"]);
  keys(extraction, ["schema_version", "status", "source_sha256", "engine", "language", "source_truth_verified", "limitations", "pages"]);
  if (receipt.schema_version !== "local_ocr_report_receipt.v1" || receipt.report_id !== reportId || receipt.file_sha256 !== sourceHash || !hash(sourceHash)
    || receipt.status !== "SEARCHABLE" || !strictTimestamp(receipt.indexed_at)
    || extraction.schema_version !== "local_ocr_preview.v1" || extraction.status !== "OCR_UNVERIFIED" || extraction.source_sha256 !== sourceHash
    || extraction.engine !== "local-tesseract" || extraction.language !== language || extraction.source_truth_verified !== false
    || !Array.isArray(extraction.limitations) || !extraction.limitations.length || extraction.limitations.length > 10 || extraction.limitations.some(v => typeof v !== "string" || v.length > 500)
    || !Array.isArray(extraction.pages) || !extraction.pages.length || extraction.pages.length > 12) throw new Error("OCR 回执身份或状态不匹配");
  extraction.pages.forEach((value, index) => {
    const page = object(value), confidence = page.mean_word_confidence;
    keys(page, ["page_number", "source_sha256", "image_sha256", "text_sha256", "mean_word_confidence"]);
    if (page.page_number !== index + 1 || page.source_sha256 !== sourceHash || !hash(page.image_sha256) || !hash(page.text_sha256)
      || (confidence !== null && (typeof confidence !== "number" || !Number.isFinite(confidence) || confidence < 0 || confidence > 100))) throw new Error("OCR 页引用回执无效");
  });
  return value as LocalReportOcrReceipt;
}

export function validateReportPageOcrResponse(value: unknown, reportId: string, sourceHash: string, pageFrom = 1, pageTo = pageFrom): void {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("页读取回执无效");
  const result = value as Record<string, unknown>;
  if (result.report_id !== reportId || result.file_sha256 !== sourceHash || result.scope !== "INDEXED_PAGE_TEXT_ONLY" || result.full_report_read !== false
    || !Array.isArray(result.items) || result.items.length > 200 || !result.coverage || typeof result.coverage !== "object" || Array.isArray(result.coverage)
    || !Array.isArray(result.requested) || result.requested.length > 200 || result.requested.some(v => !Number.isInteger(v) || v < 1 || v > 1000000)
    || typeof result.returned_chars !== "number" || !Number.isInteger(result.returned_chars) || result.returned_chars < 0 || result.returned_chars > 12000) throw new Error("页读取来源或结构无效");
  if (result.requested.length !== pageTo - pageFrom + 1 || result.requested.some((v, index) => v !== pageFrom + index) || result.items.length !== result.requested.length) throw new Error("页读取范围不匹配");
  const statuses = ["readable", "omitted", "invalid", "unreadable", "error"];
  const coverage = result.coverage as Record<string, unknown>;
  if (Object.keys(coverage).sort().join("|") !== [...statuses].sort().join("|")) throw new Error("页覆盖字段无效");
  for (const status of statuses) {
    const pages = coverage[status];
    if (!Array.isArray(pages) || pages.length > 200 || pages.some(v => !Number.isInteger(v) || v < 1 || v > 1000000)) throw new Error("页覆盖值无效");
  }
  for (const [index, value] of result.items.entries()) {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("页内容无效");
    const item = value as Record<string, unknown>;
    if (!Number.isInteger(item.page) || item.page !== result.requested[index] || !statuses.includes(String(item.status)) || typeof item.reason !== "string" || !/^[A-Z_]+$/.test(item.reason)
      || (item.text !== undefined && (typeof item.text !== "string" || item.text.length > 12000))
      || (item.truncated !== undefined && typeof item.truncated !== "boolean")
      || [item.returned_chars, item.indexed_chars].some(v => v !== undefined && (typeof v !== "number" || !Number.isInteger(v) || v < 0))) throw new Error("页内容字段无效");
  }
  for (const status of statuses) {
    const actual = result.items.filter(value => (value as Record<string, unknown>).status === status).map(value => (value as Record<string, unknown>).page);
    if (JSON.stringify(actual) !== JSON.stringify(coverage[status])) throw new Error("页覆盖与内容不一致");
  }
  if (result.extraction === null || result.extraction === undefined) return;
  const extraction = result.extraction as Record<string, unknown>;
  if (!extraction || typeof extraction !== "object" || !["eng", "chi_sim+eng"].includes(String(extraction.language))) throw new Error("OCR 页来源无效");
  // Reuse the exact saved-receipt metadata guard; no untrusted metadata reaches JSX.
  parseLocalReportOcrReceipt({ schema_version: "local_ocr_report_receipt.v1", report_id: reportId, file_sha256: sourceHash,
    status: "SEARCHABLE", indexed_at: "2000-01-01T00:00:00Z", extraction }, reportId, sourceHash, String(extraction.language));
}

export function parseLocalOcrCapability(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("OCR 能力回执无效");
  const result = value as Record<string, unknown>;
  if (typeof result.image !== "boolean" || typeof result.pdf !== "boolean" || result.automatic_language_fallback !== false
    || result.engine !== "local-tesseract" || result.status !== (result.image ? "AVAILABLE" : "DEPENDENCY_UNAVAILABLE")
    || (result.pdf && !result.image)
    || !["ENGLISH_LANGUAGE_UNAVAILABLE", "INSTALLED_QUALITY_NOT_VERIFIED"].includes(String(result.english_language_status))
    || (result.image && result.english_language_status !== "INSTALLED_QUALITY_NOT_VERIFIED")
    || !["CHINESE_LANGUAGE_UNAVAILABLE", "INSTALLED_QUALITY_NOT_VERIFIED"].includes(String(result.chinese_language_status))) throw new Error("OCR 能力或语言回执不一致");
  return { image: result.image, pdf: result.pdf, chinese_language_status: String(result.chinese_language_status) };
}
