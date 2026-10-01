import { useEffect, useRef, useState } from "react";
import { Link, useBlocker } from "react-router-dom";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { GlassCard } from "@/components/ui/GlassCard";
import type { EvidenceRecord } from "@/lib/api";
import { addNote, loadNotesState, NOTES_CHANGED_EVENT } from "@/lib/notes";
import { candidateResearchContext, candidateResearchSelection, candidateResearchSourceLinks, type NoteResearchMetadata } from "@/lib/researchNote";

export function CandidateResearchNote({ code, records, evidenceStatus, returnTo, suggestedQuestion }: {
  code: string;
  records: EvidenceRecord[];
  evidenceStatus: "loading" | "ready" | "error";
  returnTo: string;
  suggestedQuestion?: string | null;
}) {
  const [question, setQuestion] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [tentativeView, setTentativeView] = useState("");
  const [contraryEvidence, setContraryEvidence] = useState("");
  const [nextQuestion, setNextQuestion] = useState("");
  const [notesState, setNotesState] = useState(loadNotesState);
  const [error, setError] = useState("");
  const [savedIdentity, setSavedIdentity] = useState("");
  // Only user-authored text counts as pending research. Evidence refreshes and
  // selection metadata must not manufacture unsaved edits after a successful save.
  const fields = [question, tentativeView, contraryEvidence, nextQuestion].map((value) => value.trim());
  const textIdentity = JSON.stringify(fields);
  const [savedTextIdentity, setSavedTextIdentity] = useState(textIdentity);
  const dirty = fields.some(Boolean) && textIdentity !== savedTextIdentity;
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && (
    currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search
  ));
  const leaveDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (blocker.state === "blocked") leaveDialog.current?.showModal();
    else leaveDialog.current?.close();
  }, [blocker.state]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  useEffect(() => {
    const refresh = () => setNotesState(loadNotesState());
    window.addEventListener(NOTES_CHANGED_EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(NOTES_CHANGED_EVENT, refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);
  const available = records.filter((record) => record.subject_type === "stock" && record.subject_id === code && !record.deleted);
  const selected = candidateResearchSelection(code, available, selectedIds);
  const context = candidateResearchContext(code, available, selectedIds);
  const metadata: NoteResearchMetadata = {
    securityCode: code,
    question: question.trim(),
    sourceLinks: candidateResearchSourceLinks(selected),
    returnTo: `${returnTo.split("#")[0]}#candidate-research-note`,
  };
  const identity = JSON.stringify([metadata, tentativeView, contraryEvidence, nextQuestion]);
  const latest = notesState.notes.filter((note) => note.research?.securityCode === code).slice(0, 3);
  const save = () => {
    setError("");
    if (!tentativeView.trim() && !nextQuestion.trim()) {
      setError("写下一句暂定看法或下次要核对的问题，再保存。");
      return;
    }
    try {
      addNote("暂定研究", `${code} · ${question.trim().slice(0, 40) || "暂定看法"}`, [
        question.trim() && `研究问题：${question.trim()}`,
        tentativeView.trim() && `暂定看法（用户记录，尚未核验）：${tentativeView.trim()}`,
        contraryEvidence.trim() && `反证 / 不确定处：${contraryEvidence.trim()}`,
        nextQuestion.trim() && `下次核对：${nextQuestion.trim()}`,
      ].filter(Boolean).join("\n\n"), {
        ...metadata, tentativeView: tentativeView.trim(), contraryEvidence: contraryEvidence.trim(), nextQuestion: nextQuestion.trim(),
      });
      setNotesState(loadNotesState());
      setSavedIdentity(identity);
      setSavedTextIdentity(textIdentity);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "保存研究记录失败"); }
  };
  return (
    <GlassCard id="candidate-research-note" tabIndex={-1} className="scroll-mt-6 space-y-4" data-testid="candidate-research-note">
      <dialog ref={leaveDialog} aria-labelledby="candidate-unsaved-title" aria-describedby="candidate-unsaved-description"
        className="m-auto w-11/12 max-w-md rounded-lg border border-border bg-background p-5 text-foreground shadow-xl backdrop:bg-black/50"
        onCancel={(event) => { event.preventDefault(); if (blocker.state === "blocked") blocker.reset(); }}>
        <h2 id="candidate-unsaved-title" className="font-semibold">研究内容尚未保存</h2>
        <p id="candidate-unsaved-description" className="mt-2 text-sm text-muted-foreground">离开会丢失本次未保存的问题和看法。可以留在这里继续编辑或先保存。</p>
        <div className="mt-4 flex flex-wrap gap-3">
          <button type="button" autoFocus className="rounded border border-primary/40 px-3 py-2 text-sm text-primary" onClick={() => { if (blocker.state === "blocked") blocker.reset(); }}>留下继续编辑</button>
          <button type="button" className="rounded border border-border px-3 py-2 text-sm" onClick={() => { if (blocker.state === "blocked") blocker.proceed(); }}>放弃未保存内容并离开</button>
        </div>
      </dialog>
      <div>
        <h2 className="text-sm font-semibold">提问、留下看法，下次接着研究</h2>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">可以先做轻量研究，不必创建投资计划。这里保存的是本浏览器的非正式记录；不会自动成为事实、投资逻辑或决策。</p>
      </div>
      {dirty && <p role="status" className="text-xs text-warning">有尚未保存的研究内容；刷新或关闭页面时，浏览器可能会提示确认。请先保存重要内容。</p>}
      <label className="block text-xs">本次要核对的问题
        <input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：盈利增长是否有现金流支持？" className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm" />
      </label>
      {suggestedQuestion && <button type="button" className="text-left text-xs text-primary hover:underline" onClick={() => setQuestion(suggestedQuestion)}>使用建议问题：{suggestedQuestion}</button>}
      <details className="rounded border border-border/60 p-3 text-xs">
        <summary className="cursor-pointer">选择给 AI 看的证据（已选 {selected.length} 条，最多 10 条）</summary>
        <p className="mt-2 text-muted-foreground">默认不选。勾选后，这些摘录会随提问发送给当前模型；不会自动加入账户持仓或资金字段；请确认所选摘录适合发送给当前模型。</p>
        {evidenceStatus === "loading" ? <p className="mt-2">证据读取中…</p> : evidenceStatus === "error" ? <p className="mt-2 text-warning">证据读取失败，可先梳理问题；不能据此判断没有证据。</p> : available.length === 0 ? <p className="mt-2 text-muted-foreground">尚无本地证据记录，可先梳理问题。</p> : (
          <div className="mt-2 max-h-52 space-y-2 overflow-y-auto">
            {available.map((record) => <label key={record.id} className="flex items-start gap-2">
              <input type="checkbox" checked={selectedIds.includes(record.id)} disabled={selected.length >= 10 && !selectedIds.includes(record.id)} onChange={(event) => setSelectedIds((ids) => event.target.checked ? [...ids, record.id] : ids.filter((id) => id !== record.id))} />
              <span>{record.claim}<span className="block text-muted-foreground">{record.source_title || "来源未知"} · {record.source_date || "日期未知"} · {record.classification}</span></span>
            </label>)}
          </div>
        )}
      </details>
      <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">查看本次会带给 AI 的上下文</summary><pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap font-sans">{context}</pre></details>
      <p className="text-xs text-muted-foreground">追问会沿用对话历史，保存回答时会保留历史来源并标注“历史轮次”；来源链接不代表 AI 已核验原文。更换证据后若要独立分析，请先清空 AI 对话。</p>
      <AskAiButton context={context} scopeKey={code} initialQuestion={question} noteMetadata={metadata} label="围绕这个问题问 AI" suggestions={question.trim() ? [question.trim()] : suggestedQuestion ? [suggestedQuestion] : ["先帮我梳理需要核对的事实，不作买卖建议"]} />
      <div className="grid gap-3 border-t border-border/50 pt-4 sm:grid-cols-3">
        {([
          ["我的暂定看法", tentativeView, setTentativeView, "先写目前的理解，不必形成正式结论"],
          ["反证 / 不确定处", contraryEvidence, setContraryEvidence, "什么事实可能推翻这个看法？"],
          ["下次核对", nextQuestion, setNextQuestion, "下次打开时先解决什么问题？"],
        ] as const).map(([label, value, setValue, placeholder]) => <label key={label} className="block text-xs">{label}<textarea value={value} onChange={(event) => setValue(event.target.value)} placeholder={placeholder} rows={3} className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm" /></label>)}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={save} disabled={savedIdentity === identity} className="rounded border border-primary/40 px-3 py-2 text-xs text-primary disabled:opacity-60">{savedIdentity === identity ? "已保存暂定研究" : "保存暂定研究"}</button>
        <Link to={`/notes?security_code=${code}`} className="text-xs text-primary hover:underline">查看这只股票的研究记录 →</Link>
      </div>
      {(error || notesState.error) && <p role="alert" className="text-xs text-warning">{error || notesState.error}</p>}
      {latest.length > 0 && <div className="border-t border-border/50 pt-3 text-xs"><p className="font-medium">这只股票最近留下的记录</p><ul className="mt-2 space-y-2">{latest.map((note) => <li key={note.id}><Link className="text-primary hover:underline" to={`/notes?security_code=${code}&note=${encodeURIComponent(note.id)}`}>{note.title}</Link><span className="ml-2 text-muted-foreground">{note.kind === "暂定研究" ? "用户暂定记录" : "AI 原文，未经用户确认"}</span>{note.research?.nextQuestion && <p className="mt-1">下次核对：{note.research.nextQuestion} <button type="button" className="text-primary hover:underline" onClick={() => setQuestion(note.research?.nextQuestion || "")}>用这个问题继续</button></p>}</li>)}</ul></div>}
    </GlassCard>
  );
}
