"""BK-11 Slice 3e 快照选择器纯计算层测试。

不发起任何 live 请求。覆盖选择规则、合同、异常边界、输入不可变性。
"""
from __future__ import annotations

import copy
import inspect
import sys

import pytest

sys.path.insert(0, "backend")

import short_term_snapshot_selector as selector  # noqa: E402


def _row(trade_date="2026-07-31", session="final",
         schema_version="short-term-daily-facts-v0.1",
         stored_at="2026-08-05T10:00:00.000000Z", **overrides):
    row = {
        "trade_date": trade_date,
        "session": session,
        "schema_version": schema_version,
        "stored_at": stored_at,
    }
    row.update(overrides)
    return row


def _assert_shape(result):
    assert set(result.keys()) == {
        "schema_version", "status", "reason_codes", "warnings",
        "limitations", "selection",
    }
    assert result["schema_version"] == selector.SCHEMA_VERSION
    assert isinstance(result["selection"], list)


def _assert_invalid(result, reason_code):
    _assert_shape(result)
    assert result["status"] == "invalid"
    assert result["reason_codes"] == [reason_code, "OUTPUT_SUPPRESSED"]
    assert result["selection"] == []


# ---------------------------------------------------------------------------
# 1. 公开合同
# ---------------------------------------------------------------------------

class TestPublicContract:
    def test_constants(self):
        assert selector.SCHEMA_VERSION == "short-term-snapshot-selector-v0.1"

    def test_all(self):
        assert selector.__all__ == ["SCHEMA_VERSION", "select_daily_snapshots"]

    def test_signature(self):
        sig = inspect.signature(selector.select_daily_snapshots)
        assert list(sig.parameters) == ["rows"]
        for parameter in sig.parameters.values():
            assert parameter.default is inspect.Parameter.empty


# ---------------------------------------------------------------------------
# 2. 选择规则
# ---------------------------------------------------------------------------

class TestSelection:
    def test_single_row(self):
        result = selector.select_daily_snapshots([_row()])
        _assert_shape(result)
        assert result["status"] == "normal"
        assert result["reason_codes"] == []
        assert result["selection"] == [{
            "trade_date": "2026-07-31",
            "session": "final",
            "schema_version": "short-term-daily-facts-v0.1",
            "stored_at": "2026-08-05T10:00:00.000000Z",
        }]

    def test_final_preferred(self):
        rows = [
            _row(session="afternoon_session"),
            _row(session="final", stored_at="2026-08-05T09:00:00.000000Z"),
            _row(session="close_pending", stored_at="2026-08-05T11:00:00.000000Z"),
        ]
        result = selector.select_daily_snapshots(rows)
        assert result["selection"][0]["session"] == "final"

    def test_final_beats_unavailable(self):
        # final 硬优先：unavailable 是最高非 final 状态，但不能胜过 final
        rows = [
            _row(session="unavailable", stored_at="2026-08-05T11:00:00.000000Z"),
            _row(session="final", stored_at="2026-08-05T09:00:00.000000Z"),
        ]
        result = selector.select_daily_snapshots(rows)
        assert result["selection"][0]["session"] == "final"

    def test_unavailable_wins_without_final(self):
        rows = [
            _row(session="close_pending"),
            _row(session="unavailable"),
        ]
        result = selector.select_daily_snapshots(rows)
        assert result["selection"][0]["session"] == "unavailable"

    def test_session_time_order_when_no_final(self):
        rows = [
            _row(session="midday_break"),
            _row(session="morning_session"),
        ]
        result = selector.select_daily_snapshots(rows)
        assert result["selection"][0]["session"] == "midday_break"

    def test_latest_stored_at_wins_same_session(self):
        rows = [
            _row(session="final", stored_at="2026-08-05T10:00:00.000000Z"),
            _row(session="final", stored_at="2026-08-05T11:30:00.000000Z"),
        ]
        result = selector.select_daily_snapshots(rows)
        assert result["selection"][0]["stored_at"] == \
            "2026-08-05T11:30:00.000000Z"

    def test_multiple_dates_sorted(self):
        rows = [
            _row(trade_date="2026-07-30"),
            _row(trade_date="2026-07-31", session="afternoon_session"),
            _row(trade_date="2026-07-29"),
        ]
        result = selector.select_daily_snapshots(rows)
        assert [item["trade_date"] for item in result["selection"]] == [
            "2026-07-29", "2026-07-30", "2026-07-31"]

    def test_unsorted_input_deterministic(self):
        rows = [
            _row(trade_date="2026-07-31", session="final"),
            _row(trade_date="2026-07-30", session="afternoon_session"),
            _row(trade_date="2026-07-31", session="afternoon_session"),
        ]
        first = selector.select_daily_snapshots(rows)
        second = selector.select_daily_snapshots(list(reversed(rows)))
        assert first["selection"] == second["selection"]

    def test_deterministic_tie_break(self):
        rows = [
            _row(session="final", stored_at="2026-08-05T10:00:00.000000Z"),
            _row(session="final", stored_at="2026-08-05T10:00:00.000000Z"),
        ]
        result = selector.select_daily_snapshots(rows)
        assert len(result["selection"]) == 1
        assert result["selection"][0]["session"] == "final"

    def test_schema_only_tie_permutation_consistent(self):
        # 同 (date, session, stored_at) 仅 schema_version 不同：
        # 输入顺序不得影响结果（全序决胜键）
        rows = [
            _row(schema_version="short-term-daily-facts-v0.1"),
            _row(schema_version="short-term-daily-facts-v0.2"),
        ]
        first = selector.select_daily_snapshots(rows)
        second = selector.select_daily_snapshots(list(reversed(rows)))
        assert first["selection"] == second["selection"]
        assert first["selection"][0]["schema_version"] == \
            "short-term-daily-facts-v0.2"


