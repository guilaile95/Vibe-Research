import { request } from "./api.ts";
export const MAX_OCR_IMAGE_BYTES = 8 * 1024 * 1024;
export type OcrResult = { status: "OCR_UNVERIFIED" | "OCR_NO_TEXT"; text: string; sourceSha256: string; imageSha256: string; textSha256: string; engine: string; language: string; limitations: string[] };
const digest = (s: unknown): s is string => typeof s === "string" && /^[a-f0-9]{64}$/.test(s);
export function parseOcrResult(value: unknown): OcrResult {
  if (!value || typeof value !== "object") throw new Error("OCR 回执无效");
  const v = value as Record<string, unknown>;
  const page = Array.isArray(v.pages) && v.pages.length === 1 ? v.pages[0] : null;
  if (v.schema_version !== "local_ocr_preview.v1" || !page || typeof page !== "object" || Array.isArray(page) || page.page_number !== 1 || typeof page.text !== "string" || new TextEncoder().encode(page.text).length > 65536
      || !["OCR_UNVERIFIED", "OCR_NO_TEXT"].includes(String(v.status)) || v.source_truth_verified !== false
      || (v.status === "OCR_NO_TEXT") !== !page.text.trim()
      || !digest(v.source_sha256) || page.source_sha256 !== v.source_sha256 || !digest(page.image_sha256) || !digest(page.text_sha256)
      || v.engine !== "local-tesseract" || !["eng", "chi_sim+eng"].includes(String(v.language))
      || !Array.isArray(v.limitations) || v.limitations.length > 30 || v.limitations.some(x => typeof x !== "string" || x.length > 1000)) throw new Error("OCR 回执无效，请重新识别；不会导入");
  return { status: v.status as OcrResult["status"], text: page.text, sourceSha256: v.source_sha256, imageSha256: page.image_sha256, textSha256: page.text_sha256, engine: String(v.engine), language: String(v.language), limitations: v.limitations as string[] };
}
export async function recognizeWatchlistImage(file: File, language: string, signal: AbortSignal): Promise<OcrResult> {
  const extension = /\.(png|jpe?g)$/i.exec(file.name)?.[0].toLowerCase();
  if (!extension || file.size <= 0 || file.size > MAX_OCR_IMAGE_BYTES || !["eng", "chi_sim+eng"].includes(language)) throw new Error("仅支持不超过 8 MiB 的 PNG/JPEG 图片");
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (signal.aborted) throw new DOMException("Aborted", "AbortError");
  // Server also validates signature/size; the original file is never persisted by this flow.
  if (bytes.length !== file.size) throw new Error("图片读取不完整");
  const sourceHash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))).map(b => b.toString(16).padStart(2, "0")).join("");
  if (signal.aborted) throw new DOMException("Aborted", "AbortError");
  let binary = "";
  for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
  let value: unknown;
  try {
    value = await request<unknown>("/local-ocr/preview", "POST", { content_b64: btoa(binary), extension, language, confirm_local_processing: true }, { signal });
  } catch (error) {
    if (error instanceof Error && error.message.includes("CHINESE_LANGUAGE_UNAVAILABLE")) throw new Error("当前本地 OCR 未安装简体中文语言包，无法识别中文；不会自动改用英文。请保留图片并手动输入，或自行配置本地语言包后重试。");
    throw error;
  }
  const result = parseOcrResult(value);
  const textHash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(result.text)))).map(b => b.toString(16).padStart(2, "0")).join("");
  if (signal.aborted) throw new DOMException("Aborted", "AbortError");
  if (result.language !== language || result.textSha256 !== textHash) throw new Error("OCR 语言或文字哈希回执不一致；不会导入");
  if (result.sourceSha256 !== sourceHash || result.imageSha256 !== sourceHash) throw new Error("OCR 回执与所选图片不一致；不会导入");
  return result;
}
