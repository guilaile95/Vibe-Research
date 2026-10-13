import { create } from "zustand";
import { request, ApiError } from "@/lib/api";
import { streamNdjson } from "@/lib/ndjson";
import type { LlmConfig } from "@/lib/llm";
import { makeStreamLlmConfig } from "@/stores/dailyReviewAiTaskStore";
import { ownsReview, reviewIds, type ReviewPreview, type ReviewVersion } from "@/lib/shortlineReview";

interface State { key:string|null; running:boolean; stage:string; temporary:string; result:ReviewVersion|null;error:string;start:(preview:ReviewPreview,llm:LlmConfig)=>Promise<void>;cancel:()=>void }
let epoch=0;let active:AbortController|null=null;
export const useShortlineReviewTaskStore=create<State>((set,get)=>({
 key:null,running:false,stage:"",temporary:"",result:null,error:"",
 start:async(preview,llm)=>{
  if(get().running)return;
  const owner=++epoch;const controller=new AbortController();active=controller;
  const key=`${preview.mode}:${preview.trade_date}`;const generation=crypto.randomUUID().replace(/-/g,"");
  set({key,running:true,stage:"准备材料",temporary:"",result:null,error:""});
  let terminal:string|null=null,invalid=false,failed=false;const completed=new Set<string>();
  const expected=[...reviewIds(preview.mode),"summary"];
  try{
   await streamNdjson("/api/shortline-review/generate",{trade_date:preview.trade_date,mode:preview.mode,bundle_id:preview.bundle_id,generation_id:generation,llm:makeStreamLlmConfig(llm)},event=>{
    if(owner!==epoch||controller.signal.aborted)return;
    if(terminal){invalid=true;return;}
    if(event.type==="stage"){
      if(event.id!==expected[completed.size])invalid=true;
      set({stage:String(event.label),temporary:""});
    }else if(event.type==="delta"){
      if(event.id!==expected[completed.size]||typeof event.text!=="string")invalid=true;
      else set(s=>({temporary:(s.temporary+event.text).slice(0,12000)}));
    }else if(event.type==="stage_done"){
      if(event.stage?.id!==expected[completed.size]||event.stage?.bundle_id!==preview.bundle_id)invalid=true;
      else completed.add(event.stage.id);
    }else if(event.type==="done"){
      if(event.generation_id!==generation||event.bundle_id!==preview.bundle_id||completed.size!==expected.length)invalid=true;
      terminal=event.generation_id;
    }else if(event.type==="error"){failed=true;set({error:typeof event.message==="string"?event.message:"生成失败"});}
   },controller.signal);
   if(owner!==epoch||controller.signal.aborted)return;
   if(!terminal||invalid||failed)throw new ApiError("分段流未完整结束，未确认保存版本",502);
   const result=await request<ReviewVersion>(`/shortline-review/version/${terminal}`,"GET",undefined,{signal:controller.signal});
   if(owner!==epoch||controller.signal.aborted)return;
   if(!ownsReview(result,preview.trade_date,preview.mode)||result.generation_id!==generation)throw new ApiError("保存版本身份无法核对",502);
   set({result,temporary:"",stage:"已保存，事实未核验"});
  }catch(error){if(owner===epoch&&!controller.signal.aborted)set({error:error instanceof ApiError?error.message:"分段复盘失败",temporary:""});}
  finally{if(owner===epoch){active=null;set({running:false});}}
 },
 cancel:()=>{++epoch;active?.abort();active=null;set({running:false,stage:"已取消",temporary:"",error:"已请求取消；未确认新版本。"});},
}));
