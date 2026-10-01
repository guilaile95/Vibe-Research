import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Download,
  NotebookPen,
  Save,
  ScanSearch,
  Trash2,
  Upload,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import {
  addNote,
  clearNotes,
  createNotesBackupJson,
  deleteNote,
  importNotesBackupJson,
  loadNotesState,
  parseNotesBackupJson,
  replaceCorruptedNotesFromBackupJson,
  type Note,
} from "@/lib/notes";
import { reflectStream } from "@/lib/agents";
import { ApiError } from "@/lib/api";

const KIND_COLOR: Record<string, string> = {
  复盘: "bg-primary/15 text-primary",
  今日要点: "bg-warning/15 text-warning",
  问AI: "bg-success/15 text-success",
  多空辩论: "bg-sky-500/15 text-sky-400",
  反思审计: "bg-violet-500/15 text-violet-400",
};

function downloadNotesFile(raw: string, prefix: string, extension: string) {
  const blob = new Blob([raw], { type: extension === "json" ? "application/json;charset=utf-8" : "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${prefix}-${new Date().toISOString().replace(/[:.]/g, "-")}.${extension}`;
  document.body.appendChild(link);
  try {
    link.click();
  } finally {
    link.remove();
    URL.revokeObjectURL(url);
  }
}

export function Notes() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedCode = searchParams.get("security_code") || "";
  const securityCode = /^\d{6}$/.test(requestedCode) ? requestedCode : "";
  const focusedNoteId = searchParams.get("note");
  const [notesState, setNotesState] = useState(loadNotesState);
  const { notes, corruptedRaw } = notesState;
  const [openId, setOpenId] = useState<string | null>(() => focusedNoteId);
  const filteredNotes = securityCode ? notes.filter((note) => note.research?.securityCode === securityCode) : notes;
  useEffect(() => { setOpenId(focusedNoteId); }, [focusedNoteId]);
  // 反思：对某条记录做推理审计。只保留「当前这条」的结果，避免一堆长文同时挂在页面上。
  const [reflectId, setReflectId] = useState<string | null>(null);
  const [reflectText, setReflectText] = useState("");
  const [reflectErr, setReflectErr] = useState("");
  const [reflecting, setReflecting] = useState(false);
  const [reflectSaved, setReflectSaved] = useState(false);
  const [backupStatus, setBackupStatus] = useState("");
  const [backupError, setBackupError] = useState("");
  const [importing, setImporting] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const importRequestRef = useRef(0);
  const importBusyRef = useRef(false);

  useEffect(() => () => {
    const controller = abortRef.current;
    abortRef.current = null;
    controller?.abort();
    importRequestRef.current += 1;
  }, []);

  function setNotes(next: Note[]) {
    setNotesState({ notes: next, error: "", corruptedRaw: null });
  }

  function reportBackupError(error: unknown, fallback: string) {
    setNotesState(loadNotesState());
    setBackupError(error instanceof Error ? error.message : fallback);
  }

  async function runReflect(n: Note) {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setReflectId(n.id); setReflectText(""); setReflectErr(""); setReflectSaved(false); setReflecting(true);
    try {
      await reflectStream(n.content, n.title, {
        onDelta: (t) => { if (abortRef.current === ctrl && !ctrl.signal.aborted) setReflectText((s) => s + t); },
        onError: (message) => { if (abortRef.current === ctrl && !ctrl.signal.aborted) setReflectErr(message); },
      }, ctrl.signal);
    } catch (e) {
      if (abortRef.current === ctrl && !ctrl.signal.aborted && !(e instanceof DOMException && e.name === "AbortError")) {
        setReflectErr(e instanceof ApiError ? e.message : String(e));
      }
    } finally {
      if (abortRef.current === ctrl) { setReflecting(false); abortRef.current = null; }
    }
  }

  function saveReflection(n: Note) {
    setBackupStatus("");
    try {
      setNotes(addNote("反思审计", `反思 · ${n.title}`, reflectText, n.research ? {
        securityCode: n.research.securityCode,
        question: n.research.question,
        sourceLinks: n.research.sourceLinks,
        returnTo: n.research.returnTo,
      } : undefined));
      setReflectSaved(true);
      setBackupError("");
    } catch (error) {
      reportBackupError(error, "研究记录保存失败");
    }
  }

  function downloadBackup() {
    setBackupStatus("");
    setBackupError("");
    try {
      const current = loadNotesState();
      if (current.error) throw new Error(current.error);
      setNotesState(current);
      downloadNotesFile(createNotesBackupJson(current.notes), "vibe-research-notes", "json");
      setBackupStatus(`已导出 ${current.notes.length} 条研究记录。`);
    } catch (error) {
      reportBackupError(error, "研究记录导出失败");
    }
  }

  function downloadCorruptedData() {
    setBackupStatus("");
    setBackupError("");
    try {
      const current = loadNotesState();
      setNotesState(current);
      if (current.corruptedRaw === null) throw new Error("当前没有可下载的损坏研究记录，请检查存储权限或刷新页面");
      downloadNotesFile(current.corruptedRaw, "vibe-research-notes-corrupted-raw", "txt");
      setBackupStatus("已下载损坏研究记录的原始数据；这是修复留存文件，不能作为有效备份直接导入。");
    } catch (error) {
      reportBackupError(error, "原始研究记录下载失败");
    }
  }

  async function importBackup(file: File | undefined) {
    if (!file || importBusyRef.current) return;
    importBusyRef.current = true;
    setImporting(true);
    const request = ++importRequestRef.current;
    setBackupStatus("");
    setBackupError("");
    try {
      const raw = await file.text();
      if (request !== importRequestRef.current) return;
      if (corruptedRaw !== null) {
        const imported = parseNotesBackupJson(raw);
        if (!confirm(`备份已校验，共 ${imported.length} 条研究记录。\n将用此备份完全替换当前损坏的研究记录，原始数据将无法在浏览器中恢复。请先下载原始数据留存。\n仅替换研究记录，不修改模型密钥、访问密钥或 AI 对话。确定替换？`)) {
          setBackupStatus("已取消替换，原始研究记录保持不变。");
          return;
        }
        setNotes(replaceCorruptedNotesFromBackupJson(raw, corruptedRaw));
        setOpenId(null);
        setBackupStatus(`已从备份恢复 ${imported.length} 条研究记录，损坏数据已替换。`);
        return;
      }
      const result = importNotesBackupJson(raw);
      setNotes(result.notes);
      setBackupStatus(
        result.added > 0
          ? `已导入 ${result.added} 条研究记录${result.skipped > 0 ? `，另有 ${result.skipped} 条重复或超出上限` : ""}。`
          : `没有新增记录；${result.skipped} 条记录已存在或超出上限。`,
      );
    } catch (error) {
      if (request === importRequestRef.current) reportBackupError(error, "研究记录导入失败");
    } finally {
      if (request === importRequestRef.current) {
        importBusyRef.current = false;
        setImporting(false);
      }
    }
  }

  const fmt = (ts: number) => new Date(ts).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });

  return (
    <div>
      <PageHeader
        title="研究记录"
        subtitle="把 AI 复盘、今日要点和问答保存在当前浏览器中，随时回看。"
        actions={(
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              onClick={downloadBackup}
              disabled={notes.length === 0 || importing}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Download className="h-4 w-4" /> 导出备份
            </button>
            <button
              type="button"
              onClick={() => importInputRef.current?.click()}
              disabled={corruptedRaw !== null || importing}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Upload className="h-4 w-4" /> 导入备份
            </button>
            <input
              ref={importInputRef}
              data-testid="notes-backup-input"
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                event.currentTarget.value = "";
                void importBackup(file);
              }}
            />
            {notes.length > 0 && (
              <button
                type="button"
                disabled={importing}
                onClick={() => { if (confirm("清空所有研究记录？")) {
                  setBackupStatus("");
                  try { clearNotes(); setNotes([]); setBackupError(""); }
                  catch (error) { reportBackupError(error, "清空失败"); }
                } }}
                className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="h-4 w-4" /> 清空
              </button>
            )}
          </div>
        )}
      />

      <div className="mb-4 flex gap-2 rounded-lg border border-warning/30 bg-warning/5 px-3 py-2.5 text-xs leading-5 text-muted-foreground">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
        <div>
          <p className="font-medium text-foreground">研究记录只保存在当前浏览器中。</p>
          <p>清理浏览器数据、切换浏览器 Profile 或更换设备前，请先导出备份。备份文件只包含研究记录，不包含模型密钥、访问密钥或 AI 对话。</p>
        </div>
      </div>
      {notesState.error && (
        <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm" role="alert">
          <p className="font-medium text-destructive">{notesState.error}</p>
          {corruptedRaw !== null && (
            <>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">记录无法读取，但原始数据仍保留。请先下载原始数据留存，再选择有效的研究记录 JSON 备份。备份校验通过并确认后才会替换损坏数据；取消或导入失败不会清空原始数据。</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" onClick={downloadCorruptedData} disabled={importing}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 px-3 py-1.5 text-xs disabled:opacity-40">
                  <Download className="h-3.5 w-3.5" /> 下载损坏原始数据
                </button>
                <button type="button" onClick={() => importInputRef.current?.click()} disabled={importing}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-destructive/40 px-3 py-1.5 text-xs disabled:opacity-40">
                  <Upload className="h-3.5 w-3.5" /> 从备份替换损坏记录
                </button>
              </div>
            </>
          )}
        </div>
      )}
      {backupStatus && <p className="mb-3 text-xs text-success" role="status">{backupStatus}</p>}
      {backupError && backupError !== notesState.error && <p className="mb-3 text-xs text-destructive" role="alert">{backupError}</p>}

      <div className="mb-4 flex flex-wrap items-end gap-3 text-xs">
        <label>按股票代码查看
          <input value={requestedCode} placeholder="全部记录" inputMode="numeric" maxLength={6} onChange={(event) => {
            const code = event.target.value.replace(/\D/g, "");
            setSearchParams(code ? { security_code: code } : {}, { replace: true });
          }} className="ml-2 w-32 rounded border border-border bg-background px-2 py-1.5" />
        </label>
        {securityCode && <Link to={`/candidates/${securityCode}#candidate-research-note`} className="text-primary hover:underline">回到 {securityCode} 的候选研究 →</Link>}
        {securityCode && <button type="button" className="text-muted-foreground hover:underline" onClick={() => setSearchParams({})}>显示全部记录</button>}
      </div>

      {notesState.error ? null : filteredNotes.length === 0 ? (
        <GlassCard>
          <div className="flex flex-col items-center gap-2 py-10 text-center text-sm text-muted-foreground">
            <NotebookPen className="h-8 w-8 text-muted-foreground/40" />
            {securityCode ? `${securityCode} 暂无关联的研究记录。旧记录没有证券标签时仍在“全部记录”中。` : <>还没有记录。在「每日复盘」「资讯雷达」或「问 AI」里点 <b className="text-foreground">「存入沉淀」</b> 保存分析结果，或从已有 JSON 备份导入。</>}
          </div>
        </GlassCard>
      ) : (
        <div className="space-y-2">
          {filteredNotes.map((n) => {
            const open = openId === n.id;
            return (
              <GlassCard key={n.id} className="!p-0 overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-3">
                  <button onClick={() => setOpenId(open ? null : n.id)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
                    {open ? <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />}
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] ${KIND_COLOR[n.kind] || "bg-muted/50 text-muted-foreground"}`}>{n.kind}</span>
                    <span className="flex-1 truncate text-sm font-medium">{n.title}</span>
                    <span className="shrink-0 font-mono text-[11px] text-muted-foreground/60">{fmt(n.ts)}</span>
                  </button>
                  <button onClick={() => {
                    setBackupStatus("");
                    try { setNotes(deleteNote(n.id)); setBackupError(""); }
                    catch (error) { reportBackupError(error, "删除失败"); }
                  }} className="shrink-0 text-muted-foreground/60 hover:text-destructive" title="删除">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
                {open && (
                  <div className="border-t border-border/40 px-4 py-3">
                    {n.research && <div className="mb-3 space-y-1 rounded border border-border/50 p-3 text-xs" data-testid="note-research-context">
                      <p className="font-medium">{n.research.securityCode} · {n.kind === "暂定研究" ? "用户暂定记录，尚未核验" : "AI 原文，未经用户确认"}</p>
                      {n.research.question && <p>研究问题：{n.research.question}</p>}
                      {n.research.nextQuestion && <p>下次核对：{n.research.nextQuestion}</p>}
                      {n.research.sourceLinks?.length ? <ul className="space-y-1">{n.research.sourceLinks.map((source, index) => <li key={`${source.url}-${index}`}><a href={source.url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">{source.title}</a></li>)}</ul> : <p className="text-muted-foreground">未保存资料链接；不能据此认为已核验来源。</p>}
                      <Link to={n.research.returnTo || `/candidates/${n.research.securityCode}#candidate-research-note`} className="inline-block pt-1 text-primary hover:underline">回到当时的研究位置 →</Link>
                    </div>}
                    <div className="prose prose-sm dark:prose-invert max-w-none text-foreground">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{n.content}</ReactMarkdown>
                    </div>

                    <div className="mt-3 flex items-center gap-2 border-t border-border/40 pt-3">
                      <button onClick={() => runReflect(n)} disabled={reflecting}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50">
                        <ScanSearch className="h-3.5 w-3.5" />
                        {reflecting && reflectId === n.id ? "审计中…" : "反思审计"}
                      </button>
                      <span className="text-[11px] text-muted-foreground/70">
                        让 AI 回头审这段推理：哪些有数据撑着、哪些是脑补、最脆弱的一环在哪
                      </span>
                    </div>

                    {reflectId === n.id && (reflectText || reflectErr) && (
                      <div className="mt-3 rounded-lg border border-violet-500/30 bg-violet-500/[0.05] p-3">
                        {reflectErr ? (
                          <p className="text-xs text-destructive">{reflectErr}</p>
                        ) : (
                          <>
                            <div className="prose prose-sm dark:prose-invert max-w-none text-foreground">
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>{reflectText}</ReactMarkdown>
                            </div>
                            {!reflecting && (
                              <button onClick={() => saveReflection(n)} disabled={reflectSaved}
                                className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50">
                                <Save className="h-3 w-3" /> {reflectSaved ? "已存为新记录" : "把审计结果存为新记录"}
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </GlassCard>
            );
          })}
        </div>
      )}

      <Disclaimer />
    </div>
  );
}
