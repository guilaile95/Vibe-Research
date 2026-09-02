import { useState, useRef, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { Sparkles, X, Settings, Send, Loader2, Wrench, AlertCircle, Trash2, Square } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import {
  LLM_CHANGED_EVENT,
  chatSessionId,
  chatStream,
  hasLlm,
  llmIdentity,
  loadLlm,
  runtimeLabel,
  type ChatReportSource,
  type ChatMsg,
} from "@/lib/llm";
import { ApiError } from "@/lib/api";
import { SaveNoteButton } from "@/components/ui/SaveNoteButton";
import { storageGet, storageSet, storageRemove } from "@/lib/storage";

// 对话持久化。此前 msgs 只是组件内的 useState：切页面卸载、刷新、
// 关标签页，问过的东西全没了——每轮对话是花了自己 API 额度换来的，丢掉的是真金白银。
//
// 按路由分开存：不同页面的「问 AI」上下文不同（个股页 vs 板块页），
// 混在一起会把上一页的对话带到下一页，比不存更让人困惑。
const CHAT_KEY_PREFIX = "vr-askai-chat:";
const CHAT_EPOCH_PREFIX = "vr-askai-epoch:";
// 单页对话上限。localStorage 总配额约 5MB，而一轮研报级回答可能上万字；
// 不设上限迟早写爆，届时 storageSet 静默失败、用户以为存上了。
const MAX_PERSISTED_MSGS = 40;
const MAX_PERSISTED_CHARS = 80_000;

type StoredMsg = ChatMsg & {
  tools?: ToolUse[];
  sources?: ChatReportSource[];
  // 流式中途被中止、只收到半截的回答。**不落盘、也不进下一轮 history**：
  // 否则刷新后它会以「完整回答」的身份被喂回模型，后续推理建立在残句上。
  // UI 仍然显示，用户能看到已经拿到的部分。
  partial?: boolean;
};

function loadChat(key: string): StoredMsg[] {
  const raw = storageGet(key);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    // 存量数据可能来自旧版本或被手工改坏，形状不对就当没有，别让页面崩。
    if (!Array.isArray(parsed)) return [];
    return boundedCompleteTurns(parsed.filter(
      (m): m is StoredMsg =>
        m && typeof m === "object" && typeof m.content === "string" &&
        (m.role === "user" || m.role === "assistant"),
    ).map((m) => ({
      ...m,
      sources: Array.isArray(m.sources) ? m.sources.filter(
        (source) => source && typeof source.report_id === "string" &&
          typeof source.title === "string" &&
          (source.page === null || (Number.isInteger(source.page) && source.page > 0)),
      ).slice(0, 8) : undefined,
    })));
  } catch {
    return [];
  }
}

// 只保留「完整的轮次」。partial 的 assistant 要连同它前面那条 user 一起丢：
// 只丢 assistant 会留下一个孤立的提问，模型在 history 里看到连续两条 user 发言，
// 会把那个被放弃的问题当成还在等回答，去答错的题。
function completeTurns(msgs: StoredMsg[]): StoredMsg[] {
  const out: StoredMsg[] = [];
  for (const m of msgs) {
    if (m.partial) {
      if (out.length && out[out.length - 1].role === "user") out.pop();
      continue;
    }
    out.push(m);
  }
  return out;
}

// UI、持久化和发给模型的历史使用同一上限与同一完整轮次集合。
// 从尾部保留最新内容；若边界落在 assistant，丢掉该孤立回答。
function boundedCompleteTurns(msgs: StoredMsg[]): StoredMsg[] {
  const complete = completeTurns(msgs);
  if (complete.length % 2) return [];
  const out: StoredMsg[] = [];
  let chars = 0;
  for (let index = complete.length - 2; index >= 0; index -= 2) {
    const user = complete[index];
    const assistant = complete[index + 1];
    if (user.role !== "user" || assistant.role !== "assistant") return [];
    const pairChars = user.content.length + assistant.content.length;
    if (out.length + 2 > MAX_PERSISTED_MSGS || chars + pairChars > MAX_PERSISTED_CHARS) break;
    out.unshift(user, assistant);
    chars += pairChars;
  }
  return out;
}

