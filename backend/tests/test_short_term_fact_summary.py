"""BK-11 Slice 3c 多日事实摘要纯计算层测试。

不发起任何 live 请求。覆盖统计数学、状态分布、窗口合同、
异常边界、输入不可变性与输出引用隔离。
"""
from __future__ import annotations

import copy
import inspect
import sys

import pytest

sys.path.insert(0, "backend")

import short_term_fact_summary as summary  # noqa: E402


def _facts(**overrides):
    facts = {
        "advance_count": 100,
        "decline_count": 80,
        "flat_count": 20,
        "suspended_count": 5,
        "eligible_count": 205,
        "valid_count": 200,
        "up_ratio": 0.5,
        "limit_up_count": 10,
        "limit_down_count": 2,
        "failed_limit_up_count": 3,
        "touched_limit_up_count": 13,
        "sealed_limit_up_count": 10,
        "failed_board_rate": 0.2308,
        "seal_rate": 0.7692,
    }
    facts.update(overrides)
    return facts


def _ladder(max_boards=4, lianban_count=3, rows=None):
    if rows is None:
        rows = [{"boards": 2, "count": 2}, {"boards": 4, "count": 1}]
    return {
        "max_boards": max_boards,
        "lianban_count": lianban_count,
        "ladder": rows,
    }


def _gap(glc=1, gsc=1, lgw=1, fgb=3, continuous=False):
    return {
        "gap_level_count": glc,
        "gap_segment_count": gsc,
        "largest_gap_width": lgw,
        "first_gap_board": fgb,
        "is_continuous": continuous,
    }


def _envelope(trade_date="2026-07-30", status="normal", session="final",
              facts=None, ladder=None, gap=None, sections=None):
    if sections is None:
        sections = {
            "facts": {"schema_version": "short-term-market-facts-v0.1",
                      "status": status,
                      "facts": facts if facts is not None else _facts()},
            "ladder": None if ladder is None else {
                "schema_version": "short-term-limit-up-ladder-v0.1",
                "status": status, "metrics": ladder},
            "gap": None if gap is None else {
                "schema_version": "short-term-ladder-gap-v0.1",
                "status": status, "metrics": gap},
        }
    return {
        "schema_version": "short-term-daily-facts-v0.1",
        "trade_date": trade_date,
        "session": session,
        "is_final": session == "final",
        "source_ids": ["eastmoney_getTopicZTPool"],
        "fetched_at": f"{trade_date}T15:10:00.000000Z",
        "snapshot_at": f"{trade_date}T15:10:00.000000Z",
        "status": status,
        "reason_codes": [],
        "warnings": [],
        "limitations": ["fixed"],
        "source_schema_version": "short-term-limit-up-final-snapshot-v0.1",
        "source_status": "normal",
        "source_reason_codes": [],
        "sections": sections,
    }


def _assert_shape(result):
    assert set(result.keys()) == {
        "schema_version", "window", "status", "reason_codes", "warnings",
        "limitations", "stats",
    }
    assert result["schema_version"] == summary.SCHEMA_VERSION
    assert set(result["window"].keys()) == {
        "count", "first_trade_date", "last_trade_date"}


def _assert_invalid(result, reason_code):
    _assert_shape(result)
    assert result["status"] == "invalid"
    assert result["reason_codes"] == [reason_code, "OUTPUT_SUPPRESSED"]
    assert result["stats"] is None


# ---------------------------------------------------------------------------
# 1. 公开合同
# ---------------------------------------------------------------------------

class TestPublicContract:
    def test_constants(self):
        assert summary.SCHEMA_VERSION == "short-term-fact-summary-v0.1"

    def test_all(self):
        assert summary.__all__ == ["SCHEMA_VERSION", "compute_fact_summary"]

    def test_signature(self):
        sig = inspect.signature(summary.compute_fact_summary)
        assert list(sig.parameters) == ["envelopes"]
        for parameter in sig.parameters.values():
            assert parameter.default is inspect.Parameter.empty


# ---------------------------------------------------------------------------
# 2. 统计数学
# ---------------------------------------------------------------------------

