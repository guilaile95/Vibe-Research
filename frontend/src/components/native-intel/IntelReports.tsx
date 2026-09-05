import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { EChart } from "@/components/ui/EChart";
import { formatShanghaiTime } from "@/lib/intelDigestView";
import { reportApi, type IntelReport, type IntelReportItem, type IntelAnalysis, type IntelTimeline,
  type IntelSimilar, type ReportMode, type TimelineBehavior } from "@/lib/nativeIntelReports";

const box = "rounded-xl border border-border bg-card p-4 space-y-3";
const control = "rounded-lg border border-border bg-background px-3 py-2 text-sm";
const modes: Record<ReportMode, string> = { CURRENT: "当前", DAILY: "今日", INCREMENTAL: "增量" };
const message = (e: unknown) => e instanceof Error ? e.message : "读取失败";
const pct = (n: number | null) => n == null ? "无可比基线" : `${n > 0 ? "+" : ""}${n}%`;

function NewsRows({ items, onSimilar }: { items: IntelReportItem[]; onSimilar?: (id: number) => void }) {
  return <ul className="divide-y divide-border">{items.map(item => <li key={`${item.source_id}-${item.item_id}`} className="py-3 space-y-1">
    <div className="flex flex-wrap items-baseline gap-2">
      {item.rank != null && <span className={item.highlight ? "font-semibold text-primary" : "text-muted-foreground"}>#{item.rank}</span>}
      <a href={/^https?:\/\//i.test(item.url) ? item.url : undefined} target="_blank" rel="noreferrer" className="hover:underline">{item.title}</a>
      {item.new_kind && <span className="rounded border border-primary/40 px-1.5 text-xs text-primary" data-testid={`badge-${item.new_kind}`}>
        {item.new_kind === "NEW_ON_LIST" ? "新见榜 / 再上榜" : "首次本地采集"} · {item.new_kind}</span>}
      {item.change_kind === "CHANGED" && <span className="text-xs text-primary">内容或位次变化</span>}
    </div>
    <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
      <span>{item.source_name} · {item.source_type === "rss" ? "RSS · 无排名" : "热榜"}</span>
      <span>观测 {formatShanghaiTime(item.observed_at)}</span>
      <span>发布 {item.published_at ? formatShanghaiTime(item.published_at) : "时间未知"}</span>
      {onSimilar && <button className="text-primary" onClick={() => onSimilar(item.item_id)}>相似资讯</button>}
    </div>
  </li>)}</ul>;
}

export function NewIntelItems({ scope, sourceType = "all" }: { scope: "all" | "my_interests"; sourceType?: "all" | "hotlist" | "rss" }) {
  const [result, setResult] = useState<{ status: string; items: IntelReportItem[] } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setResult(null); setError("");
    reportApi.newItems(scope, controller.signal).then(data => { if (!controller.signal.aborted) setResult(data); }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [scope]);
  return <section className={box} data-testid="display-region-new_items">
    <h3 className="font-semibold">新出现的资讯</h3>
    <p className="text-xs text-muted-foreground">“首次本地采集”不代表文章刚发布；热榜标记按每个平台独立判断。</p>
    {error ? <p role="alert">{error}</p> : !result ? <p>正在读取…</p> : <><p className="text-xs">来源状态：{result.status}</p>
      {result.items.some(i => sourceType === "all" || i.source_type === sourceType) ? <NewsRows items={result.items.filter(i => sourceType === "all" || i.source_type === sourceType)} /> : <p>当前批次没有新出现的条目。</p>}</>}
  </section>;
}

function TimelineControls() {
  const [result, setResult] = useState<IntelTimeline | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    reportApi.timeline(controller.signal).then(setResult).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, []);
  const save = async () => {
    if (!result) return;
    setSaving(true); setError("");
    try { setResult(await reportApi.saveTimeline(result.config)); } catch (e) { setError(message(e)); } finally { setSaving(false); }
  };
  const changeBehavior = (index: number, patch: Partial<TimelineBehavior>) => {
    if (!result) return;
    const custom = result.config.custom;
    setResult({ ...result, config: { ...result.config, custom: index < 0 ? { ...custom, default: { ...custom.default, ...patch } }
      : { ...custom, segments: custom.segments.map((s, i) => i === index ? { ...s, ...patch } : s) } } });
  };
  const behavior = (b: TimelineBehavior, index: number) => <div className="flex flex-wrap gap-3 items-center text-sm">
    {(["fetch", "report", "once"] as const).map(k => <label key={k} className="flex gap-1 items-center"><input type="checkbox" checked={b[k]}
      onChange={e => changeBehavior(index, { [k]: e.target.checked })} />{{ fetch: "抓取", report: "生成报告", once: "本段每天一次" }[k]}</label>)}
    <select aria-label="时段报告模式" className={control} value={b.mode} onChange={e => changeBehavior(index, { mode: e.target.value as ReportMode })}>
      {Object.entries(modes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
  </div>;
  return <details className={box}><summary className="cursor-pointer font-medium">时间线与自动报告</summary>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {result && <>
      <div className="flex flex-wrap gap-3 items-center"><label><input type="checkbox" checked={result.config.enabled}
        onChange={e => setResult({ ...result, config: { ...result.config, enabled: e.target.checked } })} /> 启用时间线</label>
        <select aria-label="时间线预设" className={control} value={result.config.preset} onChange={e => setResult({ ...result, config: { ...result.config, preset: e.target.value } })}>
          {Object.entries({ always_on: "全天监控", morning_evening: "早晚汇总", office_hours: "办公时间", night_owl: "夜猫子", custom: "自定义" }).map(([key, text]) => <option key={key} value={key}>{text}</option>)}
        </select><button disabled={saving} onClick={() => void save()} className={control}>{saving ? "保存中…" : "保存时间线"}</button>
      </div>
      <p className="text-sm">已生效：{result.enabled ? result.current_segment : "时间线未启用"} · {formatShanghaiTime(result.segment_start)} — {formatShanghaiTime(result.segment_end)} · 下次切换 {formatShanghaiTime(result.next_transition)}</p>
      <p className="text-xs text-muted-foreground">北京时间；起点包含、终点不含。复用 Vibe 定时抓取，只有 Vibe 运行时才会执行；不调用 AI 或发送通知。</p>
      {result.last_scheduled_report && <p className="text-sm">最近自动报告：{formatShanghaiTime(result.last_scheduled_report.generated_at)} · {modes[result.last_scheduled_report.mode]} · {result.last_scheduled_report.item_count} 条 · {result.last_scheduled_report.status}</p>}
      {result.config.preset === "custom" && <div className="space-y-4">
        <div><p className="mb-2">其他时间默认行为</p>{behavior(result.config.custom.default, -1)}</div>
        {result.config.custom.segments.map((s, index) => <div key={index} className="rounded border border-border p-3 space-y-2">
          <div className="flex flex-wrap gap-2">
            {(["name", "start", "end", "days"] as const).map(field => <label key={field} className="text-xs">
              {{ name: "时段名称", start: "开始", end: "结束", days: "星期（1–7，逗号分隔）" }[field]}
              <input className={`${control} block`} type={field === "start" || field === "end" ? "time" : "text"} value={field === "days" ? s.days.join(",") : s[field]}
                onChange={e => setResult({ ...result, config: { ...result.config, custom: { ...result.config.custom,
                  segments: result.config.custom.segments.map((row, i) => i === index ? { ...row, [field]: field === "days" ? e.target.value.split(",").map(Number) : e.target.value } : row) } } })} />
            </label>)}
            <button className="text-sm text-destructive" onClick={() => setResult({ ...result, config: { ...result.config, custom: { ...result.config.custom,
              segments: result.config.custom.segments.filter((_, i) => i !== index) } } })}>移除此时段</button>
          </div>{behavior(s, index)}
        </div>)}
        <button className={control} onClick={() => setResult({ ...result, config: { ...result.config, custom: { ...result.config.custom,
          segments: [...result.config.custom.segments, { name: "新时段", start: "12:00", end: "13:00", days: [1, 2, 3, 4, 5, 6, 7], fetch: true, report: true, once: true, mode: "CURRENT" }] } } })}>添加时段</button>
      </div>}
    </>}
  </details>;
}

export function IntelReportPanel() {
  const [mode, setMode] = useState<ReportMode>("CURRENT");
  const [scope, setScope] = useState("all");
  const [groupBy, setGroupBy] = useState("keyword");
  const [threshold, setThreshold] = useState(5);
  const [cap, setCap] = useState(20);
  const [byPosition, setByPosition] = useState(false);
  const [result, setResult] = useState<IntelReport | null>(null);
  const [similar, setSimilar] = useState<IntelSimilar | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const requestRef = useRef<AbortController | null>(null);
  const params = new URLSearchParams({ mode, scope, group_by: groupBy, rank_threshold: String(threshold),
    max_news_per_keyword: String(cap), sort_by_position_first: String(byPosition) }).toString();
  const load = async (generate: boolean) => {
    requestRef.current?.abort();
    const controller = new AbortController(); requestRef.current = controller;
    setBusy(true); setError(""); setSimilar(null);
    try { const data = await reportApi.report(new URLSearchParams(params), generate, controller.signal); if (!controller.signal.aborted) setResult(data); }
    catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  };
  useEffect(() => { void load(false); return () => requestRef.current?.abort(); }, [params]);
  const findSimilar = async (id: number) => {
    const signal = requestRef.current?.signal;
    try { const data = await reportApi.similar(id, signal); if (!signal?.aborted) setSimilar(data); }
    catch (e) { if (!signal?.aborted) setError(message(e)); }
  };
  return <section className="space-y-4" data-testid="intel-report-panel">
    <div className={box}><h2 className="text-lg font-semibold">资讯报告</h2>
      <div className="flex flex-wrap items-center gap-3">
        <label>模式 <select aria-label="报告模式" className={control} value={mode} onChange={e => setMode(e.target.value as ReportMode)}>
          {Object.entries(modes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label>范围 <select aria-label="报告范围" className={control} value={scope} onChange={e => setScope(e.target.value)}><option value="all">全部资讯</option><option value="my_interests">我的关注</option></select></label>
        <label>分组 <select aria-label="报告分组" className={control} value={groupBy} onChange={e => setGroupBy(e.target.value)}><option value="keyword">关键词组</option><option value="platform">平台</option><option value="source">来源</option></select></label>
        <button className={control} disabled={busy} onClick={() => void load(true)}>{busy ? "读取中…" : "生成报告"}</button>
      </div>
      <details><summary className="text-sm cursor-pointer">排序与显示数量</summary><div className="mt-2 flex flex-wrap gap-3">
        <label className="text-sm">高亮前 <input aria-label="高亮排名阈值" className={`${control} w-20`} type="number" min={1} max={1000} value={threshold} onChange={e => setThreshold(Number(e.target.value))} /> 名</label>
        <label className="text-sm">每组上限 <input aria-label="每组上限" className={`${control} w-20`} type="number" min={0} max={500} value={cap} onChange={e => setCap(Number(e.target.value))} />（0 不限）</label>
        <label className="text-sm"><input type="checkbox" checked={byPosition} onChange={e => setByPosition(e.target.checked)} /> 优先使用关键词定义顺序</label>
      </div></details>
      <p className="text-xs text-muted-foreground">增量仅比较上次成功生成后的新增或有效变化。切换模式只预览；点击生成才推进基线。RSS 新鲜度和现有关注规则继续生效。</p>
    </div>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {result && !busy && <div data-testid="intel-report-result" className="space-y-3">
      <p className="text-sm">{modes[result.mode]}报告 · {result.total} 条 · 来源状态 {result.status} · {formatShanghaiTime(result.generated_at)} · 新鲜度规则已应用</p>
      <p className="text-xs text-muted-foreground">基线：{result.baseline ? formatShanghaiTime(result.baseline.generated_at) : "尚未生成"} · {result.cursor_advanced ? "本次生成成功，基线已保存" : "预览，基线未推进"}</p>
      {result.total === 0 ? <p className={box}>没有符合当前范围的新变化或资讯。</p> : result.sections.map(section => <div key={section.name} className={box}>
        <h3 className="font-medium">{section.name} · {section.count} 条（显示 {section.items.length}）</h3><NewsRows items={section.items} onSimilar={id => void findSimilar(id)} />
      </div>)}
    </div>}
    {similar && <div className={box} data-testid="intel-similar"><h3 className="font-semibold">相似资讯 · 标题规则匹配</h3>
      {similar.similar_items.length ? similar.similar_items.map(row => <div key={row.item.item_id}><span className="text-xs">标题相似度 {row.similarity_score}</span><NewsRows items={[row.item]} /></div>) : <p>没有达到 0.6 标题相似度的其他资讯。</p>}</div>}
    <TimelineControls />
  </section>;
}

export function IntelAnalyticsPanel() {
  const [topic, setTopic] = useState("机器人");
  const [topics, setTopics] = useState<string[]>([]);
  const [days, setDays] = useState(7);
  const [basis, setBasis] = useState("RAW_HISTORY");
  const [result, setResult] = useState<IntelAnalysis | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const c = new AbortController();
    api.nativeIntelFilterProfile("default", c.signal).then(p => setTopics(p.keyword_rules.groups.map(g => g.name))).catch(() => {});
    return () => c.abort();
  }, []);
  useEffect(() => {
    const c = new AbortController(); setResult(null); setError("");
    if (topic.trim()) reportApi.analysis(topic, days, basis, c.signal).then(setResult).catch(e => { if (!c.signal.aborted) setError(message(e)); });
    return () => c.abort();
  }, [topic, days, basis]);
  return <section className="space-y-4" data-testid="intel-analytics-panel">
    <div className={box}><h2 className="text-lg font-semibold">趋势分析</h2><div className="flex flex-wrap gap-3">
      <label>话题 <input aria-label="分析话题" className={control} list="intel-topic-list" value={topic} onChange={e => setTopic(e.target.value)} maxLength={120} /></label>
      <datalist id="intel-topic-list">{topics.map(t => <option key={t} value={t} />)}</datalist>
      <select aria-label="分析窗口" className={control} value={days} onChange={e => setDays(Number(e.target.value))}>{[7, 14, 30].map(d => <option key={d} value={d}>最近 {d} 天</option>)}</select>
      <select aria-label="分析数据范围" className={control} value={basis} onChange={e => setBasis(e.target.value)}><option value="RAW_HISTORY">原始历史（含过期资讯）</option><option value="CURRENT_ELIGIBLE">当前新鲜度范围</option></select>
    </div><p className="text-xs text-muted-foreground">只统计公开资讯观测，不调用 AI、不输出买卖建议。采集缺失与真实零条数分开显示。</p></div>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {!result && !error && <p>正在读取话题历史…</p>}
    {result && <>
      <div className={box}><h3 className="font-semibold">讨论趋势 · {result.topic}</h3><p className="text-xs text-muted-foreground">{result.data_basis} · {formatShanghaiTime(result.window.start)} — {formatShanghaiTime(result.window.end)}</p>
        <div className="overflow-x-auto"><table className="w-full text-left text-sm" data-testid="topic-trend"><thead><tr>{["日期", "讨论条数", "来源数", "热榜平台", "变化", "采集覆盖"].map(t => <th key={t} className="p-2">{t}</th>)}</tr></thead>
          <tbody>{result.trend.map(b => <tr key={b.date} className="border-t border-border"><td className="p-2">{b.date}</td><td>{b.mention_count}</td><td>{b.source_count}</td><td>{b.platform_count}</td><td>{pct(b.change)}</td><td>{b.coverage}</td></tr>)}</tbody></table></div>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <div className={box} data-testid="topic-lifecycle"><h3 className="font-semibold">生命周期</h3><p>{result.lifecycle.status} · {result.lifecycle.topic_type}</p><p className="text-sm text-muted-foreground">{result.lifecycle.reason}</p></div>
        <div className={box} data-testid="topic-viral"><h3 className="font-semibold">爆发检测（规则）</h3><p>{result.viral.detected == null ? "数据不足" : result.viral.detected ? "触发" : "未触发"}</p><p className="text-sm">今日 {result.viral.current_count} / 昨日 {result.viral.baseline_count}</p><p className="text-xs text-muted-foreground">{result.viral.reason}</p></div>
        <div className={box} data-testid="topic-prediction"><h3 className="font-semibold">趋势推断（规则）</h3><p>{result.prediction.direction} · 强度档位 {result.prediction.strength ?? "未评估"}</p><p className="text-xs text-muted-foreground">{result.prediction.reason}</p></div>
      </div>
      <div className={box}><h3 className="font-semibold">各平台真实排名轨迹</h3><p className="text-xs text-muted-foreground">每个平台、每条资讯独立展示；不会生成综合排名。RSS 无排名。</p>
        {!!result.rank_timeline.length && <div data-testid="rank-timeline-chart" role="img" aria-label="各来源独立真实排名折线图">
          <EChart height={280} option={{ useUTC: true, animation: false,
            grid: { left: 48, right: 20, top: 20, bottom: 38 },
            tooltip: { trigger: "item", renderMode: "richText",
              formatter: (p: { seriesName: string; value: [string, number] }) => p.seriesName + "\n" + formatShanghaiTime(p.value[0]) + " · #" + p.value[1] },
            xAxis: { type: "time", axisLabel: { color: "#888", formatter: (v: number) => formatShanghaiTime(new Date(v).toISOString()).slice(5) } },
            yAxis: { type: "value", inverse: true, min: 1, minInterval: 1, axisLabel: { color: "#888", formatter: "#{value}" }, splitLine: { lineStyle: { color: "#8883" } } },
            series: result.rank_timeline.map(t => ({ name: t.source_name + " · " + t.title, type: "line",
              showSymbol: true, symbolSize: 6, data: t.points.map(p => [p.observed_at, p.rank]) })),
          }} />
        </div>}
        {result.rank_timeline.map(t => <div key={`${t.source_id}-${t.item_id}`} data-testid={`rank-trajectory-${t.source_id}`} className="border-t border-border pt-3"><p className="text-sm font-medium">{t.source_name} · {t.title}</p><div className="flex gap-2 overflow-x-auto py-2">{t.points.map((p, i) => <span key={i} className="shrink-0 rounded bg-muted px-2 py-1 text-xs">{formatShanghaiTime(p.observed_at)}<strong className="block text-center text-primary">#{p.rank}</strong></span>)}</div></div>)}
        {!result.rank_timeline.length && <p className="text-sm text-muted-foreground">此窗口内没有真实排名观察。</p>}
      </div>
      <div className={box}><h3 className="font-semibold">平台与 RSS 活跃度对比</h3><p className="text-xs text-muted-foreground">{result.platform_note}</p><div className="overflow-x-auto"><table className="w-full text-left text-sm" data-testid="platform-comparison"><thead><tr>{["来源 / 组", "条数", "话题命中", "新出现", "排名观察", "活跃变化"].map(t => <th className="p-2" key={t}>{t}</th>)}</tr></thead><tbody>
        {result.platforms.map(p => <tr key={p.source_id} className="border-t border-border"><td className="p-2">{p.name} / {p.group}</td><td>{p.item_count}</td><td>{p.topic_hit_count}</td><td>{p.new_item_count}</td><td>{p.source_type === "rss" ? "不适用" : p.ranked_visibility}</td><td>{pct(p.activity_change)}</td></tr>)}
      </tbody></table></div></div>
      <div className={box} data-testid="keyword-cooccurrence"><h3 className="font-semibold">关键词组共现</h3><p className="text-xs text-muted-foreground">同一资讯同时命中两个关注组计一次；仅表述共同出现，不代表因果关系。</p>
        {result.cooccurrence.length ? result.cooccurrence.map(p => <div key={p.pair.join("/")}><p className="font-medium">{p.pair.join(" × ")} · {p.count} 次</p><NewsRows items={p.sample_items} /></div>) : <p>本窗口没有关键词组共现。</p>}
      </div>
    </>}
  </section>;
}
