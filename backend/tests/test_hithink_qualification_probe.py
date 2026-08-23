"""Offline safety checks for the bounded HiThink operator probe."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_TOOL_PATH = (
    Path(__file__).resolve().parents[2]
    / "tools"
    / "research"
    / "hithink_qualification_probe.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "hithink_qualification_probe_under_test", _TOOL_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def test_safe_message_scrubs_active_credential_before_truncation():
    assert probe._safe_message(
        "provider reflected credential-value in error", "credential-value"
    ) == "provider reflected <redacted> in error"


def test_data_summary_drops_presigned_url_and_secret_key_values():
    summary = probe._data_summary({
        "presigned_url": "must-not-survive",
        "api_key": "must-not-survive-either",
        "expires_at": "2026-08-24T00:00:00Z",
    })
    assert summary["keys"] == ["expires_at"]
    assert summary["types"] == {"expires_at": "str"}
    assert "must-not-survive" not in repr(summary)


def test_item_summary_is_bounded_and_does_not_copy_arbitrary_values():
    rows = [
        {
            "thscode": f"{index:06d}.SH",
            "name": "arbitrary-provider-text",
            "date_ms": index,
            "close_price": 1.0,
        }
        for index in range(20)
    ]
    summary = probe._item_summary(rows)
    assert len(summary["sample_identities"]) == probe.MAX_SAMPLE_IDENTITIES
    assert summary["count"] == 20
    assert "arbitrary-provider-text" not in repr(summary)


def test_authenticated_probe_request_never_follows_redirects():
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"code": 0, "message": "ok", "request_id": "r", "data": {}}

    class Session:
        def __init__(self):
            self.kwargs = None

        def get(self, url, **kwargs):
            self.kwargs = kwargs
            return Response()

    session = Session()
    result, _ = probe.get_json(session, "test-value", "dataset", "/fixed")
    assert result["status"] == "PASS"
    assert session.kwargs["allow_redirects"] is False
    assert "test-value" not in repr(result)


def test_probe_never_persists_non_integer_business_code_values():
    class Response:
        status_code = 200

        def __init__(self, code):
            self.code = code

        def json(self):
            return {"code": self.code, "data": None}

    class Session:
        def __init__(self, code):
            self.code = code

        def get(self, _url, **_kwargs):
            return Response(self.code)

    for value in ("test-value", False):
        result, _ = probe.get_json(Session(value), "test-value", "dataset", "/fixed")
        assert result["status"] == "UNKNOWN"
        assert result["envelope_code"] is None
        assert result["envelope_code_type"] in {"str", "bool"}
        assert "test-value" not in repr(result)
