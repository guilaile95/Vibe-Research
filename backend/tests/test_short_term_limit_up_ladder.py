"""BK-11 Slice 2A 连板梯队纯计算层离线测试。

直接只读加载 Slice 0 已验收 fixture
（docs/research/BK11_SHORT_TERM_FACTS_FIXTURE_V01.json），
根据 fixture 聚合值程序化构造 limit_up_pool，不复制 fixture、
不生成第二份 fixture、不联网。
"""

import copy
import io
import json
import os
import socket

import pytest

import short_term_limit_up_ladder as stul
from short_term_limit_up_ladder import SCHEMA_VERSION, compute_limit_up_ladder


# ---------------------------------------------------------------------------
# fixture 只读加载
# ---------------------------------------------------------------------------

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
    "metrics",
}

_METRIC_FIELDS = {"max_boards", "lianban_count", "ladder"}

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

_BLOCKED_METRIC_NAMES = [
    "layered_promotion_rates",
    "promotion",
    "next_open_return",
    "next_close_return",
    "next_high_return",
    "premium",
    "loss_effect",
    "theme",
    "theme_structure",
    "seal_quality",
    "history",
    "T+1",
    "plus",
]


@pytest.fixture(scope="module")
def fixture_doc():
    with open(_FIXTURE_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def fixture_cases(fixture_doc):
    return {case["case_id"]: case for case in fixture_doc["cases"]}


# ---------------------------------------------------------------------------
# 辅助构造
# ---------------------------------------------------------------------------


def _base_snapshot() -> dict:
    """构造一个结构合法的最小 normal snapshot。"""
    return {
        "trade_date": "2026-07-30",
        "session": "final",
        "is_final": True,
        "source_ids": ["eastmoney_limit_pool"],
        "fetched_at": "2026-07-30T07:30:00.000000Z",
        "snapshot_at": "2026-07-30T07:35:00.000000Z",
        "limit_up_pool": [
            {"stock_code": "000001", "consecutive_limit_up_days": 1},
            {"stock_code": "000002", "consecutive_limit_up_days": 2},
            {"stock_code": "000003", "consecutive_limit_up_days": 2},
            {"stock_code": "000004", "consecutive_limit_up_days": 3},
        ],
        "data_health": {
            "transport_success": True,
            "parse_success": True,
            "required_field_present": True,
            "data_array_present": True,
            "trade_date_match": True,
            "row_count": 4,
            "legal_zero": False,
            "upstream_null": False,
            "unexplained_empty": False,
            "coverage_warning": False,
        },
        "reason_codes": [],
        "warnings": [],
        "limitations": [],
    }


def _build_pool_from_fixture(case: dict) -> list:
    """根据 fixture 聚合值程序化构造 limit_up_pool。

    first_board_count = limit_up_count - lianban_count
    生成 first_board_count 条 consecutive_limit_up_days=1 的唯一股票，
    再根据 fixture ladder 每个 {boards,count} 生成 count 条对应 boards 的唯一股票。

    验证：总行数 == limit_up_count，boards>=2 行数 == lianban_count。
    """
    activity = case["limit_activity"]
    limit_up_count = activity["limit_up_count"]
    lianban_count = activity["lianban_count"]
    ladder = activity["ladder"]

    first_board_count = limit_up_count - lianban_count
    assert first_board_count >= 0, "fixture limit_up_count < lianban_count"

    pool: list = []
    idx = 0

    # 首板
    for _ in range(first_board_count):
        idx += 1
        pool.append(
            {
                "stock_code": f"FB{idx:06d}",
                "consecutive_limit_up_days": 1,
            }
        )

    # ladder 档位（boards >= 2）
    boards_ge2_count = 0
    for entry in ladder:
        boards = entry["boards"]
        count = entry["count"]
        assert boards >= 2, "fixture ladder contains boards < 2"
        for _ in range(count):
            idx += 1
            pool.append(
                {
                    "stock_code": f"LB{idx:06d}",
                    "consecutive_limit_up_days": boards,
                }
            )
        boards_ge2_count += count

    # 合同验证
    assert len(pool) == limit_up_count, (
        f"constructed pool length {len(pool)} != limit_up_count {limit_up_count}"
    )
    assert boards_ge2_count == lianban_count, (
        f"boards>=2 rows {boards_ge2_count} != lianban_count {lianban_count}"
    )

    return pool


def _snapshot_from_fixture_case(case: dict) -> dict:
    """从 fixture case 构造模块输入 snapshot。"""
    pool = _build_pool_from_fixture(case)
    return {
        "trade_date": case["trade_date"],
        "session": case["session"],
        "is_final": case["is_final"],
        "source_ids": case["source_ids"],
        "fetched_at": case["fetched_at"],
        "snapshot_at": case["snapshot_at"],
        "limit_up_pool": pool,
        "data_health": case["data_health"],
    }


# ---------------------------------------------------------------------------
# 1. 基本合同
# ---------------------------------------------------------------------------


class TestBasicContract:
    def test_schema_version_exact(self):
        assert SCHEMA_VERSION == "short-term-limit-up-ladder-v0.1"

    def test_envelope_fields_exact(self):
        result = compute_limit_up_ladder(_base_snapshot())
        assert set(result.keys()) == _ENVELOPE_FIELDS

    def test_metrics_fields_exact(self):
        result = compute_limit_up_ladder(_base_snapshot())
        assert set(result["metrics"].keys()) == _METRIC_FIELDS

    def test_data_health_fields_exact(self):
        result = compute_limit_up_ladder(_base_snapshot())
        assert set(result["data_health"].keys()) == _DATA_HEALTH_FIELDS

    def test_status_only_three_states(self):
        for snap in (_base_snapshot(), None, {}, [], "garbage"):
            result = compute_limit_up_ladder(snap)
            assert result["status"] in {"normal", "partial", "unavailable"}

    def test_json_serializable_no_nan_infinity(self):
        for snap in (_base_snapshot(), {}, None):
            result = compute_limit_up_ladder(snap)
            text = json.dumps(result, allow_nan=False)
            assert "NaN" not in text
            assert "Infinity" not in text

    def test_fixed_limitations(self):
        result = compute_limit_up_ladder(_base_snapshot())
        assert result["limitations"] == [
            "single-source (eastmoney push2ex), not cross-validated",
            "licensing_status: unclear",
            "consecutive limit-up day semantics not independently verified",
        ]

    def test_normal_reason_codes_empty(self):
        result = compute_limit_up_ladder(_base_snapshot())
        assert result["status"] == "normal"
        assert result["reason_codes"] == []
        assert result["warnings"] == []


# ---------------------------------------------------------------------------
# 2. Fixture 三场景
# ---------------------------------------------------------------------------


class TestFixtureScenarios:
    def test_fixture_headers(self, fixture_doc):
        assert fixture_doc["schema_version"] == "bk11-short-term-facts-fixture.v0.1"
        assert fixture_doc["fixture_kind"] == "synthetic-normalized"

    def test_normal_case(self, fixture_cases):
        case = fixture_cases["normal"]
        snap = _snapshot_from_fixture_case(case)
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "normal"
        activity = case["limit_activity"]
        metrics = result["metrics"]
        assert metrics["max_boards"] == activity["max_boards"]
        assert metrics["lianban_count"] == activity["lianban_count"]
        expected_ladder = [
            {"boards": e["boards"], "count": e["count"]} for e in activity["ladder"]
        ]
        assert metrics["ladder"] == expected_ladder

    def test_partial_case(self, fixture_cases):
        case = fixture_cases["partial"]
        snap = _snapshot_from_fixture_case(case)
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "partial"
        assert "SOURCE_PARTIAL" in result["reason_codes"]
        assert "PARTIAL_COVERAGE" in result["reason_codes"]
        activity = case["limit_activity"]
        metrics = result["metrics"]
        assert metrics["max_boards"] == activity["max_boards"]
        assert metrics["lianban_count"] == activity["lianban_count"]
        expected_ladder = [
            {"boards": e["boards"], "count": e["count"]} for e in activity["ladder"]
        ]
        assert metrics["ladder"] == expected_ladder

    def test_unavailable_case(self, fixture_cases):
        case = fixture_cases["unavailable"]
        # unavailable case 的 limit_activity 为 null，不构造 pool
        snap = {
            "trade_date": case["trade_date"],
            "session": case["session"],
            "is_final": case["is_final"],
            "source_ids": case["source_ids"],
            "fetched_at": case["fetched_at"],
            "snapshot_at": case["snapshot_at"],
            "limit_up_pool": [],
            "data_health": case["data_health"],
        }
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "unavailable"
        assert all(v is None for v in result["metrics"].values())
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]

    def test_fixture_plus_field_ignored(self, fixture_cases):
        """fixture 的 plus 字段不得出现在输出中。"""
        case = fixture_cases["normal"]
        snap = _snapshot_from_fixture_case(case)
        result = compute_limit_up_ladder(snap)
        blob = json.dumps(result, ensure_ascii=False)
        assert '"plus"' not in blob
        assert "plus" not in blob


