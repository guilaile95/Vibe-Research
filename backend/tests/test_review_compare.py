"""review_compare 纯比较器离线测试（不联网、不读库、不改输入）。"""
from __future__ import annotations

import copy
import json

import pytest

from review_compare import compare_daily_review_snapshots

_FORBIDDEN = frozenset({
    "recommendation", "action", "position", "forecast",
    "prediction", "cause", "reason", "score",
})


def _board(code: str, name: str, pct: float = 1.0) -> dict:
    return {"code": code, "name": name, "change_pct": pct}


def _stock(code: str, name: str, amount: float = 1e9, turnover: float = 10.0) -> dict:
    return {
        "code": code, "name": name, "amount": amount,
        "turnover_pct": turnover, "price": 10.0, "change_pct": 1.0,
    }


def _full_review(**overrides) -> dict:
    base = {
        "schema_version": "daily-review-v0.1",
        "generated_at": "2026-07-21 15:00:00",
        "trade_date": "2026-07-21",
        "status": "normal",
        "warnings": [],
        "data_health": {"components": {"breadth": "normal", "emotion": "normal"}},
        "market_environment": {
            "breadth": {
                "status": "normal",
                "data": {
                    "stock_count": 5000,
                    "valid_count": 4900,
                    "up_count": 100,
                    "down_count": 200,
                    "flat_count": 10,
                    "up_ratio": 0.3,
                    "up_3pct_count": 20,
                    "down_3pct_count": 30,
                    "total_amount": 1e12,
                    "amount_valid_count": 4900,
                },
            }
        },
        "short_term_emotion": {
            "status": "normal",
            "data": {
                "zt_count": 50,
                "dt_count": 5,
                "zb_count": 10,
                "max_boards": 4,
                "lianban_count": 12,
                "seal_rate": 0.8,
                "break_rate": 0.2,
                "promotion_rate": 0.3,
                "yzt_count": 40,
            },
        },
        "sector_rotation": {
            "industry": {
                "status": "normal",
                "data": {
                    "top": [_board("BK01", "半导体", 3), _board("BK02", "银行", 1)],
                    "bottom": [_board("BK09", "地产", -2)],
                },
            },
            "concept": {
                "status": "normal",
                "data": {
                    "top": [_board("C01", "AI", 5)],
                    "bottom": [_board("C09", "白酒", -1)],
                },
            },
            "region": {
                "status": "normal",
                "data": {
                    "top": [_board("R01", "上海", 1)],
                    "bottom": [_board("R09", "深圳", -1)],
                },
            },
            "highlights": {
                "strongest_industry": _board("BK01", "半导体", 3),
                "weakest_industry": _board("BK09", "地产", -2),
                "strongest_concept": _board("C01", "AI", 5),
                "weakest_concept": _board("C09", "白酒", -1),
                "strongest_region": _board("R01", "上海", 1),
                "weakest_region": _board("R09", "深圳", -1),
            },
        },
        "capital_activity": {
            "total_amount": 1e12,
            "amount_valid_count": 4900,
            "amount_top": [_stock("600519", "茅台"), _stock("000001", "平安")],
            "high_turnover": [_stock("300001", "特锐德", turnover=20)],
        },
    }
    base.update(overrides)
    return base


def _snap(review: dict | None = None, **meta) -> dict:
    r = review if review is not None else _full_review()
    s = {
        "id": meta.get("id", 1),
        "trade_date": meta.get("trade_date", r.get("trade_date") or "2026-07-21"),
        "schema_version": meta.get("schema_version", "daily-review-v0.1"),
        "generated_at": meta.get("generated_at", r.get("generated_at") or "2026-07-21 15:00:00"),
        "data_cutoff": meta.get("data_cutoff", None),
        "status": meta.get("status", r.get("status") or "normal"),
        "payload_hash": meta.get("payload_hash", "h1"),
        "created_at": meta.get("created_at", "2026-07-21 15:01:00"),
        "review": r,
    }
    for k, v in meta.items():
        if k not in ("id",) or v is not None:
            s[k] = v
    if "id" in meta:
        s["id"] = meta["id"]
    return s


def _keys(obj, found=None):
    if found is None:
        found = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(k)
            _keys(v, found)
    elif isinstance(obj, list):
        for it in obj:
            _keys(it, found)
    return found


# ---------------------------------------------------------------------------
# 1. 完整快照
# ---------------------------------------------------------------------------

