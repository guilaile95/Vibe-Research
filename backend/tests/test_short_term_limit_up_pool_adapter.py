"""BK-11 涨停池结构化来源适配器 v0.1 · 全路径失败关闭测试。

不发起任何 live 网络请求：所有 HTTP 行为通过 monkeypatch
``astock.em_get`` 注入 fake response 实现。所有交易日历行为通过
monkeypatch ``trade_calendar._load_calendar`` / ``_today_shanghai``
实现。
"""
from __future__ import annotations

import json
import sys
from datetime import date
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, "backend")

import astock  # noqa: E402
import trade_calendar  # noqa: E402
import short_term_limit_up_pool_adapter as adapter  # noqa: E402


# ---------------------------------------------------------------------------
# 测试基础设施
# ---------------------------------------------------------------------------

# 固定一组在 sessions 内的历史日期（2026-07-30 是周四交易日）
SESSIONS = (
    "2024-01-02", "2024-01-03", "2026-06-18", "2026-06-22",
    "2026-07-24", "2026-07-27", "2026-07-29", "2026-07-30",
    "2026-07-31",
)
GOOD_DATE = "2026-07-30"
GOOD_DATE_EM = "20260730"
TODAY_FROZEN = date(2026, 8, 4)


@pytest.fixture(autouse=True)
def _calendar_stub(monkeypatch):
    monkeypatch.setattr(trade_calendar, "_load_calendar", lambda: SESSIONS)
    monkeypatch.setattr(trade_calendar, "_today_shanghai", lambda: TODAY_FROZEN)
    monkeypatch.setattr(adapter, "_today_shanghai", lambda: TODAY_FROZEN)


@pytest.fixture(autouse=True)
def _reset_em_calls():
    """记录 em_get 是否被调用，用于验证非交易日不发请求。"""
    state = {"calls": 0}

    def fake_em_get(*args, **kwargs):
        state["calls"] += 1
        raise AssertionError("em_get must not be called in this scenario")

    yield state, fake_em_get


def _fake_response(*, status_code: int = 200, json_body=None, json_raises=None):
    class R:
        def __init__(self):
            self.status_code = status_code
            self._json_body = json_body
            self._json_raises = json_raises

        def json(self):
            if self._json_raises is not None:
                raise self._json_raises
            return self._json_body
    return R()


def _patch_em_get(monkeypatch, responder):
    calls: list[tuple[tuple, dict]] = []

    def fake(url, params=None, headers=None, timeout=15):
        calls.append(((url,), dict(params=params, headers=headers, timeout=timeout)))
        return responder(calls)

    monkeypatch.setattr(astock, "em_get", fake)
    return calls


def _assert_contract_shape(result: dict) -> None:
    """断言十字段 + 附加字段全部存在且类型正确。"""
    assert result["schema_version"] == adapter.SCHEMA_VERSION
    assert result["source_id"] == "eastmoney_getTopicZTPool"
    assert result["endpoint"] == "getTopicZTPool"
    assert isinstance(result["requested_trade_date"], str)
    assert isinstance(result["observed_at"], str)
    assert result["status"] in ("normal", "partial", "unavailable")
    assert isinstance(result["reason_codes"], list)
    for code in result["reason_codes"]:
        assert isinstance(code, str)
    assert isinstance(result["rows"], list)
    assert isinstance(result["transport_success"], bool)
    assert isinstance(result["parse_success"], bool)
    assert isinstance(result["required_field_present"], bool)
    assert isinstance(result["data_array_present"], bool)
    assert result["trade_date_match"] in (True, False, None)
    assert isinstance(result["row_count"], int) and result["row_count"] >= 0
    assert isinstance(result["legal_zero"], bool)
    assert isinstance(result["upstream_null"], bool)
    assert isinstance(result["unexplained_empty"], bool)
    assert isinstance(result["coverage_warning"], bool)
    assert result["http_status"] is None or isinstance(result["http_status"], int)
    assert isinstance(result["error_class"], str)
    assert isinstance(result["excluded_universe_count"], int)
    assert isinstance(result["invalid_row_count"], int)
    assert isinstance(result["duplicate_code_count"], int)
    # 不变量
    assert result["row_count"] == len(result["rows"])
    if result["status"] == "unavailable":
        assert result["rows"] == []
    if result["status"] == "normal":
        assert result["coverage_warning"] is False
    if result["status"] == "partial":
        assert result["coverage_warning"] is True
    # legal_zero 在本版本不可达
    assert result["legal_zero"] is False
    # rows 升序且唯一
    codes = [r["stock_code"] for r in result["rows"]]
    assert codes == sorted(codes)
    assert len(set(codes)) == len(codes)
    # reason_codes 顺序与固定顺序一致
    fixed = list(adapter._REASON_CODE_ORDER)
    seen: list[str] = []
    for c in result["reason_codes"]:
        if c not in seen:
            seen.append(c)
    for a, b in zip(seen, seen[1:]):
        if a in fixed and b in fixed:
            assert fixed.index(a) < fixed.index(b)


