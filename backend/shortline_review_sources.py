"""Allowlisted, archived market inputs for P5. Never calls a live provider/model."""
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
import importlib

import trade_calendar
import shortline_review_contract as C
import shortline_review_store as store


def _query(module, name, day):
    try:
        value=getattr(importlib.import_module(module),name)(day)
        return value if type(value)is dict else None
    except Exception:return None


def _projection(value,day,expected_schema,statuses=("normal","partial")):
    if (type(value)is not dict or value.get("trade_date")!=day or value.get("schema_version")!=expected_schema or value.get("status") not in statuses
        or value.get("point_in_time_claim")!="NONE" or value.get("selection_mode")!="CURRENT_STORED_POSTHOC"):return None
    p=value.get("projection")
    if type(p)is not dict:return None
    if expected_schema=="shortline-research.v1" and value.get("research_only")is not True:return None
    if expected_schema=="short-term-theme-research-archive-v1" and (value.get("archive_only")is not True or value.get("ingestion_enabled")is not False or p.get("canonical_authority")is not False):return None
    return p


def market_sources(day):
    """No user portfolio, private trades, journal reasons, model cfg or raw errors."""
    out={}
    shortline=_query("shortline_research_service","query_shortline_research",day)
    p=_projection(shortline,day,"shortline-research.v1")
    if p:
        identity=C.digest({"evidence":shortline.get("evidence",[]),"projection":p})
        out["sentiment"]=(identity,{"daily":p.get("daily"),"cohort":p.get("cohort")},shortline["status"],"FIXTURE" if shortline.get("fixture")is True else "ACQUIRED" if shortline.get("fixture")is False else "UNCLASSIFIED")
        out["leader"]=(identity,{"daily":p.get("daily"),"cohort":p.get("cohort")},shortline["status"],"FIXTURE" if shortline.get("fixture")is True else "ACQUIRED" if shortline.get("fixture")is False else "UNCLASSIFIED")
    themes=_query("short_term_theme_research_service","query_theme_research",day)
    p=_projection(themes,day,"short-term-theme-research-archive-v1",("complete","partial"))
    if p:
        identity=C.digest({"projection":p,"evidence":themes.get("evidence")})
        # Use only the requested day; a five-day view is never silently today's tree.
        out["theme"]=(identity,{"tree":p.get("tree"),"firstboards":[d.get("firstboards") for d in p.get("days",[]) if type(d)is dict and d.get("date")==day]},"normal" if themes["status"]=="complete" else "partial","FIXTURE" if p.get("fixture")is True else "ACQUIRED" if p.get("fixture")is False else "UNCLASSIFIED")
    try:snapshot=store.read_daily_snapshot(day)
    except Exception:snapshot=None
    if snapshot:
        review=snapshot["review"]
        if review.get("status")in ("normal","partial"):
            out["capital"]=(snapshot["payload_hash"],{"capital_activity":review.get("capital_activity"),"indices":review.get("market_environment",{}).get("indices")},review["status"])
    supplements=_query("shortline_review_supplement","query_supplements",day)
    if supplements:
        for key in ("capital_extra","dragon_tiger"):
            item=supplements.get(key)
            if type(item)is dict and item.get("trade_date")==day and item.get("status")in ("normal","partial"):
                out[key]=(item["identity"],item["data"],item["status"],"FIXTURE" if item.get("fixture")is True else "ACQUIRED" if item.get("fixture")is False else "UNCLASSIFIED")
    return out


def verification_source(day,through=None):
    # Explicit allowlist excludes user reason text and all private trading records.
    through=through or day
    start=(date.fromisoformat(through)-timedelta(days=date.fromisoformat(through).weekday())).isoformat()
    value=_query("next_day_verification","view",day)
    if type(value)is not dict or value.get("trade_date")!=day:return None
    items=value.get("items")
    if type(items)is not list:return None
    if not items:return C.digest({"day":day,"state":"NO_CONDITIONS"}),None,"NO_CONDITIONS"
    kept=[]
    for item in items:
        if type(item)is not dict:return None
        target=item.get("target_date")
        if type(target)is not str or not start<=target<=through:continue
        verified=item.get("verified")
        kept.append({"metric":item.get("metric"),"direction":item.get("direction"),"current_value":item.get("current_value"),
                     "prior_value":item.get("prior_value"),"actual":item.get("actual"),"state":item.get("state"),
                     "set_date":day,"target_date":target,"verdict":"TRUE" if verified is True else "FALSE" if verified is False else "UNKNOWN"})
    if not kept:return C.digest({"day":day,"through":through,"state":"OUTSIDE_WEEK"}),None,"OUTSIDE_WEEK"
    decided=[x for x in kept if x["verdict"]!="UNKNOWN"]
    projection={"summary":{"total":len(kept),"decided":len(decided),"hit":sum(x["verdict"]=="TRUE"for x in decided),"unknown":len(kept)-len(decided)},"items":kept}
    return C.digest(projection),projection,"normal" if len(decided)==len(kept) else "partial"


