import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, CalendarDays, Loader2, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/decisionInbox";
import type {
  ResearchEventCalendar as ResearchEventCalendarData,
  ResearchEventCalendarEvent,
  ResearchEventType,
} from "@/lib/api/types";
import {
  RESEARCH_EVENT_TYPE_LABELS,
  eventNavigationHref,
  filterResearchEvents,
  formatResearchEventDate,
  groupResearchEvents,
  researchEventStateLabel,
  researchEventTypeLabel,
  shouldApplyResearchEventResponse,
  type ResearchEventFilters,
} from "@/lib/researchEventCalendar";

const EVENT_TYPES = Object.keys(RESEARCH_EVENT_TYPE_LABELS) as ResearchEventType[];

const STATUS_LABELS: Record<string, string> = {
  NORMAL: "正常",
  PARTIAL: "部分可用",
  UNAVAILABLE: "不可用",
  ERROR: "读取失败",
  NO_RECORD: "无记录",
  NOT_REQUESTED: "未请求",
};

function statusLabel(value: string): string {
  return STATUS_LABELS[value] ?? value;
}

function limitationLabel(value: string): string {
  const labels: Record<string, string> = {
    NO_EXPLICIT_EVENT_CATALYST_LINK: "未自动绑定研究 Catalyst",
    PROVIDER_FACT_ONLY: "仅展示 provider 解禁事实",
    PROVIDER_DATE_STATUS_ONLY: "仅展示 provider 日期与状态",
    OBSERVED_PUBLICATION_ONLY: "仅展示已观察到的公开公告",
    APPOINTMENT_DATE_IS_NOT_A_COMPANY_GUARANTEE: "预约披露日不是公司保证日期",
    FUTURE_DATE_WITHOUT_PROVIDER_STATUS_NOT_PROMOTED: "缺少 provider 状态，未提升为 upcoming",
    PROVIDER_DATE_UNKNOWN: "provider 未提供可用日期",
  };
  return labels[value] ?? value;
}

function detailEntries(event: ResearchEventCalendarEvent): Array<[string, string]> {
  const displayKeys = [
    "report_date", "appointment_date", "actual_date", "type", "provider_status",
    "ex_dividend_date", "bonus_rmb", "transfer_ratio", "bonus_ratio",
    "shares", "able_shares", "ratio", "notice_at",
  ];
  const labels: Record<string, string> = {
    report_date: "报告期",
    appointment_date: "预约披露日",
    actual_date: "实际披露日",
    type: "类型",
    provider_status: "provider 状态",
    ex_dividend_date: "除权除息日",
    bonus_rmb: "税前派息",
    transfer_ratio: "转增比例",
    bonus_ratio: "送股比例",
    shares: "解禁股数",
    able_shares: "可流通股数",
    ratio: "解禁比例",
    notice_at: "公告时间（provider 原值）",
  };
  return displayKeys
    .filter((key) => event.details[key] !== undefined && event.details[key] !== null && event.details[key] !== "")
    .map((key) => [labels[key] ?? key, String(event.details[key])]);
}

