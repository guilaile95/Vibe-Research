// Vibe-Research 后端 API 客户端。/api → vite 代理到本地 FastAPI（默认 8900）。
// 后端未启动或数据源异常时抛 ApiError，页面据此优雅降级。
// 纯类型定义见 ./api/types.ts；本文件仅保留运行时客户端。

export type * from "./api/types.ts";

import type { MarketCloudEnvelope } from "./marketCloud.ts";
import type {
  MyReport,
  MyReportTextHit,
  MyReportTextIndexPreview,
  MyReportTextIndexBatchResult,
  IntelDigestLatestResult,
  IntelDigestSaveIn,
  IntelDigestSaveResult,
  MyReportsBrowseGroup,
  MyReportsBrowseResult,
  SectorReportScope,
  SectorReportsDiscoveryResult,
  SectorDynamicData,
  SectorMarketContextData,
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
  NativeIntelStatus,
  NativeIntelItemsResponse,
  NativeIntelTrending,
  NativeIntelSecurityContext,
  NativeIntelWatchlistContext,
  NativeIntelRefreshResult,
  PortfolioData,
  PositionBootstrapInput,
  PositionBootstrapPreview,
  PositionBootstrapCommitResult,
  DerivedPositionsResult,
  AccountProfileResponse,
  AccountProfileRequest,
  AccountReality,
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
  HkCashflow,
  GpuRentData,
  NorthboundCapitalFlow,
  TechnicalIndicators,
  TopRiskAnalysis,
  DailyReviewAnalyzeRequest,
  NdjsonStreamHandlers,
  NdjsonStreamResult,
  NdjsonProtocolState,
  EvidenceRecord,
  EvidenceTemporalAuthority,
  EvidenceTemporalIntakeInput,
  EvidenceCreateInput,
  EvidenceUpdateInput,
  EvidenceListResult,
  ThesisCreateInput,
  ThesisUpdateInput,
  TradeOperation,
  TradeExecutionStatus,
  TradeRecord,
  TradeCreateInput,
  TradeAttributionCandidateScan,
  TradeReconciliationResult,
  DecisionFeedbackAdoptionStatus,
  DecisionFeedbackOutcomeStatus,
  DecisionFeedbackRecord,
  DecisionFeedbackCreateInput,
  ThesisAggregate,
  ThesisListResult,
  ThesisRevision,
  RevisionListResult,
  ThesisDiff,
  LinkEvidenceInput,
  UpdateStanceInput,
  FormalThesisSnapshot,
  CampaignThesisBinding,
  CampaignCurrentThesis,
  DataHealthOverviewResult,
  DataHealthDetailResult,
  DecisionEvidenceDetailResult,
  DecisionEvidenceListResult,
  SignalLedgerQueryResult,
  SignalLedgerRunDetailResult,
  AccountExecutionPolicy,
  AccountExecutionPolicyResponse,
  AdoptionSummary,
  OutcomeSummary,
  StockAnalyticsItem,
  FormalDecisionOutcome,
  FormalDecisionReviewWorklist,
  AttributionResult,
  AttributionSnapshotSummary,
  AttributionSnapshotListResult,
  AttributionSnapshotDetailResult,
  Bk11HistoryEnvelope,
  CampaignRecord,
  CampaignStrategy,
  CampaignStatus,
  CampaignTransitionRecord,
  CampaignTransitionResult,
  CampaignTradeActivationResult,
  CampaignNextActions,
  DecisionInboxSnapshot,
  DecisionProposalDraftInput,
  DecisionProposalPreview,
  DecisionProposalDraftWitness,
  CampaignAIDraftGenerateResult,
  ResearchContinuity,
  DecisionProposalCommitResult,
  CommittedDecisionRuntimeRead,
  StreamLlmConfig,
} from "./api/types.ts";


