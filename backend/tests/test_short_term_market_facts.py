"""BK-11 Slice 1 短线市场事实纯计算层离线测试。

直接只读加载 Slice 0 已验收 fixture（docs/research/BK11_SHORT_TERM_FACTS_FIXTURE_V01.json），
不复制 fixture、不生成第二份 fixture、不联网。
"""

import copy
import io
import json
import math
import os
import socket

import pytest

import short_term_market_facts as stmf
from short_term_market_facts import SCHEMA_VERSION, compute_short_term_market_facts


def _no_time_boom(*args, **kwargs):
    raise AssertionError("module must not read current time")


_FIXTURE_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "docs",
        "research",
        "BK11_SHORT_TERM_FACTS_FIXTURE_V01.json",
    )
)

_ENVELOPE_FIELDS = {
    "schema_version",
    "trade_date",
    "session",
    "is_final",
    "source_ids",
    "fetched_at",
    "snapshot_at",
    "status",
    "reason_codes",
    "warnings",
    "limitations",
    "data_health",
    "facts",
}

_FACT_FIELDS = {
    "advance_count",
    "decline_count",
    "flat_count",
    "suspended_count",
    "eligible_count",
    "valid_count",
    "up_ratio",
    "limit_up_count",
    "limit_down_count",
    "failed_limit_up_count",
    "touched_limit_up_count",
    "sealed_limit_up_count",
    "failed_board_rate",
    "seal_rate",
}

_DATA_HEALTH_FIELDS = {
    "transport_success",
    "parse_success",
    "required_field_present",
    "data_array_present",
    "trade_date_match",
    "row_count",
    "legal_zero",
    "upstream_null",
    "unexplained_empty",
    "coverage_warning",
}

_BLOCKED_FACT_NAMES = [
    "touched_limit_down_count",
    "max_boards",
    "lianban_count",
    "ladder",
    "layered_promotion_rates",
    "promotion",
    "promotion_rate",
    "next_open_return",
    "next_close_return",
    "next_high_return",
    "premium",
    "loss_effect",
    "seal_quality",
    "seal_quality_full",
    "first_limit_up_time",
    "last_limit_up_time",
    "open_count",
    "seal_amount",
    "seal_volume",
    "seal_ratio",
    "turnover_amount",
    "turnover_rate",
    "float_market_cap",
    "theme",
    "theme_structure",
    "history",
    "T+1",
]