function SourceSummary({ data }: { data: ResearchEventCalendarData }) {
  if (data.sources.length === 0) return null;
  return (
    <div className="grid min-w-0 gap-2 sm:grid-cols-2" data-testid="research-event-sources">
      {data.sources.map((source) => {
        const failed = source.security_statuses.filter((item) => item.status === "ERROR" || item.status === "UNAVAILABLE");
        return (
          <div
            key={source.event_type}
            className={`min-w-0 rounded-md border p-3 text-xs ${
              source.status === "NORMAL"
                ? "border-border/60 bg-background/30"
                : "border-amber-500/30 bg-amber-500/5"
            }`}
            data-testid={`research-event-source-${source.event_type}`}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">{researchEventTypeLabel(source.event_type)}</span>
              <span className="rounded-full bg-background/70 px-2 py-0.5 text-muted-foreground">
                {statusLabel(source.status)}
              </span>
            </div>
            <p className="mt-1 break-words text-muted-foreground">来源：{source.source}</p>
            {source.no_record_count > 0 && (
              <p className="mt-1 text-muted-foreground">{source.no_record_count} 个证券返回 NO_RECORD；这不等同于 provider 失败。</p>
            )}
            {failed.length > 0 && (
              <p className="mt-1 break-words text-amber-700 dark:text-amber-400">
                读取失败：{failed.map((item) => item.security_code).join("、")}（保留其他 source 的成功结果）
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

function EventRow({ event }: { event: ResearchEventCalendarEvent }) {
  const details = detailEntries(event);
  const sourceUrl = typeof event.details.url === "string" ? event.details.url : "";
  return (
    <article
      className="min-w-0 rounded-lg border border-border/60 bg-card p-3 shadow-sm"
      data-testid="research-event-row"
      data-event-id={event.event_id}
      data-event-type={event.event_type}
      data-event-state={event.state}
    >
      <div className="flex min-w-0 flex-wrap items-start gap-x-3 gap-y-1 text-xs">
        <span className="shrink-0 font-mono font-semibold text-foreground">{formatResearchEventDate(event.event_date)}</span>
        <span className="shrink-0 font-mono text-muted-foreground">{event.security_code}</span>
        <span className="rounded bg-primary/10 px-1.5 py-0.5 text-primary">{researchEventTypeLabel(event.event_type)}</span>
        <span className="rounded bg-secondary px-1.5 py-0.5 text-muted-foreground">{researchEventStateLabel(event.state)}</span>
      </div>
      <h4 className="mt-2 break-words text-sm font-medium leading-5">{event.title}</h4>
      {details.length > 0 && (
        <dl className="mt-2 grid min-w-0 gap-x-4 gap-y-1 text-xs text-muted-foreground sm:grid-cols-2">
          {details.map(([label, value]) => (
            <div key={label} className="flex min-w-0 gap-1">
              <dt className="shrink-0">{label}：</dt>
              <dd className="min-w-0 break-words">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="mt-3 flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2 text-xs">
        <Link
          to={eventNavigationHref(event)}
          className="font-medium text-primary hover:underline"
          data-testid="research-event-context-link"
        >
          研究上下文 →
        </Link>
        {sourceUrl && (
          <a
            href={sourceUrl}
            target="_blank"
            rel="noreferrer"
            className="max-w-full break-all text-muted-foreground hover:text-foreground hover:underline"
          >
            查看来源
          </a>
        )}
        <details className="max-w-full">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">来源与限制</summary>
          <div className="mt-2 max-w-full space-y-1 text-[11px] text-muted-foreground">
            <p className="break-words">来源：{event.source}</p>
            {event.date_semantics === "DATE_ONLY" && <p>日期语义：DATE_ONLY（未补造具体时刻）</p>}
            {event.limitations.map((limitation) => (
              <p key={limitation} className="break-words">限制：{limitationLabel(limitation)}</p>
            ))}
          </div>
        </details>
      </div>
    </article>
  );
}

export function ResearchEventCalendar({
  reloadEpoch = 0,
  securityCode,
}: {
  reloadEpoch?: number;
  securityCode?: string;
}) {
  const [data, setData] = useState<ResearchEventCalendarData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [appliedWindow, setAppliedWindow] = useState<{ date_from?: string; date_to?: string }>({});
  const [filters, setFilters] = useState<ResearchEventFilters>({ securityCode: "", eventType: "ALL", state: "ALL" });
  const generationRef = useRef(0);
  const scoped = Boolean(securityCode);

  const load = useCallback((windowParams: { date_from?: string; date_to?: string }) => {
    const generation = ++generationRef.current;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void api.getResearchEventCalendar({ ...windowParams, security_code: securityCode, signal: controller.signal })
      .then((result) => {
        if (!shouldApplyResearchEventResponse(generation, generationRef.current)) return;
        setData(result);
        setDateFrom((current) => current || result.window.date_from);
        setDateTo((current) => current || result.window.date_to);
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (!shouldApplyResearchEventResponse(generation, generationRef.current)) return;
        setError(errorMessage(err));
      })
      .finally(() => {
        if (shouldApplyResearchEventResponse(generation, generationRef.current)) setLoading(false);
      });
    return () => controller.abort();
  }, [securityCode]);

  useEffect(() => {
    const cancel = load(appliedWindow);
    return () => {
      generationRef.current += 1;
      cancel?.();
    };
  }, [appliedWindow, load, reloadEpoch]);

  const filteredEvents = useMemo(
    () => filterResearchEvents(data?.events ?? [], filters),
    [data?.events, filters],
  );
  const groups = useMemo(
    () => groupResearchEvents(filteredEvents, data?.as_of ?? ""),
    [data?.as_of, filteredEvents],
  );
  const securityOptions = data?.universe.securities ?? [];
  const stateOptions = useMemo(
    () => [...new Set((data?.events ?? []).map((event) => event.state))].sort(),
    [data?.events],
  );

  const applyWindow = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setAppliedWindow({ date_from: dateFrom || undefined, date_to: dateTo || undefined });
  };

  return (
    <section
      className="min-w-0 space-y-4 rounded-lg border border-border/60 bg-card/50 p-4"
      data-testid="research-event-calendar"
      data-security-code={securityCode}
    >
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <CalendarDays className="h-4 w-4 shrink-0 text-primary" />
            <h2 className="text-sm font-semibold">事件日历</h2>
            {data && <span className="rounded-full bg-secondary px-2 py-0.5 text-[11px] text-muted-foreground">{statusLabel(data.status)}</span>}
          </div>
          <p className="mt-1 break-words text-xs leading-5 text-muted-foreground">
            {scoped
              ? "展示当前股票的已观察事件与 provider 支持的日期，不是提醒、预测或买卖判断。"
              : "汇总当前 active research Campaign 的已观察事件与 provider 支持的日期，不是提醒、预测或买卖判断。"}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setAppliedWindow({ date_from: dateFrom || undefined, date_to: dateTo || undefined })}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border/60 px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground"
          data-testid="research-event-calendar-refresh"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          刷新事件日历
        </button>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground" aria-busy="true">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          正在读取事件日历…
        </div>
      )}
      {!loading && error && (
        <div className="flex min-w-0 items-start gap-2 rounded-md border border-red-500/30 bg-red-500/5 p-3 text-xs text-red-600" role="alert" data-testid="research-event-calendar-error">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span className="break-words">事件日历读取失败：{error}</span>
        </div>
      )}
      {!loading && !error && data && (
        <>
          {!scoped && data.universe.status === "EMPTY" && (
            <div className="rounded-md border border-dashed border-border/60 bg-background/30 p-4 text-xs text-muted-foreground" data-testid="research-event-empty-universe">
              当前没有 active Campaign，事件日历不会扫描全市场、Watchlist 或真实持仓。
            </div>
          )}
          {!scoped && data.universe.status === "OVER_LIMIT" && (
            <div className="rounded-md border border-red-500/30 bg-red-500/5 p-4 text-xs text-red-700 dark:text-red-400" data-testid="research-event-over-limit">
              当前 active research Campaign 对应证券超过 {data.universe.max_unique_securities} 只，已停止请求，未静默截断。
            </div>
          )}
          {data.status === "UNAVAILABLE" && data.universe.status !== "OVER_LIMIT" && (
            <div className="rounded-md border border-red-500/30 bg-red-500/5 p-4 text-xs text-red-700 dark:text-red-400" data-testid="research-event-unavailable">
              事件日历暂不可用。请区分 provider 读取失败与窗口内没有事件。
            </div>
          )}
          {data.status === "PARTIAL" && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-700 dark:text-amber-400" data-testid="research-event-partial">
              部分来源读取失败；下方仍保留已成功取得的事件。
            </div>
          )}

          <form className="grid min-w-0 gap-2 rounded-md border border-border/50 bg-background/20 p-3 sm:grid-cols-[repeat(2,minmax(0,1fr))_auto]" onSubmit={applyWindow}>
            <label className="grid min-w-0 gap-1 text-[11px] text-muted-foreground">
              起始日期（自然日）
              <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} className="min-w-0 rounded border border-border/60 bg-background px-2 py-1.5 text-xs text-foreground" />
            </label>
            <label className="grid min-w-0 gap-1 text-[11px] text-muted-foreground">
              结束日期（自然日）
              <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} className="min-w-0 rounded border border-border/60 bg-background px-2 py-1.5 text-xs text-foreground" />
            </label>
            <button type="submit" className="self-end rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90">应用范围</button>
          </form>

          <div className={`grid min-w-0 gap-2 ${scoped ? "sm:grid-cols-2" : "sm:grid-cols-3"}`} data-testid="research-event-filters">
            {!scoped && (
              <label className="grid min-w-0 gap-1 text-[11px] text-muted-foreground">
                股票
                <select value={filters.securityCode} onChange={(event) => setFilters((current) => ({ ...current, securityCode: event.target.value }))} className="min-w-0 rounded border border-border/60 bg-background px-2 py-1.5 text-xs text-foreground">
                  <option value="">全部股票</option>
                  {securityOptions.map((security) => <option key={security.security_code} value={security.security_code}>{security.security_code}</option>)}
                </select>
              </label>
            )}
            <label className="grid min-w-0 gap-1 text-[11px] text-muted-foreground">
              事件类型
              <select value={filters.eventType} onChange={(event) => setFilters((current) => ({ ...current, eventType: event.target.value as ResearchEventType | "ALL" }))} className="min-w-0 rounded border border-border/60 bg-background px-2 py-1.5 text-xs text-foreground">
                <option value="ALL">全部类型</option>
                {EVENT_TYPES.map((type) => <option key={type} value={type}>{researchEventTypeLabel(type)}</option>)}
              </select>
            </label>
            <label className="grid min-w-0 gap-1 text-[11px] text-muted-foreground">
              状态
              <select value={filters.state} onChange={(event) => setFilters((current) => ({ ...current, state: event.target.value }))} className="min-w-0 rounded border border-border/60 bg-background px-2 py-1.5 text-xs text-foreground">
                <option value="ALL">全部状态</option>
                {stateOptions.map((state) => <option key={state} value={state}>{researchEventStateLabel(state)}</option>)}
              </select>
            </label>
          </div>

          <SourceSummary data={data} />

          {data.universe.status === "NORMAL" && filteredEvents.length === 0 && (
            <div className="rounded-md border border-dashed border-border/60 bg-background/30 p-4 text-xs text-muted-foreground" data-testid="research-event-no-events">
              {scoped
                ? "当前窗口和筛选条件内没有该股票的事件。NO_RECORD 与 provider failure 仍会在上方来源状态中分别显示。"
                : "有 active Campaign，但当前窗口和筛选条件内没有事件。NO_RECORD 与 provider failure 仍会在上方来源状态中分别显示。"}
            </div>
          )}
          {groups.length > 0 && (
            <div className="min-w-0 space-y-4" data-testid="research-event-groups">
              {groups.map((group) => (
                <div key={group.key} className="min-w-0 space-y-2">
                  <h3 className="text-xs font-semibold text-muted-foreground">{group.label}</h3>
                  <div className="min-w-0 space-y-2">
                    {group.events.map((event) => <EventRow key={event.event_id} event={event} />)}
                  </div>
                </div>
              ))}
            </div>
          )}
          <p className="break-words text-[11px] text-muted-foreground">
            当前窗口：{data.window.date_from} 至 {data.window.date_to}（自然日）· universe：{data.universe.unique_security_count} 只证券 · fetched_at：{data.fetched_at}
          </p>
        </>
      )}
    </section>
  );
}
