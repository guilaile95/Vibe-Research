"""board_ranking 统一板块排名离线测试（全部 Mock 网络）。"""
from __future__ import annotations

import json

import pytest

import astock


def _board(
    code="BK0475",
    name="半导体",
    *,
    f3=2.5,
    f8=1.2,
    f20=1e12,
    f104=60,
    f105=40,
    f128="某龙头",
    f136=5.0,
    **extra,
):
    d = {
        "f12": code, "f14": name,
        "f3": f3, "f8": f8, "f20": f20,
        "f104": f104, "f105": f105,
        "f128": f128, "f136": f136,
    }
    d.update(extra)
    return d


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _install_em_get(monkeypatch, handler):
    calls: list[dict] = []

    def fake_em_get(url, params=None, headers=None, timeout=15):
        calls.append({"url": url, "params": dict(params or {})})
        return _FakeResp(handler(url, params or {}))

    monkeypatch.setattr(astock, "em_get", fake_em_get)
    monkeypatch.setattr(astock, "_EM_MIN_INTERVAL", 0)
    monkeypatch.setattr(astock, "_em_last_call", [0.0])
    # amount enrichment 有独立 targeted test；此处 mock 掉避免触发 stock/get 调用
    monkeypatch.setattr(astock, "_enrich_board_amounts", lambda boards: None)
    return calls


# ── 1–3 板块类型与 fs ───────────────────────────────────────────────

def test_board_ranking_industry_fs_and_fields(monkeypatch):
    def handler(url, params):
        assert "clist/get" in url
        assert params["fs"] == astock.BOARD_FS["industry"]
        return {"data": {"total": 1, "diff": [_board()]}}

    _install_em_get(monkeypatch, handler)
    out = astock.board_ranking("industry", top_n=5)
    assert out["type"] == "industry"
    assert out["total"] == 1
    assert out["ranked_count"] == 1
    row = out["top"][0]
    assert row["code"] == "BK0475"
    assert row["name"] == "半导体"
    assert row["change_pct"] == pytest.approx(2.5)
    assert row["up_count"] == 60
    assert row["down_count"] == 40
    assert row["up_ratio"] == pytest.approx(0.6)
    assert row["leader"] == "某龙头"
    assert row["leader_change_pct"] == pytest.approx(5.0)


def test_board_ranking_concept_fs(monkeypatch):
    def handler(url, params):
        assert params["fs"] == astock.BOARD_FS["concept"]
        return {"data": {"total": 1, "diff": [_board(code="BK0881", name="人工智能")]}}

    _install_em_get(monkeypatch, handler)
    out = astock.board_ranking("concept")
    assert out["type"] == "concept"
    assert out["top"][0]["name"] == "人工智能"


def test_board_ranking_region_fs(monkeypatch):
    def handler(url, params):
        assert params["fs"] == astock.BOARD_FS["region"]
        return {"data": {"total": 1, "diff": [_board(code="BK0154", name="广东板块")]}}

    _install_em_get(monkeypatch, handler)
    out = astock.board_ranking("region")
    assert out["type"] == "region"
    assert out["top"][0]["code"] == "BK0154"


# ── 4–5 非法参数 ───────────────────────────────────────────────────

def test_board_ranking_invalid_type():
    with pytest.raises(ValueError, match="不支持的板块类型"):
        astock.board_ranking("invalid")


@pytest.mark.parametrize("n", [0, 101])
def test_board_ranking_invalid_top_n(n):
    with pytest.raises(ValueError, match="top_n"):
        astock.board_ranking("industry", top_n=n)


# ── 6–7 diff 格式 ───────────────────────────────────────────────────

def test_board_ranking_diff_list(monkeypatch):
    def handler(url, params):
        return {"data": {"total": 2, "diff": [
            _board("A", "强", f3=3.0),
            _board("B", "弱", f3=-1.0),
        ]}}

    _install_em_get(monkeypatch, handler)
    out = astock.board_ranking("industry", top_n=10)
    assert out["total"] == 2
    assert [x["code"] for x in out["top"]] == ["A", "B"]


def test_board_ranking_diff_dict(monkeypatch):
    def handler(url, params):
        return {"data": {"total": 2, "diff": {
            "1": _board("B", "乙", f3=1.0),
            "0": _board("A", "甲", f3=2.0),
        }}}

    _install_em_get(monkeypatch, handler)
    out = astock.board_ranking("industry", top_n=10)
    assert out["total"] == 2
    assert {x["code"] for x in out["top"]} == {"A", "B"}


# ── 8 多页合并 ──────────────────────────────────────────────────────

def test_board_ranking_multi_page(monkeypatch):
    page_size = 2
    p1 = [_board("C1", "一", f3=1.0), _board("C2", "二", f3=2.0)]
    p2 = [_board("C3", "三", f3=3.0)]

    def handler(url, params):
        pn = int(params["pn"])
        assert params["pz"] == str(page_size)
        if pn == 1:
            return {"data": {"total": 3, "diff": p1}}
        if pn == 2:
            return {"data": {"total": 3, "diff": p2}}
        raise AssertionError(f"unexpected page {pn}")

    calls = _install_em_get(monkeypatch, handler)
    out = astock.board_ranking("industry", top_n=10, page_size=page_size)
    assert len(calls) == 2
    assert out["total"] == 3
    codes = {x["code"] for x in out["top"]} | {x["code"] for x in out["bottom"]}
    assert codes == {"C1", "C2", "C3"}
    assert len(out["top"]) == 3


