import { useEffect, useId, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type KlineBar, type TechnicalIndicators } from "@/lib/api";
import type { EvidenceListResult, ResearchEventCalendar } from "@/lib/api/types";
import { normalizeKlineIndicatorOverlay } from "@/lib/klineIndicatorOverlay";
import { klineResearchEvents, positionResearchEvents, type PositionedResearchEvent } from "@/lib/klineResearchEvents";
import { researchEventStateLabel } from "@/lib/researchEventCalendar";
import { KlineChart } from "./KlineChart";

const EVIDENCE_LIMIT = 100;
const DISPLAY_LIMIT = 100;
type Result<T> = { data: T | null; error: string };

function EventEntry({ row }: { row: PositionedResearchEvent }) {
  const { event, placement, barDate } = row;
  return (
    <li className="min-w-0 space-y-1 rounded border border-border/50 p-2 text-xs" data-testid="kline-research-event" data-event-id={event.id} data-kind={event.kind}>
      <p className="break-words font-medium">{event.title}</p>
      <p className="break-words text-muted-foreground">
        {event.kind === "evidence" ? "证据来源日期（非有效时间）" : "事件原日期"}：{event.rawDate || "未知"}
        {event.kind === "calendar" && ` · ${researchEventStateLabel(event.state)}`}
      </p>
      <p className="text-muted-foreground">
        {placement === "EXACT" ? `图上对应 ${barDate}` : placement === "NEXT_AVAILABLE_BAR"
          ? `映射到下一条可用 K 线 ${barDate}；原日期无对应 bar，不据此判断休市或停牌。`
          : placement === "OUTSIDE_WINDOW" ? "超出当前可见 K 线范围，不落点。" : "日期未知或不是受支持的纯日期，不落点，也不以今天或录入时间代替。"}
      </p>
      <p className="break-all text-[10px] text-muted-foreground">{event.kind === "evidence" ? "证据 ID" : "事件 ID"}：{event.id}</p>
      {event.kind === "evidence" ? (
        <Link className="inline-block py-1 text-primary underline" to={`/evidence/${encodeURIComponent(event.id)}`}>查看这条证据 →</Link>
      ) : (
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          <span className="basis-full text-muted-foreground">公开事件观察；同股 Campaign 不等于正式证据绑定。</span>
          {event.campaignIds.map((id) => (
            <Link key={id} className="break-all py-1 text-primary underline" to={`/decision-inbox#campaign-${encodeURIComponent(id)}`}>查看 Campaign {id} →</Link>
          ))}
          {event.campaignIds.length === 0 && <span className="text-muted-foreground">没有关联的 active Campaign。</span>}
        </div>
      )}
    </li>
  );
}