def test_full_compare_normal():
    base = _snap(id=1, trade_date="2026-07-20", generated_at="2026-07-20 15:00:00")
    base["review"] = _full_review(trade_date="2026-07-20", generated_at="2026-07-20 15:00:00")
    target = _snap(id=2, trade_date="2026-07-21")
    out = compare_daily_review_snapshots(base, target)
    for k in (
        "schema_version", "base", "target", "comparison_status", "schema_compatible",
        "warnings", "market_breadth", "short_term_emotion", "sector_rotation",
        "capital_activity", "unknowns",
    ):
        assert k in out
    assert out["schema_version"] == "daily-review-comparison-v0.1"
    assert out["base"]["id"] == 1
    assert out["target"]["id"] == 2
    assert out["schema_compatible"] is True
    assert out["comparison_status"] == "normal"
    assert out["market_breadth"]["available"] is True


# ---------------------------------------------------------------------------
# 2–6 数值规则
# ---------------------------------------------------------------------------

def test_numeric_delta_and_pct():
    base = _snap()
    target = _snap(id=2)
    base["review"]["market_environment"]["breadth"]["data"]["up_count"] = 100
    target["review"]["market_environment"]["breadth"]["data"]["up_count"] = 130
    out = compare_daily_review_snapshots(base, target)
    c = out["market_breadth"]["up_count"]
    assert c["base"] == 100
    assert c["target"] == 130
    assert c["delta"] == 30
    assert c["change_pct"] == 0.3


def test_negative_base_abs():
    base = _snap()
    target = _snap(id=2)
    # 用 total_amount 模拟可为负的字段语义（仅测试公式）
    base["review"]["market_environment"]["breadth"]["data"]["up_count"] = -20
    target["review"]["market_environment"]["breadth"]["data"]["up_count"] = -10
    c = compare_daily_review_snapshots(base, target)["market_breadth"]["up_count"]
    assert c["delta"] == 10
    assert c["change_pct"] == 0.5


def test_base_zero_change_pct_none():
    base = _snap()
    target = _snap(id=2)
    base["review"]["market_environment"]["breadth"]["data"]["flat_count"] = 0
    target["review"]["market_environment"]["breadth"]["data"]["flat_count"] = 5
    c = compare_daily_review_snapshots(base, target)["market_breadth"]["flat_count"]
    assert c["base"] == 0
    assert c["target"] == 5
    assert c["delta"] == 5
    assert c["change_pct"] is None


def test_none_preserved():
    base = _snap()
    target = _snap(id=2)
    base["review"]["market_environment"]["breadth"]["data"]["up_ratio"] = None
    target["review"]["market_environment"]["breadth"]["data"]["up_ratio"] = 0.5
    c = compare_daily_review_snapshots(base, target)["market_breadth"]["up_ratio"]
    assert c["base"] is None
    assert c["target"] == 0.5
    assert c["delta"] is None
    assert c["change_pct"] is None
    # 真实 0
    base["review"]["short_term_emotion"]["data"]["dt_count"] = 0
    target["review"]["short_term_emotion"]["data"]["dt_count"] = 0
    z = compare_daily_review_snapshots(base, target)["short_term_emotion"]["dt_count"]
    assert z["base"] == 0
    assert z["target"] == 0
    assert z["delta"] == 0


def test_bool_not_numeric():
    base = _snap()
    target = _snap(id=2)
    base["review"]["market_environment"]["breadth"]["data"]["up_count"] = True
    target["review"]["market_environment"]["breadth"]["data"]["up_count"] = False
    c = compare_daily_review_snapshots(base, target)["market_breadth"]["up_count"]
    assert c["base"] is None
    assert c["target"] is None
    assert c["delta"] is None


# ---------------------------------------------------------------------------
# 7–8 字段映射
# ---------------------------------------------------------------------------

def test_breadth_fields_present():
    out = compare_daily_review_snapshots(_snap(), _snap(id=2))
    for f in (
        "stock_count", "valid_count", "up_count", "down_count", "flat_count",
        "up_ratio", "up_3pct_count", "down_3pct_count", "total_amount", "amount_valid_count",
    ):
        assert f in out["market_breadth"]
        assert set(out["market_breadth"][f]) == {"base", "target", "delta", "change_pct"}


