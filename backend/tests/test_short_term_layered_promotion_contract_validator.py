"""BK-11 layered-promotion 合同机械验证器 v0.1 · 全路径测试。

不发起任何 live 网络请求。真实 fixture 从仓库 JSON 读取；变异测试对
深拷贝后的 fixture 做最小修改并断言对应固定 issue code。
"""
from __future__ import annotations

import copy
import inspect
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "backend")

import short_term_layered_promotion_contract_validator as validator  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = (
    REPO_ROOT / "docs" / "research" / "BK11_LAYERED_PROMOTION_FIXTURE_V01.json"
)
VALIDATOR_DOC_PATH = (
    REPO_ROOT / "docs" / "research" / "BK11_LAYERED_PROMOTION_CONTRACT_VALIDATOR_V01.md"
)
FEASIBILITY_DOC_PATH = (
    REPO_ROOT / "docs" / "research" / "BK11_LAYERED_PROMOTION_FEASIBILITY_V01.md"
)


def _load_fixture() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _mutate(mutator) -> dict:
    fixture = _load_fixture()
    mutator(fixture)
    return fixture


def _assert_invalid_with(r, code):
    assert r["status"] == "invalid"
    assert code in r["issue_codes"], f"{code} not in {r['issue_codes']}"


def _normal_case(fixture):
    return next(c for c in fixture["cases"] if c["case_id"] == "normal")


def _partial_case(fixture):
    return next(c for c in fixture["cases"] if c["case_id"] == "partial")


def _unavailable_case(fixture):
    return next(c for c in fixture["cases"] if c["case_id"] == "unavailable")


def _identity_case(fixture):
    return next(c for c in fixture["cases"] if c["case_id"] == "identity_edge")


# ---------------------------------------------------------------------------
# 1. 公开合同
# ---------------------------------------------------------------------------

class TestPublicContract:
    def test_constants(self):
        assert validator.SCHEMA_VERSION == (
            "short-term-layered-promotion-contract-validator-v0.1")
        assert validator.FIXTURE_SCHEMA_VERSION == (
            "bk11-layered-promotion-fixture.v0.1")

    def test_all(self):
        assert validator.__all__ == [
            "SCHEMA_VERSION",
            "FIXTURE_SCHEMA_VERSION",
            "validate_layered_promotion_fixture",
        ]

    def test_signature(self):
        sig = inspect.signature(validator.validate_layered_promotion_fixture)
        assert list(sig.parameters) == ["fixture"]
        assert sig.parameters["fixture"].default is inspect.Parameter.empty

    def test_output_shape_valid(self):
        r = validator.validate_layered_promotion_fixture(_load_fixture())
        assert r["schema_version"] == validator.SCHEMA_VERSION
        assert r["fixture_schema_version"] == validator.FIXTURE_SCHEMA_VERSION
        assert r["status"] == "valid"
        assert r["issue_codes"] == []
        assert r["issue_count"] == 0
        assert r["case_count"] == 7
        assert r["validated_case_ids"] == [
            "normal", "zero_denominator", "previous_legal_zero",
            "current_legal_zero", "partial", "unavailable", "identity_edge",
        ]
        assert r["warnings"] == []
        assert len(r["case_results"]) == 7
        for cr in r["case_results"]:
            assert set(cr.keys()) == {
                "case_id", "status", "issue_codes",
                "derived_status", "derived_reason_codes",
                "derived_layered_promotion_rates",
            }
            assert cr["status"] == "valid"
            assert cr["issue_codes"] == []

    def test_output_shape_invalid(self):
        r = validator.validate_layered_promotion_fixture({"bad": True})
        assert r["status"] == "invalid"
        assert r["issue_count"] >= 1
        assert isinstance(r["issue_codes"], list)
        for code in r["issue_codes"]:
            assert code in validator._ISSUE_CODE_SET
        assert r["schema_version"] == validator.SCHEMA_VERSION
        assert isinstance(r["case_results"], list)
        assert isinstance(r["validated_case_ids"], list)


# ---------------------------------------------------------------------------
# 2. 真实 fixture
# ---------------------------------------------------------------------------

class TestRealFixture:
    def test_fixture_file_exists(self):
        assert FIXTURE_PATH.is_file()

    def test_real_fixture_valid(self):
        r = validator.validate_layered_promotion_fixture(_load_fixture())
        assert r["status"] == "valid"
        assert r["issue_codes"] == []
        assert r["issue_count"] == 0
        assert r["case_count"] == 7
        assert len(r["validated_case_ids"]) == 7
        assert all(cr["status"] == "valid" for cr in r["case_results"])

    def test_normal_three_levels(self):
        r = validator.validate_layered_promotion_fixture(_load_fixture())
        cr = next(c for c in r["case_results"] if c["case_id"] == "normal")
        assert cr["derived_status"] == "normal"
        assert cr["derived_reason_codes"] == []
        assert cr["derived_layered_promotion_rates"] == [
            {"from_level": 1, "to_level": 2, "numerator": 2,
             "denominator": 4, "sample_count": 4, "rate": 0.5},
            {"from_level": 2, "to_level": 3, "numerator": 1,
             "denominator": 2, "sample_count": 2, "rate": 0.5},
            {"from_level": 3, "to_level": 4, "numerator": 0,
             "denominator": 1, "sample_count": 1, "rate": 0.0},
        ]


# ---------------------------------------------------------------------------
# 3. 顶层变异
# ---------------------------------------------------------------------------