# ---------------------------------------------------------------------------
# 3. 纯计算
# ---------------------------------------------------------------------------


class TestPureComputation:
    def test_input_not_mutated(self):
        snap = _base_snapshot()
        before = copy.deepcopy(snap)
        compute_limit_up_ladder(snap)
        assert snap == before

    def test_deterministic_repeat_calls(self):
        snap = _base_snapshot()
        first = compute_limit_up_ladder(snap)
        second = compute_limit_up_ladder(snap)
        assert json.dumps(first, sort_keys=True) == json.dumps(
            second, sort_keys=True
        )

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

        def _boom(*args, **kwargs):
            raise AssertionError("module must not read current time")

        monkeypatch.setattr(_time, "time", _boom)
        monkeypatch.setattr(stul, "datetime", _NoNowDatetime)
        result = compute_limit_up_ladder(_base_snapshot())
        assert result["status"] == "normal"

    def test_no_environment_access(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise AssertionError("module must not read environment variables")

        monkeypatch.setattr(os, "environ", {})
        monkeypatch.setattr(os, "getenv", _boom)
        result = compute_limit_up_ladder(_base_snapshot())
        assert result["status"] == "normal"

    def test_no_file_writes(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise AssertionError("module must not write files")

        monkeypatch.setattr(io, "open", _boom)
        result = compute_limit_up_ladder(_base_snapshot())
        assert result["status"] == "normal"

    def test_no_network(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise AssertionError("module must not access network")

        monkeypatch.setattr(socket, "socket", _boom)
        result = compute_limit_up_ladder(_base_snapshot())
        assert result["status"] == "normal"

    def test_module_import_boundary(self):
        source_path = os.path.abspath(stul.__file__)
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
            "random",
        ):
            assert forbidden not in source


# ---------------------------------------------------------------------------
# 4. 数值和池边界
# ---------------------------------------------------------------------------


class TestPoolBoundaries:
    def test_single_first_board(self):
        snap = _base_snapshot()
        snap["limit_up_pool"] = [
            {"stock_code": "000001", "consecutive_limit_up_days": 1}
        ]
        snap["data_health"]["row_count"] = 1
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "normal"
        assert result["metrics"]["max_boards"] == 1
        assert result["metrics"]["lianban_count"] == 0
        assert result["metrics"]["ladder"] == []

    def test_all_first_boards(self):
        snap = _base_snapshot()
        snap["limit_up_pool"] = [
            {"stock_code": "000001", "consecutive_limit_up_days": 1},
            {"stock_code": "000002", "consecutive_limit_up_days": 1},
        ]
        snap["data_health"]["row_count"] = 2
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "normal"
        assert result["metrics"]["max_boards"] == 1
        assert result["metrics"]["lianban_count"] == 0
        assert result["metrics"]["ladder"] == []

    def test_mixed_boards(self):
        snap = _base_snapshot()
        snap["limit_up_pool"] = [
            {"stock_code": "000001", "consecutive_limit_up_days": 1},
            {"stock_code": "000002", "consecutive_limit_up_days": 2},
            {"stock_code": "000003", "consecutive_limit_up_days": 2},
            {"stock_code": "000004", "consecutive_limit_up_days": 3},
            {"stock_code": "000005", "consecutive_limit_up_days": 5},
        ]
        snap["data_health"]["row_count"] = 5
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "normal"
        assert result["metrics"]["max_boards"] == 5
        assert result["metrics"]["lianban_count"] == 4
        assert result["metrics"]["ladder"] == [
            {"boards": 2, "count": 2},
            {"boards": 3, "count": 1},
            {"boards": 5, "count": 1},
        ]

    def test_non_contiguous_boards(self):
        """非连续板数档位：跳过 3，只有 2 和 4。"""
        snap = _base_snapshot()
        snap["limit_up_pool"] = [
            {"stock_code": "000001", "consecutive_limit_up_days": 2},
            {"stock_code": "000002", "consecutive_limit_up_days": 4},
        ]
        snap["data_health"]["row_count"] = 2
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "normal"
        assert result["metrics"]["max_boards"] == 4
        assert result["metrics"]["lianban_count"] == 2
        assert result["metrics"]["ladder"] == [
            {"boards": 2, "count": 1},
            {"boards": 4, "count": 1},
        ]

    def test_legal_zero_pool(self):
        snap = _base_snapshot()
        snap["limit_up_pool"] = []
        snap["data_health"]["row_count"] = 0
        snap["data_health"]["legal_zero"] = True
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "normal"
        assert result["metrics"]["max_boards"] == 0
        assert result["metrics"]["lianban_count"] == 0
        assert result["metrics"]["ladder"] == []

    def test_unexplained_empty_pool(self):
        snap = _base_snapshot()
        snap["limit_up_pool"] = []
        snap["data_health"]["row_count"] = 0
        snap["data_health"]["legal_zero"] = False
        snap["data_health"]["unexplained_empty"] = True
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "partial"
        assert all(v is None for v in result["metrics"].values())
        assert "UNEXPLAINED_EMPTY" in result["reason_codes"]
        assert "SOURCE_PARTIAL" in result["reason_codes"]

    def test_ordinary_empty_pool(self):
        snap = _base_snapshot()
        snap["limit_up_pool"] = []
        snap["data_health"]["row_count"] = 0
        snap["data_health"]["legal_zero"] = False
        snap["data_health"]["unexplained_empty"] = False
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "unavailable"
        assert all(v is None for v in result["metrics"].values())
        assert "LIMIT_UP_POOL_UNAVAILABLE" in result["reason_codes"]
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]

    def test_huge_boards_safe(self):
        snap = _base_snapshot()
        huge = 10**18
        snap["limit_up_pool"] = [
            {"stock_code": "000001", "consecutive_limit_up_days": huge},
        ]
        snap["data_health"]["row_count"] = 1
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "normal"
        assert result["metrics"]["max_boards"] == huge
        assert result["metrics"]["lianban_count"] == 1
        text = json.dumps(result, allow_nan=False)
        assert str(huge) in text


# ---------------------------------------------------------------------------
# 5. 非法值
# ---------------------------------------------------------------------------


class TestInvalidValues:
    @pytest.mark.parametrize(
        "bad_days",
        [True, False, 0, -1, 2.5, "2", None],
    )
    def test_invalid_consecutive_days(self, bad_days):
        snap = _base_snapshot()
        snap["limit_up_pool"] = [
            {"stock_code": "000001", "consecutive_limit_up_days": bad_days},
        ]
        snap["data_health"]["row_count"] = 1
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "unavailable"
        assert all(v is None for v in result["metrics"].values())
        assert "INVALID_POOL_ROW" in result["reason_codes"]
        assert "LIMIT_UP_POOL_UNAVAILABLE" in result["reason_codes"]

    def test_empty_stock_code(self):
        snap = _base_snapshot()
        snap["limit_up_pool"] = [
            {"stock_code": "", "consecutive_limit_up_days": 1},
        ]
        snap["data_health"]["row_count"] = 1
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "unavailable"
        assert "INVALID_POOL_ROW" in result["reason_codes"]

    def test_whitespace_only_stock_code(self):
        snap = _base_snapshot()
        snap["limit_up_pool"] = [
            {"stock_code": "   ", "consecutive_limit_up_days": 1},
        ]
        snap["data_health"]["row_count"] = 1
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "unavailable"
        assert "INVALID_POOL_ROW" in result["reason_codes"]

    def test_non_dict_row(self):
        snap = _base_snapshot()
        snap["limit_up_pool"] = [
            "not-a-dict",
            42,
            None,
        ]
        snap["data_health"]["row_count"] = 3
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "unavailable"
        assert "INVALID_POOL_ROW" in result["reason_codes"]

    def test_pool_not_list(self):
        snap = _base_snapshot()
        snap["limit_up_pool"] = "not-a-list"
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "unavailable"
        assert "LIMIT_UP_POOL_UNAVAILABLE" in result["reason_codes"]
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]

    def test_stock_code_stripped(self):
        snap = _base_snapshot()
        snap["limit_up_pool"] = [
            {"stock_code": "  000001  ", "consecutive_limit_up_days": 1},
        ]
        snap["data_health"]["row_count"] = 1
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "normal"


