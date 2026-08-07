import { useState, useRef, useEffect } from "react";
import { Link } from "react-router-dom";
import { Sparkles, X, Settings, Send, Loader2, Wrench, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { hasLlm, chatStream, type ChatMsg } from "@/lib/llm";
import { ApiError } from "@/lib/api";
import { SaveNoteButton } from "@/components/ui/SaveNoteButton";

interface Props {
  context: string;
  suggestions?: string[];
  label?: string;
}

const TOOL_LABEL: Record<string, string> = {
  query_quote: "查行情",
  query_valuation: "查估值",
  query_reports: "查研报",
  query_news: "查新闻",
};

const argStr = (a: Record<string, unknown>): string => {
  if (Array.isArray(a.codes)) return (a.codes as unknown[]).join(",");
  if (typeof a.code === "string") return a.code;
  return "";
};

interface ToolUse { name: string; arg: string }

export function AskAiButton({ context, suggestions = [], label = "问 AI" }: Props) {
  const [open, setOpen] = useState(false);
  const [configured, setConfigured] = useState(false);
  const [msgs, setMsgs] = useState<(ChatMsg & { tools?: ToolUse[] })[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (open) setConfigured(hasLlm());
  }, [open]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const close = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setLoading(false);
    setOpen(false);
  };

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs, loading]);

  const send = async (text: string) => {
    const q = text.trim();
    if (!q || loading) return;
    setInput("");
    setErr(null);
    const history: ChatMsg[] = [...msgs.map(({ role, content }) => ({ role, content })), { role: "user", content: q }];
    setMsgs((m) => [...m, { role: "user", content: q }, { role: "assistant", content: "", tools: [] }]);
    setLoading(true);
    const patchLast = (fn: (msg: ChatMsg & { tools?: ToolUse[] }) => ChatMsg & { tools?: ToolUse[] }) =>
      setMsgs((m) => m.map((msg, i) => (i === m.length - 1 && msg.role === "assistant" ? fn(msg) : msg)));
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    const alive = () => abortRef.current === ac && !ac.signal.aborted;
    try {
      await chatStream(history, context, {
        onTool: (tool, args) => { if (alive()) patchLast((msg) => ({ ...msg, tools: [...(msg.tools || []), { name: tool, arg: argStr(args) }] })); },
        onDelta: (t) => { if (alive()) patchLast((msg) => ({ ...msg, content: msg.content + t })); },
      }, ac.signal);
    } catch (e) {
      setMsgs((m) => m.filter((msg, i) => !(i === m.length - 1 && msg.role === "assistant" && !msg.content)));
      if (!ac.signal.aborted) setErr(e instanceof ApiError ? e.message : "对话失败");
    } finally {
      if (abortRef.current === ac) {
        abortRef.current = null;
        setLoading(false);
      }
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex min-h-9 items-center gap-1.5 rounded-full bg-muted/90 px-3.5 text-[13px] font-medium text-foreground transition-colors hover:bg-muted"
      >
        <Sparkles className="h-3.5 w-3.5" />
        {label}
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div className="absolute inset-0 bg-black/35" onClick={close} aria-hidden="true" />
          <aside className="relative flex h-full w-full max-w-[560px] flex-col border-l border-border/40 bg-background shadow-2xl" aria-label="Vibe AI 对话">
            <div className="flex h-14 items-center justify-between px-4 sm:px-5">
              <span className="flex items-center gap-2 text-sm font-semibold">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-foreground text-background">
                  <Sparkles className="h-3.5 w-3.5" />
                </span>
                Vibe AI
              </span>
              <button
                type="button"
                onClick={close}
                className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                aria-label="关闭"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {!configured ? (
              <div className="mx-auto flex w-full max-w-lg flex-1 flex-col justify-center px-6 py-8 text-sm">
                <div className="mb-5">
                  <h2 className="text-lg font-semibold">接入你的 AI</h2>
                  <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
                    配置后，Vibe 会把当前页面上下文带入对话，并允许模型按需查询行情、估值、研报和新闻。
                  </p>
                </div>
                <div className="mb-5 rounded-xl bg-card/70 p-4">
                  <p className="mb-2 text-xs font-medium text-muted-foreground">当前页面上下文</p>
                  <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-muted-foreground">
{context}
                  </pre>
                </div>
                <Link
                  to="/settings"
                  className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl bg-foreground px-4 text-sm font-medium text-background transition-opacity hover:opacity-90"
                >
                  <Settings className="h-4 w-4" />
                  配置 AI
                </Link>
              </div>
            ) : (
              <>
                <div ref={scrollRef} className="flex-1 overflow-auto px-4 pb-5 sm:px-6">
                  <div className="mx-auto w-full max-w-xl space-y-6 pt-4 text-sm">
                    {msgs.length === 0 && (
                      <div className="py-8 text-center">
                        <span className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-muted">
                          <Sparkles className="h-4 w-4" />
                        </span>
                        <p className="mt-3 font-medium">就当前页面开始提问</p>
                        <p className="mt-1 text-xs text-muted-foreground">AI 会自动带上本页上下文，并按需调用数据工具。</p>
                      </div>
                    )}

                    {msgs.map((m, i) => (
                      <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                        {m.role === "user" ? (
                          <div className="max-w-[82%] rounded-3xl bg-muted px-4 py-2.5 leading-6 text-foreground">
                            <p className="whitespace-pre-wrap">{m.content}</p>
                          </div>
                        ) : (
                          <div className="w-full leading-6 text-foreground">
                            {m.tools && m.tools.length > 0 && (
                              <div className="mb-2 flex flex-wrap items-center gap-1.5">
                                {m.tools.map((t, j) => (
                                  <span key={j} className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-1 text-[10px] text-muted-foreground">
                                    <Wrench className="h-2.5 w-2.5" />
                                    {TOOL_LABEL[t.name] || t.name}{t.arg ? ` ${t.arg}` : ""}
                                  </span>
                                ))}
                              </div>
                            )}
                            <p className="whitespace-pre-wrap">{m.content}</p>
                            {m.content && !(loading && i === msgs.length - 1) && (
                              <div className="mt-2"><SaveNoteButton kind="问AI" title={`问 AI · ${msgs[i - 1]?.content?.slice(0, 24) || "对话"}`} content={m.content} /></div>
                            )}
                          </div>
                        )}
                      </div>
                    ))}

                    {loading && (
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" /> AI 正在思考 / 调取数据…
                      </div>
                    )}
                    {err && (
                      <div className="flex items-center gap-2 rounded-xl bg-destructive/10 p-3 text-xs text-destructive">
                        <AlertCircle className="h-3.5 w-3.5 shrink-0" /> {err}
                      </div>
                    )}

                    {msgs.length === 0 && suggestions.length > 0 && (
                      <div className="flex flex-wrap justify-center gap-2 pt-1">
                        {suggestions.map((s) => (
                          <button
                            type="button"
                            key={s}
                            onClick={() => send(s)}
                            className="rounded-full bg-card px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                          >
                            {s}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                <div className="px-4 pb-4 pt-2 sm:px-6 sm:pb-5">
                  <div className="mx-auto w-full max-w-xl rounded-[26px] bg-card p-2 shadow-sm">
                    <div className="flex items-end gap-2">
                      <textarea
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
                        rows={1}
                        placeholder="询问 Vibe..."
                        className="max-h-32 min-h-10 flex-1 resize-none bg-transparent px-2.5 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground"
                      />
                      <button
                        type="button"
                        onClick={() => send(input)}
                        disabled={loading || !input.trim()}
                        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-foreground text-background transition-opacity hover:opacity-90 disabled:opacity-30"
                        aria-label="发送"
                      >
                        <Send className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                  <p className="mt-2 text-center text-[10px] text-muted-foreground/70">Vibe 可能会出错，请结合原始数据判断。</p>
                </div>
              </>
            )}
          </aside>
        </div>
      )}
    </>
  );
}
