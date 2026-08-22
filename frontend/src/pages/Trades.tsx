import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, ApiError, type TradeAttributionCandidate, type TradeAttributionCandidateScan, type TradeRecord, type TradeReconciliationResult } from "@/lib/api";
import {
  buildTradeCreateInput,
  buildTradeListQuery,
  executionStatusLabel,
  formatTradeMoney,
  formatTradePercentage,
  formatTradeQuantity,
  formatTradeTime,
  getTradeExecutionTimePreview,
  operationLabel,
  validateTradeDraft,
  validateTradeListFilters,
  type TradeDraft,
  type TradeListFilters,
} from "@/lib/tradeLedgerView";
import {
  AlertCircle,
  CheckCircle2,
  Filter,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  X,
  Ban,
  FileText,
} from "lucide-react";
import { cn } from "@/lib/utils";

const PAGE_LIMIT = 10;

export function Trades() {
  // 列表 state
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // 筛选 state
  const [filters, setFilters] = useState<TradeListFilters>({
    code: "",
    operation: "",
    execution_status: "",
    date_from: "",
    date_to: "",
    include_voided: false,
  });
  const [appliedFilters, setAppliedFilters] = useState<TradeListFilters>({
    code: "",
    operation: "",
    execution_status: "",
    date_from: "",
    date_to: "",
    include_voided: false,
  });
  const [filterError, setFilterError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);

  // 详情 modal state
  const [selectedTradeId, setSelectedTradeId] = useState<string | null>(null);
  const [detailTrade, setDetailTrade] = useState<TradeRecord | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [reconciliation, setReconciliation] = useState<TradeReconciliationResult | null>(null);
  const [attributionCandidates, setAttributionCandidates] = useState<TradeAttributionCandidate[]>([]);
  const [candidateScanState, setCandidateScanState] = useState<TradeAttributionCandidateScan["scan_state"] | null>(null);
  const [reconciliationLoading, setReconciliationLoading] = useState(false);
  const [reconciliationError, setReconciliationError] = useState<string | null>(null);
  const [candidateError, setCandidateError] = useState<string | null>(null);
  const [reconciliationActionLoading, setReconciliationActionLoading] = useState(false);

  // 新建 modal state
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [createDraft, setCreateDraft] = useState<TradeDraft>({
    code: "",
    name: "",
    operation: "buy",
    execution_status: "full",
    planned_price: "",
    planned_quantity: "",
    actual_price: "",
    actual_quantity: "",
    executed_at: "",
    fee: "",
    other_cost: "",
    unexecuted_reason: "",
    note: "",
    advice_ref: null,
    thesis_ref: null,
  });
  const [enableAdviceRef, setEnableAdviceRef] = useState(false);
  const [enableThesisRef, setEnableThesisRef] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // 作废 modal state
  const [voidTarget, setVoidTarget] = useState<TradeRecord | null>(null);
  const [voidReason, setVoidReason] = useState("");
  const [voidLoading, setVoidLoading] = useState(false);
  const [voidError, setVoidError] = useState<string | null>(null);

  // 加载数据
  const loadTrades = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const query = buildTradeListQuery(appliedFilters, PAGE_LIMIT, offset);
      const res = await api.listTrades(query);
      setTrades(res);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(e.message);
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("加载交易流水失败");
      }
    } finally {
      setLoading(false);
    }
  }, [appliedFilters, offset]);

  useEffect(() => {
    loadTrades();
  }, [loadTrades]);

  // 加载单条详情
  const loadDetail = useCallback(async (id: string) => {
    setDetailLoading(true);
    setDetailError(null);
    try {
      const record = await api.getTrade(id);
      setDetailTrade(record);
    } catch (e) {
      if (e instanceof ApiError) {
        setDetailError(e.message);
      } else if (e instanceof Error) {
        setDetailError(e.message);
      } else {
        setDetailError("获取交易详情失败");
      }
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedTradeId) {
      loadDetail(selectedTradeId);
    } else {
      setDetailTrade(null);
      setDetailError(null);
    }
  }, [selectedTradeId, loadDetail]);

  useEffect(() => {
    if (!selectedTradeId) {
      setReconciliation(null);
      setAttributionCandidates([]);
      setCandidateScanState(null);
      setReconciliationError(null);
      setCandidateError(null);
      return;
    }
    let active = true;
    setReconciliationLoading(true);
    setReconciliationError(null);
    setCandidateError(null);
    Promise.allSettled([
      api.getTradeReconciliation(selectedTradeId),
      api.listTradeAttributionCandidates(selectedTradeId),
    ]).then(([reconciliationResult, candidatesResult]) => {
      if (!active) return;
      if (reconciliationResult.status === "fulfilled") {
        setReconciliation(reconciliationResult.value);
      } else {
        const error = reconciliationResult.reason;
        setReconciliationError(error instanceof Error ? error.message : "获取交易对账状态失败");
      }
      if (candidatesResult.status === "fulfilled") {
        setAttributionCandidates(candidatesResult.value.candidates);
        setCandidateScanState(candidatesResult.value.scan_state);
      } else {
        const error = candidatesResult.reason;
        setCandidateError(error instanceof Error ? error.message : "获取归属候选失败");
      }
    }).finally(() => {
      if (active) setReconciliationLoading(false);
    });
    return () => { active = false; };
  }, [selectedTradeId]);

  const refreshReconciliation = async () => {
    if (!selectedTradeId) return;
    setReconciliationLoading(true);
    setReconciliationError(null);
    setCandidateError(null);
    const [reconciliationResult, candidatesResult] = await Promise.allSettled([
      api.getTradeReconciliation(selectedTradeId),
      api.listTradeAttributionCandidates(selectedTradeId),
    ]);
    if (reconciliationResult.status === "fulfilled") {
      setReconciliation(reconciliationResult.value);
    } else {
      const error = reconciliationResult.reason;
      setReconciliationError(error instanceof Error ? error.message : "刷新交易对账状态失败");
    }
    if (candidatesResult.status === "fulfilled") {
      setAttributionCandidates(candidatesResult.value.candidates);
      setCandidateScanState(candidatesResult.value.scan_state);
    } else {
      const error = candidatesResult.reason;
      setCandidateError(error instanceof Error ? error.message : "刷新归属候选失败");
    }
    setReconciliationLoading(false);
  };

  const handleAttribution = async (decisionId: string) => {
    if (!selectedTradeId) return;
    setReconciliationActionLoading(true);
    setReconciliationError(null);
    try {
      await api.attributeTrade(selectedTradeId, decisionId);
      await refreshReconciliation();
    } catch (e) {
      setReconciliationError(e instanceof Error ? e.message : "交易归属失败");
    } finally {
      setReconciliationActionLoading(false);
    }
  };

  const handleMarkUnplanned = async () => {
    if (!selectedTradeId) return;
    setReconciliationActionLoading(true);
    setReconciliationError(null);
    try {
      await api.markTradeUnplanned(selectedTradeId);
      await refreshReconciliation();
    } catch (e) {
      setReconciliationError(e instanceof Error ? e.message : "标记 UNPLANNED 失败");
    } finally {
      setReconciliationActionLoading(false);
    }
  };

  // 筛选操作
  const handleFilterSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const err = validateTradeListFilters(filters);
    if (err) {
      setFilterError(err);
      return;
    }
    setFilterError(null);
    setOffset(0);
    setAppliedFilters({ ...filters });
  };

  const handleFilterReset = () => {
    const emptyFilters: TradeListFilters = {
      code: "",
      operation: "",
      execution_status: "",
      date_from: "",
      date_to: "",
      include_voided: false,
    };
    setFilters(emptyFilters);
    setFilterError(null);
    setOffset(0);
    setAppliedFilters(emptyFilters);
  };

  // 打开与关闭新建
  const handleOpenCreate = () => {
    setCreateDraft({
      code: "",
      name: "",
      operation: "buy",
      execution_status: "full",
      planned_price: "",
      planned_quantity: "",
      actual_price: "",
      actual_quantity: "",
      executed_at: "",
      fee: "0",
      other_cost: "0",
      unexecuted_reason: "",
      note: "",
      advice_ref: null,
      thesis_ref: null,
    });
    setEnableAdviceRef(false);
    setEnableThesisRef(false);
    setCreateError(null);
    setIsCreateOpen(true);
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError(null);

    const draftToSubmit: TradeDraft = {
      ...createDraft,
      advice_ref: enableAdviceRef && createDraft.advice_ref ? createDraft.advice_ref : null,
      thesis_ref: enableThesisRef && createDraft.thesis_ref ? createDraft.thesis_ref : null,
    };

    const err = validateTradeDraft(draftToSubmit);
    if (err) {
      setCreateError(err);
      return;
    }

    setCreateLoading(true);
    try {
      const payload = buildTradeCreateInput(draftToSubmit);
      const created = await api.createTrade(payload);
      // P1-TRUX1：创建成功即续接详情链路——detail / reconciliation /
      // candidates 由 selectedTradeId 的既有 effect 复用加载。若 Trade 已
      // 持久化但后续读取失败，只诚实展示读取错误，不回滚、不伪装创建失败；
      // 归属与 UNPLANNED 仍只能由用户显式点击触发。
      setIsCreateOpen(false);
      setSelectedTradeId(created.trade_id);
      setSuccessMsg("交易流水创建成功，已打开该笔交易详情");
      setTimeout(() => setSuccessMsg(null), 3000);
      loadTrades();
    } catch (e) {
      if (e instanceof ApiError) {
        setCreateError(e.message);
      } else if (e instanceof Error) {
        setCreateError(e.message);
      } else {
        setCreateError("创建交易流水失败");
      }
    } finally {
      setCreateLoading(false);
    }
  };

  // 作废操作
  const handleOpenVoid = (trade: TradeRecord) => {
    setVoidTarget(trade);
    setVoidReason("");
    setVoidError(null);
  };

  const handleVoidSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!voidTarget) return;

    if (!voidReason.trim()) {
      setVoidError("作废原因不能为空");
      return;
    }

    setVoidLoading(true);
    setVoidError(null);

    try {
      await api.voidTrade(voidTarget.trade_id, voidReason.trim());
      const voidedId = voidTarget.trade_id;
      setVoidTarget(null);
      setSuccessMsg("交易已成功作废");
      setTimeout(() => setSuccessMsg(null), 3000);
      loadTrades();
      if (selectedTradeId === voidedId) {
        loadDetail(voidedId);
      }
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 404) {
          setVoidError("交易记录不存在");
        } else if (e.status === 409) {
          setVoidError("该交易已经作废");
        } else {
          setVoidError(e.message);
        }
      } else if (e instanceof Error) {
        setVoidError(e.message);
      } else {
        setVoidError("作废交易失败");
      }
    } finally {
      setVoidLoading(false);
    }
  };

  // 分页
  const handlePrevPage = () => {
    if (offset >= PAGE_LIMIT) {
      setOffset(offset - PAGE_LIMIT);
    }
  };

  const handleNextPage = () => {
    if (trades.length >= PAGE_LIMIT) {
      setOffset(offset + PAGE_LIMIT);
    }
  };

  const executionTimePreview = createDraft.execution_status !== "not_executed"
    ? getTradeExecutionTimePreview(createDraft.executed_at)
    : null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="交易流水"
        subtitle="记录、筛选与管理交易执行流水"
        actions={
          <button
            type="button"
            onClick={handleOpenCreate}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" />
            新建交易
          </button>
        }
      />

      {/* 消息提示 */}
      {successMsg && (
        <div className="flex items-center gap-2 rounded-lg bg-emerald-500/15 p-3 text-xs text-emerald-400 border border-emerald-500/20">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      {/* 筛选面板 */}
      <GlassCard className="p-4">
        <form onSubmit={handleFilterSubmit} className="space-y-4">
          <div className="flex items-center gap-2 text-xs font-semibold text-foreground/90 mb-2">
            <Filter className="h-3.5 w-3.5" />
            <span>筛选条件</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <div>
              <label className="block text-[11px] text-muted-foreground mb-1">股票代码</label>
              <input
                type="text"
                placeholder="6位数字代码"
                maxLength={6}
                value={filters.code || ""}
                onChange={(e) => setFilters({ ...filters, code: e.target.value })}
                className="w-full rounded-md border border-input bg-background/50 px-2.5 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>

            <div>
              <label className="block text-[11px] text-muted-foreground mb-1">操作类型</label>
              <select
                value={filters.operation || ""}
                onChange={(e) =>
                  setFilters({ ...filters, operation: (e.target.value as any) || "" })
                }
                className="w-full rounded-md border border-input bg-background/50 px-2.5 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="">所有类型</option>
                <option value="buy">买入</option>
                <option value="add">加仓</option>
                <option value="reduce">减仓</option>
                <option value="sell">卖出</option>
              </select>
            </div>

            <div>
              <label className="block text-[11px] text-muted-foreground mb-1">执行状态</label>
              <select
                value={filters.execution_status || ""}
                onChange={(e) =>
                  setFilters({ ...filters, execution_status: (e.target.value as any) || "" })
                }
                className="w-full rounded-md border border-input bg-background/50 px-2.5 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="">所有状态</option>
                <option value="full">已全部执行</option>
                <option value="partial">部分执行</option>
                <option value="not_executed">未执行</option>
              </select>
            </div>

            <div>
              <label className="block text-[11px] text-muted-foreground mb-1">开始日期</label>
              <input
                type="date"
                value={filters.date_from || ""}
                onChange={(e) => setFilters({ ...filters, date_from: e.target.value })}
                className="w-full rounded-md border border-input bg-background/50 px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>

            <div>
              <label className="block text-[11px] text-muted-foreground mb-1">结束日期</label>
              <input
                type="date"
                value={filters.date_to || ""}
                onChange={(e) => setFilters({ ...filters, date_to: e.target.value })}
                className="w-full rounded-md border border-input bg-background/50 px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>

            <div className="flex flex-col justify-end">
              <label className="inline-flex items-center gap-2 cursor-pointer text-xs text-foreground py-2">
                <input
                  type="checkbox"
                  checked={filters.include_voided || false}
                  onChange={(e) => setFilters({ ...filters, include_voided: e.target.checked })}
                  className="rounded border-input text-primary focus:ring-primary"
                />
                包含作废记录
              </label>
            </div>
          </div>

          {filterError && (
            <p className="text-xs text-rose-400 flex items-center gap-1">
              <AlertCircle className="h-3.5 w-3.5" />
              {filterError}
            </p>
          )}

          <div className="flex items-center justify-end gap-2 pt-2 border-t border-border/40">
            <button
              type="button"
              onClick={handleFilterReset}
              className="rounded-md border border-input px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            >
              重置
            </button>
            <button
              type="submit"
              className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            >
              <Search className="h-3.5 w-3.5" />
              筛选
            </button>
          </div>
        </form>
      </GlassCard>

      {/* 错误展示 / 加载中 / 交易列表 */}
      {error ? (
        <GlassCard className="p-6 text-center space-y-4">
          <div className="inline-flex items-center justify-center rounded-full bg-rose-500/15 p-3 text-rose-400">
            <AlertCircle className="h-6 w-6" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-foreground">加载交易流水失败</h3>
            <p className="mt-1 text-xs text-muted-foreground">{error}</p>
          </div>
          <button
            type="button"
            onClick={loadTrades}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            重试
          </button>
        </GlassCard>
      ) : loading ? (
        <GlassCard className="p-12 text-center">
          <Loader2 className="h-6 w-6 animate-spin mx-auto text-primary" />
          <p className="mt-2 text-xs text-muted-foreground">加载交易流水中...</p>
        </GlassCard>
      ) : trades.length === 0 ? (
        <GlassCard className="p-12 text-center space-y-3">
          <FileText className="h-8 w-8 mx-auto text-muted-foreground/40" />
          <p className="text-sm font-medium text-muted-foreground">暂无交易流水</p>
        </GlassCard>
      ) : (
        <GlassCard className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-muted/40 text-muted-foreground border-b border-border/40 font-medium">
                <tr>
                  <th className="p-3">成交时间/记录时间</th>
                  <th className="p-3">股票</th>
                  <th className="p-3">操作类型</th>
                  <th className="p-3">执行状态</th>
                  <th className="p-3 text-right">计划数量</th>
                  <th className="p-3 text-right">实际数量</th>
                  <th className="p-3 text-right">实际价格</th>
                  <th className="p-3 text-right">成交金额</th>
                  <th className="p-3 text-right">净现金流</th>
                  <th className="p-3 text-center">作废状态</th>
                  <th className="p-3 text-center">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {trades.map((item) => {
                  const isVoided = Boolean(item.voided_at);
                  return (
                    <tr
                      key={item.trade_id}
                      className={cn(
                        "hover:bg-muted/30 transition-colors",
                        isVoided && "opacity-60 bg-muted/10",
                      )}
                    >
                      <td className="p-3 text-muted-foreground font-mono">
                        {formatTradeTime(item.executed_at || item.created_at)}
                      </td>
                      <td className="p-3 font-medium">
                        <span className="text-foreground">{item.name}</span>
                        <span className="ml-1 text-[11px] text-muted-foreground font-mono">
                          ({item.code})
                        </span>
                      </td>
                      <td className="p-3">
                        <span
                          className={cn(
                            "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium",
                            item.operation === "buy" || item.operation === "add"
                              ? "bg-emerald-500/15 text-emerald-400"
                              : "bg-rose-500/15 text-rose-400",
                          )}
                        >
                          {operationLabel(item.operation)}
                        </span>
                      </td>
                      <td className="p-3">
                        <span
                          className={cn(
                            "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium",
                            item.execution_status === "full"
                              ? "bg-blue-500/15 text-blue-400"
                              : item.execution_status === "partial"
                                ? "bg-amber-500/15 text-amber-400"
                                : "bg-slate-500/15 text-slate-400",
                          )}
                        >
                          {executionStatusLabel(item.execution_status)}
                        </span>
                      </td>
                      <td className="p-3 text-right font-mono">
                        {formatTradeQuantity(item.planned_quantity)}
                      </td>
                      <td className="p-3 text-right font-mono">
                        {formatTradeQuantity(item.actual_quantity)}
                      </td>
                      <td className="p-3 text-right font-mono">
                        {formatTradeMoney(item.actual_price)}
                      </td>
                      <td className="p-3 text-right font-mono">
                        {formatTradeMoney(item.gross_amount)}
                      </td>
                      <td className="p-3 text-right font-mono font-medium">
                        {formatTradeMoney(item.net_cash_flow)}
                      </td>
                      <td className="p-3 text-center">
                        {isVoided ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/15 px-2 py-0.5 text-[10px] text-rose-400 font-medium">
                            <Ban className="h-3 w-3" />
                            已作废
                          </span>
                        ) : (
                          <span className="text-muted-foreground/60 text-[11px]">—</span>
                        )}
                      </td>
                      <td className="p-3 text-center space-x-2">
                        <button
                          type="button"
                          onClick={() => setSelectedTradeId(item.trade_id)}
                          className="text-primary hover:underline font-medium text-xs"
                        >
                          详情
                        </button>
                        {!isVoided && (
                          <button
                            type="button"
                            onClick={() => handleOpenVoid(item)}
                            className="text-rose-400 hover:underline font-medium text-xs"
                          >
                            作废
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* 分页控制 */}
          <div className="flex items-center justify-between border-t border-border/40 px-4 py-3 bg-muted/20">
            <span className="text-xs text-muted-foreground">
              第 {Math.floor(offset / PAGE_LIMIT) + 1} 页
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handlePrevPage}
                disabled={offset === 0}
                className="rounded-md border border-input px-3 py-1 text-xs font-medium hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed"
              >
                上一页
              </button>
              <button
                type="button"
                onClick={handleNextPage}
                disabled={trades.length < PAGE_LIMIT}
                className="rounded-md border border-input px-3 py-1 text-xs font-medium hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed"
              >
                下一页
              </button>
            </div>
          </div>
        </GlassCard>
      )}

      {/* 新建交易 Modal */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm overflow-y-auto">
          <div className="w-full max-w-2xl rounded-xl border border-border bg-background p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-border/40 pb-3">
              <h3 className="text-base font-semibold text-foreground">新建交易流水</h3>
              <button
                type="button"
                onClick={() => setIsCreateOpen(false)}
                className="rounded-lg p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleCreateSubmit} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">
                    股票代码 <span className="text-rose-400">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="6位数字，如 600519"
                    maxLength={6}
                    value={createDraft.code}
                    onChange={(e) => setCreateDraft({ ...createDraft, code: e.target.value })}
                    className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">
                    股票名称 <span className="text-rose-400">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="如 贵州茅台"
                    value={createDraft.name}
                    onChange={(e) => setCreateDraft({ ...createDraft, name: e.target.value })}
                    className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">
                    操作类型 <span className="text-rose-400">*</span>
                  </label>
                  <select
                    value={createDraft.operation}
                    onChange={(e) =>
                      setCreateDraft({ ...createDraft, operation: e.target.value as any })
                    }
                    className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                  >
                    <option value="buy">买入</option>
                    <option value="add">加仓</option>
                    <option value="reduce">减仓</option>
                    <option value="sell">卖出</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">
                    执行状态 <span className="text-rose-400">*</span>
                  </label>
                  <select
                    value={createDraft.execution_status}
                    onChange={(e) =>
                      setCreateDraft({ ...createDraft, execution_status: e.target.value as any })
                    }
                    className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                  >
                    <option value="full">已全部执行</option>
                    <option value="partial">部分执行</option>
                    <option value="not_executed">未执行</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">计划价格</label>
                  <input
                    type="number"
                    step="any"
                    placeholder="可选，大于0"
                    value={createDraft.planned_price ?? ""}
                    onChange={(e) =>
                      setCreateDraft({ ...createDraft, planned_price: e.target.value })
                    }
                    className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">计划数量</label>
                  <input
                    type="number"
                    step="1"
                    placeholder="可选，正整数"
                    value={createDraft.planned_quantity ?? ""}
                    onChange={(e) =>
                      setCreateDraft({ ...createDraft, planned_quantity: e.target.value })
                    }
                    className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                  />
                </div>

                {/* 实际成交字段：非 not_executed 时展示 */}
                {createDraft.execution_status !== "not_executed" && (
                  <>
                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        实际价格 <span className="text-rose-400">*</span>
                      </label>
                      <input
                        type="number"
                        step="any"
                        required
                        placeholder="大于0"
                        value={createDraft.actual_price ?? ""}
                        onChange={(e) =>
                          setCreateDraft({ ...createDraft, actual_price: e.target.value })
                        }
                        className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        实际数量 <span className="text-rose-400">*</span>
                      </label>
                      <input
                        type="number"
                        step="1"
                        required
                        placeholder="正整数"
                        value={createDraft.actual_quantity ?? ""}
                        onChange={(e) =>
                          setCreateDraft({ ...createDraft, actual_quantity: e.target.value })
                        }
                        className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                      />
                    </div>

                    <div className="sm:col-span-2">
                      <label className="block text-xs font-medium text-foreground mb-1">
                        实际成交时间 <span className="text-rose-400">*</span>
                      </label>
                      <input
                        type="datetime-local"
                        required
                        aria-label="实际成交时间"
                        value={createDraft.executed_at ?? ""}
                        onChange={(e) =>
                          setCreateDraft({ ...createDraft, executed_at: e.target.value })
                        }
                        className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                      />
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        请显式选择真实成交时间；系统不会使用录入时间、创建时间或其他事实自动填充。
                      </p>
                      {createDraft.executed_at && !executionTimePreview && (
                        <p className="mt-1 text-[11px] text-rose-400">
                          成交时间格式无效，请重新选择有效的本地时间。
                        </p>
                      )}
                      {executionTimePreview && (
                        <div className="mt-2 rounded border border-border/40 bg-muted/20 p-2 text-[11px] text-muted-foreground">
                          <div>本地时间：<span className="font-mono text-foreground">{executionTimePreview.localValue}</span></div>
                          <div>浏览器解析时区：<span className="font-mono text-foreground">{executionTimePreview.timeZone}</span></div>
                          <div>UTC offset：<span className="font-mono text-foreground">{executionTimePreview.utcOffset}</span></div>
                          <div>Canonical UTC ISO：<span className="font-mono text-foreground">{executionTimePreview.canonicalUtcIso}</span></div>
                        </div>
                      )}
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        手续费 (¥)
                      </label>
                      <input
                        type="number"
                        step="any"
                        placeholder="默认为 0"
                        value={createDraft.fee ?? ""}
                        onChange={(e) => setCreateDraft({ ...createDraft, fee: e.target.value })}
                        className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        其他费用 (¥)
                      </label>
                      <input
                        type="number"
                        step="any"
                        placeholder="默认为 0"
                        value={createDraft.other_cost ?? ""}
                        onChange={(e) =>
                          setCreateDraft({ ...createDraft, other_cost: e.target.value })
                        }
                        className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                      />
                    </div>
                  </>
                )}
              </div>

              {/* 未执行原因 */}
              {(createDraft.execution_status === "partial" ||
                createDraft.execution_status === "not_executed") && (
                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">
                    未执行原因 <span className="text-rose-400">*</span>
                  </label>
                  <textarea
                    rows={2}
                    required
                    placeholder="请输入未执行或部分执行的原因"
                    value={createDraft.unexecuted_reason ?? ""}
                    onChange={(e) =>
                      setCreateDraft({ ...createDraft, unexecuted_reason: e.target.value })
                    }
                    className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                  />
                </div>
              )}

              {/* 备注 */}
              <div>
                <label className="block text-xs font-medium text-foreground mb-1">备注</label>
                <textarea
                  rows={2}
                  placeholder="可选，交易备注"
                  value={createDraft.note ?? ""}
                  onChange={(e) => setCreateDraft({ ...createDraft, note: e.target.value })}
                  className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                />
              </div>

              {/* 高级引用 */}
              <div className="space-y-3 pt-2 border-t border-border/40">
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="enableAdviceRef"
                    checked={enableAdviceRef}
                    onChange={(e) => {
                      setEnableAdviceRef(e.target.checked);
                      if (e.target.checked && !createDraft.advice_ref) {
                        setCreateDraft({
                          ...createDraft,
                          advice_ref: { trade_date: "", generated_at: "" },
                        });
                      }
                    }}
                    className="rounded border-input text-primary focus:ring-primary"
                  />
                  <label htmlFor="enableAdviceRef" className="text-xs font-medium text-foreground cursor-pointer">
                    关联 AI 建议引用
                  </label>
                </div>

                {enableAdviceRef && (
                  <div className="grid grid-cols-2 gap-3 pl-6">
                    <div>
                      <label className="block text-[11px] text-muted-foreground mb-1">
                        建议交易日期
                      </label>
                      <input
                        type="date"
                        value={createDraft.advice_ref?.trade_date ?? ""}
                        onChange={(e) =>
                          setCreateDraft({
                            ...createDraft,
                            advice_ref: {
                              trade_date: e.target.value,
                              generated_at: createDraft.advice_ref?.generated_at ?? "",
                            },
                          })
                        }
                        className="w-full rounded-md border border-input bg-background/50 px-2.5 py-1 text-xs text-foreground"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-muted-foreground mb-1">
                        建议生成时间 (ISO)
                      </label>
                      <input
                        type="text"
                        placeholder="如 2026-07-29T08:00:00Z"
                        value={createDraft.advice_ref?.generated_at ?? ""}
                        onChange={(e) =>
                          setCreateDraft({
                            ...createDraft,
                            advice_ref: {
                              trade_date: createDraft.advice_ref?.trade_date ?? "",
                              generated_at: e.target.value,
                            },
                          })
                        }
                        className="w-full rounded-md border border-input bg-background/50 px-2.5 py-1 text-xs text-foreground"
                      />
                    </div>
                  </div>
                )}

                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="enableThesisRef"
                    checked={enableThesisRef}
                    onChange={(e) => {
                      setEnableThesisRef(e.target.checked);
                      if (e.target.checked && !createDraft.thesis_ref) {
                        setCreateDraft({
                          ...createDraft,
                          thesis_ref: { thesis_id: "", revision_number: 1 },
                        });
                      }
                    }}
                    className="rounded border-input text-primary focus:ring-primary"
                  />
                  <label htmlFor="enableThesisRef" className="text-xs font-medium text-foreground cursor-pointer">
                    关联 Thesis 投资逻辑
                  </label>
                </div>

                {enableThesisRef && (
                  <div className="grid grid-cols-2 gap-3 pl-6">
                    <div>
                      <label className="block text-[11px] text-muted-foreground mb-1">
                        Thesis ID
                      </label>
                      <input
                        type="text"
                        placeholder="Thesis ID"
                        value={createDraft.thesis_ref?.thesis_id ?? ""}
                        onChange={(e) =>
                          setCreateDraft({
                            ...createDraft,
                            thesis_ref: {
                              thesis_id: e.target.value,
                              revision_number: createDraft.thesis_ref?.revision_number ?? 1,
                            },
                          })
                        }
                        className="w-full rounded-md border border-input bg-background/50 px-2.5 py-1 text-xs text-foreground"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-muted-foreground mb-1">
                        版本号
                      </label>
                      <input
                        type="number"
                        min={1}
                        value={createDraft.thesis_ref?.revision_number ?? 1}
                        onChange={(e) =>
                          setCreateDraft({
                            ...createDraft,
                            thesis_ref: {
                              thesis_id: createDraft.thesis_ref?.thesis_id ?? "",
                              revision_number: parseInt(e.target.value) || 1,
                            },
                          })
                        }
                        className="w-full rounded-md border border-input bg-background/50 px-2.5 py-1 text-xs text-foreground"
                      />
                    </div>
                  </div>
                )}
              </div>

              {createError && (
                <div className="rounded-lg bg-rose-500/15 p-3 text-xs text-rose-400 border border-rose-500/20 flex items-center gap-2">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  <span>{createError}</span>
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-border/40">
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  className="rounded-md border border-input px-4 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={createLoading}
                  className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                >
                  {createLoading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  提交创建
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 交易详情 Modal */}
      {selectedTradeId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm overflow-y-auto">
          <div className="w-full max-w-2xl rounded-xl border border-border bg-background p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-border/40 pb-3">
              <h3 className="text-base font-semibold text-foreground">交易流水详情</h3>
              <button
                type="button"
                onClick={() => setSelectedTradeId(null)}
                className="rounded-lg p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {detailLoading ? (
              <div className="py-12 text-center">
                <Loader2 className="h-6 w-6 animate-spin mx-auto text-primary" />
                <p className="mt-2 text-xs text-muted-foreground">加载详情中...</p>
              </div>
            ) : detailError ? (
              <div className="rounded-lg bg-rose-500/15 p-4 text-xs text-rose-400 border border-rose-500/20">
                {detailError}
              </div>
            ) : detailTrade ? (
              <div className="space-y-6 text-xs">
                {/* 基础与作废标头 */}
                <div className="rounded-lg bg-muted/30 p-4 space-y-2 border border-border/40">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-base font-bold text-foreground">
                        {detailTrade.name} ({detailTrade.code})
                      </span>
                      <span className="ml-2 font-mono text-[11px] text-muted-foreground">
                        ID: {detailTrade.trade_id}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="rounded-full bg-primary/15 px-2.5 py-0.5 font-medium text-primary">
                        {operationLabel(detailTrade.operation)}
                      </span>
                      <span className="rounded-full bg-muted px-2.5 py-0.5 font-medium text-foreground">
                        {executionStatusLabel(detailTrade.execution_status)}
                      </span>
                    </div>
                  </div>

                  {detailTrade.voided_at && (
                    <div className="mt-2 rounded bg-rose-500/15 p-2 text-rose-400 border border-rose-500/20 space-y-1">
                      <div className="font-semibold flex items-center gap-1">
                        <Ban className="h-3.5 w-3.5" />
                        该交易已于 {formatTradeTime(detailTrade.voided_at)} 作废
                      </div>
                      <div>作废原因：{detailTrade.void_reason || "无"}</div>
                    </div>
                  )}
                </div>

                {/* TAR1：只显示后端权威归属，不按时间/代码推断。 */}
                <div className="rounded-lg border border-border/40 bg-card p-4 space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h4 className="font-semibold text-foreground">交易归属与 Campaign 对账</h4>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        仅接受明确 Frozen Decision 归属或明确 UNPLANNED；系统不自动匹配。
                      </p>
                    </div>
                    {reconciliationLoading && <Loader2 className="h-4 w-4 animate-spin text-primary" />}
                  </div>

                  {reconciliationError && (
                    <div className="rounded border border-rose-500/20 bg-rose-500/10 p-2 text-rose-400">对账状态加载失败：{reconciliationError}</div>
                  )}
                  {candidateError && (
                    <div className="rounded border border-rose-500/20 bg-rose-500/10 p-2 text-rose-400">归属候选加载失败：{candidateError}</div>
                  )}
                  {reconciliation && (
                    <div className="grid grid-cols-2 gap-2 text-[11px]">
                      <div><span className="text-muted-foreground">状态：</span><span className="font-semibold text-foreground">{reconciliation.allocation_state}</span></div>
                      <div><span className="text-muted-foreground">对账：</span><span className="font-semibold text-foreground">{reconciliation.reconciliation_requirement}</span></div>
                      {reconciliation.campaign_id && <div><span className="text-muted-foreground">Campaign：</span><span className="font-mono text-foreground">{reconciliation.campaign_id}</span></div>}
                      {reconciliation.decision_id && <div><span className="text-muted-foreground">Frozen Decision：</span><span className="font-mono text-foreground">{reconciliation.decision_id}</span></div>}
                      {reconciliation.origin === "UNPLANNED" && <div className="col-span-2 text-amber-400">来源：明确 UNPLANNED（pre_trade_decision=NONE，pre_trade_thesis=NONE）</div>}
                    </div>
                  )}

                  {reconciliation?.allocation_state === "UNALLOCATED" && (
                    <div className="space-y-2 border-t border-border/40 pt-3">
                      <div className="text-[11px] font-semibold text-amber-400">RECONCILIATION REQUIRED：选择真实、已提交且时间有效的 Frozen Decision</div>
                      {candidateScanState === "INVALID_WITNESS" ? (
                        <p className="text-[11px] text-rose-400">发现 Frozen Decision，但见证校验失败，系统已拒绝归属；请修复决策数据或联系管理员。</p>
                      ) : candidateError ? null : attributionCandidates.length === 0 ? (
                        <p className="text-[11px] text-muted-foreground">没有可归属候选；若该交易确实非计划内，请明确标记 UNPLANNED，系统不会猜测。</p>
                      ) : attributionCandidates.map((candidate) => (
                        <div key={candidate.decision_id} className="flex items-center justify-between gap-3 rounded border border-border/40 bg-muted/20 p-2">
                          <div className="min-w-0">
                            <div className="truncate font-mono text-[11px] text-foreground">{candidate.decision_id}</div>
                            <div className="text-[10px] text-muted-foreground">Campaign {candidate.campaign_id} · {candidate.strategy} · {formatTradeTime(candidate.committed_at)}</div>
                          </div>
                          <button type="button" disabled={reconciliationActionLoading} onClick={() => handleAttribution(candidate.decision_id)} className="shrink-0 rounded bg-primary px-2.5 py-1 text-[11px] font-medium text-primary-foreground disabled:opacity-50">明确归属</button>
                        </div>
                      ))}
                      <button type="button" disabled={reconciliationActionLoading} onClick={handleMarkUnplanned} className="rounded border border-amber-500/40 px-2.5 py-1 text-[11px] font-medium text-amber-400 hover:bg-amber-500/10 disabled:opacity-50">标记为 UNPLANNED</button>
                    </div>
                  )}
                </div>

                {/* 核心指标 Grid */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div className="rounded-lg border border-border/40 bg-card p-3">
                    <div className="text-[11px] text-muted-foreground">成交金额</div>
                    <div className="mt-1 text-sm font-semibold font-mono text-foreground">
                      {formatTradeMoney(detailTrade.gross_amount)}
                    </div>
                  </div>
                  <div className="rounded-lg border border-border/40 bg-card p-3">
                    <div className="text-[11px] text-muted-foreground">总费用</div>
                    <div className="mt-1 text-sm font-semibold font-mono text-foreground">
                      {formatTradeMoney(detailTrade.total_cost)}
                    </div>
                  </div>
                  <div className="rounded-lg border border-border/40 bg-card p-3">
                    <div className="text-[11px] text-muted-foreground">净现金流</div>
                    <div className="mt-1 text-sm font-semibold font-mono text-foreground">
                      {formatTradeMoney(detailTrade.net_cash_flow)}
                    </div>
                  </div>
                  <div className="rounded-lg border border-border/40 bg-card p-3">
                    <div className="text-[11px] text-muted-foreground">数量完成率</div>
                    <div className="mt-1 text-sm font-semibold font-mono text-foreground">
                      {formatTradePercentage(detailTrade.quantity_completion_pct)}
                    </div>
                  </div>
                </div>

                {/* 计划与实际对齐 */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="space-y-2 border border-border/40 rounded-lg p-3 bg-muted/10">
                    <h4 className="font-semibold text-foreground border-b border-border/40 pb-1">
                      计划信息
                    </h4>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">计划价格：</span>
                      <span className="font-mono">{formatTradeMoney(detailTrade.planned_price)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">计划数量：</span>
                      <span className="font-mono">{formatTradeQuantity(detailTrade.planned_quantity)}</span>
                    </div>
                  </div>

                  <div className="space-y-2 border border-border/40 rounded-lg p-3 bg-muted/10">
                    <h4 className="font-semibold text-foreground border-b border-border/40 pb-1">
                      实际执行信息
                    </h4>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">实际价格：</span>
                      <span className="font-mono">{formatTradeMoney(detailTrade.actual_price)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">实际数量：</span>
                      <span className="font-mono">{formatTradeQuantity(detailTrade.actual_quantity)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">成交时间：</span>
                      <span className="font-mono">{formatTradeTime(detailTrade.executed_at)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">价格偏差：</span>
                      <span className="font-mono">
                        {formatTradeMoney(detailTrade.price_variance)} ({formatTradePercentage(detailTrade.price_variance_pct)})
                      </span>
                    </div>
                  </div>
                </div>

                {/* 费用明细 */}
                <div className="border border-border/40 rounded-lg p-3 bg-muted/10 space-y-2">
                  <h4 className="font-semibold text-foreground border-b border-border/40 pb-1">
                    费用明细
                  </h4>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">手续费：</span>
                      <span className="font-mono">{formatTradeMoney(detailTrade.fee)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">其他费用：</span>
                      <span className="font-mono">{formatTradeMoney(detailTrade.other_cost)}</span>
                    </div>
                  </div>
                </div>

                {/* 未执行原因与备注 */}
                {detailTrade.unexecuted_reason && (
                  <div className="border border-border/40 rounded-lg p-3 bg-amber-500/10 space-y-1">
                    <div className="font-semibold text-amber-400">未执行/部分执行原因</div>
                    <p className="text-muted-foreground whitespace-pre-wrap">
                      {detailTrade.unexecuted_reason}
                    </p>
                  </div>
                )}

                {detailTrade.note && (
                  <div className="border border-border/40 rounded-lg p-3 bg-muted/10 space-y-1">
                    <div className="font-semibold text-foreground">备注</div>
                    <p className="text-muted-foreground whitespace-pre-wrap">{detailTrade.note}</p>
                  </div>
                )}

                {/* 建议快照（结构化渲染） */}
                {detailTrade.advice_snapshot && (
                  <div className="border border-border/40 rounded-lg p-3 bg-card space-y-2">
                    <h4 className="font-semibold text-foreground border-b border-border/40 pb-1 flex items-center justify-between">
                      <span>建议快照 (Advice Snapshot)</span>
                      <span className="text-[11px] text-muted-foreground font-mono">
                        置信度: {detailTrade.advice_snapshot.confidence}
                      </span>
                    </h4>
                    <div className="grid grid-cols-2 gap-2 pt-1">
                      <div>
                        <span className="text-muted-foreground">建议动作：</span>
                        <span className="font-medium text-foreground ml-1">
                          {detailTrade.advice_snapshot.action}
                        </span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">建议数量：</span>
                        <span className="font-mono text-foreground ml-1">
                          {formatTradeQuantity(detailTrade.advice_snapshot.execution_quantity)}
                        </span>
                      </div>
                    </div>

                    {detailTrade.advice_snapshot.price_conditions.length > 0 && (
                      <div>
                        <span className="text-muted-foreground">价格条件：</span>
                        <ul className="list-disc list-inside text-muted-foreground pl-1 mt-0.5">
                          {detailTrade.advice_snapshot.price_conditions.map((item, idx) => (
                            <li key={idx}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {detailTrade.advice_snapshot.execution_plan.length > 0 && (
                      <div>
                        <span className="text-muted-foreground">执行计划：</span>
                        <ul className="list-disc list-inside text-muted-foreground pl-1 mt-0.5">
                          {detailTrade.advice_snapshot.execution_plan.map((item, idx) => (
                            <li key={idx}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {detailTrade.advice_snapshot.risk_conditions.length > 0 && (
                      <div>
                        <span className="text-muted-foreground">风险条件：</span>
                        <ul className="list-disc list-inside text-muted-foreground pl-1 mt-0.5">
                          {detailTrade.advice_snapshot.risk_conditions.map((item, idx) => (
                            <li key={idx}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {detailTrade.advice_snapshot.invalidation_conditions.length > 0 && (
                      <div>
                        <span className="text-muted-foreground">失效条件：</span>
                        <ul className="list-disc list-inside text-muted-foreground pl-1 mt-0.5">
                          {detailTrade.advice_snapshot.invalidation_conditions.map((item, idx) => (
                            <li key={idx}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}

                {/* 关联引用 */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-[11px]">
                  <div className="border border-border/40 rounded-lg p-2.5 bg-muted/10 flex items-center justify-between">
                    <div>
                      <span className="text-muted-foreground">建议引用：</span>
                      <span className="ml-1 text-foreground font-mono">
                        {detailTrade.advice_trade_date
                          ? `${detailTrade.advice_trade_date} (${formatTradeTime(detailTrade.advice_generated_at)})`
                          : "无"}
                      </span>
                    </div>
                    {detailTrade.advice_trade_date && (
                      <Link
                        to={`/decision-feedback?code=${detailTrade.code}`}
                        className="ml-2 inline-flex items-center gap-1 rounded bg-primary/10 px-2 py-1 text-[11px] font-medium text-primary hover:bg-primary/20 transition-colors shrink-0"
                      >
                        查看该股票反馈
                      </Link>
                    )}
                  </div>
                  <div className="border border-border/40 rounded-lg p-2.5 bg-muted/10">
                    <span className="text-muted-foreground">Thesis 引用：</span>
                    <span className="ml-1 text-foreground font-mono">
                      {detailTrade.thesis_id
                        ? `${detailTrade.thesis_id} (Rev ${detailTrade.thesis_revision})`
                        : "无"}
                    </span>
                  </div>
                </div>

                <div className="text-[11px] text-muted-foreground/60 text-right pt-2 border-t border-border/40">
                  记录创建时间：{formatTradeTime(detailTrade.created_at)}
                </div>
              </div>
            ) : null}

            <div className="flex justify-end pt-3 border-t border-border/40">
              <button
                type="button"
                onClick={() => setSelectedTradeId(null)}
                className="rounded-md border border-input px-4 py-1.5 text-xs font-medium hover:bg-accent"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 作废确认 Modal */}
      {voidTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border border-border bg-background p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-border/40 pb-3">
              <h3 className="text-base font-semibold text-rose-400 flex items-center gap-1.5">
                <Ban className="h-5 w-5" />
                作废交易确认
              </h3>
              <button
                type="button"
                onClick={() => setVoidTarget(null)}
                className="rounded-lg p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <p className="text-xs text-foreground">
              确定要作废{" "}
              <span className="font-semibold">
                {voidTarget.name} ({voidTarget.code})
              </span>{" "}
              的交易记录（ID: {voidTarget.trade_id}）吗？此操作不可撤销。
            </p>

            <form onSubmit={handleVoidSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-foreground mb-1">
                  作废原因 <span className="text-rose-400">*</span>
                </label>
                <textarea
                  rows={3}
                  required
                  placeholder="请输入作废原因"
                  value={voidReason}
                  onChange={(e) => setVoidReason(e.target.value)}
                  className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-rose-500"
                />
              </div>

              {voidError && (
                <div className="rounded-lg bg-rose-500/15 p-3 text-xs text-rose-400 border border-rose-500/20 flex items-center gap-2">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  <span>{voidError}</span>
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-border/40">
                <button
                  type="button"
                  onClick={() => setVoidTarget(null)}
                  className="rounded-md border border-input px-4 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={voidLoading}
                  className="inline-flex items-center gap-1.5 rounded-md bg-rose-500 px-4 py-1.5 text-xs font-medium text-white hover:bg-rose-600 disabled:opacity-50"
                >
                  {voidLoading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  确认作废
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