def test_emotion_not_recomputed():
    base = _snap()
    target = _snap(id=2)
    base["review"]["short_term_emotion"]["data"]["seal_rate"] = 0.8
    target["review"]["short_term_emotion"]["data"]["seal_rate"] = 0.4
    # 不按 zt/zb 重算
    c = compare_daily_review_snapshots(base, target)["short_term_emotion"]["seal_rate"]
    assert c["base"] == 0.8
    assert c["target"] == 0.4
    assert c["delta"] == pytest.approx(-0.4)


# ---------------------------------------------------------------------------
# 9–16 排名
# ---------------------------------------------------------------------------

def test_entered_exited_and_ranks_from_one():
    base = _snap()
    target = _snap(id=2)
    base["review"]["sector_rotation"]["industry"]["data"]["top"] = [
        _board("A", "甲"), _board("B", "乙"), _board("C", "丙"),
    ]
    target["review"]["sector_rotation"]["industry"]["data"]["top"] = [
        _board("B", "乙"), _board("D", "丁"), _board("A", "甲"),
    ]
    top = compare_daily_review_snapshots(base, target)["sector_rotation"]["industry"]["top"]
    entered_keys = [e["key"] for e in top["entered"]]
    exited_keys = [e["key"] for e in top["exited"]]
    assert "D" in entered_keys
    assert top["entered"][0]["target_rank"] >= 1
    assert "C" in exited_keys
    assert top["exited"][0]["base_rank"] >= 1


def test_rank_up_and_down():
    base = _snap()
    target = _snap(id=2)
    base["review"]["sector_rotation"]["industry"]["data"]["top"] = [
        _board("X1", "一"), _board("X2", "二"), _board("X3", "三"),
        _board("X4", "四"), _board("X5", "五"),
    ]
    target["review"]["sector_rotation"]["industry"]["data"]["top"] = [
        _board("X5", "五"), _board("X2", "二"), _board("X3", "三"),
        _board("X4", "四"), _board("X1", "一"),
    ]
    changes = {
        c["key"]: c
        for c in compare_daily_review_snapshots(base, target)["sector_rotation"]["industry"]["top"]["rank_changes"]
    }
    # X5: base 5 → target 1, delta = 4
    assert changes["X5"]["base_rank"] == 5
    assert changes["X5"]["target_rank"] == 1
    assert changes["X5"]["rank_delta"] == 4
    # X1: base 1 → target 5, delta = -4
    assert changes["X1"]["rank_delta"] == -4


def test_rank_order_stable_not_by_pct():
    base = _snap()
    target = _snap(id=2)
    # 故意按涨跌幅乱序写入；比较器不按涨跌幅重排，按列表位置排名
    base["review"]["sector_rotation"]["concept"]["data"]["top"] = [
        _board("C2", "低", 1), _board("C1", "高", 9),
    ]
    target["review"]["sector_rotation"]["concept"]["data"]["top"] = [
        _board("C1", "高", 9), _board("C2", "低", 1),
    ]
    ch = compare_daily_review_snapshots(base, target)["sector_rotation"]["concept"]["top"]["rank_changes"]
    # 按 target_rank 升序
    ranks = [c["target_rank"] for c in ch]
    assert ranks == sorted(ranks)
    by_key = {c["key"]: c for c in ch}
    assert by_key["C1"]["base_rank"] == 2
    assert by_key["C1"]["target_rank"] == 1


def test_code_priority_over_name():
    base = _snap()
    target = _snap(id=2)
    base["review"]["capital_activity"]["amount_top"] = [
        {"code": "600519", "name": "旧名", "amount": 1},
    ]
    target["review"]["capital_activity"]["amount_top"] = [
        {"code": "600519", "name": "新名", "amount": 2},
    ]
    ch = compare_daily_review_snapshots(base, target)["capital_activity"]["amount_top"]["rank_changes"]
    assert len(ch) == 1
    assert ch[0]["key"] == "600519"
    assert compare_daily_review_snapshots(base, target)["capital_activity"]["amount_top"]["entered"] == []


def test_name_fallback():
    base = _snap()
    target = _snap(id=2)
    base["review"]["capital_activity"]["amount_top"] = [{"name": "仅名", "amount": 1}]
    target["review"]["capital_activity"]["amount_top"] = [{"name": "仅名", "amount": 2}]
    ch = compare_daily_review_snapshots(base, target)["capital_activity"]["amount_top"]["rank_changes"]
    assert ch[0]["key"] == "仅名"


