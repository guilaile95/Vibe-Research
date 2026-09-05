import { useEffect, useState } from "react";
import { AlertCircle, CalendarClock, Loader2, RefreshCw } from "lucide-react";
import {
  api,
  ApiError,
  type ResearchContinuity,
  type ResearchContinuityChange,
  type ResearchContinuityEvidenceSnapshot,
} from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";

const changeLabel = {
  ADDED: "新增事实",
  CHANGED: "事实变化",
  SOURCE_CONFLICT: "来源冲突",
};

const fieldLabel: Record<string, string> = {
  claim: "事实",
  evidence_type: "证据类型",
  classification: "分类",
  confidence: "置信度",
  stance: "立场",
  source_title: "来源标题",
  source_url: "来源链接",
  source_date: "来源日期",
  accessed_at: "读取时间",
};

function shown(value: string | null | undefined): string {
  return value === null || value === undefined || value === "" ? "未知" : value;
}

function evidenceLine(snapshot: ResearchContinuityEvidenceSnapshot | null | undefined) {
  if (!snapshot) return null;
  return (
    <>
      <p className="mt-1 font-medium">{shown(snapshot.claim_identity)}</p>
      <p className="mt-0.5 text-muted-foreground">来源：{shown(snapshot.source)}</p>
    </>
  );
}

function changeDetails(item: ResearchContinuityChange) {
  if (item.change_type === "ADDED") return evidenceLine(item.after);
  if (item.change_type === "CHANGED") {
    return (
      <>
        <p className="mt-1 font-medium">{shown(item.after?.claim_identity || item.before?.claim_identity)}</p>
        <ul className="mt-1 space-y-0.5 text-muted-foreground">
          {(item.changed_fields || []).map((field) => (
            <li key={field}>
              {fieldLabel[field] || field}：{shown(item.before?.values[field])} → {shown(item.after?.values[field])}
            </li>
          ))}
        </ul>
        <p className="mt-0.5 text-muted-foreground">来源：{shown(item.after?.source || item.before?.source)}</p>
      </>
    );
  }
  return (
    <>
      <p className="mt-1 font-medium">{shown(item.records?.[0]?.claim_identity)}</p>
      <ul className="mt-1 space-y-0.5 text-warning">
        {(item.records || []).map((record) => (
          <li key={record.record_key}>
            {shown(record.source)}：{shown(record.values.stance)} / {shown(record.values.classification)} / {shown(record.values.confidence)}
          </li>
        ))}
      </ul>
    </>
  );
}

function calendarText(value: ResearchContinuity["decision_calendar"]): string {
  if (value.state === "ERROR") return "读取失败：披露日历暂不可用";
  if (value.state === "UNAVAILABLE") return "信息不足：披露日期无法可靠解析";
  if (value.state === "NO_RECORD") return "暂无可核验的定期报告日程";
  if (value.state === "DELAYED_SIGNAL" && value.next?.appointment_date) {
    return `预约日 ${value.next.appointment_date} 已过，尚未见实际披露`;
  }
  if (value.state === "EXPECTED" && value.next?.appointment_date) {
    return `预计披露日 ${value.next.appointment_date}（不是公司保证日期）`;
  }
  return value.latest_actual?.actual_date
    ? `最近实际披露 ${value.latest_actual.actual_date}`
    : "已确认";
}

export function ResearchContinuityCard({
  campaignId,
  prefetched,
  awaitingPrefetch = false,
}: {
  campaignId: string;
  prefetched?: ResearchContinuity | null;
  awaitingPrefetch?: boolean;
}) {
  const [data, setData] = useState<ResearchContinuity | null>(prefetched ?? null);
  const [loading, setLoading] = useState(awaitingPrefetch || prefetched === undefined);
  const [error, setError] = useState(prefetched === null ? "批量读取失败，可单独刷新" : "");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      setData(await api.getResearchContinuity(campaignId));
    } catch (cause) {
      setData(null);
      setError(cause instanceof ApiError ? cause.message : "研究变化读取失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (awaitingPrefetch) {
      setData(null);
      setError("");
      setLoading(true);
      return;
    }
    if (prefetched !== undefined) {
      setData(prefetched);
      setError(prefetched === null ? "批量读取失败，可单独刷新" : "");
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError("");
    setData(null);
    api.getResearchContinuity(campaignId)
      .then((value) => { if (active) setData(value); })
      .catch((cause) => { if (active) setError(cause instanceof ApiError ? cause.message : "研究变化读取失败"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [awaitingPrefetch, campaignId, prefetched]);

  return (
    <GlassCard data-testid="research-continuity" data-campaign-id={campaignId}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">自上次正式检查以来</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            只比较已保存的正式投资逻辑和证据记录，不会修改投资逻辑、决策、投资计划或交易。
          </p>
        </div>
        <button type="button" onClick={() => void load()} disabled={loading} aria-label="刷新研究连续性" className="rounded border border-border/50 p-1.5 text-muted-foreground hover:text-foreground disabled:opacity-50">
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {loading ? (
        <p className="mt-3 flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />读取不可变基线与披露日历…</p>
      ) : error || !data ? (
        <p className="mt-3 flex items-center gap-2 text-xs text-warning" role="alert"><AlertCircle className="h-3.5 w-3.5" />{error || "当前信息不可用"}</p>
      ) : (
        <div className="mt-3 space-y-3 text-xs">
          <div className="rounded border border-border/50 bg-background/35 p-3">
            <p className="font-medium">
              对比基线：{data.baseline.status === "READY" ? "已建立" : "尚未建立"}
            </p>
            {data.changes.status === "NO_BASELINE" ? (
              <p className="mt-1 text-muted-foreground">尚无已确认决策或正式初始投资逻辑，暂时无法比较变化。</p>
            ) : data.changes.status === "NOT_EVALUATED" ? (
              <p className="mt-1 text-muted-foreground">尚未评估：目前只有基线，没有后续记录，不能声称“没有变化”。</p>
            ) : data.changes.status === "UNAVAILABLE" ? (
              <p className="mt-1 text-warning">信息不足：基线或证据链无法完整验证。</p>
            ) : data.changes.items.length === 0 ? (
              <p className="mt-1 text-muted-foreground">已有后续观察，未发现事实字段变化。</p>
            ) : (
              <ul className="mt-2 space-y-1.5">
                {data.changes.items.slice(0, 8).map((item) => (
                  <li
                    key={`${item.change_type}:${item.record_key}`}
                    className="rounded bg-muted/40 px-2 py-1.5"
                    data-testid={`research-change-${item.change_type.toLowerCase()}`}
                  >
                    <span className="font-medium">{changeLabel[item.change_type]}</span>
                    {changeDetails(item)}
                    <p className="mt-1 font-mono text-[10px] text-muted-foreground">Evidence ID：{item.record_key}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded border border-border/50 bg-background/35 p-3" data-calendar-state={data.decision_calendar.state}>
            <p className="flex items-center gap-1.5 font-medium"><CalendarClock className="h-3.5 w-3.5 text-primary" />下一裁决点</p>
            <p className="mt-1">{calendarText(data.decision_calendar)}</p>
            {data.decision_calendar.latest_actual?.actual_date && data.decision_calendar.state !== "CONFIRMED" && (
              <p className="mt-1 text-muted-foreground">最近实际披露：{data.decision_calendar.latest_actual.actual_date}</p>
            )}
            <p className="mt-1 text-[10px] text-muted-foreground">{data.decision_calendar.source} · fetched_at {data.decision_calendar.fetched_at}</p>
          </div>
        </div>
      )}
    </GlassCard>
  );
}
