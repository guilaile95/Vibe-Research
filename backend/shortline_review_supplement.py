"""P5 market-only receipt adapters and an explicitly disabled manual collector.

Raw response archives share FactLake. Viewing/generating never invokes collect().
No client-defined endpoint, headers, credentials or account data is accepted.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
import hashlib
import json
import math
import os
import re
import uuid

from data_contracts import ProviderObservation,FetchSemantics,HistoryMode,QualityStatus
import shortline_review_contract as C

KINDS=("margin","industry_flow","dragon_tiger")
SCHEMA="shortline-review-supplement.v1"
DATASETS={k:"research_p5_"+k+"_v1" for k in KINDS}
ENDPOINTS={"margin":"RPTA_RZRQ_LSHJ","industry_flow":"push2_industry_main_flow_today","dragon_tiger":"RPT_DAILYBILLBOARD_DETAILSNEW"}
MAX_BYTES=4*1024*1024


def _instant(value):
    if type(value)is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})",value):raise ValueError("invalid supplement timestamp")
    offset=re.search(r"[+-](\d{2}):(\d{2})$",value)
    if offset and (int(offset[1])>=24 or int(offset[2])>=60):raise ValueError("invalid supplement offset")
    return datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(timezone.utc)


def _number(v):
    return v if type(v)in(int,float) and math.isfinite(v) and abs(v)<=1e15 else None


def normalize(raw,kind,day):
    C.day(day)
    if kind not in KINDS or type(raw)is not bytes or not raw or len(raw)>MAX_BYTES:raise ValueError("invalid supplemental raw response")
    def unique(pairs):
        out={}
        for k,v in pairs:
            if k in out:raise ValueError("duplicate supplemental JSON field")
            out[k]=v
        return out
    obj=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite supplemental JSON")))
    if type(obj)is not dict:raise ValueError("invalid supplemental response")
    if kind=="industry_flow":
        data=obj.get("data")
        if obj.get("rc",0)!=0 or type(data)is not dict or type(data.get("diff"))is not list:raise ValueError("invalid industry response")
        source_rows=data["diff"];total=data.get("total");rows=[]
        for row in source_rows[:100]:
            if type(row)is not dict:continue
            stamp=_number(row.get("f124"))
            if stamp is None:continue
            try:observed=datetime.fromtimestamp(stamp,timezone(timedelta(hours=8))).date().isoformat()
            except (ValueError,OverflowError,OSError):continue
            if observed!=day:continue
            rows.append({"code":C.safe_text(row.get("f12","")),"name":C.safe_text(row.get("f14","")),
                "main_net_yuan":_number(row.get("f62")),"main_pct":_number(row.get("f184")),"change_pct":_number(row.get("f3"))})
    else:
        result=obj.get("result")
        if obj.get("success")is not True or obj.get("code")!=0 or type(result)is not dict or type(result.get("data"))is not list:raise ValueError("invalid datacenter response")
        source_rows=result["data"];total=result.get("count");rows=[]
        for row in source_rows[:100]:
            if type(row)is not dict:continue
            key="DIM_DATE" if kind=="margin" else "TRADE_DATE"
            if type(row.get(key))is not str or row[key][:10]!=day:continue
            if kind=="margin":
                rows.append({"margin_balance_yuan":_number(row.get("RZRQYE")),"financing_balance_yuan":_number(row.get("RZYE")),"short_balance_yuan":_number(row.get("RQYE")),"financing_buy_yuan":_number(row.get("RZMRE")),"financing_net_yuan":_number(row.get("RZJME")),"financing_float_pct":_number(row.get("RZYEZB"))})
            else:
                code=row.get("SECURITY_CODE")
                if type(code)is not str or len(code)!=6 or not code.isdigit():continue
                rows.append({"stock_code":code,"stock_name":C.safe_text(row.get("SECURITY_NAME_ABBR","")),
                    "billboard_net_yuan":_number(row.get("BILLBOARD_NET_AMT")),"turnover_rate_pct":_number(row.get("TURNOVERRATE"))})
    unique_rows=len({C.digest(row) for row in source_rows if type(row)is dict})
    complete=type(total)is int and total>0 and len(rows)==len(source_rows)==total==unique_rows
    principal="margin_balance_yuan" if kind=="margin" else "main_net_yuan" if kind=="industry_flow" else "billboard_net_yuan"
    if any(row.get(principal)is None for row in rows):complete=False
    if kind=="margin" and len(rows)!=1:rows=[];complete=False
    return {"trade_date":day,"status":"normal" if complete else "partial","source_total":total if type(total)is int and total>=0 else None,
            "returned_count":len(rows),"complete":complete,"rows":rows,
            "reason_codes":[] if complete else ["SOURCE_DATE_OR_COVERAGE_PARTIAL"],
            "amount_unit":"YUAN","return_unit":"PERCENTAGE_POINTS","source_kind":kind,
            "limitations":["名单样本只描述本批返回记录；龙虎榜单日和多日记录不跨条求和。","融资数据T+1披露，不等同T日当时已知。","行业资金采用东财主力净额口径；不会混用新浪流入减流出。"]}


def persist_raw(lake,kind,day,raw,*,fixture=False,captured_at=None):
    if type(fixture)is not bool:raise ValueError("invalid fixture marker")
    if kind not in KINDS or type(raw)is not bytes or not raw or len(raw)>MAX_BYTES:raise ValueError("invalid capture bytes")
    C.day(day)
    try:value=normalize(raw,kind,day)
    except (ValueError,TypeError,RecursionError):value={"status":"invalid","reason_codes":["NORMALIZATION_FAILED"]}
    now=datetime.now(timezone.utc).isoformat(timespec="microseconds")
    captured_at=captured_at or now
    parsed=_instant(captured_at)
    if parsed.tzinfo is None or parsed>datetime.now(timezone.utc):raise ValueError("invalid capture time")
    observation=ProviderObservation(observation_id="p5-"+uuid.uuid4().hex,dataset_id=DATASETS[kind],provider_id="eastmoney_public",provider_endpoint=ENDPOINTS[kind],provider_symbol="MARKET",
        request_fingerprint=C.digest({"kind":kind,"trade_date":day,"sample_limit":100}),source_payload_hash="sha256:"+hashlib.sha256(raw).hexdigest(),normalizer_version=SCHEMA,
        payload={"schema_version":SCHEMA,"kind":kind,"trade_date":day,"fixture":fixture,"locally_received_at":now},
        fetch_semantics=FetchSemantics.BY_DATE if kind!="industry_flow" else FetchSemantics.SNAPSHOT,
        history_mode=HistoryMode.BY_DATE if kind!="industry_flow" else HistoryMode.SNAPSHOT_ONLY,
        fetched_at=parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z"),trade_date=day,quality_status=QualityStatus.VALID if value["status"]=="normal" else QualityStatus.INVALID if value["status"]=="invalid" else QualityStatus.DEGRADED,reason_codes=tuple(value["reason_codes"]))
    lake.store_observation(observation,raw,"application/json")
    return {"observation_id":observation.observation_id,"status":value["status"],"fixture":fixture}


def query_supplements(day):
    C.day(day);root=os.environ.get("VR_FACT_LAKE_ROOT","").strip()
    if not root:return {}
    from fact_lake_store import open_existing_fact_lake_snapshot
    lake=open_existing_fact_lake_snapshot(root);found={}
    for kind in KINDS:
        observations=lake.list_observations(dataset_id=DATASETS[kind],start_trade_date=day,end_trade_date=day,limit=100,max_payload_bytes=MAX_BYTES)
        if not observations:continue
        if len(observations)>=100:raise ValueError("supplement selection cap reached")
        latest=max(_instant(s.observation.fetched_at) for s in observations)
        candidates=[s for s in observations if _instant(s.observation.fetched_at)==latest]
        if len({(s.observation.source_payload_hash,C.canonical(s.observation.payload)) for s in candidates})!=1:raise ValueError("ambiguous same-time supplement")
        chosen=candidates[0];o=chosen.observation;p=o.payload
        if (type(p)is not dict or set(p)!={"schema_version","kind","trade_date","fixture","locally_received_at"} or p["schema_version"]!=SCHEMA
            or p["kind"]!=kind or p["trade_date"]!=day or o.trade_date!=day or o.provider_endpoint!=ENDPOINTS[kind] or o.provider_id!="eastmoney_public"
            or o.normalizer_version!=SCHEMA or o.dataset_id!=DATASETS[kind] or o.provider_symbol!="MARKET" or type(p["fixture"])is not bool):raise ValueError("supplement receipt identity mismatch")
        captured=_instant(o.fetched_at);received=_instant(p["locally_received_at"])
        if captured.tzinfo is None or received.tzinfo is None or not captured<=received<=datetime.now(timezone.utc):raise ValueError("supplement receipt time mismatch")
        if o.request_fingerprint!=C.digest({"kind":kind,"trade_date":day,"sample_limit":100}):raise ValueError("supplement request mismatch")
        raw=lake.read_payload(o.observation_id,max_payload_bytes=MAX_BYTES)
        if raw is None or "sha256:"+hashlib.sha256(raw).hexdigest()!=o.source_payload_hash:raise ValueError("supplement raw identity mismatch")
        data=normalize(raw,kind,day)
        found[kind]={"trade_date":day,"status":data["status"],"data":data,"identity":C.digest({"id":o.observation_id,"hash":o.source_payload_hash,"fixture":p["fixture"]}),"fixture":p["fixture"]}
    lake.assert_unchanged()
    if len({x["fixture"] for x in found.values()})>1:raise ValueError("mixed fixture and acquired supplement")
    capital=[found[k] for k in ("margin","industry_flow") if k in found]
    result={}
    if capital:result["capital_extra"]={"trade_date":day,"status":"normal" if len(capital)==2 and all(x["status"]=="normal" for x in capital) else "partial","identity":C.digest([x["identity"] for x in capital]),"data":{k:found[k]["data"] for k in ("margin","industry_flow") if k in found},"fixture":capital[0]["fixture"]}
    if "dragon_tiger"in found:result["dragon_tiger"]=found["dragon_tiger"]
    return result


def collect(kind,day):
    """Explicit internal manual command. Default OFF; no browser/generation caller."""
    C.day(day)
    if kind not in KINDS:raise ValueError("unsupported capture kind")
    if os.environ.get("VR_SHORTLINE_REVIEW_CAPTURE_ENABLED")!="1":raise ValueError("supplement capture disabled")
    root=os.environ.get("VR_FACT_LAKE_ROOT","").strip()
    if not root:raise ValueError("configured initialized archive required")
    import astock
    import trade_calendar
    from fact_lake_store import open_existing_fact_lake
    lake=open_existing_fact_lake(root,readonly=False)
    if kind=="industry_flow":
        if trade_calendar.observation_trade_date_at(datetime.now(timezone.utc).isoformat())!=day:raise ValueError("industry flow is current-session only")
        url="https://push2.eastmoney.com/api/qt/clist/get"
        params={"pn":"1","pz":"100","po":"1","np":"1","fltt":"2","invt":"2","fid":"f62","fs":"m:90+t:2","fields":"f12,f14,f62,f184,f3,f124"}
    else:
        url="https://datacenter-web.eastmoney.com/api/data/v1/get";field="DIM_DATE" if kind=="margin" else "TRADE_DATE"
        params={"reportName":ENDPOINTS[kind],"columns":"ALL","filter":f'({field}=\'{day}\')',"pageNumber":"1","pageSize":"100","source":"WEB","client":"WEB"}
    response=astock.em_get(url,params=params,timeout=15)
    try:
        if response.status_code!=200:raise ValueError("supplement capture transport failed")
        raw=response.content
        if len(raw)>MAX_BYTES:raise ValueError("supplement response oversized")
        return persist_raw(lake,kind,day,raw)
    finally:response.close()
