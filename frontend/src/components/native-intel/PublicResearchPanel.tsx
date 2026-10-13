import { useEffect, useRef, useState } from "react";
import { request } from "@/lib/api";
import { FIELD_LABELS, PUBLIC_SOURCES, parsePublicResearch, type PublicResearch, type PublicSource } from "@/lib/publicResearch";

const statusLabel: Record<string, string> = { normal: "已归档", partial: "部分 / 口径受限", missing: "缺失", unavailable: "不可用", closed: "已关闭 / 已结算", stale: "已陈旧" };
const display = (value: unknown) => value === null ? "未知" : typeof value === "boolean" ? value ? "是" : "否" : typeof value === "number" ? value.toLocaleString("zh-CN", { maximumFractionDigits: 6 }) : String(value);

export function PublicResearchPanel({ kind }: { kind: "events" | "industry" }) {
  const sources = (Object.keys(PUBLIC_SOURCES) as PublicSource[]).filter(s => kind === "events" ? s.startsWith("public_") : !s.startsWith("public_"));
  const [selected, setSelected] = useState<PublicSource>(sources[0]);
  const source = sources.includes(selected) ? selected : sources[0];
  const [state, setState] = useState<{ source: PublicSource; data?: PublicResearch; error?: string }>({ source });
  const [version, setVersion] = useState(0);
  const serial = useRef(0);
  useEffect(() => {
    const id = ++serial.current;
    setState({ source });
    void request<unknown>(`/public-research?source_id=${source}`).then(value => {
      const data = parsePublicResearch(value, source);
      if (serial.current === id) setState({ source, data });
    }).catch(() => {
      if (serial.current === id) setState({ source, error: "归档读取失败或响应格式无效，请重试" });
    });
    return () => { serial.current += 1; };
  }, [source, version]);
  const current = state.source === source ? state : { source };
  return <section aria-label={kind === "events" ? "事件定价归档" : "产业公开数据归档"} className="space-y-4 min-w-0">
    <p className="text-sm text-muted-foreground">只读已归档公开数据。刷新仅重读归档；实时采集与定时任务未启用。</p>
    <div className="flex flex-wrap gap-2">
      {sources.map(s => <button key={s} type="button" aria-pressed={source === s} className="rounded border px-3 py-2 text-sm aria-pressed:bg-primary/15" onClick={() => setSelected(s)}>{PUBLIC_SOURCES[s]}</button>)}
      <button type="button" className="rounded border px-3 py-2 text-sm" onClick={() => setVersion(v => v + 1)}>重读归档</button>
    </div>
    {current.error ? <p role="alert">{current.error}</p> : !current.data ? <p role="status">正在读取公开数据归档…</p> : <>
      <p role="status">{statusLabel[current.data.status]} · {current.data.message}</p>
      {current.data.fixture && <p className="rounded border border-amber-500 p-3 font-medium">合成案例：仅离线软件验证，非真实市场数据</p>}
      <p className="rounded border p-3 text-sm">{current.data.guard}</p>
      {current.data.missing_subjects.length > 0 && <p>缺少来源：{current.data.missing_subjects.join("、")}；缺失不作为零值</p>}
      {current.data.reason_codes.length > 0 && <p className="break-words text-xs">诊断：{current.data.reason_codes.join(" · ")}</p>}
      {current.data.blocks.map(block => <article key={block.subject} className="space-y-3 rounded-lg border p-3 min-w-0">
        <h4 className="font-semibold">{block.subject} · {statusLabel[block.status]}</h4>
        <p className="break-all text-xs">采集时刻：{block.captured_at} · 本地接收：{block.evidence.locally_received_at}</p>
        <p className="break-all text-xs">来源：{block.source_url}</p>
        <p className="text-xs">数据许可：{block.license_status}；公开可读不代表可自由再分发</p>
        {block.reason_codes.length > 0 && <p className="break-words text-xs">覆盖：{block.reason_codes.join(" · ")}</p>}
        {block.rows.length === 0 && <p>没有可展示记录；不代表对应经济活动为零</p>}
        {block.rows.map(row => <div key={row.id} className="space-y-2 rounded border p-3 min-w-0">
          <h5 className="break-words font-medium">{row.title}</h5>
          <p>{display(row.value)} {row.currency || ""} · {row.unit} · {statusLabel[row.status]}{row.stale ? " · 已陈旧" : ""}</p>
          <p className="break-all text-xs">来源日期：{row.source_date || "未知"} · 来源时刻：{row.source_time || "未知（采集时刻不代替源更新时间）"}</p>
          {row.missing.length > 0 && <p className="break-words text-xs">缺口：{row.missing.join(" · ")}</p>}
          <dl className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
            {Object.entries(FIELD_LABELS).filter(([key]) => key in row).map(([key, label]) => <div key={key} className="min-w-0"><dt className="text-muted-foreground">{label}</dt><dd className="break-all">{display(row[key])}</dd></div>)}
          </dl>
          {Array.isArray(row.listings) && <details><summary className="text-sm">查看岗位标识与日期（展示前 50 条，共 {row.listings.length} 条）</summary><ul className="space-y-2 text-xs">
            {row.listings.slice(0, 50).map((job: Record<string, unknown>) => <li key={String(job.listing_id)} className="break-words">{String(job.listing_id)} · {String(job.title)} · {String(job.time_semantics)}：{job.source_time ? String(job.source_time) : "未知"}</li>)}
          </ul></details>}
        </div>)}
        <details><summary className="text-xs">来源回执与版本</summary><p className="break-all text-xs">回执 {block.evidence.observation_id}<br />SHA256 {block.evidence.raw_payload_hash}<br />适配器 {block.evidence.normalizer_version}<br />当前归档事后研究，历史当时已知声明：{block.evidence.point_in_time_claim}</p></details>
      </article>)}
    </>}
  </section>;
}
