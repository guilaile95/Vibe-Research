import json
import multiprocessing
import time
from unittest.mock import patch

import pytest
import public_data_budget as budget


def stuck(path, operation, code):
    while True:
        time.sleep(1)


def success(path, operation, code):
    budget._write_result(path, {"code": code, "price": None})


def invalid(path, operation, code):
    with open(path, "wb") as f:
        f.write(b"not json")


def test_real_spawn_timeout_kills_reaps_and_releases_slot():
    before = {p.pid for p in multiprocessing.active_children()}
    start = time.monotonic()
    with pytest.raises(budget.PublicDataUnavailable, match="SOURCE_TIMEOUT"):
        budget.run("valuation", "600000", timeout=.2, _target=stuck)
    assert time.monotonic() - start < 3
    assert {p.pid for p in multiprocessing.active_children()} == before
    assert budget.run("valuation", "600000", timeout=3, _target=success) == {"code": "600000", "price": None}


def test_invalid_worker_and_busy_are_bounded():
    with pytest.raises(budget.PublicDataUnavailable, match="SOURCE_BAD_RESPONSE"):
        budget.run("overview", timeout=3, _target=invalid)
    for _ in range(4):
        assert budget._SLOTS.acquire(False)
    try:
        with pytest.raises(budget.PublicDataUnavailable, match="SOURCE_BUSY"), patch.object(budget.multiprocessing, "get_context", side_effect=AssertionError("must not spawn")):
            budget.run("overview")
    finally:
        for _ in range(4):
            budget._SLOTS.release()


def test_endpoint_fallbacks_have_null_values_and_explicit_failure(monkeypatch):
    import app
    monkeypatch.setattr(budget, "run", lambda *a, **k: (_ for _ in ()).throw(budget.PublicDataUnavailable("SOURCE_TIMEOUT")))
    overview = app.market_overview()["data"]
    assert overview["status"] == "unavailable" and overview["sentiment"]["up"] is None
    assert overview["updated"] is None and overview["reason_code"] == "SOURCE_TIMEOUT"
    valuation = app.valuation("600000")["data"]
    assert valuation["price"] is None and valuation["pe_ttm"] is None
    assert valuation["status"] == "unavailable" and valuation["analyst_count"] is None
    monkeypatch.setattr(app, "_FIN_CACHE", app.TTLCache())
    with pytest.raises(app.HTTPException) as caught:
        app.financials("600000")
    assert caught.value.status_code == 503
    assert "同花顺" in caught.value.detail


def test_forecast_failure_preserves_quote(monkeypatch):
    import astock
    monkeypatch.setattr(astock, "tencent_quote", lambda c: {"600000": {"price": 10, "name": "fixture"}})
    monkeypatch.setattr(astock, "profit_forecast", lambda c: (_ for _ in ()).throw(RuntimeError("private provider")))
    value = astock.full_valuation("600000", valuation_reader=lambda c: {})
    assert value["price"] == 10 and value["eps_26e"] is None
    assert "暂不可用" in value["forecast_note"] and "private" not in value["forecast_note"]


def partial_write_stall(path, operation, code):
    with open(path, "wb") as handle:
        handle.write(b'{"data":')
        handle.flush()
        time.sleep(60)


def test_partial_result_write_cannot_escape_deadline():
    with pytest.raises(budget.PublicDataUnavailable, match="SOURCE_TIMEOUT"):
        budget.run("overview", timeout=.3, _target=partial_write_stall)


def test_setup_failure_does_not_leak_capacity(monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(budget.multiprocessing, "get_context", lambda *a: (_ for _ in ()).throw(OSError("setup")))
        for _ in range(6):
            with pytest.raises(OSError):
                budget.run("overview", _target=success)
    assert budget.run("overview", timeout=3, _target=success)["price"] is None


def checkpoint_stall(path, operation, code):
    budget._write_result(path + ".checkpoint", {"code": code, "price": 10, "status": "partial", "reason_code": "SOURCE_TIMEOUT"})
    time.sleep(60)


def test_quote_checkpoint_survives_slow_forecast_and_worker_is_reaped():
    before = {p.pid for p in multiprocessing.active_children()}
    value = budget.run("valuation", "600000", timeout=.5, _target=checkpoint_stall)
    assert value["price"] == 10 and value["status"] == "partial"
    assert {p.pid for p in multiprocessing.active_children()} == before


def test_start_failure_releases_capacity(monkeypatch):
    from unittest.mock import Mock
    process=Mock()
    process.start.side_effect=OSError("start failed")
    with monkeypatch.context() as m:
        m.setattr(budget.multiprocessing,"get_context",lambda *a:Mock(Process=Mock(return_value=process)))
        for _ in range(6):
            with pytest.raises(OSError):budget.run("overview",_target=success)
    assert budget.run("overview",timeout=3,_target=success)["price"] is None


def test_cache_is_defensive_bounded_and_missing_results_do_not_stick(monkeypatch):
    budget._CACHE.clear();budget._INFLIGHT.clear()
    calls=[]
    def worker(op,code,**kw):calls.append(code);return {"price":10,"code":code}
    monkeypatch.setattr(budget,"_run_process",worker)
    a=budget.run("valuation","600000");a["price"]=999
    assert budget.run("valuation","600000")["price"]==10 and len(calls)==1
    budget._INFLIGHT.add(("overview",None))
    with pytest.raises(budget.PublicDataUnavailable,match="SOURCE_BUSY"):budget.run("overview")
    budget._INFLIGHT.clear()
    monkeypatch.setattr(budget,"_run_process",lambda *a,**kw:{"price":None})
    budget.run("valuation","600001")
    assert ("valuation","600001") not in budget._CACHE
    budget._CACHE.clear()


def real_valuation_stuck_em(path, operation, code):
    import astock
    astock.tencent_quote=lambda codes:{code:{"name":"synthetic", "price":10,"data_time":"2026-07-31T15:00:00+08:00","trade_date":"2026-07-31"}}
    def hold(code):time.sleep(60)
    astock.eastmoney_stock_valuation=hold
    budget._child(path,operation,code)


def test_actual_valuation_retains_tencent_before_slow_eastmoney():
    value=budget.run("valuation","600000",timeout=1,_target=real_valuation_stuck_em)
    assert value["price"]==10 and value["quote_trade_date"]=="2026-07-31"
    assert value["pe_ttm"] is None and value["mcap_yi"] is None
    assert value["status"]=="partial" and value["analyst_count"] is None


def checkpoint_then_failure(path, operation, code):
    budget._write_result(path + ".checkpoint", {"code": code,"price": 10,"status":"partial","reason_code":"SOURCE_TIMEOUT"})


def test_partial_checkpoint_survives_failed_optional_stage_without_timeout_claim():
    value=budget.run("valuation","600000",timeout=3,_target=checkpoint_then_failure)
    assert value["price"]==10 and value["reason_code"]=="SOURCE_UNAVAILABLE"


def test_empty_financial_worker_is_unavailable_not_success(monkeypatch,tmp_path):
    import astock
    monkeypatch.setattr(astock,"financials",lambda *a,**kw:{})
    path=tmp_path/"result.json"
    budget._child(str(path),"financials","600000")
    assert not path.exists()
