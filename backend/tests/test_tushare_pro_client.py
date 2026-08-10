"""Tushare Pro 客户端离线测试（无网络请求）。"""

from __future__ import annotations

import io
import json
import sys
import time
import urllib.error
from unittest import mock

import pytest

sys.path.insert(0, "backend")

import tushare_pro_client as tpc  # noqa: E402


def _payload(code=0, msg="ok", fields=("ts_code", "trade_date"), items=None):
    return json.dumps({
        "code": code,
        "msg": msg,
        "data": {
            "fields": list(fields),
            "items": items if items is not None else [["600519.SH", "2026-07-30"]],
        },
    }).encode("utf-8")


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        status: int = 200,
        content_type: str = "application/json; charset=utf-8",
    ):
        self._body = body
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit: int | None = None):
        if limit is not None:
            return self._body[:limit]
        return self._body


def _client():
    return tpc.TushareClient()


def _patch_urlopen(body: bytes, status: int = 200):
    return mock.patch(
        "urllib.request.urlopen",
        return_value=FakeResponse(body, status),
    )


def test_normal_response(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "test-token")
    with _patch_urlopen(_payload()):
        rows = _client().query("daily", {"trade_date": "20260730"}, "ts_code,trade_date")
    assert rows == [{"ts_code": "600519.SH", "trade_date": "2026-07-30"}]


def test_token_not_in_error_text(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "super-secret-token-abc")
    with _patch_urlopen(_payload(code=1001, msg="bad request")):
        with pytest.raises(tpc.TushareProtocolError) as exc:
            _client().query("daily", {})
    assert "super-secret-token-abc" not in str(exc.value)
    assert "bad request" not in str(exc.value)


