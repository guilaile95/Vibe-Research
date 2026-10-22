"""Synthetic first-page contracts; no external request is performed."""
import pytest
import astock


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def _provider(monkeypatch, rows, total=None):
    calls = []
    class Session:
        def get(self, url, **kwargs):
            calls.append(kwargs["params"])
            return Response({"data": {"list": rows, "total_hits": total}})
    monkeypatch.setattr(astock, "_em_session", lambda *_: Session())
    return calls


@pytest.mark.parametrize("total,expected", [(30, True), (1, False), (None, None), (True, None), (-1, None)])
def test_first_page_success_does_not_certify_window_or_full_text(monkeypatch, total, expected):
    calls = _provider(monkeypatch, [{"notice_date": "2026-09-01", "title": "合成公告", "art_code": "fixture"}], total)
    result = astock.announcements("600001", strict=True, with_coverage=True)
    assert result["request_status"] == "NORMAL"
    assert len(result["rows"]) == 1
    assert result["source_coverage"]["status"] == "partial"
    assert result["source_coverage"]["truncated"] is expected
    assert result["source_coverage"]["window_complete"] is False
    assert result["source_coverage"]["full_text_included"] is False
    assert result["source_coverage"]["pages_fetched"] == 1
    assert calls[0]["page_index"] == 1 and calls[0]["page_size"] == 15
    assert isinstance(astock.announcements("600001"), list), "legacy callers keep their list contract"


def test_empty_page_is_successful_but_completeness_remains_unproven(monkeypatch):
    _provider(monkeypatch, [], 0)
    result = astock.announcements("600001", with_coverage=True)
    assert result["rows"] == []
    assert result["request_status"] == "NORMAL"
    assert result["source_coverage"]["window_complete"] is False


def test_coverage_does_not_relabel_malformed_response_as_empty_success(monkeypatch):
    class Session:
        def get(self, *_, **__):
            return Response({"data": {}})
    monkeypatch.setattr(astock, "_em_session", lambda *_: Session())
    with pytest.raises(ValueError, match="missing list"):
        astock.announcements("600001", with_coverage=True)