# ---------------------------------------------------------------------------
# 6. 重复记录
# ---------------------------------------------------------------------------


class TestDuplicateHandling:
    def test_same_code_same_boards(self):
        snap = _base_snapshot()
        snap["limit_up_pool"] = [
            {"stock_code": "000001", "consecutive_limit_up_days": 2},
            {"stock_code": "000001", "consecutive_limit_up_days": 2},
        ]
        snap["data_health"]["row_count"] = 2
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "partial"
        assert "DUPLICATE_STOCK_CODE" in result["reason_codes"]
        assert "SOURCE_PARTIAL" in result["reason_codes"]
        # 只计算首次合法记录
        assert result["metrics"]["max_boards"] == 2
        assert result["metrics"]["lianban_count"] == 1
        assert result["metrics"]["ladder"] == [{"boards": 2, "count": 1}]

    def test_same_code_different_boards(self):
        snap = _base_snapshot()
        snap["limit_up_pool"] = [
            {"stock_code": "000001", "consecutive_limit_up_days": 2},
            {"stock_code": "000001", "consecutive_limit_up_days": 3},
        ]
        snap["data_health"]["row_count"] = 2
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "partial"
        assert "DUPLICATE_STOCK_CODE" in result["reason_codes"]
        # 保留首次合法记录（boards=2）
        assert result["metrics"]["max_boards"] == 2
        assert result["metrics"]["lianban_count"] == 1
        assert result["metrics"]["ladder"] == [{"boards": 2, "count": 1}]

    def test_duplicate_with_valid_rows(self):
        snap = _base_snapshot()
        snap["limit_up_pool"] = [
            {"stock_code": "000001", "consecutive_limit_up_days": 1},
            {"stock_code": "000002", "consecutive_limit_up_days": 2},
            {"stock_code": "000002", "consecutive_limit_up_days": 2},
            {"stock_code": "000003", "consecutive_limit_up_days": 3},
        ]
        snap["data_health"]["row_count"] = 4
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "partial"
        assert "DUPLICATE_STOCK_CODE" in result["reason_codes"]
        assert result["metrics"]["max_boards"] == 3
        assert result["metrics"]["lianban_count"] == 2
        assert result["metrics"]["ladder"] == [
            {"boards": 2, "count": 1},
            {"boards": 3, "count": 1},
        ]