class TestTopLevelMutations:
    def test_bad_schema_version(self):
        r = validator.validate_layered_promotion_fixture(
            _mutate(lambda f: f.update(schema_version="wrong")))
        _assert_invalid_with(r, "FIXTURE_SCHEMA_INVALID")

    def test_bad_fixture_kind(self):
        r = validator.validate_layered_promotion_fixture(
            _mutate(lambda f: f.update(fixture_kind="real-market")))
        _assert_invalid_with(r, "TOP_LEVEL_FIELD_INVALID")

    def test_missing_top_level_field(self):
        r = validator.validate_layered_promotion_fixture(
            _mutate(lambda f: f.pop("description")))
        _assert_invalid_with(r, "TOP_LEVEL_FIELD_INVALID")

    def test_extra_top_level_field(self):
        r = validator.validate_layered_promotion_fixture(
            _mutate(lambda f: f.update(extra_field=1)))
        _assert_invalid_with(r, "TOP_LEVEL_FIELD_INVALID")

    def test_trade_dates_bad_relation(self):
        def mut(f):
            f["trade_dates"] = ["2026-07-30", "2026-07-30"]
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "TOP_LEVEL_FIELD_INVALID")

    def test_trade_dates_invalid_format(self):
        def mut(f):
            f["trade_dates"] = ["2026-7-29", "2026-07-30"]
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "TOP_LEVEL_FIELD_INVALID")

    def test_generated_at_unparseable(self):
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(
                _mutate(lambda f: f.update(generated_at="not-a-time"))),
            "TOP_LEVEL_FIELD_INVALID")

    def test_description_missing_synthetic_marker(self):
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(
                _mutate(lambda f: f.update(description="真实行情数据"))),
            "TOP_LEVEL_FIELD_INVALID")


# ---------------------------------------------------------------------------
# 4. market scope 变异
# ---------------------------------------------------------------------------

class TestMarketScopeMutations:
    def test_st_removed(self):
        def mut(f):
            f["market_scope"]["included"].remove("ST")
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "MARKET_SCOPE_INVALID")

    def test_star_st_removed(self):
        def mut(f):
            f["market_scope"]["included"].remove("*ST")
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "MARKET_SCOPE_INVALID")

    def test_bse_removed(self):
        def mut(f):
            f["market_scope"]["excluded"].remove("BSE")
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "MARKET_SCOPE_INVALID")

    def test_included_duplicate(self):
        def mut(f):
            f["market_scope"]["included"].append("ST")
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "MARKET_SCOPE_INVALID")

    def test_included_not_list(self):
        def mut(f):
            f["market_scope"]["included"] = "SH main"
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "MARKET_SCOPE_INVALID")

    def test_empty_string_member(self):
        def mut(f):
            f["market_scope"]["excluded"].append("")
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "MARKET_SCOPE_INVALID")


# ---------------------------------------------------------------------------
# 5. case 集合变异
# ---------------------------------------------------------------------------

class TestCaseSetMutations:
    def test_duplicate_case_id(self):
        def mut(f):
            f["cases"][1]["case_id"] = "normal"
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "DUPLICATE_CASE_ID")

    def test_missing_case(self):
        def mut(f):
            f["cases"].pop(2)
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "CASE_SET_INVALID")

    def test_unknown_case(self):
        def mut(f):
            f["cases"][0]["case_id"] = "extra_case"
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "CASE_SET_INVALID")

    def test_case_order_wrong(self):
        def mut(f):
            f["cases"][0], f["cases"][1] = f["cases"][1], f["cases"][0]
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "CASE_SET_INVALID")

    def test_case_date_relation(self):
        def mut(f):
            f["cases"][0]["previous_trade_date"] = "2026-07-30"
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "CASE_SCHEMA_INVALID")

    def test_case_date_mismatch_top_level(self):
        def mut(f):
            f["cases"][0]["previous_trade_date"] = "2026-07-28"
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "CASE_SCHEMA_INVALID")


# ---------------------------------------------------------------------------
# 6. snapshot 变异
# ---------------------------------------------------------------------------

class TestSnapshotMutations:
    def test_missing_snapshot_field(self):
        def mut(f):
            del _normal_case(f)["previous_snapshot"]["limit_up_pool"]
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "SNAPSHOT_SCHEMA_INVALID")

    def test_wrong_trade_date(self):
        def mut(f):
            _normal_case(f)["previous_snapshot"]["trade_date"] = "2026-07-28"
        r = validator.validate_layered_promotion_fixture(_mutate(mut))
        # 结构合法：日期不匹配属业务状态 TRADE_DATE_MISMATCH，不是 schema 无效
        cr = next(c for c in r["case_results"] if c["case_id"] == "normal")
        assert "SNAPSHOT_SCHEMA_INVALID" not in cr["issue_codes"]
        assert cr["derived_status"] == "unavailable"
        assert cr["derived_reason_codes"] == [
            "SOURCE_UNAVAILABLE", "PREVIOUS_SNAPSHOT_UNAVAILABLE",
            "TRADE_DATE_MISMATCH",
        ]
        assert cr["derived_layered_promotion_rates"] is None

    def test_session_not_final(self):
        def mut(f):
            _normal_case(f)["current_snapshot"]["session"] = "draft"
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "SNAPSHOT_SCHEMA_INVALID")

    def test_is_final_false(self):
        def mut(f):
            _normal_case(f)["current_snapshot"]["is_final"] = False
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "SNAPSHOT_SCHEMA_INVALID")

    def test_empty_source_ids(self):
        def mut(f):
            _normal_case(f)["previous_snapshot"]["source_ids"] = []
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "SNAPSHOT_SCHEMA_INVALID")

    def test_fetched_after_snapshot(self):
        def mut(f):
            snap = _normal_case(f)["previous_snapshot"]
            snap["fetched_at"] = "2026-07-29T07:40:00.000000Z"
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "SNAPSHOT_SCHEMA_INVALID")

    def test_timestamp_no_tz(self):
        def mut(f):
            _normal_case(f)["previous_snapshot"]["fetched_at"] = "2026-07-29T07:30:00"
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "SNAPSHOT_SCHEMA_INVALID")


# ---------------------------------------------------------------------------
# 7. data_health 变异
# ---------------------------------------------------------------------------

