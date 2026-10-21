import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { request } from "@/lib/api";
import { annotationPlacement, type AnnotationContext, type ResearchAnnotation } from "@/lib/researchAnnotations";

/** Parent key remounts on stock/window/content/receipt change; late reads and saves are ignored. */
export function ResearchAnnotationPanel({ code, context, selectedDate, dates }: {
  code: string; context: AnnotationContext | null; selectedDate: string | null; dates: string[];
}) {
  const [enabled, setEnabled] = useState(false);
  const [rows, setRows] = useState<ResearchAnnotation[]>([]);
  const [text, setText] = useState("");
  const [price, setPrice] = useState("");
  const [linkKind, setLinkKind] = useState<"" | "evidence" | "thesis">("");
  const [linkId, setLinkId] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [epoch, setEpoch] = useState(0);
  const alive = useRef(true);
  const saving = useRef(false);
  const generation = useRef(0);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    generation.current += 1;
    setText(""); setPrice(""); setLinkKind(""); setLinkId(""); setStatus(""); setError("");
  }, [selectedDate]);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    const controller = new AbortController();
    setLoading(true); setError(""); setRows([]);
    void request<{records: ResearchAnnotation[]}>(`/research-annotations?code=${encodeURIComponent(code)}`, "GET", undefined, { signal: controller.signal })
      .then((data) => { if (active) setRows(data.records.filter((r) => r.code === code)); })
      .catch(() => { if (active) setError("标注读取失败；不能据此认为没有保存记录。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [enabled, code, epoch]);
  const validDate = !!context && !!selectedDate && dates.includes(selectedDate);
  const validPrice = price.trim() === "" || Number.isFinite(Number(price));
  async function save() {
    if (saving.current || !validDate || !text.trim() || text.length > 2000 || !validPrice || (linkKind && !linkId.trim())) return;
    saving.current = true; setBusy(true); setError(""); setStatus("");
    const version = generation.current;
    try {
      const saved = await request<ResearchAnnotation>("/research-annotations", "POST", {
        context, date: selectedDate, text: text.trim(), price: price.trim() === "" ? null : Number(price),
        link_kind: linkKind || null, link_id: linkKind ? linkId.trim() : null,
      });
      if (!alive.current) return;
      setEpoch((n) => n + 1);
      if (version === generation.current) { setText(""); setStatus(`已保存 ${saved.date} 的独立标注；正在回读归档。`); }
    } catch {
      if (alive.current && version === generation.current) setError("保存结果未确认。请先重新读取标注，避免重复保存；若快照失效，请重新加载日 K 线。输入已保留。");
    } finally {
      saving.current = false;
      if (alive.current) setBusy(false);
    }
  }
  return <section className="space-y-2 text-xs" aria-label="持久研究标注">
    <button type="button" className="rounded border px-3 py-2" aria-expanded={enabled} onClick={() => setEnabled(!enabled)}>{enabled ? "隐藏手工研究标注" : "手工研究标注"}</button>
    {enabled && <div className="space-y-3 rounded border border-border p-3">
      <p>独立研究笔记，只追加保存；不会修改正式 Thesis、证据或交易。关联只引用保存时的已有版本。归档上限共 1000 条。</p>
      {!context && <p role="status">缺少可核对的行情快照，暂不能保存。请重新加载日 K 线；旧标注仍可读取。</p>}
      {context && <p className="text-muted-foreground">当前保存凭据到期：{context.expires_at}；服务重启也会失效，届时请重新加载日 K 线。已存笔记不受影响。</p>}
      <p>选中日期：{selectedDate ?? "请先点击 K 线或使用检查器选择日期"}。仅精确匹配本快照，不移动到最近交易日。</p>
      {selectedDate && !validDate && <p role="status">所选日期不在已核对快照中，不能保存。</p>}
      <label className="block">笔记（最多 2000 字）<textarea className="block w-full rounded border bg-background p-2" maxLength={2000} value={text} disabled={busy} onChange={(e) => setText(e.target.value)} /></label>
      <label className="block">参考价格（可选，不是交易指令）<input className="ml-2 rounded border bg-background p-2" type="number" step="any" value={price} disabled={busy} onChange={(e) => setPrice(e.target.value)} /></label>
      <label className="block">关联已有记录（可选）<select className="ml-2 rounded border bg-background p-2" value={linkKind} disabled={busy} onChange={(e) => setLinkKind(e.target.value as typeof linkKind)}><option value="">无</option><option value="evidence">证据</option><option value="thesis">Thesis</option></select></label>
      {linkKind && <label className="block">同股记录 ID<input className="ml-2 rounded border bg-background p-2" maxLength={100} value={linkId} disabled={busy} onChange={(e) => setLinkId(e.target.value)} /></label>}
      <button type="button" className="rounded border px-3 py-2 disabled:opacity-50" disabled={busy || !validDate || !text.trim() || !validPrice || (!!linkKind && !linkId.trim())} onClick={() => void save()}>{busy ? "保存中…" : "追加保存标注"}</button>
      {status && <p role="status">{status}</p>}{error && <p role="alert">{error}</p>}
      <button type="button" className="ml-2 rounded border px-3 py-2" disabled={loading || busy} onClick={() => setEpoch((n) => n + 1)}>重新读取标注</button>
      {loading ? <p role="status">读取标注中…</p> : <div className="overflow-x-auto"><table className="w-full text-left"><caption>已保存研究标注（{rows.length} 条）</caption><thead><tr><th scope="col">日期与匹配</th><th scope="col">笔记</th><th scope="col">快照与关联</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id} className="border-b align-top" data-testid="research-annotation"><td className="min-w-40 p-2">
        <p>{row.date} · {annotationPlacement(row, context, code, dates) === "EXACT" ? "本快照精确日期匹配" : "未映射：快照、周期或可见日期不匹配；未移到最近 K 线"}</p>
        </td><td className="min-w-48 max-w-md p-2"><p className="whitespace-pre-wrap break-words">{row.text}</p>
        {row.price != null && <p>参考价格：{row.price}</p>}
        </td><td className="min-w-40 max-w-xs p-2"><p className="break-all text-muted-foreground">快照：{row.snapshot_id} · 保存时间：{row.created_at}</p>
        {row.link_kind && row.link_id && <p><Link className="text-primary underline" to={`/${row.link_kind === "evidence" ? "evidence" : "thesis"}/${encodeURIComponent(row.link_id)}`}>查看关联 {row.link_kind}</Link> · 保存时版本：{row.link_revision}（链接打开当前记录）</p>}
      </td></tr>)}</tbody></table></div>}
      {!loading && !error && !rows.length && <p>此股票尚无已读取的标注。</p>}
    </div>}
  </section>;
}
