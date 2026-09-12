"""StockData header PE/PB must come from Eastmoney clist f115/f23.

Tencent gtimg field 39 and Eastmoney dynamic PE (f9) are never the header
contract. Missing TTM is None, never fabricated 0. Offline: no live network.
"""
from __future__ import annotations

import json

import astock


def _quote(*, code="000001", name="测试股", price=11.5, mcap_yi=2200.0, pe_ttm=99.0, pb=7.0):
    return {
        code: {
            "name": name,
            "price": price,
            "mcap_yi": mcap_yi,
            "pe_ttm": pe_ttm,
            "pb": pb,
        }
    }


def _offline(monkeypatch, quote, *, snapshot=None):
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: quote)
    monkeypatch.setattr(astock, "profit_forecast", lambda code: [])
    if snapshot is None:
        monkeypatch.setattr(
            astock,
            "a_share_snapshot",
            lambda: (_ for _ in ()).throw(RuntimeError("a_share_snapshot must not hit the network")),
        )
    else:
        monkeypatch.setattr(astock, "a_share_snapshot", lambda: snapshot)


def _assert_provenance(out: dict) -> None:
    assert out["pe_ttm_source"] == "eastmoney_clist_f115"
    assert out["pb_source"] == "eastmoney_clist_f23"
    assert out["dynamic_pe_used"] is False


def test_header_pe_uses_snapshot_f115_not_tencent_39(monkeypatch):
    _offline(
        monkeypatch,
        _quote(pe_ttm=99.0, pb=7.0),
        snapshot=[{"code": "000001", "name": "测试股", "pe_ttm": 10.0, "pb": 1.2}],
    )
    out = astock.full_valuation("000001")
    assert out["pe_ttm"] == 10.0
    assert out["pe_ttm"] != 99.0
    assert out["pb"] == 1.2
    assert out["pb"] != 7.0
    assert out["price"] == 11.5
    _assert_provenance(out)


def test_missing_snapshot_f115_is_none_not_tencent_zero(monkeypatch):
    _offline(monkeypatch, _quote(pe_ttm=0.0, pb=0.0))
    out = astock.full_valuation(
        "000001",
        snapshot_reader=lambda: [{"code": "000001", "name": "测试股", "pe_ttm": None, "pb": None}],
    )
    assert out["pe_ttm"] is None
    assert out["pb"] is None
    assert out["pe_ttm"] != 0
    assert out["pe_ttm"] != 0.0
    _assert_provenance(out)


def test_mapped_raw_row_uses_f115_not_dynamic_f9(monkeypatch):
    _offline(monkeypatch, _quote(pe_ttm=99.0))
    raw = {
        "f12": "000001",
        "f14": "测试股",
        "f13": 0,
        "f9": 100,
        "f115": 10,
        "f23": 1.5,
    }
    mapped = astock._map_a_share_row(raw)
    assert mapped is not None
    assert mapped["pe_ttm"] == 10.0
    assert mapped["pb"] == 1.5
    out = astock.full_valuation("000001", snapshot_reader=lambda: [mapped])
    assert out["pe_ttm"] == 10.0
    assert out["pe_ttm"] != 100
    assert out["pe_ttm"] != 99.0
    assert out["pb"] == 1.5
    _assert_provenance(out)


def test_snapshot_raise_pe_none_price_still_from_tencent(monkeypatch):
    _offline(monkeypatch, _quote(pe_ttm=99.0, price=11.5, name="平安银行"))

    def boom():
        raise RuntimeError("snapshot down")

    out = astock.full_valuation("000001", snapshot_reader=boom)
    assert out["pe_ttm"] is None
    assert out["pb"] is None
    assert out["price"] == 11.5
    assert out["name"] == "平安银行"
    _assert_provenance(out)


def test_full_valuation_payload_has_no_buy_sell(monkeypatch):
    _offline(
        monkeypatch,
        _quote(pe_ttm=99.0),
        snapshot=[{"code": "000001", "name": "测试股", "pe_ttm": 10.0, "pb": 1.0}],
    )
    out = astock.full_valuation("000001")
    blob = json.dumps(out, ensure_ascii=False).upper()
    assert "BUY" not in blob
    assert "SELL" not in blob
    _assert_provenance(out)
