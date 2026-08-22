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
  const [policySnapshot, setPolicySnapshot] = useState<AccountExecutionPolicy>(DEFAULT_POLICY);
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
        if (response.data) {
          setPolicy(response.data);
          setPolicySnapshot(response.data);
        }
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
      const payload: AccountExecutionPolicy = {
        ...policySnapshot,
        lot_size: policy.lot_size,
        min_cash_reserve_pct: policy.min_cash_reserve_pct,
      };
      const saved = await api.updateAccountExecutionPolicy(payload);
      if (!saved.data) throw new Error("保存后的执行策略不可用");
      setPolicy(saved.data);
      setPolicySnapshot(saved.data);
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
    setPolicy((current) => ({
      ...current,
      lot_size: DEFAULT_POLICY.lot_size,
      min_cash_reserve_pct: DEFAULT_POLICY.min_cash_reserve_pct,
    }));
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
                每手股数 <span className="text-xs font-normal text-emerald-600 dark:text-emerald-400">当前生效约束</span>
              </label>
              <p className="text-xs text-muted-foreground">
                A 股标准为 100 股/手，不足一手时不执行买入；当前 runtime 会在现金不足时按此手数下调加仓数量
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
                可用现金安全垫（%） <span className="text-xs font-normal text-emerald-600 dark:text-emerald-400">当前生效约束</span>
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
                单股最大仓位占比（%） <span className="text-xs font-normal text-muted-foreground">当前未生效</span>
              </label>
              <p className="text-xs text-muted-foreground">
                当前仅保存该配置，尚未参与 runtime 仓位约束；不会改变实际建议。<span className="ml-1 font-mono text-[11px]">NOT_IMPLEMENTED</span>
              </p>
              <div className="flex items-center gap-2">
                <input
                  id="max_single_stock_allocation_pct"
                  data-testid="account-execution-policy-max-allocation-readonly"
                  type="number"
                  value={Math.round(policy.max_single_stock_allocation_pct * 100)}
                  readOnly
                  aria-readonly="true"
                  className="w-32 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground"
                />
                <span className="text-sm text-muted-foreground">%</span>
              </div>
            </div>

            <hr className="border-border/40" />

            {/* tie_breaker_order */}
            <div className="grid gap-1.5">
              <label className="text-sm font-medium" htmlFor="tie_breaker_order">
                多笔加仓排序规则 <span className="text-xs font-normal text-muted-foreground">当前未生效</span>
              </label>
              <p className="text-xs text-muted-foreground">
                当前多笔加仓不会按此规则自动分配，配置仅保存供后续使用。<span className="ml-1 font-mono text-[11px]">NOT_IMPLEMENTED</span>
              </p>
              <select
                id="tie_breaker_order"
                data-testid="account-execution-policy-tie-breaker-readonly"
                value={policy.tie_breaker_order}
                disabled
                aria-disabled="true"
                className="mt-1 w-52 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground"
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
                data-testid="account-execution-policy-partial-execution-readonly"
                type="checkbox"
                checked={policy.allow_partial_execution}
                disabled
                aria-disabled="true"
                readOnly
                className="mt-0.5 h-4 w-4 rounded border-border accent-primary"
              />
              <div>
                <label htmlFor="allow_partial_execution" className="text-sm font-medium">
                  允许按现金下调执行数量 <span className="text-xs font-normal text-muted-foreground">当前未生效</span>
                </label>
                <p className="text-xs text-muted-foreground mt-0.5">
                  当前 runtime 尚未读取此开关；配置仅保存，不改变实际执行数量。<span className="ml-1 font-mono text-[11px]">NOT_IMPLEMENTED</span>
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