# ---------------------------------------------------------------------------
# 7. Data Health
# ---------------------------------------------------------------------------


class TestDataHealth:
    def _health_snap(self, **overrides) -> dict:
        snap = _base_snapshot()
        for k, v in overrides.items():
            snap["data_health"][k] = v
        return snap

    def test_transport_failure(self):
        snap = self._health_snap(transport_success=False)
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "unavailable"
        assert all(v is None for v in result["metrics"].values())
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]

    def test_parse_failure(self):
        snap = self._health_snap(parse_success=False)
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "unavailable"
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]

    def test_required_field_failure(self):
        snap = self._health_snap(required_field_present=False)
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "unavailable"
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]

    def test_data_array_failure(self):
        snap = self._health_snap(data_array_present=False)
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "unavailable"
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]

    def test_upstream_null(self):
        snap = self._health_snap(upstream_null=True)
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "unavailable"
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]

    def test_trade_date_mismatch(self):
        snap = self._health_snap(trade_date_match=False)
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "partial"
        assert all(v is None for v in result["metrics"].values())
        assert "TRADE_DATE_MISMATCH" in result["reason_codes"]
        assert "SOURCE_PARTIAL" in result["reason_codes"]

    def test_coverage_warning(self):
        snap = self._health_snap(coverage_warning=True)
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "partial"
        assert "PARTIAL_COVERAGE" in result["reason_codes"]
        assert "SOURCE_PARTIAL" in result["reason_codes"]
        # metrics 仍由合法池计算
        assert result["metrics"]["max_boards"] == 3

    def test_row_count_mismatch(self):
        snap = _base_snapshot()
        snap["data_health"]["row_count"] = 99
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "partial"
        assert "PARTIAL_COVERAGE" in result["reason_codes"]
        assert "SOURCE_PARTIAL" in result["reason_codes"]

    def test_invalid_data_health_type(self):
        snap = _base_snapshot()
        snap["data_health"] = "not-a-dict"
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "unavailable"
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]

    def test_missing_data_health(self):
        snap = _base_snapshot()
        del snap["data_health"]
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "unavailable"
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]

    def test_non_bool_health_field(self):
        snap = _base_snapshot()
        snap["data_health"]["transport_success"] = "yes"
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "unavailable"
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]


