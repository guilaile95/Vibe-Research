"""Offline indexed-page acceptance; no provider or semantic model evaluation."""
import sqlite3

import pytest

import myreports as mr
import myreports_fulltext as ft
from test_myreports_fulltext import client, _pdf, _upload


@pytest.fixture
def report(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "reports")
    return _upload("correction.pdf", _pdf("Overview", "Revenue 100. " + "context " * 90 + "Correction: revenue is 80, not 100.", ""))


def read(report, **overrides):
    body = dict(report_id=report["id"], selected_report_ids=[report["id"]],
                expected_file_sha256=report["file_sha256"], page_from=2, page_to=2)
    body.update(overrides)
    return client.post("/api/myreports/page-read", json=body)


def test_late_correction_and_read_only(report):
    before = {p.name: p.read_bytes() for p in mr.REPORTS_DIR.iterdir() if p.is_file()}
    hit = mr.search_report_text("Revenue", report_ids=[report["id"]])[0]
    assert "Correction:" not in hit["snippet"]
    result = read(report).json()["data"]
    assert "Correction: revenue is 80" in result["items"][0]["text"]
    assert result["coverage"]["readable"] == [2]
    assert result["complete_requested_text"] is True
    assert result["full_report_read"] is False
    assert before == {p.name: p.read_bytes() for p in mr.REPORTS_DIR.iterdir() if p.is_file()}


def test_partition_and_budgets(report):
    result = read(report, page_from=1, page_to=4, max_pages=1).json()["data"]
    assert result["coverage"] == dict(readable=[1], omitted=[2], invalid=[4], unreadable=[3], error=[])
    result = read(report, page_from=2, page_to=3, max_chars=10).json()["data"]
    assert result["returned_chars"] == 10
    assert result["items"][0]["truncated"] is True
    assert result["complete_requested_text"] is False


def replace_page(report, text):
    with sqlite3.connect(ft._path(mr.REPORTS_DIR)) as conn:
        conn.execute("UPDATE report_text_chunks SET text=? WHERE report_id=? AND page=2", (text, report["id"]))


def test_unicode_budget_and_large_first_page(report):
    replace_page(report, "更正😀" * 10000)
    result = read(report, max_chars=5, max_page_chars=4).json()["data"]
    assert result["items"][0]["text"] == "更正😀更"
    assert result["returned_chars"] == 4
    assert result["items"][0]["indexed_chars"] == 30000


@pytest.mark.parametrize("value", ["", "   ", "[IMAGE]", "N/A", "---", "PDF_NO_EXTRACTABLE_TEXT"])
def test_empty_and_placeholder_never_read(report, value):
    replace_page(report, value)
    assert read(report).json()["data"]["coverage"]["unreadable"] == [2]


@pytest.mark.parametrize("overrides", [dict(page_from=-1), dict(page_to=10**100), dict(page_to=201, page_from=1),
    dict(page_to=1), dict(page_from=1.5), dict(page_from=True), dict(page_from="2"), dict(max_chars=20001)])
def test_invalid_request_422_before_expansion(report, overrides):
    assert read(report, **overrides).status_code == 422


def test_scope_and_hash_fail_closed(report, monkeypatch):
    assert read(report, selected_report_ids=["other"]).json()["data"]["items"][0]["reason"] == "REPORT_NOT_SELECTED"
    result = read(report, expected_file_sha256="a" * 64).json()["data"]
    assert result["coverage"]["error"] == [2] and result["returned_chars"] == 0
    real_hash = ft._source_sha256
    calls = 0
    def changing(path):
        nonlocal calls
        calls += 1
        return real_hash(path) if calls == 1 else "b" * 64
    monkeypatch.setattr(ft, "_source_sha256", changing)
    result = read(report).json()["data"]
    assert result["items"] == [dict(page=2, status="error", reason="FILE_CHANGED_DURING_READ")]
    assert result["returned_chars"] == 0


def test_unpaginated_and_missing_index(report):
    text_report = _upload("source.txt", b"No physical PDF page")
    assert read(text_report).json()["data"]["items"][0]["reason"] == "PAGE_NUMBERS_UNAVAILABLE"
    with sqlite3.connect(ft._path(mr.REPORTS_DIR)) as conn:
        conn.execute("DELETE FROM report_text_index WHERE report_id=?", (report["id"],))
    assert read(report).json()["data"]["items"][0]["reason"] == "NOT_INDEXED"

@pytest.mark.parametrize("value", ["N/A", "[IMAGE]", "OCR_REQUIRED"])
def test_placeholder_with_tiny_char_budget(report, value):
    replace_page(report, value)
    assert read(report, max_chars=1).json()["data"]["coverage"]["readable"] == []


def test_source_edit_and_corrupt_index(report):
    source = mr.REPORTS_DIR / f"{report['id']}.pdf"
    original = source.read_bytes()
    source.write_bytes(original + b"changed")
    assert read(report).json()["data"]["items"][0]["reason"] == "FILE_CHANGED"
    source.write_bytes(original)
    ft._path(mr.REPORTS_DIR).write_bytes(b"invalid sqlite")
    assert read(report).json()["data"]["items"][0]["reason"] == "INDEX_READ_FAILED"


def test_blank_report_uses_extraction_evidence_not_ocr_claim(report):
    blank = _upload("blank.pdf", _pdf(""))
    result = read(blank, page_from=1, page_to=2).json()["data"]
    assert result["coverage"]["unreadable"] == [1]
    assert result["coverage"]["invalid"] == [2]
    assert result["items"][0]["reason"] == "NO_EXTRACTABLE_TEXT"
