import { useRef, useState, type FormEvent } from "react";
import { Plus, Save } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { useUnsavedChanges } from "@/components/ui/UnsavedChangesDialog";
import { addNote, type Note } from "@/lib/notes";
import { manualResearchNotePayload, type ManualResearchNoteDraft } from "@/lib/manualResearchNote";

const control = "mt-1 block min-h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm";
const button = "inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-border px-3 py-2 text-sm hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50";

export function ManualResearchNote({ initialCode, disabled, onSaved }: {
  initialCode: string; disabled: boolean; onSaved: (notes: Note[]) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mb-5">
      {open ? <ManualResearchNoteForm initialCode={initialCode} disabled={disabled} onClose={() => setOpen(false)} onSaved={onSaved} /> : (
        <button type="button" className={`${button} border-primary/30 bg-primary/10 text-primary`} disabled={disabled} onClick={() => setOpen(true)}>
          <Plus aria-hidden="true" className="h-4 w-4" />新建研究记录
        </button>
      )}
    </div>
  );
}

function ManualResearchNoteForm({ initialCode, disabled, onClose, onSaved }: {
  initialCode: string; disabled: boolean; onClose: () => void; onSaved: (notes: Note[]) => void;
}) {
  const [draft, setDraft] = useState<ManualResearchNoteDraft>(() => ({ title: "", content: "", securityCode: initialCode, sourceTitle: "", sourceUrl: "" }));
  const baseline = useRef(JSON.stringify(draft));
  const [error, setError] = useState("");
  const saving = useRef(false);
  const dirty = JSON.stringify(draft) !== baseline.current;
  const { complete, dialog } = useUnsavedChanges(dirty, false);
  const discardDialog = useRef<HTMLDialogElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const change = (key: keyof ManualResearchNoteDraft, value: string) => {
    setDraft(current => ({ ...current, [key]: value }));
    setError("");
  };
  function save(event: FormEvent) {
    event.preventDefault();
    if (saving.current || disabled) return;
    saving.current = true;
    setError("");
    try {
      const payload = manualResearchNotePayload(draft);
      const notes = addNote(payload.kind, payload.title, payload.content, payload.research);
      complete();
      onSaved(notes);
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存失败，输入已保留，请重试。");
      saving.current = false;
    }
  }
  const stay = () => { discardDialog.current?.close(); cancelButton.current?.focus(); };
  return (
    <GlassCard className="space-y-4">
      {dialog}
      <dialog ref={discardDialog} aria-labelledby="manual-note-discard-title"
        className="m-auto w-11/12 max-w-md rounded-lg border border-border bg-background p-5 text-foreground backdrop:bg-black/50"
        onCancel={event => { event.preventDefault(); stay(); }}>
        <h2 id="manual-note-discard-title" className="font-semibold">放弃未保存的研究记录？</h2>
        <p className="mt-2 text-sm text-muted-foreground">本次输入尚未保存。已有记录不会被更改。</p>
        <div className="mt-4 flex flex-wrap gap-3">
          <button type="button" autoFocus className={button} onClick={stay}>继续编辑</button>
          <button type="button" className={button} onClick={() => { complete(); onClose(); }}>放弃本次输入</button>
        </div>
      </dialog>
      <div>
        <h2 className="text-lg font-semibold">新建研究记录</h2>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">写下资料事实、暂定看法和待核对问题。保存后仍是用户暂定记录，不会自动成为正式证据、投资逻辑或决策。</p>
      </div>
      <form aria-label="新建研究记录" onSubmit={save} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2"><label htmlFor="manual-note-title" className="text-sm">记录标题</label>
            <input id="manual-note-title" autoFocus required maxLength={120} className={control} value={draft.title} onChange={event => change("title", event.target.value)} placeholder="这条记录要解决什么问题？" /></div>
          <div><label htmlFor="manual-note-code" className="text-sm">关联股票代码（可选）</label>
            <input id="manual-note-code" inputMode="numeric" maxLength={6} className={control} value={draft.securityCode} onChange={event => change("securityCode", event.target.value)} placeholder="6 位代码，或留空" /></div>
        </div>
        <div><label htmlFor="manual-note-content" className="text-sm">记录正文</label>
          <textarea id="manual-note-content" required maxLength={6000} rows={7} className={`${control} resize-y`} value={draft.content} onChange={event => change("content", event.target.value)} placeholder="分别写下已看到的资料、你的推断，以及下次需要核对什么" />
          <p className="mt-1 text-xs text-muted-foreground">{draft.content.length} / 6000 字 · 来源与推断请分开记录</p></div>
        <details className="rounded-md border border-border p-3">
          <summary className="cursor-pointer text-sm">关联一条来源（可选，需先填写股票代码）</summary>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">保存来源链接供下次核对；不会读取链接内容，也不代表来源已经核验。</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div><label htmlFor="manual-note-source-title" className="text-sm">来源标题</label><input id="manual-note-source-title" maxLength={200} className={control} value={draft.sourceTitle} onChange={event => change("sourceTitle", event.target.value)} /></div>
            <div><label htmlFor="manual-note-source-url" className="text-sm">来源链接</label><input id="manual-note-source-url" maxLength={2048} className={control} value={draft.sourceUrl} onChange={event => change("sourceUrl", event.target.value)} placeholder="https://… 或 /evidence/…" /></div>
          </div>
        </details>
        {error && <p role="alert" className="break-words text-sm text-danger">{error}</p>}
        {disabled && <p role="alert" className="text-sm text-warning">本地记录暂不可写，请先处理上方的存储问题；本次输入仍保留。</p>}
        <div className="flex flex-wrap gap-3">
          <button type="submit" disabled={disabled} className={`${button} border-primary/30 bg-primary/10 text-primary`}><Save aria-hidden="true" className="h-4 w-4" />保存研究记录</button>
          <button ref={cancelButton} type="button" className={button} onClick={() => { if (dirty) discardDialog.current?.showModal(); else onClose(); }}>取消</button>
        </div>
      </form>
    </GlassCard>
  );
}
