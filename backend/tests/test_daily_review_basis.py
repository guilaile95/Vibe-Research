"""Actual context binding and strict v1/v2 persistence; synthetic inputs only."""
import copy
import hashlib
import json

import pytest
import daily_review_basis as basis
import daily_review_context
import ai_result_service as service
import ai_result_store as store


def review():
    return {"schema_version": "daily-review-v0.1", "trade_date": "2026-07-23", "generated_at": "2026-07-23 15:30:00",
            "data_cutoff": "2026-07-23 15:00:00", "status": "partial", "data_health": {"components": {"breadth": "partial"}},
            "warnings": ["do not retain provider error /private/path"], "market_environment": {}}


def captured():
    r = review()
    text = daily_review_context.render_daily_review_ai_context(r)
    return r, text, basis.capture_basis(text, r)


def validate(b, r):
    return basis.validate_basis(b, trade_date=r["trade_date"], source_generated_at=r["generated_at"], source_cutoff=r["data_cutoff"])


def test_basis_binds_exact_context_and_does_not_persist_arbitrary_strings():
    r, text, b = captured()
    assert b["context_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert b["component_statuses"]["breadth"] == "partial"
    assert b["component_statuses"]["emotion"] == "unknown"
    assert b["warning_count"] == 1
    assert b["unknown_count"] > 0
    assert "private/path" not in json.dumps(b)
    r["trade_date"] = "2026-07-24"
    r["warnings"].clear()
    assert b["trade_date"] == "2026-07-23" and b["warning_count"] == 1
    changed = json.loads(text); changed["data_health"]["components"]["provider private/path"] = "raw error"
    changed["unknowns"] = ["untrusted text"] * 30
    b2 = basis.capture_basis(json.dumps(changed), review())
    assert b2["omitted_component_count"] == 1 and b2["unknown_count"] == 30
    assert "untrusted" not in json.dumps(b2) and "private/path" not in json.dumps(b2)


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(extra="unexpected"), lambda b: b.update(schema_version="future"),
    lambda b: b.update(context_sha256="bad"), lambda b: b.update(warning_count=True),
    lambda b: b.update(unknown_count=-1), lambda b: b.update(omitted_component_count=10001),
    lambda b: b.update(review_status=[]), lambda b: b.update(trade_date="2026-07-24"),
    lambda b: b.update(source_data_cutoff=None), lambda b: b.update(source_review_generated_at="invalid"),
    lambda b: b["component_statuses"].update(private="normal"),
    lambda b: b["component_statuses"].update(breadth="healthy"),
    lambda b: b.update(review_schema_version="/private/path"),
])
def test_malformed_basis_rejected(mutate):
    r, _, b = captured(); mutate(b)
    with pytest.raises(ValueError): validate(b, r)


@pytest.mark.parametrize("text", ["{}", "[]", '{"schema_version":1,"schema_version":2}', '{"n":NaN}', "[" * 40 + "0" + "]" * 40, "x" * (basis.MAX_CONTEXT_BYTES + 1)], ids=["empty-object", "array", "duplicate-schema", "nonfinite", "deep-nesting", "oversized-context"])
def test_invalid_or_oversized_context_fails(text):
    with pytest.raises(ValueError): basis.capture_basis(text, review())


def test_v2_roundtrip_and_legacy_remain_distinct(tmp_path, monkeypatch):
    monkeypatch.setattr(service.review_history, "resolve_review_db_path", lambda: tmp_path / "ai.sqlite3")
    r, _, b = captured()
    legacy = service.save_daily_review_ai(r, "legacy", {"model": "synthetic"})
    assert legacy["schema_version"] == "daily_review_ai.v1"
    service._validate_restored_record(legacy, "daily_review_ai")
    new = service.save_daily_review_ai(r, "new", {"model": "synthetic"}, input_basis=b)
    assert new["schema_version"] == "daily_review_ai.v2"
    assert new["input_fingerprint"] == b["context_sha256"]
    service._validate_restored_record(new, "daily_review_ai")
    restored = service.get_ai_result("daily_review_ai", trade_date=r["trade_date"])
    assert restored["payload"]["input_basis"] == b
    b["warning_count"] = 99
    assert store.get_result(tmp_path / "ai.sqlite3", "daily_review_ai", r["trade_date"])["payload"]["input_basis"]["warning_count"] == 1
    for mutate in [lambda x: x["payload"].pop("input_basis"), lambda x: x.update(input_fingerprint="0" * 64),
                   lambda x: x["payload"]["input_basis"].update(trade_date="2026-07-24"),
                   lambda x: x.update(schema_version="daily_review_ai.v1")]:
        bad = copy.deepcopy(new); mutate(bad)
        with pytest.raises(service.AiResultCorruptedError): service._validate_restored_record(bad, "daily_review_ai")
    legacy["payload"]["input_basis"] = new["payload"]["input_basis"]
    with pytest.raises(service.AiResultCorruptedError): service._validate_restored_record(legacy, "daily_review_ai")


def test_invalid_new_basis_never_overwrites_existing_row(tmp_path, monkeypatch):
    path = tmp_path / "ai.sqlite3"
    monkeypatch.setattr(service.review_history, "resolve_review_db_path", lambda: path)
    r, _, b = captured(); service.save_daily_review_ai(r, "old", {"model": "synthetic"})
    b["warning_count"] = -1
    with pytest.raises(service.AiResultValidationError): service.save_daily_review_ai(r, "bad", {"model": "synthetic"}, input_basis=b)
    assert store.get_result(path, "daily_review_ai", r["trade_date"])["payload"]["markdown"] == "old"


@pytest.mark.parametrize("stamp", ["2026-07-23T12:00:00+01:60", "2026-07-23T12:00:00+00:99", "2026-07-23T12:00:00-01:60"])
def test_v2_rejects_normalized_timezone_offsets(stamp):
    r, _, b = captured()
    r["generated_at"] = b["source_review_generated_at"] = stamp
    with pytest.raises(ValueError): validate(b, r)