export class ApiError extends Error {
  readonly status: number;
  /** 后端结构化 detail（如 Portfolio Advice 的 {message,error_code,stage,reason}），无则为 undefined。 */
  readonly detail?: unknown;
  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export class DecisionChallengeReadError extends Error {
  constructor(message = "Decision Challenge readback 格式无效") {
    super(message);
  }
}

export class CommittedDecisionReadError extends Error {
  constructor(message = "COMMITTED_DECISION_READ_ERROR：Committed Decision durable readback 格式无效") {
    super(message);
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
    const rawDetail = payload?.detail;
    // 结构化 detail（对象）取其 message 字段做兜底文案，并保留原始对象供上层解析
    const detailText =
      typeof rawDetail === "string"
        ? rawDetail
        : rawDetail && typeof rawDetail === "object" && typeof (rawDetail as { message?: unknown }).message === "string"
          ? (rawDetail as { message: string }).message
          : undefined;
    throw new ApiError(payload?.error || detailText || payload?.message || `HTTP ${resp.status}`, resp.status, rawDetail);
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
  marketNorthbound: () => get<NorthboundCapitalFlow>("/market/northbound"),
  marketCloud: (scope: string, period: string, signal?: AbortSignal) =>
    get<MarketCloudEnvelope>(
      `/market/cloud?scope=${encodeURIComponent(scope)}&period=${encodeURIComponent(period)}`,
      signal ? { signal } : undefined,
    ),
  /** BK-11 短线市场历史（只读；有界窗口，默认最近 5 个交易日） */
  bk11History: (days = 5, signal?: AbortSignal) =>
    get<Bk11HistoryEnvelope>(
      `/market/bk11-history?days=${days}`,
      signal ? { signal } : undefined,
    ),
  /** 顶部风险分析（影子模式，第一版）：按股票代码分析，signal 恒 unknown、不参与最终结论。 */
  topRisk: (code: string, days = 120) =>
    get<TopRiskAnalysis>(
      `/market/top-risk?code=${encodeURIComponent(code)}${days != null ? `&days=${days}` : ""}`,
    ),
  marketBoards: (type: "industry" | "concept" | "region" = "industry", topN = 20) =>
    get<TimedComponentEnvelope<BoardRankingData>>(`/market/boards?type=${type}&top_n=${topN}`),
  globalIndices: () => get<GlobalIndex[]>("/global/indices"),
  globalStock: (symbol: string) => get<GlobalStock>(`/global/stock?symbol=${encodeURIComponent(symbol)}`),
  hkCashflow: (symbol: string) => get<HkCashflow>(`/global/hk/cashflow?symbol=${encodeURIComponent(symbol)}`),
  // ---- Native Intel（NATIVE-INTEL1，Vibe 本地持久化，无 sidecar / MCP）----
  nativeIntelStatus: () =>
    get<NativeIntelStatus>("/native-intel/status", { unwrapData: false }),
  nativeIntelItems: (limit = 30, signal?: AbortSignal) =>
    get<NativeIntelItemsResponse>(
      `/native-intel/items?limit=${limit}&order_by=last_seen`,
      { unwrapData: false, ...(signal ? { signal } : {}) },
    ),
  nativeIntelRefresh: () =>
    request<NativeIntelRefreshResult>("/native-intel/refresh", "POST", undefined, { unwrapData: false }),
  nativeIntelTrending: (windowHours = 24, topN = 20) =>
    get<NativeIntelTrending>(
      `/native-intel/trending?window_hours=${windowHours}&top_n=${topN}`,
      { unwrapData: false },
    ),
  nativeIntelSecurityContext: (code: string, signal?: AbortSignal) =>
    get<NativeIntelSecurityContext>(
      `/native-intel/security-context/${encodeURIComponent(code)}`,
      signal ? { signal } : undefined,
    ),
  nativeIntelWatchlistContext: (signal?: AbortSignal) =>
    get<NativeIntelWatchlistContext>(
      "/native-intel/watchlist-context",
      signal ? { signal } : undefined,
    ),
  radar: () => get<RadarData>("/radar"),
  radarRefresh: () => request<RadarData>("/radar/refresh", "POST"),
  gpuRent: () => get<GpuRentData>("/signals/gpu-rent"),
  gpuRentRefresh: () => request<GpuRentData>("/signals/gpu-rent/refresh", "POST"),
  getIntelDigestLatest: (sectorKey: string) =>
    get<IntelDigestLatestResult>(`/intel-digests/latest?sector_key=${encodeURIComponent(sectorKey)}`, { unwrapData: false }),
  saveIntelDigest: (payload: IntelDigestSaveIn, signal?: AbortSignal) =>
    request<IntelDigestSaveResult>("/intel-digests", "POST", payload, { signal }),
  portfolio: () => get<PortfolioData>("/portfolio"),
  /**
   * 账户初始化（P0-AB2）：仅复用 stable 既有 position reality authority。
   * preview 零写；commit 由用户显式确认后才允许调用。
   */
  positionBootstrapPreview: (payload: PositionBootstrapInput) =>
    request<PositionBootstrapPreview>(
      "/position/bootstrap-preview",
      "POST",
      payload,
    ),
  positionBootstrapCommit: (payload: PositionBootstrapInput) =>
    request<PositionBootstrapCommitResult>(
      "/position/bootstrap-commit",
      "POST",
      payload,
    ),
  getDerivedPositions: () =>
    get<DerivedPositionsResult>("/position/derived"),
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
      confirm_current: data.confirm_current,
    }, { unwrapData: false }),
  /** 只读账户现实（P1-CASH1）：canonical ledger cash candidate 与 manual fact 的对账 read model。 */
  getAccountReality: () => get<AccountReality>("/account/reality"),
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
  /** 技术指标与价格触发（SMA/EMA/MACD/RSI/布林带/5-20 日均量比）；依赖缺失抛 501。 */
  technicalIndicators: (code: string, period = "daily", days = 120) =>
    get<TechnicalIndicators>(`/market/technical-indicators?code=${code}&period=${period}&days=${days}`),
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
  searchMyReportText: (q: string, reportIds?: string[], limit = 20) => {
    const params = new URLSearchParams({ q, limit: String(limit) });
    for (const reportId of reportIds ?? []) params.append("report_ids", reportId);
    return get<MyReportTextHit[]>(`/myreports/fulltext-search?${params.toString()}`);
  },
  previewMyReportTextIndex: (reportIds?: string[]) => {
    const params = new URLSearchParams();
    for (const reportId of reportIds ?? []) params.append("report_ids", reportId);
    const query = params.toString();
    return get<MyReportTextIndexPreview>(`/myreports/text-index/preview${query ? `?${query}` : ""}`);
  },
  indexMyReportText: (id: string) =>
    request<MyReport>(`/myreports/${id}/text-index`, "POST", {}),
  batchIndexMyReportText: (reportIds: string[]) =>
    request<MyReportTextIndexBatchResult>("/myreports/text-index/batch", "POST", {
      report_ids: reportIds,
      confirm: true,
    }),
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