def test_no_identity_skipped():
    base = _snap()
    target = _snap(id=2)
    base["review"]["capital_activity"]["amount_top"] = [{"amount": 1}, {"code": "A", "name": "a"}]
    target["review"]["capital_activity"]["amount_top"] = [{"amount": 2}, {"code": "A", "name": "a"}]
    top = compare_daily_review_snapshots(base, target)["capital_activity"]["amount_top"]
    assert all(e["key"] for e in top["entered"] + top["exited"] + top["rank_changes"])
    assert all(c["key"] != "" for c in top["rank_changes"])


def test_board_limit():
    base = _snap()
    target = _snap(id=2)
    base["review"]["sector_rotation"]["industry"]["data"]["top"] = [
        _board(f"B{i}", f"板{i}") for i in range(15)
    ]
    target["review"]["sector_rotation"]["industry"]["data"]["top"] = [
        _board(f"B{i}", f"板{i}") for i in range(5, 20)
    ]
    top = compare_daily_review_snapshots(base, target, board_limit=5)["sector_rotation"]["industry"]["top"]
    assert top["base_count"] == 5
    assert top["target_count"] == 5
    # 只有前 5 的交集/差集
    assert all(e["target_rank"] <= 5 for e in top["entered"])


def test_stock_limit():
    base = _snap()
    target = _snap(id=2)
    base["review"]["capital_activity"]["amount_top"] = [
        _stock(f"{i:06d}", f"股{i}") for i in range(20)
    ]
    target["review"]["capital_activity"]["amount_top"] = [
        _stock(f"{i:06d}", f"股{i}") for i in range(10, 30)
    ]
    top = compare_daily_review_snapshots(base, target, stock_limit=3)["capital_activity"]["amount_top"]
    assert top["base_count"] == 3
    assert top["target_count"] == 3


# ---------------------------------------------------------------------------
# 17 highlights
# ---------------------------------------------------------------------------

def test_highlights_variants():
    base = _snap()
    target = _snap(id=2)
    # 相同
    out = compare_daily_review_snapshots(base, target)
    assert out["sector_rotation"]["highlights"]["strongest_industry"]["changed"] is False

    # 改变
    target["review"]["sector_rotation"]["highlights"]["strongest_industry"] = _board("BK99", "新能源")
    out = compare_daily_review_snapshots(base, target)
    assert out["sector_rotation"]["highlights"]["strongest_industry"]["changed"] is True

    # 一侧缺失
    target["review"]["sector_rotation"]["highlights"]["weakest_industry"] = None
    out = compare_daily_review_snapshots(base, target)
    assert out["sector_rotation"]["highlights"]["weakest_industry"]["changed"] is True

    # 双方缺失
    base["review"]["sector_rotation"]["highlights"]["strongest_region"] = None
    target["review"]["sector_rotation"]["highlights"]["strongest_region"] = None
    out = compare_daily_review_snapshots(base, target)
    assert out["sector_rotation"]["highlights"]["strongest_region"]["changed"] is False

    # 无法提取标识
    base["review"]["sector_rotation"]["highlights"]["weakest_concept"] = {"change_pct": 1}
    target["review"]["sector_rotation"]["highlights"]["weakest_concept"] = {"change_pct": 2}
    out = compare_daily_review_snapshots(base, target)
    assert out["sector_rotation"]["highlights"]["weakest_concept"]["changed"] is None


# ---------------------------------------------------------------------------
# 18–21 状态
# ---------------------------------------------------------------------------

def test_schema_mismatch():
    base = _snap(schema_version="daily-review-v0.1")
    target = _snap(id=2, schema_version="daily-review-v0.2")
    out = compare_daily_review_snapshots(base, target)
    assert out["schema_compatible"] is False
    assert out["comparison_status"] == "partial"
    assert any("schema_version" in w for w in out["warnings"])
    assert out["market_breadth"]["available"] is True


def test_base_partial_status():
    base = _snap(status="partial")
    target = _snap(id=2, status="normal")
    out = compare_daily_review_snapshots(base, target)
    assert out["comparison_status"] in ("partial", "unavailable")
    assert out["comparison_status"] == "partial"
    assert any("partial" in w for w in out["warnings"])


