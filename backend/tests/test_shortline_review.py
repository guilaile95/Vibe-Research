"""Offline model stubs, temporary stores and scoped evidence for P5."""
import copy
import json
import threading
import pytest
import shortline_review_contract as C
import shortline_review_sources as sources
import shortline_review_service as service
import shortline_review_store as store

DAY="2026-07-23"

def inputs(day):
    return {key:("a"*64,{"count":5,"stock_code":"600001","account":{"assets":999},"warnings":["secret"]},"normal") for key in ("sentiment","capital","capital_extra","theme","dragon_tiger","leader")}

def bundle(mode="daily"):
    return sources.build_bundle(DAY,mode,sources=inputs,verify=lambda d:("b"*64,{"decided":2},"normal"),dates=lambda end,m:[end])

def model(calls,bad=False):
    def stream(cfg,messages,**kwargs):
        body=json.loads(messages[1]["content"]);calls.append((cfg,body))
        assert kwargs=={"use_tools":False}
        text="需要继续观察["+body["evidence"][0]["id"]+"]"
        if bad and body["section"]=="sentiment":text="错误引用[ev-unknown]"
        yield {"type":"delta","text":text};yield {"type":"done"}
    return stream

@pytest.fixture
def db(tmp_path,monkeypatch):
    p=tmp_path/"review.sqlite3";monkeypatch.setattr(store.review_history,"resolve_review_db_path",lambda:p);return p


def test_sections_are_scoped_and_private_fields_excluded():
    b=bundle();C.validate_bundle(b)
    assert len(b["sections"])==5
    text=C.canonical(b)
    assert "assets" not in text and "secret" not in text
    assert set(e["source"] for e in b["sections"][0]["evidence"])=={"sentiment"}
    bad=copy.deepcopy(b);bad["canonical_authority"]=0
    with pytest.raises(ValueError):C.validate_bundle(bad)


def test_day_and_week_budget_version_immutability_and_no_secrets(db):
    for mode,cost in [("daily",6),("weekly",4)]:
        calls=[];b=bundle(mode);identity=("a" if mode=="daily" else "b")*32
        ev=list(service.generate(b,identity,{"provider":"fixture","model":"fixture","apiKey":"secret-key"},threading.Event(),stream=model(calls)))
        assert ev[-1]["type"]=="done" and ev[-1]["model_calls"]==cost and len(calls)==cost
        assert len({cfg["_session"] for cfg,_ in calls})==cost
        saved=store.get_version(identity);assert saved["bundle"]==b
        assert "secret-key" not in C.canonical(saved)
        assert saved["fact_verification"]=="NOT_PERFORMED"
        assert store.append_version(saved)==saved
        assert len(store.list_versions(DAY,mode))==1
        _,same=service.prepare(DAY,mode,b["bundle_id"],identity);assert same==saved
    assert len(store.list_versions(DAY,"daily"))==1


def test_audit_issue_never_enters_summary_as_validated_section(db):
    calls=[];events=list(service.generate(bundle(),"c"*32,{"model":"fixture"},threading.Event(),stream=model(calls,True)))
    assert events[-1]["status"]=="requires_review"
    summary=calls[-1][1]
    assert "sentiment" not in [s["id"] for s in summary["untrusted_prior_sections"]]
    assert "ev-unknown" not in C.canonical(summary)
    assert "SENTIMENT:REQUIRES_REVIEW" in summary["missing_inputs"]
    saved=store.get_version("c"*32);saved["stages"][0]["status"]="generated"
    with pytest.raises(ValueError):store.validate_version(saved)


def test_empty_inputs_do_not_call_model_or_create_database(db,monkeypatch):
    b=sources.build_bundle(DAY,"daily",sources=lambda d:{},dates=lambda d,m:[d])
    monkeypatch.setattr(sources,"build_bundle",lambda *_:b)
    with pytest.raises(ValueError):service.prepare(DAY,"daily",b["bundle_id"],"d"*32)
    assert not db.exists()


