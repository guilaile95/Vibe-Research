// Vibe-Research 后端 API 客户端。/api → vite 代理到本地 FastAPI（默认 8900）。
// 后端未启动或数据源异常时抛 ApiError，页面据此优雅降级。
// 纯类型定义见 ./api/types.ts；本文件仅保留运行时客户端。

export type * from "./api/types.ts";

import type {
  MyReport,
  MyReportsBrowseGroup,
  MyReportsBrowseResult,
  SectorReportScope,
  SectorReportsDiscoveryResult,
  SectorDynamicData,
  Quote,
  Valuation,
  Report,
  ValPercentile,
  Announcement,
  Financials,
  NewsItem,
  IndexQuote,
  TimedComponentEnvelope,
  MarketOverview,
  ShortTermEmotion,
  TurnoverTop,
  MarketBreadthData,
  BoardRankingData,
  DailyReviewCacheMeta,
  DailyReviewData,
  DailyReviewHistorySnapshot,
  SaveDailyReviewHistoryResult,
  DailyReviewHistoryList,
  DailyReviewComparison,
  RadarData,
  PortfolioData,
  AccountProfileResponse,
  AccountProfileRequest,
  PortfolioAdviceResult,
  PortfolioAdviceRequest,
  AiResultType,
  AiGeneratedResult,
  AiGeneratedResultMetadata,
  MarginRow,
  BlockTradeRow,
  HolderRow,
  DividendRow,
  FundFlowRow,
  DragonTiger,
  Lockup,
  Blocks,
  HotConcept,
  QaRow,
  IndustryData,
  KlineBar,
  DisclosureItem,
  GlobalIndex,
  GlobalStock,
  DailyReviewAnalyzeRequest,
  NdjsonStreamHandlers,
  NdjsonStreamResult,
  NdjsonProtocolState,
  EvidenceRecord,
  EvidenceCreateInput,
  EvidenceUpdateInput,
  EvidenceListResult,
  ThesisCreateInput,
  ThesisUpdateInput,
  ThesisAggregate,
  ThesisListResult,
  ThesisRevision,
  RevisionListResult,
  ThesisDiff,
  LinkEvidenceInput,
  UpdateStanceInput,
} from "./api/types.ts";


export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}


// 后端访问密钥（对应后端部署时的 VR_API_KEY，公网部署防蹭用）。只存本地浏览器。
const ACCESS_KEY = "vr-access-key";


export function loadAccessKey(): string {
  try {
    return localStorage.getItem(ACCESS_KEY) || "";
  } catch {
    return "";
  }
}


export function saveAccessKey(key: string) {
  try {
    if (key) localStorage.setItem(ACCESS_KEY, key);
    else localStorage.removeItem(ACCESS_KEY);
  } catch {
    /* 隐私模式等场景 localStorage 不可用 */
  }
}


export function authHeaders(): Record<string, string> {
  const k = loadAccessKey();
  return k ? { Authorization: `Bearer ${k}` } : {};
}


export function unwrapApiPayload(payload: any): any {
  if (
    payload !== null
    && typeof payload === "object"
    && Object.prototype.hasOwnProperty.call(payload, "data")
  ) {
    return payload.data;
  }
  return payload;
}


// 下载/预览研报：带鉴权头 fetch → blob → 触发浏览器下载（<a download> 无法带 Authorization，故走 blob）。
export async function downloadReport(id: string, name: string): Promise<void> {
  const resp = await fetch(`/api/myreports/file/${id}`, { headers: authHeaders() });
  if (!resp.ok) throw new ApiError(`下载失败 HTTP ${resp.status}`, resp.status);
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}


export async function request<T>(
  path: string,
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE" = "GET",
  body?: unknown,
  options?: { unwrapData?: boolean; signal?: AbortSignal },
): Promise<T> {
  const unwrapData = options?.unwrapData ?? true;
  let resp: Response;
  const headers: Record<string, string> = { ...authHeaders() };
  const opts: RequestInit = { method };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  if (options?.signal) opts.signal = options.signal;
  if (Object.keys(headers).length > 0) opts.headers = headers;
  try {
    resp = await fetch(`/api${path}`, opts);
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    if (typeof e === "object" && e !== null && "name" in e && (e as { name: string }).name === "AbortError") {
      throw e;
    }
    throw new ApiError("连接不到后端，请先启动 backend（uvicorn app:app --port 8900）", 0);
  }
  let payload: any = null;
  try {
    payload = await resp.json();
  } catch {
    /* 非 JSON 响应 */
  }
  if (!resp.ok) {
    if (resp.status === 401) {
      throw new ApiError("后端开启了访问鉴权（VR_API_KEY）：请在「接入 AI」页底部填写后端访问密钥", 401);
    }
    throw new ApiError(payload?.detail || `HTTP ${resp.status}`, resp.status);
  }
  const result = unwrapData ? unwrapApiPayload(payload) : payload;
  return result as T;
}