  /** 显式 THS 映射的板块强度；传 key 时补当前成分股截面。 */
  getSectorMarketContext: (sectorKey?: string) =>
    get<SectorMarketContextData>(
      `/sector-research/market-context${sectorKey ? `?sector_key=${encodeURIComponent(sectorKey)}` : ""}`,
    ),

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
  evidenceTemporalAuthority: (id: string, evaluationAsOf?: string) => {
    const qs = evaluationAsOf ? `?evaluation_as_of=${encodeURIComponent(evaluationAsOf)}` : "";
    return get<EvidenceTemporalAuthority>(`/evidence/${encodeURIComponent(id)}/temporal-authority${qs}`);
  },
  evidenceTemporalIntake: (id: string, body: EvidenceTemporalIntakeInput) =>
    request<EvidenceTemporalAuthority>(`/evidence/${encodeURIComponent(id)}/temporal-authority`, "POST", body),

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
  // P0-CT1：Thesis Formal 化（LEGACY→DRAFT→CONFIRMED→FROZEN；端点与 backend 逐字一致）
  thesisBeginFormalization: (id: string) =>
    request<ThesisAggregate>(`/thesis/${encodeURIComponent(id)}/begin-formalization`, "POST"),
  thesisConfirm: (id: string, expected_revision: number) =>
    request<ThesisAggregate>(`/thesis/${encodeURIComponent(id)}/confirm`, "POST", { expected_revision }),
  thesisFreeze: (id: string, expected_revision: number) =>
    request<FormalThesisSnapshot>(`/thesis/${encodeURIComponent(id)}/freeze`, "POST", { expected_revision }),
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

  // ---- 数据健康中心（只读）----
  getDataHealth: (params?: {
    module?: string;
    status?: string;
    is_stale?: boolean;
    blocks_advice?: boolean;
  }) => {
    const q = new URLSearchParams();
    if (params?.module) q.set("module", params.module);
    if (params?.status) q.set("status", params.status);
    if (params?.is_stale != null) q.set("is_stale", String(params.is_stale));
    if (params?.blocks_advice != null) q.set("blocks_advice", String(params.blocks_advice));
    const qs = q.toString();
    return get<DataHealthOverviewResult>(`/data-health${qs ? `?${qs}` : ""}`);
  },
  getDataHealthSource: (sourceId: string) =>
    get<DataHealthDetailResult>(`/data-health/${encodeURIComponent(sourceId)}`),

  // ---- 交易流水 ----
  listTrades: (params?: {
    code?: string;
    operation?: TradeOperation;
    execution_status?: TradeExecutionStatus;
    date_from?: string;
    date_to?: string;
    include_voided?: boolean;
    limit?: number;
    offset?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.code) q.set("code", params.code);
    if (params?.operation) q.set("operation", params.operation);
    if (params?.execution_status) q.set("execution_status", params.execution_status);
    if (params?.date_from) q.set("date_from", params.date_from);
    if (params?.date_to) q.set("date_to", params.date_to);
    if (params?.include_voided != null) q.set("include_voided", String(params.include_voided));
    if (params?.limit != null) q.set("limit", String(params.limit));
    if (params?.offset != null) q.set("offset", String(params.offset));
    const qs = q.toString();
    return get<TradeRecord[]>(`/trades${qs ? `?${qs}` : ""}`);
  },
  getTrade: (tradeId: string) => get<TradeRecord>(`/trades/${encodeURIComponent(tradeId)}`),
  createTrade: (body: TradeCreateInput) => request<TradeRecord>("/trades", "POST", body),
  voidTrade: (tradeId: string, reason: string) =>
    request<TradeRecord>(`/trades/${encodeURIComponent(tradeId)}/void`, "POST", { reason }),
  listTradeAttributionCandidates: (tradeId: string) =>
    get<TradeAttributionCandidateScan>(`/trades/${encodeURIComponent(tradeId)}/attribution-candidates`),
  getTradeReconciliation: (tradeId: string) =>
    get<TradeReconciliationResult>(`/trades/${encodeURIComponent(tradeId)}/reconciliation`),
  attributeTrade: (tradeId: string, decisionId: string) =>
    request<{ record: Record<string, unknown>; idempotent: boolean }>(`/trades/${encodeURIComponent(tradeId)}/attribution`, "POST", { decision_id: decisionId }),
  markTradeUnplanned: (tradeId: string) =>
    request<{ record: Record<string, unknown>; idempotent: boolean }>(`/trades/${encodeURIComponent(tradeId)}/unplanned`, "POST", { confirm: true }),

  // ---- 决策反馈 ----
  listDecisionFeedbacks: (params?: {
    code?: string;
    adoption_status?: DecisionFeedbackAdoptionStatus | string;
    outcome_status?: DecisionFeedbackOutcomeStatus | string;
    date_from?: string;
    date_to?: string;
    include_voided?: boolean;
    limit?: number;
    offset?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.code) q.set("code", params.code);
    if (params?.adoption_status) q.set("adoption_status", params.adoption_status);
    if (params?.outcome_status) q.set("outcome_status", params.outcome_status);
    if (params?.date_from) q.set("date_from", params.date_from);
    if (params?.date_to) q.set("date_to", params.date_to);
    if (params?.include_voided != null) q.set("include_voided", String(params.include_voided));
    if (params?.limit != null) q.set("limit", String(params.limit));
    if (params?.offset != null) q.set("offset", String(params.offset));
    const qs = q.toString();
    return get<DecisionFeedbackRecord[]>(`/decision-feedback${qs ? `?${qs}` : ""}`);
  },
  getDecisionFeedback: (feedbackId: string) =>
    get<DecisionFeedbackRecord>(`/decision-feedback/${encodeURIComponent(feedbackId)}`),
  createDecisionFeedback: (body: DecisionFeedbackCreateInput) => {
    const { advice_trade_date, advice_generated_at, ...payload } = body as any;
    return request<DecisionFeedbackRecord>("/decision-feedback", "POST", payload);
  },
  voidDecisionFeedback: (feedbackId: string, reason?: string) =>
    request<DecisionFeedbackRecord>(
      `/decision-feedback/${encodeURIComponent(feedbackId)}/void`,
      "POST",
      reason != null ? { reason } : {},
    ),