class TestStats:
    def _window(self):
        return [
            _envelope("2026-07-28",
                      facts=_facts(limit_up_count=8, advance_count=90,
                                   failed_board_rate=0.3, seal_rate=0.7,
                                   up_ratio=0.45),
                      ladder=_ladder(2, 1, [{"boards": 2, "count": 1}]),
                      gap=_gap(0, 0, 0, None, True)),
            _envelope("2026-07-29",
                      facts=_facts(limit_up_count=12, advance_count=110,
                                   failed_board_rate=0.2, seal_rate=0.8,
                                   up_ratio=0.55),
                      ladder=_ladder(4, 3, [{"boards": 2, "count": 2},
                                            {"boards": 4, "count": 1}]),
                      gap=_gap(1, 1, 1, 3, False)),
            _envelope("2026-07-30",
                      facts=_facts(limit_up_count=10, advance_count=100,
                                   failed_board_rate=0.2308, seal_rate=0.7692,
                                   up_ratio=0.5),
                      ladder=_ladder(5, 5, [{"boards": 2, "count": 3},
                                            {"boards": 5, "count": 2}]),
                      gap=_gap(0, 0, 0, None, True)),
        ]

    def test_fact_stats(self):
        result = summary.compute_fact_summary(self._window())
        _assert_shape(result)
        assert result["status"] == "normal"
        assert result["reason_codes"] == []
        assert result["window"] == {
            "count": 3,
            "first_trade_date": "2026-07-28",
            "last_trade_date": "2026-07-30",
        }
        lu = result["stats"]["facts"]["limit_up_count"]
        assert lu == {"min": 8, "max": 12, "avg": 10.0, "count": 3}
        adv = result["stats"]["facts"]["advance_count"]
        assert adv == {"min": 90, "max": 110, "avg": 100.0, "count": 3}
        fbr = result["stats"]["facts"]["failed_board_rate"]
        assert fbr["min"] == 0.2
        assert fbr["max"] == 0.3
        assert fbr["avg"] == round((0.3 + 0.2 + 0.2308) / 3, 4)
        assert fbr["count"] == 3
        assert result["stats"]["status_distribution"] == {
            "normal": 3, "partial": 0, "unavailable": 0, "invalid": 0}

    def test_ladder_gap_stats(self):
        result = summary.compute_fact_summary(self._window())
        ladder = result["stats"]["ladder"]
        assert ladder["max_boards"] == {
            "min": 2, "max": 5, "avg": round((2 + 4 + 5) / 3, 4), "count": 3}
        assert ladder["lianban_count"] == {
            "min": 1, "max": 5, "avg": 3.0, "count": 3}
        assert ladder["days_with_ladder"] == 3
        gap = result["stats"]["gap"]
        assert gap["gap_level_count"] == {
            "min": 0, "max": 1, "avg": round(1 / 3, 4), "count": 3}
        assert gap["largest_gap_width"] == {
            "min": 0, "max": 1, "avg": round(1 / 3, 4), "count": 3}
        assert gap["days_with_gap_section"] == 3
        assert gap["continuous_days"] == 2

    def test_null_fields_skipped(self):
        window = [
            _envelope("2026-07-28", facts=_facts(up_ratio=None),
                      ladder=_ladder(), gap=_gap()),
            _envelope("2026-07-29", facts=_facts(up_ratio=0.6),
                      ladder=_ladder(), gap=_gap()),
        ]
        result = summary.compute_fact_summary(window)
        up = result["stats"]["facts"]["up_ratio"]
        assert up == {"min": 0.6, "max": 0.6, "avg": 0.6, "count": 1}
        assert result["stats"]["facts"]["limit_up_count"]["count"] == 2

    def test_missing_ladder_gap_sections(self):
        window = [
            _envelope("2026-07-28", ladder=None, gap=None),
            _envelope("2026-07-29", ladder=None, gap=None),
        ]
        result = summary.compute_fact_summary(window)
        assert result["status"] == "normal"
        ladder = result["stats"]["ladder"]
        assert ladder["max_boards"]["count"] == 0
        assert ladder["max_boards"]["min"] is None
        assert ladder["days_with_ladder"] == 0
        gap = result["stats"]["gap"]
        assert gap["gap_level_count"]["count"] == 0
        assert gap["days_with_gap_section"] == 0
        assert gap["continuous_days"] == 0
        assert result["stats"]["facts"]["limit_up_count"]["count"] == 2