export const get = <T>(path: string, options?: { unwrapData?: boolean; signal?: AbortSignal }) =>
  request<T>(path, "GET", undefined, options);

export const put = <T>(path: string, body: unknown, options?: { unwrapData?: boolean; signal?: AbortSignal }) =>
  request<T>(path, "PUT", body, options);


export function createNdjsonProtocolState(): NdjsonProtocolState {
  return {
    content: "",
    trace: [],
    rounds: 0,
    sawDone: false,
    sawError: false,
    errorMessage: null,
  };
}


/** Pure protocol transition used by streamNdjson and suitable for isolated tests. */
export function applyNdjsonLine(
  state: NdjsonProtocolState,
  line: string,
  handlers: NdjsonStreamHandlers = {},
): void {
  const text = line.trim();
  if (!text) return;
  let event: any;
  try {
    event = JSON.parse(text);
  } catch {
    state.sawError = true;
    state.errorMessage = "后端响应格式错误";
    return;
  }
  if (!event || typeof event !== "object") {
    state.sawError = true;
    state.errorMessage = "后端响应格式错误";
    return;
  }
  if (event.type === "delta") {
    if (state.sawDone || typeof event.text !== "string") {
      state.sawError = true;
      state.errorMessage = "后端响应完成顺序异常";
      return;
    }
    state.content += event.text;
    handlers.onDelta?.(event.text);
  } else if (event.type === "tool") {
    if (state.sawDone) {
      state.sawError = true;
      state.errorMessage = "后端响应完成顺序异常";
      return;
    }
    handlers.onTool?.(String(event.tool || ""), event.args || {});
  } else if (event.type === "done") {
    if (state.sawDone) {
      state.sawError = true;
      state.errorMessage = "后端重复发送完成信号";
      return;
    }
    state.sawDone = true;
    state.trace = Array.isArray(event.trace) ? event.trace : [];
    state.rounds = Number.isInteger(event.rounds) ? event.rounds : 0;
    if (event.result && typeof event.result === "object") {
      state.result = event.result as AiGeneratedResultMetadata;
    }
  } else if (event.type === "error") {
    state.sawError = true;
    state.errorMessage = typeof event.message === "string" && event.message.trim()
      ? event.message
      : "后端返回错误";
  } else {
    state.sawError = true;
    state.errorMessage = "后端响应包含未知事件";
  }
}


/**
 * 共享 NDJSON 流解析：每行一个事件 {type: tool|delta|done|error}。
 * path 为 /api 之后的路径，如 "/chat"、"/daily-review/analyze"。
 */