def test_incomplete_stream_or_cancel_never_commits(db):
    def incomplete(*_args,**_kw):yield {"type":"delta","text":"partial"}
    events=list(service.generate(bundle(),"e"*32,{},threading.Event(),stream=incomplete))
    assert events[-1]["type"]=="error" and not db.exists()
    cancel=threading.Event()
    def cancelled(*_args,**_kw):
        cancel.set();yield {"type":"done"}
    list(service.generate(bundle(),"f"*32,{},cancel,stream=cancelled))
    assert not db.exists()


def test_preview_change_and_duplicate_active_fail_before_model(db,monkeypatch):
    b=bundle()
    monkeypatch.setattr(sources,"build_bundle",lambda *_:b)
    with pytest.raises(ValueError):service.prepare(DAY,"daily","0"*64,"1"*32)
    service.acquire("1"*32)
    try:
        with pytest.raises(RuntimeError):service.acquire("1"*32)
    finally:service.release("1"*32)


def test_append_cancellation_rolls_back_and_preserves_old_version(db):
    events=list(service.generate(bundle(),"2"*32,{"model":"fixture"},threading.Event(),stream=model([])))
    old=store.get_version("2"*32);new=copy.deepcopy(old);new["generation_id"]="3"*32
    n=0
    def cancel():
        nonlocal n;n+=1;return n>=2
    with pytest.raises(ValueError):store.append_version(new,cancel)
    assert store.get_version("3"*32)is None and store.get_version("2"*32)==old


def test_readonly_missing_paths_do_not_create_anything(tmp_path,monkeypatch):
    p=tmp_path/"missing"/"review.sqlite3";monkeypatch.setattr(store.review_history,"resolve_review_db_path",lambda:p)
    assert store.list_versions(DAY,"daily")==[] and store.read_daily_snapshot(DAY)is None
    assert not p.parent.exists()


def test_stage_deadline_signals_existing_runtime_and_never_saves(db,monkeypatch):
    monkeypatch.setattr(C,"MAX_STAGE_SECONDS",0.01)
    observed=[]
    def blocked(cfg,*_args,**_kw):
        observed.append(cfg["_cancel_event"].wait(1))
        yield {"type":"done"}
    list(service.generate(bundle(),"4"*32,{},threading.Event(),stream=blocked))
    assert observed==[True] and not db.exists()


def test_output_limit_has_no_retry_or_partial_version(db):
    calls=[]
    def oversized(*_args,**_kw):
        calls.append(1);yield {"type":"delta","text":"x"*(C.MAX_SECTION_CHARS+1)};yield {"type":"done"}
    events=list(service.generate(bundle(),"5"*32,{},threading.Event(),stream=oversized))
    assert calls==[1] and events[-1]["type"]=="error" and not db.exists()


def test_version_read_is_side_effect_free_and_corrupt_hash_rejected(db):
    import sqlite3
    list(service.generate(bundle(),"6"*32,{},threading.Event(),stream=model([])))
    before={p.name:p.read_bytes()for p in db.parent.iterdir()}
    assert store.get_version("6"*32)
    assert {p.name:p.read_bytes()for p in db.parent.iterdir()}==before
    with sqlite3.connect(db)as conn:conn.execute("UPDATE shortline_review_versions SET payload_hash='broken'")
    with pytest.raises(ValueError):store.get_version("6"*32)


def test_projection_truncates_only_whole_evidence_rows():
    huge={"items":[{"stock_code":str(600000+i),"count":i,"name":"长"*120}for i in range(300)]}
    b=sources.build_bundle(DAY,"daily",sources=lambda d:{"sentiment":("a"*64,huge,"normal","FIXTURE")},dates=lambda d,m:[d])
    C.validate_bundle(b);s=b["sections"][0]
    assert s["omitted_count"]>0 and len(C.canonical(s).encode())<=C.MAX_SECTION_INPUT_BYTES
    assert all(e["origin"]=="FIXTURE" for e in s["evidence"])