# ---------------------------------------------------------------------------
# 3. 状态分布与窗口合同
# ---------------------------------------------------------------------------

class TestStatusAndWindow:
    def test_partial_days_not_in_stats(self):
        window = [
            _envelope("2026-07-28",
                      facts=_facts(limit_up_count=8),
                      ladder=_ladder(), gap=_gap()),
            _envelope("2026-07-29", status="partial",
                      facts=_facts(limit_up_count=999),
                      ladder=_ladder(9, 9), gap=_gap(9, 9, 9, 9, False)),
        ]
        result = summary.compute_fact_summary(window)
        assert result["status"] == "partial"
        assert result["reason_codes"] == [
            "SOURCE_PARTIAL", "OUTPUT_SUPPRESSED"]
        assert result["stats"]["status_distribution"] == {
            "normal": 1, "partial": 1, "unavailable": 0, "invalid": 0}
        assert result["stats"]["facts"]["limit_up_count"] == {
            "min": 8, "max": 8, "avg": 8.0, "count": 1}
        assert result["stats"]["ladder"]["max_boards"]["max"] == 4

    def test_unavailable_window(self):
        window = [
            _envelope("2026-07-28", status="unavailable"),
            _envelope("2026-07-29"),
        ]
        result = summary.compute_fact_summary(window)
        assert result["status"] == "unavailable"
        assert result["reason_codes"] == [
            "SOURCE_UNAVAILABLE", "OUTPUT_SUPPRESSED"]
        assert result["stats"]["status_distribution"]["unavailable"] == 1

    def test_invalid_envelope_status_fail_closed(self):
        window = [
            _envelope("2026-07-28", status="invalid"),
            _envelope("2026-07-29"),
        ]
        result = summary.compute_fact_summary(window)
        _assert_invalid(result, reason_code="ENVELOPE_CONTRACT_INVALID")

    @pytest.mark.parametrize("bad", [None, "x", 1, ("a",), {"a": 1}])
    def test_not_list(self, bad):
        result = summary.compute_fact_summary(bad)
        _assert_invalid(result, reason_code="INPUT_CONTRACT_INVALID")

    def test_empty_list_invalid(self):
        result = summary.compute_fact_summary([])
        _assert_invalid(result, reason_code="INPUT_CONTRACT_INVALID")

    def test_duplicate_snapshot_invalid(self):
        window = [
            _envelope("2026-07-28"),
            _envelope("2026-07-28"),
            _envelope("2026-07-29"),
        ]
        result = summary.compute_fact_summary(window)
        _assert_invalid(result, reason_code="DUPLICATE_SNAPSHOT_INVALID")

    def test_multi_session_sorted_accepted(self):
        window = [
            _envelope("2026-07-28", session="afternoon_session"),
            _envelope("2026-07-28", session="final"),
            _envelope("2026-07-29"),
        ]
        result = summary.compute_fact_summary(window)
        assert result["status"] == "normal"
        assert result["window"]["count"] == 3

    def test_unsorted_invalid(self):
        result = summary.compute_fact_summary([
            _envelope("2026-07-29"),
            _envelope("2026-07-28"),
        ])
        _assert_invalid(result, reason_code="DATE_ORDER_INVALID")

    def test_wrong_schema(self):
        envelope = _envelope("2026-07-28")
        envelope["schema_version"] = "wrong"
        result = summary.compute_fact_summary([envelope])
        _assert_invalid(result, reason_code="ENVELOPE_CONTRACT_INVALID")

    def test_missing_sections(self):
        envelope = _envelope("2026-07-28")
        del envelope["sections"]
        result = summary.compute_fact_summary([envelope])
        _assert_invalid(result, reason_code="ENVELOPE_CONTRACT_INVALID")


# ---------------------------------------------------------------------------
# 4. 输出合同与不可变性
# ---------------------------------------------------------------------------

