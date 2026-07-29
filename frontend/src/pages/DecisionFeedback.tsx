import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, ApiError, type DecisionFeedbackRecord } from "@/lib/api";
import {
  adoptionStatusLabel,
  buildFeedbackCreateInput,
  buildFeedbackListQuery,
  formatFeedbackTime,
  outcomeStatusLabel,
  validateFeedbackDraft,
  validateFeedbackListFilters,
  type DecisionFeedbackDraft,
  type DecisionFeedbackListFilters,
} from "@/lib/decisionFeedbackView";
import {
  AlertCircle,
  Ban,
  CheckCircle2,
  Filter,
  Loader2,
  MessageSquareCode,
  Plus,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

const PAGE_LIMIT = 10;

export function DecisionFeedback() {
  const [searchParams] = useSearchParams();
  const initialCodeParam = searchParams.get("code") || "";

  // List state
  const [feedbacks, setFeedbacks] = useState<DecisionFeedbackRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Filters state
  const [filters, setFilters] = useState<DecisionFeedbackListFilters>({
    code: initialCodeParam,
    adoption_status: "",
    outcome_status: "",
    date_from: "",
    date_to: "",
    include_voided: false,
  });
  const [appliedFilters, setAppliedFilters] = useState<DecisionFeedbackListFilters>({
    code: initialCodeParam,
    adoption_status: "",
    outcome_status: "",
    date_from: "",
    date_to: "",
    include_voided: false,
  });
  const [filterError, setFilterError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);

  // Detail modal state
  const [selectedFeedbackId, setSelectedFeedbackId] = useState<string | null>(null);
  const [detailFeedback, setDetailFeedback] = useState<DecisionFeedbackRecord | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Create modal state
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [createDraft, setCreateDraft] = useState<DecisionFeedbackDraft>({
    code: "",
    advice_trade_date: new Date().toISOString().split("T")[0],
    advice_generated_at: new Date().toISOString(),
    trade_id: "",
    adoption_status: "followed",
    outcome_status: "as_expected",
    note: "",
  });
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Void modal state
  const [voidTarget, setVoidTarget] = useState<DecisionFeedbackRecord | null>(null);
  const [voidReason, setVoidReason] = useState("");
  const [voidLoading, setVoidLoading] = useState(false);
  const [voidError, setVoidError] = useState<string | null>(null);

  // Load list
  const loadFeedbacks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const query = buildFeedbackListQuery(appliedFilters, PAGE_LIMIT, offset);
      const data = await api.listDecisionFeedbacks(query);
      setFeedbacks(data);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(e.message);
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("加载决策反馈列表失败");
      }
    } finally {
      setLoading(false);
    }
  }, [appliedFilters, offset]);

  useEffect(() => {
    loadFeedbacks();
  }, [loadFeedbacks]);

  // Load detail
  const loadDetail = useCallback(async (id: string) => {
    setDetailLoading(true);
    setDetailError(null);
    try {
      const record = await api.getDecisionFeedback(id);
      setDetailFeedback(record);
    } catch (e) {
      if (e instanceof ApiError) {
        setDetailError(e.message);
      } else if (e instanceof Error) {
        setDetailError(e.message);
      } else {
        setDetailError("加载决策反馈详情失败");
      }
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedFeedbackId) {
      loadDetail(selectedFeedbackId);
    } else {
      setDetailFeedback(null);
      setDetailError(null);
    }
  }, [selectedFeedbackId, loadDetail]);

  // Handle filter submit
  const handleFilterSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const err = validateFeedbackListFilters(filters);
    if (err) {
      setFilterError(err);
      return;
    }
    setFilterError(null);
    setOffset(0);
    setAppliedFilters(filters);
  };

  const handleFilterReset = () => {
    const emptyFilters: DecisionFeedbackListFilters = {
      code: "",
      adoption_status: "",
      outcome_status: "",
      date_from: "",
      date_to: "",
      include_voided: false,
    };
    setFilters(emptyFilters);
    setFilterError(null);
    setOffset(0);
    setAppliedFilters(emptyFilters);
  };

  // Create handlers
  const handleOpenCreate = () => {
    setCreateDraft({
      code: initialCodeParam || "",
      advice_trade_date: new Date().toISOString().split("T")[0],
      advice_generated_at: new Date().toISOString(),
      trade_id: "",
      adoption_status: "followed",
      outcome_status: "as_expected",
      note: "",
    });
    setCreateError(null);
    setIsCreateOpen(true);
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const err = validateFeedbackDraft(createDraft);
    if (err) {
      setCreateError(err);
      return;
    }
    setCreateLoading(true);
    setCreateError(null);

    try {
      const input = buildFeedbackCreateInput(createDraft);
      await api.createDecisionFeedback(input);
      setIsCreateOpen(false);
      setSuccessMsg("决策反馈已新建");
      setTimeout(() => setSuccessMsg(null), 3000);
      loadFeedbacks();
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 404) {
          setCreateError("关联数据不存在（持仓建议或交易记录）");
        } else if (e.status === 409) {
          setCreateError("建议发生变化，生成时间不一致");
        } else {
          setCreateError(e.message);
        }
      } else if (e instanceof Error) {
        setCreateError(e.message);
      } else {
        setCreateError("创建决策反馈失败");
      }
    } finally {
      setCreateLoading(false);
    }
  };

  // Void handlers
  const handleOpenVoid = (record: DecisionFeedbackRecord) => {
    setVoidTarget(record);
    setVoidReason("");
    setVoidError(null);
  };

  const handleVoidSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!voidTarget) return;
    setVoidLoading(true);
    setVoidError(null);

    try {
      await api.voidDecisionFeedback(voidTarget.feedback_id, voidReason.trim() || undefined);
      const voidedId = voidTarget.feedback_id;
      setVoidTarget(null);
      setSuccessMsg("决策反馈已成功作废");
      setTimeout(() => setSuccessMsg(null), 3000);
      loadFeedbacks();
      if (selectedFeedbackId === voidedId) {
        loadDetail(voidedId);
      }
    } catch (e) {
      if (e instanceof ApiError) {
        setVoidError(e.message);
      } else if (e instanceof Error) {
        setVoidError(e.message);
      } else {
        setVoidError("作废决策反馈失败");
      }
    } finally {
      setVoidLoading(false);
    }
  };

  // Pagination
  const handlePrevPage = () => {
    if (offset >= PAGE_LIMIT) {
      setOffset(offset - PAGE_LIMIT);
    }
  };

  const handleNextPage = () => {
    if (feedbacks.length >= PAGE_LIMIT) {
      setOffset(offset + PAGE_LIMIT);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="决策反馈"
        subtitle="对比 AI 建议与后续表现，完成决策闭环"
        actions={
          <button
            type="button"
            onClick={handleOpenCreate}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" />
            新建决策反馈
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
              <label className="block text-[11px] text-muted-foreground mb-1">采纳执行状态</label>
              <select
                value={filters.adoption_status || ""}
                onChange={(e) =>
                  setFilters({
                    ...filters,
                    adoption_status: (e.target.value as any) || "",
                  })
                }
                className="w-full rounded-md border border-input bg-background/50 px-2.5 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="">所有采纳状态</option>
                <option value="followed">按照建议执行</option>
                <option value="partially_followed">部分执行建议</option>
                <option value="not_followed">明确未执行</option>
                <option value="not_applicable">不适用/未达成条件</option>
              </select>
            </div>

            <div>
              <label className="block text-[11px] text-muted-foreground mb-1">事后评估结果</label>
              <select
                value={filters.outcome_status || ""}
                onChange={(e) =>
                  setFilters({
                    ...filters,
                    outcome_status: (e.target.value as any) || "",
                  })
                }
                className="w-full rounded-md border border-input bg-background/50 px-2.5 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="">所有评估结果</option>
                <option value="better_than_expected">超出预期</option>
                <option value="as_expected">符合预期</option>
                <option value="worse_than_expected">低于预期</option>
                <option value="not_evaluated">暂未评估</option>
              </select>
            </div>

            <div>
              <label className="block text-[11px] text-muted-foreground mb-1">开始日期</label>
              <input
                type="date"
                value={filters.date_from || ""}
                onChange={(e) => setFilters({ ...filters, date_from: e.target.value })}
                className="w-full rounded-md border border-input bg-background/50 px-2.5 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>

            <div>
              <label className="block text-[11px] text-muted-foreground mb-1">结束日期</label>
              <input
                type="date"
                value={filters.date_to || ""}
                onChange={(e) => setFilters({ ...filters, date_to: e.target.value })}
                className="w-full rounded-md border border-input bg-background/50 px-2.5 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>

            <div className="flex items-center pt-5">
              <label className="inline-flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
                <input
                  type="checkbox"
                  checked={filters.include_voided || false}
                  onChange={(e) =>
                    setFilters({ ...filters, include_voided: e.target.checked })
                  }
                  className="rounded border-input text-primary focus:ring-primary"
                />
                包含已作废记录
              </label>
            </div>
          </div>

          {filterError && (
            <div className="text-xs text-rose-400 font-medium flex items-center gap-1">
              <AlertCircle className="h-3.5 w-3.5" />
              <span>{filterError}</span>
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-2 border-t border-border/40">
            <button
              type="button"
              onClick={handleFilterReset}
              className="inline-flex items-center gap-1 rounded-md border border-input px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              重置
            </button>
            <button
              type="submit"
              className="inline-flex items-center gap-1 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
            >
              <Search className="h-3.5 w-3.5" />
              筛选
            </button>
          </div>
        </form>
      </GlassCard>

      {/* 反馈列表 */}
      {loading ? (
        <GlassCard className="p-12 text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto text-primary" />
          <p className="mt-3 text-xs text-muted-foreground">正在加载决策反馈流水...</p>
        </GlassCard>
      ) : error ? (
        <GlassCard className="p-6 text-center space-y-3">
          <div className="inline-flex items-center justify-center rounded-full bg-rose-500/15 p-3 text-rose-400">
            <AlertCircle className="h-6 w-6" />
          </div>
          <p className="text-sm font-medium text-rose-400">{error}</p>
          <button
            type="button"
            onClick={loadFeedbacks}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            重试加载
          </button>
        </GlassCard>
      ) : feedbacks.length === 0 ? (
        <GlassCard className="p-12 text-center space-y-3">
          <div className="inline-flex items-center justify-center rounded-full bg-muted p-4 text-muted-foreground">
            <MessageSquareCode className="h-8 w-8" />
          </div>
          <h3 className="text-sm font-semibold text-foreground">未查找到决策反馈记录</h3>
          <p className="text-xs text-muted-foreground">
            请尝试调整筛选条件，或通过右上角按钮新建一条决策反馈。
          </p>
        </GlassCard>
      ) : (
        <GlassCard className="overflow-hidden p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-muted/40 border-b border-border/40 text-muted-foreground font-medium">
                <tr>
                  <th className="p-3">创建时间</th>
                  <th className="p-3">股票代码</th>
                  <th className="p-3">建议日期</th>
                  <th className="p-3">关联交易</th>
                  <th className="p-3">采纳执行状态</th>
                  <th className="p-3">事后评估结果</th>
                  <th className="p-3 text-center">状态</th>
                  <th className="p-3 text-center">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {feedbacks.map((item) => {
                  const isVoided = !!item.voided_at;
                  return (
                    <tr
                      key={item.feedback_id}
                      className={cn(
                        "hover:bg-muted/30 transition-colors",
                        isVoided && "opacity-60 bg-muted/10",
                      )}
                    >
                      <td className="p-3 text-muted-foreground font-mono">
                        {formatFeedbackTime(item.created_at)}
                      </td>
                      <td className="p-3 font-mono font-medium text-foreground">
                        {item.code}
                      </td>
                      <td className="p-3 font-mono text-muted-foreground">
                        {item.advice_trade_date}
                      </td>
                      <td className="p-3 font-mono text-xs">
                        {item.trade_id ? (
                          <span className="text-primary">{item.trade_id}</span>
                        ) : (
                          <span className="text-muted-foreground/60">—</span>
                        )}
                      </td>
                      <td className="p-3">
                        <span
                          className={cn(
                            "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium",
                            item.adoption_status === "followed"
                              ? "bg-emerald-500/15 text-emerald-400"
                              : item.adoption_status === "partially_followed"
                                ? "bg-amber-500/15 text-amber-400"
                                : item.adoption_status === "not_followed"
                                  ? "bg-rose-500/15 text-rose-400"
                                  : "bg-slate-500/15 text-slate-400",
                          )}
                        >
                          {adoptionStatusLabel(item.adoption_status)}
                        </span>
                      </td>
                      <td className="p-3">
                        <span
                          className={cn(
                            "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium",
                            item.outcome_status === "better_than_expected"
                              ? "bg-emerald-500/15 text-emerald-400"
                              : item.outcome_status === "as_expected"
                                ? "bg-blue-500/15 text-blue-400"
                                : item.outcome_status === "worse_than_expected"
                                  ? "bg-rose-500/15 text-rose-400"
                                  : "bg-slate-500/15 text-slate-400",
                          )}
                        >
                          {outcomeStatusLabel(item.outcome_status)}
                        </span>
                      </td>
                      <td className="p-3 text-center">
                        {isVoided ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/15 px-2 py-0.5 text-[10px] text-rose-400 font-medium">
                            <Ban className="h-3 w-3" />
                            已作废
                          </span>
                        ) : (
                          <span className="text-muted-foreground/60 text-[11px]">正常</span>
                        )}
                      </td>
                      <td className="p-3 text-center space-x-2">
                        <button
                          type="button"
                          onClick={() => setSelectedFeedbackId(item.feedback_id)}
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
                disabled={feedbacks.length < PAGE_LIMIT}
                className="rounded-md border border-input px-3 py-1 text-xs font-medium hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed"
              >
                下一页
              </button>
            </div>
          </div>
        </GlassCard>
      )}

      {/* 新建 Modal */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm overflow-y-auto">
          <div className="w-full max-w-lg rounded-xl border border-border bg-background p-6 shadow-2xl space-y-4 my-8">
            <div className="flex items-center justify-between border-b border-border/40 pb-3">
              <h3 className="text-base font-semibold text-foreground">新建决策反馈</h3>
              <button
                type="button"
                onClick={() => setIsCreateOpen(false)}
                className="rounded-lg p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleCreateSubmit} className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">
                    股票代码 <span className="text-rose-400">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    maxLength={6}
                    placeholder="6位数字"
                    value={createDraft.code}
                    onChange={(e) => setCreateDraft({ ...createDraft, code: e.target.value })}
                    className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">
                    建议交易日期 <span className="text-rose-400">*</span>
                  </label>
                  <input
                    type="date"
                    required
                    value={createDraft.advice_trade_date}
                    onChange={(e) =>
                      setCreateDraft({ ...createDraft, advice_trade_date: e.target.value })
                    }
                    className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">
                  建议生成时间 (ISO) <span className="text-rose-400">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="如 2026-07-29T08:00:00Z"
                  value={createDraft.advice_generated_at}
                  onChange={(e) =>
                    setCreateDraft({ ...createDraft, advice_generated_at: e.target.value })
                  }
                  className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">
                  关联交易 ID (可选)
                </label>
                <input
                  type="text"
                  placeholder="如 trade_xxx"
                  value={createDraft.trade_id || ""}
                  onChange={(e) =>
                    setCreateDraft({ ...createDraft, trade_id: e.target.value })
                  }
                  className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">
                    采纳执行状态 <span className="text-rose-400">*</span>
                  </label>
                  <select
                    value={createDraft.adoption_status}
                    onChange={(e) =>
                      setCreateDraft({
                        ...createDraft,
                        adoption_status: e.target.value as any,
                      })
                    }
                    className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                  >
                    <option value="followed">按照建议执行</option>
                    <option value="partially_followed">部分执行建议</option>
                    <option value="not_followed">明确未执行</option>
                    <option value="not_applicable">不适用/未达成条件</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">
                    事后评估结果 <span className="text-rose-400">*</span>
                  </label>
                  <select
                    value={createDraft.outcome_status}
                    onChange={(e) =>
                      setCreateDraft({
                        ...createDraft,
                        outcome_status: e.target.value as any,
                      })
                    }
                    className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                  >
                    <option value="better_than_expected">超出预期</option>
                    <option value="as_expected">符合预期</option>
                    <option value="worse_than_expected">低于预期</option>
                    <option value="not_evaluated">暂未评估</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">备注说明</label>
                <textarea
                  rows={3}
                  placeholder="请输入决策复盘与反馈备注（最多 2000 字符）"
                  value={createDraft.note || ""}
                  onChange={(e) => setCreateDraft({ ...createDraft, note: e.target.value })}
                  className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
                />
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

      {/* 详情 Modal */}
      {selectedFeedbackId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm overflow-y-auto">
          <div className="w-full max-w-xl rounded-xl border border-border bg-background p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-border/40 pb-3">
              <h3 className="text-base font-semibold text-foreground">决策反馈详情</h3>
              <button
                type="button"
                onClick={() => setSelectedFeedbackId(null)}
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
            ) : detailFeedback ? (
              <div className="space-y-4 text-xs">
                {/* 标头 */}
                <div className="rounded-lg bg-muted/30 p-4 space-y-2 border border-border/40">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-base font-bold text-foreground">
                        代码 {detailFeedback.code}
                      </span>
                      <span className="ml-2 font-mono text-[11px] text-muted-foreground">
                        ID: {detailFeedback.feedback_id}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="rounded-full bg-primary/15 px-2.5 py-0.5 font-medium text-primary">
                        {adoptionStatusLabel(detailFeedback.adoption_status)}
                      </span>
                      <span className="rounded-full bg-muted px-2.5 py-0.5 font-medium text-foreground">
                        {outcomeStatusLabel(detailFeedback.outcome_status)}
                      </span>
                    </div>
                  </div>

                  {detailFeedback.voided_at && (
                    <div className="mt-2 rounded bg-rose-500/15 p-2 text-rose-400 border border-rose-500/20 space-y-1">
                      <div className="font-semibold flex items-center gap-1">
                        <Ban className="h-3.5 w-3.5" />
                        该反馈已于 {formatFeedbackTime(detailFeedback.voided_at)} 作废
                      </div>
                      <div>作废原因：{detailFeedback.void_reason || "无"}</div>
                    </div>
                  )}
                </div>

                {/* 关联 AI 建议与交易信息 */}
                <div className="border border-border/40 rounded-lg p-3 bg-muted/10 space-y-2">
                  <h4 className="font-semibold text-foreground border-b border-border/40 pb-1">
                    关联引用
                  </h4>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <span className="text-muted-foreground">建议交易日期：</span>
                      <span className="font-mono text-foreground">{detailFeedback.advice_trade_date}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">建议生成时间：</span>
                      <span className="font-mono text-foreground text-[11px]">
                        {detailFeedback.advice_generated_at}
                      </span>
                    </div>
                  </div>

                  <div className="pt-2 flex items-center justify-between border-t border-border/20">
                    <div>
                      <span className="text-muted-foreground">关联交易 ID：</span>
                      <span className="font-mono text-foreground">
                        {detailFeedback.trade_id || "无"}
                      </span>
                    </div>
                    {detailFeedback.trade_id && (
                      <Link
                        to={`/trades`}
                        className="text-primary hover:underline font-medium text-xs"
                      >
                        跳转交易流水
                      </Link>
                    )}
                  </div>
                </div>

                {/* 备注 */}
                {detailFeedback.note && (
                  <div className="border border-border/40 rounded-lg p-3 bg-card space-y-1">
                    <div className="font-semibold text-foreground">备注说明</div>
                    <p className="text-muted-foreground whitespace-pre-wrap">{detailFeedback.note}</p>
                  </div>
                )}

                {/* 元数据 */}
                <div className="text-[11px] text-muted-foreground/80 flex justify-between border-t border-border/40 pt-2">
                  <span>创建时间：{formatFeedbackTime(detailFeedback.created_at)}</span>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}

      {/* 作废 Modal */}
      {voidTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border border-border bg-background p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-border/40 pb-3">
              <h3 className="text-base font-semibold text-foreground flex items-center gap-1.5 text-rose-400">
                <Ban className="h-5 w-5" />
                作废决策反馈
              </h3>
              <button
                type="button"
                onClick={() => setVoidTarget(null)}
                className="rounded-lg p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <p className="text-xs text-muted-foreground">
              确认作废反馈 ID 为 <span className="font-mono text-foreground font-semibold">{voidTarget.feedback_id}</span> 的记录？作废后该记录不再纳入有效反馈。
            </p>

            <form onSubmit={handleVoidSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-foreground mb-1">
                  作废原因 (可选)
                </label>
                <textarea
                  rows={2}
                  placeholder="请输入作废原因..."
                  value={voidReason}
                  onChange={(e) => setVoidReason(e.target.value)}
                  className="w-full rounded-md border border-input bg-background/50 px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-primary"
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
