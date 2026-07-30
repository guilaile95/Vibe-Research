import React, { useEffect, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import {
  Activity,
  ArrowLeft,
  CheckCircle2,
  AlertTriangle,
  Layers,
  Search,
  RefreshCw,
  FileCode,
} from "lucide-react";
import { api, ApiError } from "../lib/api";
import type {
  SignalEntryRecord,
  DecisionOutcomeRecord,
  DecisionRunRecord,
  SignalStage,
  SignalSeverity,
} from "../lib/api/types";
import {
  stageLabel,
  stageBadgeColor,
  severityLabel,
  severityBadgeColor,
  actionLabel,
  actionBadgeColor,
  formatSignalTime,
  validateSignalFilters,
  SignalLedgerFilters,
} from "../lib/signalLedgerView";

export default function SignalLedger() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialRunId = searchParams.get("decision_run_id") || "";

  const [filters, setFilters] = useState<SignalLedgerFilters>({
    decision_run_id: initialRunId,
    stage: "",
    code: "",
    severity: "",
  });

  const [runRecord, setRunRecord] = useState<DecisionRunRecord | null>(null);
  const [signalEntries, setSignalEntries] = useState<SignalEntryRecord[]>([]);
  const [decisionOutcomes, setDecisionOutcomes] = useState<DecisionOutcomeRecord[]>([]);

  const [loading, setLoading] = useState<boolean>(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [filterError, setFilterError] = useState<string | null>(null);

  const fetchData = async (currentFilters: SignalLedgerFilters) => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const targetRunId = currentFilters.decision_run_id?.trim();
      if (targetRunId) {
        // Run detail mode
        const detail = await api.getRunSignalLedger(targetRunId);
        setRunRecord(detail.run);
        setSignalEntries(detail.signal_entries);
        setDecisionOutcomes(detail.decision_outcomes);
      } else {
        // General query mode
        setRunRecord(null);
        setDecisionOutcomes([]);
        const queryRes = await api.listSignalEntries({
          stage: currentFilters.stage || undefined,
          code: currentFilters.code?.trim() || undefined,
          severity: currentFilters.severity || undefined,
          limit: 100,
        });
        setSignalEntries(queryRes.items);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(err.message);
      } else {
        setErrorMsg("加载信号账本失败，请稍后重试");
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData(filters);
  }, []);

  const handleFilterSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const vErr = validateSignalFilters(filters);
    if (vErr) {
      setFilterError(vErr);
      return;
    }
    setFilterError(null);

    // Sync URL search params
    const newParams = new URLSearchParams();
    if (filters.decision_run_id?.trim()) {
      newParams.set("decision_run_id", filters.decision_run_id.trim());
    }
    setSearchParams(newParams);

    fetchData(filters);
  };

  return (
    <div className="max-w-7xl mx-auto px-4 py-8 space-y-6">
      {/* 顶部标题与返回 */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-sm text-gray-500 mb-1">
            <Link
              to="/decision-evidence"
              className="hover:text-gray-900 dark:hover:text-white flex items-center gap-1 transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              返回决策依据
            </Link>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Activity className="w-7 h-7 text-indigo-600 dark:text-indigo-400" />
            信号账本 (Signal Ledger)
          </h1>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
            全流程决策流水：追踪从 Schema 校验、事实对账、策略风控到最终执行裁决的信号轨迹。
          </p>
        </div>
      </div>

      {/* 筛选栏 */}
      <div className="bg-white dark:bg-gray-800 p-4 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm">
        <form onSubmit={handleFilterSubmit} className="flex flex-wrap items-center gap-3">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-xs text-gray-500 mb-1">决策 ID (Run ID)</label>
            <input
              type="text"
              placeholder="e.g. dr_..."
              value={filters.decision_run_id || ""}
              onChange={(e) => setFilters({ ...filters, decision_run_id: e.target.value })}
              className="w-full text-xs px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-white font-mono"
            />
          </div>

          <div className="w-36">
            <label className="block text-xs text-gray-500 mb-1">阶段 (Stage)</label>
            <select
              value={filters.stage || ""}
              onChange={(e) => setFilters({ ...filters, stage: e.target.value as SignalStage })}
              className="w-full text-xs px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
            >
              <option value="">全部阶段</option>
              <option value="schema">模式校验</option>
              <option value="compatibility">兼容核验</option>
              <option value="fact_reconciliation">事实对账</option>
              <option value="policy_audit">策略风控</option>
              <option value="execution">执行裁决</option>
              <option value="narrative_audit">叙事审核</option>
              <option value="account_constraint">资金约束</option>
            </select>
          </div>

          <div className="w-28">
            <label className="block text-xs text-gray-500 mb-1">股票代码</label>
            <input
              type="text"
              placeholder="6位代码"
              value={filters.code || ""}
              onChange={(e) => setFilters({ ...filters, code: e.target.value })}
              className="w-full text-xs px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-white font-mono"
            />
          </div>

          <div className="w-28">
            <label className="block text-xs text-gray-500 mb-1">严重程度</label>
            <select
              value={filters.severity || ""}
              onChange={(e) => setFilters({ ...filters, severity: e.target.value as SignalSeverity })}
              className="w-full text-xs px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
            >
              <option value="">全部级别</option>
              <option value="info">正常 (Info)</option>
              <option value="warning">预警 (Warning)</option>
              <option value="error">错误 (Error)</option>
            </select>
          </div>

          <div className="flex items-end gap-2 mt-4 sm:mt-0">
            <button
              type="submit"
              className="px-4 py-1.5 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg flex items-center gap-1.5 transition-colors"
            >
              <Search className="w-3.5 h-3.5" />
              查询信号
            </button>
            <button
              type="button"
              onClick={() => {
                const cleared: SignalLedgerFilters = { decision_run_id: "", stage: "", code: "", severity: "" };
                setFilters(cleared);
                setSearchParams(new URLSearchParams());
                fetchData(cleared);
              }}
              className="px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 bg-gray-100 hover:bg-gray-200 dark:bg-gray-700 dark:hover:bg-gray-600 rounded-lg transition-colors"
            >
              重置
            </button>
          </div>
        </form>
        {filterError && (
          <p className="text-xs text-rose-500 mt-2 font-medium">{filterError}</p>
        )}
      </div>

      {/* 错误提示 */}
      {errorMsg && (
        <div className="bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800 p-4 rounded-xl flex items-center justify-between">
          <div className="flex items-center gap-2 text-rose-700 dark:text-rose-300 text-sm">
            <AlertTriangle className="w-5 h-5 flex-shrink-0" />
            <span>{errorMsg}</span>
          </div>
          <button
            onClick={() => fetchData(filters)}
            className="px-3 py-1 text-xs bg-rose-600 text-white rounded-lg hover:bg-rose-700 transition-colors flex items-center gap-1"
          >
            <RefreshCw className="w-3 h-3" />
            重试
          </button>
        </div>
      )}

      {/* 决策 Run 元信息卡片（仅在指定 Run ID 时显示） */}
      {runRecord && (
        <div className="bg-gradient-to-r from-indigo-900/10 via-purple-900/10 to-blue-900/10 dark:from-indigo-950/40 dark:to-blue-950/40 border border-indigo-200 dark:border-indigo-800 p-5 rounded-xl">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono text-indigo-600 dark:text-indigo-400 font-semibold">
                  Run ID: {runRecord.decision_run_id}
                </span>
                <span className="px-2 py-0.5 text-xs rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 font-medium">
                  {runRecord.trace_status || "archived"}
                </span>
              </div>
              <p className="text-sm text-gray-700 dark:text-gray-300 mt-1">
                交易日：<span className="font-semibold">{runRecord.trade_date}</span> | 生成时间：
                <span className="font-mono">{formatSignalTime(runRecord.generated_at)}</span>
              </p>
            </div>
            <Link
              to={`/decision-evidence?decision_run_id=${encodeURIComponent(runRecord.decision_run_id || "")}`}
              className="text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1"
            >
              查看决策依据详情 &rarr;
            </Link>
          </div>
        </div>
      )}

      {/* 最终决策裁决 Outcome 卡片区域 */}
      {decisionOutcomes.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-base font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <CheckCircle2 className="w-5 h-5 text-emerald-500" />
            最终裁决结果 (Decision Outcomes)
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {decisionOutcomes.map((doRecord) => (
              <div
                key={doRecord.outcome_id}
                className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 shadow-sm hover:shadow transition-shadow"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono font-bold text-gray-900 dark:text-white text-base">
                    {doRecord.code}
                  </span>
                  <span className={`px-2.5 py-0.5 rounded-full text-xs font-semibold border ${actionBadgeColor(doRecord.action)}`}>
                    {actionLabel(doRecord.action)}
                  </span>
                </div>

                {doRecord.target_ratio != null && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">
                    执行比例（相对当前持股）：
                    <span className="font-semibold text-gray-800 dark:text-gray-200">
                      {(doRecord.target_ratio * 100).toFixed(1)}%
                    </span>
                  </p>
                )}

                <p className="text-xs text-gray-600 dark:text-gray-300 mt-2 bg-gray-50 dark:bg-gray-900/50 p-2 rounded-lg border border-gray-100 dark:border-gray-800">
                  {doRecord.reason}
                </p>

                {doRecord.constraints_applied_json && doRecord.constraints_applied_json.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {doRecord.constraints_applied_json.map((c, i) => (
                      <span
                        key={i}
                        className="px-2 py-0.5 text-[10px] rounded bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300 border border-amber-200 dark:border-amber-800"
                      >
                        {c}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 时间线 / 信号列表 */}
      <div className="space-y-3">
        <h2 className="text-base font-semibold text-gray-900 dark:text-white flex items-center gap-2">
          <Layers className="w-5 h-5 text-indigo-500" />
          阶段流水时间线 ({signalEntries.length} 条信号)
        </h2>

        {loading ? (
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-12 text-center">
            <RefreshCw className="w-8 h-8 text-indigo-500 animate-spin mx-auto mb-3" />
            <p className="text-sm text-gray-500">正在加载信号流水...</p>
          </div>
        ) : signalEntries.length === 0 ? (
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-12 text-center">
            <FileCode className="w-10 h-10 text-gray-400 mx-auto mb-3" />
            <p className="text-sm text-gray-500 font-medium">暂无信号记录</p>
            <p className="text-xs text-gray-400 mt-1">
              请检查筛选条件，或在「持仓建议」页面生成最新建议后查看流水。
            </p>
          </div>
        ) : (
          <div className="relative border-l-2 border-indigo-200 dark:border-indigo-900 ml-4 space-y-6 py-2">
            {signalEntries.map((sig) => (
              <div key={sig.entry_id} className="relative pl-6">
                {/* 节点点位 */}
                <div className="absolute -left-[9px] top-1.5 w-4 h-4 rounded-full bg-white dark:bg-gray-900 border-2 border-indigo-500 flex items-center justify-center">
                  <div className="w-1.5 h-1.5 rounded-full bg-indigo-600 dark:bg-indigo-400" />
                </div>

                {/* 卡片正文 */}
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 shadow-sm hover:border-indigo-300 dark:hover:border-indigo-700 transition-colors">
                  <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`px-2.5 py-0.5 rounded-md text-xs font-medium border ${stageBadgeColor(sig.stage)}`}>
                        {stageLabel(sig.stage)}
                      </span>
                      <span className={`px-2 py-0.5 rounded-md text-xs font-medium border ${severityBadgeColor(sig.severity)}`}>
                        {severityLabel(sig.severity)}
                      </span>
                      <span className="text-xs font-mono text-gray-500 dark:text-gray-400 font-semibold">
                        {sig.signal_type}
                      </span>
                      {sig.code && (
                        <span className="px-2 py-0.5 text-xs bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded font-mono">
                          {sig.code}
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-gray-400 font-mono">
                      {formatSignalTime(sig.created_at)}
                    </span>
                  </div>

                  <div className="bg-gray-50 dark:bg-gray-900/60 rounded-lg p-3 font-mono text-xs text-gray-800 dark:text-gray-200 overflow-x-auto border border-gray-100 dark:border-gray-800">
                    <pre className="whitespace-pre-wrap break-words font-sans">
                      {JSON.stringify(sig.payload_json, null, 2)}
                    </pre>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
