"""BK-11 layered-promotion coverage eligibility gate v0.1 · 全路径测试。

不发起任何 live 网络请求。真实 producer 联合路径通过 fake 上游
（astock.em_get / trade calendar / sleep / monotonic）组装。
"""
from __future__ import annotations

import inspect
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, "backend")

import astock  # noqa: E402
import trade_calendar  # noqa: E402
import short_term_limit_up_final_snapshot as producer  # noqa: E402
import short_term_layered_promotion_coverage_gate as gate  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_DOC_PATH = (
    REPO_ROOT / "docs" / "research" / "BK11_LAYERED_PROMOTION_COVERAGE_GATE_V01.md"
)
PREV_DATE = "2026-07-29"
CURR_DATE = "2026-07-30"
FIRST_MONO = 100.0
LAST_MONO = 104.4
ACTUAL_MONO = LAST_MONO - FIRST_MONO


def _adapter_snapshot(date_str, **overrides):
    snapshot = {
        "schema_version": "short-term-limit-up-pool-adapter-v0.1",
        "source_id": "eastmoney_getTopicZTPool",
        "endpoint": "getTopicZTPool",
        "requested_trade_date": date_str,
        "observed_at": f"{date_str}T15:05:00.000000Z",
        "status": "normal",
        "reason_codes": [],
        "rows": [{"stock_code": "600001", "lbc": 1}],
        "transport_success": True,
        "parse_success": True,
        "required_field_present": True,
        "data_array_present": True,
        "trade_date_match": True,
        "row_count": 1,
        "legal_zero": False,
        "upstream_null": False,
        "unexplained_empty": False,
        "coverage_warning": False,
        "target_universe_empty_after_filter": False,
        "source_pool_row_count": 1,
        "http_status": 200,
        "error_class": "NONE",
        "excluded_universe_count": 0,
        "invalid_row_count": 0,
        "duplicate_code_count": 0,
    }
    snapshot.update(overrides)
    return snapshot


def _target_universe_empty_snapshot(date_str):
    return _adapter_snapshot(
        date_str,
        rows=[],
        row_count=0,
        source_pool_row_count=2,
        excluded_universe_count=2,
        target_universe_empty_after_filter=True,
    )


def _producer_result(date_str, status="normal", **overrides):
    result = {
        "schema_version": "short-term-limit-up-final-snapshot-v0.1",
        "requested_trade_date": date_str,
        "observed_at": f"{date_str}T15:10:00.000000Z",
        "status": status,
        "reason_codes": [],
        "session": "final" if status == "normal" else "not_final",
        "is_final": status == "normal",
        "finality_basis": (
            "three_identical_normal_observations" if status == "normal" else None),
        "required_observations": 3,
        "completed_observations": 3,
        "stable_observation_count": 3,
        "observation_interval_seconds": 2.2,
        "required_stability_window_seconds": 4.4,
        "actual_stability_window_seconds": ACTUAL_MONO,
        "first_observation_monotonic": FIRST_MONO,
        "last_observation_monotonic": LAST_MONO,
        "snapshot": (
            _adapter_snapshot(date_str) if status == "normal" else None),
        "warnings": [],
    }
    result.update(overrides)
    return result


def _partial_result(date_str, **overrides):
    result = _producer_result(
        date_str,
        status="partial",
        reason_codes=["SOURCE_PARTIAL", "PARTIAL_COVERAGE"],
        warnings=["snapshot partially available"],
    )
    result.update(overrides)
    return result


def _unavailable_result(date_str, **overrides):
    result = _producer_result(
        date_str,
        status="unavailable",
        reason_codes=["SOURCE_UNAVAILABLE", "CURRENT_SNAPSHOT_UNAVAILABLE"],
        warnings=["snapshot unavailable"],
    )
    result.update(overrides)
    return result


def _complete_pair(prev=_producer_result(PREV_DATE),
                   curr=_producer_result(CURR_DATE)):
    return prev, curr


def _gate(prev, curr):
    return gate.evaluate_layered_promotion_coverage(prev, curr)


