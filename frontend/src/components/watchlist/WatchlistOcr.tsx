import { useEffect, useRef, useState } from "react";
import { MAX_OCR_IMAGE_BYTES, recognizeWatchlistImage, type OcrResult } from "@/lib/watchlistOcr";
export function WatchlistOcr({ disabled, onText }: { disabled: boolean; onText: (text: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState("eng");
  const [result, setResult] = useState<OcrResult | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef<{ id: number; controller: AbortController } | null>(null);
  const sequence = useRef(0);
  const cancel = () => { sequence.current++; active.current?.controller.abort(); active.current = null; setBusy(false); };
  useEffect(() => () => { sequence.current++; active.current?.controller.abort(); }, []);
  const reset = () => { cancel(); setResult(null); setText(""); setError(""); };
  const recognize = async () => {
    if (!file || disabled || active.current) return;
    const id = ++sequence.current; const controller = new AbortController(); active.current = { id, controller };
    setBusy(true); setResult(null); setText(""); setError("");
    try { const data = await recognizeWatchlistImage(file, language, controller.signal); if (sequence.current === id) { setResult(data); setText(data.text); } }
    catch (e) { if (sequence.current === id) setError(e instanceof Error ? e.message : "本地 OCR 失败，请重试"); }
    finally { if (sequence.current === id) { active.current = null; setBusy(false); } }
  };
  return <section className="mt-3 border-t border-border pt-3" data-testid="watchlist-ocr">
    <h4 className="text-sm font-medium">截图转文字（可选）</h4>
    <p className="my-2 text-xs text-muted-foreground">点击“本地 OCR 识别”才会把所选图片发送到当前 Vibe 后端（/api/local-ocr/preview），由本地 Tesseract 处理，不发送给模型或第三方、不保存原图。请先裁去持仓数量、金额和其他私人信息。OCR 可能错读代码、漏行；识别后必须逐行核对，只保留代码/市场列，再预览和确认添加。</p>
    <input type="file" accept=".png,.jpg,.jpeg" aria-label="选择待识别自选截图" disabled={disabled || busy} onChange={e => {
      reset(); const next = e.target.files?.[0] ?? null; e.target.value = "";
      if (next && (!/\.(png|jpe?g)$/i.test(next.name) || !next.size || next.size > MAX_OCR_IMAGE_BYTES)) { setFile(null); setError("仅支持不超过 8 MiB 的 PNG/JPEG 图片"); } else setFile(next);
    }} />
    <label className="block text-xs">识别语言 <select aria-label="截图识别语言" value={language} disabled={disabled || busy} onChange={e => { reset(); setLanguage(e.target.value); }}><option value="eng">英文 / 数字</option><option value="chi_sim+eng">简体中文 + 英文（需本地语言包）</option></select></label>
    <div className="flex gap-3"><button type="button" className="min-h-11 text-primary disabled:opacity-50" disabled={disabled || busy || !file} onClick={() => void recognize()}>{busy ? "本地识别中…" : "本地 OCR 识别"}</button><button type="button" className="min-h-11" onClick={() => { reset(); setFile(null); }}>取消识别 / 清空</button></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {result && <div>
      <p className="text-xs" role="status">{result.status === "OCR_NO_TEXT" ? "未识别到文字" : "OCR 未核验；不是已确认的股票身份"} · {result.engine} · {result.language}</p>
      <p className="break-all text-[10px] text-muted-foreground">来源 SHA256：{result.sourceSha256}；原始 OCR 文本 SHA256：{result.textSha256}（编辑后不再代表下方文本）</p>
      {result.limitations.map((line, i) => <p className="text-xs text-warning" key={i}>{line}</p>)}
      <textarea aria-label="核对并编辑截图识别文字" rows={5} className="my-2 w-full rounded border border-border bg-transparent p-2 text-sm" value={text} disabled={disabled} onChange={e => setText(e.target.value)} />
      <button type="button" disabled={disabled || !text.trim() || new TextEncoder().encode(text).length > 65536} className="min-h-11 text-primary disabled:opacity-50" onClick={() => onText(text)}>使用核对后的文字替换上方导入编辑框</button>
    </div>}
  </section>;
}
