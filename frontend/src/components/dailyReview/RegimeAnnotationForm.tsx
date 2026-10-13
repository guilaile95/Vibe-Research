import { useRef, useState } from "react";
import { request } from "@/lib/api";

/** Explicit user note save, never provider activation or official rule evidence. */
export function RegimeAnnotationForm({ tradeDate, onSaved }: { tradeDate: string; onSaved: () => void }) {
  const [effective, setEffective] = useState(tradeDate);
  const [announcement, setAnnouncement] = useState("");
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const pending = useRef(false);
  const attempt = useRef<{ body: string; key: string } | null>(null);
  const save = async () => {
    if (pending.current || !title.trim()) return;
    const fields = { effective_date: effective, announcement_date: announcement || null, title, note, source_url: url || null };
    const body = JSON.stringify(fields);
    if (attempt.current?.body !== body) attempt.current = { body, key: crypto.randomUUID() };
    pending.current = true; setBusy(true); setMessage("");
    try {
      const result = await request<{ id: string; created_at: string; authority: string }>("/market/shortline-research/regime-events", "POST", { ...fields, idempotency_key: attempt.current.key });
      if (typeof result.id !== "string" || result.authority !== "USER_AUTHORED_UNVERIFIED") throw new Error("unverified save");
      setMessage("已保存人工记录；原记录不可变，未升级为官方规则证据"); onSaved();
    } catch { setMessage("保存未确认。请检查日期、链接和研究归档配置；重试相同内容不会重复新增"); }
    finally { pending.current = false; setBusy(false); }
  };
  return <details className="mt-4"><summary className="cursor-pointer text-xs">人工登记制度事件（未经核验）</summary>
    <p className="mt-2 text-xs">仅保存你的研究记录；日期和链接不会自动核验，不请求供应商，不创建归档。未来日期表示计划，不能作为规则已确认的证明</p>
    <div className="mt-3 grid gap-3 sm:grid-cols-2">
      <label className="text-xs">记录生效日<input aria-label="记录生效日" type="date" className="mt-1 block w-full rounded bg-muted p-2" value={effective} onChange={e => setEffective(e.target.value)} disabled={busy} /></label>
      <label className="text-xs">用户所知公告日（可空）<input aria-label="用户所知公告日" type="date" className="mt-1 block w-full rounded bg-muted p-2" value={announcement} onChange={e => setAnnouncement(e.target.value)} disabled={busy} /></label>
      <label className="text-xs sm:col-span-2">标题<input aria-label="制度事件标题" className="mt-1 block w-full rounded bg-muted p-2" maxLength={160} value={title} onChange={e => setTitle(e.target.value)} disabled={busy} /></label>
      <label className="text-xs sm:col-span-2">说明<textarea aria-label="制度事件说明" className="mt-1 block w-full rounded bg-muted p-2" maxLength={2000} value={note} onChange={e => setNote(e.target.value)} disabled={busy} /></label>
      <label className="text-xs sm:col-span-2">来源链接（可空，HTTP/HTTPS）<input aria-label="制度事件来源链接" type="url" className="mt-1 block w-full rounded bg-muted p-2" maxLength={2048} value={url} onChange={e => setUrl(e.target.value)} disabled={busy} /></label>
    </div>
    <button type="button" disabled={busy || !title.trim() || !effective} onClick={save} className="mt-3 rounded bg-primary/15 px-3 py-2 text-xs text-primary disabled:opacity-50">{busy ? "保存中…" : "保存人工记录"}</button>
    {message && <p role="status" className="mt-2 text-xs">{message}</p>}
  </details>;
}