# ---------------------------------------------------------------------------
# fixture 只读加载
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fixture_doc():
    with open(_FIXTURE_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def fixture_cases(fixture_doc):
    return {case["case_id"]: case for case in fixture_doc["cases"]}


# 哨兵：用于参数化测试中明确区分"显式 is_final=None"与"字段缺失"。
# 不得用 None 兼任两种语义。当前实现将两种场景拆成独立参数化测试，
# 显式 null 通过 snap["is_final"] = None 写入，字段缺失通过 del snap["is_final"] 实现。
_MISSING = object()


def _base_snapshot() -> dict:
    """构造一个结构合法的最小 normal snapshot（合成值，非真实行情）。"""
    return {
        "trade_date": "2026-07-30",
        "session": "final",
        "is_final": True,
        "source_ids": ["eastmoney_limit_pool", "eastmoney_market_breadth"],
        "fetched_at": "2026-07-30T07:30:00.000000Z",
        "snapshot_at": "2026-07-30T07:35:00.000000Z",
        "universe": {},
        "breadth": {
            "advance_count": 100,
            "decline_count": 60,
            "flat_count": 40,
            "suspended_count": 5,
            "eligible_count": 205,
        },
        "limit_activity": {
            "limit_up_count": 7,
            "limit_down_count": 3,
            "failed_limit_up_count": 3,
        },
        "data_health": {
            "transport_success": True,
            "parse_success": True,
            "required_field_present": True,
            "data_array_present": True,
            "trade_date_match": True,
            "row_count": 7,
            "legal_zero": False,
            "upstream_null": False,
            "unexplained_empty": False,
            "coverage_warning": False,
        },
        "limitations": ["single-source, not cross-validated"],
        "reason_codes": [],
    }


def _r4(value: float) -> float:
    return round(value, 4)


# ---------------------------------------------------------------------------
# 13.1 基本合同
# ---------------------------------------------------------------------------


class TestBasicContract:
    def test_schema_version_exact(self):
        assert SCHEMA_VERSION == "short-term-market-facts-v0.1"

    def test_envelope_fields_exact(self):
        result = compute_short_term_market_facts(_base_snapshot())
        assert set(result.keys()) == _ENVELOPE_FIELDS
        assert result["schema_version"] == SCHEMA_VERSION

    def test_facts_fields_exact(self):
        result = compute_short_term_market_facts(_base_snapshot())
        assert set(result["facts"].keys()) == _FACT_FIELDS

    def test_data_health_fields_exact(self):
        result = compute_short_term_market_facts(_base_snapshot())
        assert set(result["data_health"].keys()) == _DATA_HEALTH_FIELDS

    def test_status_only_three_states(self):
        for snap in (
            _base_snapshot(),
            None,
            {},
            [],
            "garbage",
        ):
            result = compute_short_term_market_facts(snap)
            assert result["status"] in {"normal", "partial", "unavailable"}

    def test_json_serializable_no_nan_infinity(self):
        for snap in (_base_snapshot(), {}, None):
            result = compute_short_term_market_facts(snap)
            text = json.dumps(result, allow_nan=False)
            assert "NaN" not in text
            assert "Infinity" not in text


# ---------------------------------------------------------------------------
# 13.2 Fixture 三场景
# ---------------------------------------------------------------------------


class TestFixtureScenarios:
    def test_fixture_headers(self, fixture_doc):
        assert fixture_doc["schema_version"] == "bk11-short-term-facts-fixture.v0.1"
        assert fixture_doc["fixture_kind"] == "synthetic-normalized"

    def test_normal_case(self, fixture_cases):
        case = copy.deepcopy(fixture_cases["normal"])
        result = compute_short_term_market_facts(case)
        assert result["status"] == "normal"
        breadth = fixture_cases["normal"]["breadth"]
        facts = result["facts"]
        assert facts["advance_count"] == breadth["advance_count"]
        assert facts["decline_count"] == breadth["decline_count"]
        assert facts["flat_count"] == breadth["flat_count"]
        assert facts["suspended_count"] == breadth["suspended_count"]
        assert facts["eligible_count"] == breadth["eligible_count"]
        valid = breadth["advance_count"] + breadth["decline_count"] + breadth["flat_count"]
        assert facts["valid_count"] == valid
        assert facts["up_ratio"] == _r4(breadth["advance_count"] / valid)
        activity = fixture_cases["normal"]["limit_activity"]
        assert facts["limit_up_count"] == activity["limit_up_count"]
        assert facts["limit_down_count"] == activity["limit_down_count"]
        assert facts["failed_limit_up_count"] == activity["failed_limit_up_count"]
        touched = activity["limit_up_count"] + activity["failed_limit_up_count"]
        assert facts["touched_limit_up_count"] == touched
        assert facts["sealed_limit_up_count"] == activity["limit_up_count"]
        assert facts["failed_board_rate"] == _r4(activity["failed_limit_up_count"] / touched)
        assert facts["seal_rate"] == _r4(activity["limit_up_count"] / touched)
        assert abs(facts["failed_board_rate"] + facts["seal_rate"] - 1.0) <= 1e-4
        assert result["is_final"] is True

    def test_partial_case(self, fixture_cases):
        case = copy.deepcopy(fixture_cases["partial"])
        result = compute_short_term_market_facts(case)
        assert result["status"] == "partial"
        assert result["facts"]["up_ratio"] == 0.5629
        activity = fixture_cases["partial"]["limit_activity"]
        touched = activity["limit_up_count"] + activity["failed_limit_up_count"]
        assert result["facts"]["failed_board_rate"] == _r4(activity["failed_limit_up_count"] / touched)
        assert result["facts"]["seal_rate"] == _r4(activity["limit_up_count"] / touched)
        assert "PARTIAL_COVERAGE" in result["reason_codes"]

    def test_unavailable_case(self, fixture_cases):
        case = copy.deepcopy(fixture_cases["unavailable"])
        result = compute_short_term_market_facts(case)
        assert result["status"] == "unavailable"
        assert all(value is None for value in result["facts"].values())
        assert set(result["facts"].keys()) == _FACT_FIELDS
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]
        blob = json.dumps(result)
        for marker in ("TimeoutError", "Traceback", "ProxyError", "HTTPError"):
            assert marker not in blob


# ---------------------------------------------------------------------------
# 13.3 纯计算
# ---------------------------------------------------------------------------