def test_weekly_verification_allowlist_drops_user_reason_and_private_fields(monkeypatch):
    v={"trade_date":DAY,"revision":3,"summary":{"decided":1},"items":[{"metric":"limit_up_count","direction":"up","current_value":5,"reason":"private thought","account":{"asset":999}}],"portfolio":{"secret":123}}
    monkeypatch.setattr(sources,"_query",lambda *_:v)
    result=sources.verification_source(DAY)
    assert "private" not in C.canonical(result) and "asset" not in C.canonical(result) and "portfolio" not in C.canonical(result)


def test_real_theme_status_and_fixture_location_are_consumed(monkeypatch):
    value={"schema_version":"short-term-theme-research-archive-v1","trade_date":DAY,"status":"complete","archive_only":True,"ingestion_enabled":False,"selection_mode":"CURRENT_STORED_POSTHOC","point_in_time_claim":"NONE","projection":{"canonical_authority":False,"fixture":True,"tree":[{"tag":"synthetic","count":2}],"days":[]}}
    monkeypatch.setattr(sources,"_query",lambda module,*_:value if module=="short_term_theme_research_service"else None)
    monkeypatch.setattr(store,"read_daily_snapshot",lambda *_:None)
    observed=sources.market_sources(DAY)
    assert observed["theme"][2:]==("normal","FIXTURE")


def test_actual_verification_fields_and_week_cutoff_are_preserved(monkeypatch):
    value={"trade_date":"2026-07-22","items":[{"metric":"limit_up_count","direction":"up","actual":"down","state":"VERIFIED","target_date":DAY,"prior_value":10,"current_value":5,"verified":False,"reason":"private"}]}
    monkeypatch.setattr(sources,"_query",lambda *_:value)
    identity,data,status=sources.verification_source("2026-07-22",DAY)
    assert data["items"][0]["actual"]=="down" and data["items"][0]["verdict"]=="FALSE"
    assert data["summary"]["decided"]==1 and data["summary"]["hit"]==0
    value["items"][0]["target_date"]="2026-07-24"
    assert sources.verification_source("2026-07-22",DAY)[2]=="OUTSIDE_WEEK"
    value["items"]=[]
    assert sources.verification_source("2026-07-22",DAY)[2]=="NO_CONDITIONS"


def test_nulls_remain_explicit_path_evidence_and_all_null_is_not_usable(db,monkeypatch):
    b=sources.build_bundle(DAY,"daily",sources=lambda d:{"sentiment":("a"*64,{"value":None},"partial")},dates=lambda d,m:[d])
    e=b["sections"][0]["evidence"][0]
    assert e["path"]=="sentiment.value" and e["value"]is None
    monkeypatch.setattr(sources,"build_bundle",lambda *_:b)
    with pytest.raises(ValueError,match="no usable"):service.prepare(DAY,"daily",b["bundle_id"],"7"*32)


def test_dense_week_keeps_every_day_with_explicit_omissions():
    days=['2026-07-20','2026-07-21','2026-07-22',DAY]
    def dense(d):return {k:('a'*64,{'rows':[{'count':i}for i in range(200)]},'normal')for k in ('sentiment','theme')}
    b=sources.build_bundle(DAY,'weekly',sources=dense,verify=lambda d:None,dates=lambda *_:days)
    for section in b['sections'][:2]:
        assert {e['trade_date'] for e in section['evidence']}==set(days)
        assert all(any(d in gap and 'OMITTED_' in gap for gap in section['gaps'])for d in days)


def test_summary_prompt_has_independent_byte_bound():
    b=bundle();section=b['sections'][0]
    with pytest.raises(ValueError,match='bounded prompt'):
        service._messages(b,section,[{'text':'巨'*C.MAX_PROMPT_BYTES}])


def test_sqlite_header_modes_and_page_size_rejected(db):
    import sqlite3
    with sqlite3.connect(db)as conn:conn.execute('create table x(a)')
    raw=db.read_bytes()
    for index,value in ((18,9),(16,3)):
        bad=bytearray(raw);bad[index]=value;db.write_bytes(bad)
        with pytest.raises(ValueError):store.read_image()
    db.write_bytes(raw)
    conn=store.read_image();assert conn.execute('PRAGMA trusted_schema').fetchone()[0]==0;conn.close()