  // ---- 决策依据与可解释性 (P2-1) ----
  listDecisionEvidence: (params?: {
    code?: string;
    symbol?: string;
    trade_date?: string;
    quality_status?: string;
    trace_status?: string;
    page?: number;
    limit?: number;
    offset?: number;
    page_size?: number;
  }) => listDecisionEvidence(params),
  getDecisionEvidence: (runId: string) => getDecisionEvidence(runId),
  getDecisionEvidenceByAdvice: (params: string | { advice_id?: string; trade_date?: string; generated_at?: string; code?: string; symbol?: string }) =>
    getDecisionEvidenceByAdvice(params),

  // ---- 信号账本 (P2-2) ----
  listSignalEntries: (params?: {
    decision_run_id?: string;
    stage?: string;
    code?: string;
    severity?: string;
    limit?: number;
    offset?: number;
  }) => listSignalEntries(params),
  getRunSignalLedger: (decisionRunId: string) => getRunSignalLedger(decisionRunId),

  // ---- 账户资金执行策略 (P2-3) ----
  getAccountExecutionPolicy(): Promise<AccountExecutionPolicyResponse> {
    return get<AccountExecutionPolicyResponse>("/account-execution-policy", { unwrapData: false });
  },
  updateAccountExecutionPolicy(body: AccountExecutionPolicy): Promise<AccountExecutionPolicyResponse> {
    return request<AccountExecutionPolicyResponse>(
      "/account-execution-policy",
      "PUT",
      body,
      { unwrapData: false },
    );
  },

  // ---- 决策绩效分析 (P2-4A) ----
  getAdoptionSummary(params?: { date_from?: string; date_to?: string }): Promise<AdoptionSummary> {
    return getAdoptionSummary(params);
  },
  getOutcomeSummary(params?: {
    adoption_status?: string;
    date_from?: string;
    date_to?: string;
  }): Promise<OutcomeSummary> {
    return getOutcomeSummary(params);
  },
  getStockAnalytics(params?: {
    date_from?: string;
    date_to?: string;
    limit?: number;
  }): Promise<StockAnalyticsItem[]> {
    return getStockAnalytics(params);
  },

  // ---- Formal Decision Outcome (P0-OL1); separate from legacy analytics ----
  getFormalDecisionReviewWorklist: () =>
    get<FormalDecisionReviewWorklist>("/formal-decision-review-worklist"),
  listFormalDecisionOutcomes: (params?: {
    evaluation_as_of?: string;
    limit?: number;
    offset?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.evaluation_as_of) q.set("evaluation_as_of", params.evaluation_as_of);
    if (params?.limit != null) q.set("limit", String(params.limit));
    if (params?.offset != null) q.set("offset", String(params.offset));
    const qs = q.toString();
    return get<FormalDecisionOutcome[]>(`/formal-decision-outcomes${qs ? `?${qs}` : ""}`);
  },
  getFormalDecisionOutcome: (decisionId: string, evaluationAsOf?: string) => {
    const q = new URLSearchParams();
    if (evaluationAsOf) q.set("evaluation_as_of", evaluationAsOf);
    const qs = q.toString();
    return get<FormalDecisionOutcome>(
      `/formal-decisions/${encodeURIComponent(decisionId)}/outcome${qs ? `?${qs}` : ""}`,
    );
  },

  // ---- 收益归因 (P2-4B) ----
  getPerformanceAttribution: (params?: { date_from?: string; date_to?: string }) =>
    getPerformanceAttribution(params),
  createAttributionSnapshot: (body?: { date_from?: string; date_to?: string; price_map?: Record<string, number> }) =>
    createAttributionSnapshot(body),
  listAttributionSnapshots: (params?: { date_from?: string; date_to?: string; limit?: number; offset?: number }) =>
    listAttributionSnapshots(params),
  getAttributionSnapshot: (snapshotId: string) => getAttributionSnapshot(snapshotId),

