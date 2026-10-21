import copy
import pytest
import astock
import daily_review as review


def envelope():
    return {"status": "normal", "data": [{"code": c, "data_time": "2026-07-31T15:00:00+08:00", "trade_date": "2026-07-31"} for c in astock.A_INDICES]}


def test_source_dates_agree_without_collection_day_fallback():
    assert review._index_source_trade_date(envelope()) == "2026-07-31"
    assert review._index_source_trade_date({"status": "normal", "data": [{"name": "legacy"}]}) is None


@pytest.mark.parametrize("field,value", [("trade_date", "2026-07-30"), ("data_time", "2026-02-30T15:00:00+08:00"),
    ("data_time", "2026-07-31T15:00:00"), ("data_time", "2099-07-31T15:00:00+08:00"),
    ("data_time", "0000-07-31T15:00:00+08:00"), ("code", "unknown")])
def test_invalid_or_mixed_source_date_is_unknown(field,value):
    e=envelope();e["data"][0][field]=value
    assert review._index_source_trade_date(e) is None


def test_weekend_and_preopen_source_time_is_not_promoted():
    for stamp,day in [("2026-08-01T15:00:00+08:00","2026-08-01"),("2026-07-31T09:00:00+08:00","2026-07-31")]:
        e=envelope()
        for row in e["data"]:row.update(data_time=stamp,trade_date=day)
        assert review._index_source_trade_date(e) is None


def test_index_adapter_preserves_source_identity(monkeypatch):
    monkeypatch.setattr(astock, "_fetch_gtimg", lambda c: "fixture")
    monkeypatch.setattr(astock, "_parse_gtimg", lambda x: {"000001": {"name":"index","price":1,"change_pct":None,"change_amt":None,"data_time":"2026-07-31T15:00:00+08:00","trade_date":"2026-07-31"}})
    row=astock.index_quote()[0]
    assert row["code"]=="sh000001" and row["trade_date"]=="2026-07-31"


def test_actual_daily_builder_and_history_keep_unknown_breadth(monkeypatch, tmp_path):
    from test_daily_review import _install_all_ok, _breadth_env
    import review_history
    _install_all_ok(monkeypatch, emotion_date=None)
    rows=envelope()["data"]
    for row in rows:row.update(name="synthetic index",price=100,change_pct=0,change_amt=0)
    monkeypatch.setattr(astock,"index_quote",lambda:rows)
    monkeypatch.setattr(review.market,"get_market_breadth",lambda:_breadth_env(status="unavailable"))
    value=review._build_daily_review()
    assert value["trade_date"]=="2026-07-31"
    assert value["trade_date_basis"]=="tencent_index_source_time"
    assert value["market_environment"]["breadth"]["data"] is None
    assert value["status"]=="partial" and value["data_cutoff"] is None
    monkeypatch.setattr(review,"generate_daily_review",lambda:value)
    saved=review_history.save_current_daily_review(tmp_path/"history.db")
    assert saved["snapshot"]["trade_date"]=="2026-07-31"
    assert saved["review_status"]=="partial"


@pytest.fixture(autouse=True)
def _source_mocked_assembly(monkeypatch):
    # These tests inject provider results in this process. Production collection
    # is verified separately with disposable synthetic workers.
    import daily_review as _review
    monkeypatch.setattr(_review, "_build_daily_review",
        lambda: _review._assemble_daily_review(None, _test_provider_calls=True))