class TestDataHealthMutations:
    def test_missing_field(self):
        def mut(f):
            del _normal_case(f)["previous_snapshot"]["data_health"]["coverage_warning"]
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "DATA_HEALTH_INVALID")

    def test_row_count_mismatch(self):
        def mut(f):
            _normal_case(f)["previous_snapshot"]["data_health"]["row_count"] = 8
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "DATA_HEALTH_INVALID")

    def test_legal_zero_and_unexplained(self):
        def mut(f):
            _normal_case(f)["current_snapshot"]["data_health"]["legal_zero"] = True
            _normal_case(f)["current_snapshot"]["data_health"]["unexplained_empty"] = True
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "DATA_HEALTH_INVALID")

    def test_trade_date_match_int(self):
        def mut(f):
            _normal_case(f)["previous_snapshot"]["data_health"]["trade_date_match"] = 1
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "DATA_HEALTH_INVALID")

    def test_row_count_bool(self):
        def mut(f):
            _normal_case(f)["previous_snapshot"]["data_health"]["row_count"] = True
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "DATA_HEALTH_INVALID")


# ---------------------------------------------------------------------------
# 8. pool row 变异
# ---------------------------------------------------------------------------

class TestPoolRowMutations:
    def test_bad_prefix(self):
        def mut(f):
            _normal_case(f)["previous_snapshot"]["limit_up_pool"][0]["stock_code"] = "400001"
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "POOL_ROW_INVALID")

    def test_duplicate_code(self):
        def mut(f):
            pool = _normal_case(f)["previous_snapshot"]["limit_up_pool"]
            pool[0]["stock_code"] = pool[1]["stock_code"]
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "POOL_ROW_INVALID")

    def test_unsorted(self):
        def mut(f):
            pool = _normal_case(f)["previous_snapshot"]["limit_up_pool"]
            pool[0], pool[1] = pool[1], pool[0]
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "POOL_ROW_INVALID")

    def test_days_bool(self):
        def mut(f):
            _normal_case(f)["previous_snapshot"]["limit_up_pool"][0]["consecutive_limit_up_days"] = True
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "POOL_ROW_INVALID")

    def test_days_zero(self):
        def mut(f):
            _normal_case(f)["previous_snapshot"]["limit_up_pool"][0]["consecutive_limit_up_days"] = 0
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "POOL_ROW_INVALID")

    def test_extra_row_field(self):
        def mut(f):
            _normal_case(f)["previous_snapshot"]["limit_up_pool"][0]["name"] = "x"
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "POOL_ROW_INVALID")


# ---------------------------------------------------------------------------
# 9. expected / reason-code / status 变异
# ---------------------------------------------------------------------------

class TestStatusMapping:
    def test_partial_with_concrete_rates(self):
        def mut(f):
            _partial_case(f)["expected"]["layered_promotion_rates"] = [
                {"from_level": 1, "to_level": 2, "numerator": 1,
                 "denominator": 1, "sample_count": 1, "rate": 1.0}]
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "EXPECTED_SCHEMA_INVALID")

    def test_unavailable_with_concrete_rates(self):
        def mut(f):
            _unavailable_case(f)["expected"]["layered_promotion_rates"] = [
                {"from_level": 1, "to_level": 2, "numerator": 1,
                 "denominator": 1, "sample_count": 1, "rate": 1.0}]
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "EXPECTED_SCHEMA_INVALID")

    def test_normal_with_null_rates(self):
        def mut(f):
            _normal_case(f)["expected"]["layered_promotion_rates"] = None
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "EXPECTED_SCHEMA_INVALID")

    def test_unknown_status(self):
        def mut(f):
            _normal_case(f)["expected"]["status"] = "weird"
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "EXPECTED_STATUS_INVALID")

    def test_status_mapping_mismatch(self):
        def mut(f):
            exp = _normal_case(f)["expected"]
            exp["status"] = "partial"
            exp["reason_codes"] = ["SOURCE_PARTIAL", "PARTIAL_COVERAGE"]
            exp["layered_promotion_rates"] = None
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "STATUS_MAPPING_MISMATCH")


class TestReasonCodeMutations:
    def test_unknown_reason_code(self):
        def mut(f):
            _partial_case(f)["expected"]["reason_codes"].append("UNKNOWN_CODE")
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "REASON_CODE_INVALID")

    def test_duplicate_reason_code(self):
        def mut(f):
            _partial_case(f)["expected"]["reason_codes"].append("SOURCE_PARTIAL")
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "REASON_CODE_INVALID")

    def test_reason_code_order_wrong(self):
        def mut(f):
            _partial_case(f)["expected"]["reason_codes"] = [
                "PARTIAL_COVERAGE", "SOURCE_PARTIAL"]
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "REASON_CODE_ORDER_INVALID")

    def test_reason_codes_mapping_mismatch(self):
        def mut(f):
            _unavailable_case(f)["expected"]["reason_codes"] = []
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "STATUS_MAPPING_MISMATCH")


# ---------------------------------------------------------------------------
# 10. rate 变异
# ---------------------------------------------------------------------------