class TestPureComputation:
    def test_input_not_mutated(self):
        snap = _base_snapshot()
        before = copy.deepcopy(snap)
        compute_short_term_market_facts(snap)
        assert snap == before

    def test_deterministic_repeat_calls(self):
        snap = _base_snapshot()
        first = compute_short_term_market_facts(snap)
        second = compute_short_term_market_facts(snap)
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def test_no_current_time(self, monkeypatch):
        import time as _time
        from datetime import datetime as _dt

        class _NoNowDatetime(_dt):
            @classmethod
            def now(cls, *args, **kwargs):
                raise AssertionError("module must not read current time")

            @classmethod
            def utcnow(cls, *args, **kwargs):
                raise AssertionError("module must not read current time")

            @classmethod
            def today(cls, *args, **kwargs):
                raise AssertionError("module must not read current time")

        monkeypatch.setattr(_time, "time", _no_time_boom)
        monkeypatch.setattr(stmf, "datetime", _NoNowDatetime)
        result = compute_short_term_market_facts(_base_snapshot())
        assert result["status"] == "normal"

    def test_no_environment_access(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise AssertionError("module must not read environment variables")

        monkeypatch.setattr(os, "environ", {})
        monkeypatch.setattr(os, "getenv", _boom)
        result = compute_short_term_market_facts(_base_snapshot())
        assert result["status"] == "normal"

    def test_no_file_writes(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise AssertionError("module must not write files")

        monkeypatch.setattr(io, "open", _boom)
        result = compute_short_term_market_facts(_base_snapshot())
        assert result["status"] == "normal"

    def test_no_network(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise AssertionError("module must not access network")

        monkeypatch.setattr(socket, "socket", _boom)
        result = compute_short_term_market_facts(_base_snapshot())
        assert result["status"] == "normal"

    def test_module_import_boundary(self):
        source_path = os.path.abspath(stmf.__file__)
        with open(source_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        for forbidden in (
            "requests",
            "httpx",
            "urllib",
            "sqlite3",
            "os.environ",
            "getenv",
            "write_text",
            "write_bytes",
        ):
            assert forbidden not in source


# ---------------------------------------------------------------------------
# 13.4 数值边界
# ---------------------------------------------------------------------------


class TestNumericBoundaries:
    def test_legal_zero_limit_activity(self):
        snap = _base_snapshot()
        snap["limit_activity"] = {
            "limit_up_count": 0,
            "limit_down_count": 0,
            "failed_limit_up_count": 0,
        }
        snap["data_health"]["legal_zero"] = True
        snap["data_health"]["row_count"] = 0
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "normal"
        facts = result["facts"]
        assert facts["touched_limit_up_count"] == 0
        assert facts["sealed_limit_up_count"] == 0
        assert facts["failed_board_rate"] is None
        assert facts["seal_rate"] is None

    def test_zero_valid_count_up_ratio_null(self):
        snap = _base_snapshot()
        snap["breadth"] = {
            "advance_count": 0,
            "decline_count": 0,
            "flat_count": 0,
            "suspended_count": 10,
            "eligible_count": 10,
        }
        result = compute_short_term_market_facts(snap)
        assert result["facts"]["valid_count"] == 0
        assert result["facts"]["up_ratio"] is None

    @pytest.mark.parametrize("bad", [-1, 2.5, True, False, "10", math.nan, math.inf])
    def test_invalid_count_rejected(self, bad):
        snap = _base_snapshot()
        snap["breadth"]["advance_count"] = bad
        result = compute_short_term_market_facts(snap)
        assert result["status"] != "normal"
        assert "INVALID_COUNT" in result["reason_codes"]
        assert result["facts"]["advance_count"] is None

    def test_huge_counts_safe(self):
        snap = _base_snapshot()
        huge = 10**18
        snap["breadth"] = {
            "advance_count": huge,
            "decline_count": huge,
            "flat_count": 0,
            "suspended_count": 0,
            "eligible_count": huge * 2,
        }
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "normal"
        assert result["facts"]["up_ratio"] == 0.5
        blob = json.dumps(result, allow_nan=False)
        assert "NaN" not in blob and "Infinity" not in blob

    def test_nan_in_derived_input_never_reaches_output(self):
        snap = _base_snapshot()
        snap["breadth"]["up_ratio"] = math.nan
        snap["limit_activity"]["failed_board_rate"] = math.inf
        result = compute_short_term_market_facts(snap)
        assert "DERIVED_VALUE_MISMATCH" in result["reason_codes"]
        blob = json.dumps(result, allow_nan=False)
        assert "NaN" not in blob and "Infinity" not in blob


# ---------------------------------------------------------------------------
# 13.5 恒等式
# ---------------------------------------------------------------------------


class TestIdentities:
    def test_all_identities(self):
        snap = _base_snapshot()
        result = compute_short_term_market_facts(snap)
        facts = result["facts"]
        assert facts["valid_count"] == facts["advance_count"] + facts["decline_count"] + facts["flat_count"]
        assert facts["eligible_count"] == facts["valid_count"] + facts["suspended_count"]
        assert facts["touched_limit_up_count"] == facts["limit_up_count"] + facts["failed_limit_up_count"]
        assert facts["sealed_limit_up_count"] == facts["limit_up_count"]
        assert facts["failed_board_rate"] == _r4(
            facts["failed_limit_up_count"] / facts["touched_limit_up_count"]
        )
        assert facts["seal_rate"] == _r4(facts["limit_up_count"] / facts["touched_limit_up_count"])
        assert abs(facts["failed_board_rate"] + facts["seal_rate"] - 1.0) <= 1e-4

    def test_breadth_identity_invalid(self):
        snap = _base_snapshot()
        snap["breadth"]["eligible_count"] = 9999
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "partial"
        assert "BREADTH_IDENTITY_INVALID" in result["reason_codes"]
        assert result["facts"]["advance_count"] is None
        assert result["facts"]["up_ratio"] is None
        # limit activity 独立有效
        assert result["facts"]["limit_up_count"] == 7


# ---------------------------------------------------------------------------
# 13.6 派生字段不可信
# ---------------------------------------------------------------------------


class TestDerivedFieldsNotTrusted:
    def test_wrong_derived_values_recomputed(self):
        snap = _base_snapshot()
        snap["breadth"]["valid_count"] = 4321
        snap["breadth"]["up_ratio"] = 0.9999
        snap["limit_activity"]["touched_limit_up_count"] = 1234
        snap["limit_activity"]["sealed_limit_up_count"] = 999
        snap["limit_activity"]["failed_board_rate"] = 0.0001
        snap["limit_activity"]["seal_rate"] = 0.0002
        result = compute_short_term_market_facts(snap)
        facts = result["facts"]
        assert facts["valid_count"] == 200
        assert facts["up_ratio"] == _r4(100 / 200)
        assert facts["touched_limit_up_count"] == 10
        assert facts["sealed_limit_up_count"] == 7
        assert facts["failed_board_rate"] == _r4(3 / 10)
        assert facts["seal_rate"] == _r4(7 / 10)
        assert result["status"] == "partial"
        assert "DERIVED_VALUE_MISMATCH" in result["reason_codes"]

    def test_correct_derived_values_no_mismatch(self):
        snap = _base_snapshot()
        snap["breadth"]["valid_count"] = 200
        snap["breadth"]["up_ratio"] = 0.5
        snap["limit_activity"]["touched_limit_up_count"] = 10
        snap["limit_activity"]["sealed_limit_up_count"] = 7
        snap["limit_activity"]["failed_board_rate"] = 0.3
        snap["limit_activity"]["seal_rate"] = 0.7
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "normal"
        assert "DERIVED_VALUE_MISMATCH" not in result["reason_codes"]


# ---------------------------------------------------------------------------
# 13.7 独立降级
# ---------------------------------------------------------------------------


class TestIndependentDegradation:
    def test_only_breadth_available(self):
        snap = _base_snapshot()
        snap["limit_activity"] = None
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "partial"
        assert "LIMIT_ACTIVITY_UNAVAILABLE" in result["reason_codes"]
        assert result["facts"]["advance_count"] == 100
        assert result["facts"]["limit_up_count"] is None

    def test_only_limit_activity_available(self):
        snap = _base_snapshot()
        snap["breadth"] = None
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "partial"
        assert "BREADTH_UNAVAILABLE" in result["reason_codes"]
        assert result["facts"]["limit_up_count"] == 7
        assert result["facts"]["advance_count"] is None

    def test_both_components_invalid(self):
        snap = _base_snapshot()
        snap["breadth"] = None
        snap["limit_activity"] = None
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "unavailable"
        assert all(value is None for value in result["facts"].values())

    @pytest.mark.parametrize("field", ["transport_success", "parse_success", "required_field_present", "data_array_present"])
    def test_global_failure_flags(self, field):
        snap = _base_snapshot()
        snap["data_health"][field] = False
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "unavailable"
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]
        assert all(value is None for value in result["facts"].values())

    def test_global_failure_ignores_residual_counts(self):
        snap = _base_snapshot()
        snap["data_health"]["transport_success"] = False
        # 残留数据不得被使用
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "unavailable"
        assert result["facts"]["advance_count"] is None

    def test_trade_date_mismatch_partial(self):
        snap = _base_snapshot()
        snap["data_health"]["trade_date_match"] = False
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "partial"
        assert "TRADE_DATE_MISMATCH" in result["reason_codes"]

    def test_coverage_warning_partial(self):
        snap = _base_snapshot()
        snap["data_health"]["coverage_warning"] = True
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "partial"
        assert "PARTIAL_COVERAGE" in result["reason_codes"]

    def test_upstream_null_unavailable(self):
        snap = _base_snapshot()
        snap["data_health"]["upstream_null"] = True
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "unavailable"
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]

    def test_unexplained_empty_not_legal_zero(self):
        snap = _base_snapshot()
        snap["data_health"]["unexplained_empty"] = True
        snap["data_health"]["legal_zero"] = False
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "partial"
        assert "UNEXPLAINED_EMPTY" in result["reason_codes"]

    def test_legal_zero_not_degraded(self):
        snap = _base_snapshot()
        snap["limit_activity"] = {
            "limit_up_count": 0,
            "limit_down_count": 0,
            "failed_limit_up_count": 0,
        }
        snap["data_health"]["legal_zero"] = True
        snap["data_health"]["row_count"] = 0
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "normal"

    def test_bool_not_accepted_as_data_health_flag(self):
        snap = _base_snapshot()
        snap["data_health"]["transport_success"] = 1
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "unavailable"

    def test_bool_not_accepted_as_row_count(self):
        snap = _base_snapshot()
        snap["data_health"]["row_count"] = True
        result = compute_short_term_market_facts(snap)
        assert result["data_health"]["row_count"] == 0


# ---------------------------------------------------------------------------
# 13.8 元数据
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_source_ids_dedup_order_stable(self):
        snap = _base_snapshot()
        snap["source_ids"] = ["b_source", "a_source", "b_source", "a_source"]
        result = compute_short_term_market_facts(snap)
        assert result["source_ids"] == ["b_source", "a_source"]

    def test_invalid_source_id_items_dropped_and_degraded(self):
        snap = _base_snapshot()
        snap["source_ids"] = ["ok_source", "", 123, None]
        result = compute_short_term_market_facts(snap)
        assert result["source_ids"] == ["ok_source"]
        assert "METADATA_INVALID" in result["reason_codes"]
        assert result["status"] == "partial"

    def test_fetched_after_snapshot_degraded(self):
        snap = _base_snapshot()
        snap["fetched_at"] = "2026-07-30T08:00:00.000000Z"
        snap["snapshot_at"] = "2026-07-30T07:00:00.000000Z"
        result = compute_short_term_market_facts(snap)
        assert "METADATA_INVALID" in result["reason_codes"]
        assert result["status"] == "partial"

    @pytest.mark.parametrize("bad", ["not-a-timestamp", "2026-07-30 07:30:00", 12345])
    def test_invalid_utc_string_degraded(self, bad):
        snap = _base_snapshot()
        snap["fetched_at"] = bad
        result = compute_short_term_market_facts(snap)
        assert result["fetched_at"] is None
        assert "METADATA_INVALID" in result["reason_codes"]

    def test_non_utc_timezone_rejected(self):
        snap = _base_snapshot()
        snap["fetched_at"] = "2026-07-30T15:30:00.000000+08:00"
        result = compute_short_term_market_facts(snap)
        assert result["fetched_at"] is None
        assert "METADATA_INVALID" in result["reason_codes"]

    def test_final_session_requires_is_final_true(self):
        snap = _base_snapshot()
        snap["session"] = "final"
        snap["is_final"] = False
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "final"
        assert result["is_final"] is True
        assert "METADATA_INVALID" in result["reason_codes"]
        assert result["status"] == "partial"

    def test_non_final_session_requires_is_final_false(self):
        snap = _base_snapshot()
        snap["session"] = "call_auction"
        snap["is_final"] = True
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "call_auction"
        assert result["is_final"] is False
        assert "METADATA_INVALID" in result["reason_codes"]
        assert result["status"] == "partial"

    def test_invalid_session_degraded(self):
        snap = _base_snapshot()
        snap["session"] = "lunch_time"
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "unavailable"
        assert "METADATA_INVALID" in result["reason_codes"]

    def test_invalid_trade_date_degraded(self):
        snap = _base_snapshot()
        snap["trade_date"] = "30/07/2026"
        result = compute_short_term_market_facts(snap)
        assert result["trade_date"] is None
        assert "METADATA_INVALID" in result["reason_codes"]


# ---------------------------------------------------------------------------
# 13.9 安全失败
# ---------------------------------------------------------------------------


class TestSafeFailure:
    @pytest.mark.parametrize(
        "bad_input",
        [
            None,
            [],
            [1, 2, 3],
            {},
            "snapshot",
            42,
            3.14,
            object(),
            {"breadth": "not-a-dict", "limit_activity": 7},
            {"breadth": {"advance_count": object()}},
            {"data_health": object()},
        ],
    )
    def test_never_raises(self, bad_input):
        result = compute_short_term_market_facts(bad_input)
        assert set(result.keys()) == _ENVELOPE_FIELDS
        assert result["status"] in {"normal", "partial", "unavailable"}
        assert set(result["facts"].keys()) == _FACT_FIELDS
        json.dumps(result, allow_nan=False)

    def test_empty_dict_unavailable(self):
        result = compute_short_term_market_facts({})
        assert result["status"] == "unavailable"
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]

    def test_fallback_does_not_leak_exception_text(self):
        class Exploding(dict):
            def get(self, *args, **kwargs):
                raise RuntimeError("secret-internal-detail")

        result = compute_short_term_market_facts(Exploding())
        blob = json.dumps(result)
        assert "secret-internal-detail" not in blob
        assert "RuntimeError" not in blob
        assert result["status"] == "unavailable"


# ---------------------------------------------------------------------------
# 13.10 范围阻断
# ---------------------------------------------------------------------------


class TestBlockedScope:
    def test_blocked_fields_absent_from_facts(self, fixture_cases):
        for case_id, case in fixture_cases.items():
            result = compute_short_term_market_facts(copy.deepcopy(case))
            facts = result["facts"]
            assert set(facts.keys()) == _FACT_FIELDS
            for name in _BLOCKED_FACT_NAMES:
                assert name not in facts, f"blocked field {name} leaked in {case_id}"

    def test_blocked_fields_absent_from_synthetic(self):
        result = compute_short_term_market_facts(_base_snapshot())
        for name in _BLOCKED_FACT_NAMES:
            assert name not in result["facts"]
            assert name not in result

    def test_extra_input_fields_do_not_change_result(self):
        snap = _base_snapshot()
        baseline = compute_short_term_market_facts(copy.deepcopy(snap))
        snap["ladder"] = [{"boards": 2, "count": 3}]
        snap["theme_structure"] = {"anything": True}
        snap["extra_unknown_field"] = "noise"
        result = compute_short_term_market_facts(snap)
        assert result["facts"] == baseline["facts"]
        assert result["status"] == baseline["status"]


# ---------------------------------------------------------------------------
# 13.11 Session 缺失与非法值
# ---------------------------------------------------------------------------


class TestSessionValidation:
    def test_session_missing(self):
        snap = _base_snapshot()
        del snap["session"]
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "unavailable"
        assert "METADATA_INVALID" in result["reason_codes"]
        assert result["status"] == "partial"

    def test_session_none(self):
        snap = _base_snapshot()
        snap["session"] = None
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "unavailable"
        assert "METADATA_INVALID" in result["reason_codes"]
        assert result["status"] == "partial"

    def test_session_empty_string(self):
        snap = _base_snapshot()
        snap["session"] = ""
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "unavailable"
        assert "METADATA_INVALID" in result["reason_codes"]

    def test_session_uppercase_final(self):
        snap = _base_snapshot()
        snap["session"] = "FINAL"
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "unavailable"
        assert "METADATA_INVALID" in result["reason_codes"]

    def test_session_with_spaces(self):
        snap = _base_snapshot()
        snap["session"] = " final "
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "unavailable"
        assert "METADATA_INVALID" in result["reason_codes"]

    def test_session_list(self):
        snap = _base_snapshot()
        snap["session"] = []
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "unavailable"
        assert "METADATA_INVALID" in result["reason_codes"]

    def test_session_unknown_string(self):
        snap = _base_snapshot()
        snap["session"] = "unknown"
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "unavailable"
        assert "METADATA_INVALID" in result["reason_codes"]

    def test_session_none_with_is_final_true(self):
        snap = _base_snapshot()
        snap["session"] = None
        snap["is_final"] = True
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "unavailable"
        assert result["is_final"] is False
        assert "METADATA_INVALID" in result["reason_codes"]
        assert result["status"] == "partial"

    def test_invalid_session_with_global_failure(self):
        snap = _base_snapshot()
        snap["session"] = "unknown"
        snap["data_health"]["transport_success"] = False
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "unavailable"
        assert result["is_final"] is False
        assert result["status"] == "unavailable"
        assert "METADATA_INVALID" in result["reason_codes"]
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]

    def test_missing_is_final_degraded(self):
        snap = _base_snapshot()
        del snap["is_final"]
        result = compute_short_term_market_facts(snap)
        assert result["is_final"] is True
        assert "METADATA_INVALID" in result["reason_codes"]
        assert result["status"] == "partial"