def test_target_unavailable_still_partial_if_data():
    base = _snap(status="normal")
    target = _snap(id=2, status="unavailable")
    out = compare_daily_review_snapshots(base, target)
    # 仍有可比较核心数据
    assert out["comparison_status"] == "partial"
    assert any("unavailable" in w for w in out["warnings"])


def test_all_core_missing_unavailable():
    empty = {"review": {}}
    out = compare_daily_review_snapshots(
        {"review": {}, "schema_version": "a"},
        {"review": {}, "schema_version": "a"},
    )
    assert out["comparison_status"] == "unavailable"
    assert out["market_breadth"]["available"] is False
    assert "schema_version" in out
    assert isinstance(out["unknowns"], list)


# ---------------------------------------------------------------------------
# 22–24 日期
# ---------------------------------------------------------------------------

def test_same_trade_date_allowed():
    base = _snap(trade_date="2026-07-21")
    target = _snap(id=2, trade_date="2026-07-21")
    out = compare_daily_review_snapshots(base, target)
    assert any("相同" in w for w in out["warnings"])
    assert out["comparison_status"] == "normal"


def test_target_earlier_date_warns():
    base = _snap(trade_date="2026-07-22")
    target = _snap(id=2, trade_date="2026-07-21")
    out = compare_daily_review_snapshots(base, target)
    assert any("早于" in w for w in out["warnings"])
    assert out["base"]["trade_date"] == "2026-07-22"
    assert out["target"]["trade_date"] == "2026-07-21"


def test_invalid_dates_partial():
    base = _snap(trade_date="20260721")
    target = _snap(id=2, trade_date="2026-07-21")
    out = compare_daily_review_snapshots(base, target)
    assert out["comparison_status"] == "partial"
    assert any("日期" in w for w in out["warnings"])


# ---------------------------------------------------------------------------
# 25–28 其他
# ---------------------------------------------------------------------------

def test_unknowns_deduped():
    out = compare_daily_review_snapshots({"review": {}}, {"review": {}})
    assert len(out["unknowns"]) == len(set(out["unknowns"]))
    assert out["unknowns"] == sorted(out["unknowns"], key=out["unknowns"].index)


def test_empty_review_no_keyerror():
    out = compare_daily_review_snapshots({"review": {}}, {"review": {}})
    assert out["comparison_status"] == "unavailable"
    assert out["market_breadth"]["available"] is False


def test_input_not_mutated():
    base = _snap()
    target = _snap(id=2)
    bb, tt = copy.deepcopy(base), copy.deepcopy(target)
    compare_daily_review_snapshots(base, target)
    assert base == bb
    assert target == tt


def test_deterministic():
    base = _snap()
    target = _snap(id=2)
    a = compare_daily_review_snapshots(base, target)
    b = compare_daily_review_snapshots(base, target)
    assert a == b


# ---------------------------------------------------------------------------
# 29–31 非法输入
# ---------------------------------------------------------------------------

def test_illegal_snapshot_types():
    with pytest.raises(TypeError, match="base_snapshot"):
        compare_daily_review_snapshots([], _snap())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="target_snapshot"):
        compare_daily_review_snapshots(_snap(), None)  # type: ignore[arg-type]


def test_illegal_review():
    with pytest.raises(ValueError, match="base_snapshot.review"):
        compare_daily_review_snapshots({"review": []}, _snap())
    with pytest.raises(ValueError, match="target_snapshot.review"):
        compare_daily_review_snapshots(_snap(), {"review": "x"})


@pytest.mark.parametrize("kwargs", [
    {"board_limit": 0},
    {"board_limit": 21},
    {"stock_limit": 0},
    {"stock_limit": 31},
])
def test_illegal_limits(kwargs):
    with pytest.raises(ValueError):
        compare_daily_review_snapshots(_snap(), _snap(id=2), **kwargs)


def test_no_forbidden_conclusion_keys():
    out = compare_daily_review_snapshots(_snap(), _snap(id=2))
    keys = _keys(out)
    for f in _FORBIDDEN:
        assert f not in keys


def test_one_side_breadth_unknowns():
    base = _snap()
    target = _snap(id=2)
    target["review"]["market_environment"] = {}
    out = compare_daily_review_snapshots(base, target)
    assert "目标快照市场广度不可用" in out["unknowns"]
    assert out["market_breadth"]["available"] is False
    assert out["comparison_status"] == "partial"