class TestRateMutations:
    def _first_rate(self, fixture):
        return _normal_case(fixture)["expected"]["layered_promotion_rates"][0]

    def test_numerator_wrong(self):
        def mut(f):
            item = self._first_rate(f)
            item["numerator"] = 3
            item["rate"] = 0.75
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "RATE_CALCULATION_MISMATCH")

    def test_denominator_wrong(self):
        def mut(f):
            item = self._first_rate(f)
            item["denominator"] = 5
            item["sample_count"] = 5
            item["rate"] = 0.4
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "RATE_CALCULATION_MISMATCH")

    def test_sample_count_wrong(self):
        def mut(f):
            item = self._first_rate(f)
            item["sample_count"] = 3
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "RATE_SCHEMA_INVALID")

    def test_rate_wrong(self):
        def mut(f):
            item = self._first_rate(f)
            item["rate"] = 0.9
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "RATE_SCHEMA_INVALID")

    def test_to_level_wrong(self):
        def mut(f):
            item = self._first_rate(f)
            item["to_level"] = 3
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "RATE_SCHEMA_INVALID")

    def test_zero_denominator_layer(self):
        def mut(f):
            _normal_case(f)["expected"]["layered_promotion_rates"].append(
                {"from_level": 5, "to_level": 6, "numerator": 0,
                 "denominator": 0, "sample_count": 0, "rate": 0.0})
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "RATE_SCHEMA_INVALID")

    def test_rate_nan(self):
        def mut(f):
            item = self._first_rate(f)
            item["rate"] = float("nan")
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "TOP_LEVEL_FIELD_INVALID")


# ---------------------------------------------------------------------------
# 11. identity edge
# ---------------------------------------------------------------------------

class TestIdentityEdge:
    def test_real_identity_edge_valid(self):
        r = validator.validate_layered_promotion_fixture(_load_fixture())
        cr = next(c for c in r["case_results"] if c["case_id"] == "identity_edge")
        assert cr["status"] == "valid"
        assert cr["derived_status"] == "normal"
        assert cr["derived_layered_promotion_rates"] == [
            {"from_level": 1, "to_level": 2, "numerator": 1,
             "denominator": 2, "sample_count": 2, "rate": 0.5},
            {"from_level": 2, "to_level": 3, "numerator": 0,
             "denominator": 2, "sample_count": 2, "rate": 0.0},
            {"from_level": 3, "to_level": 4, "numerator": 0,
             "denominator": 1, "sample_count": 1, "rate": 0.0},
        ]

    def test_skip_counted_as_promotion_rejected(self):
        def mut(f):
            exp = _identity_case(f)["expected"]
            item = exp["layered_promotion_rates"][1]  # 2→3 层
            item["numerator"] = 1
            item["rate"] = 0.5
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "RATE_CALCULATION_MISMATCH")

    def test_duplicate_row_in_identity_invalid(self):
        def mut(f):
            pool = _identity_case(f)["previous_snapshot"]["limit_up_pool"]
            pool[0]["stock_code"] = pool[1]["stock_code"]
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "POOL_ROW_INVALID")


# ---------------------------------------------------------------------------
# 12. 输入不变性
# ---------------------------------------------------------------------------

class TestInputImmutability:
    def test_input_not_modified(self):
        original = _load_fixture()
        snapshot = copy.deepcopy(original)
        validator.validate_layered_promotion_fixture(original)
        assert original == snapshot

    def test_input_not_modified_invalid_path(self):
        original = _load_fixture()
        snapshot = copy.deepcopy(original)
        original["cases"][0]["case_id"] = "normal"
        snapshot["cases"][0]["case_id"] = "normal"
        validator.validate_layered_promotion_fixture(original)
        assert original == snapshot


# ---------------------------------------------------------------------------
# 13. 普通异常边界
# ---------------------------------------------------------------------------

class TestOrdinaryExceptionBoundary:
    @pytest.mark.parametrize("bad", [None, [], "string", 123, object(), set(), b"bytes"])
    def test_non_dict_inputs(self, bad):
        r = validator.validate_layered_promotion_fixture(bad)
        assert r["status"] == "invalid"
        assert "FIXTURE_NOT_DICT" in r["issue_codes"]

    def test_dict_with_object_value(self):
        fixture = _load_fixture()
        fixture["description"] = object()
        r = validator.validate_layered_promotion_fixture(fixture)
        assert r["status"] == "invalid"
        assert "TOP_LEVEL_FIELD_INVALID" in r["issue_codes"]

    def test_dict_with_set_value(self):
        fixture = _load_fixture()
        fixture["cases"] = {"a": 1}
        r = validator.validate_layered_promotion_fixture(fixture)
        assert r["status"] == "invalid"

    def test_nan_and_inf(self):
        for bad in [float("nan"), float("inf"), float("-inf")]:
            fixture = _load_fixture()
            _normal_case(fixture)["expected"]["layered_promotion_rates"][0]["rate"] = bad
            r = validator.validate_layered_promotion_fixture(fixture)
            assert r["status"] == "invalid"
            assert "TOP_LEVEL_FIELD_INVALID" in r["issue_codes"]

    def test_no_exception_text_leak(self):
        fixture = _load_fixture()
        fixture["description"] = object()
        r = validator.validate_layered_promotion_fixture(fixture)
        text = str(r)
        assert "Object of type" not in text
        assert "Traceback" not in text


# ---------------------------------------------------------------------------
# 14. 进程控制异常自然传播
# ---------------------------------------------------------------------------

class TestProcessControl:
    @pytest.mark.parametrize("exc", [
        KeyboardInterrupt(), SystemExit(1), GeneratorExit(),
    ])
    def test_propagates_from_validation_paths(self, monkeypatch, exc):
        """json.dumps / 严格 JSON 递归 / prefix / case 语义 / 推导 / rate 计算
        任一路径抛出进程控制异常均自然传播，不得被结构化。"""
        targets = [
            (validator.json, "dumps"),
            (validator, "_is_strict_json_value"),
            (validator, "_validate_code_prefix_contract"),
            (validator, "_validate_case_semantics"),
            (validator, "_derive"),
            (validator, "_calculate_rates"),
        ]
        for module, name in targets:
            original = getattr(module, name)

            def raiser(*a, **k):
                raise exc

            monkeypatch.setattr(module, name, raiser)
            try:
                with pytest.raises(type(exc)):
                    validator.validate_layered_promotion_fixture(_load_fixture())
            finally:
                monkeypatch.setattr(module, name, original)


# ---------------------------------------------------------------------------
# 15. prefix 合同精确验证
# ---------------------------------------------------------------------------

