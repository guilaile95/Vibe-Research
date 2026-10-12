import json
import pytest
import shortline_review_supplement as S
DAY="2026-07-23"

def raw(kind,**row):
    if kind=="industry_flow":return json.dumps({"rc":0,"data":{"total":1,"diff":[row]}}).encode()
    return json.dumps({"success":True,"code":0,"result":{"count":1,"data":[row]}}).encode()


def test_market_margin_exact_date_and_missing_numbers_not_zero():
    value=S.normalize(raw("margin",DIM_DATE=DAY,RZRQYE=100),"margin",DAY)
    assert value["rows"][0]["margin_balance_yuan"]==100
    assert value["rows"][0]["financing_net_yuan"]is None
    assert S.normalize(raw("margin",DIM_DATE="2026-07-22",RZRQYE=100),"margin",DAY)["rows"]==[]


def test_board_timestamp_must_prove_business_date_not_capture_date():
    value=S.normalize(raw("industry_flow",f12="BK01",f14="fixture",f62=20),"industry_flow",DAY)
    assert value["rows"]==[] and value["status"]=="partial"


def test_dragon_rows_exact_date_and_no_duplicate_total_inference():
    value=S.normalize(raw("dragon_tiger",TRADE_DATE=DAY,SECURITY_CODE="600001",BILLBOARD_NET_AMT=0),"dragon_tiger",DAY)
    assert value["rows"][0]["billboard_net_yuan"]==0
    value=S.normalize(raw("dragon_tiger",TRADE_DATE="2026-07-22",SECURITY_CODE="600001"),"dragon_tiger",DAY)
    assert value["rows"]==[]


def test_disabled_capture_never_opens_archive_or_requests_provider(monkeypatch):
    monkeypatch.delenv("VR_SHORTLINE_REVIEW_CAPTURE_ENABLED",raising=False)
    import astock
    monkeypatch.setattr(astock,"em_get",lambda *_a,**_k:pytest.fail("provider must not run"))
    with pytest.raises(ValueError,match="disabled"):S.collect("margin",DAY)

@pytest.mark.parametrize("payload",[b"{}",b"[]",b"{\"success\":false,\"code\":0}",b"{\"success\":true,\"code\":9501,\"result\":{\"data\":[]}}"])
def test_bad_provider_responses_are_not_empty_success(payload):
    with pytest.raises(ValueError):S.normalize(payload,"margin",DAY)


def test_ambiguous_and_nonfinite_json_is_rejected():
    for payload in [b'{"success":true,"success":false}',b'{"v":NaN}']:
        with pytest.raises(ValueError):S.normalize(payload,"margin",DAY)


def test_missing_principal_value_is_partial_not_full():
    value=S.normalize(raw("margin",DIM_DATE=DAY),"margin",DAY)
    assert value["status"]=="partial"


def test_failed_normalization_retains_invalid_raw_receipt():
    class Sink:
        def store_observation(self,*args):self.args=args
    sink=Sink();data=b'{"success":false}'
    result=S.persist_raw(sink,'margin',DAY,data,fixture=True)
    assert result['status']=='invalid'
    observation,raw_bytes,mime=sink.args
    assert raw_bytes==data and observation.reason_codes==('NORMALIZATION_FAILED',)
    assert observation.quality_status.value=='invalid'


def test_selection_cap_and_same_time_conflict_fail_closed(monkeypatch):
    from types import SimpleNamespace
    import fact_lake_store
    def observation(h):return SimpleNamespace(observation=SimpleNamespace(fetched_at='2026-07-23T08:00:00+00:00',source_payload_hash=h,payload={}))
    class Lake:
        def list_observations(self,**kwargs):return self.rows
    lake=Lake();monkeypatch.setenv('VR_FACT_LAKE_ROOT','synthetic-only')
    monkeypatch.setattr(fact_lake_store,'open_existing_fact_lake_snapshot',lambda *_:lake,raising=False)
    lake.rows=[observation('a')]*100
    with pytest.raises(ValueError,match='cap'):S.query_supplements(DAY)
    lake.rows=[observation('a'),observation('b')]
    with pytest.raises(ValueError,match='ambiguous'):S.query_supplements(DAY)


def test_real_factlake_retains_valid_and_failed_raw_receipts(tmp_path):
    from fact_lake_store import initialize_fact_lake
    lake=initialize_fact_lake(tmp_path/'archive')
    for payload in (raw('margin',DIM_DATE=DAY,RZRQYE=100),b'{"success":false}'):
        result=S.persist_raw(lake,'margin',DAY,payload,fixture=True)
        assert lake.read_payload(result['observation_id'])==payload


@pytest.mark.parametrize('stamp',['2026-07-23T08:00:00+01:60','2026-02-30T08:00:00Z','2026-07-23T24:00:00Z'])
def test_noncanonical_timestamps_rejected_before_receipt_write(stamp):
    class Sink:
        def store_observation(self,*_):pytest.fail('invalid timestamp cannot write')
    with pytest.raises(ValueError):S.persist_raw(Sink(),'margin',DAY,raw('margin',DIM_DATE=DAY,RZRQYE=100),captured_at=stamp)
