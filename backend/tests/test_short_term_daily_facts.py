"""BK-11 Slice 2K 日事实组合层测试。

不发起任何 live 请求。覆盖组合编排、状态优先级、producer/输入合同、
元数据、异常边界、输入不可变性与输出引用隔离。
"""
from __future__ import annotations

import copy
import inspect
import sys

import pytest

sys.path.insert(0, "backend")

import short_term_daily_facts as daily  # noqa: E402


TRADE_DATE = "2026-07-31"
FIRST_MONO = 100.0
LAST_MONO = 104.4
ACTUAL_MONO = LAST_MONO - FIRST_MONO


def _adapter(date_str=TRADE_DATE, rows=None, **overrides):
    if rows is None:
        rows = [{"stock_code": "600001", "lbc": 2}]
    snapshot = {
        "schema_version": "short-term-limit-up-pool-adapter-v0.2",
        "source_id": "eastmoney_getTopicZTPool",
        "endpoint": "getTopicZTPool",
        "requested_trade_date": date_str,
        "observed_at": f"{date_str}T15:05:00.000000Z",
        "status": "normal",
        "reason_codes": [],
        "rows": rows,
        "transport_success": True,
        "parse_success": True,
        "required_field_present": True,
        "data_array_present": True,
        "trade_date_match": True,
        "row_count": len(rows),
        "legal_zero": False,
        "upstream_null": False,
        "unexplained_empty": False,
        "coverage_warning": False,
        "target_universe_empty_after_filter": False,
        "source_pool_row_count": len(rows),
        "http_status": 200,
        "error_class": "NONE",
        "excluded_universe_count": 0,
        "invalid_row_count": 0,
        "duplicate_code_count": 0,
    }
    snapshot.update(overrides)
    return snapshot


def _legal_zero_adapter(date_str=TRADE_DATE):
    return _adapter(
        date_str,
        rows=[],
        row_count=0,
        source_pool_row_count=2,
        excluded_universe_count=2,
        target_universe_empty_after_filter=True,
    )


def _producer(status="normal", date_str=TRADE_DATE, snapshot=None, **overrides):
    if snapshot is None:
        snapshot = _adapter(date_str) if status == "normal" else None
    result = {
        "schema_version": "short-term-limit-up-final-snapshot-v0.1",
        "requested_trade_date": date_str,
        "observed_at": f"{date_str}T15:10:00.000000Z",
        "status": status,
        "reason_codes": [] if status == "normal" else ["SOURCE_PARTIAL"],
        "session": "final" if status == "normal" else "not_final",
        "is_final": status == "normal",
        "finality_basis": (
            "three_identical_normal_observations"
            if status == "normal" else None),
        "required_observations": 3,
        "completed_observations": 3,
        "stable_observation_count": 3,
        "observation_interval_seconds": 2.2,
        "required_stability_window_seconds": 4.4,
        "actual_stability_window_seconds": ACTUAL_MONO,
        "first_observation_monotonic": FIRST_MONO,
        "last_observation_monotonic": LAST_MONO,
        "snapshot": snapshot,
        "warnings": [] if status == "normal" else ["snapshot partial"],
    }
    result.update(overrides)
    return result


def _facts_data_health(**overrides):
    health = {
        "transport_success": True,
        "parse_success": True,
        "required_field_present": True,
        "data_array_present": True,
        "trade_date_match": True,
        "row_count": 3,
        "legal_zero": False,
        "upstream_null": False,
        "unexplained_empty": False,
        "coverage_warning": False,
    }
    health.update(overrides)
    return health


def _breadth(**overrides):
    data = {
        "advance_count": 100,
        "decline_count": 80,
        "flat_count": 20,
        "suspended_count": 5,
        "eligible_count": 205,
    }
    data.update(overrides)
    return data


def _limit_activity(**overrides):
    data = {
        "limit_up_count": 10,
        "limit_down_count": 2,
        "failed_limit_up_count": 3,
    }
    data.update(overrides)
    return data


def _input(producer=None, breadth=None, limit_activity=None,
           facts_data_health=None, **overrides):
    data = {
        "final_snapshot": producer if producer is not None else _producer(),
        "breadth": breadth if breadth is not None else _breadth(),
        "limit_activity": (
            limit_activity if limit_activity is not None else _limit_activity()),
        "facts_data_health": (
            facts_data_health
            if facts_data_health is not None else _facts_data_health()),
    }
    data.update(overrides)
    return data