# ---------------------------------------------------------------------------
# 8. 元数据
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_invalid_session(self):
        snap = _base_snapshot()
        snap["session"] = "unknown"
        result = compute_limit_up_ladder(snap)
        assert result["session"] == "unavailable"
        assert result["is_final"] is False
        assert "METADATA_INVALID" in result["reason_codes"]
        assert result["status"] == "partial"

    def test_session_is_final_conflict(self):
        snap = _base_snapshot()
        snap["session"] = "final"
        snap["is_final"] = False
        result = compute_limit_up_ladder(snap)
        assert result["session"] == "final"
        assert result["is_final"] is True
        assert "METADATA_INVALID" in result["reason_codes"]
        assert result["status"] == "partial"

    def test_invalid_timestamp(self):
        snap = _base_snapshot()
        snap["fetched_at"] = "not-a-timestamp"
        result = compute_limit_up_ladder(snap)
        assert "METADATA_INVALID" in result["reason_codes"]
        assert result["status"] == "partial"

    def test_time_reverse(self):
        snap = _base_snapshot()
        snap["fetched_at"] = "2026-07-30T08:00:00.000000Z"
        snap["snapshot_at"] = "2026-07-30T07:00:00.000000Z"
        result = compute_limit_up_ladder(snap)
        assert "METADATA_INVALID" in result["reason_codes"]
        assert result["status"] == "partial"

    def test_source_ids_dedup(self):
        snap = _base_snapshot()
        snap["source_ids"] = ["a", "b", "a", "c", "b"]
        result = compute_limit_up_ladder(snap)
        assert result["source_ids"] == ["a", "b", "c"]

    def test_invalid_source_ids(self):
        snap = _base_snapshot()
        snap["source_ids"] = ["a", "", None, 42, "b"]
        result = compute_limit_up_ladder(snap)
        assert result["source_ids"] == ["a", "b"]
        assert "METADATA_INVALID" in result["reason_codes"]

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
    def test_allowed_sessions_legal_is_final(self, session, exp_is_final):
        snap = _base_snapshot()
        snap["session"] = session
        snap["is_final"] = exp_is_final
        result = compute_limit_up_ladder(snap)
        assert result["session"] == session
        assert result["is_final"] is exp_is_final
        assert "METADATA_INVALID" not in result["reason_codes"]