  // ---- Campaign（P0-CS1）----
  listCampaigns: (params?: { security_code?: string; strategy?: CampaignStrategy; status?: CampaignStatus }) =>
    listCampaigns(params),
  createCampaign: (securityCode: string, strategy: CampaignStrategy) =>
    createCampaign(securityCode, strategy),
  getCampaign: (campaignId: string) => getCampaign(campaignId),
  transitionCampaign: (campaignId: string, expectedStatus: CampaignStatus, toStatus: CampaignStatus) =>
    transitionCampaign(campaignId, expectedStatus, toStatus),
  activateCampaignFromTrade: (campaignId: string, tradeId: string) =>
    activateCampaignFromTrade(campaignId, tradeId),
  getCampaignTransitions: (campaignId: string) => getCampaignTransitions(campaignId),
  getCampaignNextActions: (campaignId: string) => getCampaignNextActions(campaignId),
  // P0-CT1：Campaign ↔ Formal Thesis 绑定 / Current Thesis 投影
  bindCampaignThesis: (campaignId: string, thesisId: string) =>
    bindCampaignThesis(campaignId, thesisId),
  getCampaignThesisBinding: (campaignId: string) => getCampaignThesisBinding(campaignId),
  getCampaignCurrentThesis: (campaignId: string) => getCampaignCurrentThesis(campaignId),
  getResearchContinuity: (campaignId: string) => getResearchContinuity(campaignId),
  generateCampaignAIDraft: (campaignId: string, llm: StreamLlmConfig) =>
    generateCampaignAIDraft(campaignId, llm),
  previewDecisionProposal: (campaignId: string, body: DecisionProposalDraftInput) =>
    previewDecisionProposal(campaignId, body),
  commitDecisionProposal: (
    campaignId: string,
    body: DecisionProposalDraftInput & {
      as_of: string;
      expected_proposal_fingerprint: string;
      user_confirmed: true;
      challenge_id?: string;
    },
  ) => commitDecisionProposal(campaignId, body),
  getCommittedDecisionRuntime: (campaignId: string, decisionId: string) =>
    getCommittedDecisionRuntime(campaignId, decisionId),
  finalizeDecisionChallenge: (
    campaignId: string,
    body: DecisionChallengeFinalizeInput,
  ) => finalizeDecisionChallenge(campaignId, body),
  getDecisionChallenge: (challengeId: string) => getDecisionChallenge(challengeId),
  getDecisionChallengeForProposal: (campaignId: string, proposalFingerprint: string) =>
    getDecisionChallengeForProposal(campaignId, proposalFingerprint),
  getDecisionInbox: () => getDecisionInbox(),
};

export async function listDecisionEvidence(params?: {
  code?: string;
  symbol?: string;
  trade_date?: string;
  quality_status?: string;
  trace_status?: string;
  page?: number;
  limit?: number;
  offset?: number;
  page_size?: number;
}): Promise<DecisionEvidenceListResult> {
  const q = new URLSearchParams();
  const stockCode = params?.code || params?.symbol;
  if (stockCode) q.set("code", stockCode);
  if (params?.trade_date) q.set("trade_date", params.trade_date);
  if (params?.quality_status) q.set("quality_status", params.quality_status);
  if (params?.trace_status) q.set("trace_status", params.trace_status);

  const limitVal = params?.limit || params?.page_size || 50;
  const offsetVal = params?.offset ?? ((params?.page ? params.page - 1 : 0) * limitVal);
  q.set("limit", String(limitVal));
  q.set("offset", String(offsetVal));

  const qs = q.toString();
  const res = await get<any>(`/decision-evidence${qs ? `?${qs}` : ""}`);
  if (Array.isArray(res)) {
    return {
      items: res,
      total: res.length,
      page: params?.page || 1,
      limit: limitVal,
      offset: offsetVal,
      total_pages: Math.ceil(res.length / limitVal) || 1,
    };
  }
  if (res && Array.isArray(res.items)) {
    const total = typeof res.total === "number" ? res.total : res.items.length;
    const page = params?.page || Math.floor((res.offset ?? offsetVal) / limitVal) + 1;
    return {
      items: res.items,
      total,
      page,
      limit: res.limit || limitVal,
      offset: res.offset ?? offsetVal,
      total_pages: Math.ceil(total / limitVal) || 1,
    };
  }
  return (res as DecisionEvidenceListResult) || { items: [], total: 0, page: 1, limit: limitVal };
}

export async function getDecisionEvidence(runId: string): Promise<DecisionEvidenceDetailResult> {
  const res = await get<any>(`/decision-evidence/${encodeURIComponent(runId)}`);
  const data = unwrapApiPayload(res);
  return {
    run: data?.run || data?.decision_run,
    decision_run: data?.decision_run || data?.run,
    evidence_items: data?.evidence_items || [],
    explanations: data?.explanations || data?.explanation_items || [],
    explanation_items: data?.explanation_items || data?.explanations || [],
    missing_evidences: data?.missing_evidences || (data?.evidence_items ? data.evidence_items.filter((i: any) => i.is_missing || i.quality_status === "missing") : []),
  };
}

export async function getDecisionEvidenceByAdvice(params: string | {
  advice_id?: string;
  trade_date?: string;
  generated_at?: string;
  code?: string;
  symbol?: string;
}): Promise<DecisionEvidenceDetailResult> {
  let url = "";
  if (typeof params === "string") {
    url = `/decision-evidence/by-advice?advice_id=${encodeURIComponent(params)}`;
  } else {
    const q = new URLSearchParams();
    if (params.advice_id) q.set("advice_id", params.advice_id);
    if (params.trade_date) q.set("trade_date", params.trade_date);
    if (params.generated_at) q.set("generated_at", params.generated_at);
    const stockCode = params.code || params.symbol;
    if (stockCode) q.set("code", stockCode);
    url = `/decision-evidence/by-advice?${q.toString()}`;
  }
  const res = await get<any>(url);
  const data = unwrapApiPayload(res);
  return {
    run: data?.run || data?.decision_run,
    decision_run: data?.decision_run || data?.run,
    evidence_items: data?.evidence_items || [],
    explanations: data?.explanations || data?.explanation_items || [],
    explanation_items: data?.explanation_items || data?.explanations || [],
    missing_evidences: data?.missing_evidences || (data?.evidence_items ? data.evidence_items.filter((i: any) => i.is_missing || i.quality_status === "missing") : []),
  };
}

