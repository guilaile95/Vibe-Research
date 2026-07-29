import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import { Plus, ShieldCheck, RefreshCw, Loader2, Trash2, AlertCircle, Sparkles, RotateCw, Pencil } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  api,
  ApiError,
  type PortfolioData,
  type PortfolioAdviceHoldingAdvice,
  type PortfolioAdviceHoldingAction,
  type PortfolioAdviceAccountAction,
  type PortfolioAdviceConfidence,
  type AccountProfileData,
  type AccountFundingData,
  type DataHealthRecordDto,
} from "@/lib/api";
import { loadLlm } from "@/lib/llm";
import { usePortfolioAdviceTaskStore } from "@/stores/portfolioAdviceTaskStore";
import { cn } from "@/lib/utils";
import { gateAdviceLabel, gateAdviceState } from "@/lib/dataHealthView";

/** 持仓页轻量入口：最近 Gate 评估，不替代实时 preflight */
function PortfolioGateHealthEntry() {
  const [gate, setGate] = useState<DataHealthRecordDto | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getDataHealthSource("portfolio_advice_gate")
      .then((d) => {
        if (!cancelled) setGate(d.record);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const state = gateAdviceState(gate);
  const label = gateAdviceLabel(state);

  return (
    <GlassCard className="mb-4 mt-6 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">建议可用性</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            最近 Gate 评估：
            <span className="ml-1 font-medium text-foreground">{failed ? "读取失败" : label}</span>
            {gate?.is_stale && (
              <span className="ml-2 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] text-amber-300">
                评估已陈旧
              </span>
            )}
          </p>
          {gate?.blocks_advice && gate.block_reason && (
            <p className="mt-1 text-[11px] text-amber-200">{gate.block_reason}</p>
          )}
          <p className="mt-1 text-[11px] text-muted-foreground">
            下一次生成仍会重新执行实时 preflight。
          </p>
        </div>
        <Link
          to="/data-health"
          className="text-xs text-primary hover:underline"
        >
          查看数据健康详情
        </Link>
      </div>
    </GlassCard>
  );
}

const REFRESH_MS = 30 * 60 * 1000; // 每半小时自动刷新
const pnlColor = (v: number | null | undefined) => (v == null || Number.isNaN(v) || v === 0 ? "text-muted-foreground" : v > 0 ? "text-danger" : "text-success");
const fmt = (v: number | null | undefined) => (v == null || Number.isNaN(v) ? "—" : v.toLocaleString("zh-CN", { maximumFractionDigits: 2 }));
// 单价类（现价/成本/清仓价）最多 4 位小数：ETF/基金常见 3-4 位，截断成 2 位会与市值/盈亏对不上账
const fmtPx = (v: number | null | undefined) => (v == null || Number.isNaN(v) ? "行情不可用" : v.toLocaleString("zh-CN", { maximumFractionDigits: 4 }));
const fmtShares = (v: number | null | undefined) => (v == null || Number.isNaN(v) ? "—" : Math.round(v).toLocaleString("zh-CN"));
const fmtCny = (v: number | null | undefined) => (v == null || Number.isNaN(v) ? "—" : `¥${v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const fmtPct = (v: number | null | undefined) => {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v > 0 ? "+" : ""}${v}%`;
};
const fmtSigned = (v: number | null | undefined) => {
  if (v == null || Number.isNaN(v)) return "—";
  const s = fmt(v);
  return s === "—" ? "—" : `${v > 0 ? "+" : ""}${s}`;
};

const formatAdviceDuration = (ms: number): string => {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
};

const formatAdviceEta = (date: Date): string =>
  date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });

const HOLDING_ACTION_LABEL: Record<PortfolioAdviceHoldingAction, string> = {
  add: "加仓",
  hold: "持有",
  reduce: "减仓",
  sell: "卖出",
  watch: "观望",
  avoid: "回避继续买入",
};

const ACCOUNT_ACTION_LABEL: Record<PortfolioAdviceAccountAction, string> = {
  hold: "保持当前配置",
  reduce_risk: "降低整体风险",
  selective_add: "选择性加仓",
  defensive: "防御为主",
};

const CONFIDENCE_LABEL: Record<PortfolioAdviceConfidence, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

const MARKET_STATUS_LABEL: Record<string, string> = {
  normal: "数据完整",
  partial: "部分数据缺失",
  unavailable: "核心数据不足",
};

function actionBadgeClass(action: string): string {
  switch (action) {
    case "add":
    case "selective_add":
      return "bg-danger/15 text-danger border-danger/30";
    case "reduce":
    case "sell":
    case "reduce_risk":
    case "defensive":
      return "bg-success/15 text-success border-success/30";
    case "avoid":
      return "bg-amber-500/15 text-amber-600 border-amber-500/30";
    case "watch":
      return "bg-muted/40 text-muted-foreground border-border";
    default:
      return "bg-primary/10 text-primary border-primary/25";
  }
}

function ConditionList({ title, items, emphasize }: { title: string; items: string[]; emphasize?: boolean }) {
  if (!items || items.length === 0) return null;
  return (
    <div className={cn(emphasize && "rounded-md border border-amber-500/25 bg-amber-500/5 p-2")}>
      <p className={cn("mb-1 text-xs font-medium", emphasize ? "text-amber-700 dark:text-amber-400" : "text-muted-foreground")}>
        {title}
      </p>
      <ul className="list-inside list-disc space-y-0.5 text-xs text-foreground/90">
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    </div>
  );
}