/** A keyed child scopes pending requests and opt-in to one stock/window. */
function ScopedResearchKlineChart({ bars, indicators, code, dates }: {
  bars: KlineBar[]; indicators: TechnicalIndicators | null; code: string; dates: string[];
}) {
  const [enabled, setEnabled] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const [loading, setLoading] = useState(false);
  const [calendar, setCalendar] = useState<Result<ResearchEventCalendar>>({ data: null, error: "" });
  const [evidence, setEvidence] = useState<Result<EvidenceListResult>>({ data: null, error: "" });
  const id = useId().replace(/:/g, "");
  const from = dates[0];
  const to = dates[dates.length - 1];
  useEffect(() => {
    if (!enabled || !from || !to || !/^\d{6}$/.test(code)) return;
    let active = true;
    const controller = new AbortController();
    setLoading(true);
    setCalendar({ data: null, error: "" });
    setEvidence({ data: null, error: "" });
    const calendarRequest = api.getResearchEventCalendar({ security_code: code, date_from: from, date_to: to, signal: controller.signal })
      .then((data) => { if (active) setCalendar({ data, error: "" }); })
      .catch(() => { if (active) setCalendar({ data: null, error: "事件读取失败；保留价格和已返回的证据。" }); });
    const evidenceRequest = api.evidenceList({ subject_type: "stock", subject_id: code, limit: EVIDENCE_LIMIT, offset: 0, signal: controller.signal })
      .then((data) => { if (active) setEvidence({ data, error: "" }); })
      .catch(() => { if (active) setEvidence({ data: null, error: "证据读取失败；保留价格和已返回的事件。" }); });
    void Promise.all([calendarRequest, evidenceRequest]).finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [enabled, epoch, code, from, to]);

  const rows = useMemo(() => positionResearchEvents(klineResearchEvents(code, calendar.data?.events ?? [], evidence.data?.items ?? []), dates), [code, calendar.data, evidence.data, dates]);
  const displayed = rows.slice(0, DISPLAY_LIMIT);
  const groups = new Map<string, PositionedResearchEvent[]>();
  for (const row of displayed) {
    const key = row.barDate ?? "unmapped";
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  const mapped = [...groups.entries()].filter(([date]) => date !== "unmapped");
  const markers = mapped.map(([date, entries], index) => ({ date, label: String(index + 1), href: `#${id}-${date}`, title: `标记 ${index + 1}：${date}，${entries.length} 条研究记录；跳到文字列表` }));
  return (
    <div className="min-w-0 scroll-mt-16 space-y-3 md:scroll-mt-4" data-testid="research-kline-chart" data-security-code={code}>
      <KlineChart bars={bars} indicators={indicators} researchMarkers={enabled ? markers : []} />
      {from && to && /^\d{6}$/.test(code) && (
        <button type="button" className="rounded border border-border px-3 py-2 text-xs hover:bg-muted" aria-expanded={enabled} aria-controls={`${id}-list`} onClick={() => {
          setEnabled(!enabled);
          if (enabled) { setCalendar({ data: null, error: "" }); setEvidence({ data: null, error: "" }); }
        }}>{enabled ? "隐藏研究事件" : "显示研究事件"}</button>
      )}
      {enabled && (
        <section id={`${id}-list`} className="min-w-0 space-y-3" aria-label="K 线研究事件文字列表" data-testid="kline-research-list">
          <div className="space-y-1 rounded bg-muted/40 p-3 text-xs text-muted-foreground">
            <p>只读对照 {from} 至 {to} 的可见日 K 线；编号标记与下面文字列表对应，不代表价格因果或买卖判断。</p>
            <p>事件来自已有日历；证据来自当前股票账本的前 {EVIDENCE_LIMIT} 条，不会自动绑定 Campaign。证据来源日期不等同于已证明的生效时间。</p>
            <p>日期缺少对应 bar 时仅移到窗口内下一条可用 K 线；未知及范围外记录保留文字说明。</p>
          </div>
          {loading && <p role="status" className="text-xs text-muted-foreground">读取研究记录中…</p>}
          {[calendar.error, evidence.error].filter(Boolean).map((error) => <p key={error} role="alert" className="text-xs text-warning">{error}</p>)}
          {calendar.data && calendar.data.status !== "NORMAL" && <p className="text-xs text-warning">日历状态：{calendar.data.status}；部分来源不可用，不表示没有事件。</p>}
          {calendar.data?.limitations.map((limitation) => <p key={limitation} className="break-words text-xs text-muted-foreground">日历限制：{limitation}</p>)}
          {evidence.data && evidence.data.total > evidence.data.items.length && <p className="text-xs text-warning">证据共 {evidence.data.total} 条，本次仅取得 {evidence.data.items.length} 条；其余未读取，图上没有不代表账本不存在。</p>}
          {rows.length > DISPLAY_LIMIT && <p className="text-xs text-warning">已取得 {rows.length} 条可用记录，本视图仅展示前 {DISPLAY_LIMIT} 条，其余 {rows.length - DISPLAY_LIMIT} 条未显示。</p>}
          {mapped.map(([date, entries], index) => (
            <section key={date} id={`${id}-${date}`} tabIndex={-1} className="scroll-mt-16 space-y-2 rounded md:scroll-mt-4 focus:outline focus:outline-2 focus:outline-primary">
              <h4 className="text-xs font-semibold">标记 {index + 1} · {date} · {entries.length} 条</h4>
              <ul className="space-y-2">{entries.map((row) => <EventEntry key={row.event.key} row={row} />)}</ul>
            </section>
          ))}
          {groups.has("unmapped") && <section className="space-y-2"><h4 className="text-xs font-semibold">未在图上落点</h4><ul className="space-y-2">{groups.get("unmapped")!.map((row) => <EventEntry key={row.event.key} row={row} />)}</ul></section>}
          {!loading && (calendar.data || evidence.data) && !rows.length && <p className="text-xs text-muted-foreground">本次成功读取的数据中没有可展示记录；请同时检查读取状态与限制。</p>}
          <button type="button" disabled={loading} className="rounded border border-border px-3 py-2 text-xs disabled:opacity-50" onClick={() => setEpoch((value) => value + 1)}>重新读取研究事件</button>
        </section>
      )}
    </div>
  );
}

export function ResearchKlineChart({ bars, indicators, code }: { bars: KlineBar[]; indicators: TechnicalIndicators | null; code: string }) {
  const dates = useMemo(() => normalizeKlineIndicatorOverlay(bars, null, 60).map((point) => point.date), [bars]);
  return <ScopedResearchKlineChart key={`${code}:${dates.join(",")}`} bars={bars} indicators={indicators} code={code} dates={dates} />;
}