def _assert_shape(r):
    assert set(r.keys()) == {
        "schema_version", "status", "reason_codes", "coverage_eligible",
        "rates_policy", "layered_promotion_rates", "previous_trade_date",
        "current_trade_date", "previous_state", "current_state",
        "implementation_allowed", "warnings",
    }
    assert r["schema_version"] == gate.SCHEMA_VERSION
    assert r["status"] in ("complete", "partial", "unavailable", "invalid")
    assert isinstance(r["reason_codes"], list)
    assert isinstance(r["coverage_eligible"], bool)
    assert r["rates_policy"] in ("not_computed", "must_be_null")
    assert r["layered_promotion_rates"] is None
    assert r["implementation_allowed"] is False
    assert isinstance(r["warnings"], list)
    assert r["previous_state"] in ("complete", "partial", "unavailable", "invalid")
    assert r["current_state"] in ("complete", "partial", "unavailable", "invalid")
    for code in r["reason_codes"]:
        assert code in gate._REASON_CODE_SET
    # 固定顺序
    fixed = list(gate._REASON_CODE_ORDER)
    seen = []
    for code in r["reason_codes"]:
        if code not in seen:
            seen.append(code)
    for a, b in zip(seen, seen[1:]):
        assert fixed.index(a) < fixed.index(b)
    # 核心不变量
    if r["status"] != "complete":
        assert r["coverage_eligible"] is False
        assert r["rates_policy"] == "must_be_null"
        assert "RATE_OUTPUT_SUPPRESSED" in r["reason_codes"]
    else:
        assert r["coverage_eligible"] is True
        assert r["reason_codes"] == []
        assert r["rates_policy"] == "not_computed"
        assert r["previous_state"] == "complete"
        assert r["current_state"] == "complete"


# ---------------------------------------------------------------------------
# 1. 公开合同
# ---------------------------------------------------------------------------

class TestPublicContract:
    def test_constants(self):
        assert gate.SCHEMA_VERSION == (
            "short-term-layered-promotion-coverage-gate-v0.1")
        assert gate.FINAL_SNAPSHOT_SCHEMA_VERSION == (
            "short-term-limit-up-final-snapshot-v0.1")

    def test_all(self):
        assert gate.__all__ == [
            "SCHEMA_VERSION",
            "FINAL_SNAPSHOT_SCHEMA_VERSION",
            "evaluate_layered_promotion_coverage",
        ]

    def test_signature(self):
        sig = inspect.signature(gate.evaluate_layered_promotion_coverage)
        assert list(sig.parameters) == ["previous_result", "current_result"]
        for p in sig.parameters.values():
            assert p.default is inspect.Parameter.empty

    def test_no_rates_parameters(self):
        sig = inspect.signature(gate.evaluate_layered_promotion_coverage)
        for name in sig.parameters:
            assert "rate" not in name


# ---------------------------------------------------------------------------
# 2. complete
# ---------------------------------------------------------------------------

class TestCompleteCoverage:
    def test_both_complete(self):
        r = _gate(*_complete_pair())
        _assert_shape(r)
        assert r["status"] == "complete"
        assert r["coverage_eligible"] is True
        assert r["rates_policy"] == "not_computed"
        assert r["layered_promotion_rates"] is None
        assert r["implementation_allowed"] is False
        assert r["previous_trade_date"] == PREV_DATE
        assert r["current_trade_date"] == CURR_DATE
        assert r["previous_state"] == "complete"
        assert r["current_state"] == "complete"

    def test_target_universe_empty_complete(self):
        prev = _producer_result(
            PREV_DATE, snapshot=_target_universe_empty_snapshot(PREV_DATE))
        curr = _producer_result(
            CURR_DATE, snapshot=_target_universe_empty_snapshot(CURR_DATE))
        r = _gate(prev, curr)
        _assert_shape(r)
        assert r["status"] == "complete"
        assert r["coverage_eligible"] is True

    def test_observed_at_and_http_status_differ(self):
        prev = _producer_result(
            PREV_DATE,
            observed_at=f"{PREV_DATE}T15:10:00.000000Z",
            snapshot=_adapter_snapshot(PREV_DATE, http_status=200),
        )
        curr = _producer_result(
            CURR_DATE,
            observed_at=f"{CURR_DATE}T15:12:00.000000Z",
            snapshot=_adapter_snapshot(CURR_DATE, http_status=202),
        )
        r = _gate(prev, curr)
        assert r["status"] == "complete"