# ── 9 本地重排 ──────────────────────────────────────────────────────

def test_board_ranking_local_sort(monkeypatch):
    # 远端乱序
    rows = [
        _board("M", "中", f3=0.0),
        _board("H", "高", f3=5.0),
        _board("L", "低", f3=-3.0),
    ]

    def handler(url, params):
        return {"data": {"total": 3, "diff": rows}}

    _install_em_get(monkeypatch, handler)
    out = astock.board_ranking("industry", top_n=2)
    assert [x["code"] for x in out["top"]] == ["H", "M"]
    assert [x["code"] for x in out["bottom"]] == ["L", "M"]
    assert out["bottom"][0]["change_pct"] == pytest.approx(-3.0)


# ── 10 缺失涨跌幅 ───────────────────────────────────────────────────

def test_board_ranking_missing_change_pct(monkeypatch):
    rows = [
        _board("OK", "有值", f3=1.0),
        _board("NA", "缺失", f3="-"),
        _board("NA2", "空", f3=None),
    ]

    def handler(url, params):
        return {"data": {"total": 3, "diff": rows}}

    _install_em_get(monkeypatch, handler)
    out = astock.board_ranking("industry", top_n=10)
    assert out["total"] == 3
    assert out["ranked_count"] == 1
    assert out["unknown_count"] == 2
    assert [x["code"] for x in out["top"]] == ["OK"]
    assert [x["code"] for x in out["bottom"]] == ["OK"]
    assert out["unknown_count"] == 2


# ── 11 up_ratio ─────────────────────────────────────────────────────

def test_map_board_up_ratio():
    r = astock._map_board_row(_board(f104=60, f105=40))
    assert r["up_ratio"] == pytest.approx(0.6)
    r0 = astock._map_board_row(_board(f104=0, f105=0))
    assert r0["up_ratio"] is None
    rnone = astock._map_board_row(_board(f104=None, f105=40))
    assert rnone["up_ratio"] is None


# ── 12 缺失值清洗 ───────────────────────────────────────────────────

def test_board_ranking_optional_cleaning(monkeypatch):
    row = _board(f3="-", f8="", f20=0, f104="0", f105="-", f128="", f136="--")

    def handler(url, params):
        return {"data": {"total": 1, "diff": [row]}}

    _install_em_get(monkeypatch, handler)
    out = astock.board_ranking("industry", top_n=5)
    # change_pct 缺失 → 不进 top，但仍在 total
    assert out["total"] == 1
    assert out["ranked_count"] == 0
    assert out["unknown_count"] == 1
    # 直接 map 校验清洗
    m = astock._map_board_row(row)
    assert m["change_pct"] is None
    assert m["turnover_pct"] is None
    assert m["market_cap"] == pytest.approx(0.0)
    assert m["up_count"] == 0
    assert m["down_count"] is None
    assert m["leader"] is None
    assert m["leader_change_pct"] is None


# ── 13 重复 code ────────────────────────────────────────────────────

def test_board_ranking_dedupe(monkeypatch):
    rows = [
        _board("DUP", "第一", f3=1.0),
        _board("DUP", "第二", f3=9.0),
        _board("X", "其它", f3=0.5),
    ]

    def handler(url, params):
        return {"data": {"total": 3, "diff": rows}}

    _install_em_get(monkeypatch, handler)
    out = astock.board_ranking("industry", top_n=10)
    assert out["total"] == 2
    dup = next(x for x in out["top"] if x["code"] == "DUP")
    assert dup["name"] == "第一"
    assert dup["change_pct"] == pytest.approx(1.0)


# ── 14 空市场 ───────────────────────────────────────────────────────

def test_board_ranking_empty(monkeypatch):
    def handler(url, params):
        return {"data": {"total": 0, "diff": []}}

    _install_em_get(monkeypatch, handler)
    out = astock.board_ranking("industry")
    assert out == {
        "type": "industry",
        "total": 0,
        "ranked_count": 0,
        "unknown_count": 0,
        "top": [],
        "bottom": [],
        "amount_top": [],
    }


# ── 15 异常结构 ─────────────────────────────────────────────────────

def test_board_ranking_missing_data_raises(monkeypatch):
    def handler(url, params):
        return {"rc": 0}

    _install_em_get(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="missing data"):
        astock.board_ranking("industry")


def test_board_ranking_total_nonzero_empty_page_raises(monkeypatch):
    def handler(url, params):
        return {"data": {"total": 50, "diff": []}}

    _install_em_get(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="first page is empty"):
        astock.board_ranking("industry")


def test_board_ranking_request_failure_raises(monkeypatch):
    def handler(url, params):
        raise ConnectionError("down")

    _install_em_get(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="request failed"):
        astock.board_ranking("industry")