def _pool(rows: list[dict]) -> dict:
    return {"data": {"pool": rows}}


# ---------------------------------------------------------------------------
# 1. 日期输入
# ---------------------------------------------------------------------------

class TestDateInput:
    @pytest.mark.parametrize("value", [None, 123, True, False, 3.14, object()])
    def test_non_string(self, monkeypatch, value, _reset_em_calls):
        state, fake = _reset_em_calls
        monkeypatch.setattr(astock, "em_get", fake)
        r = adapter.fetch_limit_up_pool_snapshot(value)
        _assert_contract_shape(r)
        assert r["status"] == "unavailable"
        assert "NON_TRADING_DATE" in r["reason_codes"]
        assert r["transport_success"] is False
        assert r["parse_success"] is False
        assert state["calls"] == 0

    def test_empty_string(self, monkeypatch, _reset_em_calls):
        state, fake = _reset_em_calls
        monkeypatch.setattr(astock, "em_get", fake)
        r = adapter.fetch_limit_up_pool_snapshot("")
        _assert_contract_shape(r)
        assert r["status"] == "unavailable"
        assert "NON_TRADING_DATE" in r["reason_codes"]
        assert state["calls"] == 0

    @pytest.mark.parametrize("value", [
        "2026-7-30", "2026/07/30", "20260730", " 2026-07-30", "2026-07-30 ",
        " 2026-07-30 ", "2026-7-30", "abcd-ef-gh", "not-a-date",
    ])
    def test_non_strict_format(self, monkeypatch, value, _reset_em_calls):
        state, fake = _reset_em_calls
        monkeypatch.setattr(astock, "em_get", fake)
        r = adapter.fetch_limit_up_pool_snapshot(value)
        _assert_contract_shape(r)
        assert r["status"] == "unavailable"
        assert "NON_TRADING_DATE" in r["reason_codes"]
        assert state["calls"] == 0

    @pytest.mark.parametrize("value", ["2026-13-01", "2026-02-30", "2026-00-15"])
    def test_invalid_calendar_values(self, monkeypatch, value, _reset_em_calls):
        state, fake = _reset_em_calls
        monkeypatch.setattr(astock, "em_get", fake)
        r = adapter.fetch_limit_up_pool_snapshot(value)
        _assert_contract_shape(r)
        assert r["status"] == "unavailable"
        assert "NON_TRADING_DATE" in r["reason_codes"]
        assert state["calls"] == 0

    def test_weekend(self, monkeypatch, _reset_em_calls):
        # 2026-08-01 是周六，不在 sessions
        state, fake = _reset_em_calls
        monkeypatch.setattr(astock, "em_get", fake)
        r = adapter.fetch_limit_up_pool_snapshot("2026-08-01")
        _assert_contract_shape(r)
        assert r["status"] == "unavailable"
        assert "NON_TRADING_DATE" in r["reason_codes"]
        assert state["calls"] == 0

    def test_official_holiday(self, monkeypatch, _reset_em_calls):
        # 2026-06-19 是端午（官方休市日），不在 sessions
        state, fake = _reset_em_calls
        monkeypatch.setattr(astock, "em_get", fake)
        r = adapter.fetch_limit_up_pool_snapshot("2026-06-19")
        _assert_contract_shape(r)
        assert r["status"] == "unavailable"
        assert "NON_TRADING_DATE" in r["reason_codes"]
        assert state["calls"] == 0

    def test_future_date(self, monkeypatch, _reset_em_calls):
        # 2026-12-31 > TODAY_FROZEN 2026-08-04，但 sessions 包含它
        # 我们 monkeypatch sessions 加入未来日
        monkeypatch.setattr(trade_calendar, "_load_calendar",
                            lambda: SESSIONS + ("2026-12-31",))
        monkeypatch.setattr(adapter, "_today_shanghai", lambda: TODAY_FROZEN)
        state, fake = _reset_em_calls
        monkeypatch.setattr(astock, "em_get", fake)
        r = adapter.fetch_limit_up_pool_snapshot("2026-12-31")
        _assert_contract_shape(r)
        assert r["status"] == "unavailable"
        assert "NON_TRADING_DATE" in r["reason_codes"]
        assert state["calls"] == 0

    def test_out_of_range(self, monkeypatch, _reset_em_calls):
        state, fake = _reset_em_calls
        monkeypatch.setattr(astock, "em_get", fake)
        r = adapter.fetch_limit_up_pool_snapshot("2020-01-02")
        _assert_contract_shape(r)
        assert r["status"] == "unavailable"
        assert "NON_TRADING_DATE" in r["reason_codes"]
        assert state["calls"] == 0

    def test_calendar_unavailable(self, monkeypatch, _reset_em_calls):
        monkeypatch.setattr(trade_calendar, "_load_calendar", lambda: None)
        state, fake = _reset_em_calls
        monkeypatch.setattr(astock, "em_get", fake)
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["status"] == "unavailable"
        assert "TRADING_CALENDAR_UNAVAILABLE" in r["reason_codes"]
        assert state["calls"] == 0