class TestStrictPrefixContract:
    def _run_prefix_mutation(self, mutator):
        fixture = _load_fixture()
        mutator(fixture)
        r = validator.validate_layered_promotion_fixture(fixture)
        _assert_invalid_with(r, "CODE_PREFIX_CONTRACT_INVALID")

    def test_not_dict(self):
        self._run_prefix_mutation(lambda f: f.update(code_prefix_contract={"x": 1}))

    def test_missing_sh_main(self):
        self._run_prefix_mutation(
            lambda f: f["code_prefix_contract"].pop("sh_main"))

    def test_extra_field(self):
        def mut(f):
            f["code_prefix_contract"]["extra"] = "x"
        self._run_prefix_mutation(mut)

    def test_sh_main_wrong(self):
        self._run_prefix_mutation(
            lambda f: f["code_prefix_contract"].update(sh_main="61xxxx"))

    def test_sz_main_wrong(self):
        self._run_prefix_mutation(
            lambda f: f["code_prefix_contract"].update(sz_main="01xxxx"))

    def test_chinext_wrong(self):
        self._run_prefix_mutation(
            lambda f: f["code_prefix_contract"].update(chinext="31xxxx"))

    def test_star_wrong(self):
        self._run_prefix_mutation(
            lambda f: f["code_prefix_contract"].update(star="69xxxx"))

    def test_excluded_missing_item(self):
        self._run_prefix_mutation(
            lambda f: f["code_prefix_contract"]["excluded_prefixes"].pop())

    def test_excluded_extra_item(self):
        self._run_prefix_mutation(
            lambda f: f["code_prefix_contract"]["excluded_prefixes"].append("5xxxxx"))

    def test_excluded_wrong_order(self):
        def mut(f):
            f["code_prefix_contract"]["excluded_prefixes"] = [
                "8xxxxx", "4xxxxx", "920xxx", "9xxxxx"]
        self._run_prefix_mutation(mut)

    def test_excluded_duplicate(self):
        def mut(f):
            f["code_prefix_contract"]["excluded_prefixes"] = [
                "4xxxxx", "4xxxxx", "8xxxxx", "920xxx"]
        self._run_prefix_mutation(mut)

    def test_normalization_empty(self):
        self._run_prefix_mutation(
            lambda f: f["code_prefix_contract"].update(normalization=""))

    def test_normalization_int(self):
        self._run_prefix_mutation(
            lambda f: f["code_prefix_contract"].update(normalization=123))

    def test_normalization_tampered(self):
        self._run_prefix_mutation(
            lambda f: f["code_prefix_contract"].update(
                normalization="trim → keep string → validate 6 digits"))

    def test_note_empty(self):
        self._run_prefix_mutation(
            lambda f: f["code_prefix_contract"].update(note=""))

    def test_note_missing(self):
        self._run_prefix_mutation(
            lambda f: f["code_prefix_contract"].pop("note"))

    def test_note_st_boundary_removed(self):
        self._run_prefix_mutation(
            lambda f: f["code_prefix_contract"].update(
                note="前缀合同用于市场板块形状校验。"))

    def test_note_tampered(self):
        self._run_prefix_mutation(
            lambda f: f["code_prefix_contract"].update(
                note="前缀合同用于市场板块形状校验；不能只依赖前缀。"))


# ---------------------------------------------------------------------------
# 16. 严格 JSON 树类型
# ---------------------------------------------------------------------------

class TestStrictJsonTree:
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

    def test_top_level_dict_subclass_rejected(self):
        r = validator.validate_layered_promotion_fixture(self._DictSubclass())
        assert r["status"] == "invalid"
        assert "FIXTURE_NOT_DICT" in r["issue_codes"]

    @pytest.mark.parametrize("bad_value", [
        _ListSubclass([1]),
        _StrSubclass("x"),
        _IntSubclass(1),
        _FloatSubclass(1.0),
        (1, 2),
        {"a"},
        b"bytes",
        1j,
        object(),
        float("nan"),
        float("inf"),
        float("-inf"),
    ])
    def test_nested_non_json_values_rejected(self, bad_value):
        fixture = _load_fixture()
        fixture["description"] = bad_value
        r = validator.validate_layered_promotion_fixture(fixture)
        assert r["status"] == "invalid"
        assert "TOP_LEVEL_FIELD_INVALID" in r["issue_codes"]

    def test_non_str_dict_key_rejected(self):
        fixture = _load_fixture()
        fixture[1] = "x"
        r = validator.validate_layered_promotion_fixture(fixture)
        assert r["status"] == "invalid"
        assert "TOP_LEVEL_FIELD_INVALID" in r["issue_codes"]

    def test_valid_fixture_still_valid(self):
        r = validator.validate_layered_promotion_fixture(_load_fixture())
        assert r["status"] == "valid"


# ---------------------------------------------------------------------------
# 17. 七类 case 命名语义
# ---------------------------------------------------------------------------