function saveChat(key: string, msgs: StoredMsg[]): void {
  if (!msgs.length) {
    storageRemove(key);
    return;
  }
  const keep = boundedCompleteTurns(msgs);
  if (!keep.length) {
    storageRemove(key);
    return;
  }
  storageSet(key, JSON.stringify(keep));
}

function loadEpoch(key: string): number {
  const value = Number(storageGet(CHAT_EPOCH_PREFIX + key) ?? 0);
  return Number.isSafeInteger(value) && value >= 0 ? value : 0;
}

interface Props {
  context: string;
  suggestions?: string[];
  label?: string;
  // 用来在**同一路由内**再切分对话。不传则只按路由区分——目前每个页面都只挂
  // 一个 AskAiButton、且一个路由对应一个对象，够用。
  // ⚠️ 不换路由就能换标的的页面（如个股页）必须传入已解析的代码，否则对话会串台。
  scopeKey?: string;
  reportIds?: string[];
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

export function AskAiButton({ context, suggestions = [], label = "问 AI", scopeKey, reportIds = [] }: Props) {
  const { pathname } = useLocation();
  const selectedLlm = loadLlm();
  const isCodexRuntime = selectedLlm?.provider === "cli-codex";

  const [open, setOpen] = useState(false);
  const [configured, setConfigured] = useState(false);
  const [runtimeKey, setRuntimeKey] = useState(() => llmIdentity());
  const chatKey = CHAT_KEY_PREFIX + pathname + (scopeKey ? `#${scopeKey}` : "") + `@${runtimeKey}`;
  // key 与消息放在**同一个 state 里原子更新**——这是正确性的关键，不是风格问题。
  // 若分成 msgs + 一个记录归属的 ref，key 变化那一帧 ref 已指向新 key 而 msgs 仍是旧的
  // （setState 下一帧才生效），落盘守卫会误放行，把来源页对话写进目标 key、
  // 覆盖掉目标页已存的对话。捆在一起后，转场帧里 chat.key 天然还是旧值，守卫必然拦住。
  // 惰性初始化：首帧就带上已存的对话，避免先渲染空列表再闪一下补上。
  const [chat, setChat] = useState<{ key: string; msgs: StoredMsg[] }>(
    () => ({ key: chatKey, msgs: loadChat(chatKey) }),
  );
  const msgs = chat.msgs;
  const setMsgs = (
    updater: StoredMsg[] | ((prev: StoredMsg[]) => StoredMsg[]),
  ) =>
    setChat((c) => ({
      key: c.key,
      msgs: typeof updater === "function" ? updater(c.msgs) : updater,
    }));
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(() => loadEpoch(chatKey));
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  // 始终镜像当前 chatKey，供异步回调判断「对话是否已经被换掉」。
  const chatKeyRef = useRef(chatKey);
  chatKeyRef.current = chatKey;

  useEffect(() => {
    if (open) {
      setConfigured(hasLlm());
      setRuntimeKey(llmIdentity());
    }
  }, [open]);

  useEffect(() => {
    const refreshRuntime = () => {
      abortRef.current?.abort();
      abortRef.current = null;
      setLoading(false);
      setConfigured(hasLlm());
      setRuntimeKey(llmIdentity());
    };
    window.addEventListener(LLM_CHANGED_EVENT, refreshRuntime);
    window.addEventListener("storage", refreshRuntime);
    return () => {
      window.removeEventListener(LLM_CHANGED_EVENT, refreshRuntime);
      window.removeEventListener("storage", refreshRuntime);
    };
  }, []);

  // 换页面/换标的 = 换一份对话（key 变了），把目标 key 已存的读进来。
  // 同时**中止在跑的流式请求**：否则它的 alive() 仍然成立，迟到的 chunk 会被
  // 追加到目标页的最后一条助手消息上，并把「用来源页上下文生成的回答」存进目标 key。
  useEffect(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setLoading(false);
    setEpoch(loadEpoch(chatKey));
    setChat({ key: chatKey, msgs: loadChat(chatKey) });
  }, [chatKey]);

