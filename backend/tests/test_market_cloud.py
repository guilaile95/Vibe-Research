"""市场云图 get_market_cloud 离线测试（全部 Mock，不打真实东财）。

V1 语义：
- 个股 tile 面积 = 真实流通市值（float_market_cap）
- 个股 tile 颜色 = 当日涨跌幅（红涨绿跌）
- 行业分组：个股按行业聚合
- fail-closed：缺流通市值或缺涨跌幅的股票不进入云图，不补 0，status=partial
"""
from __future__ import annotations

import pytest

import market
import astock


def _stock(code, name, *, f3=1.0, f21=1e10, f100="电子", **extra):
    """构造一条东财 clist 个股行。f3=涨跌幅, f21=流通市值, f100=行业。"""
    d = {
        "f2": 10.0, "f3": f3, "f4": 0.1, "f5": 1000.0, "f6": 1e8,
        "f7": 1.0, "f8": 0.5, "f12": code, "f13": 1, "f14": name,
        "f15": 10.5, "f16": 9.5, "f17": 10.0, "f18": 9.9,
        "f20": 2e10, "f21": f21, "f100": f100,
    }
    d.update(extra)
    return d


def _install_snapshot(monkeypatch, stocks):
    """mock get_a_share_snapshot 返回指定股票列表。"""
    def fake_snapshot():
        return [astock._map_a_share_row(s) for s in stocks]
    monkeypatch.setattr(market, "get_a_share_snapshot", fake_snapshot)


# ── 1. 行业分组 + 流通市值面积 ────────────────────────────────────────

def test_market_cloud_industry_grouping_and_float_cap_area(monkeypatch):
    """行业分组正确，行业内个股按流通市值降序，行业按总流通市值降序。"""
    stocks = [
        _stock("600001", "电子A", f3=2.0, f21=3e10, f100="电子"),
        _stock("600002", "电子B", f3=-1.0, f21=1e10, f100="电子"),
        _stock("600003", "电子C", f3=0.5, f21=2e10, f100="电子"),
        _stock("000001", "银行A", f3=0.2, f21=5e10, f100="银行"),
        _stock("000002", "银行B", f3=-0.3, f21=4e10, f100="银行"),
    ]
    _install_snapshot(monkeypatch, stocks)

    result = market.get_market_cloud("all", "today")
    assert result["status"] == "normal"
    data = result["data"]
    assert data is not None
    assert data["stock_count"] == 5
    assert data["valid_count"] == 5
    assert data["industry_count"] == 2

    # 行业按总流通市值降序：银行(9e10) > 电子(6e10)
    industries = data["industries"]
    assert [ind["name"] for ind in industries] == ["银行", "电子"]

    # 银行行业：总流通市值 = 5e10 + 4e10 = 9e10
    bank = industries[0]
    assert bank["stock_count"] == 2
    assert bank["total_float_cap"] == pytest.approx(9e10)
    # 行业内个股按流通市值降序
    assert [s["name"] for s in bank["stocks"]] == ["银行A", "银行B"]
    assert bank["stocks"][0]["float_market_cap"] == pytest.approx(5e10)

    # 电子行业：3 只股票
    elec = industries[1]
    assert elec["stock_count"] == 3
    assert elec["total_float_cap"] == pytest.approx(6e10)
    assert [s["name"] for s in elec["stocks"]] == ["电子A", "电子C", "电子B"]


# ── 2. fail-closed：缺流通市值或缺涨跌幅必须排除，status=partial，不补 0 ──

def test_market_cloud_fail_closed_missing_cap_or_pct(monkeypatch):
    """缺流通市值或缺涨跌幅的股票不进入云图，不补 0，status=partial。"""
    stocks = [
        _stock("600001", "正常股", f3=1.5, f21=1e10, f100="电子"),
        _stock("600002", "缺市值", f3=2.0, f21=None, f100="电子"),  # f21=None
        _stock("600003", "缺涨幅", f3="-", f21=2e10, f100="电子"),    # f3="-"
        _stock("600004", "都缺", f3=None, f21=0, f100="银行"),          # f3=None, f21=0
    ]
    _install_snapshot(monkeypatch, stocks)

    result = market.get_market_cloud("all", "today")
    assert result["status"] == "partial"
    data = result["data"]
    assert data is not None
    assert data["stock_count"] == 4
    assert data["valid_count"] == 1  # 只有"正常股"同时有市值和涨幅
    assert data["industry_count"] == 1

    # 唯一有效股票
    valid = data["industries"][0]["stocks"][0]
    assert valid["name"] == "正常股"
    assert valid["float_market_cap"] == pytest.approx(1e10)
    assert valid["change_pct"] == pytest.approx(1.5)

    # 被排除的股票不出现在任何行业中
    all_names = {s["name"] for ind in data["industries"] for s in ind["stocks"]}
    assert "缺市值" not in all_names
    assert "缺涨幅" not in all_names
    assert "都缺" not in all_names

    # warnings 明确说明缺失
    warnings = result["warnings"]
    assert any("缺流通市值" in w for w in warnings)
    assert any("缺涨跌幅" in w for w in warnings)