class TestCaseSemanticContracts:
    def _paired_mutation(self, case_id, mutator):
        fixture = _load_fixture()
        mutator(fixture)
        r = validator.validate_layered_promotion_fixture(fixture)
        cr = next(c for c in r["case_results"] if c["case_id"] == case_id)
        assert cr["status"] == "invalid"
        assert "CASE_SCHEMA_INVALID" in cr["issue_codes"]

    def _sync_normal_expected(self, case):
        prev_pool = case["previous_snapshot"]["limit_up_pool"]
        curr_pool = case["current_snapshot"]["limit_up_pool"]
        case["expected"] = {
            "status": "normal",
            "reason_codes": [],
            "warnings": [],
            "layered_promotion_rates": validator._calculate_rates(
                prev_pool, curr_pool),
        }

    def test_normal_single_level_rejected(self):
        def mut(f):
            case = next(c for c in f["cases"] if c["case_id"] == "normal")
            case["previous_snapshot"]["limit_up_pool"] = [
                {"stock_code": "600001", "consecutive_limit_up_days": 1},
                {"stock_code": "600002", "consecutive_limit_up_days": 1},
            ]
            case["previous_snapshot"]["data_health"]["row_count"] = 2
            self._sync_normal_expected(case)
        self._paired_mutation("normal", mut)

    def test_zero_denominator_adds_level_3_rejected(self):
        def mut(f):
            case = next(c for c in f["cases"]
                        if c["case_id"] == "zero_denominator")
            case["previous_snapshot"]["limit_up_pool"].insert(
                1, {"stock_code": "300001", "consecutive_limit_up_days": 3})
            case["previous_snapshot"]["data_health"]["row_count"] = 4
            self._sync_normal_expected(case)
        self._paired_mutation("zero_denominator", mut)

    def test_previous_legal_zero_flag_removed_rejected(self):
        def mut(f):
            case = next(c for c in f["cases"]
                        if c["case_id"] == "previous_legal_zero")
            case["previous_snapshot"]["data_health"]["legal_zero"] = False
            case["expected"] = {
                "status": "normal", "reason_codes": [],
                "warnings": [], "layered_promotion_rates": [],
            }
        self._paired_mutation("previous_legal_zero", mut)

    def test_current_legal_zero_flag_removed_rejected(self):
        def mut(f):
            case = next(c for c in f["cases"]
                        if c["case_id"] == "current_legal_zero")
            case["current_snapshot"]["data_health"]["legal_zero"] = False
            prev_pool = case["previous_snapshot"]["limit_up_pool"]
            case["expected"] = {
                "status": "normal", "reason_codes": [],
                "warnings": [],
                "layered_promotion_rates": validator._calculate_rates(
                    prev_pool, []),
            }
        self._paired_mutation("current_legal_zero", mut)

    def test_partial_repaired_to_normal_rejected(self):
        def mut(f):
            case = next(c for c in f["cases"] if c["case_id"] == "partial")
            case["current_snapshot"]["data_health"]["coverage_warning"] = False
            self._sync_normal_expected(case)
        self._paired_mutation("partial", mut)

    def test_unavailable_repaired_to_normal_rejected(self):
        def mut(f):
            case = next(c for c in f["cases"]
                        if c["case_id"] == "unavailable")
            case["current_snapshot"]["data_health"]["transport_success"] = True
            self._sync_normal_expected(case)
        self._paired_mutation("unavailable", mut)

    def test_identity_edge_plain_consecutive_rejected(self):
        def mut(f):
            case = next(c for c in f["cases"]
                        if c["case_id"] == "identity_edge")
            case["current_snapshot"]["limit_up_pool"] = [
                {"stock_code": "000001", "consecutive_limit_up_days": 3},
                {"stock_code": "000002", "consecutive_limit_up_days": 3},
                {"stock_code": "600001", "consecutive_limit_up_days": 2},
            ]
            case["current_snapshot"]["data_health"]["row_count"] = 3
            self._sync_normal_expected(case)
        self._paired_mutation("identity_edge", mut)


# ---------------------------------------------------------------------------
# 18. 9 个 reason code 全部可达
# ---------------------------------------------------------------------------

class TestReasonCodeReachability:
    def _case_result(self, case_id, mutator):
        fixture = _load_fixture()
        mutator(fixture)
        r = validator.validate_layered_promotion_fixture(fixture)
        return next(c for c in r["case_results"] if c["case_id"] == case_id)

    def _sync_unavailable_expected(self, case, reason_codes):
        case["expected"] = {
            "status": "unavailable",
            "reason_codes": reason_codes,
            "warnings": [],
            "layered_promotion_rates": None,
        }

    def test_source_and_current_unavailable(self):
        cr = self._case_result(
            "unavailable", lambda f: None)
        assert cr["derived_status"] == "unavailable"
        assert cr["derived_reason_codes"] == [
            "SOURCE_UNAVAILABLE", "CURRENT_SNAPSHOT_UNAVAILABLE"]
        assert cr["derived_layered_promotion_rates"] is None

    def test_previous_unavailable(self):
        def mut(f):
            case = next(c for c in f["cases"] if c["case_id"] == "normal")
            case["previous_snapshot"]["data_health"]["transport_success"] = False
            self._sync_unavailable_expected(
                case, ["SOURCE_UNAVAILABLE", "PREVIOUS_SNAPSHOT_UNAVAILABLE"])
        cr = self._case_result("normal", mut)
        assert cr["derived_status"] == "unavailable"
        assert cr["derived_reason_codes"] == [
            "SOURCE_UNAVAILABLE", "PREVIOUS_SNAPSHOT_UNAVAILABLE"]

    def test_calendar_unavailable(self):
        def mut(f):
            case = next(c for c in f["cases"] if c["case_id"] == "normal")
            case["previous_snapshot"]["data_health"]["trade_date_match"] = None
            self._sync_unavailable_expected(case, [
                "SOURCE_UNAVAILABLE", "PREVIOUS_SNAPSHOT_UNAVAILABLE",
                "TRADING_CALENDAR_UNAVAILABLE"])
        cr = self._case_result("normal", mut)
        assert cr["derived_reason_codes"] == [
            "SOURCE_UNAVAILABLE", "PREVIOUS_SNAPSHOT_UNAVAILABLE",
            "TRADING_CALENDAR_UNAVAILABLE"]

    def test_trade_date_mismatch(self):
        def mut(f):
            case = next(c for c in f["cases"] if c["case_id"] == "normal")
            case["current_snapshot"]["data_health"]["trade_date_match"] = False
            self._sync_unavailable_expected(case, [
                "SOURCE_UNAVAILABLE", "CURRENT_SNAPSHOT_UNAVAILABLE",
                "TRADE_DATE_MISMATCH"])
        cr = self._case_result("normal", mut)
        assert cr["derived_reason_codes"] == [
            "SOURCE_UNAVAILABLE", "CURRENT_SNAPSHOT_UNAVAILABLE",
            "TRADE_DATE_MISMATCH"]

    def test_not_final(self):
        def mut(f):
            case = next(c for c in f["cases"] if c["case_id"] == "normal")
            case["current_snapshot"]["session"] = "not_final"
            case["current_snapshot"]["is_final"] = False
            self._sync_unavailable_expected(case, [
                "SOURCE_UNAVAILABLE", "CURRENT_SNAPSHOT_UNAVAILABLE",
                "NOT_FINAL"])
        cr = self._case_result("normal", mut)
        assert cr["derived_reason_codes"] == [
            "SOURCE_UNAVAILABLE", "CURRENT_SNAPSHOT_UNAVAILABLE", "NOT_FINAL"]

    def test_source_partial_and_partial_coverage(self):
        cr = self._case_result("partial", lambda f: None)
        assert cr["derived_status"] == "partial"
        assert cr["derived_reason_codes"] == [
            "SOURCE_PARTIAL", "PARTIAL_COVERAGE"]
        assert cr["derived_layered_promotion_rates"] is None

    def test_unexplained_empty(self):
        def mut(f):
            case = next(c for c in f["cases"]
                        if c["case_id"] == "zero_denominator")
            case["current_snapshot"]["limit_up_pool"] = []
            case["current_snapshot"]["data_health"].update(
                row_count=0, unexplained_empty=True)
            case["expected"] = {
                "status": "partial",
                "reason_codes": ["SOURCE_PARTIAL", "UNEXPLAINED_EMPTY"],
                "warnings": [],
                "layered_promotion_rates": None,
            }
        cr = self._case_result("zero_denominator", mut)
        assert cr["derived_status"] == "partial"
        assert cr["derived_reason_codes"] == [
            "SOURCE_PARTIAL", "UNEXPLAINED_EMPTY"]
        assert cr["derived_layered_promotion_rates"] is None