# 市场摘要门禁与存档数值差是独立契约；样本来自实际纯计算入口。
def _market_snap(day="2026-07-20", clock="14:00:00", rows=None):
    from market import calculate_market_breadth

    snapshot = _snap(trade_date=day)
    snapshot["review"]["market_environment"]["breadth"] = {
        "status": "normal", "source": "eastmoney_push2", "trade_date": day,
        "data_time": f"{day}T{clock}+08:00", "is_stale": False,
        "data": calculate_market_breadth(rows if rows is not None else [
            _stock("000001", "甲", amount=100), _stock("000002", "乙", amount=200),
        ]),
    }
    return snapshot


def _breadth(snapshot):
    return snapshot["review"]["market_environment"]["breadth"]


def _comparability(base, target):
    return compare_daily_review_snapshots(base, target)["market_comparability"]


def test_market_comparability_known_source_times_and_same_samples():
    base = _market_snap()
    target = _market_snap("2026-07-21", rows=[
        _stock("000002", "乙", amount=300), _stock("000001", "甲", amount=200),
    ])
    _breadth(target)["data"]["up_ratio"] = 0.5
    originals = copy.deepcopy((base, target))
    out = compare_daily_review_snapshots(base, target)
    assert out["market_comparability"] == {
        "status": "comparable",
        "metrics": {metric: {"status": "comparable", "issues": []} for metric in ("up_ratio", "total_amount")},
    }
    assert out["market_breadth"]["total_amount"]["delta"] == 200
    assert out["market_breadth"]["up_ratio"]["delta"] == -0.5
    assert (base, target) == originals


def test_market_comparability_does_not_substitute_generation_or_cutoff_for_source_time():
    base, target = _market_snap(), _market_snap("2026-07-21")
    for snapshot in (base, target):
        envelope = _breadth(snapshot)
        snapshot["data_cutoff"] = snapshot["generated_at"]
        snapshot["date"] = snapshot["trade_date"]
        envelope["fetched_at"] = envelope["data_time"]
        envelope["data_time"] = envelope["trade_date"] = None
    out = compare_daily_review_snapshots(base, target)
    assert out["market_comparability"]["status"] == "unverified"
    assert out["market_breadth"]["total_amount"]["delta"] == 0
    assert out["comparison_status"] == "normal"
    assert any("源行情时间" in issue for issue in out["market_comparability"]["metrics"]["up_ratio"]["issues"])


def test_market_comparability_same_count_different_codes_is_incomparable():
    base = _market_snap()
    target = _market_snap("2026-07-21", rows=[
        _stock("000001", "甲", amount=100), _stock("000003", "丙", amount=200),
    ])
    result = _comparability(base, target)
    assert result["status"] == "incomparable"
    for metric in result["metrics"].values():
        assert metric["status"] == "incomparable"
        assert any("样本身份不一致" in issue for issue in metric["issues"])


@pytest.mark.parametrize("field,metric,other", [
    ("amount", "total_amount", "up_ratio"),
    ("change_pct", "up_ratio", "total_amount"),
])
def test_market_comparability_field_populations_checked_independently(field, metric, other):
    base_rows = [_stock("000001", "甲"), _stock("000002", "乙")]
    target_rows = copy.deepcopy(base_rows)
    base_rows[0][field] = None
    target_rows[1][field] = None
    result = _comparability(_market_snap(rows=base_rows), _market_snap("2026-07-21", rows=target_rows))
    assert result["status"] == "incomparable"
    assert result["metrics"][metric]["status"] == "incomparable"
    assert result["metrics"][other] == {"status": "comparable", "issues": []}


@pytest.mark.parametrize("target_day,target_clock,status", [
    ("2026-07-20", "14:30:00", "comparable"),
    ("2026-07-21", "14:00:00", "comparable"),
    ("2026-07-20", "14:00:00", "incomparable"),
    ("2026-07-20", "13:59:00", "incomparable"),
    ("2026-07-19", "14:00:00", "incomparable"),
    ("2026-07-20", "15:00:00", "incomparable"),
    ("2026-07-21", "15:00:00", "incomparable"),
    ("2026-07-21", "14:30:00", "incomparable"),
])
def test_market_comparability_source_time_order_clock_and_session(target_day, target_clock, status):
    assert _comparability(_market_snap(), _market_snap(target_day, target_clock))["status"] == status