def test_permission_denied_2002(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    with _patch_urlopen(_payload(code=2002, msg="permission denied")):
        with pytest.raises(tpc.TusharePermissionDenied):
            _client().query("daily", {})


def test_nonzero_code_protocol_error(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    with _patch_urlopen(_payload(code=1001, msg="some provider error")):
        with pytest.raises(tpc.TushareProtocolError):
            _client().query("daily", {})


def test_malformed_json(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    with _patch_urlopen(b"{not json"):
        with pytest.raises(tpc.TushareProtocolError):
            _client().query("daily", {})


def test_data_none(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    body = json.dumps({"code": 0, "msg": "ok", "data": None}).encode()
    with _patch_urlopen(body):
        with pytest.raises(tpc.TushareProtocolError):
            _client().query("daily", {})


def test_fields_missing(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    body = json.dumps({"code": 0, "msg": "ok", "data": {"items": []}}).encode()
    with _patch_urlopen(body):
        with pytest.raises(tpc.TushareProtocolError):
            _client().query("daily", {})


def test_items_missing(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    body = json.dumps({"code": 0, "msg": "ok", "data": {"fields": ["a"]}}).encode()
    with _patch_urlopen(body):
        with pytest.raises(tpc.TushareProtocolError):
            _client().query("daily", {})


def test_row_length_mismatch(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    with _patch_urlopen(_payload(items=[["only-one"] ])):
        with pytest.raises(tpc.TushareProtocolError):
            _client().query("daily", {})


def test_duplicate_fields(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    with _patch_urlopen(_payload(fields=("a", "a"), items=[[1, 2]])):
        with pytest.raises(tpc.TushareProtocolError):
            _client().query("daily", {})


def test_oversize_response(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    with _patch_urlopen(b"x" * (tpc._MAX_RESPONSE_BYTES + 10)):
        with pytest.raises(tpc.TushareProtocolError):
            _client().query("daily", {})


def test_http_5xx_retries_then_transport_error(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    with mock.patch(
        "urllib.request.urlopen",
        side_effect=[FakeResponse(b"", 500), FakeResponse(b"", 503),
                     FakeResponse(b"", 502)],
    ) as m, mock.patch.object(time, "sleep"):
        with pytest.raises(tpc.TushareTransportError):
            _client().query("daily", {})
    assert m.call_count == 3


def test_http_5xx_retry_then_success(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    with mock.patch(
        "urllib.request.urlopen",
        side_effect=[FakeResponse(b"", 500), FakeResponse(_payload())],
    ) as m, mock.patch.object(time, "sleep"):
        rows = _client().query("daily", {})
    assert m.call_count == 2
    assert rows


def test_protocol_error_not_retried(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    with mock.patch(
        "urllib.request.urlopen",
        side_effect=[FakeResponse(_payload(code=1001))],
    ) as m:
        with pytest.raises(tpc.TushareProtocolError):
            _client().query("daily", {})
    assert m.call_count == 1


def test_transport_error_retries(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    exc = urllib.error.URLError("boom")
    with mock.patch(
        "urllib.request.urlopen",
        side_effect=[exc, exc, exc],
    ) as m, mock.patch.object(time, "sleep"):
        with pytest.raises(tpc.TushareTransportError):
            _client().query("daily", {})
    assert m.call_count == 3


def test_token_missing(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    with pytest.raises(tpc.TushareCredentialMissing):
        _client().query("daily", {})


def test_input_not_modified(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    params = {"trade_date": "20260730"}
    fields = "ts_code,trade_date"
    with _patch_urlopen(_payload()):
        _client().query("daily", params, fields)
    assert params == {"trade_date": "20260730"}
    assert fields == "ts_code,trade_date"


def test_unknown_api_rejected(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    with pytest.raises(tpc.TushareProtocolError):
        _client().query("unknown_api", {})


def test_keyboard_interrupt_propagates(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "t")
    with mock.patch(
        "urllib.request.urlopen",
        side_effect=KeyboardInterrupt,
    ):
        with pytest.raises(KeyboardInterrupt):
            _client().query("daily", {})


def test_custom_endpoint_rejected():
    with pytest.raises(ValueError):
        tpc.TushareClient(endpoint="https://evil.example.com")


def test_request_body_contains_api_name_token_params_fields(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "tok123")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["url"] = request.full_url
        return FakeResponse(_payload())

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        _client().query("stock_basic", {"list_status": "L"}, "ts_code")
    assert captured["url"] == tpc.ENDPOINT
    assert captured["body"]["api_name"] == "stock_basic"
    assert captured["body"]["token"] == "tok123"
    assert captured["body"]["params"] == {"list_status": "L"}
    assert captured["body"]["fields"] == "ts_code"


def test_fina_indicator_is_allowed_and_raw_sink_receives_exact_response_only(
    monkeypatch,
):
    token = "secret-that-must-never-reach-the-sink"
    monkeypatch.setenv("TUSHARE_TOKEN", token)
    monkeypatch.setattr(
        tpc,
        "_utc_now_iso",
        lambda: "2026-08-11T08:00:00.000000Z",
    )
    raw = _payload(
        fields=("ts_code", "ann_date", "end_date", "update_flag", "eps"),
        items=[["600519.SH", "20260430", "20260331", "1", 2.5]],
    )
    captured = []
    with _patch_urlopen(raw):
        rows = _client().query(
            "fina_indicator",
            {"ts_code": "600519.SH", "period": "20260331"},
            "ts_code,ann_date,end_date,update_flag,eps",
            raw_response_sink=lambda body, metadata: captured.append(
                (body, dict(metadata))
            ),
        )
    assert rows == [{
        "ts_code": "600519.SH",
        "ann_date": "20260430",
        "end_date": "20260331",
        "update_flag": "1",
        "eps": 2.5,
    }]
    assert captured == [(raw, {
        "endpoint": tpc.ENDPOINT,
        "api_name": "fina_indicator",
        "params": {"period": "20260331", "ts_code": "600519.SH"},
        "fields": "ts_code,ann_date,end_date,update_flag,eps",
        "http_status": 200,
        "content_type": "application/json; charset=utf-8",
        "fetched_at": "2026-08-11T08:00:00.000000Z",
    })]
    serialized = raw.decode("utf-8") + json.dumps(
        captured[0][1],
        ensure_ascii=False,
    )
    assert token not in serialized
    assert "raw POST body" not in serialized


def test_raw_sink_observes_malformed_terminal_bytes_before_parser_rejects(
    monkeypatch,
):
    monkeypatch.setenv("TUSHARE_TOKEN", "not-persisted")
    monkeypatch.setattr(
        tpc,
        "_utc_now_iso",
        lambda: "2026-08-11T08:00:00.000000Z",
    )
    captured = []
    with _patch_urlopen(b"{malformed"):
        with pytest.raises(tpc.TushareProtocolError):
            _client().query(
                "fina_indicator",
                {"ts_code": "600519.SH", "period": "20260331"},
                "ts_code",
                raw_response_sink=lambda body, metadata: captured.append(
                    (body, dict(metadata))
                ),
            )
    assert captured[0][0] == b"{malformed"


def test_public_interpreter_preserves_exact_field_manifest():
    raw = _payload(
        fields=("ts_code", "end_date"),
        items=[["600519.SH", "20260331"]],
    )
    parsed = tpc.interpret_tushare_response_bytes(raw, "fina_indicator")
    assert parsed.fields == ("ts_code", "end_date")
    assert parsed.as_rows() == [{"ts_code": "600519.SH", "end_date": "20260331"}]


def test_raw_sink_failure_is_not_retried_as_transport(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "test-only-placeholder")
    monkeypatch.setattr(
        tpc,
        "_utc_now_iso",
        lambda: "2026-08-11T08:00:00.000000Z",
    )
    with _patch_urlopen(_payload()) as request:
        with pytest.raises(tpc.TushareProtocolError, match="原始响应接收失败"):
            _client().query(
                "fina_indicator",
                {"ts_code": "600519.SH", "period": "20260331"},
                "ts_code,trade_date",
                raw_response_sink=lambda *_: (_ for _ in ()).throw(
                    OSError("local sink failure")
                ),
            )
    assert request.call_count == 1


@pytest.mark.parametrize("secret_key", ["token", "authorization", "cookie"])
def test_raw_sink_rejects_secret_bearing_semantic_params_before_network(
    monkeypatch,
    secret_key,
):
    monkeypatch.setenv("TUSHARE_TOKEN", "test-only-placeholder")
    with mock.patch("urllib.request.urlopen") as request:
        with pytest.raises(tpc.TushareProtocolError, match="unsafe"):
            _client().query(
                "fina_indicator",
                {"ts_code": "600519.SH", secret_key: "must-not-persist"},
                "ts_code",
                raw_response_sink=lambda *_: None,
            )
    request.assert_not_called()


def test_sink_absent_does_not_touch_new_receipt_metadata_path(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "test-only-placeholder")

    class LegacyShapeResponse(FakeResponse):
        @property
        def headers(self):
            raise AssertionError("headers must not be read without raw sink")

        @headers.setter
        def headers(self, value):
            pass

    with mock.patch(
        "urllib.request.urlopen",
        return_value=LegacyShapeResponse(_payload()),
    ):
        assert _client().query("daily", {})