# ---------------------------------------------------------------------------
# 19. unavailable / partial 组合优先级
# ---------------------------------------------------------------------------

class TestUnavailableReasonComposition:
    def _derived(self, case_id, mutator):
        fixture = _load_fixture()
        mutator(fixture)
        r = validator.validate_layered_promotion_fixture(fixture)
        cr = next(c for c in r["case_results"] if c["case_id"] == case_id)
        return cr["derived_status"], cr["derived_reason_codes"], \
            cr["derived_layered_promotion_rates"]

    def _sync(self, case, status, codes):
        case["expected"] = {
            "status": status, "reason_codes": codes,
            "warnings": [], "layered_promotion_rates": None,
        }

    def test_transport_failure_beats_coverage(self):
        def mut(f):
            case = next(c for c in f["cases"] if c["case_id"] == "normal")
            case["previous_snapshot"]["data_health"]["transport_success"] = False
            case["current_snapshot"]["data_health"]["coverage_warning"] = True
            self._sync(case, "unavailable",
                       ["SOURCE_UNAVAILABLE", "PREVIOUS_SNAPSHOT_UNAVAILABLE"])
        status, codes, rates = self._derived("normal", mut)
        assert status == "unavailable"
        assert codes == ["SOURCE_UNAVAILABLE", "PREVIOUS_SNAPSHOT_UNAVAILABLE"]
        assert rates is None

    def test_calendar_beats_legal_zero(self):
        def mut(f):
            case = next(c for c in f["cases"]
                        if c["case_id"] == "current_legal_zero")
            case["previous_snapshot"]["data_health"]["trade_date_match"] = None
            self._sync(case, "unavailable", [
                "SOURCE_UNAVAILABLE", "PREVIOUS_SNAPSHOT_UNAVAILABLE",
                "TRADING_CALENDAR_UNAVAILABLE"])
        status, codes, _ = self._derived("current_legal_zero", mut)
        assert status == "unavailable"
        assert codes == [
            "SOURCE_UNAVAILABLE", "PREVIOUS_SNAPSHOT_UNAVAILABLE",
            "TRADING_CALENDAR_UNAVAILABLE"]

    def test_date_mismatch_beats_partial(self):
        def mut(f):
            case = next(c for c in f["cases"] if c["case_id"] == "partial")
            case["current_snapshot"]["data_health"]["trade_date_match"] = False
            self._sync(case, "unavailable", [
                "SOURCE_UNAVAILABLE", "CURRENT_SNAPSHOT_UNAVAILABLE",
                "TRADE_DATE_MISMATCH"])
        status, codes, _ = self._derived("partial", mut)
        assert status == "unavailable"
        assert codes == [
            "SOURCE_UNAVAILABLE", "CURRENT_SNAPSHOT_UNAVAILABLE",
            "TRADE_DATE_MISMATCH"]

    def test_not_final_beats_partial(self):
        def mut(f):
            case = next(c for c in f["cases"] if c["case_id"] == "partial")
            case["current_snapshot"]["session"] = "not_final"
            case["current_snapshot"]["is_final"] = False
            self._sync(case, "unavailable", [
                "SOURCE_UNAVAILABLE", "CURRENT_SNAPSHOT_UNAVAILABLE",
                "NOT_FINAL"])
        status, codes, _ = self._derived("partial", mut)
        assert status == "unavailable"
        assert codes == [
            "SOURCE_UNAVAILABLE", "CURRENT_SNAPSHOT_UNAVAILABLE", "NOT_FINAL"]

    def test_previous_and_current_unavailable(self):
        def mut(f):
            case = next(c for c in f["cases"] if c["case_id"] == "normal")
            case["previous_snapshot"]["data_health"]["transport_success"] = False
            case["current_snapshot"]["data_health"]["transport_success"] = False
            self._sync(case, "unavailable", [
                "SOURCE_UNAVAILABLE", "PREVIOUS_SNAPSHOT_UNAVAILABLE",
                "CURRENT_SNAPSHOT_UNAVAILABLE"])
        status, codes, _ = self._derived("normal", mut)
        assert status == "unavailable"
        assert codes == [
            "SOURCE_UNAVAILABLE", "PREVIOUS_SNAPSHOT_UNAVAILABLE",
            "CURRENT_SNAPSHOT_UNAVAILABLE"]

    def test_previous_partial_current_unavailable(self):
        def mut(f):
            case = next(c for c in f["cases"] if c["case_id"] == "partial")
            case["previous_snapshot"]["data_health"]["coverage_warning"] = True
            case["current_snapshot"]["data_health"]["transport_success"] = False
            self._sync(case, "unavailable",
                       ["SOURCE_UNAVAILABLE", "CURRENT_SNAPSHOT_UNAVAILABLE"])
        status, codes, _ = self._derived("partial", mut)
        assert status == "unavailable"
        assert codes == ["SOURCE_UNAVAILABLE", "CURRENT_SNAPSHOT_UNAVAILABLE"]

    def test_previous_unavailable_current_partial(self):
        def mut(f):
            case = next(c for c in f["cases"] if c["case_id"] == "partial")
            case["previous_snapshot"]["data_health"]["transport_success"] = False
            self._sync(case, "unavailable",
                       ["SOURCE_UNAVAILABLE", "PREVIOUS_SNAPSHOT_UNAVAILABLE"])
        status, codes, _ = self._derived("partial", mut)
        assert status == "unavailable"
        assert codes == ["SOURCE_UNAVAILABLE", "PREVIOUS_SNAPSHOT_UNAVAILABLE"]

    def test_coverage_plus_unexplained(self):
        def mut(f):
            case = next(c for c in f["cases"]
                        if c["case_id"] == "zero_denominator")
            case["current_snapshot"]["limit_up_pool"] = []
            case["current_snapshot"]["data_health"].update(
                row_count=0, coverage_warning=True, unexplained_empty=True)
            case["expected"] = {
                "status": "partial",
                "reason_codes": [
                    "SOURCE_PARTIAL", "PARTIAL_COVERAGE", "UNEXPLAINED_EMPTY"],
                "warnings": [],
                "layered_promotion_rates": None,
            }
        status, codes, _ = self._derived("zero_denominator", mut)
        assert status == "partial"
        assert codes == [
            "SOURCE_PARTIAL", "PARTIAL_COVERAGE", "UNEXPLAINED_EMPTY"]