def _assert_shape(result):
    assert set(result.keys()) == {
        "schema_version", "trade_date", "session", "is_final", "source_ids",
        "fetched_at", "snapshot_at", "status", "reason_codes", "warnings",
        "limitations", "source_schema_version", "source_status",
        "source_reason_codes", "sections",
    }
    assert result["schema_version"] == daily.SCHEMA_VERSION
    assert set(result["sections"].keys()) == {"facts", "ladder", "gap"}
    assert isinstance(result["reason_codes"], list)


def _assert_invalid(result, reason_code="INPUT_CONTRACT_INVALID"):
    _assert_shape(result)
    assert result["status"] == "invalid"
    assert result["reason_codes"] == [reason_code, "OUTPUT_SUPPRESSED"]
    assert result["sections"] == {"facts": None, "ladder": None, "gap": None}


# ---------------------------------------------------------------------------
# 1. 公开合同
# ---------------------------------------------------------------------------

class TestPublicContract:
    def test_constants(self):
        assert daily.SCHEMA_VERSION == "short-term-daily-facts-v0.1"

    def test_all(self):
        assert daily.__all__ == ["SCHEMA_VERSION", "compute_daily_facts"]

    def test_signature(self):
        sig = inspect.signature(daily.compute_daily_facts)
        assert list(sig.parameters) == ["input_envelope"]
        for parameter in sig.parameters.values():
            assert parameter.default is inspect.Parameter.empty


# ---------------------------------------------------------------------------
# 2. 正常组合
# ---------------------------------------------------------------------------

class TestNormalComposition:
    def test_full_normal(self):
        result = daily.compute_daily_facts(_input())
        _assert_shape(result)
        assert result["status"] == "normal"
        assert result["reason_codes"] == []
        assert result["trade_date"] == TRADE_DATE
        assert result["session"] == "final"
        assert result["is_final"] is True
        assert result["source_ids"] == ["eastmoney_getTopicZTPool"]
        assert result["fetched_at"] == "2026-07-31T15:10:00.000000Z"
        assert result["snapshot_at"] == "2026-07-31T15:10:00.000000Z"
        assert result["source_status"] == "normal"
        assert result["source_reason_codes"] == []
        facts = result["sections"]["facts"]
        ladder = result["sections"]["ladder"]
        gap = result["sections"]["gap"]
        assert facts["schema_version"] == "short-term-market-facts-v0.1"
        assert facts["status"] == "normal"
        assert ladder["schema_version"] == "short-term-limit-up-ladder-v0.1"
        assert ladder["status"] == "normal"
        assert ladder["metrics"]["ladder"] == [{"boards": 2, "count": 1}]
        assert gap["schema_version"] == "short-term-ladder-gap-v0.1"
        assert gap["status"] == "normal"
        assert gap["metrics"]["occupied_boards"] == [2]
        assert gap["metrics"]["missing_boards"] == []
        assert gap["metrics"]["is_continuous"] is True

    def test_target_universe_empty_ladder_unavailable(self):
        # adapter 合同禁止 legal_zero=True（Blocker 6 正向确认未实现）；
        # 空池经 2A 判为 LIMIT_UP_POOL_UNAVAILABLE -> 组合 unavailable
        producer = _producer(snapshot=_legal_zero_adapter())
        result = daily.compute_daily_facts(_input(producer=producer))
        assert result["status"] == "unavailable"
        assert result["reason_codes"] == ["OUTPUT_SUPPRESSED"]
        ladder = result["sections"]["ladder"]
        gap = result["sections"]["gap"]
        assert ladder["status"] == "unavailable"
        # 2J 对 ladder unavailable 返回 suppressed envelope
        assert gap["status"] == "unavailable"
        assert all(value is None for value in gap["metrics"].values())

    def test_ladder_gap_with_high_top(self):
        rows = [{"stock_code": "600001", "lbc": 2},
                {"stock_code": "600002", "lbc": 5}]
        producer = _producer(snapshot=_adapter(rows=rows))
        result = daily.compute_daily_facts(_input(producer=producer))
        assert result["status"] == "normal"
        gap = result["sections"]["gap"]
        assert gap["metrics"]["occupied_boards"] == [2, 5]
        assert gap["metrics"]["missing_boards"] == [3, 4]
        assert gap["metrics"]["gap_segments"] == [
            {"from_board": 3, "to_board": 4, "width": 2}]

    def test_limitations_fixed(self):
        result = daily.compute_daily_facts(_input())
        assert result["limitations"] == [
            "composed from approved BK-11 pure calculators",
            "does not validate upstream consecutive-limit-up semantics",
            "does not compute layered promotion rates",
            "production integration not authorized",
        ]


