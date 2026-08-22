import React, { useState, useEffect } from "react";
import { Settings2, Save, RotateCcw, CheckCircle2, AlertCircle } from "lucide-react";
import { api } from "@/lib/api";
import type {
  AccountExecutionPolicy,
  AccountExecutionPolicyStatus,
} from "@/lib/api/types";

const DEFAULT_POLICY: AccountExecutionPolicy = {
  lot_size: 100,
  min_cash_reserve_pct: 0.10,
  max_single_stock_allocation_pct: 0.30,
  tie_breaker_order: "code_asc",
  allow_partial_execution: true,
};

export default function AccountPolicy() {
  const [policy, setPolicy] = useState<AccountExecutionPolicy>(DEFAULT_POLICY);
  const [policyStatus, setPolicyStatus] = useState<AccountExecutionPolicyStatus | "error">("default");
  const [policyReasonCode, setPolicyReasonCode] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<"ok" | "error" | null>(null);
  const [errorMsg, setErrorMsg] = useState<string>("");

  useEffect(() => {
    api.getAccountExecutionPolicy()
      .then((response) => {
        setPolicyStatus(response.status);
        setPolicyReasonCode(response.reason_code);
        if (response.data) setPolicy(response.data);
      })
      .catch((err: any) => {
        setPolicyStatus("error");
        setPolicyReasonCode(null);
        setErrorMsg(err?.message || "执行策略读取失败");
      })
      .finally(() => setLoading(false));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSaveResult(null);
    try {
      const saved = await api.updateAccountExecutionPolicy(policy);
      if (!saved.data) throw new Error("保存后的执行策略不可用");
      setPolicy(saved.data);
      setPolicyStatus(saved.status);
      setPolicyReasonCode(saved.reason_code);
      setSaveResult("ok");
    } catch (err: any) {
      setErrorMsg(err?.message || "保存失败");
      setSaveResult("error");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setPolicy(DEFAULT_POLICY);
    setSaveResult(null);
  };

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center gap-3">
        <Settings2 className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-xl font-bold">执行策略</h1>
          <p className="text-sm text-muted-foreground">配置账户资金执行约束参数</p>
        </div>
      </div>

      {loading ? (
        <div className="flex min-h-[20vh] items-center justify-center text-sm text-muted-foreground">
          加载中…
        </div>
      ) : (
        <>
          {policyStatus === "corrupted" && (
            <div data-testid="account-execution-policy-corrupted" className="rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
              <p className="font-semibold">账户执行策略损坏/不可读取</p>
              <p className="mt-1">当前不会使用默认策略生成可执行数量；请修改后显式保存新策略。</p>
              <p className="mt-1 font-mono text-xs">{policyReasonCode || "ACCOUNT_EXECUTION_POLICY_CORRUPTED"}</p>
            </div>
          )}
          {policyStatus === "default" && (
            <div data-testid="account-execution-policy-default" className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
              未配置账户执行策略，当前使用默认策略；如需持久化，请显式保存。
            </div>
          )}
          {policyStatus === "configured" && (
            <div data-testid="account-execution-policy-configured" className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
              当前使用已配置的账户执行策略。
            </div>
          )}
          {policyStatus === "error" && (
            <div data-testid="account-execution-policy-load-error" className="rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
              {errorMsg || "执行策略读取失败"}
            </div>
          )}
          <form onSubmit={handleSubmit} className="space-y-6">
          <div className="rounded-xl border border-border/60 bg-card p-6 shadow-sm space-y-6">

            {/* lot_size */}
            <div className="grid gap-1.5">
              <label className="text-sm font-medium" htmlFor="lot_size">
                每手股数
              </label>
              <p className="text-xs text-muted-foreground">
                A 股标准为 100 股/手，不足一手时不执行买入
              </p>
              <input
                id="lot_size"
                type="number"
                min={1}
                step={1}
                required
                value={policy.lot_size}
                onChange={(e) =>
                  setPolicy((p) => ({ ...p, lot_size: Number(e.target.value) }))
                }
                className="mt-1 w-48 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
              />
            </div>

            <hr className="border-border/40" />

            {/* min_cash_reserve_pct */}
            <div className="grid gap-1.5">
              <label className="text-sm font-medium" htmlFor="min_cash_reserve_pct">
                可用现金安全垫（%）
              </label>
              <p className="text-xs text-muted-foreground">
                执行后仍保留可用现金的此比例；仅作用于可用现金，不是总资产比例
              </p>
              <div className="flex items-center gap-2">
                <input
                  id="min_cash_reserve_pct"
                  type="number"
                  min={0}
                  max={99}
                  step={1}
                  required
                  value={Math.round(policy.min_cash_reserve_pct * 100)}
                  onChange={(e) =>
                    setPolicy((p) => ({
                      ...p,
                      min_cash_reserve_pct: Number(e.target.value) / 100,
                    }))
                  }
                  className="w-32 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                />
                <span className="text-sm text-muted-foreground">%</span>
              </div>
            </div>

            <hr className="border-border/40" />

            {/* max_single_stock_allocation_pct */}
            <div className="grid gap-1.5">
              <label className="text-sm font-medium" htmlFor="max_single_stock_allocation_pct">
                单股最大仓位占比（%）
              </label>
              <p className="text-xs text-muted-foreground">
                任意单只股票市值不超过总资产的此比例
              </p>
              <div className="flex items-center gap-2">
                <input
                  id="max_single_stock_allocation_pct"
                  type="number"
                  min={1}
                  max={100}
                  step={1}
                  required
                  value={Math.round(policy.max_single_stock_allocation_pct * 100)}
                  onChange={(e) =>
                    setPolicy((p) => ({
                      ...p,
                      max_single_stock_allocation_pct: Number(e.target.value) / 100,
                    }))
                  }
                  className="w-32 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                />
                <span className="text-sm text-muted-foreground">%</span>
              </div>
            </div>

            <hr className="border-border/40" />

            {/* tie_breaker_order */}
            <div className="grid gap-1.5">
              <label className="text-sm font-medium" htmlFor="tie_breaker_order">
                多笔加仓排序规则
              </label>
              <p className="text-xs text-muted-foreground">
                当多笔建议同时加仓时，按此规则决定执行优先顺序
              </p>
              <select
                id="tie_breaker_order"
                value={policy.tie_breaker_order}
                onChange={(e) =>
                  setPolicy((p) => ({
                    ...p,
                    tie_breaker_order: e.target.value as AccountExecutionPolicy["tie_breaker_order"],
                  }))
                }
                className="mt-1 w-52 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
              >
                <option value="code_asc">股票代码升序（code_asc）</option>
                <option value="code_desc">股票代码降序（code_desc）</option>
                <option value="proportional">按建议比例分配（proportional）</option>
              </select>
            </div>

            <hr className="border-border/40" />

            {/* allow_partial_execution */}
            <div className="flex items-start gap-3">
              <input
                id="allow_partial_execution"
                type="checkbox"
                checked={policy.allow_partial_execution}
                onChange={(e) =>
                  setPolicy((p) => ({ ...p, allow_partial_execution: e.target.checked }))
                }
                className="mt-0.5 h-4 w-4 rounded border-border accent-primary cursor-pointer"
              />
              <div>
                <label htmlFor="allow_partial_execution" className="text-sm font-medium cursor-pointer">
                  允许按现金下调执行数量
                </label>
                <p className="text-xs text-muted-foreground mt-0.5">
                  勾选后，当现金不足以完整执行时，按剩余可用现金比例缩减执行数量
                </p>
              </div>
            </div>
          </div>

          {/* Feedback */}
          {saveResult === "ok" && (
            <div className="flex items-center gap-2 rounded-lg bg-emerald-500/10 border border-emerald-500/30 px-4 py-3 text-sm text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <span>策略已保存成功</span>
            </div>
          )}
          {saveResult === "error" && (
            <div className="flex items-center gap-2 rounded-lg bg-red-500/10 border border-red-500/30 px-4 py-3 text-sm text-red-600 dark:text-red-400">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{errorMsg || "保存失败，请重试"}</span>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={saving}
              className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
            >
              <Save className="h-4 w-4" />
              {saving ? "保存中…" : "保存策略"}
            </button>
            <button
              type="button"
              onClick={handleReset}
              disabled={saving}
              className="flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground disabled:opacity-60"
            >
              <RotateCcw className="h-4 w-4" />
              重置默认值
            </button>
          </div>
        </form>
        </>
      )}
    </div>
  );
}
