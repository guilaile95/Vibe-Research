"""全 A 股行情快照 a_share_snapshot 离线测试（全部 Mock 网络，不打真实东财）。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import astock


def _row(
    code="600519",
    name="贵州茅台",
    *,
    f2=1700.0,
    f3=1.25,
    f4=21.0,
    f5=10000.0,
    f6=1.7e9,
    f7=2.1,
    f8=0.5,
    f13=1,
    f15=1710.0,
    f16=1680.0,
    f17=1690.0,
    f18=1679.0,
    f20=2.1e12,
    f21=2.0e12,
    f100="白酒",
    **extra,
):
    d = {
        "f2": f2, "f3": f3, "f4": f4, "f5": f5, "f6": f6, "f7": f7, "f8": f8,
        "f12": code, "f13": f13, "f14": name,
        "f15": f15, "f16": f16, "f17": f17, "f18": f18,
        "f20": f20, "f21": f21, "f100": f100,
    }
    d.update(extra)
    return d


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        if isinstance(self._payload, str):
            return json.loads(self._payload)
        return self._payload


def _install_em_get(monkeypatch, handler):
    """handler(url, params) -> payload dict or raises."""
    calls: list[dict] = []

    def fake_em_get(url, params=None, headers=None, timeout=15):
        calls.append({"url": url, "params": dict(params or {}), "headers": headers, "timeout": timeout})
        return _FakeResp(handler(url, params or {}))

    monkeypatch.setattr(astock, "em_get", fake_em_get)
    # 避免测试触发真实限流 sleep
    monkeypatch.setattr(astock, "_EM_MIN_INTERVAL", 0)
    monkeypatch.setattr(astock, "_em_last_call", [0.0])
    return calls


# ── 1. 单页 list 格式 ───────────────────────────────────────────────

def test_snapshot_single_page_list(monkeypatch):
    rows = [
        _row("600519", "贵州茅台", f2=1700.5, f3=1.2),
        _row("000001", "平安银行", f2=11.5, f3=-0.5, f13=0),
    ]

    def handler(url, params):
        assert "clist/get" in url
        assert params["pn"] == "1"
        assert params["pz"] == "500"
        assert "f12" in params["fields"] and "f2" in params["fields"]
        assert "f100" in params["fields"], "a_share_snapshot 必须请求 f100（行业归属）"
        return {"data": {"total": 2, "diff": rows}}

    calls = _install_em_get(monkeypatch, handler)
    out = astock.a_share_snapshot()
    assert len(calls) == 1
    assert len(out) == 2

    a = out[0]
    assert a["code"] == "600519"
    assert a["name"] == "贵州茅台"
    assert a["market"] == 1
    assert a["price"] == pytest.approx(1700.5)
    assert a["change_pct"] == pytest.approx(1.2)
    assert a["change"] == pytest.approx(21.0)
    assert a["volume"] == pytest.approx(10000.0)
    assert a["amount"] == pytest.approx(1.7e9)
    assert a["amplitude_pct"] == pytest.approx(2.1)
    assert a["turnover_pct"] == pytest.approx(0.5)
    assert a["high"] == pytest.approx(1710.0)
    assert a["low"] == pytest.approx(1680.0)
    assert a["open"] == pytest.approx(1690.0)
    assert a["prev_close"] == pytest.approx(1679.0)
    assert a["market_cap"] == pytest.approx(2.1e12)
    assert a["float_market_cap"] == pytest.approx(2.0e12)
    # f100 → industry 映射（市场云图必需字段）
    assert a["industry"] == "白酒"
    assert set(a.keys()) == {
        "code", "name", "market", "price", "change_pct", "change",
        "volume", "amount", "amplitude_pct", "turnover_pct",
        "high", "low", "open", "prev_close", "market_cap", "float_market_cap",
        "industry",
    }

    b = out[1]
    assert b["code"] == "000001"
    assert b["name"] == "平安银行"
    assert b["market"] == 0
    assert b["change_pct"] == pytest.approx(-0.5)


# ── 2. diff 为 dict 格式 ────────────────────────────────────────────

def test_snapshot_diff_as_dict(monkeypatch):
    diff = {
        "1": _row("000002", "万科A", f2=9.0),
        "0": _row("600000", "浦发银行", f2=8.0),
    }

    def handler(url, params):
        return {"data": {"total": 2, "diff": diff}}

    _install_em_get(monkeypatch, handler)
    out = astock.a_share_snapshot()
    assert len(out) == 2
    # 按数字键排序：0 → 600000，1 → 000002
    assert [x["code"] for x in out] == ["600000", "000002"]
    assert out[0]["price"] == pytest.approx(8.0)
    assert out[1]["name"] == "万科A"


# ── 3. 多页合并 ─────────────────────────────────────────────────────

def test_snapshot_multi_page_merge(monkeypatch):
    page_size = 3
    page1 = [_row(f"60000{i}", f"股{i}") for i in range(3)]
    page2 = [_row("000001", "末页甲"), _row("000002", "末页乙")]

    def handler(url, params):
        pn = int(params["pn"])
        assert params["pz"] == str(page_size)
        if pn == 1:
            return {"data": {"total": 5, "diff": page1}}
        if pn == 2:
            return {"data": {"total": 5, "diff": page2}}
        raise AssertionError(f"unexpected page {pn}")

    calls = _install_em_get(monkeypatch, handler)
    out = astock.a_share_snapshot(page_size=page_size)
    assert len(calls) == 2
    assert [c["params"]["pn"] for c in calls] == ["1", "2"]
    assert len(out) == 5
    codes = [x["code"] for x in out]
    assert codes == ["600000", "600001", "600002", "000001", "000002"]
    assert len(codes) == len(set(codes))  # 不重复


# ── 4. 缺失值清洗 ───────────────────────────────────────────────────

def test_optional_float_and_missing_fields(monkeypatch):
    assert astock._optional_float(None) is None
    assert astock._optional_float("") is None
    assert astock._optional_float("-") is None
    assert astock._optional_float("--") is None
    assert astock._optional_float("abc") is None
    assert astock._optional_float("12.5") == pytest.approx(12.5)
    assert astock._optional_float(0) == pytest.approx(0.0)
    assert astock._optional_float(0.0) == pytest.approx(0.0)
    assert astock._optional_float("0") == pytest.approx(0.0)

    row = _row(
        f2="-", f3="", f4=None, f5="--", f6="12.5", f7=0, f8="0",
        f15="bad", f16=0.0,
    )

    def handler(url, params):
        return {"data": {"total": 1, "diff": [row]}}

    _install_em_get(monkeypatch, handler)
    out = astock.a_share_snapshot()
    assert len(out) == 1
    s = out[0]
    assert s["price"] is None
    assert s["change_pct"] is None
    assert s["change"] is None
    assert s["volume"] is None
    assert s["amount"] == pytest.approx(12.5)
    assert s["amplitude_pct"] == pytest.approx(0.0)
    assert s["turnover_pct"] == pytest.approx(0.0)
    assert s["high"] is None
    assert s["low"] == pytest.approx(0.0)


# ── 5. 异常数据 ─────────────────────────────────────────────────────

def test_snapshot_missing_data_raises(monkeypatch):
    def handler(url, params):
        return {"rc": 0}  # 无 data

    _install_em_get(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="missing data"):
        astock.a_share_snapshot()


def test_snapshot_total_nonzero_empty_first_page_raises(monkeypatch):
    def handler(url, params):
        return {"data": {"total": 100, "diff": []}}

    _install_em_get(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="first page is empty"):
        astock.a_share_snapshot()


def test_snapshot_request_failure_not_empty_list(monkeypatch):
    def handler(url, params):
        raise ConnectionError("network down")

    _install_em_get(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="request failed"):
        astock.a_share_snapshot()


def test_snapshot_invalid_json_raises(monkeypatch):
    calls: list = []

    def fake_em_get(url, params=None, headers=None, timeout=15):
        calls.append(1)

        class Bad:
            def json(self):
                raise ValueError("not json")

        return Bad()

    monkeypatch.setattr(astock, "em_get", fake_em_get)
    monkeypatch.setattr(astock, "_EM_MIN_INTERVAL", 0)
    monkeypatch.setattr(astock, "_em_last_call", [0.0])
    with pytest.raises(RuntimeError, match="invalid JSON"):
        astock.a_share_snapshot()


def test_snapshot_data_null_raises(monkeypatch):
    def handler(url, params):
        return {"data": None}

    _install_em_get(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="missing data"):
        astock.a_share_snapshot()


# ── 6. 无效证券过滤 ─────────────────────────────────────────────────

def test_snapshot_filters_invalid_securities(monkeypatch):
    rows = [
        _row("600519", "贵州茅台"),
        _row("12345", "五位代码"),           # 非 6 位
        _row("600ABC", "非数字"),            # 非数字
        _row("000001", ""),                  # 空名称
        _row("000001", "   "),               # 空白名称
        _row("000002", "正常股", f2=10.0),
    ]

    def handler(url, params):
        return {"data": {"total": 6, "diff": rows}}

    _install_em_get(monkeypatch, handler)
    out = astock.a_share_snapshot()
    assert [x["code"] for x in out] == ["600519", "000002"]
    assert all(len(x["code"]) == 6 and x["code"].isdigit() for x in out)
    assert all(x["name"].strip() for x in out)