function TruncatedNotes({ title, items }: { title: string; items: string[] }) {
  if (!items || items.length === 0) return null;
  const shown = items.slice(0, 8);
  const rest = items.length - shown.length;
  return (
    <div className="rounded-lg border border-border/50 bg-black/10 p-3">
      <p className="mb-1.5 text-xs font-semibold text-muted-foreground">{title}</p>
      <ul className="list-inside list-disc space-y-0.5 text-xs text-foreground/90">
        {shown.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
      {rest > 0 && <p className="mt-1 text-[11px] text-muted-foreground/70">另有 {rest} 条</p>}
    </div>
  );
}

function AccountFundingCard({ funding, corrupted }: { funding?: AccountFundingData | null; corrupted?: boolean }) {
  if (corrupted) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive flex items-center gap-2">
        <AlertCircle className="h-4 w-4 shrink-0" />
        <span>账户资金配置文件读取失败或损坏，未计算账户级仓位指标。</span>
      </div>
    );
  }

  if (!funding || !funding.configured) {
    return (
      <div className="rounded-lg border border-border/50 bg-black/10 p-3 text-xs text-muted-foreground">
        <p className="font-medium text-foreground/80 mb-0.5">账户资金参考</p>
        <p>账户资金尚未配置，本次建议未计算账户级仓位。</p>
      </div>
    );
  }

  const cov = funding.quote_coverage;
  const isComplete = cov?.complete;

  return (
    <div className="rounded-lg border border-border/50 bg-black/10 p-3.5">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs font-semibold text-foreground/90">账户资金参考（只读）</p>
        {funding.updated_at && (
          <span className="text-[11px] text-muted-foreground">更新于 {funding.updated_at}</span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div>
          <p className="text-muted-foreground">账户总资产</p>
          <p className="font-mono font-medium">{funding.total_assets != null ? fmtCny(funding.total_assets) : "—"}</p>
        </div>
        <div>
          <p className="text-muted-foreground">可用现金</p>
          <p className="font-mono font-medium">
            {funding.available_cash != null ? fmtCny(funding.available_cash) : "—"}
            <span className="ml-1 text-muted-foreground/80">({fmtPct(funding.available_cash_pct)})</span>
          </p>
        </div>
        <div>
          <p className="text-muted-foreground">已跟踪持仓市值</p>
          <p className="font-mono font-medium">{funding.tracked_stock_market_value != null ? fmt(funding.tracked_stock_market_value) : "—"}</p>
        </div>
        <div>
          <p className="text-muted-foreground">已跟踪持仓占总资产比例</p>
          <p className="font-mono font-medium">
            {isComplete && funding.tracked_stock_weight_pct != null
              ? `${funding.tracked_stock_weight_pct}%`
              : "部分持仓行情不可用"}
          </p>
        </div>
      </div>
      {cov && !isComplete && (
        <p className="mt-2 text-[11px] text-amber-700 dark:text-amber-400">
          行情覆盖：{cov.valid_holdings} / {cov.total_holdings}（部分持仓行情不可用）
        </p>
      )}
    </div>
  );
}

function HoldingAdviceCard({ h }: { h: PortfolioAdviceHoldingAdvice }) {
  const actionLabel = HOLDING_ACTION_LABEL[h.action] ?? h.action;
  const confLabel = CONFIDENCE_LABEL[h.confidence] ?? h.confidence;
  const showQty = h.action === "reduce" || h.action === "sell";
  const isAdd = h.action === "add";
  const isNoQty = h.action === "hold" || h.action === "watch" || h.action === "avoid";

  return (
    <GlassCard className="p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <span className="text-base font-semibold">{h.name}</span>
          <span className="ml-2 font-mono text-xs text-muted-foreground">{h.code}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn("rounded-md border px-2 py-0.5 text-xs font-semibold", actionBadgeClass(h.action))}>
            {actionLabel}
          </span>
          <span className="text-xs text-muted-foreground">置信度 {confLabel}</span>
        </div>
      </div>

      <div className="mb-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div>
          <p className="text-muted-foreground">持股数量</p>
          <p className="font-mono font-medium">{fmtShares(h.shares)}</p>
        </div>
        <div>
          <p className="text-muted-foreground">成本价</p>
          <p className="font-mono font-medium">{fmtPx(h.cost_price)}</p>
        </div>
        <div>
          <p className="text-muted-foreground">当前价</p>
          <p className="font-mono font-medium">{fmtPx(h.current_price)}</p>
        </div>
        <div>
          <p className="text-muted-foreground">持仓市值</p>
          <p className="font-mono font-medium">{fmt(h.market_value)}</p>
        </div>
        <div>
          <p className="text-muted-foreground">浮动盈亏</p>
          <p className={cn("font-mono font-medium", pnlColor(h.pnl_amount))}>{fmtSigned(h.pnl_amount)}</p>
        </div>
        <div>
          <p className="text-muted-foreground">盈亏比例</p>
          <p className={cn("font-mono font-medium", pnlColor(h.pnl_amount))}>{fmtPct(h.pnl_pct)}</p>
        </div>
        <div>
          <p className="text-muted-foreground">占股票持仓市值</p>
          <p className="font-mono font-medium">
            {h.holding_weight_pct == null ? "—" : `${h.holding_weight_pct}%`}
          </p>
        </div>
        {h.account_metrics?.account_weight_pct != null && (
          <div>
            <p className="text-muted-foreground">占账户总资产比例</p>
            <p className="font-mono font-medium">{h.account_metrics.account_weight_pct}%</p>
          </div>
        )}
        {h.execution_size_pct_of_holding != null && !isAdd && (
          <div>
            <p className="text-muted-foreground">建议操作比例</p>
            <p className="font-mono font-medium">{h.execution_size_pct_of_holding}%</p>
          </div>
        )}
      </div>

      {/* 执行数量 / add 预计金额 */}
      <div className="mb-3 rounded-md border border-border/40 bg-black/10 p-2.5 text-xs">
        {showQty && h.execution_quantity != null && (
          <>
            <p className="font-medium text-foreground">
              建议操作数量：<span className="font-mono text-primary">{fmtShares(h.execution_quantity)}</span> 股
            </p>
            {h.sellable_quantity_advisory != null && (
              <p className="mt-1 font-medium text-foreground">
                理论建议卖出数量（非券商可卖数量）：
                <span className="font-mono text-primary">{fmtShares(h.sellable_quantity_advisory)}</span> 股
              </p>
            )}
            <p className="mt-1 text-amber-700 dark:text-amber-400">执行前请以券商实际可卖数量为准</p>
          </>
        )}
        {showQty && h.execution_quantity == null && (
          <p className="text-muted-foreground">无具体数量操作</p>
        )}
        {isAdd && (
          <>
            {h.execution_size_pct_of_holding != null && (
              <p className="font-medium">
                相对当前持股加仓：
                <span className="font-mono text-primary"> {h.execution_size_pct_of_holding}%</span>
              </p>
            )}
            {h.execution_quantity != null && (
              <p className="mt-1 font-medium text-foreground">
                建议买入数量：
                <span className="font-mono text-primary">{fmtShares(h.execution_quantity)}</span>
                股
              </p>
            )}
            {h.estimated_amount != null && (
              <p className="mt-1 font-medium text-foreground">
                预计所需金额：约{" "}
                <span className="font-mono text-primary">{fmtCny(h.estimated_amount)}</span>
              </p>
            )}
            {(h.execution_quantity != null || h.estimated_amount != null) && (
              <p className="mt-1 text-amber-700 dark:text-amber-400">执行前确认可用资金</p>
            )}
            {h.execution_quantity == null && h.estimated_amount == null && (
              <p className="mt-1 text-muted-foreground">
                暂无具体买入数量与预计金额（见数据限制说明）
              </p>
            )}
          </>
        )}
        {isNoQty && <p className="text-muted-foreground">无具体数量操作</p>}
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <ConditionList title="触发条件" items={h.trigger_conditions} />
        <ConditionList title="价格条件" items={h.price_conditions} />
        <ConditionList title="执行步骤" items={h.execution_plan} />
        <ConditionList title="主要风险" items={h.risk_conditions} />
        <ConditionList title="失效条件" items={h.invalidation_conditions} />
        <ConditionList title="数据限制" items={h.data_limitations} emphasize />
      </div>
    </GlassCard>
  );
}

