export type ReviewMode = "daily" | "weekly";
export interface ReviewEvidence { id: string; source: string; trade_date: string; source_identity: string; path: string; value: string | number | null; unit: string; origin: "FIXTURE"|"ACQUIRED"|"UNCLASSIFIED" }
export interface ReviewSection { id: string; label: string; evidence: ReviewEvidence[]; gaps: string[]; omitted_count: number }
export interface ReviewBundle { schema_version: string; mode: ReviewMode; trade_date: string; days: string[]; bundle_id: string; sections: ReviewSection[]; selection_mode: "CURRENT_STORED_POSTHOC"; point_in_time_claim: "NONE"; canonical_authority: false }
export interface ReviewPreview { schema_version: string; mode: ReviewMode; trade_date: string; bundle_id: string; days: string[]; max_model_calls: number; available: boolean; sections: Array<{id:string;label:string;evidence_count:number;gaps:string[];omitted_count:number;source_identities:string[];origins:string[]}>; limitations:string[] }
export interface ReviewStage { id: string; label: string; status: "generated" | "requires_review" | "skipped" | "failed"; text: string; audit: {status:string;reason_codes:string[];fact_verification:"NOT_PERFORMED"}; reason_codes: string[]; evidence_ids: string[]; bundle_id: string }
export interface ReviewVersion { schema_version:string;generation_id:string;mode:ReviewMode;trade_date:string;bundle:ReviewBundle;stages:ReviewStage[];created_at:string;model_provider:string;model_name:string;status:"generated_unverified"|"requires_review";fact_verification:"NOT_PERFORMED" }
export interface ReviewVersionMeta { generation_id:string;mode:ReviewMode;trade_date:string;created_at:string;status:string }
export const reviewIds = (mode:ReviewMode) => mode === "daily" ? ["sentiment","capital","theme","dragon_tiger","leader"] : ["trend","themes","verify"];
type Obj = Record<string, unknown>;
const obj=(v:unknown):v is Obj=>typeof v==="object"&&v!==null&&!Array.isArray(v);
const keys=(v:Obj,want:string[])=>Object.keys(v).length===want.length&&want.every(k=>Object.prototype.hasOwnProperty.call(v,k));
const text=(v:unknown,max:number):v is string=>typeof v==="string"&&v.length<=max;
const integer=(v:unknown,max:number)=>typeof v==="number"&&Number.isInteger(v)&&v>=0&&v<=max;
const hash=(v:unknown,length=64)=>typeof v==="string"&&new RegExp(`^[0-9a-f]{${length}}$`).test(v);
const strings=(v:unknown,max:number,size:number):v is string[]=>Array.isArray(v)&&v.length<=max&&v.every(x=>text(x,size));
function day(v:unknown):v is string {
 if(typeof v!=="string"||!/^\d{4}-\d{2}-\d{2}$/.test(v)||v.startsWith("0000"))return false;
 const d=new Date(v+"T00:00:00Z");return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===v;
}
function stamp(v:unknown):v is string {
 if(typeof v!=="string"||v.length>64)return false;
 const m=/^(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|([+-])(\d{2}):(\d{2}))?$/.exec(v);
 return !!m&&day(m[1])&&Number(m[2])<24&&Number(m[3])<60&&Number(m[4])<60&&(!m[5]||(Number(m[6])<24&&Number(m[7])<60));
}
const gapList=(v:unknown)=>strings(v,100,100)&&v.every(x=>/^[A-Z0-9_:-]+$/.test(x));
const origins=(v:unknown)=>strings(v,3,20)&&v.every(x=>["FIXTURE","ACQUIRED","UNCLASSIFIED"].includes(x));
function days(v:unknown,end:string):v is string[]{return Array.isArray(v)&&v.length>=1&&v.length<=10&&v.every(day)&&v.every((d,i)=>d<=end&&(!i||v[i-1]<d));}
function identity(v:Obj,date:string,mode:ReviewMode){return day(date)&&v.schema_version==="shortline-segmented-review.v1"&&v.trade_date===date&&v.mode===mode&&(mode==="daily"||mode==="weekly");}
function authority(v:Obj){return v.selection_mode==="CURRENT_STORED_POSTHOC"&&v.point_in_time_claim==="NONE"&&v.canonical_authority===false;}
function evidence(v:unknown,window:string[]):v is ReviewEvidence{
 if(!obj(v)||!keys(v,["id","source","trade_date","source_identity","path","value","unit","origin"]))return false;
 return typeof v.id==="string"&&/^ev-[0-9a-f]{16}$/.test(v.id)&&text(v.source,64)&&typeof v.trade_date==="string"&&window.includes(v.trade_date)&&hash(v.source_identity)&&text(v.path,400)&&text(v.unit,32)
  &&typeof v.origin==="string"&&["FIXTURE","ACQUIRED","UNCLASSIFIED"].includes(v.origin)
  &&(v.value===null||text(v.value,120)||(typeof v.value==="number"&&Number.isFinite(v.value)&&Math.abs(v.value)<=1e15));
}
function bundle(v:unknown,date:string,mode:ReviewMode):v is ReviewBundle{
 if(!obj(v)||!keys(v,["schema_version","mode","trade_date","days","bundle_id","sections","selection_mode","point_in_time_claim","canonical_authority"])||!identity(v,date,mode)||!authority(v)||!hash(v.bundle_id)||!days(v.days,date)||!Array.isArray(v.sections)||v.sections.length!==reviewIds(mode).length)return false;
 const window=v.days;
 return v.sections.every((s,i)=>obj(s)&&keys(s,["id","label","evidence","gaps","omitted_count"])&&s.id===reviewIds(mode)[i]&&text(s.label,120)&&gapList(s.gaps)&&integer(s.omitted_count,100000)&&Array.isArray(s.evidence)&&s.evidence.length<=160&&s.evidence.every(e=>evidence(e,window))&&new Set(s.evidence.map(e=>e.id)).size===s.evidence.length);
}
function audit(v:unknown):boolean{
 return obj(v)&&keys(v,["status","reason_codes","unknown_reference_count","arithmetic_warning_count","unbound_number_count","fact_verification"])&&typeof v.status==="string"&&["not_run","requires_review","no_detected_issue_not_verified"].includes(v.status)&&gapList(v.reason_codes)&&integer(v.unknown_reference_count,20)&&integer(v.arithmetic_warning_count,3)&&integer(v.unbound_number_count,200)&&v.fact_verification==="NOT_PERFORMED";
}
export function ownsReview(value:unknown,date:string,mode:ReviewMode):value is ReviewVersion {
 if(!obj(value)||!keys(value,["schema_version","generation_id","mode","trade_date","bundle","stages","created_at","model_provider","model_name","status","fact_verification"])||!identity(value,date,mode)||!hash(value.generation_id,32)||!stamp(value.created_at)||!text(value.model_provider,120)||!text(value.model_name,120)||value.fact_verification!=="NOT_PERFORMED"||!["generated_unverified","requires_review"].includes(String(value.status))||!bundle(value.bundle,date,mode)||!Array.isArray(value.stages))return false;
 const ids=[...reviewIds(mode),"summary"],b=value.bundle;
 const all=new Set(b.sections.flatMap(s=>s.evidence.map(e=>e.id)));
 return value.stages.length===ids.length&&value.stages.every((s,i)=>obj(s)&&keys(s,["id","label","status","text","audit","reason_codes","evidence_ids","bundle_id"])&&s.id===ids[i]&&text(s.label,120)&&typeof s.status==="string"&&["generated","requires_review","skipped"].includes(s.status)&&text(s.text,12000)&&audit(s.audit)&&gapList(s.reason_codes)&&strings(s.evidence_ids,800,19)&&s.evidence_ids.every(id=>all.has(id))&&s.bundle_id===b.bundle_id);
}
export function ownsPreview(p:unknown,date:string,mode:ReviewMode):p is ReviewPreview{
 if(!obj(p)||!keys(p,["schema_version","mode","trade_date","bundle_id","days","selection_mode","point_in_time_claim","canonical_authority","max_model_calls","model_calls_performed","sections","available","limitations"])||!identity(p,date,mode)||!authority(p)||!hash(p.bundle_id)||!days(p.days,date)||p.max_model_calls!==reviewIds(mode).length+1||p.model_calls_performed!==0||typeof p.available!=="boolean"||!strings(p.limitations,20,300)||!Array.isArray(p.sections)||p.sections.length!==reviewIds(mode).length)return false;
 return p.sections.every((s,i)=>obj(s)&&keys(s,["id","label","evidence_count","gaps","omitted_count","source_identities","origins"])&&s.id===reviewIds(mode)[i]&&text(s.label,120)&&integer(s.evidence_count,160)&&integer(s.omitted_count,100000)&&gapList(s.gaps)&&Array.isArray(s.source_identities)&&s.source_identities.length<=160&&s.source_identities.every(x=>hash(x))&&origins(s.origins));
}
export function ownsVersionList(value:unknown,date:string,mode:ReviewMode):value is ReviewVersionMeta[]{
 return Array.isArray(value)&&value.length<=30&&value.every(v=>obj(v)&&keys(v,["generation_id","mode","trade_date","created_at","status"])&&v.mode===mode&&v.trade_date===date&&day(v.trade_date)&&hash(v.generation_id,32)&&stamp(v.created_at)&&typeof v.status==="string"&&["generated_unverified","requires_review"].includes(v.status));
}
