import { useEffect, useRef, useState } from "react";
import { request } from "@/lib/api";
import { parseBasisReceipt, ReviewResponseError, type BasisReceipt as Receipt } from "@/lib/personalReviewValidation";
export function PriceBasisImport({ onSaved }: { onSaved: () => void }) {
  const [raw, setRaw] = useState("");
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  async function preview(file: File | undefined) {
    if (uncertain) return;
    const token = ++generation.current;
    setRaw(""); setReceipt(null); setError("");
    if (!file) return;
    if (file.size > 1000000) { setError("采集文件不能超过 1 MB"); return; }
    setBusy(true);
    try {
      const text = await file.text();
      if (token !== generation.current) return;
      const value = await request<unknown>("/personal-review/price-basis/preview", "POST", { raw_json: text });
      const result = await parseBasisReceipt(value, text);
      if (token === generation.current) { setRaw(text); setReceipt(result); }
    } catch (e) { if (token === generation.current) setError(e instanceof Error ? e.message : "因子预览失败"); }
    finally { if (token === generation.current) setBusy(false); }
  }
  async function archive() {
    if (busy || uncertain || !receipt) return;
    const token = generation.current;
    setBusy(true); setError("");
    try {
      const saved = await request<unknown>("/personal-review/price-basis/archive", "POST", { raw_json: raw });
      await parseBasisReceipt(saved, raw);
      if (token === generation.current) { setRaw(""); setReceipt(null); onSaved(); }
    } catch (e) { if (token === generation.current) { if (e instanceof ReviewResponseError || (e as { status?: number })?.status === 0) setUncertain(true); setError(e instanceof Error ? e.message : "因子归档失败"); } }
    finally { if (token === generation.current) setBusy(false); }
  }
  async function reconcile() {
    if (!receipt || busy) return;
    const token = generation.current; setBusy(true); setError("");
    try {
      const value = await request<unknown>(`/personal-review/price-basis/receipts/${receipt.capture_sha256}`);
      if (value !== null) await parseBasisReceipt(value, raw);
      if (token === generation.current) { setUncertain(false); if (value !== null) { setRaw(""); setReceipt(null); onSaved(); } }
    } catch (e) { if (token === generation.current) setError(e instanceof Error ? e.message : "归档结果仍无法核验"); }
    finally { if (token === generation.current) setBusy(false); }
  }
  return <details className="text-sm"><summary className="cursor-pointer">本地价格基准证据导入</summary><div className="space-y-2 py-2">
    <p>仅接受公开市场的因子采集 JSON（personal-review-adjustment-capture.v1），绑定已有不可变价格快照、股票、供应商版本和调整基准。先预览，再显式归档；不会抓取行情、改交易或导入旧 VA 数据。</p>
    <p>按采集声明的复权因子计算日线内部区间下界，不证明供应商经济口径正确，也不代表精确持有期 MFE/MAE、总回报或事前已知事实。</p>
    <label>选择公开价格因子文件<input type="file" accept=".json,application/json" disabled={busy || uncertain} onChange={e => void preview(e.target.files?.[0])} className="block w-full text-xs" /></label>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {uncertain && <p role="status">归档结果待核验，已停用重复提交。<button type="button" disabled={busy} onClick={() => void reconcile()}>重新核验归档结果</button></p>}
    {busy && <p role="status">正在核验本地价格证据…</p>}
    {receipt && <div className="space-y-1 break-all"><p>{receipt.code} · {receipt.provider_id} / {receipt.provider_revision}</p><p>{receipt.from} – {receipt.through} · {receipt.sessions} 个完整会话 · 基准 {receipt.adjustment_basis_id}</p><p className="text-xs">内容哈希 {receipt.capture_sha256}</p><button disabled={busy || uncertain} type="button" className="rounded border border-input px-3 py-2 disabled:opacity-50" onClick={() => void archive()}>确认归档公开价格因子</button></div>}
  </div></details>;
}
