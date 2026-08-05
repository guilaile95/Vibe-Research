"""BK-11 Slice 3b 日事实历史比较纯计算层测试。

不发起任何 live 请求。覆盖 delta 数学、状态组合、日期顺序、合同、
异常边界、输入不可变性与输出引用隔离。
"""
from __future__ import annotations

import copy
import inspect
import sys

import pytest

sys.path.insert(0, "backend")

import short_term_fact_compare as compare  # noqa: E402


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


def _ladder(max_boards=4, lianban_count=3, ladder=None):
    if ladder is None:
        ladder = [{"boards": 2, "count": 2}, {"boards": 4, "count": 1}]
    return {
        "max_boards": max_boards,
        "lianban_count": lianban_count,
        "ladder": ladder,
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
                      "status": status, "facts": facts if facts is not None
                      else _facts()},
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
        "schema_version", "previous_trade_date", "current_trade_date",
        "status", "reason_codes", "warnings", "limitations",
        "section_status", "deltas",
    }
    assert result["schema_version"] == compare.SCHEMA_VERSION
    assert set(result["section_status"].keys()) == {
        "facts", "ladder", "gap"}
    assert set(result["deltas"].keys()) == {"facts", "ladder", "gap"}


def _assert_invalid(result, reason_code="ENVELOPE_CONTRACT_INVALID"):
    _assert_shape(result)
    assert result["status"] == "invalid"
    assert result["reason_codes"] == [reason_code, "OUTPUT_SUPPRESSED"]
    assert result["deltas"] == {"facts": None, "ladder": None, "gap": None}


# ---------------------------------------------------------------------------
# 1. 公开合同
# ---------------------------------------------------------------------------

class TestPublicContract:
    def test_constants(self):
        assert compare.SCHEMA_VERSION == "short-term-fact-compare-v0.1"

    def test_all(self):
        assert compare.__all__ == ["SCHEMA_VERSION", "compute_fact_compare"]

    def test_signature(self):
        sig = inspect.signature(compare.compute_fact_compare)
        assert list(sig.parameters) == [
            "previous_envelope", "current_envelope"]
        for parameter in sig.parameters.values():
            assert parameter.default is inspect.Parameter.empty


# ---------------------------------------------------------------------------
# 2. facts delta
# ---------------------------------------------------------------------------

class TestFactsDelta:
    def test_full_delta(self):
        prev = _envelope("2026-07-30",
                         facts=_facts(advance_count=100,
                                      limit_up_count=10,
                                      failed_board_rate=0.2308),
                         ladder=_ladder(), gap=_gap())
        curr = _envelope("2026-07-31",
                         facts=_facts(advance_count=120,
                                      limit_up_count=15,
                                      failed_board_rate=0.2),
                         ladder=_ladder(), gap=_gap())
        result = compare.compute_fact_compare(prev, curr)
        _assert_shape(result)
        assert result["status"] == "normal"
        assert result["reason_codes"] == []
        d = result["deltas"]["facts"]
        assert d["advance_count"] == 20
        assert d["limit_up_count"] == 5
        assert d["failed_board_rate"] == -0.0308
        assert d["decline_count"] == 0
        assert result["section_status"]["facts"] == "normal"

    def test_null_field_delta_null(self):
        prev = _envelope("2026-07-30", facts=_facts(up_ratio=None))
        curr = _envelope("2026-07-31", facts=_facts(up_ratio=0.6))
        result = compare.compute_fact_compare(prev, curr)
        assert result["deltas"]["facts"]["up_ratio"] is None
        assert result["deltas"]["facts"]["advance_count"] == 0

    def test_float_precision(self):
        prev = _envelope("2026-07-30", facts=_facts(seal_rate=0.7692))
        curr = _envelope("2026-07-31", facts=_facts(seal_rate=0.75))
        result = compare.compute_fact_compare(prev, curr)
        assert result["deltas"]["facts"]["seal_rate"] == -0.0192


# ---------------------------------------------------------------------------
# 3. ladder / gap delta
# ---------------------------------------------------------------------------