# ---------------------------------------------------------------------------
# 13.11b Session / is_final 强制不变量
# ---------------------------------------------------------------------------


class TestSessionIsFinalInvariant:
    """is_final 必须由归一化后的 session 强制决定，绝不保留调用方冲突值。"""

    @pytest.mark.parametrize(
        "session_in,is_final_in,exp_session,exp_is_final",
        [
            # 非法 session + is_final=true → unavailable / false
            (None, True, "unavailable", False),
            ("unknown", True, "unavailable", False),
            ([], True, "unavailable", False),
            ("unavailable", True, "unavailable", False),
            # 合法 final + 冲突 → final / true
            ("final", False, "final", True),
            ("final", None, "final", True),       # 显式 null
            ("final", _MISSING, "final", True),   # 字段缺失
            # 合法非 final + 冲突 → 保留 session / false
            ("afternoon_session", True, "afternoon_session", False),
            ("morning_session", None, "morning_session", False),     # 显式 null
            ("morning_session", _MISSING, "morning_session", False), # 字段缺失
            # 非法 session + 显式 null / 缺失 → unavailable / false
            (None, None, "unavailable", False),
            (None, _MISSING, "unavailable", False),
            ("unknown", None, "unavailable", False),
            ("unknown", _MISSING, "unavailable", False),
            ("unavailable", None, "unavailable", False),
            ("unavailable", _MISSING, "unavailable", False),
            ("afternoon_session", None, "afternoon_session", False),
            ("afternoon_session", _MISSING, "afternoon_session", False),
        ],
    )
    def test_conflict_pairs_normalize_to_session(self, session_in, is_final_in, exp_session, exp_is_final):
        snap = _base_snapshot()
        snap["session"] = session_in
        # 使用哨兵 _MISSING 区分"显式 is_final=None"与"字段缺失"。
        if is_final_in is _MISSING:
            del snap["is_final"]
        else:
            snap["is_final"] = is_final_in
        result = compute_short_term_market_facts(snap)
        assert result["session"] == exp_session
        assert result["is_final"] is exp_is_final
        assert "METADATA_INVALID" in result["reason_codes"]
        # 无全局 Data Health 失败的冲突输入必须精确为 partial。
        assert result["status"] == "partial"

    def test_final_session_explicit_null_is_final(self):
        snap = _base_snapshot()
        snap["session"] = "final"
        snap["is_final"] = None
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "final"
        assert result["is_final"] is True
        assert result["status"] == "partial"
        assert "METADATA_INVALID" in result["reason_codes"]

    def test_final_session_missing_is_final(self):
        snap = _base_snapshot()
        snap["session"] = "final"
        del snap["is_final"]
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "final"
        assert result["is_final"] is True
        assert result["status"] == "partial"
        assert "METADATA_INVALID" in result["reason_codes"]

    def test_morning_session_explicit_null_is_final(self):
        snap = _base_snapshot()
        snap["session"] = "morning_session"
        snap["is_final"] = None
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "morning_session"
        assert result["is_final"] is False
        assert result["status"] == "partial"
        assert "METADATA_INVALID" in result["reason_codes"]

    def test_morning_session_missing_is_final(self):
        snap = _base_snapshot()
        snap["session"] = "morning_session"
        del snap["is_final"]
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "morning_session"
        assert result["is_final"] is False
        assert result["status"] == "partial"
        assert "METADATA_INVALID" in result["reason_codes"]

    @pytest.mark.parametrize("bad_is_final", [0, 1, "true", [], {}])
    def test_final_session_non_bool_is_final(self, bad_is_final):
        snap = _base_snapshot()
        snap["session"] = "final"
        snap["is_final"] = bad_is_final
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "final"
        assert result["is_final"] is True
        assert "METADATA_INVALID" in result["reason_codes"]
        assert result["status"] == "partial"

    @pytest.mark.parametrize("bad_is_final", [0, 1, "true", [], {}])
    def test_non_final_session_non_bool_is_final(self, bad_is_final):
        snap = _base_snapshot()
        snap["session"] = "morning_session"
        snap["is_final"] = bad_is_final
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "morning_session"
        assert result["is_final"] is False
        assert "METADATA_INVALID" in result["reason_codes"]
        assert result["status"] == "partial"

    @pytest.mark.parametrize(
        "session,exp_is_final",
        [
            ("pre_open", False),
            ("call_auction", False),
            ("morning_session", False),
            ("midday_break", False),
            ("afternoon_session", False),
            ("close_pending", False),
            ("final", True),
            ("unavailable", False),
        ],
    )
    def test_allowed_sessions_legal_is_final_no_metadata_invalid(self, session, exp_is_final):
        snap = _base_snapshot()
        snap["session"] = session
        snap["is_final"] = exp_is_final
        result = compute_short_term_market_facts(snap)
        assert result["session"] == session
        assert result["is_final"] is exp_is_final
        assert "METADATA_INVALID" not in result["reason_codes"]

    def test_global_failure_with_invalid_session_and_is_final_true(self):
        snap = _base_snapshot()
        snap["session"] = "unknown"
        snap["is_final"] = True
        snap["data_health"]["transport_success"] = False
        result = compute_short_term_market_facts(snap)
        assert result["session"] == "unavailable"
        assert result["is_final"] is False
        # 仅在明确全局 Data Health 失败时精确断言 unavailable。
        assert result["status"] == "unavailable"
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]
        assert "METADATA_INVALID" in result["reason_codes"]

    @pytest.mark.parametrize("bad_input", [None, [], [1, 2, 3], "snapshot", 42, 3.14, object()])
    def test_fallback_session_is_final_invariant(self, bad_input):
        result = compute_short_term_market_facts(bad_input)
        assert result["session"] == "unavailable"
        assert result["is_final"] is False
        assert result["status"] == "unavailable"

    def test_fallback_malicious_dict_subclass(self):
        class Exploding(dict):
            def get(self, *args, **kwargs):
                raise RuntimeError("secret-internal-detail")

        result = compute_short_term_market_facts(Exploding())
        assert result["session"] == "unavailable"
        assert result["is_final"] is False
        assert result["status"] == "unavailable"