def review_days(end,mode):
    C.day(end);C.plan(mode)
    if end>datetime.now(timezone(timedelta(hours=8))).date().isoformat():raise ValueError("future review date")
    sessions=trade_calendar._load_calendar()
    if not sessions or end not in sessions:raise ValueError("official calendar unavailable")
    if mode=="daily":return [end]
    start=date.fromisoformat(end)-timedelta(days=date.fromisoformat(end).weekday()+7)
    return [d for d in sessions if start.isoformat()<=d<=end][-10:]


def build_bundle(end,mode,*,sources=market_sources,verify=None,dates=review_days):
    days=dates(end,mode);specs=C.plan(mode)
    verify=verify or (lambda d:verification_source(d,end))
    sections={sid:{"id":sid,"label":label,"evidence":[],"gaps":[],"omitted_count":0} for sid,label in specs}
    def add(sid,source,d,item):
        s=sections[sid]
        if item is None:s["gaps"].append(source.upper()+":MISSING:"+d);return
        identity,data,status=item[:3]
        origin=item[3] if len(item)>3 else "UNCLASSIFIED"
        if status in ("NO_CONDITIONS","OUTSIDE_WEEK"):
            s["gaps"].append(source.upper()+":"+status+":"+d);return
        evidence,omitted=C.evidence_from(source,d,identity,data,maximum=(C.MAX_EVIDENCE//len(days) if mode=="weekly" else C.MAX_EVIDENCE//(2 if sid=="capital" else 1)),origin=origin)
        # Each day receives its own equal count/byte budget so early dense days cannot erase later ones.
        budget=C.MAX_SECTION_INPUT_BYTES//(len(days) if mode=="weekly" else (2 if sid=="capital" else 1))-1200
        while evidence and len(C.canonical(evidence).encode())>budget:evidence.pop();omitted+=1
        s["evidence"].extend(evidence);s["omitted_count"]+=omitted
        if omitted:s["gaps"].append(source.upper()+":OMITTED_"+str(omitted)+":"+d)
        if status!="normal":s["gaps"].append(source.upper()+":PARTIAL:"+d)
        if not evidence:s["gaps"].append(source.upper()+":NO_USABLE_EVIDENCE:"+d)
    monday=(date.fromisoformat(end)-timedelta(days=date.fromisoformat(end).weekday())).isoformat()
    for d in days:
        values=sources(d)
        if mode=="daily":
            for sid,_ in specs:add(sid,sid,d,values.get(sid))
            add("capital","capital_extra",d,values.get("capital_extra"))
        else:
            add("trend","sentiment",d,values.get("sentiment"))
            if d>=monday:
                add("themes","theme",d,values.get("theme"))
            add("verify","verification",d,verify(d))
    for s in sections.values():
        s["gaps"]=sorted(set(s["gaps"]))
        while s["evidence"] and len(C.canonical(s).encode())>C.MAX_SECTION_INPUT_BYTES:
            s["evidence"].pop();s["omitted_count"]+=1
    return C.finalize_bundle(mode,end,days,list(sections.values()))


def preview(end,mode):
    b=build_bundle(end,mode)
    return {"schema_version":C.SCHEMA,"mode":mode,"trade_date":end,"bundle_id":b["bundle_id"],"days":b["days"],**C.BASIS,
            "max_model_calls":len(C.plan(mode))+1,"model_calls_performed":0,
            "sections":[{"id":s["id"],"label":s["label"],"evidence_count":len(s["evidence"]),"gaps":s["gaps"],"omitted_count":s["omitted_count"],"source_identities":sorted({e["source_identity"] for e in s["evidence"]}),"origins":sorted({e["origin"] for e in s["evidence"]})} for s in b["sections"]],
            "available":any(e["value"] is not None for s in b["sections"] for e in s["evidence"]),
            "limitations":["仅使用现有归档，生成不会采集行情。","当前存档的事后研究，不证明复盘当时可知。","每段独立调用；缺证据跳过，不自动重试。","私人交易统计不进入模型材料。"]}