export async function listSignalEntries(params?: {
  decision_run_id?: string;
  stage?: string;
  code?: string;
  severity?: string;
  limit?: number;
  offset?: number;
}): Promise<SignalLedgerQueryResult> {
  const q = new URLSearchParams();
  if (params?.decision_run_id) q.set("decision_run_id", params.decision_run_id);
  if (params?.stage) q.set("stage", params.stage);
  if (params?.code) q.set("code", params.code);
  if (params?.severity) q.set("severity", params.severity);
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const qs = q.toString();
  const res = await get<any>(`/signal-ledger${qs ? `?${qs}` : ""}`);
  const data = unwrapApiPayload(res);
  return {
    items: data?.items || [],
    total: typeof data?.total === "number" ? data.total : (data?.items?.length || 0),
    limit: data?.limit || params?.limit || 50,
    offset: data?.offset || params?.offset || 0,
  };
}

export async function getRunSignalLedger(decisionRunId: string): Promise<SignalLedgerRunDetailResult> {
  const res = await get<any>(`/signal-ledger/run/${encodeURIComponent(decisionRunId)}`);
  const data = unwrapApiPayload(res);
  return {
    run: data?.run || {},
    signal_entries: data?.signal_entries || [],
    decision_outcomes: data?.decision_outcomes || [],
  };
}

export async function getAccountExecutionPolicy(): Promise<AccountExecutionPolicyResponse> {
  return api.getAccountExecutionPolicy();
}

export async function updateAccountExecutionPolicy(body: AccountExecutionPolicy): Promise<AccountExecutionPolicyResponse> {
  return api.updateAccountExecutionPolicy(body);
}

export async function getAdoptionSummary(params?: {
  date_from?: string;
  date_to?: string;
}): Promise<AdoptionSummary> {
  const q = new URLSearchParams();
  if (params?.date_from) q.set("date_from", params.date_from);
  if (params?.date_to) q.set("date_to", params.date_to);
  const qs = q.toString();
  return get<AdoptionSummary>(`/decision-analytics/adoption${qs ? `?${qs}` : ""}`);
}

export async function getOutcomeSummary(params?: {
  adoption_status?: string;
  date_from?: string;
  date_to?: string;
}): Promise<OutcomeSummary> {
  const q = new URLSearchParams();
  if (params?.adoption_status) q.set("adoption_status", params.adoption_status);
  if (params?.date_from) q.set("date_from", params.date_from);
  if (params?.date_to) q.set("date_to", params.date_to);
  const qs = q.toString();
  return get<OutcomeSummary>(`/decision-analytics/outcome${qs ? `?${qs}` : ""}`);
}

export async function getStockAnalytics(params?: {
  date_from?: string;
  date_to?: string;
  limit?: number;
}): Promise<StockAnalyticsItem[]> {
  const q = new URLSearchParams();
  if (params?.date_from) q.set("date_from", params.date_from);
  if (params?.date_to) q.set("date_to", params.date_to);
  if (params?.limit != null) q.set("limit", String(params.limit));
  const qs = q.toString();
  return get<StockAnalyticsItem[]>(`/decision-analytics/stocks${qs ? `?${qs}` : ""}`);
}

// ---- 收益归因 (P2-4B) ----

export async function getPerformanceAttribution(params?: {
  date_from?: string;
  date_to?: string;
}): Promise<AttributionResult> {
  const q = new URLSearchParams();
  if (params?.date_from) q.set("date_from", params.date_from);
  if (params?.date_to) q.set("date_to", params.date_to);
  const qs = q.toString();
  return get<AttributionResult>(`/performance-attribution${qs ? `?${qs}` : ""}`);
}

export async function createAttributionSnapshot(body?: {
  date_from?: string;
  date_to?: string;
  price_map?: Record<string, number>;
}): Promise<{ snapshot: AttributionSnapshotSummary; attribution: AttributionResult }> {
  return request<{ snapshot: AttributionSnapshotSummary; attribution: AttributionResult }>(
    "/performance-attribution/snapshot",
    "POST",
    body ?? {},
  );
}

export async function listAttributionSnapshots(params?: {
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}): Promise<AttributionSnapshotListResult> {
  const q = new URLSearchParams();
  if (params?.date_from) q.set("date_from", params.date_from);
  if (params?.date_to) q.set("date_to", params.date_to);
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const qs = q.toString();
  return get<AttributionSnapshotListResult>(`/performance-attribution/snapshots${qs ? `?${qs}` : ""}`);
}

export async function getAttributionSnapshot(snapshotId: string): Promise<AttributionSnapshotDetailResult> {
  return get<AttributionSnapshotDetailResult>(
    `/performance-attribution/snapshots/${encodeURIComponent(snapshotId)}`,
  );
}

// ---------------------------------------------------------------------------
// Campaign（P0-CS1）
// 创建只提交 security_code + strategy（status/campaign_id/created_at 由服务端决定）；
// transition 只提交 expected_status + to_status，由 backend frozen graph 校验。
// ---------------------------------------------------------------------------

export async function listCampaigns(params?: {
  security_code?: string;
  strategy?: CampaignStrategy;
  status?: CampaignStatus;
}): Promise<CampaignRecord[]> {
  const q = new URLSearchParams();
  if (params?.security_code) q.set("security_code", params.security_code);
  if (params?.strategy) q.set("strategy", params.strategy);
  if (params?.status) q.set("status", params.status);
  const qs = q.toString();
  return get<CampaignRecord[]>(`/campaigns${qs ? `?${qs}` : ""}`);
}