# ---------------------------------------------------------------------------
# 3. producer 状态抑制与优先级
# ---------------------------------------------------------------------------

class TestProducerStatus:
    def test_partial_suppresses_ladder_gap(self):
        producer = _producer(status="partial")
        result = daily.compute_daily_facts(_input(producer=producer))
        _assert_shape(result)
        assert result["status"] == "partial"
        assert result["reason_codes"] == [
            "UPSTREAM_LADDER_PARTIAL", "OUTPUT_SUPPRESSED"]
        assert result["sections"]["facts"]["status"] == "normal"
        assert result["sections"]["ladder"] is None
        assert result["sections"]["gap"] is None
        assert result["source_status"] == "partial"
        assert result["source_reason_codes"] == ["SOURCE_PARTIAL"]

    def test_unavailable_suppresses_ladder_gap(self):
        producer = _producer(status="unavailable")
        result = daily.compute_daily_facts(_input(producer=producer))
        assert result["status"] == "unavailable"
        assert result["reason_codes"] == [
            "UPSTREAM_LADDER_UNAVAILABLE", "OUTPUT_SUPPRESSED"]
        assert result["sections"]["ladder"] is None
        assert result["sections"]["gap"] is None

    def test_facts_unavailable_beats_producer_partial(self):
        producer = _producer(status="partial")
        health = _facts_data_health(transport_success=False,
                                    parse_success=False,
                                    required_field_present=False,
                                    data_array_present=False,
                                    upstream_null=True)
        result = daily.compute_daily_facts(
            _input(producer=producer, facts_data_health=health))
        assert result["status"] == "unavailable"
        assert result["reason_codes"] == [
            "UPSTREAM_LADDER_PARTIAL", "OUTPUT_SUPPRESSED"]
        assert result["sections"]["facts"]["status"] == "unavailable"

    def test_facts_partial_with_normal_producer(self):
        health = _facts_data_health(coverage_warning=True)
        result = daily.compute_daily_facts(
            _input(facts_data_health=health))
        assert result["status"] == "partial"
        assert result["reason_codes"] == ["OUTPUT_SUPPRESSED"]
        assert result["sections"]["facts"]["status"] == "partial"
        assert result["sections"]["ladder"]["status"] == "normal"

    def test_breadth_invalid_facts_partial(self):
        result = daily.compute_daily_facts(
            _input(breadth=_breadth(advance_count=-1)))
        # Slice 1：breadth 非法 -> BREADTH_UNAVAILABLE + 降级 partial
        assert result["status"] == "partial"
        assert result["sections"]["facts"]["status"] == "partial"
        assert "BREADTH_UNAVAILABLE" in result["sections"]["facts"]["reason_codes"]

    def test_huge_lbc_gap_section_invalid(self):
        rows = [{"stock_code": "600001", "lbc": 10 ** 30}]
        producer = _producer(snapshot=_adapter(rows=rows))
        result = daily.compute_daily_facts(_input(producer=producer))
        assert result["status"] == "invalid"
        assert result["reason_codes"] == ["OUTPUT_SUPPRESSED"]
        assert result["sections"]["ladder"]["status"] == "normal"
        assert result["sections"]["gap"]["status"] == "invalid"


# ---------------------------------------------------------------------------
# 4. 输入合同
# ---------------------------------------------------------------------------

class TestInputContract:
    @pytest.mark.parametrize("bad", [None, "x", 1, [], ("a",)])
    def test_non_dict(self, bad):
        result = daily.compute_daily_facts(bad)
        _assert_invalid(result)

    def test_dict_subclass(self):
        class D(dict):
            pass
        result = daily.compute_daily_facts(D(_input()))
        _assert_invalid(result)

    @pytest.mark.parametrize("missing", [
        "final_snapshot", "breadth", "limit_activity", "facts_data_health"])
    def test_missing_key(self, missing):
        data = _input()
        del data[missing]
        result = daily.compute_daily_facts(data)
        _assert_invalid(result)

    def test_extra_key_ignored(self):
        data = _input()
        data["extra"] = 1
        result = daily.compute_daily_facts(data)
        assert result["status"] == "normal"
        assert "extra" not in result


# ---------------------------------------------------------------------------
# 5. producer 合同
# ---------------------------------------------------------------------------