# ---------------------------------------------------------------------------
# 2. 传输与 HTTP
# ---------------------------------------------------------------------------

class TestTransport:
    def _run(self, monkeypatch, exc):
        def raise_exc(*args, **kwargs):
            raise exc
        monkeypatch.setattr(astock, "em_get", raise_exc)
        return adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)

    def test_timeout(self, monkeypatch):
        import requests
        r = self._run(monkeypatch, requests.Timeout("boom"))
        _assert_contract_shape(r)
        assert r["status"] == "unavailable"
        assert "REQUEST_TIMEOUT" in r["reason_codes"]
        assert r["transport_success"] is False

    def test_connect_timeout(self, monkeypatch):
        import requests
        r = self._run(monkeypatch, requests.ConnectTimeout())
        _assert_contract_shape(r)
        assert "REQUEST_TIMEOUT" in r["reason_codes"]

    def test_read_timeout(self, monkeypatch):
        import requests
        r = self._run(monkeypatch, requests.ReadTimeout())
        _assert_contract_shape(r)
        assert "REQUEST_TIMEOUT" in r["reason_codes"]

    def test_connection_error(self, monkeypatch):
        import requests
        r = self._run(monkeypatch, requests.ConnectionError("down"))
        _assert_contract_shape(r)
        assert "TRANSPORT_ERROR" in r["reason_codes"]
        assert r["transport_success"] is False

    def test_proxy_error(self, monkeypatch):
        # urllib3 ProxyError 通常被 requests 包成 ConnectionError
        import requests
        r = self._run(monkeypatch, requests.ConnectionError("proxy down"))
        _assert_contract_shape(r)
        assert "TRANSPORT_ERROR" in r["reason_codes"]

    def test_tls_error(self, monkeypatch):
        import requests
        r = self._run(monkeypatch, requests.ConnectionError("SSL failure"))
        _assert_contract_shape(r)
        assert "TRANSPORT_ERROR" in r["reason_codes"]

    @pytest.mark.parametrize("code,expected", [
        (429, "RATE_LIMITED"),
        (401, "ACCESS_RESTRICTED"),
        (403, "ACCESS_RESTRICTED"),
        (404, "HTTP_ERROR"),
        (500, "HTTP_ERROR"),
        (503, "HTTP_ERROR"),
    ])
    def test_http_status_classification(self, monkeypatch, code, expected):
        def resp(*args, **kwargs):
            return _fake_response(status_code=code, json_body={"data": {"pool": []}})
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["status"] == "unavailable"
        assert expected in r["reason_codes"]
        assert r["transport_success"] is True
        assert r["parse_success"] is False
        assert r["legal_zero"] is False
        assert r["rows"] == []
        assert r["http_status"] == code


# ---------------------------------------------------------------------------
# 3. JSON / schema
# ---------------------------------------------------------------------------