export async function createCampaign(
  securityCode: string,
  strategy: CampaignStrategy,
): Promise<CampaignRecord> {
  return request<CampaignRecord>("/campaigns", "POST", {
    security_code: securityCode,
    strategy,
  });
}

export async function getCampaign(campaignId: string): Promise<CampaignRecord> {
  return get<CampaignRecord>(`/campaigns/${encodeURIComponent(campaignId)}`);
}

export async function transitionCampaign(
  campaignId: string,
  expectedStatus: CampaignStatus,
  toStatus: CampaignStatus,
): Promise<CampaignTransitionResult> {
  return request<CampaignTransitionResult>(
    `/campaigns/${encodeURIComponent(campaignId)}/transitions`,
    "POST",
    { expected_status: expectedStatus, to_status: toStatus },
  );
}

export async function activateCampaignFromTrade(
  campaignId: string,
  tradeId: string,
): Promise<CampaignTradeActivationResult> {
  return request<CampaignTradeActivationResult>(
    `/campaigns/${encodeURIComponent(campaignId)}/activate-from-trade`,
    "POST",
    { trade_id: tradeId },
  );
}

export async function getCampaignTransitions(
  campaignId: string,
): Promise<CampaignTransitionRecord[]> {
  return get<CampaignTransitionRecord[]>(
    `/campaigns/${encodeURIComponent(campaignId)}/transitions`,
  );
}

export async function getCampaignNextActions(
  campaignId: string,
): Promise<CampaignNextActions> {
  return get<CampaignNextActions>(
    `/campaigns/${encodeURIComponent(campaignId)}/next-actions`,
  );
}

// ---------------------------------------------------------------------------
// P0-CT1：Campaign ↔ Formal Thesis 绑定（POST 201）+ Current Thesis 投影（只读）
// body 只提交 thesis_id；strategy 一致性由 backend 校验，前端不复制语义。
// ---------------------------------------------------------------------------

export async function bindCampaignThesis(
  campaignId: string,
  thesisId: string,
): Promise<CampaignThesisBinding> {
  return request<CampaignThesisBinding>(
    `/campaigns/${encodeURIComponent(campaignId)}/thesis-binding`,
    "POST",
    { thesis_id: thesisId },
  );
}

export async function getCampaignThesisBinding(
  campaignId: string,
): Promise<CampaignThesisBinding> {
  return get<CampaignThesisBinding>(
    `/campaigns/${encodeURIComponent(campaignId)}/thesis-binding`,
  );
}

export async function getCampaignCurrentThesis(
  campaignId: string,
): Promise<CampaignCurrentThesis> {
  return get<CampaignCurrentThesis>(
    `/campaigns/${encodeURIComponent(campaignId)}/current-thesis`,
  );
}

export async function getResearchContinuity(
  campaignId: string,
): Promise<ResearchContinuity> {
  return get<ResearchContinuity>(
    `/campaigns/${encodeURIComponent(campaignId)}/research-continuity`,
  );
}

// ---------------------------------------------------------------------------
// P0-DC1：Decision Proposal（Preview 只读；Commit 显式确认；提交后重读）
// ---------------------------------------------------------------------------

export async function generateCampaignAIDraft(
  campaignId: string,
  llm: StreamLlmConfig,
): Promise<CampaignAIDraftGenerateResult> {
  return request<CampaignAIDraftGenerateResult>(
    `/campaigns/${encodeURIComponent(campaignId)}/ai-draft/generate`,
    "POST",
    { llm },
  );
}

export async function previewDecisionProposal(
  campaignId: string,
  body: DecisionProposalDraftInput,
): Promise<DecisionProposalPreview> {
  return request<DecisionProposalPreview>(
    `/campaigns/${encodeURIComponent(campaignId)}/decision-proposal/preview`,
    "POST",
    body,
  );
}

export async function commitDecisionProposal(
  campaignId: string,
  body: DecisionProposalDraftInput & {
    as_of: string;
    expected_proposal_fingerprint: string;
    user_confirmed: true;
    challenge_id?: string;
    draft_witness?: DecisionProposalDraftWitness | null;
  },
): Promise<DecisionProposalCommitResult> {
  return request<DecisionProposalCommitResult>(
    `/campaigns/${encodeURIComponent(campaignId)}/decision-proposal/commit`,
    "POST",
    body,
  );
}

// ---------------------------------------------------------------------------
// P0-DCH1：optional pre-freeze Decision Challenge packet
// Types stay local to this file to avoid fan-in on api/types.ts.
// ---------------------------------------------------------------------------

export const DECISION_CHALLENGE_DIMENSIONS = [
  "STRONGEST_SUPPORTING_EVIDENCE",
  "STRONGEST_OPPOSING_EVIDENCE",
  "PRE_MORTEM",
  "INVALIDATION_FACTS",
] as const;

export type DecisionChallengeDimensionName = (typeof DECISION_CHALLENGE_DIMENSIONS)[number];

export interface DecisionChallengeDimensionInput {
  status: "ANSWERED" | "UNKNOWN";
  text?: string;
}

export interface DecisionChallengeFinalizeInput extends DecisionProposalDraftInput {
  expected_proposal_fingerprint: string;
  as_of: string;
  user_confirmed: true;
  dimensions: Record<DecisionChallengeDimensionName, DecisionChallengeDimensionInput>;
}