# ---------------------------------------------------------------------------
# 3. partial suppression
# ---------------------------------------------------------------------------

class TestPartialSuppression:
    def test_previous_partial(self):
        r = _gate(_partial_result(PREV_DATE), _producer_result(CURR_DATE))
        _assert_shape(r)
        assert r["status"] == "partial"
        assert r["reason_codes"] == [
            "PREVIOUS_SOURCE_PARTIAL", "RATE_OUTPUT_SUPPRESSED"]
        assert r["previous_state"] == "partial"
        assert r["current_state"] == "complete"

    def test_current_partial(self):
        r = _gate(_producer_result(PREV_DATE), _partial_result(CURR_DATE))
        _assert_shape(r)
        assert r["reason_codes"] == [
            "CURRENT_SOURCE_PARTIAL", "RATE_OUTPUT_SUPPRESSED"]

    def test_both_partial(self):
        r = _gate(_partial_result(PREV_DATE), _partial_result(CURR_DATE))
        _assert_shape(r)
        assert r["reason_codes"] == [
            "PREVIOUS_SOURCE_PARTIAL", "CURRENT_SOURCE_PARTIAL",
            "RATE_OUTPUT_SUPPRESSED"]

    def test_partial_plus_complete(self):
        r = _gate(_partial_result(PREV_DATE), _producer_result(CURR_DATE))
        assert r["status"] == "partial"
        assert r["coverage_eligible"] is False
        assert r["rates_policy"] == "must_be_null"
        assert r["layered_promotion_rates"] is None


# ---------------------------------------------------------------------------
# 4. unavailable suppression
# ---------------------------------------------------------------------------

class TestUnavailableSuppression:
    def test_previous_unavailable(self):
        r = _gate(_unavailable_result(PREV_DATE), _producer_result(CURR_DATE))
        _assert_shape(r)
        assert r["status"] == "unavailable"
        assert r["reason_codes"] == [
            "PREVIOUS_SOURCE_UNAVAILABLE", "RATE_OUTPUT_SUPPRESSED"]

    def test_current_unavailable(self):
        r = _gate(_producer_result(PREV_DATE), _unavailable_result(CURR_DATE))
        _assert_shape(r)
        assert r["reason_codes"] == [
            "CURRENT_SOURCE_UNAVAILABLE", "RATE_OUTPUT_SUPPRESSED"]

    def test_both_unavailable(self):
        r = _gate(_unavailable_result(PREV_DATE), _unavailable_result(CURR_DATE))
        _assert_shape(r)
        assert r["reason_codes"] == [
            "PREVIOUS_SOURCE_UNAVAILABLE", "CURRENT_SOURCE_UNAVAILABLE",
            "RATE_OUTPUT_SUPPRESSED"]

    def test_unavailable_beats_partial(self):
        r = _gate(_partial_result(PREV_DATE), _unavailable_result(CURR_DATE))
        _assert_shape(r)
        assert r["status"] == "unavailable"
        assert r["reason_codes"] == [
            "CURRENT_SOURCE_UNAVAILABLE", "RATE_OUTPUT_SUPPRESSED"]

    def test_partial_plus_unavailable_reversed(self):
        r = _gate(_unavailable_result(PREV_DATE), _partial_result(CURR_DATE))
        _assert_shape(r)
        assert r["status"] == "unavailable"
        assert r["reason_codes"] == [
            "PREVIOUS_SOURCE_UNAVAILABLE", "RATE_OUTPUT_SUPPRESSED"]


# ---------------------------------------------------------------------------
# 5. invalid suppression
# ---------------------------------------------------------------------------