# ---------------------------------------------------------------------------
# 9. 范围阻断
# ---------------------------------------------------------------------------


class TestBlockedScope:
    def test_no_blocked_fields_in_output(self):
        snap = _base_snapshot()
        result = compute_limit_up_ladder(snap)
        blob = json.dumps(result, ensure_ascii=False)
        for name in _BLOCKED_METRIC_NAMES:
            assert name not in blob, f"blocked field '{name}' found in output"

    def test_caller_provided_max_boards_ignored(self):
        snap = _base_snapshot()
        snap["max_boards"] = 99
        result = compute_limit_up_ladder(snap)
        assert result["metrics"]["max_boards"] == 3

    def test_caller_provided_lianban_count_ignored(self):
        snap = _base_snapshot()
        snap["lianban_count"] = 99
        result = compute_limit_up_ladder(snap)
        assert result["metrics"]["lianban_count"] == 3

    def test_caller_provided_ladder_ignored(self):
        snap = _base_snapshot()
        snap["ladder"] = [{"boards": 99, "count": 99}]
        result = compute_limit_up_ladder(snap)
        assert result["metrics"]["ladder"] == [
            {"boards": 2, "count": 2},
            {"boards": 3, "count": 1},
        ]

    def test_caller_provided_reason_codes_ignored(self):
        snap = _base_snapshot()
        snap["reason_codes"] = ["SOURCE_UNAVAILABLE", "ARBITRARY_CODE"]
        result = compute_limit_up_ladder(snap)
        assert result["status"] == "normal"
        assert result["reason_codes"] == []

    def test_caller_provided_warnings_ignored(self):
        snap = _base_snapshot()
        snap["warnings"] = ["custom warning"]
        result = compute_limit_up_ladder(snap)
        assert result["warnings"] == []

    def test_caller_provided_limitations_ignored(self):
        snap = _base_snapshot()
        snap["limitations"] = ["custom limitation"]
        result = compute_limit_up_ladder(snap)
        assert result["limitations"] == [
            "single-source (eastmoney push2ex), not cross-validated",
            "licensing_status: unclear",
            "consecutive limit-up day semantics not independently verified",
        ]


