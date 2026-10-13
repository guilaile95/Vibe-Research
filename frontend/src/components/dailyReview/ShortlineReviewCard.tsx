import { useEffect, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { request } from "@/lib/api";
import { loadLlm } from "@/lib/llm";
import { ownsPreview, ownsReview, ownsVersionList, type ReviewMode, type ReviewPreview, type ReviewVersion, type ReviewVersionMeta } from "@/lib/shortlineReview";
import { useShortlineReviewTaskStore } from "@/stores/shortlineReviewTaskStore";

export function ShortlineReviewCard({tradeDate}:{tradeDate:string|null}) {
 const [mode,setMode]=useState<ReviewMode>("daily");const [preview,setPreview]=useState<ReviewPreview|null>(null);
 const [versions,setVersions]=useState<ReviewVersionMeta[]>([]);const [selected,setSelected]=useState<ReviewVersion|null>(null);
 const [error,setError]=useState("");const [loading,setLoading]=useState(false);const ownership=useRef(0);
 const task=useShortlineReviewTaskStore();const key=`${mode}:${tradeDate}`;const ownTask=task.key===key;
 useEffect(()=>{const id=++ownership.current;const controller=new AbortController();setPreview(null);setSelected(null);setVersions([]);setError("");setLoading(false);
  if(tradeDate)request<ReviewVersionMeta[]>(`/shortline-review/versions?trade_date=${tradeDate}&mode=${mode}`,"GET",undefined,{signal:controller.signal}).then(v=>{
   if(id!==ownership.current||controller.signal.aborted)return;
   if(!ownsVersionList(v,tradeDate,mode))throw Error();setVersions(v);
  }).catch(()=>{if(id===ownership.current&&!controller.signal.aborted)setError("历史版本暂不可读取");});
  return()=>{++ownership.current;controller.abort();};
 },[tradeDate,mode,task.result?.generation_id]);
 async function inspect(){if(!tradeDate)return;const id=++ownership.current;setLoading(true);setError("");setPreview(null);
  try{const p=await request<ReviewPreview>(`/shortline-review/preview?trade_date=${tradeDate}&mode=${mode}`);if(id!==ownership.current)return;if(!ownsPreview(p,tradeDate,mode))throw Error();setPreview(p);}
  catch{if(id===ownership.current)setError("材料预览暂不可用；未调用模型");}finally{if(id===ownership.current)setLoading(false);}}
 async function choose(id:string){if(!tradeDate)return;const owner=++ownership.current;setLoading(false);setSelected(null);setError("");
  try{const v=await request<ReviewVersion>(`/shortline-review/version/${id}`);if(owner!==ownership.current)return;if(!ownsReview(v,tradeDate,mode)||v.generation_id!==id)throw Error();setSelected(v);}
  catch{if(owner===ownership.current)setError("版本身份或内容无法核对");}}
 const result=selected||(ownTask&&ownsReview(task.result,tradeDate||"",mode)?task.result:null);
 return <GlassCard className="p-4" data-testid="shortline-segmented-review">
  <h3 className="font-semibold">分段复盘与周报</h3><p className="mt-1 text-xs text-muted-foreground">{tradeDate||"未选择交易日"} · 只读归档事后研究，PIT未证明。每次手动生成最多{mode==="daily"?6:4}次模型调用；不自动采集、不自动重试。</p>
  <div className="mt-3 flex flex-wrap gap-2"><select aria-label="复盘类型" value={mode} onChange={e=>setMode(e.target.value as ReviewMode)} className="rounded border bg-background p-2"><option value="daily">五段日复盘＋汇总</option><option value="weekly">本周回看＋汇总</option></select>
   <button type="button" disabled={!tradeDate||loading} onClick={()=>void inspect()} className="rounded border px-3 py-2">{loading?"读取材料…":"查看生成材料"}</button>
   <button type="button" disabled={!preview?.available||task.running} onClick={()=>{const llm=loadLlm();if(!llm){setError("请先在接入AI配置现有模型");return;}if(preview)void task.start(preview,llm);}} className="rounded bg-primary px-3 py-2 text-white disabled:opacity-40">手动生成（最多{mode==="daily"?6:4}次）</button>
   {task.running&&<button type="button" onClick={task.cancel} className="rounded border px-3 py-2">取消当前分段任务</button>}
  </div>
  {preview&&<details open className="mt-3 text-xs"><summary>本次材料范围 · {preview.days.join("、")}</summary>{preview.sections.map(s=><p key={s.id}>{s.label}：{s.evidence_count}条证据，省略{s.omitted_count}项；来源标记{s.origins?.join("/")||"UNCLASSIFIED"}；{s.gaps.length?s.gaps.join(" / "):"未报告缺口"}</p>)}<p className="break-all">材料身份：{preview.bundle_id}</p><p>缺证据段跳过；未记录等于未知。私人交易明细和统计不进入模型材料。</p></details>}
  {(error||(ownTask&&task.error))&&<p role="alert" className="mt-3 text-sm text-destructive">{error||(ownTask&&task.error)}</p>}
  {ownTask&&task.running&&<div className="mt-3"><p>{task.stage} · 临时内容，尚未保存</p><pre className="whitespace-pre-wrap break-words text-sm">{task.temporary}</pre></div>}
  <div className="mt-3"><label className="text-xs">已保存版本 <select aria-label="选择复盘版本" value={selected?.generation_id||""} onChange={e=>{if(e.target.value)void choose(e.target.value);else {++ownership.current;setLoading(false);setSelected(null);}}} className="max-w-full rounded border bg-background p-2"><option value="">{versions.length?"选择历史版本":"暂无已保存版本"}</option>{versions.map(v=><option key={v.generation_id} value={v.generation_id}>{v.created_at} · {v.status==="requires_review"?"需复查":"生成完成，未核验"}</option>)}</select></label></div>
  {result&&<div className="mt-4"><p className="text-xs">版本{result.generation_id.slice(0,8)} · {result.created_at} · {result.model_provider}/{result.model_name} · 事实核验未执行</p>{result.stages.map(s=><section key={s.id} className="mt-3 border-t pt-3"><h4 className="font-medium">{s.label} · {s.status==="requires_review"?"需要人工复查":s.status==="skipped"?"材料不足，未生成":"已生成，未验证事实"}</h4>{s.reason_codes.length>0&&<p className="text-xs text-amber-700">{s.reason_codes.join(" / ")}</p>}<pre className="mt-2 whitespace-pre-wrap break-words font-sans text-sm">{s.text}</pre><details className="mt-2 text-xs"><summary>查看本段原始依据与日期</summary>{result.bundle.sections.filter(x=>x.id===s.id||s.id==="summary").flatMap(x=>x.evidence).filter(e=>s.evidence_ids.includes(e.id)).slice(0,160).map(e=><p key={e.id} className="break-all">{e.trade_date} · {e.origin} · {e.path} = {e.value===null?"未知（源字段缺失）":String(e.value)}（{e.unit}）[{e.id}]</p>)}</details></section>)}</div>}
 </GlassCard>;
}