@pytest.mark.parametrize("base_time,target_time", [
    ("2026-07-20 15:00:00", "2026-07-21T07:00:00Z"),
    ("2026-07-20T15:00:00+08:00", "2026-07-21T15:00:00+08:00"),
])
def test_market_comparability_source_times_use_beijing_timezone(base_time, target_time):
    base, target = _market_snap(), _market_snap("2026-07-21")
    _breadth(base)["data_time"], _breadth(target)["data_time"] = base_time, target_time
    assert _comparability(base, target)["status"] == "comparable"


@pytest.mark.parametrize("value", [None, "15:00:00", "2026-07-21", "2026-02-30T14:00:00", "not a time"])
def test_market_comparability_missing_or_invalid_time_is_unverified(value):
    base, target = _market_snap(), _market_snap("2026-07-21")
    _breadth(target)["data_time"] = value
    assert _comparability(base, target)["status"] == "unverified"


@pytest.mark.parametrize("field,value,expected", [
    ("source", None, "unverified"),
    ("source", " ", "unverified"),
    ("source", "another_provider", "incomparable"),
    ("status", None, "unverified"),
    ("status", "partial", "incomparable"),
    ("status", "unavailable", "incomparable"),
    ("trade_date", None, "unverified"),
    ("trade_date", "2026-02-30", "unverified"),
    ("trade_date", "2026-07-22", "incomparable"),
    ("is_stale", True, "incomparable"),
    ("data", None, "unverified"),
])
def test_market_comparability_envelope_missing_evidence_and_known_conflicts(field, value, expected):
    base, target = _market_snap(), _market_snap("2026-07-21")
    _breadth(target)[field] = value
    assert _comparability(base, target)["status"] == expected


@pytest.mark.parametrize("value,status", [(None, "unverified"), (" ", "unverified"), ("daily-review-v0.2", "incomparable")])
def test_market_comparability_requires_known_equal_snapshot_schema(value, status):
    base, target = _market_snap(), _market_snap("2026-07-21")
    target["schema_version"] = value
    assert _comparability(base, target)["status"] == status
    if status == "unverified":
        base["schema_version"] = value
        # None == None 仍可满足旧 schema_compatible，但不能通过市场门禁。
        assert _comparability(base, target)["status"] == "unverified"


def test_market_comparability_missing_fingerprint_cannot_use_equal_counts():
    base, target = _market_snap(), _market_snap("2026-07-21")
    _breadth(target)["data"]["comparison_samples"]["up_ratio"]["fingerprint"] = None
    result = _comparability(base, target)
    assert result["status"] == "unverified"
    assert result["metrics"]["up_ratio"]["status"] == "unverified"
    assert result["metrics"]["total_amount"]["status"] == "comparable"
    _breadth(target)["data"]["comparison_samples"]["total_amount"]["count"] = 3
    # 已知冲突优先于另一指标的未知。
    result = _comparability(base, target)
    assert result["status"] == "incomparable"
    assert result["metrics"]["up_ratio"]["status"] == "unverified"


@pytest.mark.parametrize("metric", ["up_ratio", "total_amount"])
@pytest.mark.parametrize("value", [None, True, float("nan"), float("inf")])
def test_market_comparability_requires_finite_metric_values(metric, value):
    base, target = _market_snap(), _market_snap("2026-07-21")
    _breadth(target)["data"][metric] = value
    result = _comparability(base, target)
    assert result["status"] == "unverified"
    assert result["metrics"][metric]["status"] == "unverified"


@pytest.mark.parametrize("value", [float("inf"), float("-inf")])
@pytest.mark.parametrize("side", ["base", "target"])
def test_nonfinite_archived_values_do_not_escape_into_numeric_deltas_or_json(value, side):
    base, target = _market_snap(), _market_snap("2026-07-21")
    snapshot = base if side == "base" else target
    _breadth(snapshot)["data"]["total_amount"] = value
    snapshot["review"]["capital_activity"]["total_amount"] = value
    snapshot["review"]["short_term_emotion"]["data"]["seal_rate"] = value
    out = compare_daily_review_snapshots(base, target)
    for section, field in (
        ("market_breadth", "total_amount"),
        ("capital_activity", "total_amount"),
        ("short_term_emotion", "seal_rate"),
    ):
        assert out[section][field][side] is None
        assert out[section][field]["delta"] is None
        assert out[section][field]["change_pct"] is None
    assert out["market_comparability"]["metrics"]["total_amount"]["status"] == "unverified"
    json.dumps(out, allow_nan=False)
