import type {
  DailyReviewAnalyzeRequest,
  DailyReviewCacheMeta,
  DailyReviewComparison,
  DailyReviewData,
  DailyReviewHistoryList,
  DailyReviewHistorySnapshot,
  SaveDailyReviewHistoryResult,
} from "./types/dailyReview.ts";
import type { NdjsonStreamHandlers, NdjsonStreamResult } from "./types.ts";

type ReviewPayload = { data: DailyReviewData; cache_meta?: DailyReviewCacheMeta | null };

export interface DailyReviewClientDependencies {
  get: <T>(path: string) => Promise<T>;
  request: <T>(path: string, method: "POST", body?: unknown) => Promise<T>;
  authHeaders: () => Record<string, string>;
  createApiError: (message: string, status: number) => Error;
  streamNdjson: (
    path: string,
    body: unknown,
    handlers?: NdjsonStreamHandlers,
    signal?: AbortSignal,
  ) => Promise<NdjsonStreamResult>;
}

/**
 * 每日复盘的专属客户端。依赖由 api facade 注入，避免领域模块反向导入 facade。
 */
export function createDailyReviewClient(deps: DailyReviewClientDependencies) {
  const fetchReview = async (path: string, method: "GET" | "POST"): Promise<ReviewPayload> => {
    let resp: Response;
    const headers: Record<string, string> = method === "POST"
      ? { "Content-Type": "application/json", ...deps.authHeaders() }
      : { ...deps.authHeaders() };
    try {
      resp = await fetch(`/api${path}`, method === "POST"
        ? { method, headers, body: "{}" }
        : { method, ...(Object.keys(headers).length > 0 ? { headers } : {}) });
    } catch {
      throw deps.createApiError("连接不到后端，请先启动 backend（uvicorn app:app --port 8900）", 0);
    }
    let payload: any = null;
    try {
      payload = await resp.json();
    } catch {
      /* 非 JSON 响应 */
    }
    if (!resp.ok) {
      if (resp.status === 401) {
        throw deps.createApiError("后端开启了访问鉴权（VR_API_KEY）：请在「接入 AI」页底部填写后端访问密钥", 401);
      }
      throw deps.createApiError(payload?.detail || `HTTP ${resp.status}`, resp.status);
    }
    return {
      data: (payload?.data ?? payload) as DailyReviewData,
      cache_meta: (payload?.cache_meta ?? null) as DailyReviewCacheMeta | null,
    };
  };

  return {
    analyzeStream: (
      request: DailyReviewAnalyzeRequest,
      handlers: NdjsonStreamHandlers = {},
      signal?: AbortSignal,
    ): Promise<NdjsonStreamResult> => deps.streamNdjson(
      "/daily-review/analyze",
      { user_request: request.user_request ?? null, llm: request.llm },
      handlers,
      signal,
    ),
    getDailyReview: () => fetchReview("/daily-review", "GET"),
    refreshDailyReview: () => fetchReview("/daily-review/refresh", "POST"),
    saveHistory: () => deps.request<SaveDailyReviewHistoryResult>("/daily-review/history/save", "POST"),
    listHistory: (params?: { trade_date?: string; limit?: number; offset?: number }) => {
      const query = new URLSearchParams();
      if (params?.trade_date) query.set("trade_date", params.trade_date);
      if (params?.limit != null) query.set("limit", String(params.limit));
      if (params?.offset != null) query.set("offset", String(params.offset));
      const suffix = query.toString();
      return deps.get<DailyReviewHistoryList>(`/daily-review/history${suffix ? `?${suffix}` : ""}`);
    },
    getHistorySnapshot: (snapshotId: number) =>
      deps.get<DailyReviewHistorySnapshot>(`/daily-review/history/${snapshotId}`),
    compareHistory: (params: { base_id: number; target_id: number; board_limit?: number; stock_limit?: number }) => {
      const query = new URLSearchParams({ base_id: String(params.base_id), target_id: String(params.target_id) });
      if (params.board_limit != null) query.set("board_limit", String(params.board_limit));
      if (params.stock_limit != null) query.set("stock_limit", String(params.stock_limit));
      return deps.get<DailyReviewComparison>(`/daily-review/history/compare?${query.toString()}`);
    },
  };
}
