"""review_history 历史服务层离线测试（Mock + tmp_path，不写真实用户目录）。"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import daily_review
import review_db_path
import review_history
import review_store
from review_history import (
    REVIEW_DB_ENV,
    ReviewSnapshotNotSavableError,
    get_latest_review_history_snapshot,
    get_review_history_snapshot,
    list_review_history,
    resolve_review_db_path,
    save_current_daily_review,
    validate_review_for_history,
)


def _review(**overrides) -> dict:
    base = {
        "schema_version": "daily-review-v0.1",
        "generated_at": "2026-07-21 15:30:00",
        "trade_date": "2026-07-21",
        "data_cutoff": None,
        "status": "normal",
        "warnings": ["提示A"],
        "data_health": {"components": {"indices": "normal", "breadth": "normal"}},
        "market_environment": {
            "breadth": {"status": "normal", "data": {"up_count": 100, "down_count": 50}}
        },
        "sector_rotation": {"industry": {"status": "normal"}},
        "short_term_emotion": {"status": "normal", "data": {"zt_count": 10}},
        "capital_activity": {"total_amount": 0},
    }
    base.update(overrides)
    return base


def _store_result(**overrides) -> dict:
    base = {
        "id": 7,
        "inserted": True,
        "trade_date": "2026-07-21",
        "schema_version": "daily-review-v0.1",
        "generated_at": "2026-07-21 15:30:00",
        "status": "normal",
        "payload_hash": "abc",
        "created_at": "2026-07-21 15:31:00",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1–6 路径解析
# ---------------------------------------------------------------------------

def test_explicit_path_overrides_env(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit" / "a.sqlite3"
    monkeypatch.setenv(REVIEW_DB_ENV, str(tmp_path / "from_env.sqlite3"))
    got = resolve_review_db_path(explicit)
    assert got == explicit.resolve()
    assert got != Path(os.environ[REVIEW_DB_ENV]).resolve()


def test_env_path_used_when_no_explicit(tmp_path, monkeypatch):
    env_p = tmp_path / "env_dir" / "daily.sqlite3"
    monkeypatch.setenv(REVIEW_DB_ENV, str(env_p))
    got = resolve_review_db_path(None)
    assert got == env_p.resolve()


def test_blank_env_falls_through_to_default(monkeypatch):
    monkeypatch.setenv(REVIEW_DB_ENV, "   ")
    with patch.object(review_db_path, "_default_review_db_path") as mock_def:
        mock_def.return_value = Path("/tmp/default.sqlite3").resolve()
        got = resolve_review_db_path(None)
    assert got == mock_def.return_value
    mock_def.assert_called_once()


def test_default_paths_by_platform(monkeypatch):
    monkeypatch.delenv(REVIEW_DB_ENV, raising=False)

    # Windows LOCALAPPDATA
    with (
        patch.object(review_db_path.sys, "platform", "win32"),
        patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\Dino\AppData\Local"}, clear=False),
    ):
        monkeypatch.delenv("USERPROFILE", raising=False)
        p = review_db_path._default_review_db_path()
        assert p.name == "daily_reviews.sqlite3"
        assert "VibeResearch" in p.parts
        assert "AppData" in str(p) or "Local" in p.parts

    # Windows fallback USERPROFILE
    with (
        patch.object(review_db_path.sys, "platform", "win32"),
        patch.dict(
            os.environ,
            {"USERPROFILE": r"C:\Users\Dino", "LOCALAPPDATA": ""},
            clear=False,
        ),
    ):
        # ensure empty LOCALAPPDATA
        monkeypatch.setenv("LOCALAPPDATA", "")
        monkeypatch.setenv("USERPROFILE", r"C:\Users\Dino")
        p = review_db_path._default_review_db_path()
        assert p.as_posix().endswith("VibeResearch/daily_reviews.sqlite3") or (
            "VibeResearch" in p.parts and p.name == "daily_reviews.sqlite3"
        )

    # macOS
    with (
        patch.object(review_db_path.sys, "platform", "darwin"),
        patch.object(Path, "home", return_value=Path("/Users/dino")),
    ):
        p = review_db_path._default_review_db_path()
        assert "Application Support" in p.parts
        assert "VibeResearch" in p.parts
        assert p.name == "daily_reviews.sqlite3"

    # Linux XDG_DATA_HOME
    with (
        patch.object(review_db_path.sys, "platform", "linux"),
        patch.dict(os.environ, {"XDG_DATA_HOME": "/custom/data"}, clear=False),
    ):
        monkeypatch.setenv("XDG_DATA_HOME", "/custom/data")
        p = review_db_path._default_review_db_path()
        assert "vibe-research" in p.parts
        assert p.name == "daily_reviews.sqlite3"
        assert "custom" in p.parts or "data" in p.parts

    # Linux default ~/.local/share
    with (
        patch.object(review_db_path.sys, "platform", "linux"),
        patch.object(Path, "home", return_value=Path("/home/dino")),
    ):
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        # also clear if set empty
        monkeypatch.setenv("XDG_DATA_HOME", "")
        p = review_db_path._default_review_db_path()
        assert ".local" in p.parts or "share" in p.parts
        assert "vibe-research" in p.parts
        assert p.name == "daily_reviews.sqlite3"


def test_resolve_has_no_side_effects(tmp_path, monkeypatch):
    target = tmp_path / "no_create" / "x.sqlite3"
    monkeypatch.delenv(REVIEW_DB_ENV, raising=False)
    got = resolve_review_db_path(target)
    assert got == target.resolve()
    assert not target.exists()
    assert not target.parent.exists()


def test_windows_default_has_no_side_effects(tmp_path, monkeypatch):
    local_app_data = tmp_path / "Local"
    monkeypatch.delenv(REVIEW_DB_ENV, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    with patch.object(review_db_path.sys, "platform", "win32"):
        got = resolve_review_db_path()

    expected = (local_app_data / "VibeResearch" / "daily_reviews.sqlite3").resolve()
    assert got == expected
    assert not expected.parent.exists()
    assert not expected.exists()
    for suffix in ("-wal", "-shm", "-journal"):
        assert not expected.with_name(expected.name + suffix).exists()


def test_tilde_expand(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    # On Windows expanduser uses USERPROFILE more than HOME; use explicit ~ via Path
    home = Path.home()
    rel = "~/vibe_test_reviews.sqlite3"
    got = resolve_review_db_path(rel)
    assert got == (home / "vibe_test_reviews.sqlite3").resolve()
    assert not got.exists()


@pytest.mark.parametrize("bad", ["", "   ", 123])
def test_illegal_path_inputs(bad):
    if bad in ("", "   "):
        with pytest.raises(ValueError, match="db_path 不能为空"):
            resolve_review_db_path(bad)
    else:
        with pytest.raises(TypeError, match="db_path 必须是字符串、Path或None"):
            resolve_review_db_path(bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 7–17 保存策略
# ---------------------------------------------------------------------------

def test_save_normal(monkeypatch):
    review = _review(status="normal")
    store_ret = _store_result(inserted=True)
    gen = MagicMock(return_value=review)
    save = MagicMock(return_value=store_ret)
    monkeypatch.setattr(daily_review, "generate_daily_review", gen)
    monkeypatch.setattr(review_store, "save_daily_review_snapshot", save)

    out = save_current_daily_review(db_path=Path("/tmp/x.db"))
    gen.assert_called_once_with()
    save.assert_called_once()
    assert save.call_args[0][0] is review
    assert out["snapshot"]["id"] == 7
    assert out["snapshot"]["inserted"] is True
    assert out["review_status"] == "normal"
    assert out["review_warnings"] == ["提示A"]


def test_save_partial_keeps_warnings(monkeypatch):
    review = _review(status="partial", warnings=["[概念] timeout", "w2"])
    store_ret = _store_result(status="partial")
    monkeypatch.setattr(daily_review, "generate_daily_review", lambda: review)
    monkeypatch.setattr(
        review_store, "save_daily_review_snapshot", MagicMock(return_value=store_ret)
    )
    out = save_current_daily_review(db_path=Path("/tmp/p.db"))
    assert out["review_status"] == "partial"
    assert out["review_warnings"] == ["[概念] timeout", "w2"]


def test_unavailable_rejected(tmp_path, monkeypatch):
    review = _review(status="unavailable")
    save = MagicMock()
    monkeypatch.setattr(daily_review, "generate_daily_review", lambda: review)
    monkeypatch.setattr(review_store, "save_daily_review_snapshot", save)
    with pytest.raises(ReviewSnapshotNotSavableError, match="核心数据不可用"):
        save_current_daily_review(db_path=tmp_path / "u.db")
    save.assert_not_called()
    assert not (tmp_path / "u.db").exists()


@pytest.mark.parametrize("td", [None, ""])
def test_missing_trade_date_rejected(tmp_path, monkeypatch, td):
    review = _review(trade_date=td)
    save = MagicMock()
    monkeypatch.setattr(daily_review, "generate_daily_review", lambda: review)
    monkeypatch.setattr(review_store, "save_daily_review_snapshot", save)
    with pytest.raises(ReviewSnapshotNotSavableError, match="交易日期"):
        save_current_daily_review(db_path=tmp_path / "t.db")
    save.assert_not_called()


@pytest.mark.parametrize("td", ["20260721", "2026-02-30"])
def test_illegal_trade_date_rejected(tmp_path, monkeypatch, td):
    review = _review(trade_date=td)
    save = MagicMock()
    monkeypatch.setattr(daily_review, "generate_daily_review", lambda: review)
    monkeypatch.setattr(review_store, "save_daily_review_snapshot", save)
    with pytest.raises(ReviewSnapshotNotSavableError):
        save_current_daily_review(db_path=tmp_path / "bad.db")
    save.assert_not_called()


def test_validate_not_dict():
    with pytest.raises(ReviewSnapshotNotSavableError, match="字典"):
        validate_review_for_history([])  # type: ignore[arg-type]


def test_save_does_not_mutate_review(monkeypatch):
    review = _review()
    before = copy.deepcopy(review)
    monkeypatch.setattr(daily_review, "generate_daily_review", lambda: review)
    monkeypatch.setattr(
        review_store,
        "save_daily_review_snapshot",
        MagicMock(return_value=_store_result()),
    )
    save_current_daily_review(db_path=Path("/tmp/m.db"))
    assert review == before


def test_single_generate_and_save(monkeypatch):
    gen = MagicMock(return_value=_review())
    save = MagicMock(return_value=_store_result())
    monkeypatch.setattr(daily_review, "generate_daily_review", gen)
    monkeypatch.setattr(review_store, "save_daily_review_snapshot", save)
    save_current_daily_review(db_path=Path("/tmp/once.db"))
    assert gen.call_count == 1
    assert save.call_count == 1


def test_does_not_call_market_layer(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("market/astock must not be called")

    monkeypatch.setattr("market.get_market_breadth", _boom)
    monkeypatch.setattr("market.get_board_ranking", _boom)
    monkeypatch.setattr("market.get_short_term_emotion", _boom)
    monkeypatch.setattr("astock.index_quote", _boom)
    monkeypatch.setattr(daily_review, "generate_daily_review", lambda: _review())
    monkeypatch.setattr(
        review_store,
        "save_daily_review_snapshot",
        MagicMock(return_value=_store_result()),
    )
    out = save_current_daily_review(db_path=Path("/tmp/mkt.db"))
    assert out["snapshot"]["inserted"] is True


def test_dedupe_inserted_false_passthrough(monkeypatch):
    monkeypatch.setattr(daily_review, "generate_daily_review", lambda: _review())
    monkeypatch.setattr(
        review_store,
        "save_daily_review_snapshot",
        MagicMock(return_value=_store_result(inserted=False, id=3)),
    )
    out = save_current_daily_review(db_path=Path("/tmp/d.db"))
    assert out["snapshot"]["inserted"] is False
    assert out["snapshot"]["id"] == 3


def test_response_does_not_expose_db_path(monkeypatch):
    monkeypatch.setattr(daily_review, "generate_daily_review", lambda: _review())
    monkeypatch.setattr(
        review_store,
        "save_daily_review_snapshot",
        MagicMock(return_value=_store_result()),
    )
    out = save_current_daily_review(db_path=Path("/secret/path.db"))
    blob = str(out)
    assert "db_path" not in out
    assert "database" not in out
    assert "path" not in out
    assert "/secret" not in blob
    assert "review" not in out  # 不返回完整 review


# ---------------------------------------------------------------------------
# 18–21 读取包装
# ---------------------------------------------------------------------------

def test_get_by_id_wrapper(tmp_path, monkeypatch):
    expected = {"id": 1, "review": {"status": "normal"}}
    mock = MagicMock(return_value=expected)
    monkeypatch.setattr(review_store, "get_daily_review_snapshot", mock)
    db = tmp_path / "r.db"
    got = get_review_history_snapshot(1, db_path=db)
    assert got is expected
    mock.assert_called_once()
    assert mock.call_args[0][0] == 1
    assert mock.call_args[0][1] == db.resolve()


def test_latest_wrapper(tmp_path, monkeypatch):
    mock = MagicMock(return_value={"id": 2})
    monkeypatch.setattr(review_store, "get_latest_daily_review_snapshot", mock)
    db = tmp_path / "r.db"
    get_latest_review_history_snapshot(db_path=db)
    assert mock.call_args[0][0] == db.resolve()
    assert mock.call_args[1].get("trade_date") is None or mock.call_args.kwargs.get("trade_date") is None

    mock.reset_mock()
    get_latest_review_history_snapshot(trade_date="2026-07-21", db_path=db)
    # trade_date 以关键字或位置传入均可
    args, kwargs = mock.call_args
    assert args[0] == db.resolve()
    assert kwargs.get("trade_date") == "2026-07-21" or (len(args) > 1 and args[1] == "2026-07-21")


def test_list_wrapper(tmp_path, monkeypatch):
    mock = MagicMock(return_value=[])
    monkeypatch.setattr(review_store, "list_daily_review_snapshots", mock)
    db = tmp_path / "r.db"
    list_review_history(trade_date="2026-07-21", limit=10, offset=5, db_path=db)
    args, kwargs = mock.call_args
    assert args[0] == db.resolve()
    assert kwargs.get("trade_date") == "2026-07-21" or (len(args) > 1)
    # 确保 limit/offset 传到底层
    assert kwargs.get("limit") == 10 or (len(args) > 2 and args[2] == 10)
    assert kwargs.get("offset") == 5 or (len(args) > 3 and args[3] == 5)


def test_reads_do_not_generate_review(monkeypatch, tmp_path):
    gen = MagicMock(side_effect=AssertionError("must not generate"))
    monkeypatch.setattr(daily_review, "generate_daily_review", gen)
    monkeypatch.setattr(review_store, "get_daily_review_snapshot", MagicMock(return_value=None))
    monkeypatch.setattr(review_store, "get_latest_daily_review_snapshot", MagicMock(return_value=None))
    monkeypatch.setattr(review_store, "list_daily_review_snapshots", MagicMock(return_value=[]))
    db = tmp_path / "r.db"
    get_review_history_snapshot(1, db_path=db)
    get_latest_review_history_snapshot(db_path=db)
    list_review_history(db_path=db)
    gen.assert_not_called()


# ---------------------------------------------------------------------------
# 22. 真实 SQLite 集成（tmp_path，无网络）
# ---------------------------------------------------------------------------

def test_real_sqlite_roundtrip(tmp_path, monkeypatch):
    db = tmp_path / "integration" / "daily.sqlite3"
    review = _review(status="normal", warnings=["中文提示"])
    monkeypatch.setattr(daily_review, "generate_daily_review", lambda: review)

    out = save_current_daily_review(db_path=db)
    assert out["snapshot"]["inserted"] is True
    assert db.exists()

    sid = out["snapshot"]["id"]
    listed = list_review_history(db_path=db)
    assert len(listed) == 1
    assert listed[0]["id"] == sid
    assert "review" not in listed[0]

    latest = get_latest_review_history_snapshot(db_path=db)
    assert latest is not None
    assert latest["id"] == sid
    assert latest["review"]["warnings"] == ["中文提示"]

    by_id = get_review_history_snapshot(sid, db_path=db)
    assert by_id is not None
    assert by_id["review"] == review

    # 去重
    out2 = save_current_daily_review(db_path=db)
    assert out2["snapshot"]["inserted"] is False
    assert out2["snapshot"]["id"] == sid
