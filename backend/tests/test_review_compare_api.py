"""GET /api/daily-review/history/compare 离线 API 测试（Mock 服务/比较器，不联网）。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
from fastapi.testclient import TestClient

import app as app_module
import chat as chat_layer
import daily_review
import review_compare
import review_history
import review_store

client = TestClient(app_module.app)


def _snap(sid: int, trade_date: str = "2026-07-21") -> dict:
    return {
        "id": sid,
        "trade_date": trade_date,
        "schema_version": "daily-review-v0.1",
        "generated_at": f"{trade_date} 15:00:00",
        "data_cutoff": None,
        "status": "normal",
        "payload_hash": f"h{sid}",
        "created_at": f"{trade_date} 15:01:00",
        "review": {
            "schema_version": "daily-review-v0.1",
            "trade_date": trade_date,
            "generated_at": f"{trade_date} 15:00:00",
            "status": "normal",
            "warnings": [],
            "market_environment": {
                "breadth": {
                    "status": "normal",
                    "data": {"up_count": 100 * sid, "down_count": 50},
                }
            },
            "short_term_emotion": {"status": "normal", "data": {"zt_count": 10}},
            "sector_rotation": {
                "industry": {"status": "normal", "data": {"top": [], "bottom": []}},
                "concept": {"status": "normal", "data": {"top": [], "bottom": []}},
                "region": {"status": "normal", "data": {"top": [], "bottom": []}},
                "highlights": {},
            },
            "capital_activity": {
                "total_amount": 1e12,
                "amount_top": [],
                "high_turnover": [],
            },
        },
    }


def _comparison(**overrides) -> dict:
    base = {
        "schema_version": "daily-review-comparison-v0.1",
        "base": {"id": 1, "trade_date": "2026-07-20", "status": "normal"},
        "target": {"id": 2, "trade_date": "2026-07-21", "status": "normal"},
        "comparison_status": "normal",
        "schema_compatible": True,
        "warnings": [],
        "market_breadth": {"available": True, "up_count": {"base": 100, "target": 130, "delta": 30, "change_pct": 0.3}},
        "short_term_emotion": {"available": True},
        "sector_rotation": {},
        "capital_activity": {},
        "unknowns": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1–5 正常与状态透传
# ---------------------------------------------------------------------------

def test_compare_ok(monkeypatch):
    get_snap = MagicMock(side_effect=[_snap(1), _snap(2)])
    cmp = MagicMock(return_value=_comparison())
    monkeypatch.setattr(review_history, "get_review_history_snapshot", get_snap)
    monkeypatch.setattr(review_compare, "compare_daily_review_snapshots", cmp)

    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 1, "target_id": 2},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"data"}
    assert body["data"]["comparison_status"] == "normal"
    assert body["data"]["market_breadth"]["up_count"]["delta"] == 30
    assert get_snap.call_count == 2
    get_snap.assert_has_calls([call(1), call(2)])
    cmp.assert_called_once()
    args, kwargs = cmp.call_args
    assert args[0]["id"] == 1
    assert args[1]["id"] == 2


def test_default_limits(monkeypatch):
    monkeypatch.setattr(
        review_history, "get_review_history_snapshot",
        MagicMock(side_effect=[_snap(1), _snap(2)]),
    )
    cmp = MagicMock(return_value=_comparison())
    monkeypatch.setattr(review_compare, "compare_daily_review_snapshots", cmp)
    client.get("/api/daily-review/history/compare", params={"base_id": 1, "target_id": 2})
    _, kwargs = cmp.call_args
    assert kwargs.get("board_limit") == 10
    assert kwargs.get("stock_limit") == 10


def test_custom_limits(monkeypatch):
    monkeypatch.setattr(
        review_history, "get_review_history_snapshot",
        MagicMock(side_effect=[_snap(1), _snap(2)]),
    )
    cmp = MagicMock(return_value=_comparison())
    monkeypatch.setattr(review_compare, "compare_daily_review_snapshots", cmp)
    client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 1, "target_id": 2, "board_limit": 5, "stock_limit": 20},
    )
    _, kwargs = cmp.call_args
    assert kwargs["board_limit"] == 5
    assert kwargs["stock_limit"] == 20


def test_partial_status_still_200(monkeypatch):
    monkeypatch.setattr(
        review_history, "get_review_history_snapshot",
        MagicMock(side_effect=[_snap(1), _snap(2)]),
    )
    monkeypatch.setattr(
        review_compare, "compare_daily_review_snapshots",
        MagicMock(return_value=_comparison(comparison_status="partial", warnings=["w"])),
    )
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 1, "target_id": 2},
    )
    assert r.status_code == 200
    assert r.json()["data"]["comparison_status"] == "partial"
    assert r.json()["data"]["warnings"] == ["w"]


def test_unavailable_status_still_200(monkeypatch):
    monkeypatch.setattr(
        review_history, "get_review_history_snapshot",
        MagicMock(side_effect=[_snap(1), _snap(2)]),
    )
    monkeypatch.setattr(
        review_compare, "compare_daily_review_snapshots",
        MagicMock(return_value=_comparison(
            comparison_status="unavailable",
            unknowns=["基础快照市场广度不可用"],
            warnings=["schema"],
        )),
    )
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 1, "target_id": 2},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["comparison_status"] == "unavailable"
    assert data["unknowns"]
    assert data["warnings"]


# ---------------------------------------------------------------------------
# 6–8 404 与同 ID
# ---------------------------------------------------------------------------

def test_base_missing_404(monkeypatch):
    get_snap = MagicMock(return_value=None)
    cmp = MagicMock()
    monkeypatch.setattr(review_history, "get_review_history_snapshot", get_snap)
    monkeypatch.setattr(review_compare, "compare_daily_review_snapshots", cmp)
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 9, "target_id": 10},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "未找到基础每日复盘历史快照"
    get_snap.assert_called_once_with(9)
    cmp.assert_not_called()


def test_target_missing_404(monkeypatch):
    get_snap = MagicMock(side_effect=[_snap(1), None])
    cmp = MagicMock()
    monkeypatch.setattr(review_history, "get_review_history_snapshot", get_snap)
    monkeypatch.setattr(review_compare, "compare_daily_review_snapshots", cmp)
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 1, "target_id": 99},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "未找到目标每日复盘历史快照"
    assert get_snap.call_count == 2
    cmp.assert_not_called()


def test_same_id_allowed(monkeypatch):
    get_snap = MagicMock(side_effect=[_snap(5), _snap(5)])
    cmp = MagicMock(return_value=_comparison())
    monkeypatch.setattr(review_history, "get_review_history_snapshot", get_snap)
    monkeypatch.setattr(review_compare, "compare_daily_review_snapshots", cmp)
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 5, "target_id": 5},
    )
    assert r.status_code == 200
    get_snap.assert_has_calls([call(5), call(5)])
    assert get_snap.call_count == 2
    cmp.assert_called_once()


# ---------------------------------------------------------------------------
# 9–12 422
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("params", [
    {"base_id": 0, "target_id": 1},
    {"base_id": 1, "target_id": 0},
    {"base_id": -1, "target_id": 1},
    {"base_id": 1, "target_id": -1},
])
def test_invalid_id_422(params):
    r = client.get("/api/daily-review/history/compare", params=params)
    assert r.status_code == 422


def test_id_type_error_422():
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": "abc", "target_id": 1},
    )
    assert r.status_code == 422


@pytest.mark.parametrize("board_limit", [0, 21])
def test_invalid_board_limit_422(board_limit):
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 1, "target_id": 2, "board_limit": board_limit},
    )
    assert r.status_code == 422


@pytest.mark.parametrize("stock_limit", [0, 31])
def test_invalid_stock_limit_422(stock_limit):
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 1, "target_id": 2, "stock_limit": stock_limit},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 13–17 错误映射
# ---------------------------------------------------------------------------

def test_history_value_error_400(monkeypatch):
    monkeypatch.setattr(
        review_history, "get_review_history_snapshot",
        MagicMock(side_effect=ValueError("snapshot_id 必须是正整数")),
    )
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 1, "target_id": 2},
    )
    assert r.status_code == 400
    assert "正整数" in r.json()["detail"]


def test_compare_value_error_400(monkeypatch):
    monkeypatch.setattr(
        review_history, "get_review_history_snapshot",
        MagicMock(side_effect=[_snap(1), _snap(2)]),
    )
    monkeypatch.setattr(
        review_compare, "compare_daily_review_snapshots",
        MagicMock(side_effect=ValueError("internal secret payload xyz")),
    )
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 1, "target_id": 2},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "每日复盘快照比较参数或数据结构无效"
    assert "secret" not in r.json()["detail"]
    assert "payload" not in r.json()["detail"]


def test_compare_type_error_400(monkeypatch):
    monkeypatch.setattr(
        review_history, "get_review_history_snapshot",
        MagicMock(side_effect=[_snap(1), _snap(2)]),
    )
    monkeypatch.setattr(
        review_compare, "compare_daily_review_snapshots",
        MagicMock(side_effect=TypeError("bad type")),
    )
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 1, "target_id": 2},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "每日复盘快照比较参数或数据结构无效"


def test_db_runtime_error_hides_path(monkeypatch):
    monkeypatch.setattr(
        review_history, "get_review_history_snapshot",
        MagicMock(side_effect=RuntimeError(
            r"database locked at C:\Users\secret\daily_reviews.sqlite3"
        )),
    )
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 1, "target_id": 2},
    )
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert detail == "每日复盘历史快照比较失败"
    assert "database locked" not in detail
    assert "secret" not in detail
    assert "sqlite" not in detail.lower()
    assert "C:" not in detail


def test_compare_unexpected_500(monkeypatch):
    monkeypatch.setattr(
        review_history, "get_review_history_snapshot",
        MagicMock(side_effect=[_snap(1), _snap(2)]),
    )
    monkeypatch.setattr(
        review_compare, "compare_daily_review_snapshots",
        MagicMock(side_effect=RuntimeError("boom internal")),
    )
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 1, "target_id": 2},
    )
    assert r.status_code == 500
    assert r.json()["detail"] == "每日复盘历史快照比较失败"
    assert "boom" not in r.json()["detail"]


# ---------------------------------------------------------------------------
# 18–22 路由与副作用
# ---------------------------------------------------------------------------

def test_compare_route_not_captured_as_id(monkeypatch):
    get_snap = MagicMock(side_effect=[_snap(1), _snap(2)])
    cmp = MagicMock(return_value=_comparison())
    monkeypatch.setattr(review_history, "get_review_history_snapshot", get_snap)
    monkeypatch.setattr(review_compare, "compare_daily_review_snapshots", cmp)
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 1, "target_id": 2},
    )
    assert r.status_code == 200
    cmp.assert_called_once()
    # 不是把 "compare" 当 snapshot_id 的 422
    assert r.status_code != 422


def test_api_does_not_call_store(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("must not call store/sqlite")

    monkeypatch.setattr(review_store, "get_daily_review_snapshot", _boom)
    monkeypatch.setattr("sqlite3.connect", _boom)
    monkeypatch.setattr(
        review_history, "get_review_history_snapshot",
        MagicMock(side_effect=[_snap(1), _snap(2)]),
    )
    monkeypatch.setattr(
        review_compare, "compare_daily_review_snapshots",
        MagicMock(return_value=_comparison()),
    )
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 1, "target_id": 2},
    )
    assert r.status_code == 200


def test_does_not_accept_db_path(monkeypatch):
    get_snap = MagicMock(side_effect=[_snap(1), _snap(2)])
    monkeypatch.setattr(review_history, "get_review_history_snapshot", get_snap)
    monkeypatch.setattr(
        review_compare, "compare_daily_review_snapshots",
        MagicMock(return_value=_comparison()),
    )
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 1, "target_id": 2, "db_path": r"C:\fake.sqlite3"},
    )
    assert r.status_code == 200
    for c in get_snap.call_args_list:
        assert c == call(1) or c == call(2)
        assert "db_path" not in (c.kwargs or {})
        assert len(c.args) == 1


def test_no_save_or_ai_side_effects(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("side effect forbidden")

    monkeypatch.setattr(review_history, "save_current_daily_review", _boom)
    monkeypatch.setattr(daily_review, "generate_daily_review", _boom)
    monkeypatch.setattr(chat_layer, "prepare_daily_review_messages", _boom)
    monkeypatch.setattr(
        review_history, "get_review_history_snapshot",
        MagicMock(side_effect=[_snap(1), _snap(2)]),
    )
    monkeypatch.setattr(
        review_compare, "compare_daily_review_snapshots",
        MagicMock(return_value=_comparison()),
    )
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 1, "target_id": 2},
    )
    assert r.status_code == 200


def test_call_order(monkeypatch):
    order: list[str] = []

    def get_snap(sid: int):
        order.append(f"get:{sid}")
        return _snap(sid)

    def cmp(base, target, **kwargs):
        order.append("compare")
        return _comparison()

    monkeypatch.setattr(review_history, "get_review_history_snapshot", get_snap)
    monkeypatch.setattr(review_compare, "compare_daily_review_snapshots", cmp)
    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": 3, "target_id": 7},
    )
    assert r.status_code == 200
    assert order == ["get:3", "get:7", "compare"]


# ---------------------------------------------------------------------------
# 真实 SQLite 有限集成
# ---------------------------------------------------------------------------

def test_real_sqlite_compare_integration(tmp_path, monkeypatch):
    db = tmp_path / "reviews.sqlite3"
    monkeypatch.setenv(review_history.REVIEW_DB_ENV, str(db))

    def _review(up: int, trade_date: str, gen: str) -> dict:
        return {
            "schema_version": "daily-review-v0.1",
            "generated_at": gen,
            "trade_date": trade_date,
            "data_cutoff": None,
            "status": "normal",
            "warnings": [],
            "data_health": {"components": {"breadth": "normal", "emotion": "normal"}},
            "market_environment": {
                "breadth": {
                    "status": "normal",
                    "data": {
                        "stock_count": 5000,
                        "valid_count": 4900,
                        "up_count": up,
                        "down_count": 100,
                        "flat_count": 0,
                        "up_ratio": 0.5,
                        "up_3pct_count": 1,
                        "down_3pct_count": 1,
                        "total_amount": 1e12,
                        "amount_valid_count": 4900,
                    },
                }
            },
            "short_term_emotion": {
                "status": "normal",
                "data": {
                    "zt_count": 10, "dt_count": 1, "zb_count": 2,
                    "max_boards": 3, "lianban_count": 4,
                    "seal_rate": 0.8, "break_rate": 0.2,
                    "promotion_rate": 0.3, "yzt_count": 5,
                },
            },
            "sector_rotation": {
                "industry": {
                    "status": "normal",
                    "data": {
                        "top": [{"code": "BK1", "name": "半导体", "change_pct": 1}],
                        "bottom": [{"code": "BK9", "name": "地产", "change_pct": -1}],
                    },
                },
                "concept": {
                    "status": "normal",
                    "data": {
                        "top": [{"code": "C1", "name": "AI", "change_pct": 2}],
                        "bottom": [{"code": "C9", "name": "白酒", "change_pct": -1}],
                    },
                },
                "region": {
                    "status": "normal",
                    "data": {
                        "top": [{"code": "R1", "name": "上海", "change_pct": 1}],
                        "bottom": [{"code": "R9", "name": "深圳", "change_pct": -1}],
                    },
                },
                "highlights": {
                    "strongest_industry": {"code": "BK1", "name": "半导体", "change_pct": 1},
                    "weakest_industry": {"code": "BK9", "name": "地产", "change_pct": -1},
                    "strongest_concept": {"code": "C1", "name": "AI", "change_pct": 2},
                    "weakest_concept": {"code": "C9", "name": "白酒", "change_pct": -1},
                    "strongest_region": {"code": "R1", "name": "上海", "change_pct": 1},
                    "weakest_region": {"code": "R9", "name": "深圳", "change_pct": -1},
                },
            },
            "capital_activity": {
                "total_amount": 1e12,
                "amount_valid_count": 4900,
                "amount_top": [{"code": "600519", "name": "茅台", "amount": 1e10}],
                "high_turnover": [{"code": "300001", "name": "特锐德", "turnover_pct": 20}],
            },
        }

    # 保存两份不同内容
    monkeypatch.setattr(
        daily_review, "generate_daily_review",
        lambda: _review(100, "2026-07-20", "2026-07-20 15:00:00"),
    )
    r1 = client.post("/api/daily-review/history/save")
    assert r1.status_code == 200
    id1 = r1.json()["data"]["snapshot"]["id"]

    monkeypatch.setattr(
        daily_review, "generate_daily_review",
        lambda: _review(130, "2026-07-21", "2026-07-21 15:00:00"),
    )
    r2 = client.post("/api/daily-review/history/save")
    assert r2.status_code == 200
    id2 = r2.json()["data"]["snapshot"]["id"]

    r = client.get(
        "/api/daily-review/history/compare",
        params={"base_id": id1, "target_id": id2},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["base"]["id"] == id1
    assert data["target"]["id"] == id2
    assert data["market_breadth"]["up_count"]["base"] == 100
    assert data["market_breadth"]["up_count"]["target"] == 130
    assert data["market_breadth"]["up_count"]["delta"] == 30
    assert db.exists()