export async function streamNdjson(
  path: string,
  body: unknown,
  handlers: NdjsonStreamHandlers = {},
  signal?: AbortSignal,
): Promise<NdjsonStreamResult> {
  let resp: Response;
  try {
    resp = await fetch(`/api${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError("连接不到后端，请先启动 backend（uvicorn app:app --port 8900）", 0);
  }
  // 配置错误 / 上下文准备失败等：流开始前以 HTTP 状态返回
  if (!resp.ok) {
    let payload: any = null;
    try {
      payload = await resp.json();
    } catch {
      /* ignore */
    }
    if (resp.status === 401) {
      throw new ApiError("后端开启了访问鉴权（VR_API_KEY）：请在「接入 AI」页底部填写后端访问密钥", 401);
    }
    throw new ApiError(payload?.detail || `HTTP ${resp.status}`, resp.status);
  }
  if (!resp.body) throw new ApiError("后端无响应流", 502);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  const state = createNdjsonProtocolState();
  let buf = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop() ?? "";
      for (const line of lines) applyNdjsonLine(state, line, handlers);
    }
    buf += decoder.decode();
    if (buf.trim()) applyNdjsonLine(state, buf, handlers);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    if (typeof error === "object" && error !== null && "name" in error && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError("后端响应流意外中断", 502);
  } finally {
    reader.releaseLock();
  }
  if (state.sawError) throw new ApiError(state.errorMessage || "后端返回错误", 502);
  if (!state.sawDone) throw new ApiError("后端响应流未返回完成信号", 502);
  return { content: state.content, trace: state.trace, rounds: state.rounds, result: state.result };
}


/**
 * 每日复盘 AI 流式分析。只发送 user_request + llm；
 * 市场上下文与 system prompt 由服务器生成，客户端不可注入。
 */
export async function dailyReviewAnalyzeStream(
  request: DailyReviewAnalyzeRequest,
  handlers: NdjsonStreamHandlers = {},
  signal?: AbortSignal,
): Promise<NdjsonStreamResult> {
  return streamNdjson(
    "/daily-review/analyze",
    {
      user_request: request.user_request ?? null,
      llm: request.llm,
    },
    handlers,
    signal,
  );
}


export const api = {
  health: () => get<{ ok: boolean }>("/health"),
  indices: () => get<IndexQuote[]>("/indices"),
  marketOverview: () => get<MarketOverview>("/market/overview"),
  emotion: () => get<ShortTermEmotion>("/market/emotion"),
  turnoverTop: () => get<TurnoverTop>("/market/turnover-top"),
  /**
   * 结构化每日复盘聚合包（一次请求覆盖指数/广度/情绪/成交/板块）。
   * 保留 data；附带可选 cache_meta（stale 时前端可轮询）。
   */
  dailyReview: async (): Promise<{
    data: DailyReviewData;
    cache_meta?: DailyReviewCacheMeta | null;
  }> => {
    let resp: Response;
    const headers: Record<string, string> = { ...authHeaders() };
    const opts: RequestInit = { method: "GET" };
    if (Object.keys(headers).length > 0) opts.headers = headers;
    try {
      resp = await fetch("/api/daily-review", opts);
    } catch {
      throw new ApiError("连接不到后端，请先启动 backend（uvicorn app:app --port 8900）", 0);
    }
    let payload: any = null;
    try {
      payload = await resp.json();
    } catch {
      /* 非 JSON */
    }
    if (!resp.ok) {
      if (resp.status === 401) {
        throw new ApiError("后端开启了访问鉴权（VR_API_KEY）：请在「接入 AI」页底部填写后端访问密钥", 401);
      }
      throw new ApiError(payload?.detail || `HTTP ${resp.status}`, resp.status);
    }
    const data = (payload?.data ?? payload) as DailyReviewData;
    const cache_meta = (payload?.cache_meta ?? null) as DailyReviewCacheMeta | null;
    return { data, cache_meta };
  },
  /**
   * 用户显式刷新每日复盘完整包（绕过 300s 内存缓存）。
   * 与 GET 返回形状一致：{ data, cache_meta }；不写历史、不调用 AI。
   */
  dailyReviewRefresh: async (): Promise<{
    data: DailyReviewData;
    cache_meta?: DailyReviewCacheMeta | null;
  }> => {
    let resp: Response;
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...authHeaders(),
    };
    try {
      resp = await fetch("/api/daily-review/refresh", {
        method: "POST",
        headers,
        body: "{}",
      });
    } catch {
      throw new ApiError("连接不到后端，请先启动 backend（uvicorn app:app --port 8900）", 0);
    }
    let payload: any = null;
    try {
      payload = await resp.json();
    } catch {
      /* 非 JSON */
    }
    if (!resp.ok) {
      if (resp.status === 401) {
        throw new ApiError("后端开启了访问鉴权（VR_API_KEY）：请在「接入 AI」页底部填写后端访问密钥", 401);
      }
      throw new ApiError(payload?.detail || `HTTP ${resp.status}`, resp.status);
    }
    const data = (payload?.data ?? payload) as DailyReviewData;
    const cache_meta = (payload?.cache_meta ?? null) as DailyReviewCacheMeta | null;
    return { data, cache_meta };
  },
  /** 显式保存当前复盘快照（无请求体；服务器自行聚合校验） */
  saveDailyReviewHistory: () =>
    request<SaveDailyReviewHistoryResult>("/daily-review/history/save", "POST"),
  /** 历史元数据列表 */
  listDailyReviewHistory: (params?: {
    trade_date?: string;
    limit?: number;
    offset?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.trade_date) q.set("trade_date", params.trade_date);
    if (params?.limit != null) q.set("limit", String(params.limit));
    if (params?.offset != null) q.set("offset", String(params.offset));
    const qs = q.toString();
    return get<DailyReviewHistoryList>(`/daily-review/history${qs ? `?${qs}` : ""}`);
  },
  /** 历史快照详情 */
  getDailyReviewHistorySnapshot: (snapshotId: number) =>
    get<DailyReviewHistorySnapshot>(`/daily-review/history/${snapshotId}`),
  /** 历史快照结构化比较（服务端计算 delta/排名变化） */
  compareDailyReviewHistory: (params: {
    base_id: number;
    target_id: number;
    board_limit?: number;
    stock_limit?: number;
  }) => {
    const q = new URLSearchParams();
    q.set("base_id", String(params.base_id));
    q.set("target_id", String(params.target_id));
    if (params.board_limit != null) q.set("board_limit", String(params.board_limit));
    if (params.stock_limit != null) q.set("stock_limit", String(params.stock_limit));
    return get<DailyReviewComparison>(`/daily-review/history/compare?${q.toString()}`);
  },
  marketBreadth: () => get<TimedComponentEnvelope<MarketBreadthData>>("/market/breadth"),
  marketBoards: (type: "industry" | "concept" | "region" = "industry", topN = 20) =>
    get<TimedComponentEnvelope<BoardRankingData>>(`/market/boards?type=${type}&top_n=${topN}`),
  globalIndices: () => get<GlobalIndex[]>("/global/indices"),
  globalStock: (symbol: string) => get<GlobalStock>(`/global/stock?symbol=${encodeURIComponent(symbol)}`),
  radar: () => get<RadarData>("/radar"),
  radarRefresh: () => request<RadarData>("/radar/refresh", "POST"),
  portfolio: () => get<PortfolioData>("/portfolio"),
  addHolding: (code: string, shares: number, cost: number) => request<PortfolioData>("/portfolio/holding", "POST", { code, shares, cost }),
  updateHolding: (code: string, shares: number, cost: number) =>
    request<PortfolioData>("/portfolio/holding", "PUT", { code, shares, cost }),
  removeHolding: (code: string) => request<PortfolioData>(`/portfolio/holding?code=${code}`, "DELETE"),
  refreshPortfolio: () => request<PortfolioData>("/portfolio/refresh", "POST"),
  closePosition: (code: string, date: string, price: number, shares: number, cost: number) =>
    request<PortfolioData>("/portfolio/close", "POST", { code, date, price, shares, cost }),
  removeClosed: (index: number) => request<PortfolioData>(`/portfolio/close?index=${index}`, "DELETE"),
  /** 账户资金。未配置 → configured=false, data=null；不把未配置解释为 0。 */
  getAccountProfile: () => get<AccountProfileResponse>("/account-profile", { unwrapData: false }),
  /**
   * 保存账户资金（后端校验 + 生成 updated_at）。
   * 返回 { configured: true, data: { total_assets, available_cash, updated_at } }。
   */
  saveAccountProfile: (data: AccountProfileRequest) =>
    put<AccountProfileResponse>("/account-profile", {
      total_assets: data.total_assets,
      available_cash: data.available_cash,
    }, { unwrapData: false }),
  /**
   * 结构化持仓操作建议（普通 JSON）。
   * 只发送 user_request + llm；持仓与市场上下文由服务器读取，不注入 portfolio/context/messages。
   */
  portfolioAdvice: (req: PortfolioAdviceRequest, signal?: AbortSignal) =>
    request<PortfolioAdviceResult>("/portfolio/advice", "POST", {
      user_request: req.user_request ?? null,
      llm: req.llm,
    }, { signal }),
  aiResult: <TPayload>(
    resultType: AiResultType,
    tradeDate?: string | null,
    signal?: AbortSignal,
  ) => {
    const query = tradeDate ? `?trade_date=${encodeURIComponent(tradeDate)}` : "";
    return get<AiGeneratedResult<TPayload> | null>(`/ai-results/${resultType}${query}`, { signal });
  },
  valuation: (code: string) => get<Valuation>(`/valuation?code=${code}`),
  percentile: (code: string) => get<ValPercentile>(`/valuation/percentile?code=${code}`),
  financials: (code: string) => get<Financials>(`/financials?code=${code}`),
  announcements: (code: string) => get<Announcement[]>(`/announcements?code=${code}`),
  quote: (codes: string) => get<Record<string, Quote>>(`/quote?codes=${codes}`),
  reports: (code: string) => get<Report[]>(`/reports?code=${code}`),
  news: (code: string) => get<NewsItem[]>(`/news?code=${code}`),
  margin: (code: string) => get<MarginRow[]>(`/margin?code=${code}`),
  blockTrade: (code: string) => get<BlockTradeRow[]>(`/block-trade?code=${code}`),
  holders: (code: string) => get<HolderRow[]>(`/holders?code=${code}`),
  dividend: (code: string) => get<DividendRow[]>(`/dividend?code=${code}`),
  fundFlow: (code: string) => get<FundFlowRow[]>(`/fund-flow?code=${code}`),
  dragonTiger: (code: string) => get<DragonTiger>(`/dragon-tiger?code=${code}`),
  lockup: (code: string) => get<Lockup>(`/lockup?code=${code}`),
  blocks: (code: string) => get<Blocks>(`/blocks?code=${code}`),
  hotConcepts: (code: string) => get<HotConcept[]>(`/hot-concepts?code=${code}`),
  investorQa: (code: string) => get<QaRow[]>(`/investor-qa?code=${code}`),
  industry: (top = 20) => get<IndustryData>(`/industry?top=${top}`),
  /** K 线（需 mootdx）：category 4=日 5=周 6=月 11=60分钟；依赖缺失抛 501。 */
  kline: (code: string, category = 4, offset = 60) =>
    get<KlineBar[]>(`/kline?code=${code}&category=${category}&offset=${offset}`),
  /** 季报财务快照（需 mootdx，37 字段）；依赖缺失抛 501。 */
  finance: (code: string) => get<Record<string, string | number | null>>(`/finance?code=${code}`),
  /** 个股基本面：行业 / 总股本 / 上市时间等（需 akshare）；依赖缺失抛 501。 */
  info: (code: string) => get<Record<string, string | number>>(`/info?code=${code}`),
  /** 巨潮公告全文列表（需 akshare，备用源）；依赖缺失抛 501。 */
  disclosure: (code: string) => get<DisclosureItem[]>(`/disclosure?code=${code}`),
  myReports: () => get<MyReport[]>("/myreports"),
  uploadReport: (name: string, contentB64: string, meta?: {
    title?: string; institution?: string; publish_date?: string;
    sector_keys?: string[]; source_url?: string; source_kind?: string;
  }) =>
    request<MyReport>("/myreports", "POST", {
      name, content_b64: contentB64,
      ...(meta?.title != null ? { title: meta.title } : {}),
      ...(meta?.institution != null ? { institution: meta.institution } : {}),
      ...(meta?.publish_date != null ? { publish_date: meta.publish_date } : {}),
      ...(meta?.sector_keys != null ? { sector_keys: meta.sector_keys } : {}),
      ...(meta?.source_url != null ? { source_url: meta.source_url } : {}),
      ...(meta?.source_kind != null ? { source_kind: meta.source_kind } : {}),
    }),
  deleteReport: (id: string) => request<{ ok: boolean }>(`/myreports/${id}`, "DELETE"),
  // 注意：get()/request() 已自动加 /api 前缀，这里只传 /myreports/... 即可，禁止重复 /api。
  browseMyReports: (group: MyReportsBrowseGroup, sectorKey?: string) => {
    const q = new URLSearchParams({ group });
    if (sectorKey) q.set("sector_key", sectorKey);
    return get<MyReportsBrowseResult>(`/myreports/browse?${q.toString()}`);
  },
  searchMyReports: (q: string) =>
    get<MyReport[]>(`/myreports/search?q=${encodeURIComponent(q)}`),
  patchReport: (id: string, meta: {
    title?: string; institution?: string; publish_date?: string;
    sector_keys?: string[]; source_url?: string; source_kind?: string;
  }) => {
    const body: Record<string, unknown> = {};
    for (const k of ["title", "institution", "publish_date", "sector_keys", "source_url", "source_kind"] as const) {
      if (meta[k] !== undefined) body[k] = meta[k];
    }
    return request<MyReport>(`/myreports/${id}`, "PATCH", body);
  },

  /**
   * 板块研报发现（不自动归档）。
   * 注意：get()/request() 已自动加 /api 前缀，路径禁止写 /api/...
   */
  discoverSectorReports: (
    sectorKey: string,
    opts?: { days?: number; maxPages?: number; scope?: SectorReportScope },
  ) => {
    const q = new URLSearchParams();
    if (opts?.days != null) q.set("days", String(opts.days));
    if (opts?.maxPages != null) q.set("max_pages", String(opts.maxPages));
    if (opts?.scope) q.set("scope", opts.scope);
    const qs = q.toString();
    return get<SectorReportsDiscoveryResult>(
      `/sector-research/reports/${encodeURIComponent(sectorKey)}${qs ? `?${qs}` : ""}`,
    );
  },

  /** 导入发现研报到我的研报：body 仅 { external_id } */
  importSectorReport: (sectorKey: string, externalId: string) =>
    request<MyReport>(`/sector-research/import/${encodeURIComponent(sectorKey)}`, "POST", {
      external_id: externalId,
    }),

  /** 板块动态数据（一致预期 / 公告等） */
  getSectorResearchData: (sectorKey: string) =>
    get<SectorDynamicData>(`/sector-research/data/${encodeURIComponent(sectorKey)}`),

  // -------------------------------------------------------------------------
  // 投资逻辑与证据账本（Investment Thesis & Evidence Ledger）
  // 注意：get()/request() 已自动加 /api 前缀，路径禁止写 /api/...
  // -------------------------------------------------------------------------

  // ---- Evidence ----
  evidenceList: (params?: {
    subject_type?: string;
    subject_id?: string;
    limit?: number;
    offset?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.subject_type) q.set("subject_type", params.subject_type);
    if (params?.subject_id) q.set("subject_id", params.subject_id);
    if (params?.limit != null) q.set("limit", String(params.limit));
    if (params?.offset != null) q.set("offset", String(params.offset));
    const qs = q.toString();
    return get<EvidenceListResult>(`/evidence${qs ? `?${qs}` : ""}`);
  },
  evidenceCreate: (body: EvidenceCreateInput) =>
    request<EvidenceRecord>("/evidence", "POST", body),
  evidenceGet: (id: string) => get<EvidenceRecord>(`/evidence/${id}`),
  evidenceUpdate: (id: string, body: EvidenceUpdateInput) =>
    request<EvidenceRecord>(`/evidence/${id}`, "PUT", body),
  evidenceDelete: (id: string) =>
    request<EvidenceRecord>(`/evidence/${id}?confirm=true`, "DELETE"),

  // ---- Thesis ----
  thesisList: (params?: {
    subject_type?: string;
    subject_id?: string;
    status?: string;
    limit?: number;
    offset?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.subject_type) q.set("subject_type", params.subject_type);
    if (params?.subject_id) q.set("subject_id", params.subject_id);
    if (params?.status) q.set("status", params.status);
    if (params?.limit != null) q.set("limit", String(params.limit));
    if (params?.offset != null) q.set("offset", String(params.offset));
    const qs = q.toString();
    return get<ThesisListResult>(`/thesis${qs ? `?${qs}` : ""}`);
  },
  thesisCreate: (body: ThesisCreateInput) => request<ThesisAggregate>("/thesis", "POST", body),
  thesisGet: (id: string) => get<ThesisAggregate>(`/thesis/${id}`),
  thesisUpdate: (id: string, body: ThesisUpdateInput) => request<ThesisAggregate>(`/thesis/${id}`, "PUT", body),
  thesisArchive: (id: string, expected_revision: number, change_summary?: string) => {
    const q = new URLSearchParams({ confirm: "true", expected_revision: String(expected_revision) });
    if (change_summary) q.set("change_summary", change_summary);
    return request<ThesisAggregate>(`/thesis/${id}?${q.toString()}`, "DELETE");
  },
  thesisRevisions: (id: string) => get<RevisionListResult>(`/thesis/${id}/revisions`),
  thesisRevision: (id: string, rev: number) => get<ThesisRevision>(`/thesis/${id}/revisions/${rev}`),
  thesisDiff: (id: string, fromRev: number, toRev: number) =>
    get<ThesisDiff>(`/thesis/${id}/diff?from=${fromRev}&to=${toRev}`),

  // ---- Thesis ↔ Evidence Link ----
  thesisLinkEvidence: (id: string, body: LinkEvidenceInput) =>
    request<ThesisAggregate>(`/thesis/${id}/evidence`, "POST", body),
  thesisUpdateStance: (id: string, evidenceId: string, body: UpdateStanceInput) =>
    request<ThesisAggregate>(`/thesis/${id}/evidence/${evidenceId}`, "PUT", body),
  thesisUnlinkEvidence: (id: string, evidenceId: string, expected_revision: number, change_summary?: string) => {
    const q = new URLSearchParams({ expected_revision: String(expected_revision) });
    if (change_summary) q.set("change_summary", change_summary);
    return request<ThesisAggregate>(`/thesis/${id}/evidence/${evidenceId}?${q.toString()}`, "DELETE");
  },
};