class TestOutputAndImmutability:
    def test_limitations_fixed(self):
        result = summary.compute_fact_summary([_envelope("2026-07-28")])
        assert result["limitations"] == [
            "descriptive window summary of daily-facts envelopes",
            "stats computed over normal-status days only",
            "does not compute layered promotion rates",
            "does not validate consecutive-limit-up semantics",
            "no per-stock cross-day identity tracking",
            "does not evaluate legal zero",
        ]

    def test_inputs_deep_equal_after(self):
        window = [
            _envelope("2026-07-28", ladder=_ladder(), gap=_gap()),
            _envelope("2026-07-29", ladder=_ladder(5, 5), gap=_gap()),
        ]
        original = copy.deepcopy(window)
        summary.compute_fact_summary(window)
        assert window == original

    def test_no_shared_references(self):
        window = [_envelope("2026-07-28", ladder=_ladder(), gap=_gap())]
        result = summary.compute_fact_summary(window)
        stats = result["stats"]
        assert stats is not window[0]["sections"]
        assert stats["status_distribution"] is not window[0]["sections"]
        stats["status_distribution"]["normal"] = 99
        assert window[0]["status"] == "normal"


# ---------------------------------------------------------------------------
# 5. 异常边界与进程控制
# ---------------------------------------------------------------------------

class TestExceptionBoundary:
    HELPERS = [
        "_validate_envelope",
        "_compute_stats",
        "_collect_fact_stats",
        "_collect_ladder_stats",
        "_normal_envelope",
    ]

    @pytest.mark.parametrize("target", HELPERS)
    @pytest.mark.parametrize("exc", [
        RuntimeError("boom-fact-summary"),
        ValueError("boom-fact-summary"),
        TypeError("boom-fact-summary"),
    ])
    def test_ordinary_exception_fixed_fallback(self, monkeypatch, target, exc):
        def raiser(*args, **kwargs):
            raise exc
        monkeypatch.setattr(summary, target, raiser)
        result = summary.compute_fact_summary(
            [_envelope("2026-07-28", ladder=_ladder(), gap=_gap())])
        _assert_invalid(result, reason_code="INPUT_CONTRACT_INVALID")
        assert "boom-fact-summary" not in repr(result)
        assert "boom-fact-summary" not in str(result)

    @pytest.mark.parametrize("target", HELPERS)
    @pytest.mark.parametrize("exc", [
        KeyboardInterrupt(),
        SystemExit(1),
        GeneratorExit(),
    ])
    def test_process_control_propagates(self, monkeypatch, target, exc):
        def raiser(*args, **kwargs):
            raise exc
        monkeypatch.setattr(summary, target, raiser)
        with pytest.raises(type(exc)):
            summary.compute_fact_summary(
                [_envelope("2026-07-28", ladder=_ladder(), gap=_gap())])

    def test_emergency_exact_literal(self, monkeypatch):
        def raiser(*args, **kwargs):
            raise RuntimeError("secret")
        monkeypatch.setattr(summary, "_evaluate", raiser)
        result = summary.compute_fact_summary(
            [_envelope("2026-07-28", ladder=_ladder(), gap=_gap())])
        _assert_invalid(result, reason_code="INPUT_CONTRACT_INVALID")
        assert result["window"] == {"count": None, "first_trade_date": None,
                                    "last_trade_date": None}


# ---------------------------------------------------------------------------
# 6. 跨调用隔离
# ---------------------------------------------------------------------------

class TestCrossCallIsolation:
    def test_cross_call(self):
        first = summary.compute_fact_summary(
            [_envelope("2026-07-28", ladder=_ladder(), gap=_gap())])
        second = summary.compute_fact_summary(
            [_envelope("2026-07-28", ladder=_ladder(), gap=_gap())])
        first["limitations"].append("mutated")
        first["stats"]["facts"]["limit_up_count"]["max"] = 999
        assert second["limitations"] == [
            "descriptive window summary of daily-facts envelopes",
            "stats computed over normal-status days only",
            "does not compute layered promotion rates",
            "does not validate consecutive-limit-up semantics",
            "no per-stock cross-day identity tracking",
            "does not evaluate legal zero",
        ]
        assert second["stats"]["facts"]["limit_up_count"]["max"] == 10