class TestSchema:
    def test_invalid_json(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_raises=ValueError("bad json"))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert "PARSE_ERROR" in r["reason_codes"]
        assert r["transport_success"] is True and r["parse_success"] is False

    def test_top_level_list(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=[{"pool": []}])
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert "DATA_ARRAY_INVALID" in r["reason_codes"]

    def test_data_missing(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body={})
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert "REQUIRED_FIELD_MISSING" in r["reason_codes"]

    def test_data_null(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body={"data": None})
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert "UPSTREAM_NULL" in r["reason_codes"]
        assert r["upstream_null"] is True

    def test_data_non_dict(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body={"data": "x"})
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert "DATA_ARRAY_INVALID" in r["reason_codes"]

    def test_pool_missing(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body={"data": {}})
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert "REQUIRED_FIELD_MISSING" in r["reason_codes"]

    def test_pool_null(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body={"data": {"pool": None}})
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert "UPSTREAM_NULL" in r["reason_codes"]
        assert r["upstream_null"] is True

    def test_pool_non_list(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body={"data": {"pool": "x"}})
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert "DATA_ARRAY_INVALID" in r["reason_codes"]
        assert r["data_array_present"] is True


# ---------------------------------------------------------------------------
# 4. Date binding
# ---------------------------------------------------------------------------