export interface DecisionChallengePacket {
  challenge_id: string;
  packet_state: string;
  challenge_evaluation: string;
  challenge_coverage_state: string;
  decision_quality: "NOT_EVALUATED";
  two_pass_semantic_independence_verified: "NO";
  proposal_fingerprint: string;
  proposal_as_of: string;
  finalized_at: string;
  first_pass_ref: string;
  first_pass_at: string;
  second_pass_ref: string;
  second_pass_at: string;
  two_pass_state: string;
  source_refs?: string[];
  [key: string]: unknown;
}

export interface DecisionChallengeRead {
  schema_version: string;
  challenge: DecisionChallengePacket;
  decision_quality: "NOT_EVALUATED";
}

function parseDecisionChallengeRead(value: unknown): DecisionChallengeRead {
  if (!value || typeof value !== "object") {
    throw new DecisionChallengeReadError();
  }
  const record = value as Record<string, unknown>;
  const challenge = record.challenge;
  if (
    typeof record.schema_version !== "string"
    || !challenge
    || typeof challenge !== "object"
    || typeof (challenge as Record<string, unknown>).challenge_id !== "string"
    || !(challenge as Record<string, unknown>).challenge_id
    || record.decision_quality !== "NOT_EVALUATED"
  ) {
    throw new DecisionChallengeReadError();
  }
  return value as DecisionChallengeRead;
}

export async function finalizeDecisionChallenge(
  campaignId: string,
  body: DecisionChallengeFinalizeInput,
): Promise<DecisionChallengeRead> {
  const result = await request<unknown>(
    `/campaigns/${encodeURIComponent(campaignId)}/decision-challenge/finalize`,
    "POST",
    body,
  );
  return parseDecisionChallengeRead(result);
}

export async function getDecisionChallenge(
  challengeId: string,
): Promise<DecisionChallengeRead> {
  const result = await get<unknown>(
    `/decision-challenges/${encodeURIComponent(challengeId)}`,
  );
  return parseDecisionChallengeRead(result);
}

export async function getDecisionChallengeForProposal(
  campaignId: string,
  proposalFingerprint: string,
): Promise<DecisionChallengeRead | null> {
  try {
    const result = await get<unknown>(
      `/campaigns/${encodeURIComponent(campaignId)}/decision-challenge?proposal_fingerprint=${encodeURIComponent(proposalFingerprint)}`,
    );
    return parseDecisionChallengeRead(result);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

const COMMITTED_RUNTIME_SCHEMA_VERSION = "decision_commit_runtime.v0.1";

type RuntimeRecord = Record<string, unknown>;

function isRuntimeRecord(value: unknown): value is RuntimeRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function readbackError(field: string): never {
  throw new CommittedDecisionReadError(
    `COMMITTED_DECISION_READ_ERROR：${field} 缺失或格式无效`,
  );
}

function requireRecord(value: unknown, field: string): RuntimeRecord {
  if (!isRuntimeRecord(value)) readbackError(field);
  return value;
}

function validateCommittedSnapshot(
  value: unknown,
  campaignId: string,
  decisionId: string,
): RuntimeRecord {
  const committed = requireRecord(value, "committed");
  if (committed.decision_id !== decisionId) readbackError("committed.decision_id");
  if (committed.campaign_id !== campaignId) readbackError("committed.campaign_id");
  return committed;
}

function validateFormalDecision(value: unknown, decisionId: string): RuntimeRecord {
  const formalDecision = requireRecord(value, "formal_decision");
  if (formalDecision.decision_id !== decisionId) {
    readbackError("formal_decision.decision_id");
  }
  return formalDecision;
}


export function parseCommittedDecisionRuntimeRead(
  value: unknown,
  campaignId: string,
  decisionId: string,
): CommittedDecisionRuntimeRead {
  const runtime = requireRecord(value, "committed runtime");
  if (runtime.schema_version !== COMMITTED_RUNTIME_SCHEMA_VERSION) readbackError("schema_version");
  const committed = validateCommittedSnapshot(runtime.committed, campaignId, decisionId);
  const authorityFields = [
    "formal_thesis",
    "critical_data",
    "formal_decision",
    "hard_risk",
    "material_change",
    "sell_engine",
    "decision_assurance",
  ] as const;
  const authorities = Object.fromEntries(
    authorityFields.map((field) => [field, requireRecord(runtime[field], field)]),
  );
  const formalDecision = validateFormalDecision(authorities.formal_decision, decisionId);
  return {
    ...runtime,
    schema_version: runtime.schema_version,
    committed,
    formal_thesis: authorities.formal_thesis,
    critical_data: authorities.critical_data,
    formal_decision: formalDecision,
    hard_risk: authorities.hard_risk,
    material_change: authorities.material_change,
    sell_engine: authorities.sell_engine,
    decision_assurance: authorities.decision_assurance,
  } as CommittedDecisionRuntimeRead;
}

export async function getCommittedDecisionRuntime(
  campaignId: string,
  decisionId: string,
): Promise<CommittedDecisionRuntimeRead> {
  const result = await get<unknown>(
    `/campaigns/${encodeURIComponent(campaignId)}/decision-proposal/committed/${encodeURIComponent(decisionId)}`,
  );
  return parseCommittedDecisionRuntimeRead(result, campaignId, decisionId);
}

// ---------------------------------------------------------------------------
// Decision Inbox（P0-CS1）：只读快照。
// ---------------------------------------------------------------------------

export async function getDecisionInbox(): Promise<DecisionInboxSnapshot> {
  return get<DecisionInboxSnapshot>("/decision-inbox");
}