def test_market_cloud_all_invalid_is_unavailable_not_fake_zero(monkeypatch):
    """全部股票缺市值/涨幅 → status=unavailable，不返回全 0 假数据。"""
    stocks = [
        _stock("600001", "缺市值", f3=1.0, f21=None, f100="电子"),
        _stock("600002", "缺涨幅", f3="-", f21=1e10, f100="银行"),
    ]
    _install_snapshot(monkeypatch, stocks)

    result = market.get_market_cloud("all", "today")
    assert result["status"] == "unavailable"
    assert result["data"] is None
    # 不返回假 0 数据
    assert result["warnings"]  # 有明确警告


# ── 3. scope 过滤 ─────────────────────────────────────────────────────

def test_market_cloud_scope_filtering(monkeypatch):
    """scope 过滤基于代码前缀：cyb=30开头, star=68开头, sh=60/68, sz=00/30。"""
    stocks = [
        _stock("600001", "上证A", f3=1.0, f21=1e10, f100="电子"),
        _stock("688001", "科创板A", f3=2.0, f21=2e10, f100="半导体"),
        _stock("300001", "创业板A", f3=3.0, f21=3e10, f100="医药"),
        _stock("000001", "深证A", f3=0.5, f21=4e10, f100="银行"),
    ]
    _install_snapshot(monkeypatch, stocks)

    # all = 全部
    r_all = market.get_market_cloud("all", "today")
    assert r_all["data"]["stock_count"] == 4
    assert r_all["data"]["valid_count"] == 4

    # cyb = 30开头
    r_cyb = market.get_market_cloud("cyb", "today")
    assert r_cyb["data"]["stock_count"] == 1
    assert r_cyb["data"]["industries"][0]["stocks"][0]["name"] == "创业板A"

    # star = 68开头
    r_star = market.get_market_cloud("star", "today")
    assert r_star["data"]["stock_count"] == 1
    assert r_star["data"]["industries"][0]["stocks"][0]["name"] == "科创板A"

    # sh = 60/68开头
    r_sh = market.get_market_cloud("sh", "today")
    assert r_sh["data"]["stock_count"] == 2
    sh_names = {s["name"] for ind in r_sh["data"]["industries"] for s in ind["stocks"]}
    assert sh_names == {"上证A", "科创板A"}

    # sz = 00/30开头
    r_sz = market.get_market_cloud("sz", "today")
    assert r_sz["data"]["stock_count"] == 2
    sz_names = {s["name"] for ind in r_sz["data"]["industries"] for s in ind["stocks"]}
    assert sz_names == {"创业板A", "深证A"}


def test_market_cloud_invalid_scope_raises(monkeypatch):
    """非法 scope / period 抛出 ValueError（不静默降级）。"""
    with pytest.raises(ValueError, match="不支持的市场范围"):
        market.get_market_cloud("hs300", "today")
    with pytest.raises(ValueError, match="不支持的周期"):
        market.get_market_cloud("all", "5d")


# ── 4. 行业涨跌统计 ───────────────────────────────────────────────────

def test_market_cloud_industry_up_down_counts(monkeypatch):
    """行业上涨/下跌家数和平均涨跌幅正确。"""
    stocks = [
        _stock("600001", "涨1", f3=2.0, f21=1e10, f100="电子"),
        _stock("600002", "涨2", f3=1.0, f21=1e10, f100="电子"),
        _stock("600003", "跌1", f3=-1.0, f21=1e10, f100="电子"),
        _stock("600004", "平", f3=0.0, f21=1e10, f100="电子"),
    ]
    _install_snapshot(monkeypatch, stocks)

    result = market.get_market_cloud("all", "today")
    ind = result["data"]["industries"][0]
    assert ind["up_count"] == 2
    assert ind["down_count"] == 1
    assert ind["avg_change_pct"] == pytest.approx(0.5)  # (2+1-1+0)/4
