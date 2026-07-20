"""每日复盘历史 HTTP API 离线测试（Mock 服务层，不写真实用户目录、不联网）。"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app as app_module
import chat as chat_layer
import daily_review
import review_history
import review_store

client = TestClient(app_module.app)

_LLM = {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "baseURL": "http://example.test/v1",
    "apiKey": "sk-test",
}


def _save_payload(*, inserted=True, status="normal"):
    return {
        "snapshot": {
            "id": 1,
            "inserted": inserted,
            "trade_date": "2026-07-21",
            "schema_version": "daily-review-v0.1",
            "generated_at": "2026-07-21 15:30:00",
            "status": status,
            "payload_hash": "hash1",
            "created_at": "2026-07-21 15:31:00",
        },
        "review_status": status,
        "review_warnings": ["w1"],
    }


def _full_snapshot(sid=1):
    return {
        "id": sid,
        "trade_date": "2026-07-21",
        "schema_version": "daily-review-v0.1",
        "generated_at": "2026-07-21 15:30:00",
        "data_cutoff": None,
        "status": "normal",
        "payload_hash": "hash1",
        "created_at": "2026-07-21 15:31:00",
        "review": {
            "schema_version": "daily-review-v0.1",
            "trade_date": "2026-07-21",
            "generated_at": "2026-07-21 15:30:00",
            "status": "normal",
            "warnings": [],
            "data_health": {"components": {"indices": "normal"}},
            "market_environment": {},
            "sector_rotation": {},
            "short_term_emotion": {},
            "capital_activity": {},
        },
    }


def _meta_item(sid=1):
    return {
        "id": sid,
        "trade_date": "2026-07-21",
        "schema_version": "daily-review-v0.1",
        "generated_at": "2026-07-21 15:30:00",
        "data_cutoff": None,
        "status": "normal",
        "payload_hash": "hash1",
        "created_at": "2026-07-21 15:31:00",
    }


# ---------------------------------------------------------------------------
# 1–5 保存
# ---------------------------------------------------------------------------

def test_save_success_inserted_true(monkeypatch):
    mock = MagicMock(return_value=_save_payload(inserted=True))
    monkeypatch.setattr(review_history, "save_current_daily_review", mock)
    r = client.post("/api/daily-review/history/save")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"data"}
    assert body["data"]["snapshot"]["inserted"] is True
    assert body["data"]["snapshot"]["id"] == 1
    assert body["data"]["review_status"] == "normal"
    assert body["data"]["review_warnings"] == ["w1"]
    mock.assert_called_once_with()


def test_save_duplicate_inserted_false(monkeypatch):
    mock = MagicMock(return_value=_save_payload(inserted=False))
    monkeypatch.setattr(review_history, "save_current_daily_review", mock)
    r = client.post("/api/daily-review/history/save")
    assert r.status_code == 200
    assert r.json()["data"]["snapshot"]["inserted"] is False
    assert r.json()["data"]["snapshot"]["inserted"] is not True


def test_save_unavailable_409(monkeypatch):
    mock = MagicMock(
        side_effect=review_history.ReviewSnapshotNotSavableError(
            "每日复盘核心数据不可用，不保存历史快照"
        )
    )
    monkeypatch.setattr(review_history, "save_current_daily_review", mock)
    r = client.post("/api/daily-review/history/save")
    assert r.status_code == 409
    assert r.json()["detail"] == "每日复盘核心数据不可用，不保存历史快照"
    assert "snapshot" not in r.json()


def test_save_missing_trade_date_409(monkeypatch):
    mock = MagicMock(
        side_effect=review_history.ReviewSnapshotNotSavableError(
            "每日复盘缺少明确交易日期，不保存历史快照"
        )
    )
    monkeypatch.setattr(review_history, "save_current_daily_review", mock)
    r = client.post("/api/daily-review/history/save")
    assert r.status_code == 409
    assert "交易日期" in r.json()["detail"]


def test_save_unexpected_error_hides_path(monkeypatch):
    mock = MagicMock(
        side_effect=RuntimeError(
            r"database locked at C:\secret\daily_reviews.sqlite3"
        )
    )
    monkeypatch.setattr(review_history, "save_current_daily_review", mock)
    r = client.post("/api/daily-review/history/save")
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert detail == "每日复盘历史保存失败"
    assert "database locked" not in detail
    assert "secret" not in detail
    assert "sqlite" not in detail.lower()
    assert "C:" not in detail
    assert "daily_reviews" not in detail


# ---------------------------------------------------------------------------
# 6–12 列表
# ---------------------------------------------------------------------------

def test_list_defaults(monkeypatch):
    mock = MagicMock(return_value=[_meta_item()])
    monkeypatch.setattr(review_history, "list_review_history", mock)
    r = client.get("/api/daily-review/history")
    assert r.status_code == 200
    data = r.json()["data"]
    assert set(data.keys()) == {"items", "trade_date", "limit", "offset", "count"}
    assert data["trade_date"] is None
    assert data["limit"] == 30
    assert data["offset"] == 0
    assert data["count"] == 1
    mock.assert_called_once_with(trade_date=None, limit=30, offset=0)


def test_list_with_filters(monkeypatch):
    mock = MagicMock(return_value=[_meta_item(), _meta_item(2)])
    monkeypatch.setattr(review_history, "list_review_history", mock)
    r = client.get(
        "/api/daily-review/history",
        params={"trade_date": "2026-07-21", "limit": 10, "offset": 20},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["trade_date"] == "2026-07-21"
    assert data["limit"] == 10
    assert data["offset"] == 20
    assert data["count"] == 2
    mock.assert_called_once_with(trade_date="2026-07-21", limit=10, offset=20)


def test_list_empty_200(monkeypatch):
    monkeypatch.setattr(review_history, "list_review_history", MagicMock(return_value=[]))
    r = client.get("/api/daily-review/history")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["items"] == []
    assert data["count"] == 0


def test_list_no_full_review(monkeypatch):
    monkeypatch.setattr(
        review_history, "list_review_history", MagicMock(return_value=[_meta_item()])
    )
    r = client.get("/api/daily-review/history")
    text = r.text
    data = r.json()["data"]
    for item in data["items"]:
        assert "review" not in item
        assert "payload_json" not in item
    assert "payload_json" not in text or "payload_json" not in json.dumps(data)


def test_list_invalid_date_400(monkeypatch):
    monkeypatch.setattr(
        review_history,
        "list_review_history",
        MagicMock(side_effect=ValueError("trade_date 必须是非空字符串且格式为YYYY-MM-DD")),
    )
    r = client.get("/api/daily-review/history", params={"trade_date": "bad"})
    assert r.status_code == 400


@pytest.mark.parametrize("params", [
    {"limit": 0},
    {"limit": 101},
    {"offset": -1},
])
def test_list_invalid_pagination_422(params):
    r = client.get("/api/daily-review/history", params=params)
    assert r.status_code == 422


def test_list_unexpected_500(monkeypatch):
    monkeypatch.setattr(
        review_history,
        "list_review_history",
        MagicMock(side_effect=RuntimeError(r"fail at C:\secret\db.sqlite3")),
    )
    r = client.get("/api/daily-review/history")
    assert r.status_code == 500
    assert r.json()["detail"] == "每日复盘历史列表读取失败"
    assert "secret" not in r.json()["detail"]
    assert "sqlite" not in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 13–16 最新
# ---------------------------------------------------------------------------

def test_latest_ok(monkeypatch):
    snap = _full_snapshot(9)
    mock = MagicMock(return_value=snap)
    monkeypatch.setattr(review_history, "get_latest_review_history_snapshot", mock)
    r = client.get("/api/daily-review/history/latest")
    assert r.status_code == 200
    assert r.json()["data"] == snap
    mock.assert_called_once_with(trade_date=None)


def test_latest_with_trade_date(monkeypatch):
    mock = MagicMock(return_value=_full_snapshot())
    monkeypatch.setattr(review_history, "get_latest_review_history_snapshot", mock)
    r = client.get(
        "/api/daily-review/history/latest",
        params={"trade_date": "2026-07-21"},
    )
    assert r.status_code == 200
    mock.assert_called_once_with(trade_date="2026-07-21")


def test_latest_not_found_404(monkeypatch):
    monkeypatch.setattr(
        review_history, "get_latest_review_history_snapshot", MagicMock(return_value=None)
    )
    r = client.get("/api/daily-review/history/latest")
    assert r.status_code == 404
    assert r.json()["detail"] == "未找到每日复盘历史快照"


def test_latest_invalid_date_400(monkeypatch):
    monkeypatch.setattr(
        review_history,
        "get_latest_review_history_snapshot",
        MagicMock(side_effect=ValueError("trade_date 必须是非空字符串且格式为YYYY-MM-DD")),
    )
    r = client.get(
        "/api/daily-review/history/latest",
        params={"trade_date": "20260721"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 17–19 详情
# ---------------------------------------------------------------------------

def test_detail_ok(monkeypatch):
    snap = _full_snapshot(7)
    mock = MagicMock(return_value=snap)
    monkeypatch.setattr(review_history, "get_review_history_snapshot", mock)
    r = client.get("/api/daily-review/history/7")
    assert r.status_code == 200
    assert r.json()["data"] == snap
    mock.assert_called_once_with(7)


def test_detail_not_found_404(monkeypatch):
    monkeypatch.setattr(
        review_history, "get_review_history_snapshot", MagicMock(return_value=None)
    )
    r = client.get("/api/daily-review/history/99")
    assert r.status_code == 404
    assert r.json()["detail"] == "未找到每日复盘历史快照"


def test_detail_id_zero_400(monkeypatch):
    monkeypatch.setattr(
        review_history,
        "get_review_history_snapshot",
        MagicMock(side_effect=ValueError("snapshot_id 必须是正整数")),
    )
    r = client.get("/api/daily-review/history/0")
    assert r.status_code == 400


def test_detail_non_int_422():
    r = client.get("/api/daily-review/history/abc")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 20. latest 不被动态 ID 截获
# ---------------------------------------------------------------------------

def test_latest_route_not_captured_as_id(monkeypatch):
    latest = MagicMock(return_value=_full_snapshot())
    detail = MagicMock(return_value=_full_snapshot())
    monkeypatch.setattr(review_history, "get_latest_review_history_snapshot", latest)
    monkeypatch.setattr(review_history, "get_review_history_snapshot", detail)
    r = client.get("/api/daily-review/history/latest")
    assert r.status_code == 200
    latest.assert_called_once()
    detail.assert_not_called()


# ---------------------------------------------------------------------------
# 21. API 不直接调用存储层
# ---------------------------------------------------------------------------

def test_api_only_uses_service_layer(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("app must not call review_store or sqlite3")

    monkeypatch.setattr(review_store, "save_daily_review_snapshot", _boom)
    monkeypatch.setattr(review_store, "get_daily_review_snapshot", _boom)
    monkeypatch.setattr(review_store, "get_latest_daily_review_snapshot", _boom)
    monkeypatch.setattr(review_store, "list_daily_review_snapshots", _boom)
    monkeypatch.setattr("sqlite3.connect", _boom)

    monkeypatch.setattr(
        review_history, "save_current_daily_review",
        MagicMock(return_value=_save_payload()),
    )
    monkeypatch.setattr(
        review_history, "list_review_history", MagicMock(return_value=[])
    )
    monkeypatch.setattr(
        review_history, "get_latest_review_history_snapshot",
        MagicMock(return_value=_full_snapshot()),
    )
    monkeypatch.setattr(
        review_history, "get_review_history_snapshot",
        MagicMock(return_value=_full_snapshot(3)),
    )

    assert client.post("/api/daily-review/history/save").status_code == 200
    assert client.get("/api/daily-review/history").status_code == 200
    assert client.get("/api/daily-review/history/latest").status_code == 200
    assert client.get("/api/daily-review/history/3").status_code == 200


# ---------------------------------------------------------------------------
# 22. 不接受 db_path
# ---------------------------------------------------------------------------

def test_does_not_accept_db_path(monkeypatch):
    save = MagicMock(return_value=_save_payload())
    listing = MagicMock(return_value=[])
    monkeypatch.setattr(review_history, "save_current_daily_review", save)
    monkeypatch.setattr(review_history, "list_review_history", listing)

    r1 = client.post(
        "/api/daily-review/history/save",
        params={"db_path": r"C:\fake.sqlite3"},
    )
    assert r1.status_code == 200
    save.assert_called_once_with()  # 无 db_path 参数

    r2 = client.get(
        "/api/daily-review/history",
        params={"db_path": r"C:\fake.sqlite3"},
    )
    assert r2.status_code == 200
    listing.assert_called_once_with(trade_date=None, limit=30, offset=0)


# ---------------------------------------------------------------------------
# 23–24. 不自动保存
# ---------------------------------------------------------------------------

def test_get_daily_review_does_not_auto_save(monkeypatch):
    save = MagicMock(side_effect=AssertionError("must not save"))
    monkeypatch.setattr(review_history, "save_current_daily_review", save)
    monkeypatch.setattr(
        daily_review,
        "generate_daily_review",
        lambda: {
            "schema_version": "daily-review-v0.1",
            "status": "normal",
            "trade_date": "2026-07-21",
            "generated_at": "2026-07-21 15:00:00",
            "warnings": [],
            "data_health": {"components": {}},
            "market_environment": {},
            "sector_rotation": {},
            "short_term_emotion": {},
            "capital_activity": {},
        },
    )
    r = client.get("/api/daily-review")
    assert r.status_code == 200
    save.assert_not_called()


def test_analyze_does_not_auto_save(monkeypatch):
    save = MagicMock(side_effect=AssertionError("must not save"))
    monkeypatch.setattr(review_history, "save_current_daily_review", save)
    monkeypatch.setattr(
        chat_layer,
        "prepare_daily_review_messages",
        MagicMock(return_value=[
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
        ]),
    )

    def _stream(*_a, **_k):
        yield {"type": "done", "trace": [], "rounds": 1}

    monkeypatch.setattr(chat_layer, "stream_messages", _stream)
    r = client.post(
        "/api/daily-review/analyze",
        json={"llm": _LLM},
    )
    assert r.status_code == 200
    save.assert_not_called()


# ---------------------------------------------------------------------------
# 25. 单次调用
# ---------------------------------------------------------------------------

def test_each_endpoint_calls_service_once(monkeypatch):
    save = MagicMock(return_value=_save_payload())
    listing = MagicMock(return_value=[])
    latest = MagicMock(return_value=_full_snapshot())
    detail = MagicMock(return_value=_full_snapshot(5))
    monkeypatch.setattr(review_history, "save_current_daily_review", save)
    monkeypatch.setattr(review_history, "list_review_history", listing)
    monkeypatch.setattr(review_history, "get_latest_review_history_snapshot", latest)
    monkeypatch.setattr(review_history, "get_review_history_snapshot", detail)

    assert client.post("/api/daily-review/history/save").status_code == 200
    assert save.call_count == 1

    assert client.get("/api/daily-review/history").status_code == 200
    assert listing.call_count == 1

    assert client.get("/api/daily-review/history/latest").status_code == 200
    assert latest.call_count == 1

    assert client.get("/api/daily-review/history/5").status_code == 200
    assert detail.call_count == 1


# ---------------------------------------------------------------------------
# 真实 SQLite 集成（tmp_path + 环境变量）
# ---------------------------------------------------------------------------

def test_real_sqlite_api_roundtrip(tmp_path, monkeypatch):
    db = tmp_path / "reviews.sqlite3"
    monkeypatch.setenv(review_history.REVIEW_DB_ENV, str(db))

    review = {
        "schema_version": "daily-review-v0.1",
        "generated_at": "2026-07-21 15:30:00",
        "trade_date": "2026-07-21",
        "data_cutoff": None,
        "status": "normal",
        "warnings": ["中文"],
        "data_health": {"components": {"indices": "normal", "breadth": "normal"}},
        "market_environment": {
            "breadth": {"status": "normal", "data": {"up_count": 1, "down_count": 2}}
        },
        "sector_rotation": {"industry": {"status": "normal"}},
        "short_term_emotion": {"status": "normal", "data": {"zt_count": 3}},
        "capital_activity": {"total_amount": 0},
    }
    monkeypatch.setattr(daily_review, "generate_daily_review", lambda: review)

    r_save = client.post("/api/daily-review/history/save")
    assert r_save.status_code == 200
    sid = r_save.json()["data"]["snapshot"]["id"]
    assert r_save.json()["data"]["snapshot"]["inserted"] is True
    assert db.exists()

    r_list = client.get("/api/daily-review/history")
    assert r_list.status_code == 200
    assert r_list.json()["data"]["count"] == 1
    assert "review" not in r_list.json()["data"]["items"][0]

    r_latest = client.get("/api/daily-review/history/latest")
    assert r_latest.status_code == 200
    assert r_latest.json()["data"]["id"] == sid
    assert r_latest.json()["data"]["review"]["warnings"] == ["中文"]

    r_detail = client.get(f"/api/daily-review/history/{sid}")
    assert r_detail.status_code == 200
    assert r_detail.json()["data"]["review"]["trade_date"] == "2026-07-21"