# ---------------------------------------------------------------------------
# 3. 合同
# ---------------------------------------------------------------------------

class TestContract:
    @pytest.mark.parametrize("bad", [None, "x", 1, {"a": 1}, ("a",)])
    def test_not_list(self, bad):
        _assert_invalid(selector.select_daily_snapshots(bad),
                        "INPUT_CONTRACT_INVALID")

    def test_empty_list_invalid(self):
        _assert_invalid(selector.select_daily_snapshots([]),
                        "INPUT_CONTRACT_INVALID")

    def test_non_dict_row(self):
        _assert_invalid(selector.select_daily_snapshots(["x"]),
                        "ROW_CONTRACT_INVALID")

    def test_missing_field(self):
        row = _row()
        del row["stored_at"]
        _assert_invalid(selector.select_daily_snapshots([row]),
                        "ROW_CONTRACT_INVALID")

    def test_extra_field(self):
        _assert_invalid(
            selector.select_daily_snapshots([_row(extra=1)]),
            "ROW_CONTRACT_INVALID")

    @pytest.mark.parametrize("bad", ["2026-7-31", "20260731", "2026-02-30",
                                     20260731, None])
    def test_bad_trade_date(self, bad):
        _assert_invalid(
            selector.select_daily_snapshots([_row(trade_date=bad)]),
            "ROW_CONTRACT_INVALID")

    @pytest.mark.parametrize("bad", ["draft", 1, None])
    def test_bad_session(self, bad):
        _assert_invalid(
            selector.select_daily_snapshots([_row(session=bad)]),
            "ROW_CONTRACT_INVALID")

    def test_bad_schema_version(self):
        _assert_invalid(
            selector.select_daily_snapshots([_row(schema_version="")]),
            "ROW_CONTRACT_INVALID")

    def test_bad_stored_at(self):
        _assert_invalid(
            selector.select_daily_snapshots([_row(stored_at="")]),
            "ROW_CONTRACT_INVALID")


# ---------------------------------------------------------------------------
# 4. 不可变性与异常边界
# ---------------------------------------------------------------------------

class TestImmutabilityAndExceptions:
    def test_input_deep_equal_after(self):
        rows = [_row(), _row(session="afternoon_session")]
        original = copy.deepcopy(rows)
        selector.select_daily_snapshots(rows)
        assert rows == original

    def test_no_shared_references(self):
        rows = [_row(), _row(session="afternoon_session")]
        result = selector.select_daily_snapshots(rows)
        assert result["selection"] is not rows
        result["selection"].append({"trade_date": "x", "session": "x",
                                    "schema_version": "x", "stored_at": "x"})
        assert len(rows) == 2

    @pytest.mark.parametrize("target", [
        "_validate_row",
        "_select_per_date",
        "_normal_envelope",
    ])
    @pytest.mark.parametrize("exc", [
        RuntimeError("boom-selector"),
        ValueError("boom-selector"),
        TypeError("boom-selector"),
    ])
    def test_ordinary_exception_fixed_fallback(self, monkeypatch, target, exc):
        def raiser(*args, **kwargs):
            raise exc
        monkeypatch.setattr(selector, target, raiser)
        result = selector.select_daily_snapshots([_row()])
        _assert_invalid(result, reason_code="INPUT_CONTRACT_INVALID")
        assert "boom-selector" not in repr(result)
        assert "boom-selector" not in str(result)

    @pytest.mark.parametrize("target", [
        "_validate_row",
        "_select_per_date",
        "_normal_envelope",
    ])
    @pytest.mark.parametrize("exc", [
        KeyboardInterrupt(),
        SystemExit(1),
        GeneratorExit(),
    ])
    def test_process_control_propagates(self, monkeypatch, target, exc):
        def raiser(*args, **kwargs):
            raise exc
        monkeypatch.setattr(selector, target, raiser)
        with pytest.raises(type(exc)):
            selector.select_daily_snapshots([_row()])

    def test_cross_call_isolation(self):
        rows = [_row(), _row(session="afternoon_session")]
        first = selector.select_daily_snapshots(rows)
        second = selector.select_daily_snapshots(rows)
        first["limitations"].append("mutated")
        first["selection"].append({"trade_date": "x", "session": "x",
                                   "schema_version": "x", "stored_at": "x"})
        assert second["limitations"] == [
            "deterministic per-date snapshot selection",
            "prefers final session, then session time order, then latest stored_at",
            "does not read storage or live data",
            "does not validate snapshot content semantics",
            "no per-stock cross-day identity tracking",
        ]
        assert len(second["selection"]) == 1
