"""P0-SER1 A-share Security Exchange Routing Authority v0.1 tests."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import security_exchange_policy as ser
from security_exchange_policy import (
    BSE_LEGACY_STOCK_CODES_V01,
    BSE_SOURCE_REFS_V01,
    POLICY_AUTHORITY_REF_V01,
    POLICY_VERSION_V01,
    SCHEMA_VERSION,
    SSE_SOURCE_REFS_V01,
    SZSE_SOURCE_REFS_V01,
    SecurityExchangePolicyValidationError,
    resolve_security_exchange,
)

BACKEND = Path(__file__).resolve().parents[1]
MODULE_PATH = BACKEND / "security_exchange_policy.py"


def _resolve(code: str = "600519", version: str = POLICY_VERSION_V01):
    return resolve_security_exchange(
        security_code=code,
        policy_version=version,
    )


def _assert_resolved(code: str, exchange: str, refs: tuple[str, ...]) -> None:
    result = _resolve(code)
    assert result == {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION_V01,
        "security_code": code,
        "exchange_resolution_state": "RESOLVED",
        "exchange": exchange,
        "authority_ref": POLICY_AUTHORITY_REF_V01,
        "source_refs": list(refs),
    }


@pytest.mark.parametrize(
    "code",
    [
        "600000", "600519", "600999",
        "601000", "601999",
        "603000", "603999",
        "605000", "605999",
    ],
)
def test_sse_main_board_exact_segments_resolve(code):
    _assert_resolved(code, "SSE", SSE_SOURCE_REFS_V01)


@pytest.mark.parametrize("code", ["688000", "688001", "688999"])
def test_sse_star_exact_segment_resolves(code):
    _assert_resolved(code, "SSE", SSE_SOURCE_REFS_V01)


@pytest.mark.parametrize(
    "code",
    ["000000", "000001", "000999", "001200", "001999", "002000", "004999"],
)
def test_szse_main_board_exact_segments_resolve(code):
    _assert_resolved(code, "SZSE", SZSE_SOURCE_REFS_V01)


@pytest.mark.parametrize("code", ["300000", "300750", "309799"])
def test_szse_chinext_exact_segment_resolves(code):
    _assert_resolved(code, "SZSE", SZSE_SOURCE_REFS_V01)


@pytest.mark.parametrize("code", ["430017", "837023", "831010"])
def test_bse_official_exact_legacy_codes_resolve(code):
    _assert_resolved(code, "BSE", BSE_SOURCE_REFS_V01)


def test_bse_legacy_mapping_is_full_exact_frozen_set():
    assert len(BSE_LEGACY_STOCK_CODES_V01) == 248
    assert {"430017", "837023", "831010"} <= BSE_LEGACY_STOCK_CODES_V01


@pytest.mark.parametrize("code", ["920000", "920001", "920999"])
def test_bse_current_stock_allocation_segment_resolves(code):
    _assert_resolved(code, "BSE", BSE_SOURCE_REFS_V01)


@pytest.mark.parametrize("code", ["510300", "159915", "184801"])
def test_known_etf_or_fund_segments_not_resolved(code):
    result = _resolve(code)
    assert result["exchange_resolution_state"] == "NOT_RESOLVED"
    assert result["exchange"] is None


@pytest.mark.parametrize("code", ["110000", "127001", "019001"])
def test_known_bond_segments_not_resolved(code):
    assert _resolve(code)["exchange_resolution_state"] == "NOT_RESOLVED"


@pytest.mark.parametrize("code", ["900901", "200001"])
def test_known_b_share_segments_not_resolved(code):
    assert _resolve(code)["exchange_resolution_state"] == "NOT_RESOLVED"


@pytest.mark.parametrize("code", ["689001", "001001", "001199", "309800"])
def test_known_depositary_receipt_segments_not_resolved(code):
    assert _resolve(code)["exchange_resolution_state"] == "NOT_RESOLVED"


@pytest.mark.parametrize(
    "code", ["602000", "604000", "606000", "310000", "919999", "930000"]
)
def test_unproven_six_digit_gaps_not_resolved(code):
    assert _resolve(code)["exchange_resolution_state"] == "NOT_RESOLVED"


@pytest.mark.parametrize("code", ["430001", "837024", "830001", "873999"])
def test_bse_legacy_prefix_or_suffix_is_never_guessed(code):
    assert code not in BSE_LEGACY_STOCK_CODES_V01
    assert _resolve(code)["exchange_resolution_state"] == "NOT_RESOLVED"


@pytest.mark.parametrize(
    "value",
    [
        None, True, False, 600519, 600519.0, "", "60051", "6005190",
        "60051A", " 600519", "600519 ", "SH600519", "600519.SH",
        "６００５１９",
    ],
)
def test_malformed_security_code_fails_closed(value):
    with pytest.raises(SecurityExchangePolicyValidationError):
        resolve_security_exchange(
            security_code=value,
            policy_version=POLICY_VERSION_V01,
        )


@pytest.mark.parametrize("value", [None, True, 1, "", " ", " v0.1"])
def test_invalid_policy_version_fails_closed(value):
    with pytest.raises(SecurityExchangePolicyValidationError):
        resolve_security_exchange(
            security_code="600519",
            policy_version=value,
        )


def test_unknown_policy_version_is_not_evaluated_not_latest():
    result = _resolve("600519", "security_exchange_policy.v9.9")
    assert result == {
        "schema_version": SCHEMA_VERSION,
        "policy_version": "security_exchange_policy.v9.9",
        "security_code": "600519",
        "exchange_resolution_state": "NOT_EVALUATED",
        "exchange": None,
        "authority_ref": None,
        "source_refs": [],
    }


def test_policy_version_has_no_default_latest():
    signature = inspect.signature(resolve_security_exchange)
    assert signature.parameters["policy_version"].default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        resolve_security_exchange(security_code="600519")


def test_resolution_is_deterministic_for_repeated_calls():
    expected = _resolve("600519")
    for _ in range(100):
        assert _resolve("600519") == expected


def test_result_mutation_does_not_mutate_policy_or_future_output():
    code = "000001"
    first = _resolve(code)
    first["source_refs"].append("caller:forged")
    first["exchange"] = "SSE"
    second = _resolve(code)
    assert code == "000001"
    assert second["exchange"] == "SZSE"
    assert second["source_refs"] == list(SZSE_SOURCE_REFS_V01)


def test_output_does_not_claim_existence_listing_tradability_or_coverage():
    result = _resolve("600123")  # range routing may resolve a nonexistent code
    forbidden = {
        "exists", "instrument_exists", "listed", "listing_status",
        "active", "tradable", "usable", "data_coverage", "price_data_exists",
    }
    assert result["exchange_resolution_state"] == "RESOLVED"
    assert forbidden.isdisjoint(result)


def test_output_is_canonical_exchange_not_provider_alias():
    for code, expected in (("600519", "SSE"), ("000001", "SZSE"), ("920001", "BSE")):
        result = _resolve(code)
        assert result["exchange"] == expected
        assert not result["exchange"].startswith(".")
        assert result["security_code"] == code
        assert ".SH" not in str(result) and ".SZ" not in str(result)
        assert ".BJ" not in str(result)


def test_policy_source_metadata_and_authority_reference_are_stable():
    assert POLICY_AUTHORITY_REF_V01 == "security_exchange_policy:v0.1"
    assert POLICY_VERSION_V01 == "security_exchange_policy.v0.1"
    assert SZSE_SOURCE_REFS_V01 == (
        "https://www.szse.cn/marketServices/technicalservice/doc/"
        "P020260306733846760075.pdf",
    )
    assert all(ref.startswith("https://") for ref in ser.SOURCE_REFS_V01)
    assert len(ser.SOURCE_REFS_V01) == len(set(ser.SOURCE_REFS_V01))


def test_module_has_no_provider_or_runtime_authority_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {
        "requests", "httpx", "tushare", "akshare", "sqlite3", "duckdb",
        "pathlib", "os", "time", "datetime", "campaign_store",
        "fact_lake_store", "bk11_tushare_facts_adapter",
        "tushare_daily_shadow", "financial_indicator_shadow",
    }
    assert imported.isdisjoint(forbidden)


def test_module_has_no_network_db_filesystem_wall_clock_or_stock_basic_call():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    call_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                call_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                call_names.add(node.func.attr)
    forbidden = {
        "open", "connect", "request", "get", "post", "urlopen", "now",
        "utcnow", "today", "time", "stock_basic", "daily", "query",
    }
    assert call_names.isdisjoint(forbidden)


def test_public_api_does_not_accept_as_of_provider_alias_or_injected_authority():
    params = inspect.signature(resolve_security_exchange).parameters
    assert tuple(params) == ("security_code", "policy_version")
    assert "as_of" not in params
    assert "provider" not in params
    assert "ts_code" not in params
    assert "authority_ref" not in params