# ---------------------------------------------------------------------------
# 10. Fallback 与异常边界
# ---------------------------------------------------------------------------


class TestFallback:
    @pytest.mark.parametrize(
        "bad_input", [None, [], [1, 2, 3], "snapshot", 42, 3.14, object()]
    )
    def test_fallback_returns_unavailable(self, bad_input):
        result = compute_limit_up_ladder(bad_input)
        assert result["schema_version"] == SCHEMA_VERSION
        assert result["session"] == "unavailable"
        assert result["is_final"] is False
        assert result["status"] == "unavailable"
        assert all(v is None for v in result["metrics"].values())
        assert "SOURCE_UNAVAILABLE" in result["reason_codes"]
        assert result["warnings"] == [
            "snapshot unavailable; no ladder metrics emitted"
        ]

    def test_fallback_malicious_dict_subclass(self):
        class Exploding(dict):
            def get(self, *args, **kwargs):
                raise RuntimeError("secret-internal-detail")

        result = compute_limit_up_ladder(Exploding())
        assert result["status"] == "unavailable"
        blob = json.dumps(result, ensure_ascii=False)
        assert "RuntimeError" not in blob
        assert "secret-internal-detail" not in blob
        assert "Traceback" not in blob

    def test_unavailable_metrics_keys_preserved(self):
        snap = _base_snapshot()
        snap["data_health"]["transport_success"] = False
        result = compute_limit_up_ladder(snap)
        assert set(result["metrics"].keys()) == _METRIC_FIELDS
        assert all(v is None for v in result["metrics"].values())