class TestProducerContract:
    def _assert_producer_invalid(self, producer):
        result = daily.compute_daily_facts(_input(producer=producer))
        _assert_invalid(result, reason_code="PRODUCER_CONTRACT_INVALID")

    def test_non_dict(self):
        self._assert_producer_invalid("x")

    def test_wrong_schema(self):
        producer = _producer()
        producer["schema_version"] = "wrong"
        self._assert_producer_invalid(producer)

    def test_extra_field(self):
        producer = _producer()
        producer["extra"] = 1
        self._assert_producer_invalid(producer)

    def test_missing_field(self):
        producer = _producer()
        del producer["warnings"]
        self._assert_producer_invalid(producer)

    def test_illegal_status(self):
        self._assert_producer_invalid(_producer(status="weird"))

    def test_partial_with_snapshot(self):
        producer = _producer(status="partial", snapshot=_adapter())
        self._assert_producer_invalid(producer)

    def test_partial_empty_reason_codes(self):
        producer = _producer(status="partial", reason_codes=[])
        self._assert_producer_invalid(producer)

    def test_normal_not_complete(self):
        producer = _producer(completed_observations=2,
                             stable_observation_count=2,
                             actual_stability_window_seconds=2.2,
                             last_observation_monotonic=102.2)
        self._assert_producer_invalid(producer)

    def test_normal_interval_tampered(self):
        self._assert_producer_invalid(_producer(
            observation_interval_seconds=2.1))

    def test_bad_trade_date(self):
        self._assert_producer_invalid(
            _producer(date_str="2026-02-30"))

    def test_bad_observed_at(self):
        producer = _producer()
        producer["observed_at"] = "not-a-time"
        self._assert_producer_invalid(producer)

    @pytest.mark.parametrize("status", ["normal", "partial", "unavailable"])
    def test_observed_at_none_invalid(self, status):
        producer = _producer(status=status)
        producer["observed_at"] = None
        self._assert_producer_invalid(producer)

    def test_nested_adapter_observed_at_none_invalid(self):
        adapter = _adapter()
        adapter["observed_at"] = None
        self._assert_producer_invalid(_producer(snapshot=adapter))

    def test_is_final_mismatch(self):
        producer = _producer(session="final", is_final=False)
        self._assert_producer_invalid(producer)

    def test_timing_inconsistent(self):
        producer = _producer(
            first_observation_monotonic=100.0,
            last_observation_monotonic=103.0,
            actual_stability_window_seconds=2.0)
        self._assert_producer_invalid(producer)

    def test_nested_adapter_invalid(self):
        adapter = _adapter()
        adapter["source_id"] = "forged"
        self._assert_producer_invalid(_producer(snapshot=adapter))

    def test_nested_adapter_rows_invalid(self):
        adapter = _adapter(rows=[{"stock_code": "600001", "lbc": True}])
        self._assert_producer_invalid(_producer(snapshot=adapter))

    def test_nested_adapter_row_count_mismatch(self):
        adapter = _adapter(rows=[{"stock_code": "600001", "lbc": 1}],
                           row_count=2)
        self._assert_producer_invalid(_producer(snapshot=adapter))


# ---------------------------------------------------------------------------
# 6. 输出合同
# ---------------------------------------------------------------------------

class TestOutputContract:
    def test_section_schemas(self):
        result = daily.compute_daily_facts(_input())
        assert result["sections"]["facts"]["schema_version"] == (
            "short-term-market-facts-v0.1")
        assert result["sections"]["ladder"]["schema_version"] == (
            "short-term-limit-up-ladder-v0.1")
        assert result["sections"]["gap"]["schema_version"] == (
            "short-term-ladder-gap-v0.1")

    def test_source_fields(self):
        producer = _producer(status="partial")
        result = daily.compute_daily_facts(_input(producer=producer))
        assert result["source_schema_version"] == (
            "short-term-limit-up-final-snapshot-v0.1")
        assert result["source_status"] == "partial"
        assert result["source_reason_codes"] == ["SOURCE_PARTIAL"]

    def test_metadata_copied(self):
        producer = _producer(date_str="2026-07-30")
        result = daily.compute_daily_facts(_input(producer=producer))
        assert result["trade_date"] == "2026-07-30"
        assert result["sections"]["facts"]["trade_date"] == "2026-07-30"
        assert result["sections"]["ladder"]["trade_date"] == "2026-07-30"


# ---------------------------------------------------------------------------
# 7. 输入不可变性与引用隔离
# ---------------------------------------------------------------------------