# ---------------------------------------------------------------------------
# 13.12 Limitations 安全清洗
# ---------------------------------------------------------------------------


class TestLimitationSanitization:
    @pytest.mark.parametrize(
        "unsafe",
        [
            "http://internal.host/secret",
            "https://example.invalid/x",
            "ftp://files.example/data",
            "www.evil.com/path",
            "C:\\tmp\\path",
            "C:/tmp/path",
            "\\\\server\\share\\file",
            "/home/user/token.txt",
            "/tmp/debug.log",
            "/var/log/app.log",
            "/Users/admin/.ssh/id_rsa",
            "TimeoutError: boom",
            "ConnectionError: refused",
            "ProxyError: connect failed",
            "HTTPError: 502",
            "FileNotFoundError: missing.txt",
            "CustomProviderException: failed",
            "Traceback (most recent call last)",
        ],
    )
    def test_unsafe_limitations_filtered(self, unsafe):
        snap = _base_snapshot()
        snap["limitations"] = ["safe text", unsafe]
        result = compute_short_term_market_facts(snap)
        blob = json.dumps(result, ensure_ascii=False)
        assert unsafe not in blob
        assert "safe text" in result["limitations"]
        assert "METADATA_INVALID" in result["reason_codes"]
        assert result["status"] == "partial"
        assert _has_filtered_warning(result["warnings"])

    def test_safe_limitations_preserved(self):
        snap = _base_snapshot()
        snap["limitations"] = [
            "single-source, not cross-validated",
            "licensing_status: unclear",
        ]
        result = compute_short_term_market_facts(snap)
        assert "single-source, not cross-validated" in result["limitations"]
        assert "licensing_status: unclear" in result["limitations"]
        assert "METADATA_INVALID" not in result["reason_codes"]
        assert result["status"] == "normal"

    def test_filtered_warning_only_once(self):
        snap = _base_snapshot()
        snap["limitations"] = [
            "http://a.com",
            "https://b.com",
            "/tmp/x",
            "TimeoutError",
        ]
        result = compute_short_term_market_facts(snap)
        warning = "部分输入限制说明因包含不安全细节已过滤。"
        assert result["warnings"].count(warning) == 1

    def test_unsafe_in_unavailable_case(self):
        snap = _base_snapshot()
        snap["data_health"]["transport_success"] = False
        snap["limitations"] = ["https://secret.url/path", "safe note"]
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "unavailable"
        assert "METADATA_INVALID" in result["reason_codes"]
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]
        assert "safe note" in result["limitations"]
        assert "https://secret.url/path" not in json.dumps(result, ensure_ascii=False)
        assert _has_filtered_warning(result["warnings"])