class TestInvalidSuppression:
    def _assert_invalid(self, r, expected_codes):
        _assert_shape(r)
        assert r["status"] == "invalid"
        assert r["coverage_eligible"] is False
        assert r["rates_policy"] == "must_be_null"
        assert r["layered_promotion_rates"] is None
        assert "RATE_OUTPUT_SUPPRESSED" in r["reason_codes"]
        for code in expected_codes:
            assert code in r["reason_codes"]

    def test_non_dict(self):
        r = _gate(None, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_dict_subclass(self):
        class D(dict):
            pass
        r = _gate(D(), _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_missing_field(self):
        prev = _producer_result(PREV_DATE)
        del prev["warnings"]
        r = _gate(prev, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_extra_field(self):
        prev = _producer_result(PREV_DATE)
        prev["extra"] = 1
        r = _gate(prev, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_wrong_schema(self):
        prev = _producer_result(PREV_DATE, schema_version="wrong")
        r = _gate(prev, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_illegal_status(self):
        prev = _producer_result(PREV_DATE, status="weird")
        r = _gate(prev, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_normal_but_not_final(self):
        prev = _producer_result(PREV_DATE, session="not_final", is_final=False)
        r = _gate(prev, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_normal_but_snapshot_null(self):
        prev = _producer_result(PREV_DATE, snapshot=None)
        r = _gate(prev, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_partial_but_snapshot_present(self):
        prev = _partial_result(PREV_DATE, snapshot=_adapter_snapshot(PREV_DATE))
        r = _gate(prev, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_unavailable_but_final_true(self):
        prev = _unavailable_result(
            PREV_DATE, session="final", is_final=True)
        r = _gate(prev, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_reason_codes_wrong_type(self):
        prev = _producer_result(PREV_DATE, reason_codes="not-a-list")
        r = _gate(prev, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_counter_bool(self):
        prev = _producer_result(PREV_DATE, required_observations=True)
        r = _gate(prev, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_counter_negative(self):
        prev = _producer_result(PREV_DATE, completed_observations=-1)
        r = _gate(prev, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_counter_out_of_range(self):
        prev = _producer_result(PREV_DATE, stable_observation_count=4)
        r = _gate(prev, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_clock_nan(self):
        prev = _producer_result(PREV_DATE, actual_stability_window_seconds=float("nan"))
        r = _gate(prev, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_clock_inf(self):
        prev = _producer_result(PREV_DATE, first_observation_monotonic=float("inf"))
        r = _gate(prev, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_clock_regression(self):
        prev = _producer_result(
            PREV_DATE, first_observation_monotonic=104.4,
            last_observation_monotonic=100.0, actual_stability_window_seconds=-4.4)
        r = _gate(prev, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])

    def test_timing_one_sided(self):
        prev = _producer_result(
            PREV_DATE, first_observation_monotonic=100.0,
            last_observation_monotonic=None, actual_stability_window_seconds=None)
        r = _gate(prev, _producer_result(CURR_DATE))
        self._assert_invalid(r, ["PREVIOUS_INPUT_INVALID"])


# ---------------------------------------------------------------------------
# 6. 日期关系
# ---------------------------------------------------------------------------

class TestDateOrder:
    def test_previous_before_current(self):
        r = _gate(*_complete_pair())
        assert r["status"] == "complete"

    def test_equal_dates(self):
        r = _gate(_producer_result(PREV_DATE), _producer_result(PREV_DATE))
        _assert_shape(r)
        assert r["status"] == "invalid"
        assert r["reason_codes"] == ["DATE_ORDER_INVALID", "RATE_OUTPUT_SUPPRESSED"]

    def test_reversed_dates(self):
        r = _gate(_producer_result(CURR_DATE), _producer_result(PREV_DATE))
        _assert_shape(r)
        assert r["status"] == "invalid"
        assert r["reason_codes"] == ["DATE_ORDER_INVALID", "RATE_OUTPUT_SUPPRESSED"]

    def test_illegal_date(self):
        prev = _producer_result("2026-02-30")
        r = _gate(prev, _producer_result(CURR_DATE))
        _assert_shape(r)
        assert r["status"] == "invalid"
        assert "PREVIOUS_INPUT_INVALID" in r["reason_codes"]
        assert "RATE_OUTPUT_SUPPRESSED" in r["reason_codes"]


# ---------------------------------------------------------------------------
# 7. producer 合同逐项
# ---------------------------------------------------------------------------

class TestProducerContract:
    @pytest.mark.parametrize("overrides", [
        {"schema_version": "wrong"},
        {"requested_trade_date": "2026-7-29"},
        {"observed_at": "not-a-time"},
        {"observed_at": "2026-07-29T15:10:00+08:00"},
        {"status": "weird"},
        {"reason_codes": ["X", 1]},
        {"session": "draft"},
        {"is_final": 1},
        {"finality_basis": 123},
        {"required_observations": 0},
        {"required_observations": True},
        {"completed_observations": 4},
        {"stable_observation_count": -1},
        {"observation_interval_seconds": 0.0},
        {"observation_interval_seconds": float("nan")},
        {"required_stability_window_seconds": -1.0},
        {"actual_stability_window_seconds": float("inf")},
        {"snapshot": "not-a-dict"},
        {"warnings": "not-a-list"},
        {"warnings": ["ok", 1]},
    ])
    def test_producer_contract_violations(self, overrides):
        prev = _producer_result(PREV_DATE, **overrides)
        r = _gate(prev, _producer_result(CURR_DATE))
        _assert_shape(r)
        assert r["status"] == "invalid"
        assert "PREVIOUS_INPUT_INVALID" in r["reason_codes"]
        assert "RATE_OUTPUT_SUPPRESSED" in r["reason_codes"]

    def test_actual_mismatch(self):
        prev = _producer_result(
            PREV_DATE, actual_stability_window_seconds=3.0)
        r = _gate(prev, _producer_result(CURR_DATE))
        assert r["status"] == "invalid"
        assert "PREVIOUS_INPUT_INVALID" in r["reason_codes"]

    def test_both_sides_invalid(self):
        r = _gate(None, "x")
        _assert_shape(r)
        assert r["status"] == "invalid"
        assert r["reason_codes"] == [
            "PREVIOUS_INPUT_INVALID", "CURRENT_INPUT_INVALID",
            "RATE_OUTPUT_SUPPRESSED"]


# ---------------------------------------------------------------------------
# 8. nested adapter 合同
# ---------------------------------------------------------------------------

class TestNestedAdapterContract:
    def _invalid_prev(self, snapshot):
        prev = _producer_result(PREV_DATE, snapshot=snapshot)
        r = _gate(prev, _producer_result(CURR_DATE))
        assert r["status"] == "invalid"
        assert "PREVIOUS_INPUT_INVALID" in r["reason_codes"]
        assert "RATE_OUTPUT_SUPPRESSED" in r["reason_codes"]

    def test_missing_field(self):
        snap = _adapter_snapshot(PREV_DATE)
        del snap["error_class"]
        self._invalid_prev(snap)

    def test_extra_field(self):
        snap = _adapter_snapshot(PREV_DATE, extra=1)
        self._invalid_prev(snap)

    def test_coverage_warning(self):
        self._invalid_prev(
            _adapter_snapshot(PREV_DATE, coverage_warning=True))

    def test_legal_zero(self):
        self._invalid_prev(
            _adapter_snapshot(PREV_DATE, legal_zero=True, rows=[],
                              row_count=0, source_pool_row_count=0,
                              excluded_universe_count=0,
                              target_universe_empty_after_filter=False))

    def test_unexplained_empty(self):
        self._invalid_prev(
            _adapter_snapshot(PREV_DATE, unexplained_empty=True, rows=[],
                              row_count=0, source_pool_row_count=0,
                              excluded_universe_count=0,
                              target_universe_empty_after_filter=False))

    def test_trade_date_match_false(self):
        self._invalid_prev(
            _adapter_snapshot(PREV_DATE, trade_date_match=False))

    def test_trade_date_match_null(self):
        self._invalid_prev(
            _adapter_snapshot(PREV_DATE, trade_date_match=None))

    def test_row_count_mismatch(self):
        self._invalid_prev(_adapter_snapshot(PREV_DATE, row_count=2))

    def test_source_count_not_conserved(self):
        self._invalid_prev(
            _adapter_snapshot(PREV_DATE, source_pool_row_count=3,
                              excluded_universe_count=1))

    def test_error_class_wrong(self):
        self._invalid_prev(
            _adapter_snapshot(PREV_DATE, error_class="HTTP_ERROR"))

    def test_status_not_normal(self):
        self._invalid_prev(
            _adapter_snapshot(PREV_DATE, status="partial",
                              reason_codes=["X"], coverage_warning=True))

    def test_outer_date_mismatch(self):
        self._invalid_prev(_adapter_snapshot(CURR_DATE))


# ---------------------------------------------------------------------------
# 9. rows
# ---------------------------------------------------------------------------

class TestRows:
    def _invalid_row(self, rows, row_count=1, source=1):
        self._invalid_prev(_adapter_snapshot(
            PREV_DATE, rows=rows, row_count=row_count,
            source_pool_row_count=source))

    def _invalid_prev(self, snapshot):
        prev = _producer_result(PREV_DATE, snapshot=snapshot)
        r = _gate(prev, _producer_result(CURR_DATE))
        assert r["status"] == "invalid"
        assert "PREVIOUS_INPUT_INVALID" in r["reason_codes"]

    def test_extra_row_field(self):
        self._invalid_row([{"stock_code": "600001", "lbc": 1, "x": 1}])

    def test_bad_code(self):
        self._invalid_row([{"stock_code": "60000", "lbc": 1}])

    def test_lbc_zero(self):
        self._invalid_row([{"stock_code": "600001", "lbc": 0}])

    def test_lbc_bool(self):
        self._invalid_row([{"stock_code": "600001", "lbc": True}])

    def test_unsorted(self):
        self._invalid_row([
            {"stock_code": "600001", "lbc": 1},
            {"stock_code": "000001", "lbc": 1},
        ], row_count=2, source=2)

    def test_duplicate_code(self):
        self._invalid_row([
            {"stock_code": "000001", "lbc": 1},
            {"stock_code": "000001", "lbc": 2},
        ], row_count=2, source=2)

    def test_valid_multiple_rows(self):
        snap = _adapter_snapshot(
            PREV_DATE,
            rows=[
                {"stock_code": "000001", "lbc": 2},
                {"stock_code": "600001", "lbc": 1},
                {"stock_code": "688001", "lbc": 1},
            ],
            row_count=3,
            source_pool_row_count=3,
        )
        prev = _producer_result(PREV_DATE, snapshot=snap)
        r = _gate(prev, _producer_result(CURR_DATE))
        assert r["status"] == "complete"


# ---------------------------------------------------------------------------
# 10. 严格 JSON
# ---------------------------------------------------------------------------

class TestStrictJson:
    class _DictSubclass(dict):
        pass

    class _ListSubclass(list):
        pass

    class _StrSubclass(str):
        pass

    class _IntSubclass(int):
        pass

    class _FloatSubclass(float):
        pass

    @pytest.mark.parametrize("bad", [
        _DictSubclass(),
        _ListSubclass([1]),
        _StrSubclass("x"),
        _IntSubclass(1),
        _FloatSubclass(1.0),
        (1, 2),
        {1},
        b"bytes",
        1j,
        object(),
        float("nan"),
        float("inf"),
        float("-inf"),
    ])
    def test_nested_bad_values(self, bad):
        prev = _producer_result(PREV_DATE, warnings=[bad])
        r = _gate(prev, _producer_result(CURR_DATE))
        assert r["status"] == "invalid"
        assert "PREVIOUS_INPUT_INVALID" in r["reason_codes"]
        assert "RATE_OUTPUT_SUPPRESSED" in r["reason_codes"]

    def test_non_str_key(self):
        prev = _producer_result(PREV_DATE)
        prev[1] = "x"
        r = _gate(prev, _producer_result(CURR_DATE))
        assert r["status"] == "invalid"


# ---------------------------------------------------------------------------
# 11. 输出不变量
# ---------------------------------------------------------------------------

class TestOutputInvariants:
    def test_all_paths(self):
        cases = [
            (_producer_result(PREV_DATE), _producer_result(CURR_DATE)),
            (_partial_result(PREV_DATE), _producer_result(CURR_DATE)),
            (_producer_result(PREV_DATE), _unavailable_result(CURR_DATE)),
            (_partial_result(PREV_DATE), _unavailable_result(CURR_DATE)),
            (None, _producer_result(CURR_DATE)),
            (_producer_result(PREV_DATE), _producer_result(PREV_DATE)),
        ]
        for prev, curr in cases:
            r = _gate(prev, curr)
            _assert_shape(r)

    def test_complete_never_computes_rates(self):
        r = _gate(*_complete_pair())
        assert r["layered_promotion_rates"] is None
        assert r["rates_policy"] == "not_computed"

    def test_implementation_allowed_always_false(self):
        for prev, curr in [
            (_producer_result(PREV_DATE), _producer_result(CURR_DATE)),
            (_partial_result(PREV_DATE), _producer_result(CURR_DATE)),
            (_unavailable_result(PREV_DATE), _producer_result(CURR_DATE)),
            (None, _producer_result(CURR_DATE)),
        ]:
            r = _gate(prev, curr)
            assert r["implementation_allowed"] is False


# ---------------------------------------------------------------------------
# 12. 普通异常边界与进程控制
# ---------------------------------------------------------------------------

class TestOrdinaryExceptionBoundary:
    def test_structured_fallback(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("secret token leak-check")
        monkeypatch.setattr(gate, "_classify_side", boom)
        r = _gate(_producer_result(PREV_DATE), _producer_result(CURR_DATE))
        _assert_shape(r)
        assert r["status"] == "invalid"
        assert r["rates_policy"] == "must_be_null"
        assert r["layered_promotion_rates"] is None
        assert "secret token leak-check" not in str(r)

    @pytest.mark.parametrize("target", [
        "_classify_side", "_validate_producer_contract",
        "_validate_nested_adapter", "_extract_date",
        "_is_strict_json_value",
    ])
    def test_no_leak_from_any_stage(self, monkeypatch, target):
        def boom(*a, **k):
            raise TypeError("leaky-type-error")
        monkeypatch.setattr(gate, target, boom)
        r = _gate(_producer_result(PREV_DATE), _producer_result(CURR_DATE))
        assert r["status"] == "invalid"
        assert "leaky-type-error" not in str(r)


class TestProcessControl:
    @pytest.mark.parametrize("exc", [
        KeyboardInterrupt(), SystemExit(1), GeneratorExit(),
    ])
    @pytest.mark.parametrize("target", [
        "_classify_side", "_validate_producer_contract",
        "_validate_nested_adapter", "_extract_date",
        "_is_strict_json_value", "_output",
    ])
    def test_propagates(self, monkeypatch, exc, target):
        def raiser(*a, **k):
            raise exc
        monkeypatch.setattr(gate, target, raiser)
        with pytest.raises(type(exc)):
            _gate(_producer_result(PREV_DATE), _producer_result(CURR_DATE))


# ---------------------------------------------------------------------------
# 13. 真实 producer 联合路径
# ---------------------------------------------------------------------------

class TestRealProducerJoint:
    SESSIONS = (
        "2024-01-02", "2026-06-18", "2026-06-22", "2026-07-24",
        "2026-07-27", "2026-07-29", "2026-07-30", "2026-07-31",
    )
    TODAY = date(2026, 8, 4)

    def _run_real_producer(self, monkeypatch, date_str, body, em_raises=None):
        def fake_em_get(*a, **k):
            if em_raises is not None:
                raise em_raises

            class R:
                status_code = 200

                def json(self):
                    return body

            return R()

        monkeypatch.setattr(astock, "em_get", fake_em_get)
        monkeypatch.setattr(trade_calendar, "_load_calendar",
                            lambda: self.SESSIONS)
        monkeypatch.setattr(trade_calendar, "_today_shanghai",
                            lambda: self.TODAY)
        monkeypatch.setattr(producer, "_sleep", lambda sec: None)
        clock = {"n": 0}

        def fake_monotonic():
            values = [100.0, 102.2, 104.4]
            v = values[min(clock["n"], 2)]
            clock["n"] += 1
            return v

        monkeypatch.setattr(producer, "_monotonic", fake_monotonic)
        return producer.fetch_final_limit_up_pool_snapshot(date_str)

    def test_real_complete(self, monkeypatch):
        prev = self._run_real_producer(
            monkeypatch, "2026-07-29",
            {"trade_date": "20260729",
             "data": {"date": "2026-07-29",
                      "pool": [{"c": "600001", "lbc": 1}]}})
        curr = self._run_real_producer(
            monkeypatch, "2026-07-30",
            {"trade_date": "20260730",
             "data": {"date": "2026-07-30",
                      "pool": [{"c": "600001", "lbc": 2}]}})
        assert prev["status"] == "normal" and curr["status"] == "normal"
        r = _gate(prev, curr)
        _assert_shape(r)
        assert r["status"] == "complete"
        assert r["coverage_eligible"] is True

    def test_real_partial(self, monkeypatch):
        prev = self._run_real_producer(
            monkeypatch, "2026-07-29",
            {"data": {"date": "2026-07-29", "pool": []}})
        assert prev["status"] == "partial"
        curr = self._run_real_producer(
            monkeypatch, "2026-07-30",
            {"trade_date": "20260730",
             "data": {"date": "2026-07-30",
                      "pool": [{"c": "600001", "lbc": 1}]}})
        r = _gate(prev, curr)
        _assert_shape(r)
        assert r["status"] == "partial"
        assert r["reason_codes"] == [
            "PREVIOUS_SOURCE_PARTIAL", "RATE_OUTPUT_SUPPRESSED"]

    def test_real_unavailable(self, monkeypatch):
        prev = self._run_real_producer(
            monkeypatch, "2026-07-29", None,
            em_raises=RuntimeError("upstream down"))
        assert prev["status"] == "unavailable"
        curr = self._run_real_producer(
            monkeypatch, "2026-07-30",
            {"trade_date": "20260730",
             "data": {"date": "2026-07-30",
                      "pool": [{"c": "600001", "lbc": 1}]}})
        r = _gate(prev, curr)
        _assert_shape(r)
        assert r["status"] == "unavailable"
        assert r["reason_codes"] == [
            "PREVIOUS_SOURCE_UNAVAILABLE", "RATE_OUTPUT_SUPPRESSED"]

    def test_real_target_universe_empty_complete(self, monkeypatch):
        prev = self._run_real_producer(
            monkeypatch, "2026-07-29",
            {"trade_date": "20260729",
             "data": {"date": "2026-07-29",
                      "pool": [{"c": "400001", "lbc": 1}]}})
        assert prev["status"] == "normal"
        assert prev["snapshot"]["target_universe_empty_after_filter"] is True
        curr = self._run_real_producer(
            monkeypatch, "2026-07-30",
            {"trade_date": "20260730",
             "data": {"date": "2026-07-30",
                      "pool": [{"c": "400001", "lbc": 1}]}})
        r = _gate(prev, curr)
        _assert_shape(r)
        assert r["status"] == "complete"


# ---------------------------------------------------------------------------
# 14. 文档一致性
# ---------------------------------------------------------------------------

class TestDocumentationAlignment:
    def test_doc_sections(self):
        text = GATE_DOC_PATH.read_text(encoding="utf-8")
        for i in range(1, 21):
            assert f"## {i}." in text

    def test_doc_disclaimers(self):
        text = GATE_DOC_PATH.read_text(encoding="utf-8")
        assert "coverage_eligible != implementation_allowed" in text
        assert "complete 不计算 rates" in text
        assert "强制 rates=null" in text
        assert "legal_zero 正向确认未实现" in text
        assert "日期严格递增不等于相邻交易日" in text
        assert "Blocker 8 关闭不代表生产晋级率获准" in text
        assert "candidate CLOSED pending independent review" in text
        assert "implementation_allowed(layered_promotion_rates)" in text

    def test_doc_blocker_table(self):
        text = GATE_DOC_PATH.read_text(encoding="utf-8")
        assert "| 8 | candidate CLOSED pending independent review |" in text
        assert "| 2 | OPEN |" in text
        assert "| 3 | OPEN |" in text
        assert "| 6 | PARTIALLY CLOSED |" in text
        assert "| 9 | CLOSED |" in text
