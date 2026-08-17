"""P0-ET1 R1 adversarial contract tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
import decision_evidence_delta_projection as ec1
import evidence_effective_time_authority as authority
import evidence_thesis_service as evidence_service
import evidence_thesis_store as evidence_store


BASE = "2025-01-01T00:00:00.000000Z"
LATER = "2025-01-02T00:00:00.000000Z"
EVIDENCE_ID = "a" * 32


def _evidence() -> dict:
    return {"id": EVIDENCE_ID, "subject_type": "stock", "subject_id": "600519"}


def _row(**overrides) -> dict:
    row = {"evidence_id": EVIDENCE_ID}
    row.update(overrides)
    return row


def _evidence_payload() -> dict:
    return {
        "subject_type": "stock", "subject_id": "600519", "evidence_type": "news",
        "claim": "claim", "source_title": "source", "source_url": None,
        "source_date": None, "accessed_at": "2025-01-01T00:00:00+00:00",
        "classification": "fact", "confidence": "high",
    }


def _create_evidence(db: Path) -> dict:
    evidence_store.initialize_store(db)
    return evidence_service.create_evidence(db, _evidence_payload())


def test_public_source_metadata_never_proves_authority():
    result = authority.evaluate_temporal_authority(
        _evidence(), ({"evidence_id": EVIDENCE_ID, "source_identity": "fake", "source_published_at": BASE},)
    )
    assert result.temporal_state == authority.UNPROVEN
    assert result.effective_at is None
    assert result.temporal_basis == authority.NONE
    assert result.authority_refs == ()
    assert result.ec1_evaluation == authority.NOT_EVALUATED
    assert result.ec1_safe_item is not None
    assert result.ec1_safe_item.effective_at is None


def test_public_event_metadata_never_proves_authority():
    result = authority.evaluate_temporal_authority(
        _evidence(), ({"evidence_id": EVIDENCE_ID, "event_identity": "fake-event", "event_occurred_at": BASE},)
    )
    assert result.temporal_state == authority.UNPROVEN
    assert result.effective_at is None
    assert result.authority_refs == ()


def test_public_identity_text_cannot_generate_authority_ref():
    result = authority.evaluate_temporal_authority(
        _evidence(), ({"evidence_id": EVIDENCE_ID, "source_identity": "authority_refs=trusted", "source_published_at": BASE},)
    )
    assert result.authority_refs == ()
    assert result.temporal_state == authority.UNPROVEN


def test_no_as_of_can_never_be_evaluated():
    result = authority.evaluate_temporal_authority(
        _evidence(), ({"evidence_id": EVIDENCE_ID, "source_identity": "fake", "source_published_at": BASE},)
    )
    assert result.ec1_evaluation == authority.NOT_EVALUATED


def test_explicit_as_of_does_not_bypass_missing_trusted_producer():
    result = authority.evaluate_temporal_authority(
        _evidence(), ({"evidence_id": EVIDENCE_ID, "source_identity": "fake", "source_published_at": BASE},),
        evaluation_as_of=LATER,
    )
    assert authority.PROVEN_PRODUCTION_PATH == "NOT_IMPLEMENTED"
    assert result.temporal_state == authority.UNPROVEN
    assert result.ec1_evaluation == authority.NOT_EVALUATED


def test_observed_created_ingested_remain_non_authoritative():
    result = authority.evaluate_temporal_authority(
        _evidence(), (_row(observed_at=LATER, created_at=LATER, ingested_at=LATER),)
    )
    assert result.temporal_state == authority.UNPROVEN
    assert result.effective_at is None
    assert "OBSERVED_TIME_NOT_EFFECTIVE_TIME" in result.reason_codes
    assert "CREATED_TIME_NOT_EFFECTIVE_TIME" in result.reason_codes
    assert "INGESTED_TIME_NOT_EFFECTIVE_TIME" in result.reason_codes


def test_malformed_timestamp_is_rejected_before_write_and_api_returns_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "evidence.db"
    created = _create_evidence(db)
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(db))
    client = TestClient(app_module.app)
    valid = client.post(
        f"/api/evidence/{created['id']}/temporal-authority",
        json={"observed_at": BASE},
    )
    assert valid.status_code == 200
    with sqlite3.connect(db) as conn:
        before = conn.execute("SELECT COUNT(*) FROM evidence_temporal_intakes").fetchone()[0]
    malformed = client.post(
        f"/api/evidence/{created['id']}/temporal-authority",
        json={"source_identity": "fake", "source_published_at": "2025-02-30T00:00:00.000000Z"},
    )
    assert malformed.status_code == 422
    with sqlite3.connect(db) as conn:
        after = conn.execute("SELECT COUNT(*) FROM evidence_temporal_intakes").fetchone()[0]
    assert after == before


def test_tampered_source_timestamp_fails_closed(tmp_path: Path):
    db = tmp_path / "evidence.db"
    created = _create_evidence(db)
    authority.record_temporal_intake(
        authority.TemporalIntake(created["id"], source_identity="asserted", source_published_at=BASE),
        db_path=db,
    )
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE evidence_temporal_intakes SET source_published_at = ?", (LATER,))
        conn.commit()
    with pytest.raises(authority.TemporalAuthorityCorruptedError):
        authority.get_temporal_authority(created["id"], db_path=db)


def test_tampered_payload_hash_fails_closed(tmp_path: Path):
    db = tmp_path / "evidence.db"
    created = _create_evidence(db)
    authority.record_temporal_intake(
        authority.TemporalIntake(created["id"], observed_at=BASE), db_path=db
    )
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE evidence_temporal_intakes SET payload_hash = ?", ("0" * 64,))
        conn.commit()
    with pytest.raises(authority.TemporalAuthorityCorruptedError):
        authority.get_temporal_authority(created["id"], db_path=db)


def test_wrong_schema_version_row_fails_closed(tmp_path: Path):
    db = tmp_path / "evidence.db"
    created = _create_evidence(db)
    authority.record_temporal_intake(
        authority.TemporalIntake(created["id"], observed_at=BASE), db_path=db
    )
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE evidence_temporal_intakes SET schema_version = 'wrong'")
        conn.commit()
    with pytest.raises(authority.TemporalAuthorityCorruptedError):
        authority.get_temporal_authority(created["id"], db_path=db)


def test_malformed_existing_companion_schema_fails_closed_without_repair(tmp_path: Path):
    db = tmp_path / "evidence.db"
    created = _create_evidence(db)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE evidence_temporal_intakes (evidence_id TEXT)")
        conn.commit()
    with pytest.raises(authority.TemporalAuthorityCorruptedError):
        authority.get_temporal_authority(created["id"], db_path=db)
    with sqlite3.connect(db) as conn:
        assert [row[1] for row in conn.execute("PRAGMA table_info(evidence_temporal_intakes)")] == ["evidence_id"]


def test_missing_required_index_fails_closed(tmp_path: Path):
    db = tmp_path / "evidence.db"
    created = _create_evidence(db)
    with sqlite3.connect(db) as conn:
        conn.executescript(authority._CREATE_TEMPORAL_TABLE)
        conn.execute("DROP INDEX IF EXISTS idx_evidence_temporal_intakes_evidence")
        conn.commit()
    with pytest.raises(authority.TemporalAuthorityCorruptedError):
        authority.record_temporal_intake(
            authority.TemporalIntake(created["id"], observed_at=BASE), db_path=db
        )


def test_destructive_trigger_is_rejected_before_mutation(tmp_path: Path):
    db = tmp_path / "evidence.db"
    created = _create_evidence(db)
    old = authority.TemporalIntake(created["id"], observed_at=BASE)
    authority.record_temporal_intake(old, db_path=db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TRIGGER destructive_temporal_insert
            BEFORE INSERT ON evidence_temporal_intakes
            BEGIN
                DELETE FROM evidence_temporal_intakes;
            END
            """
        )
        conn.commit()
    new = authority.TemporalIntake(created["id"], observed_at=LATER)
    with pytest.raises(authority.TemporalAuthorityCorruptedError):
        authority.record_temporal_intake(new, db_path=db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM evidence_temporal_intakes").fetchone()[0] == 1
        assert conn.execute("SELECT observed_at FROM evidence_temporal_intakes").fetchone()[0] == BASE


def test_corrupt_existing_row_different_intake_is_zero_write(tmp_path: Path):
    db = tmp_path / "evidence.db"
    created = _create_evidence(db)
    authority.record_temporal_intake(
        authority.TemporalIntake(created["id"], observed_at=BASE), db_path=db
    )
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE evidence_temporal_intakes SET observed_at = ?", (LATER,))
        conn.commit()
    with pytest.raises(authority.TemporalAuthorityCorruptedError):
        authority.record_temporal_intake(
            authority.TemporalIntake(created["id"], ingested_at=LATER), db_path=db
        )
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM evidence_temporal_intakes").fetchone()[0] == 1


def test_corrupt_existing_row_idempotent_path_fails_closed(tmp_path: Path):
    db = tmp_path / "evidence.db"
    created = _create_evidence(db)
    intake = authority.TemporalIntake(created["id"], observed_at=BASE)
    authority.record_temporal_intake(intake, db_path=db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE evidence_temporal_intakes SET observed_at = ?", (LATER,))
        conn.commit()
    with pytest.raises(authority.TemporalAuthorityCorruptedError):
        authority.record_temporal_intake(intake, db_path=db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM evidence_temporal_intakes").fetchone()[0] == 1


def test_same_exact_factual_intake_is_idempotent_and_public_unproven(tmp_path: Path):
    db = tmp_path / "evidence.db"
    created = _create_evidence(db)
    intake = authority.TemporalIntake(
        created["id"], source_identity="asserted", source_published_at=BASE, observed_at=LATER
    )
    authority.record_temporal_intake(intake, db_path=db)
    authority.record_temporal_intake(intake, db_path=db)
    result = authority.get_temporal_authority(created["id"], db_path=db)
    assert result is not None
    assert result.temporal_state == authority.UNPROVEN
    assert result.ec1_evaluation == authority.NOT_EVALUATED
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM evidence_temporal_intakes").fetchone()[0] == 1


def test_valid_new_intake_appends_normally(tmp_path: Path):
    db = tmp_path / "evidence.db"
    created = _create_evidence(db)
    authority.record_temporal_intake(
        authority.TemporalIntake(created["id"], observed_at=BASE), db_path=db
    )
    authority.record_temporal_intake(
        authority.TemporalIntake(created["id"], observed_at=LATER), db_path=db
    )
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM evidence_temporal_intakes").fetchone()[0] == 2


def test_conflicting_public_metadata_has_no_authority_winner(tmp_path: Path):
    db = tmp_path / "evidence.db"
    created = _create_evidence(db)
    authority.record_temporal_intake(
        authority.TemporalIntake(created["id"], source_identity="a", source_published_at=BASE), db_path=db
    )
    authority.record_temporal_intake(
        authority.TemporalIntake(created["id"], event_identity="b", event_occurred_at=LATER), db_path=db
    )
    result = authority.get_temporal_authority(created["id"], db_path=db)
    assert result is not None
    assert result.temporal_state == authority.UNPROVEN
    assert result.authority_refs == ()


def test_existing_evidence_crud_is_unaffected(tmp_path: Path):
    db = tmp_path / "evidence.db"
    created = _create_evidence(db)
    updated = evidence_service.update_evidence(db, created["id"], {
        **{key: created[key] for key in ("evidence_type", "claim", "source_title", "source_url", "source_date", "classification", "confidence")},
        "accessed_at": created["accessed_at"],
    })
    assert updated["id"] == created["id"]


def test_existing_ec1_regression_stays_green():
    context = ec1.DecisionContext(
        security_code="600519", strategy="SWING", campaign_id="campaign_" + "b" * 32,
        decision_id="decision_" + "c" * 32, decision_boundary_at=BASE,
    )
    item = ec1.NormalizedEvidenceItem(
        evidence_id=EVIDENCE_ID, scope_kind=ec1.SCOPE_SECURITY, scope_id="600519",
        effective_at=None, retrieved_at=LATER, time_semantics=ec1.TIME_SEMANTICS_UNKNOWN,
        authority_refs=(),
    )
    delta = ec1.project_decision_evidence_delta(context=context, evidence_items=(item,))
    assert delta.new_evidence == ()
    assert delta.unknown_temporal_evidence == (EVIDENCE_ID,)
