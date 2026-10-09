"""Synthetic source-to-sink evidence checks; no real-model quality evaluation."""
import json

import pytest

import app as app_module
import myreports as mr
import myreports_fulltext as ft
from test_myreports_fulltext import client, _pdf, _upload


@pytest.mark.parametrize("provider", ["api", "cli-codex"])
def test_corrected_pdf_extraction_cannot_be_cited_using_cached_old_hit(tmp_path, monkeypatch, provider):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "reports")
    report = _upload("correction.pdf", _pdf("catalyst OLD_EXTRACTION_100"))
    old = mr.search_report_text("catalyst", report_ids=[report["id"]])
    assert old[0]["page"] == 1
    monkeypatch.setattr(ft, "extract", lambda *args: (
        ft.STATUS_SEARCHABLE, [(1, "catalyst CORRECTED_EXTRACTION_80")], 1, ""))
    mr.index_report_text(report["id"])
    fresh = mr.search_report_text("catalyst", report_ids=[report["id"]])
    assert old[0]["file_sha256"] == fresh[0]["file_sha256"]
    assert old[0]["chunk_sha256"] != fresh[0]["chunk_sha256"]
    supplied = [old]
    monkeypatch.setattr(mr, "search_report_text", lambda *args, **kwargs: supplied[0])
    contexts = []

    def api_stream(_cfg, _messages, context):
        contexts.append(context)
        yield {"type": "delta", "text": "SYNTHETIC"}
        yield {"type": "done"}

    def codex_stream(**kwargs):
        yield from api_stream(None, None, kwargs["context"])

    monkeypatch.setattr(app_module.chat_layer, "run_chat_stream", api_stream)
    monkeypatch.setattr(app_module.agent_runtime, "stream_chat", codex_stream)
    monkeypatch.setattr(app_module.agent_runtime, "status", lambda: {"available": True})
    body = {"messages": [{"role": "user", "content": "catalyst"}], "report_ids": [report["id"]],
            "session": "synthetic-hit-freshness", "llm": {"provider": provider,
            "model": "synthetic", "baseURL": "https://example.test", "apiKey": "synthetic"}}
    response = client.post("/api/chat", json=body)
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0]["type"] == "sources" and events[0]["items"] == []
    assert events[0]["coverage"]["rejected_hit_count"] == 1
    assert events[0]["coverage"]["uncovered_reports"][0]["reason"] == "STALE_HIT"
    assert len(contexts) == 1 and "OLD_EXTRACTION_100" not in contexts[0]
    assert "OLD_EXTRACTION_100" not in response.text and events[-1]["type"] == "done"
    # A fresh retrieval restores only the current extracted evidence and page.
    supplied[0] = fresh
    response = client.post("/api/chat", json=body)
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0]["items"] == [{"report_id": report["id"], "title": "correction", "page": 1}]
    assert len(contexts) == 2 and "CORRECTED_EXTRACTION_80" in contexts[1]
    assert "OLD_EXTRACTION_100" not in contexts[1]


def test_rejected_page_does_not_remove_unchanged_page_or_invent_budget_loss(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "reports")
    report = _upload("two-pages.pdf", _pdf("catalyst unchanged", "catalyst OLD_100"))
    old = mr.search_report_text("catalyst", report_ids=[report["id"]])
    monkeypatch.setattr(ft, "extract", lambda *args: (
        ft.STATUS_SEARCHABLE, [(1, "catalyst unchanged"), (2, "catalyst NEW_80")], 2, ""))
    mr.index_report_text(report["id"])
    context, sources, coverage = mr.build_chat_report_context(old, report_ids=[report["id"]])
    assert [(source["report_id"], source["page"]) for source in sources] == [(report["id"], 1)]
    assert "OLD_100" not in context and "unchanged" in context
    assert coverage["rejected_hit_count"] == 1
    assert coverage["included_hit_count"] == 1 and coverage["context_truncated"] is False