  // 每次消息变动落盘。守卫见上方 chat state 的注释：转场帧里 chat.key 仍是旧值，
  // 与 chatKey 不等，于是不会把旧对话写进新 key。
  useEffect(() => {
    if (chat.key !== chatKey) return;
    saveChat(chatKey, chat.msgs);
  }, [chatKey, chat]);

  useEffect(() => () => abortRef.current?.abort(), []); // 组件卸载兜底

  const clearChat = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setLoading(false);
    setErr(null);
    setMsgs([]);          // saveChat 见空数组会 storageRemove，不留空壳
    setEpoch((current) => {
      const next = current + 1;
      storageSet(CHAT_EPOCH_PREFIX + chatKey, String(next));
      return next;
    });
  };

  const close = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setLoading(false);
    setOpen(false);
  };

  const stop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setLoading(false);
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
    // 未完成的轮次整轮不进 history（半截回答 + 它的提问）：
    // 模型会把残句当成自己上一轮的完整发言继续推理，孤立的提问则会被当成待答问题。
    const visibleHistory = boundedCompleteTurns(msgs);
    const history: ChatMsg[] = [
      ...visibleHistory.map(({ role, content }) => ({ role, content })),
      { role: "user", content: q },
    ];
    // assistant 气泡**从创建就是 partial**，只有流式正常结束才摘掉这个标记。
    // 这样「流到一半用户换页/换标的」时，落盘的那份天然就不含这条残句——
    // 靠中止时再补标记是来不及的：每个 delta 都会触发落盘。
    setMsgs([
      ...visibleHistory,
      { role: "user", content: q },
      { role: "assistant", content: "", tools: [], partial: true },
    ]);
    setLoading(true);
    const patchLast = (fn: (msg: StoredMsg) => StoredMsg) =>
      setMsgs((m) => m.map((msg, i) => (i === m.length - 1 && msg.role === "assistant" ? fn(msg) : msg)));
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    const startedKey = chatKeyRef.current;   // 这次请求属于哪份对话
    const session = chatSessionId(`${startedKey}:${epoch}`);
    // 只有仍是「当前这次请求」才允许写 UI——旧请求的迟到 chunk 直接丢弃
    const alive = () => abortRef.current === ac && !ac.signal.aborted;
    try {
      await chatStream(history, context, {
        onTool: (tool, args) => { if (alive()) patchLast((msg) => ({ ...msg, tools: [...(msg.tools || []), { name: tool, arg: argStr(args) }] })); },
        onSources: (items) => { if (alive()) patchLast((msg) => ({ ...msg, sources: items })); },
        onDelta: (t) => { if (alive()) patchLast((msg) => ({ ...msg, content: msg.content + t })); },
      }, ac.signal, session, reportIds);
      // 正常收完：摘掉 partial，这条回答才开始落盘、才进下一轮 history。
      if (alive()) setMsgs((current) => boundedCompleteTurns(current.map((msg, index) => {
        if (index !== current.length - 1 || msg.role !== "assistant") return msg;
        const { partial: _drop, ...rest } = msg;
        return rest;
      })));
    } catch (e) {
      // 三种「不该清理」的情况要分开判，不能简单用 abortRef.current === ac：
      //   · 有更新的请求接管了（abortRef 指向别人）→ 别删人家的气泡
      //   · 对话已经被换掉（key 变了）→ 别动新对话
      //   · 面板被关闭（close 把 abortRef 置 null，但对话没变）→ **仍要清理**
      const superseded = abortRef.current !== null && abortRef.current !== ac;
      if (!superseded && chatKeyRef.current === startedKey) {
        // 只处理「一个字都没收到」：把空气泡**连同它的提问**一起从界面移除——
        // 有内容的半截回答带着 partial 标记，completeTurns 已挡在落盘与 history 之外。
        setMsgs((m) => {
          const last = m[m.length - 1];
          if (!last || last.role !== "assistant" || last.content) return m;
          const dropUser = m[m.length - 2]?.role === "user";
          return m.slice(0, dropUser ? -2 : -1);
        });
        if (!ac.signal.aborted) setErr(e instanceof ApiError ? e.message : "对话失败");
      }
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
        <div className="fixed inset-0 z-50 flex justify-end md:pointer-events-none md:left-auto md:w-[440px] xl:w-[480px]">
          <div className="absolute inset-0 bg-black/35 md:hidden" onClick={close} aria-hidden="true" />
          <aside
            className="pointer-events-auto relative ml-auto flex h-full w-full max-w-[560px] flex-col border-l border-border/50 bg-background shadow-2xl md:max-w-none md:shadow-xl"
            aria-label="Vibe AI 对话"
          >
            <div className="flex h-14 items-center justify-between border-b border-border/40 px-4 sm:px-5">
              <span className="flex items-center gap-2 text-sm font-semibold">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-foreground text-background">
                  <Sparkles className="h-3.5 w-3.5" />
                </span>
                Vibe AI
                <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                  {runtimeLabel(selectedLlm)}
                </span>
              </span>
              <div className="flex items-center gap-1">
                {msgs.length > 0 && (
                  // 存了就得能删：对话留在本机 localStorage，用户得有办法清掉。
                  <button
                    type="button"
                    onClick={clearChat}
                    title="清空本页对话"
                    aria-label="清空本页对话"
                    className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
                <button
                  type="button"
                  onClick={close}
                  className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  aria-label="关闭"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            {!configured ? (
              <div className="mx-auto flex w-full max-w-lg flex-1 flex-col justify-center px-6 py-8 text-sm">
                <div className="mb-5">
                  <h2 className="text-lg font-semibold">接入你的 AI</h2>
                  <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
                    配置后，Vibe 会把当前页面上下文带入对话。Codex Subscription 只使用页面上下文；API Compatible 保留现有数据工具能力。
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
                        <p className="mt-1 text-xs text-muted-foreground">
                          {isCodexRuntime
                            ? "Codex 只使用当前页面上下文，不会读取本机文件或调用数据工具。"
                            : "AI 会自动带上本页上下文，并按需调用 Vibe 数据工具。"}
                        </p>
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
                            {m.role === "assistant" ? (
                              <>
                                <div className="mb-1 text-[9px] font-semibold tracking-wide text-muted-foreground">
                                  NON_AUTHORITATIVE_AI_DRAFT
                                </div>
                                <div className="prose prose-sm dark:prose-invert max-w-none break-words text-foreground">
                                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                                </div>
                                {m.sources && m.sources.length > 0 && (
                                  <div className="mt-3 rounded-xl border border-border/50 bg-muted/40 p-3 text-xs text-muted-foreground">
                                    <p className="mb-1 font-medium text-foreground">检索依据</p>
                                    {m.sources.map((source) => (
                                      <p key={`${source.report_id}:${source.page ?? 0}`}>
                                        {source.title} · report_id={source.report_id} · {source.page ? `第 ${source.page} 页` : "页码不可用"}
                                      </p>
                                    ))}
                                  </div>
                                )}
                              </>
                            ) : (
                              <p className="whitespace-pre-wrap break-words">{m.content}</p>
                            )}
                            {m.content && !(loading && i === msgs.length - 1) && (
                              <div className="mt-2"><SaveNoteButton kind="问AI" title={`问 AI · ${msgs[i - 1]?.content?.slice(0, 24) || "对话"}`} content={m.content} /></div>
                            )}
                          </div>
                        )}
                      </div>
                    ))}

                    {loading && (
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        {isCodexRuntime ? "Codex 正在根据当前页面思考…" : "AI 正在思考 / 调取数据…"}
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

                <div className="border-t border-border/40 px-4 pb-4 pt-3 sm:px-6 sm:pb-5">
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
                      {loading ? (
                        <button
                          type="button"
                          onClick={stop}
                          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-foreground text-background transition-opacity hover:opacity-90"
                          aria-label="停止生成"
                          title="停止生成"
                        >
                          <Square className="h-3.5 w-3.5 fill-current" />
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => send(input)}
                          disabled={!input.trim()}
                          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-foreground text-background transition-opacity hover:opacity-90 disabled:opacity-30"
                          aria-label="发送"
                        >
                          <Send className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  </div>
                  <p className="mt-2 text-center text-[10px] text-muted-foreground/70">非正式 AI 草稿；需要正式操作时请进入对应 Vibe 页面。</p>
                </div>
              </>
            )}
          </aside>
        </div>
      )}
    </>
  );
}
