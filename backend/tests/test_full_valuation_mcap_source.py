"""StockData header 总市值 must come from Eastmoney clist f20 (元→亿).

Tencent gtimg field 44 is never the header contract. Missing market cap is
None, never fabricated 0. Offline: no live network.
"""
from __future__ import annotations

import json
import math

import pytest

import astock

# Eastmoney f20 is 元; header mcap_yi is 亿.
_MCAP_YUAN = 5085296143
_MCAP_YI = _MCAP_YUAN / 1e8


def _quote(*, code="000001", name="测试股", price=11.5, mcap_yi=0.0, pe_ttm=99.0, pb=7.0):
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
    assert out["mcap_source"] == "eastmoney_clist_f20"
    assert out["dynamic_pe_used"] is False


def _assert_not_zero_mcap(out: dict) -> None:
    assert out["mcap_yi"] is None
    assert out["mcap_yi"] != 0
    assert out["mcap_yi"] != 0.0


def test_header_mcap_uses_snapshot_f20_not_tencent_44(monkeypatch):
    _offline(
        monkeypatch,
        _quote(mcap_yi=0.0, pe_ttm=99.0, pb=7.0),
        snapshot=[{
            "code": "000001",
            "name": "测试股",
            "pe_ttm": 10.0,
            "pb": 1.2,
            "market_cap": _MCAP_YUAN,
        }],
    )
    out = astock.full_valuation("000001")
    assert out["mcap_yi"] == pytest.approx(_MCAP_YI)
    assert out["mcap_yi"] != 0
    assert out["mcap_yi"] != 0.0
    assert out["pe_ttm"] == 10.0
    assert out["pe_ttm"] != 99.0
    assert out["pb"] == 1.2
    assert out["pb"] != 7.0
    assert out["price"] == 11.5
    _assert_provenance(out)


def test_missing_snapshot_market_cap_is_none_not_tencent_zero(monkeypatch):
    _offline(monkeypatch, _quote(mcap_yi=0.0, pe_ttm=0.0, pb=0.0))
    out = astock.full_valuation(
        "000001",
        snapshot_reader=lambda: [{
            "code": "000001",
            "name": "测试股",
            "pe_ttm": None,
            "pb": None,
            "market_cap": None,
        }],
    )
    _assert_not_zero_mcap(out)
    assert out["pe_ttm"] is None
    assert out["pb"] is None
    _assert_provenance(out)


def test_missing_market_cap_field_is_none_not_tencent(monkeypatch):
    _offline(monkeypatch, _quote(mcap_yi=88.0))
    out = astock.full_valuation(
        "000001",
        snapshot_reader=lambda: [{"code": "000001", "name": "测试股", "pe_ttm": 10.0, "pb": 1.0}],
    )
    _assert_not_zero_mcap(out)
    assert out["pe_ttm"] == 10.0
    _assert_provenance(out)


def test_missing_code_in_snapshot_mcap_none_not_tencent(monkeypatch):
    _offline(monkeypatch, _quote(mcap_yi=0.0))
    out = astock.full_valuation(
        "000001",
        snapshot_reader=lambda: [{
            "code": "000002",
            "name": "别的股",
            "pe_ttm": 10.0,
            "pb": 1.0,
            "market_cap": _MCAP_YUAN,
        }],
    )
    _assert_not_zero_mcap(out)
    assert out["pe_ttm"] is None
    assert out["pb"] is None
    _assert_provenance(out)


def test_invalid_snapshot_market_cap_is_none(monkeypatch):
    _offline(monkeypatch, _quote(mcap_yi=0.0))
    for bad in ("-", "--", "", "abc", math.nan, math.inf):
        out = astock.full_valuation(
            "000001",
            snapshot_reader=lambda bad=bad: [{
                "code": "000001",
                "name": "测试股",
                "market_cap": bad,
            }],
        )
        _assert_not_zero_mcap(out)
        _assert_provenance(out)


def test_mapped_raw_row_uses_f20_not_tencent_44(monkeypatch):
    _offline(monkeypatch, _quote(mcap_yi=0.0, pe_ttm=99.0))
    raw = {
        "f12": "000001",
        "f14": "测试股",
        "f13": 0,
        "f9": 100,
        "f115": 10,
        "f23": 1.5,
        "f20": _MCAP_YUAN,
    }
    mapped = astock._map_a_share_row(raw)
    assert mapped is not None
    assert mapped["market_cap"] == pytest.approx(float(_MCAP_YUAN))
    assert mapped["pe_ttm"] == 10.0
    assert mapped["pb"] == 1.5
    out = astock.full_valuation("000001", snapshot_reader=lambda: [mapped])
    assert out["mcap_yi"] == pytest.approx(_MCAP_YI)
    assert out["mcap_yi"] != 0
    assert out["pe_ttm"] == 10.0
    assert out["pe_ttm"] != 100
    assert out["pe_ttm"] != 99.0
    assert out["pb"] == 1.5
    _assert_provenance(out)


def test_snapshot_raise_mcap_none_price_still_from_tencent(monkeypatch):
    _offline(monkeypatch, _quote(mcap_yi=0.0, pe_ttm=99.0, price=11.5, name="平安银行"))

    def boom():
        raise RuntimeError("snapshot down")

    out = astock.full_valuation("000001", snapshot_reader=boom)
    _assert_not_zero_mcap(out)
    assert out["pe_ttm"] is None
    assert out["pb"] is None
    assert out["price"] == 11.5
    assert out["name"] == "平安银行"
    _assert_provenance(out)


def test_full_valuation_mcap_payload_has_no_buy_sell(monkeypatch):
    _offline(
        monkeypatch,
        _quote(mcap_yi=0.0, pe_ttm=99.0),
        snapshot=[{
            "code": "000001",
            "name": "测试股",
            "pe_ttm": 10.0,
            "pb": 1.0,
            "market_cap": _MCAP_YUAN,
        }],
    )
    out = astock.full_valuation("000001")
    blob = json.dumps(out, ensure_ascii=False).upper()
    assert "BUY" not in blob
    assert "SELL" not in blob
    assert out["mcap_yi"] == pytest.approx(_MCAP_YI)
    _assert_provenance(out)