class TestLadderGapDelta:
    def test_ladder_changes(self):
        prev = _envelope(
            "2026-07-30",
            ladder=_ladder(4, 3, [{"boards": 2, "count": 2},
                                  {"boards": 4, "count": 1}]),
            gap=_gap(1, 1, 1, 3, False))
        curr = _envelope(
            "2026-07-31",
            ladder=_ladder(5, 5, [{"boards": 2, "count": 3},
                                  {"boards": 4, "count": 1},
                                  {"boards": 5, "count": 1}]),
            gap=_gap(0, 0, 0, None, True))
        result = compare.compute_fact_compare(prev, curr)
        assert result["status"] == "normal"
        ld = result["deltas"]["ladder"]
        assert ld["max_boards_delta"] == 1
        assert ld["lianban_count_delta"] == 2
        assert ld["prev_occupied_boards"] == [2, 4]
        assert ld["curr_occupied_boards"] == [2, 4, 5]
        assert ld["board_level_changes"] == [
            {"boards": 2, "prev_count": 2, "curr_count": 3, "delta": 1},
            {"boards": 4, "prev_count": 1, "curr_count": 1, "delta": 0},
            {"boards": 5, "prev_count": 0, "curr_count": 1, "delta": 1},
        ]
        gd = result["deltas"]["gap"]
        assert gd["gap_level_count_delta"] == -1
        assert gd["gap_segment_count_delta"] == -1
        assert gd["largest_gap_width_delta"] == -1
        assert gd["prev_first_gap_board"] == 3
        assert gd["curr_first_gap_board"] is None
        assert gd["prev_is_continuous"] is False
        assert gd["curr_is_continuous"] is True

    def test_ladder_section_missing(self):
        prev = _envelope("2026-07-30", ladder=None, gap=None)
        curr = _envelope("2026-07-31", ladder=None, gap=None)
        result = compare.compute_fact_compare(prev, curr)
        assert result["section_status"]["ladder"] == "unavailable"
        assert result["section_status"]["gap"] == "unavailable"
        assert result["deltas"]["ladder"] is None
        assert result["deltas"]["gap"] is None
        assert result["status"] == "unavailable"
        assert result["reason_codes"] == ["OUTPUT_SUPPRESSED"]

    def test_ladder_missing_on_one_side(self):
        prev = _envelope("2026-07-30", ladder=None, gap=None)
        curr = _envelope("2026-07-31",
                         ladder=_ladder(), gap=_gap())
        result = compare.compute_fact_compare(prev, curr)
        assert result["section_status"]["ladder"] == "unavailable"
        assert result["deltas"]["ladder"] is None


# ---------------------------------------------------------------------------
# 4. 状态组合与日期顺序
# ---------------------------------------------------------------------------

class TestStatusAndOrder:
    def test_equal_dates_invalid(self):
        prev = _envelope("2026-07-31")
        curr = _envelope("2026-07-31")
        result = compare.compute_fact_compare(prev, curr)
        _assert_invalid(result, reason_code="DATE_ORDER_INVALID")

    def test_reversed_dates_invalid(self):
        result = compare.compute_fact_compare(
            _envelope("2026-07-31"), _envelope("2026-07-30"))
        _assert_invalid(result, reason_code="DATE_ORDER_INVALID")

    def test_previous_unavailable(self):
        prev = _envelope("2026-07-30", status="unavailable")
        curr = _envelope("2026-07-31")
        result = compare.compute_fact_compare(prev, curr)
        assert result["status"] == "unavailable"
        assert result["reason_codes"] == [
            "SOURCE_UNAVAILABLE", "OUTPUT_SUPPRESSED"]

    def test_previous_partial(self):
        prev = _envelope("2026-07-30", status="partial",
                         ladder=_ladder(), gap=_gap())
        curr = _envelope("2026-07-31",
                         ladder=_ladder(), gap=_gap())
        result = compare.compute_fact_compare(prev, curr)
        assert result["status"] == "partial"
        assert result["reason_codes"] == [
            "SOURCE_PARTIAL", "OUTPUT_SUPPRESSED"]
        # partial 时 facts 仍逐字段计算（缺失字段 null）
        assert result["deltas"]["facts"]["advance_count"] == 0

    def test_invalid_envelope_status(self):
        prev = _envelope("2026-07-30", status="invalid")
        curr = _envelope("2026-07-31")
        result = compare.compute_fact_compare(prev, curr)
        assert result["status"] == "invalid"
        assert result["reason_codes"] == [
            "ENVELOPE_CONTRACT_INVALID", "OUTPUT_SUPPRESSED"]

    def test_current_unavailable_beats_previous_partial(self):
        prev = _envelope("2026-07-30", status="partial")
        curr = _envelope("2026-07-31", status="unavailable")
        result = compare.compute_fact_compare(prev, curr)
        assert result["status"] == "unavailable"
        assert result["reason_codes"] == [
            "SOURCE_UNAVAILABLE", "SOURCE_PARTIAL", "OUTPUT_SUPPRESSED"]