class TestImmutability:
    def test_input_deep_equal_after(self):
        data = _input()
        original = copy.deepcopy(data)
        daily.compute_daily_facts(data)
        assert data == original

    @pytest.mark.parametrize("status", ["partial", "unavailable"])
    def test_input_deep_equal_after_failures(self, status):
        data = _input(producer=_producer(status=status))
        original = copy.deepcopy(data)
        daily.compute_daily_facts(data)
        assert data == original

    def test_no_shared_mutable_references(self):
        data = _input()
        result = daily.compute_daily_facts(data)
        assert result["source_ids"] is not data["final_snapshot"]["snapshot"]
        assert result["sections"]["ladder"] is not None
        rows = result["sections"]["ladder"]["metrics"]["ladder"]
        adapter_rows = data["final_snapshot"]["snapshot"]["rows"]
        assert rows is not adapter_rows
        assert result["sections"]["facts"] is not data["breadth"]


# ---------------------------------------------------------------------------
# 8. 普通异常边界与进程控制
# ---------------------------------------------------------------------------

class TestExceptionBoundary:
    HELPERS = [
        "_validate_producer",
        "_validate_nested_adapter",
        "_build_ladder_snapshot",
        "_build_facts_snapshot",
        "_normal_envelope",
    ]

    @pytest.mark.parametrize("target", HELPERS)
    @pytest.mark.parametrize("exc", [
        RuntimeError("boom-daily-facts"),
        ValueError("boom-daily-facts"),
        TypeError("boom-daily-facts"),
    ])
    def test_ordinary_exception_fixed_fallback(self, monkeypatch, target, exc):
        def raiser(*args, **kwargs):
            raise exc
        monkeypatch.setattr(daily, target, raiser)
        result = daily.compute_daily_facts(_input())
        _assert_invalid(result, reason_code="INPUT_CONTRACT_INVALID")
        assert "boom-daily-facts" not in repr(result)
        assert "boom-daily-facts" not in str(result)

    @pytest.mark.parametrize("target", HELPERS)
    @pytest.mark.parametrize("exc", [
        KeyboardInterrupt(),
        SystemExit(1),
        GeneratorExit(),
    ])
    def test_process_control_propagates(self, monkeypatch, target, exc):
        def raiser(*args, **kwargs):
            raise exc
        monkeypatch.setattr(daily, target, raiser)
        with pytest.raises(type(exc)):
            daily.compute_daily_facts(_input())

    @pytest.mark.parametrize("exc", [
        RuntimeError("boom-calc"),
        ValueError("boom-calc"),
        TypeError("boom-calc"),
    ])
    def test_imported_calculator_raise_fallback(self, monkeypatch, exc):
        def raiser(*args, **kwargs):
            raise exc
        monkeypatch.setattr(
            daily.short_term_market_facts,
            "compute_short_term_market_facts",
            raiser)
        result = daily.compute_daily_facts(_input())
        assert result["status"] == "invalid"
        assert "boom-calc" not in str(result)

    def test_emergency_exact_literal(self, monkeypatch):
        def raiser(*args, **kwargs):
            raise RuntimeError("secret")
        monkeypatch.setattr(daily, "_evaluate", raiser)
        result = daily.compute_daily_facts(_input())
        _assert_invalid(result, reason_code="INPUT_CONTRACT_INVALID")
        assert result["sections"] == {
            "facts": None, "ladder": None, "gap": None}
        assert result["limitations"] == [
            "composed from approved BK-11 pure calculators",
            "does not validate upstream consecutive-limit-up semantics",
            "does not compute layered promotion rates",
            "production integration not authorized",
        ]


# ---------------------------------------------------------------------------
# 9. 跨调用隔离
# ---------------------------------------------------------------------------

class TestCrossCallIsolation:
    def test_normal_cross_call(self):
        first = daily.compute_daily_facts(_input())
        second = daily.compute_daily_facts(_input())
        first["limitations"].append("mutated")
        first["sections"]["ladder"]["metrics"]["ladder"].append(
            {"boards": 9, "count": 1})
        assert second["limitations"] == [
            "composed from approved BK-11 pure calculators",
            "does not validate upstream consecutive-limit-up semantics",
            "does not compute layered promotion rates",
            "production integration not authorized",
        ]
        assert second["sections"]["ladder"]["metrics"]["ladder"] == [
            {"boards": 2, "count": 1}]

    def test_failure_cross_call(self):
        producer = _producer(status="partial")
        first = daily.compute_daily_facts(_input(producer=producer))
        second = daily.compute_daily_facts(_input(producer=producer))
        first["reason_codes"].append("MUTATED")
        assert second["reason_codes"] == [
            "UPSTREAM_LADDER_PARTIAL", "OUTPUT_SUPPRESSED"]
