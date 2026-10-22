"""Offline source snapshots describe selected inputs, never fresh reconstructed news."""
import json
from unittest.mock import patch
import pytest
import native_intel_ai as ai

CFG = {"provider": "cli-codex", "model": "fixture"}
VALID = json.dumps({key: {} if key == "standalone_summaries" else "fixture" for key in ai.REQUIRED_ANALYSIS_KEYS})


def item(name, section="hotlist", **extra):
    return {"item_key": name, "title": name, "source_id": "synthetic", "source_type": section,
            "url": "https://example.com/" + name, "published_at": "2026-10-20T08:00:00Z", **extra}


def run(report, runner=lambda *_: VALID, **kwargs):
    with patch.object(ai.store, "find_cached_ai_artifact", return_value=None), patch.object(ai.store, "save_ai_artifact") as save:
        result = ai.analyze_report(report, cfg=CFG, model_runner=runner, **kwargs)
        assert save.call_args.kwargs["payload"] == result
        return result


def test_snapshot_matches_actual_selected_prompt_and_standalone():
    first, second, rss, excluded, standalone = item("first", ordering_score=10), item("second"), item("rss", "rss"), item("excluded", "rss"), item("standalone")
    prompts = []
    def runner(_, messages):
        prompts.append(messages[1]["content"])
        return VALID
    with patch("native_intel_service.get_standalone_items", return_value={"items": [standalone, standalone], "total": 1}):
        result = run({"items": [second, first, first, rss, excluded]}, runner, max_news=3, include_standalone=True)
    snapshot = result["input_sources"]
    assert [entry["title"] for entry in snapshot["items"]] == ["first", "second", "rss", "standalone"]
    for entry in snapshot["items"]:
        assert entry["title"] in prompts[0]
        assert entry["published_at"] in prompts[0]
    assert "excluded" not in prompts[0]
    assert snapshot["submission_status"] == "RESPONSE_RECEIVED"
    assert snapshot["coverage"]["rss"]["omitted"] == 1
    assert snapshot["coverage"]["rss"]["reason"] == "budget_truncated"


@pytest.mark.parametrize("enabled,items,reason", [
    (False, [item("rss", "rss")], "disabled"),
    (True, [], "no_items"),
    (True, [item("hot"), item("rss", "rss")], "budget_exhausted"),
])
def test_rss_zero_reasons(enabled, items, reason):
    result = run({"items": items}, max_news=1, include_rss=enabled)
    assert result["input_sources"]["coverage"]["rss"]["reason"] == reason
    assert result["counts"]["rss_analyzed"] == 0


def test_source_missing_fields_remain_unknown_and_identity_stable():
    entry = {"item_id": 7, "title": "same"}
    a = ai._analysis_source(entry, "hotlist")
    b = ai._analysis_source({**entry, "title": "renamed"}, "hotlist")
    assert a["id"] == b["id"]
    assert a["source_name"] is None and a["published_at"] is None and a["original_url"] is None


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,test", "//example.com", "https://u:p@example.com", "https://example.com\\@evil.com", "https://example.com\n/path", "https://[", "http://example.com:bad"])
def test_unsafe_original_url_is_not_exposed(url):
    assert ai._analysis_source(item("unsafe", url=url), "hotlist")["original_url"] is None


def test_metadata_changes_fingerprint_without_changing_prompt():
    a, text_a, _ = ai._prepare_analysis_facts({"items": [item("same")]})
    b, text_b, _ = ai._prepare_analysis_facts({"items": [item("same", url="https://example.com/changed")]})
    assert text_a == text_b
    assert ai.compute_ai_input_fingerprint("analysis", a, "p", "m", "v") != ai.compute_ai_input_fingerprint("analysis", b, "p", "m", "v")


def test_legacy_cache_not_filled_from_current_candidates():
    old = {"status": "SUCCESS", "core_trends": "old"}
    with patch.object(ai.store, "find_cached_ai_artifact", return_value={"payload": old, "artifact_id": "old-id"}), patch.object(ai, "invoke_llm_text") as invoke:
        result = ai.analyze_report({"items": [item("new")]}, cfg=CFG)
    assert "input_sources" not in result
    assert result["core_trends"] == "old"
    invoke.assert_not_called()


def test_cached_snapshot_immutable_and_matches_saved_artifact():
    original = run({"items": [item("old")]})
    with patch.object(ai.store, "find_cached_ai_artifact", return_value={"payload": original, "artifact_id": original["artifact_id"]}):
        cached = ai.analyze_report({"items": [item("current")]}, cfg=CFG)
    assert cached["input_sources"] == original["input_sources"]
    assert cached["input_sources"]["items"][0]["title"] == "old"


def test_invocation_error_does_not_claim_submitted_or_success():
    def fail(*_):
        raise RuntimeError("offline fixture")
    result = run({"items": [item("prepared")]}, fail)
    assert result["status"] == "ERROR"
    assert result["input_sources"]["submission_status"] == "UNKNOWN"
    assert result["core_trends"] == ""


def test_invalid_response_and_repair_not_successful():
    result = run({"items": [item("sent")]}, lambda *_: "not json")
    assert result["status"] == "ERROR"
    assert result["input_sources"]["submission_status"] == "RESPONSE_RECEIVED"
    assert result["core_trends"] == ""


def test_standalone_failure_is_unknown_not_empty_success():
    with patch("native_intel_service.get_standalone_items", side_effect=RuntimeError("offline")):
        result = run({"items": []}, include_standalone=True)
    coverage = result["input_sources"]["coverage"]["standalone"]
    assert coverage["available"] is None and coverage["omitted"] is None
    assert coverage["reason"] == "source_unavailable"


def test_malformed_standalone_total_keeps_selected_count_honest():
    with patch("native_intel_service.get_standalone_items", return_value={"items": [item("selected")], "total": "invalid"}):
        result = run({"items": []}, include_standalone=True)
    assert result["counts"]["standalone_analyzed"] == 1
    assert result["input_sources"]["coverage"]["standalone"]["included"] == 1
    assert result["input_sources"]["coverage"]["standalone"]["available"] is None