class TestDateBinding:
    def test_qdate_yyyymmdd_match(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body={
                "qdate": GOOD_DATE_EM,
                "data": {"pool": [{"c": "600000", "lbc": 1}]},
            })
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["trade_date_match"] is True
        assert r["status"] == "normal"
        assert r["rows"] == [{"stock_code": "600000", "lbc": 1}]

    def test_date_yyyy_mm_dd_match(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body={
                "data": {"date": GOOD_DATE, "pool": [{"c": "000001", "lbc": 1}]},
            })
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["trade_date_match"] is True

    def test_trade_date_match(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body={
                "data": {"trade_date": GOOD_DATE_EM, "pool": [{"c": "300001", "lbc": 2}]},
            })
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["trade_date_match"] is True

    def test_date_mismatch(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body={
                "data": {"date": "2026-07-29", "pool": [{"c": "600000", "lbc": 1}]},
            })
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["trade_date_match"] is False
        assert "TRADE_DATE_MISMATCH" in r["reason_codes"]
        assert r["status"] == "unavailable"
        assert r["rows"] == []

    def test_no_date_field(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": "600000", "lbc": 1},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["trade_date_match"] is None
        assert "DATE_BINDING_UNVERIFIED" in r["reason_codes"]
        assert r["status"] == "partial"
        assert r["coverage_warning"] is True

    def test_invalid_date_field_keeps_unverified(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body={
                "data": {"date": "not-a-date", "pool": [{"c": "600000", "lbc": 1}]},
            })
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["trade_date_match"] is None
        assert "DATE_BINDING_UNVERIFIED" in r["reason_codes"]


# ---------------------------------------------------------------------------
# 5. Universe
# ---------------------------------------------------------------------------

class TestUniverse:
    @pytest.mark.parametrize("code,included", [
        ("600000", True),
        ("000001", True),
        ("300001", True),
        ("688001", True),
        ("400001", False),
        ("830001", False),
        ("920001", False),
        ("900901", False),
        ("200001", False),
        ("510300", False),
        ("159919", False),
        ("113000", False),
    ])
    def test_prefix_inclusion(self, monkeypatch, code, included):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": code, "lbc": 1},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        if included:
            assert any(x["stock_code"] == code for x in r["rows"])
            assert r["excluded_universe_count"] == 0
        else:
            assert all(x["stock_code"] != code for x in r["rows"])
            assert r["excluded_universe_count"] == 1

    def test_st_name_included(self, monkeypatch):
        # 名称不影响 universe（adapter 不读取名称）
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": "600000", "n": "ST test", "lbc": 1},
                {"c": "000001", "n": "*ST test", "lbc": 1},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["row_count"] == 2
        assert r["excluded_universe_count"] == 0
        assert {x["stock_code"] for x in r["rows"]} == {"600000", "000001"}

    def test_excluded_rows_do_not_cause_partial(self, monkeypatch):
        # 全部因 universe 排除：仍是 partial + UNEXPLAINED_EMPTY
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": "400001", "lbc": 1},
                {"c": "830001", "lbc": 2},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["rows"] == []
        assert r["excluded_universe_count"] == 2
        assert r["invalid_row_count"] == 0


# ---------------------------------------------------------------------------
# 6. 行合同
# ---------------------------------------------------------------------------

class TestRowContract:
    def test_valid_six_digit_code(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": "600000", "lbc": 1},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["rows"] == [{"stock_code": "600000", "lbc": 1}]

    def test_string_leading_zero_preserved(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": "000009", "lbc": 1},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["rows"] == [{"stock_code": "000009", "lbc": 1}]

    def test_int_code_rejected(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": 1, "lbc": 1},
                {"c": "600000", "lbc": 1},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["invalid_row_count"] == 1
        assert r["rows"] == [{"stock_code": "600000", "lbc": 1}]
        assert "INVALID_POOL_ROW" in r["reason_codes"]

    def test_five_digit_rejected(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": "60000", "lbc": 1},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["invalid_row_count"] == 1
        assert r["rows"] == []

    def test_seven_digit_rejected(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": "6000000", "lbc": 1},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["invalid_row_count"] == 1

    def test_non_digit_rejected(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": "60abcd", "lbc": 1},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["invalid_row_count"] == 1

    def test_lbc_missing(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": "600000"},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["invalid_row_count"] == 1
        assert r["rows"] == []

    def test_lbc_zero(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": "600000", "lbc": 0},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["invalid_row_count"] == 1

    def test_lbc_negative(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": "600000", "lbc": -1},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["invalid_row_count"] == 1

    def test_lbc_bool_rejected(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": "600000", "lbc": True},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["invalid_row_count"] == 1

    def test_lbc_string_rejected(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": "600000", "lbc": "2"},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["invalid_row_count"] == 1

    def test_duplicate_keeps_first(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": "600000", "lbc": 3},
                {"c": "600000", "lbc": 5},  # 重复
                {"c": "000001", "lbc": 2},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["duplicate_code_count"] == 1
        assert "DUPLICATE_STOCK_CODE" in r["reason_codes"]
        assert r["rows"] == [
            {"stock_code": "000001", "lbc": 2},
            {"stock_code": "600000", "lbc": 3},  # 保留首次
        ]
        # 排序 + 唯一
        codes = [x["stock_code"] for x in r["rows"]]
        assert codes == sorted(codes)
        assert len(set(codes)) == len(codes)

    def test_sorted_ascending(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": "688001", "lbc": 1},
                {"c": "300001", "lbc": 2},
                {"c": "000001", "lbc": 3},
                {"c": "600000", "lbc": 4},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert [x["stock_code"] for x in r["rows"]] == [
            "000001", "300001", "600000", "688001",
        ]


# ---------------------------------------------------------------------------
# 7. 空池 / legal_zero
# ---------------------------------------------------------------------------

class TestEmptyPool:
    def test_http200_empty_pool_is_unexplained(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["status"] == "partial"
        assert r["rows"] == []
        assert r["row_count"] == 0
        assert r["legal_zero"] is False
        assert r["unexplained_empty"] is True
        assert "UNEXPLAINED_EMPTY" in r["reason_codes"]
        assert r["coverage_warning"] is True


# ---------------------------------------------------------------------------
# 8. 完整合同不变量
# ---------------------------------------------------------------------------

class TestContractInvariants:
    def test_normal_means_no_coverage_warning(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body={
                "data": {"date": GOOD_DATE, "pool": [{"c": "600000", "lbc": 1}]},
            })
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["status"] == "normal"
        assert r["coverage_warning"] is False
        assert r["reason_codes"] == []

    def test_partial_means_coverage_warning(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body=_pool([
                {"c": "600000", "lbc": 1},
            ]))
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        _assert_contract_shape(r)
        assert r["status"] == "partial"
        assert r["coverage_warning"] is True

    def test_no_exception_text_in_output(self, monkeypatch):
        import requests as req
        def raise_exc(*args, **kwargs):
            raise req.ConnectionError("leaked URL https://foo/?token=abc123")
        monkeypatch.setattr(astock, "em_get", raise_exc)
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        text = json.dumps(r, ensure_ascii=False, default=str)
        assert "https://foo" not in text
        assert "abc123" not in text
        assert "token=" not in text

    def test_no_network_leak_in_partial(self, monkeypatch):
        def resp(*args, **kwargs):
            return _fake_response(status_code=200, json_body={
                "data": {"pool": [{"c": "bad", "lbc": 1}, {"c": "600000", "lbc": 1}]},
            })
        _patch_em_get(monkeypatch, lambda calls: resp())
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        text = json.dumps(r, ensure_ascii=False, default=str)
        for sensitive in ("Cookie", "Authorization", "Token"):
            assert sensitive not in text

    def test_no_raw_exception_text_in_unavailable(self, monkeypatch):
        import requests as req
        def raise_exc(*args, **kwargs):
            raise req.ConnectionError("raw traceback line")
        monkeypatch.setattr(astock, "em_get", raise_exc)
        r = adapter.fetch_limit_up_pool_snapshot(GOOD_DATE)
        assert "raw traceback line" not in json.dumps(r, ensure_ascii=False, default=str)
