import { WatchlistOcr } from "./WatchlistOcr";
import { useEffect, useRef, useState } from "react";
import { importPreviewCurrent, MAX_IMPORT_BYTES, previewWatchlistImport, type ImportPreview } from "@/lib/watchlistImport";

export function WatchlistImport({ codes, etag, disabled, onApply }: {
  codes: string[]; etag: string | null; disabled: boolean; onApply: (codes: string[]) => Promise<boolean>;
}) {
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [message, setMessage] = useState("");
  const [reading, setReading] = useState(false);
  const [applying, setApplying] = useState(false);
  const generation = useRef(0); const applyingRef = useRef(false);
  useEffect(() => () => { generation.current++; }, []);
  const invalidate = () => { generation.current++; setPreview(null); setMessage(""); setReading(false); };
  const current = preview && importPreviewCurrent(preview, codes, etag);
  const apply = async () => {
    if (!preview || !current || disabled || applyingRef.current || preview.errors.length || !preview.additions.length) return;
    applyingRef.current = true; setApplying(true);
    try {
      if (await onApply(preview.next)) { setText(""); setPreview(null); setMessage(`已添加 ${preview.additions.length} 只自选`); }
      else { setPreview(null); setMessage("未确认保存成功。输入已保留，请重新读取自选并预览后重试。"); }
    } catch { setPreview(null); setMessage("保存失败。输入已保留，请重新读取自选并预览后重试。");
    } finally { applyingRef.current = false; setApplying(false); }
  };
  return <details className="mt-4 rounded-lg border border-border p-3" data-testid="watchlist-import">
    <summary className="cursor-pointer text-sm font-medium">从表格导入（本机预览）</summary>
    <p className="my-2 text-xs text-muted-foreground">仅支持 A 股代码。CSV/TSV 多列表格须含“代码 / code / symbol”表头，可附“市场 / market / exchange”列；无表头时每行一个代码。最多 64 KiB、500 行，合并自选最多 50 只。其他列不会保存或发送到模型。截图请使用下方独立的本地 OCR 步骤，不会自动上传图片。</p>
    <input type="file" accept=".csv,.tsv,.txt" aria-label="选择本机自选表格" disabled={disabled || applying} onChange={async e => {
      const file = e.target.files?.[0]; e.target.value = ""; invalidate(); setText("");
      if (!file) return;
      if (!/\.(csv|tsv|txt)$/i.test(file.name) || file.size > MAX_IMPORT_BYTES) { setMessage("请选择不超过 64 KiB 的 CSV/TSV/TXT 文件"); return; }
      const run = generation.current; setReading(true);
      try { const value = await file.text(); if (run === generation.current) setText(value); }
      catch { if (run === generation.current) setMessage("文件读取失败，请重试"); }
      finally { if (run === generation.current) setReading(false); }
    }} />
    <textarea aria-label="自选导入表格文本" value={text} disabled={disabled || applying} rows={4} onChange={e => { invalidate(); setText(e.target.value); }} placeholder={'代码,市场,名称\n600519,SH,贵州茅台\n000858,SZ,五粮液'} className="my-2 w-full rounded border border-border bg-transparent p-2 text-sm" />
    <div className="flex gap-3">
      <button type="button" disabled={disabled || applying || reading} onClick={() => { setMessage(""); setPreview(previewWatchlistImport(text, codes, etag)); }} className="min-h-11 text-primary disabled:opacity-50">预览导入</button>
      <button type="button" disabled={applying} onClick={() => { invalidate(); setText(""); }} className="min-h-11">取消 / 清空</button>
    </div>
    {reading && <p role="status">正在本机读取文件…</p>}
    {message && <p role="status">{message}</p>}
    {preview && <div>
      <p className="text-sm">新增 {preview.additions.length} 只；已存在/重复 {preview.rows.filter(r => r.status === "existing" || r.status === "duplicate").length} 行；无效 {preview.rows.filter(r => r.status === "invalid").length} 行</p>
      {!current && <p role="alert">自选版本已变化，请重新预览。</p>}
      {preview.errors.map(error => <p key={error} role="alert" className="text-sm text-destructive">{error}</p>)}
      <ul className="my-2 max-h-64 overflow-auto text-xs" aria-label="导入逐行预览">{preview.rows.map(row => <li key={row.row}>第 {row.row} 行：{row.market ?? "—"} {row.code ?? "无效身份"} · {row.reason}</li>)}</ul>
      <button type="button" onClick={() => void apply()} disabled={disabled || applying || !current || !!preview.errors.length || !preview.additions.length} className="min-h-11 rounded bg-primary/15 px-3 text-primary disabled:opacity-50">{applying ? "保存中…" : `确认添加 ${preview.additions.length} 只`}</button>
    </div>}
    <WatchlistOcr disabled={disabled || applying || reading} onText={value => { invalidate(); setText(value); setMessage("OCR 文字已放入编辑框；请继续核对并点击预览，尚未添加自选。"); }} />
  </details>;
}
