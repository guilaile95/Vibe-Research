import { useRef, useState } from "react";
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
  loadNotes,
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

export function Notes() {
  const [notes, setNotes] = useState<Note[]>(loadNotes);
  const [openId, setOpenId] = useState<string | null>(null);
  // 反思：对某条记录做推理审计。只保留「当前这条」的结果，避免一堆长文同时挂在页面上。
  const [reflectId, setReflectId] = useState<string | null>(null);
  const [reflectText, setReflectText] = useState("");
  const [reflectErr, setReflectErr] = useState("");
  const [reflecting, setReflecting] = useState(false);
  const [reflectSaved, setReflectSaved] = useState(false);
  const [backupStatus, setBackupStatus] = useState("");
  const [backupError, setBackupError] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const importInputRef = useRef<HTMLInputElement | null>(null);

  async function runReflect(note: Note) {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setReflectId(note.id);
    setReflectText("");
    setReflectErr("");
    setReflectSaved(false);
    setReflecting(true);
    try {
      await reflectStream(note.content, note.title, {
        onDelta: (text) => setReflectText((value) => value + text),
        onError: setReflectErr,
      }, controller.signal);
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setReflectErr(error instanceof ApiError ? error.message : String(error));
      }
    } finally {
      setReflecting(false);
    }
  }

  function saveReflection(note: Note) {
    setNotes(addNote("反思审计", `反思 · ${note.title}`, reflectText));
    setReflectSaved(true);
  }

  function downloadBackup() {
    setBackupError("");
    const json = createNotesBackupJson(notes);
    const blob = new Blob([json], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    link.href = url;
    link.download = `vibe-research-notes-${stamp}.json`;
    document.body.appendChild(link);
    try {
      link.click();
      setBackupStatus(`已导出 ${notes.length} 条研究记录。`);
    } finally {
      link.remove();
      URL.revokeObjectURL(url);
    }
  }

  async function importBackup(file: File | undefined) {
    if (!file) return;
    setBackupStatus("");
    setBackupError("");
    try {
      const result = importNotesBackupJson(await file.text());
      setNotes(result.notes);
      setBackupStatus(
        result.added > 0
          ? `已导入 ${result.added} 条研究记录${result.skipped > 0 ? `，另有 ${result.skipped} 条重复或超出上限` : ""}。`
          : `没有新增记录；${result.skipped} 条记录已存在或超出上限。`,
      );
    } catch (error) {
      setBackupError(error instanceof Error ? error.message : "研究记录导入失败");
    }
  }

  const formatTime = (ts: number) => new Date(ts).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });

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
              disabled={notes.length === 0}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Download className="h-4 w-4" /> 导出备份
            </button>
            <button
              type="button"
              onClick={() => importInputRef.current?.click()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground"
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
                onClick={() => {
                  if (confirm("清空所有研究记录？")) {
                    clearNotes();
                    setNotes([]);
                  }
                }}
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

      {backupStatus && <p className="mb-3 text-xs text-success" role="status">{backupStatus}</p>}
      {backupError && <p className="mb-3 text-xs text-destructive" role="alert">{backupError}</p>}

      {notes.length === 0 ? (
        <GlassCard>
          <div className="flex flex-col items-center gap-2 py-10 text-center text-sm text-muted-foreground">
            <NotebookPen className="h-8 w-8 text-muted-foreground/40" />
            还没有记录。在「每日复盘」「资讯雷达」或「问 AI」里点 <b className="text-foreground">「存入沉淀」</b> 保存分析结果，或从已有 JSON 备份导入。
          </div>
        </GlassCard>
      ) : (
        <div className="space-y-2">
          {notes.map((note) => {
            const open = openId === note.id;
            return (
              <GlassCard key={note.id} className="!p-0 overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-3">
                  <button onClick={() => setOpenId(open ? null : note.id)} className="flex flex-1 items-center gap-2 text-left">
                    {open ? <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />}
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] ${KIND_COLOR[note.kind] || "bg-muted/50 text-muted-foreground"}`}>{note.kind}</span>
                    <span className="flex-1 truncate text-sm font-medium">{note.title}</span>
                    <span className="shrink-0 font-mono text-[11px] text-muted-foreground/60">{formatTime(note.ts)}</span>
                  </button>
                  <button onClick={() => setNotes(deleteNote(note.id))} className="shrink-0 text-muted-foreground/60 hover:text-destructive" title="删除">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
                {open && (
                  <div className="border-t border-border/40 px-4 py-3">
                    <div className="prose prose-sm dark:prose-invert max-w-none text-foreground">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{note.content}</ReactMarkdown>
                    </div>

                    <div className="mt-3 flex items-center gap-2 border-t border-border/40 pt-3">
                      <button onClick={() => runReflect(note)} disabled={reflecting}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50">
                        <ScanSearch className="h-3.5 w-3.5" />
                        {reflecting && reflectId === note.id ? "审计中…" : "反思审计"}
                      </button>
                      <span className="text-[11px] text-muted-foreground/70">
                        让 AI 回头审这段推理：哪些有数据撑着、哪些是脑补、最脆弱的一环在哪
                      </span>
                    </div>

                    {reflectId === note.id && (reflectText || reflectErr) && (
                      <div className="mt-3 rounded-lg border border-violet-500/30 bg-violet-500/[0.05] p-3">
                        {reflectErr ? (
                          <p className="text-xs text-destructive">{reflectErr}</p>
                        ) : (
                          <>
                            <div className="prose prose-sm dark:prose-invert max-w-none text-foreground">
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>{reflectText}</ReactMarkdown>
                            </div>
                            {!reflecting && (
                              <button onClick={() => saveReflection(note)} disabled={reflectSaved}
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