# ---------------------------------------------------------------------------
# 5. 输入合同
# ---------------------------------------------------------------------------

class TestInputContract:
    @pytest.mark.parametrize("bad", [None, "x", 1, [], ("a",)])
    def test_previous_non_dict(self, bad):
        result = compare.compute_fact_compare(bad, _envelope("2026-07-31"))
        _assert_invalid(result)

    @pytest.mark.parametrize("bad", [None, "x", 1])
    def test_current_non_dict(self, bad):
        result = compare.compute_fact_compare(_envelope("2026-07-30"), bad)
        _assert_invalid(result)

    def test_wrong_schema(self):
        prev = _envelope("2026-07-30")
        prev["schema_version"] = "wrong"
        result = compare.compute_fact_compare(prev, _envelope("2026-07-31"))
        _assert_invalid(result)

    def test_missing_sections_key(self):
        prev = _envelope("2026-07-30")
        del prev["sections"]
        result = compare.compute_fact_compare(prev, _envelope("2026-07-31"))
        _assert_invalid(result)

    def test_extra_key(self):
        prev = _envelope("2026-07-30")
        prev["extra"] = 1
        result = compare.compute_fact_compare(prev, _envelope("2026-07-31"))
        _assert_invalid(result)

    def test_bad_trade_date(self):
        prev = _envelope("2026-02-30")
        result = compare.compute_fact_compare(prev, _envelope("2026-07-31"))
        _assert_invalid(result)

    def test_bad_session(self):
        prev = _envelope("2026-07-30", session="draft")
        result = compare.compute_fact_compare(prev, _envelope("2026-07-31"))
        _assert_invalid(result)


# ---------------------------------------------------------------------------
# 6. 输出合同
# ---------------------------------------------------------------------------

class TestOutputContract:
    def test_limitations_fixed(self):
        result = compare.compute_fact_compare(
            _envelope("2026-07-30"), _envelope("2026-07-31"))
        assert result["limitations"] == [
            "descriptive aggregate comparison of two daily-facts envelopes",
            "no per-stock cross-day identity tracking",
            "does not compute layered promotion rates",
            "does not validate consecutive-limit-up semantics",
            "does not evaluate legal zero",
        ]

    def test_dates_copied(self):
        result = compare.compute_fact_compare(
            _envelope("2026-07-30"), _envelope("2026-07-31"))
        assert result["previous_trade_date"] == "2026-07-30"
        assert result["current_trade_date"] == "2026-07-31"


# ---------------------------------------------------------------------------
# 7. 输入不可变性与引用隔离
# ---------------------------------------------------------------------------

