import { useCallback, useEffect, useState } from "react";
import {
  PieChart,
  Loader2,
  AlertCircle,
  AlertTriangle,
  Camera,
  RefreshCw,
  History,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AttributionPosition,
  AttributionResult,
  AttributionSnapshotSummary,
} from "@/lib/api/types";

const fmtMoney = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const fmtQty = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("zh-CN", { maximumFractionDigits: 4 });

const pnlClass = (v: number | null | undefined) => {
  if (v == null) return "text-muted-foreground";
  if (v > 0) return "text-emerald-500";
  if (v < 0) return "text-red-500";
  return "";
};

const CARD = "rounded-xl border border-border/60 bg-card p-6 shadow-sm";

function SummaryCard({
  label,
  value,
  colored,
}: {
  label: string;
  value: number | null;
  colored?: boolean;
}) {
  return (
    <div className={CARD}>
      <div className="font-mono text-xs uppercase tracking-widest text-muted-foreground">{label}</div>
      <div className={`mt-2 text-2xl font-mono font-semibold ${colored ? pnlClass(value) : ""}`}>
        {fmtMoney(value)}
      </div>
    </div>
  );
}

export default function PerformanceAttribution() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AttributionResult | null>(null);
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [snapshots, setSnapshots] = useState<AttributionSnapshotSummary[]>([]);
  const [snapshotsOpen, setSnapshotsOpen] = useState(false);
  const [freezing, setFreezing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [viewingSnapshotId, setViewingSnapshotId] = useState<string | null>(null);

  const loadSnapshots = useCallback(async () => {
    try {
      const res = await api.listAttributionSnapshots({ limit: 20, offset: 0 });
      setSnapshots(res.items ?? []);
    } catch {
      /* 快照列表失败不阻塞主视图 */
    }
  }, []);

  const fetchAttribution = useCallback(async () => {
    setLoading(true);
    setError(null);
    setViewingSnapshotId(null);
    try {
      const res = await api.getPerformanceAttribution({
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      setResult(res);
    } catch (err: any) {
      setError(err?.message || "加载收益归因失败");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo]);

  useEffect(() => {
    fetchAttribution();
  }, [fetchAttribution]);

  useEffect(() => {
    loadSnapshots();
  }, [loadSnapshots]);

  const handleFreeze = async () => {
    setFreezing(true);
    setNotice(null);
    setError(null);
    try {
      const res = await api.createAttributionSnapshot({
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      setResult(res.attribution);
      setViewingSnapshotId(null);
      setNotice(`已冻结快照（as_of ${res.snapshot?.as_of_date ?? "—"}）`);
      await loadSnapshots();
      setSnapshotsOpen(true);
    } catch (err: any) {
      setError(err?.message || "冻结快照失败");
    } finally {
      setFreezing(false);
    }
  };

  const handleOpenSnapshot = async (snapshotId: string) => {
    setLoading(true);
    setError(null);
    setNotice(null);
    try {
      const detail = await api.getAttributionSnapshot(snapshotId);
      const payload = detail.snapshot?.payload;
      if (payload) {
        setResult({ ...payload, positions: detail.positions ?? payload.positions ?? [] });
      } else {
        setResult(null);
      }
      setViewingSnapshotId(snapshotId);
    } catch (err: any) {
      setError(err?.message || "加载快照详情失败");
    } finally {
      setLoading(false);
    }
  };

  const positions: AttributionPosition[] = result?.positions ?? [];
  const totals = result?.totals ?? null;
  const limitations = result?.data_limitations ?? [];

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-500/10">
            <PieChart className="h-5 w-5 text-blue-500" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">收益归因</h1>
            <p className="text-muted-foreground">基于交易流水的加权平均成本法实现盈亏归因</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="date"
            aria-label="起始日期"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm"
          />
          <input
            type="date"
            aria-label="结束日期"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm"
          />
          <button
            type="button"
            onClick={fetchAttribution}
            disabled={loading}
            className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            计算
          </button>
          <button
            type="button"
            onClick={handleFreeze}
            disabled={freezing}
            className="flex items-center gap-2 rounded-md border border-border px-4 py-2 text-sm hover:bg-accent/50 disabled:opacity-50"
          >
            {freezing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Camera className="h-4 w-4" />}
            冻结快照
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-md bg-red-500/10 p-3 text-red-500">
          <AlertCircle className="h-5 w-5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {notice && (
        <div className="rounded-md bg-emerald-500/10 p-3 text-sm text-emerald-600">{notice}</div>
      )}

      {viewingSnapshotId && (
        <div className="rounded-md border border-border/60 bg-accent/30 p-3 text-sm text-muted-foreground">
          正在查看历史快照 {viewingSnapshotId}
          <button
            type="button"
            onClick={fetchAttribution}
            className="ml-3 underline hover:text-foreground"
          >
            返回实时计算
          </button>
        </div>
      )}

      {limitations.length > 0 && (
        <div className="flex gap-2 rounded-md bg-amber-500/10 p-3 text-sm text-amber-600">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <ul className="space-y-1">
            {limitations.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : !result || positions.length === 0 ? (
        <div className={`${CARD} text-center text-muted-foreground`}>
          暂无交易流水，无法计算归因
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <SummaryCard label="已实现盈亏" value={totals?.total_realized_pnl ?? null} colored />
            <SummaryCard label="未实现盈亏" value={totals?.total_unrealized_pnl ?? null} colored />
            <SummaryCard label="手续费合计" value={totals?.total_fees ?? null} />
            <SummaryCard label="持仓成本合计" value={totals?.total_cost_basis ?? null} />
          </div>

          <div className={CARD}>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-medium">逐股归因</h2>
              <span className="text-xs text-muted-foreground">
                as_of {result.as_of_date} · {totals?.position_count ?? positions.length} 只
              </span>
            </div>
            <div className="overflow-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left">
                    {[
                      "代码",
                      "名称",
                      "已卖数量",
                      "已实现盈亏",
                      "持仓数量",
                      "均价成本",
                      "持仓成本",
                      "手续费",
                      "未实现盈亏",
                    ].map((h) => (
                      <th
                        key={h}
                        className="pb-3 font-mono text-xs uppercase tracking-widest text-muted-foreground"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {positions.map((p) => (
                    <tr key={p.code} className="hover:bg-accent/50">
                      <td className="py-3 font-mono">{p.code}</td>
                      <td className="py-3">
                        <div>{p.name}</div>
                        {p.data_limitations?.length > 0 && (
                          <div className="mt-1 space-y-0.5 text-xs text-amber-600">
                            {p.data_limitations.map((d, i) => (
                              <div key={i}>{d}</div>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="py-3 font-mono">{fmtQty(p.closed_quantity)}</td>
                      <td className={`py-3 font-mono ${pnlClass(p.realized_pnl)}`}>
                        {fmtMoney(p.realized_pnl)}
                      </td>
                      <td className="py-3 font-mono">{fmtQty(p.remaining_quantity)}</td>
                      <td className="py-3 font-mono">{fmtMoney(p.avg_cost)}</td>
                      <td className="py-3 font-mono">{fmtMoney(p.cost_basis)}</td>
                      <td className="py-3 font-mono">{fmtMoney(p.total_fees)}</td>
                      <td className={`py-3 font-mono ${pnlClass(p.unrealized_pnl)}`}>
                        {fmtMoney(p.unrealized_pnl)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      <div className={CARD}>
        <button
          type="button"
          onClick={() => setSnapshotsOpen((v) => !v)}
          aria-expanded={snapshotsOpen}
          className="flex w-full items-center justify-between text-left"
        >
          <span className="flex items-center gap-2 font-medium">
            <History className="h-4 w-4" />
            历史快照
            <span className="text-xs text-muted-foreground">({snapshots.length})</span>
          </span>
          <span className="text-xs text-muted-foreground">{snapshotsOpen ? "收起" : "展开"}</span>
        </button>

        {snapshotsOpen && (
          <div className="mt-4 overflow-auto">
            {snapshots.length === 0 ? (
              <div className="py-4 text-center text-sm text-muted-foreground">暂无快照</div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left">
                    {["快照时间", "AS OF", "已实现盈亏", "持仓数"].map((h) => (
                      <th
                        key={h}
                        className="pb-3 font-mono text-xs uppercase tracking-widest text-muted-foreground"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {snapshots.map((s) => (
                    <tr
                      key={s.snapshot_id}
                      onClick={() => handleOpenSnapshot(s.snapshot_id)}
                      className="cursor-pointer hover:bg-accent/50"
                    >
                      <td className="py-3 font-mono text-xs">{s.created_at}</td>
                      <td className="py-3 font-mono">{s.as_of_date}</td>
                      <td className={`py-3 font-mono ${pnlClass(s.total_realized_pnl)}`}>
                        {fmtMoney(s.total_realized_pnl)}
                      </td>
                      <td className="py-3 font-mono">{s.position_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