# ---------------------------------------------------------------------------
# 20. rate 必须为 float
# ---------------------------------------------------------------------------

class TestRateFloatBoundary:
    def test_int_zero_rate_rejected(self):
        def mut(f):
            item = _normal_case(f)["expected"]["layered_promotion_rates"][0]
            item["rate"] = 0
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "RATE_SCHEMA_INVALID")

    def test_int_one_rate_rejected(self):
        def mut(f):
            item = _normal_case(f)["expected"]["layered_promotion_rates"][2]
            item["rate"] = 1
        _assert_invalid_with(
            validator.validate_layered_promotion_fixture(_mutate(mut)),
            "RATE_SCHEMA_INVALID")

    def test_oracle_rates_are_float(self):
        r = validator.validate_layered_promotion_fixture(_load_fixture())
        for cr in r["case_results"]:
            rates = cr["derived_layered_promotion_rates"]
            if rates is None:
                continue
            for item in rates:
                assert type(item["rate"]) is float


# ---------------------------------------------------------------------------
# 21. case_count 语义
# ---------------------------------------------------------------------------

class TestCaseCountSemantics:
    def test_valid_fixture_seven(self):
        r = validator.validate_layered_promotion_fixture(_load_fixture())
        assert r["case_count"] == 7
        assert len(r["case_results"]) == 7

    def test_non_dict_fixture_zero(self):
        r = validator.validate_layered_promotion_fixture(None)
        assert r["case_count"] == 0
        assert r["case_results"] == []

    def test_cases_not_list_zero(self):
        def mut(f):
            f["cases"] = "not-a-list"
        r = validator.validate_layered_promotion_fixture(_mutate(mut))
        assert r["case_count"] == 0
        assert r["case_results"] == []

    def test_empty_cases_zero(self):
        def mut(f):
            f["cases"] = []
        r = validator.validate_layered_promotion_fixture(_mutate(mut))
        assert r["case_count"] == 0

    def test_mixed_cases_count_matches_results(self):
        def mut(f):
            f["cases"][0] = "not-a-dict"
        r = validator.validate_layered_promotion_fixture(_mutate(mut))
        assert r["case_count"] == 7
        assert len(r["case_results"]) == 7
        assert r["case_results"][0]["status"] == "invalid"


# ---------------------------------------------------------------------------
# 22. 文档一致性
# ---------------------------------------------------------------------------

class TestDocumentationAlignment:
    def test_validator_doc_sections(self):
        text = VALIDATOR_DOC_PATH.read_text(encoding="utf-8")
        for i in range(1, 22):
            assert f"## {i}." in text

    def test_validator_doc_decision_table(self):
        text = VALIDATOR_DOC_PATH.read_text(encoding="utf-8")
        assert "CONDITIONAL GO" in text
        assert "Blocker 9" in text
        assert "candidate CLOSED" in text
        assert "implementation_allowed(layered_promotion_rates)" in text
        assert "false" in text

    def test_feasibility_doc_no_affirmative_stale_contracts(self):
        text = FEASIBILITY_DOC_PATH.read_text(encoding="utf-8")
        # 否定性说明允许；肯定性失真合同不得存在
        assert "partial 状态输出 concrete rates" not in text
        assert "coverage_warning=true 仍计算比例" not in text
        assert "getYesterdayZTPool 作为精确 previous denominator" not in text