class TestImmutability:
    def test_inputs_deep_equal_after(self):
        prev = _envelope("2026-07-30", ladder=_ladder(), gap=_gap())
        curr = _envelope("2026-07-31", ladder=_ladder(5, 5), gap=_gap())
        prev_original = copy.deepcopy(prev)
        curr_original = copy.deepcopy(curr)
        compare.compute_fact_compare(prev, curr)
        assert prev == prev_original
        assert curr == curr_original

    def test_no_shared_mutable_references(self):
        prev = _envelope("2026-07-30", ladder=_ladder(), gap=_gap())
        curr = _envelope("2026-07-31", ladder=_ladder(5, 5), gap=_gap())
        result = compare.compute_fact_compare(prev, curr)
        changes = result["deltas"]["ladder"]["board_level_changes"]
        assert changes is not prev["sections"]["ladder"]["metrics"]["ladder"]
        assert changes is not curr["sections"]["ladder"]["metrics"]["ladder"]
        changes.append({"boards": 99, "prev_count": 0, "curr_count": 0,
                        "delta": 0})
        assert len(curr["sections"]["ladder"]["metrics"]["ladder"]) == 2


# ---------------------------------------------------------------------------
# 8. 普通异常边界与进程控制
# ---------------------------------------------------------------------------

class TestExceptionBoundary:
    HELPERS = [
        "_validate_envelope",
        "_compute_facts_delta",
        "_compute_ladder_delta",
        "_compute_gap_delta",
        "_normal_envelope",
    ]

    @pytest.mark.parametrize("target", HELPERS)
    @pytest.mark.parametrize("exc", [
        RuntimeError("boom-fact-compare"),
        ValueError("boom-fact-compare"),
        TypeError("boom-fact-compare"),
    ])
    def test_ordinary_exception_fixed_fallback(self, monkeypatch, target, exc):
        def raiser(*args, **kwargs):
            raise exc
        monkeypatch.setattr(compare, target, raiser)
        result = compare.compute_fact_compare(
            _envelope("2026-07-30", ladder=_ladder(), gap=_gap()),
            _envelope("2026-07-31", ladder=_ladder(), gap=_gap()))
        _assert_invalid(result, reason_code="INPUT_CONTRACT_INVALID")
        assert "boom-fact-compare" not in repr(result)
        assert "boom-fact-compare" not in str(result)

    @pytest.mark.parametrize("target", HELPERS)
    @pytest.mark.parametrize("exc", [
        KeyboardInterrupt(),
        SystemExit(1),
        GeneratorExit(),
    ])
    def test_process_control_propagates(self, monkeypatch, target, exc):
        def raiser(*args, **kwargs):
            raise exc
        monkeypatch.setattr(compare, target, raiser)
        with pytest.raises(type(exc)):
            compare.compute_fact_compare(
                _envelope("2026-07-30", ladder=_ladder(), gap=_gap()),
                _envelope("2026-07-31", ladder=_ladder(), gap=_gap()))

    def test_emergency_exact_literal(self, monkeypatch):
        def raiser(*args, **kwargs):
            raise RuntimeError("secret")
        monkeypatch.setattr(compare, "_evaluate", raiser)
        result = compare.compute_fact_compare(
            _envelope("2026-07-30"), _envelope("2026-07-31"))
        _assert_invalid(result, reason_code="INPUT_CONTRACT_INVALID")
        assert result["limitations"] == [
            "descriptive aggregate comparison of two daily-facts envelopes",
            "no per-stock cross-day identity tracking",
            "does not compute layered promotion rates",
            "does not validate consecutive-limit-up semantics",
            "does not evaluate legal zero",
        ]


# ---------------------------------------------------------------------------
# 9. 跨调用隔离
# ---------------------------------------------------------------------------

class TestCrossCallIsolation:
    def test_cross_call(self):
        first = compare.compute_fact_compare(
            _envelope("2026-07-30"), _envelope("2026-07-31"))
        second = compare.compute_fact_compare(
            _envelope("2026-07-30"), _envelope("2026-07-31"))
        first["limitations"].append("mutated")
        first["deltas"]["facts"]["advance_count"] = 999
        assert second["limitations"] == [
            "descriptive aggregate comparison of two daily-facts envelopes",
            "no per-stock cross-day identity tracking",
            "does not compute layered promotion rates",
            "does not validate consecutive-limit-up semantics",
            "does not evaluate legal zero",
        ]
        assert second["deltas"]["facts"]["advance_count"] == 0