export function Portfolio() {
  const [data, setData] = useState<PortfolioData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // 账户资金（手工填写）
  const [acct, setAcct] = useState<AccountProfileData | null>(null);
  const [acctConfigured, setAcctConfigured] = useState(false);
  const [acctLoading, setAcctLoading] = useState(false);
  const [acctLoadError, setAcctLoadError] = useState<string | null>(null);
  const [acctOpen, setAcctOpen] = useState(false);
  const [accTotal, setAccTotal] = useState("");
  const [accCash, setAccCash] = useState("");
  const [acctSaving, setAcctSaving] = useState(false);
  const [acctErr, setAcctErr] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [code, setCode] = useState("");
  const [shares, setShares] = useState("");
  const [cost, setCost] = useState("");
  const [adding, setAdding] = useState(false);
  // 清仓录入
  const [cCode, setCCode] = useState("");
  const [cDate, setCDate] = useState("");
  const [cPrice, setCPrice] = useState("");
  const [cShares, setCShares] = useState("");
  const [cCost, setCCost] = useState("");
  const [closing, setClosing] = useState(false);
  // 持仓编辑
  const [editCode, setEditCode] = useState("");
  const [editShares, setEditShares] = useState("");
  const [editCost, setEditCost] = useState("");
  const [editOpen, setEditOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editErr, setEditErr] = useState<string | null>(null);
  // 删除确认（code + 展示用名称/数量）
  const [delConfirm, setDelConfirm] = useState<{ code: string; name: string; shares: number } | null>(null);
  const [delDeleting, setDelDeleting] = useState(false);
  const [delErr, setDelErr] = useState<string | null>(null);

  const [adviceRequest, setAdviceRequest] = useState("");

  const refreshSavedAdvice = useCallback(async () => {
    await usePortfolioAdviceTaskStore.getState().restore();
  }, []);

  const load = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    try {
      setData(manual ? await api.refreshPortfolio() : await api.portfolio());
      setErr(null);
      await refreshSavedAdvice();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "加载失败");
    } finally {
      if (manual) setRefreshing(false);
    }
  }, [refreshSavedAdvice]);

  const loadAcct = useCallback(async () => {
    setAcctLoading(true);
    setAcctLoadError(null);
    try {
      const resp = await api.getAccountProfile();
      // resp 现在是 AccountProfileResponse（{configured, data}），
      // 因为 getAccountProfile 使用 unwrapData=false。
      if (resp.configured && resp.data) {
        setAcctConfigured(true);
        setAcct(resp.data);
      } else {
        setAcctConfigured(false);
        setAcct(null);
      }
      setAcctLoadError(null);
    } catch (e) {
      // GET 失败 ≠ 未配置。不重置现有已配置数据。
      setAcctLoadError(e instanceof ApiError ? e.message : "账户资金加载失败");
      setAcctConfigured(prev => prev);
      setAcct(prev => prev);
    } finally {
      setAcctLoading(false);
    }
  }, []);

  useEffect(() => {
    // 首次加载持仓 + 账户资金；不自动请求 advice
    const boot = async () => {
      try {
        setData(await api.portfolio());
        setErr(null);
        await refreshSavedAdvice();
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : "加载失败");
      }
      await loadAcct();
    };
    boot();
    const t = setInterval(() => load(), REFRESH_MS); // 每半小时自动刷新
    return () => clearInterval(t);
  }, [load, loadAcct, refreshSavedAdvice]);

  // 数量校验：空值 / 含非数字字符（除负号和小数点）/ 非整数 / <=0 / NaN·Infinity → 拒绝
  const validateShares = (raw: string): number | null => {
    const v = raw.trim();
    if (!v) return null;
    if (!/^-?\d+(\.\d+)?$/.test(v)) return null;
    const n = parseFloat(v);
    if (!Number.isFinite(n) || !Number.isInteger(n) || n <= 0) return null;
    return n;
  };

  const add = async () => {
    if (adding) return;
    if (!/^\d{6}$/.test(code.trim())) { setErr("请输入 6 位股票代码"); return; }
    const s = validateShares(shares);
    const c = parseFloat(cost);
    if (s === null) { setErr("数量必须为正整数"); return; }
    if (!Number.isFinite(c)) { setErr("成本价请填数字（可为负）"); return; }
    setAdding(true); setErr(null);
    try {
      setData(await api.addHolding(code.trim(), s, c));
      setCode(""); setShares(""); setCost("");
      await refreshSavedAdvice();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "添加失败");
    } finally {
      setAdding(false);
    }
  };

  // 打开编辑窗口
  const openEdit = (code: string, shares: number, cost: number) => {
    setEditCode(code);
    setEditShares(String(shares));
    setEditCost(String(cost));
    setEditErr(null);
    setEditOpen(true);
  };

  const closeEdit = () => {
    setEditOpen(false);
    setEditErr(null);
  };

  // 保存编辑
  const saveEdit = async () => {
    if (editing) return;
    const s = validateShares(editShares);
    const c = parseFloat(editCost);
    if (s === null) { setEditErr("数量必须为正整数"); return; }
    if (!Number.isFinite(c)) { setEditErr("成本价请填数字（可为负）"); return; }
    setEditing(true);
    setEditErr(null);
    try {
      setData(await api.updateHolding(editCode, s, c));
      await refreshSavedAdvice();
      setEditOpen(false);
    } catch (e) {
      setEditErr(e instanceof ApiError ? e.message : "保存失败，请重试");
    } finally {
      setEditing(false);
    }
  };

  // 确认删除（仅一次 DELETE；失败不移除页面记录）
  const confirmRemove = async () => {
    if (!delConfirm || delDeleting) return;
    const c = delConfirm.code;
    setDelDeleting(true);
    setDelErr(null);
    try {
      setData(await api.removeHolding(c));
      await refreshSavedAdvice();
      setDelConfirm(null);
    } catch (e) {
      setDelErr(e instanceof ApiError ? e.message : "删除失败，请重试");
    } finally {
      setDelDeleting(false);
    }
  };

  // 账户资金：打开填写窗口
  const openAcct = () => {
    setAccTotal(acct ? fmtCny(acct.total_assets).replace(/[¥,]/g, "") : "");
    setAccCash(acct ? fmtCny(acct.available_cash).replace(/[¥,]/g, "") : "");
    setAcctErr(null);
    setAcctOpen(true);
  };

  const closeAcct = () => {
    setAcctOpen(false);
    setAcctErr(null);
  };

  // 账户资金：保存
  const saveAcct = async () => {
    if (acctSaving) return;
    const total = parseFloat(accTotal);
    const cash = parseFloat(accCash);
    if (!(total > 0)) { setAcctErr("账户总资产必须大于 0"); return; }
    if (!(cash >= 0)) { setAcctErr("可用现金不能小于 0"); return; }
    if (cash > total) { setAcctErr("可用现金不能大于账户总资产"); return; }
    setAcctSaving(true);
    setAcctErr(null);
    try {
      const resp = await api.saveAccountProfile({ total_assets: total, available_cash: cash });
      // resp 现在是 AccountProfileResponse（由于使用了 unwrapData=false）。
      if (resp.configured && resp.data) {
        setAcctConfigured(true);
        setAcct(resp.data);
        setAcctOpen(false);
      } else {
        // 服务端返回非法结构：不关闭弹窗、保留输入、显示错误
        setAcctErr("服务端返回数据异常，请重试");
      }
    } catch (e) {
      // 保存失败保留输入内容，仅显示错误
      setAcctErr(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setAcctSaving(false);
    }
  };

  const addClose = async () => {
    if (!/^\d{6}$/.test(cCode.trim())) { setErr("清仓记录：请输入 6 位代码"); return; }
    const p = parseFloat(cPrice), s = validateShares(cShares), c = parseFloat(cCost);
    if (!cDate) { setErr("请选清仓日期"); return; }
    if (!(p > 0) || !Number.isFinite(p)) { setErr("清仓价必须大于 0"); return; }
    if (s === null) { setErr("股数必须为正整数"); return; }
    if (!Number.isFinite(c)) { setErr("成本请填数字（可为负）"); return; }
    setClosing(true); setErr(null);
    try {
      setData(await api.closePosition(cCode.trim(), cDate, p, s, c));
      setCCode(""); setCDate(""); setCPrice(""); setCShares(""); setCCost("");
      await refreshSavedAdvice();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "添加清仓记录失败");
    } finally {
      setClosing(false);
    }
  };

  const removeClosed = async (i: number) => {
    try {
      setData(await api.removeClosed(i));
      await refreshSavedAdvice();
    } catch { /* ignore */ }
  };

  const adviceStatus = usePortfolioAdviceTaskStore((s) => s.status);
  const advice = usePortfolioAdviceTaskStore((s) => s.result);
  const adviceMeta = usePortfolioAdviceTaskStore((s) => s.resultMeta);
  const adviceError = usePortfolioAdviceTaskStore((s) => s.error);
  const adviceRestoreError = usePortfolioAdviceTaskStore((s) => s.restoreError);
  const adviceStartedAt = usePortfolioAdviceTaskStore((s) => s.startedAt);
  const adviceEstimatedDurationMs = usePortfolioAdviceTaskStore((s) => s.estimatedDurationMs);
  const adviceLoading = adviceStatus === "running";
  const [adviceNow, setAdviceNow] = useState(Date.now());

  useEffect(() => {
    if (!adviceLoading) return;
    setAdviceNow(Date.now());
    const id = setInterval(() => setAdviceNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [adviceLoading]);

  const adviceElapsedMs = adviceLoading && adviceStartedAt !== null
    ? adviceNow - adviceStartedAt
    : 0;
  const adviceRemainingMs = adviceLoading
    ? Math.max(0, adviceEstimatedDurationMs - adviceElapsedMs)
    : 0;
  const adviceOverTimeMs = adviceLoading
    ? Math.max(0, adviceElapsedMs - adviceEstimatedDurationMs)
    : 0;
  const adviceEta = adviceLoading && adviceStartedAt !== null
    ? new Date(adviceStartedAt + adviceEstimatedDurationMs)
    : null;

  const generateAdvice = async () => {
    if (adviceLoading) return;
    const llm = loadLlm();
    if (!llm) {
      setErr('请先在“接入 AI”中配置模型');
      return;
    }
    setErr(null);
    await usePortfolioAdviceTaskStore.getState().start(llm, adviceRequest);
  };

  const cancelAdvice = () => {
    usePortfolioAdviceTaskStore.getState().cancel();
  };

  const holdings = data?.holdings || [];
  const totals = data?.totals;
  const closed = data?.closed || [];
  const summary = advice?.portfolio_summary;
  const account = advice?.account_action;

  return (
    <div>
      <PageHeader
        title="我的持仓"
        subtitle="自己录、存在本地，实时看浮动盈亏"
        actions={
          <div className="flex items-center gap-2">
            <button onClick={() => load(true)} disabled={refreshing}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">
              {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              刷新
            </button>
          </div>
        }
      />

      <div className="mb-4 flex items-start gap-2 rounded-lg border border-success/25 bg-success/5 p-3 text-xs text-muted-foreground">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" />
        <span>持仓<b className="text-foreground">只存在你本地</b>，不上传、不进仓库。行情每半小时自动刷新，也可手动刷新。结构化操作建议由本地配置的 AI 生成，数量与盈亏以代码校验结果为准。</span>
      </div>

      {/* 汇总 */}
      {totals && holdings.length > 0 && (
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { k: "总市值", v: fmt(totals.market_value), c: "text-foreground" },
            { k: "总成本", v: fmt(totals.cost), c: "text-foreground" },
            { k: "浮动盈亏", v: fmtSigned(totals.pnl), c: pnlColor(totals.pnl) },
            { k: "盈亏比例", v: fmtPct(totals.pnl_pct), c: pnlColor(totals.pnl) },
          ].map((m) => (
            <GlassCard key={m.k} className="p-3">
              <p className="text-xs text-muted-foreground">{m.k}</p>
              <p className={cn("mt-1 font-mono text-lg font-bold", m.c)}>{m.v}</p>
            </GlassCard>
          ))}
        </div>
      )}

      {/* 账户资金 */}
      <GlassCard className="mb-4">
        <h3 className="mb-3 text-sm font-semibold">账户资金</h3>
        {acctLoading ? (
          <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            加载中…
          </div>
        ) : acctLoadError ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {acctLoadError}
            </div>
            <button onClick={loadAcct} disabled={acctLoading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground">
              <RotateCw className={cn("h-4 w-4", acctLoading && "animate-spin")} />
              重试
            </button>
          </div>
        ) : acctConfigured && acct ? (
          <div className="flex flex-wrap items-end gap-4">
            <div>
              <p className="mb-1 text-xs text-muted-foreground">账户总资产</p>
              <p className="font-mono text-lg font-bold text-foreground">{fmtCny(acct.total_assets)}</p>
            </div>
            <div>
              <p className="mb-1 text-xs text-muted-foreground">可用现金</p>
              <p className="font-mono text-lg font-bold text-foreground">{fmtCny(acct.available_cash)}</p>
            </div>
            <div className="ml-auto flex flex-col items-end gap-1">
              <span className="text-[11px] text-muted-foreground/60">更新于 {acct.updated_at}</span>
              <button onClick={openAcct}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/25">
                编辑
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground">尚未配置账户资金</p>
            <button onClick={openAcct}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/25">
              填写账户资金
            </button>
          </div>
        )}
        <p className="mt-2 text-[11px] text-muted-foreground/60">手工填写、存在本地，不上传、不进仓库。用于后续持仓建议参考（本轮仅维护展示）。</p>
      </GlassCard>

      {/* 账户资金填写窗口 */}
      {acctOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={closeAcct}>
          <div className="w-full max-w-md rounded-xl border border-border bg-background p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="mb-4 text-base font-semibold">{acctConfigured ? "编辑账户资金" : "填写账户资金"}</h3>
            <div className="mb-3">
              <label className="mb-1 block text-xs text-muted-foreground">账户总资产</label>
              <input
                value={accTotal}
                onChange={(e) => setAccTotal(e.target.value.replace(/[^\d.]/g, ""))}
                placeholder="如 100000"
                className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
              />
            </div>
            <div className="mb-3">
              <label className="mb-1 block text-xs text-muted-foreground">可用现金</label>
              <input
                value={accCash}
                onChange={(e) => setAccCash(e.target.value.replace(/[^\d.]/g, ""))}
                placeholder="如 20000"
                className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
              />
            </div>
            {acctErr && (
              <div className="mb-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-2.5 text-sm text-destructive">
                <AlertCircle className="h-4 w-4 shrink-0" /> {acctErr}
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button onClick={closeAcct} disabled={acctSaving}
                className="rounded-lg border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">
                取消
              </button>
              <button onClick={saveAcct} disabled={acctSaving}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50">
                {acctSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : null} 保存
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 持仓编辑窗口 */}
      {editOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={closeEdit}>
          <div className="w-full max-w-md rounded-xl border border-border bg-background p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="mb-4 text-base font-semibold">编辑持仓</h3>
            <div className="mb-3">
              <label className="mb-1 block text-xs text-muted-foreground">股票代码</label>
              <input value={editCode} readOnly
                className="w-full rounded-lg border border-border bg-black/10 px-3 py-2 text-sm text-muted-foreground outline-none"
              />
            </div>
            <div className="mb-3">
              <label className="mb-1 block text-xs text-muted-foreground">持仓数量（股）</label>
              <input value={editShares} onChange={(e) => setEditShares(e.target.value)} placeholder="如 100"
                className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
              />
            </div>
            <div className="mb-3">
              <label className="mb-1 block text-xs text-muted-foreground">成本价</label>
              <input value={editCost} onChange={(e) => setEditCost(e.target.value)} placeholder="如 12.5，可负"
                className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
              />
            </div>
            {editErr && (
              <div className="mb-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-2.5 text-sm text-destructive">
                <AlertCircle className="h-4 w-4 shrink-0" /> {editErr}
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button onClick={closeEdit} disabled={editing}
                className="rounded-lg border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">
                取消
              </button>
              <button onClick={saveEdit} disabled={editing}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50">
                {editing ? <Loader2 className="h-4 w-4 animate-spin" /> : null} 保存
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 删除确认窗口 */}
      {delConfirm !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => { if (!delDeleting) { setDelConfirm(null); setDelErr(null); } }}>
          <div className="w-full max-w-sm rounded-xl border border-border bg-background p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="mb-3 text-base font-semibold">确认删除持仓</h3>
            <p className="mb-2 text-sm text-muted-foreground">
              确认删除{" "}
              <span className="font-medium text-foreground">{delConfirm.name}</span>{" "}
              <span className="font-mono text-foreground">{delConfirm.code}</span>
              ？当前持仓数量：
              <span className="font-mono text-foreground">{delConfirm.shares}</span> 股。
            </p>
            <p className="mb-3 text-xs text-muted-foreground/80">
              删除只移除当前持仓记录，不会写入清仓记录，也不影响账户资金。
            </p>
            {delErr && (
              <div className="mb-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-2.5 text-sm text-destructive">
                <AlertCircle className="h-4 w-4 shrink-0" /> {delErr}
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button onClick={() => { setDelConfirm(null); setDelErr(null); }} disabled={delDeleting}
                className="rounded-lg border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">
                取消
              </button>
              <button onClick={confirmRemove} disabled={delDeleting}
                className="inline-flex items-center gap-1.5 rounded-lg bg-danger/15 px-4 py-2 text-sm font-medium text-danger hover:bg-danger/25 disabled:opacity-50">
                {delDeleting ? <Loader2 className="h-4 w-4 animate-spin" /> : null} 确认删除
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 录入 */}
      <GlassCard className="mb-4">
        <h3 className="mb-3 text-sm font-semibold">添加持仓</h3>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">股票代码</label>
            <input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="6 位代码"
              className="w-28 rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50" />
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">数量（股）</label>
            <input value={shares} onChange={(e) => setShares(e.target.value)} placeholder="如 100"
              className="w-28 rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50" />
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">成本价</label>
            <input value={cost} onChange={(e) => setCost(e.target.value)} placeholder="如 12.5，可负"
              className="w-28 rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50" />
          </div>
          <button onClick={add} disabled={adding}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50">
            {adding ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} 添加
          </button>
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground/60">同一代码再次添加会按加权平均成本合并（加仓）。</p>
      </GlassCard>

      {err && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" /> {err}
        </div>
      )}

      {/* 持仓表 */}
      <GlassCard glow>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="font-semibold">持仓明细</h3>
          {data?.updated && <span className="text-xs text-muted-foreground/60">更新于 {data.updated}</span>}
        </div>
        {holdings.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground/60">还没有持仓记录，用上面的表单添加一笔。</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  {["名称", "现价", "数量", "成本", "市值", "浮动盈亏", "盈亏%", ""].map((h) => (
                    <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {holdings.map((h) => (
                  <tr key={h.code} className="border-b border-border/30">
                    <td className="px-2 py-2.5">
                      <span className="font-medium">{h.name}</span>
                      <span className="ml-1.5 font-mono text-xs text-muted-foreground/60">{h.code}</span>
                    </td>
                    <td className="px-2 py-2.5 font-mono">{fmtPx(h.price)}</td>
                    <td className="px-2 py-2.5 font-mono text-muted-foreground">{fmt(h.shares)}</td>
                    <td className="px-2 py-2.5 font-mono text-muted-foreground">{fmtPx(h.cost)}</td>
                    <td className="px-2 py-2.5 font-mono">{fmt(h.market_value)}</td>
                    <td className={cn("px-2 py-2.5 font-mono", pnlColor(h.pnl))}>{fmtSigned(h.pnl)}</td>
                    <td className={cn("px-2 py-2.5 font-mono", pnlColor(h.pnl))}>{fmtPct(h.pnl_pct)}</td>
                    <td className="px-2 py-2.5">
                      <div className="flex items-center gap-1.5">
                        <button onClick={() => openEdit(h.code, h.shares, h.cost)} className="text-muted-foreground/50 hover:text-primary" title="编辑">
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => {
                            setDelConfirm({ code: h.code, name: h.name, shares: h.shares });
                            setDelErr(null);
                          }}
                          className="text-muted-foreground/50 hover:text-destructive"
                          title="删除"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      {/* 建议可用性（数据健康轻量入口，不替代实时 gate） */}
      <PortfolioGateHealthEntry />

      {/* 持仓操作建议（结构化 API） */}
      <GlassCard className="mb-4 mt-6">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">持仓操作建议</h3>
          <span className="text-[11px] text-muted-foreground/70">独立分析，不写入持仓</span>
        </div>
        <label className="mb-1 block text-xs text-muted-foreground">补充要求（可选）</label>
        <textarea
          value={adviceRequest}
          onChange={(e) => setAdviceRequest(e.target.value)}
          rows={2}
          placeholder="例如：重点判断是否需要减仓，持有周期以短线为主"
          disabled={adviceLoading}
          className="mb-3 w-full resize-y rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50 disabled:opacity-50"
        />
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={generateAdvice}
            disabled={adviceLoading}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50"
          >
            {adviceLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {adviceLoading
              ? "持仓建议分析中…"
              : advice
                ? "重新生成持仓建议"
                : "生成持仓操作建议"}
          </button>
          {adviceLoading && (
            <button
              type="button"
              onClick={cancelAdvice}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:text-foreground"
            >
              取消
            </button>
          )}
        </div>

        {adviceStatus === "restoring" && (
          <div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> 正在恢复已保存的持仓建议…
          </div>
        )}

        {adviceStatus === "empty" && (
          <p className="mt-3 text-sm text-muted-foreground">暂无已保存建议，不会自动调用模型。</p>
        )}

        {adviceRestoreError && (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>恢复失败：{adviceRestoreError}</span>
          </div>
        )}

        {adviceLoading && (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm text-primary">
            <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" />
            <div>
              <p className="font-medium">
                {advice ? "正在重新生成，旧建议会保留到新结果成功。" : "持仓建议分析中，切换页面后会继续运行。"}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                已用 {formatAdviceDuration(adviceElapsedMs)}
                {adviceEta
                  ? adviceOverTimeMs > 0
                    ? ` · 已超过预计时间 ${formatAdviceDuration(adviceOverTimeMs)}，仍在生成`
                    : ` · 预计 ${formatAdviceEta(adviceEta)} 完成 · 剩余 ${formatAdviceDuration(adviceRemainingMs)}`
                  : null}
              </p>
            </div>
          </div>
        )}

        {adviceError && (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{advice ? `重新生成失败，继续显示旧建议：${adviceError}` : adviceError}</span>
          </div>
        )}

        {adviceMeta?.stale && (
          <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-200">
            {adviceMeta.stale_message || "持仓已发生变化，该建议基于生成时的持仓，可能已经过期。"}
          </div>
        )}

        {advice && summary && account && (
          <div className="mt-4 space-y-4">
            {advice.generated_at && (
              <div className="flex items-center justify-between border-b border-border/40 pb-2">
                <span className="text-xs font-medium text-muted-foreground">持仓决策依据追溯</span>
                <Link
                  to={`/decision-evidence?trade_date=${encodeURIComponent(advice.trade_date || "")}&generated_at=${encodeURIComponent(advice.generated_at)}`}
                  className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline font-medium"
                >
                  <ShieldCheck className="h-4 w-4" />
                  查看决策依据
                </Link>
              </div>
            )}
            {/* 总体摘要 */}
            <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3 lg:grid-cols-6">
              <div className="rounded-md border border-border/40 p-2">
                <p className="text-muted-foreground">生成时间</p>
                <p className="font-medium">{advice.generated_at || "—"}</p>
              </div>
              {adviceMeta && (
                <div className="rounded-md border border-border/40 p-2">
                  <p className="text-muted-foreground">生成模型</p>
                  <p className="truncate font-medium">{adviceMeta.model_provider} / {adviceMeta.model_name}</p>
                </div>
              )}
              {advice.trade_date ? (
                <div className="rounded-md border border-border/40 p-2">
                  <p className="text-muted-foreground">交易日期</p>
                  <p className="font-medium">{advice.trade_date}</p>
                </div>
              ) : null}
              <div className="rounded-md border border-border/40 p-2">
                <p className="text-muted-foreground">市场数据状态</p>
                <p className="font-medium">
                  {MARKET_STATUS_LABEL[advice.market_status] ?? (advice.market_status || "—")}
                </p>
              </div>
              <div className="rounded-md border border-border/40 p-2">
                <p className="text-muted-foreground">持仓数量</p>
                <p className="font-mono font-medium">{summary.holding_count}</p>
              </div>
              <div className="rounded-md border border-border/40 p-2">
                <p className="text-muted-foreground">持仓市值</p>
                <p className="font-mono font-medium">{fmt(summary.market_value)}</p>
              </div>
              <div className="rounded-md border border-border/40 p-2">
                <p className="text-muted-foreground">持仓成本</p>
                <p className="font-mono font-medium">{fmt(summary.cost)}</p>
              </div>
              <div className="rounded-md border border-border/40 p-2">
                <p className="text-muted-foreground">浮动盈亏</p>
                <p className={cn("font-mono font-medium", pnlColor(summary.pnl))}>
                  {fmtSigned(summary.pnl)}
                  <span className="ml-1 text-muted-foreground">({fmtPct(summary.pnl_pct)})</span>
                </p>
              </div>
            </div>

            {/* 账户资金参考 */}
            <AccountFundingCard
              funding={advice.account_funding}
              corrupted={advice.data_limitations?.some((l) => l.includes("读取失败或损坏"))}
            />

            {/* 账户级建议 */}
            <div className="rounded-lg border border-primary/20 bg-primary/5 p-3">
              <p className="mb-1 text-xs font-semibold text-muted-foreground">账户整体建议</p>
              <div className="flex flex-wrap items-center gap-2">
                <span className={cn("rounded-md border px-2 py-0.5 text-sm font-semibold", actionBadgeClass(account.action))}>
                  {ACCOUNT_ACTION_LABEL[account.action] ?? account.action}
                </span>
                <span className="text-xs text-muted-foreground">
                  置信度 {CONFIDENCE_LABEL[account.confidence] ?? account.confidence}
                </span>
              </div>
              {account.reason && (
                <p className="mt-2 text-sm text-foreground/90">{account.reason}</p>
              )}
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <TruncatedNotes title="分析提示" items={advice.warnings || []} />
              <TruncatedNotes title="数据限制" items={advice.data_limitations || []} />
            </div>

            {/* 逐股建议 */}
            <div className="space-y-3">
              <p className="text-xs font-semibold text-muted-foreground">逐股操作建议</p>
              {(advice.holdings || []).map((h) => (
                <HoldingAdviceCard key={h.code} h={h} />
              ))}
              {(!advice.holdings || advice.holdings.length === 0) && (
                <p className="text-sm text-muted-foreground">暂无逐股建议</p>
              )}
            </div>
          </div>
        )}
      </GlassCard>

      {/* 清仓录入 */}
      <GlassCard className="mb-4 mt-6">
        <h3 className="mb-3 text-sm font-semibold">添加清仓记录</h3>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">股票代码</label>
            <input value={cCode} onChange={(e) => setCCode(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="6 位代码"
              className="w-24 rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50" />
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">清仓日期</label>
            <input type="date" value={cDate} onChange={(e) => setCDate(e.target.value)}
              className="rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50" />
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">清仓价</label>
            <input value={cPrice} onChange={(e) => setCPrice(e.target.value.replace(/[^\d.]/g, ""))} placeholder="卖出价"
              className="w-24 rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50" />
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">股数</label>
            <input value={cShares} onChange={(e) => setCShares(e.target.value.replace(/\D/g, ""))} placeholder="如 100"
              className="w-24 rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50" />
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">买入成本</label>
            <input value={cCost} onChange={(e) => setCCost(e.target.value.replace(/[^\d.-]/g, "").replace(/(?!^)-/g, ""))} placeholder="成本价，可负"
              className="w-24 rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50" />
          </div>
          <button onClick={addClose} disabled={closing}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50">
            {closing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} 记录
          </button>
        </div>
      </GlassCard>

      {/* 已清仓列表 */}
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground">已清仓</h3>
        {closed.length > 0 && data && (
          <span className="text-sm">
            已实现盈亏合计 <b className={cn("font-mono", pnlColor(data.realized_pnl))}>{fmtSigned(data.realized_pnl)}</b>
          </span>
        )}
      </div>
      <GlassCard>
        {closed.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground/60">还没有清仓记录。卖出后在上面记一笔，作为已实现盈亏的历史。</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  {["名称", "清仓日期", "清仓价", "股数", "成本", "已实现盈亏", "盈亏%", ""].map((h) => (
                    <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {closed.map((c, i) => (
                  <tr key={i} className="border-b border-border/30">
                    <td className="px-2 py-2.5">
                      <span className="font-medium">{c.name}</span>
                      <span className="ml-1.5 font-mono text-xs text-muted-foreground/60">{c.code}</span>
                    </td>
                    <td className="px-2 py-2.5 font-mono text-muted-foreground">{c.date}</td>
                    <td className="px-2 py-2.5 font-mono">{fmtPx(c.price)}</td>
                    <td className="px-2 py-2.5 font-mono text-muted-foreground">{fmt(c.shares)}</td>
                    <td className="px-2 py-2.5 font-mono text-muted-foreground">{fmtPx(c.cost)}</td>
                    <td className={cn("px-2 py-2.5 font-mono", pnlColor(c.pnl))}>{fmtSigned(c.pnl)}</td>
                    <td className={cn("px-2 py-2.5 font-mono", pnlColor(c.pnl))}>{fmtPct(c.pnl_pct)}</td>
                    <td className="px-2 py-2.5">
                      <button onClick={() => removeClosed(i)} className="text-muted-foreground/50 hover:text-destructive" title="删除">
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </div>
  );
}