def _has_filtered_warning(warnings):
    return "部分输入限制说明因包含不安全细节已过滤。" in warnings


# ---------------------------------------------------------------------------
# 13.13 Reason codes 由模块计算
# ---------------------------------------------------------------------------


class TestReasonCodeIsolation:
    def test_normal_with_injected_source_unavailable(self):
        snap = _base_snapshot()
        snap["reason_codes"] = ["SOURCE_UNAVAILABLE"]
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "normal"
        assert result["reason_codes"] == []

    def test_normal_with_injected_partial_coverage(self):
        snap = _base_snapshot()
        snap["reason_codes"] = ["PARTIAL_COVERAGE"]
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "normal"
        assert result["reason_codes"] == []

    def test_normal_with_injected_unknown_code(self):
        snap = _base_snapshot()
        snap["reason_codes"] = ["ARBITRARY_CODE"]
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "normal"
        assert result["reason_codes"] == []

    def test_normal_with_injected_duplicate_codes(self):
        snap = _base_snapshot()
        snap["reason_codes"] = [
            "SOURCE_UNAVAILABLE",
            "SOURCE_UNAVAILABLE",
            "PARTIAL_COVERAGE",
            "BREADTH_UNAVAILABLE",
        ]
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "normal"
        assert result["reason_codes"] == []

    def test_true_unavailable_with_empty_input_codes(self):
        snap = _base_snapshot()
        snap["data_health"]["transport_success"] = False
        snap["reason_codes"] = []
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "unavailable"
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]

    def test_true_partial_with_contradictory_input_codes(self):
        snap = _base_snapshot()
        snap["data_health"]["coverage_warning"] = True
        snap["reason_codes"] = ["SOURCE_UNAVAILABLE"]
        result = compute_short_term_market_facts(snap)
        assert result["status"] == "partial"
        assert "PARTIAL_COVERAGE" in result["reason_codes"]
        assert "SOURCE_UNAVAILABLE" not in result["reason_codes"]

    def test_fixture_partial_not_echoed(self, fixture_cases):
        case = copy.deepcopy(fixture_cases["partial"])
        case["reason_codes"] = ["SOURCE_UNAVAILABLE", "BREADTH_UNAVAILABLE"]
        result = compute_short_term_market_facts(case)
        assert "PARTIAL_COVERAGE" in result["reason_codes"]
        assert "SOURCE_UNAVAILABLE" not in result["reason_codes"]
        assert "BREADTH_UNAVAILABLE" not in result["reason_codes"]
