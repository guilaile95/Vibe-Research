from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import decision_challenge_router

import decision_challenge_projection as domain
import decision_challenge_runtime as challenge_runtime
import decision_challenge_store as challenge_store
import decision_commit_runtime as runtime

from test_decision_commit_runtime import (
    AS_OF,
    CAMPAIGN_ID,
    THESIS_ID,
    _critical_data,
    _draft,
    _ports,
    _thesis,
)

FINALIZED_AT = "2026-08-16T00:00:01.000000Z"
CHALLENGE_ID = "decision_challenge_" + "d" * 32


def _dimensions(*, unknown: str | None = "PRE_MORTEM") -> dict:
    rows = {
        "STRONGEST_SUPPORTING_EVIDENCE": {
            "status": "ANSWERED",
            "text": "财报与渠道数据支持当前等待判断",
        },
        "STRONGEST_OPPOSING_EVIDENCE": {
            "status": "ANSWERED",
            "text": "估值仍不便宜，存在下修空间",
        },
        "PRE_MORTEM": {
            "status": "ANSWERED",
            "text": "若渠道库存失真，等待会被证明过早",
        },
        "INVALIDATION_FACTS": {
            "status": "ANSWERED",
            "text": "连续两个季度毛利率下修则本判断失效",
        },
    }
    if unknown:
        rows[unknown] = {"status": "UNKNOWN", "text": "尚未看到足够的失效路径样本"}
    return rows


def _packet(**overrides) -> dict:
    packet = domain.project_challenge_packet(
        challenge_id=overrides.pop("challenge_id", CHALLENGE_ID),
        security_code=overrides.pop("security_code", "600519"),
        strategy=overrides.pop("strategy", "SWING"),
        campaign_id=overrides.pop("campaign_id", CAMPAIGN_ID),
        thesis_id=overrides.pop("thesis_id", THESIS_ID),
        thesis_revision=overrides.pop("thesis_revision", 1),
        proposal_fingerprint=overrides.pop("proposal_fingerprint", "a" * 64),
        proposal_as_of=overrides.pop("proposal_as_of", AS_OF),
        finalized_at=overrides.pop("finalized_at", FINALIZED_AT),
        user_dimensions=overrides.pop("user_dimensions", _dimensions()),
    )
    packet.update(overrides)
    return packet


def _finalize_payload(preview: dict, **overrides) -> dict:
    payload = {
        **_draft(),
        "as_of": preview["proposal"]["as_of"],
        "expected_proposal_fingerprint": preview["proposal_fingerprint"],
        "user_confirmed": True,
        "dimensions": _dimensions(),
    }
    payload.update(overrides)
    return payload


def _challenge_ports(commit_ports, tmp_path: Path, **overrides):
    db_path = tmp_path / "decision_challenges.sqlite3"

    def append(packet):
        return challenge_store.append_challenge(packet, db_path=db_path)

    def reader(challenge_id):
        return challenge_store.get_challenge(challenge_id, db_path=db_path)

    def fingerprint_reader(fingerprint):
        return challenge_store.get_challenge_by_fingerprint(fingerprint, db_path=db_path)

    return challenge_runtime.ChallengePorts(
        preview=lambda campaign_id, payload, as_of=None: runtime.preview_decision_proposal(
            campaign_id, payload, ports=commit_ports, as_of=as_of or AS_OF
        ),
        append=overrides.get("append", append),
        reader=overrides.get("reader", reader),
        fingerprint_reader=overrides.get("fingerprint_reader", fingerprint_reader),
        clock=overrides.get("clock", lambda: FINALIZED_AT),
        new_id=overrides.get("new_id", lambda: CHALLENGE_ID),
    ), db_path


def test_caller_cannot_submit_identity_or_proposal_fields():
    with pytest.raises(domain.DecisionChallengeValidationError):
        domain.normalize_user_dimensions(
            {
                **_dimensions(),
                "STRONGEST_SUPPORTING_EVIDENCE": {
                    "status": "ANSWERED",
                    "text": "ok",
                    "security_code": "600519",
                },
            }
        )


def test_caller_cannot_submit_dimension_evaluation_or_authority_refs():
    with pytest.raises(domain.DecisionChallengeValidationError, match="evaluation or authority"):
        domain.normalize_user_dimensions(
            {
                **_dimensions(),
                "PRE_MORTEM": {
                    "status": "ANSWERED",
                    "text": "ok",
                    "evaluation": "EVALUATED",
                    "authority_refs": ["caller:declared"],
                },
            }
        )


def test_missing_dimension_is_rejected():
    rows = _dimensions()
    del rows["INVALIDATION_FACTS"]
    with pytest.raises(domain.DecisionChallengeValidationError, match="missing dimensions"):
        domain.normalize_user_dimensions(rows)


def test_answered_empty_text_is_rejected():
    rows = _dimensions()
    rows["STRONGEST_SUPPORTING_EVIDENCE"] = {"status": "ANSWERED", "text": "   "}
    with pytest.raises(domain.DecisionChallengeValidationError, match="non-empty text"):
        domain.normalize_user_dimensions(rows)


def test_explicit_unknown_is_coverage_not_positive_evidence():
    packet = _packet()
    assert packet["packet_state"] == "COMPLETE"
    assert packet["challenge_evaluation"] == "UNKNOWN"
    assert "PRE_MORTEM" in packet["unknown_dimensions"]
    assert "PRE_MORTEM" in packet["covered_dimensions"]
    assert packet["dimension_results"]["PRE_MORTEM"]["positive_evidence"] is False
    assert packet["dimension_results"]["STRONGEST_SUPPORTING_EVIDENCE"]["positive_evidence"] is True
    assert packet["decision_quality"] == "NOT_EVALUATED"
    assert packet["two_pass_semantic_independence_verified"] == "NO"
    assert packet["authority_refs"] == [
        domain.AUTHORITY_REF,
        f"decision_challenge:{CHALLENGE_ID}",
        f"decision_proposal:{'a' * 64}",
        f"decision_challenge:{CHALLENGE_ID}:STRONGEST_SUPPORTING_EVIDENCE",
        f"decision_challenge:{CHALLENGE_ID}:STRONGEST_OPPOSING_EVIDENCE",
        f"decision_challenge:{CHALLENGE_ID}:PRE_MORTEM",
        f"decision_challenge:{CHALLENGE_ID}:INVALIDATION_FACTS",
    ]


def test_stale_proposal_fingerprint_is_zero_write(tmp_path):
    commit_ports, state = _ports(_thesis())
    challenge_ports, db_path = _challenge_ports(commit_ports, tmp_path)
    preview = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=commit_ports, as_of=AS_OF
    )
    writes = {"count": 0}

    def counting_append(packet):
        writes["count"] += 1
        return challenge_store.append_challenge(packet, db_path=db_path)

    challenge_ports = challenge_runtime.ChallengePorts(
        preview=challenge_ports.preview,
        append=counting_append,
        reader=challenge_ports.reader,
        fingerprint_reader=challenge_ports.fingerprint_reader,
        clock=challenge_ports.clock,
        new_id=challenge_ports.new_id,
    )
    payload = _finalize_payload(preview, expected_proposal_fingerprint="b" * 64)
    with pytest.raises(challenge_runtime.DecisionChallengeStaleError):
        challenge_runtime.finalize_decision_challenge(
            CAMPAIGN_ID, payload, ports=challenge_ports
        )
    assert writes["count"] == 0
    assert challenge_store.get_challenge_by_fingerprint(
        preview["proposal_fingerprint"], db_path=db_path
    ) is None


@pytest.mark.parametrize(
    "override",
    [
        {"as_of": "2026-08-17T00:00:00.000000Z"},
        {"trade_view": {"view": "TRADE", "stance": "REDUCE"}},
    ],
)
def test_changed_as_of_or_draft_is_stale_zero_write(tmp_path, override):
    commit_ports, _state = _ports(_thesis())
    challenge_ports, db_path = _challenge_ports(commit_ports, tmp_path)
    preview = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=commit_ports, as_of=AS_OF
    )
    writes = {"count": 0}

    def counting_append(packet):
        writes["count"] += 1
        return challenge_store.append_challenge(packet, db_path=db_path)

    challenge_ports = challenge_runtime.ChallengePorts(
        preview=challenge_ports.preview,
        append=counting_append,
        reader=challenge_ports.reader,
        fingerprint_reader=challenge_ports.fingerprint_reader,
        clock=challenge_ports.clock,
        new_id=challenge_ports.new_id,
    )
    changed_payload = _finalize_payload(preview)
    changed_payload.update(override)
    with pytest.raises(challenge_runtime.DecisionChallengeStaleError):
        challenge_runtime.finalize_decision_challenge(
            CAMPAIGN_ID, changed_payload, ports=challenge_ports
        )
    assert writes["count"] == 0
    assert not db_path.exists()


def test_stale_thesis_revision_is_zero_write(tmp_path):
    thesis = _thesis()
    commit_ports, _state = _ports(thesis)
    challenge_ports, db_path = _challenge_ports(commit_ports, tmp_path)
    preview = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=commit_ports, as_of=AS_OF
    )
    thesis["frozen_revision"] = 2
    writes = {"count": 0}

    def counting_append(packet):
        writes["count"] += 1
        return packet

    challenge_ports = challenge_runtime.ChallengePorts(
        preview=challenge_ports.preview,
        append=counting_append,
        reader=challenge_ports.reader,
        fingerprint_reader=challenge_ports.fingerprint_reader,
        clock=challenge_ports.clock,
        new_id=challenge_ports.new_id,
    )
    with pytest.raises(challenge_runtime.DecisionChallengeStaleError):
        challenge_runtime.finalize_decision_challenge(
            CAMPAIGN_ID, _finalize_payload(preview), ports=challenge_ports
        )
    assert writes["count"] == 0
    assert not db_path.exists()


def test_preview_identity_is_backend_derived(tmp_path):
    commit_ports, _state = _ports(_thesis())
    challenge_ports, _db = _challenge_ports(commit_ports, tmp_path)
    preview = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=commit_ports, as_of=AS_OF
    )
    result = challenge_runtime.finalize_decision_challenge(
        CAMPAIGN_ID, _finalize_payload(preview), ports=challenge_ports
    )
    packet = result["challenge"]
    assert packet["security_code"] == "600519"
    assert packet["strategy"] == "SWING"
    assert packet["campaign_id"] == CAMPAIGN_ID
    assert packet["thesis_id"] == THESIS_ID
    assert packet["thesis_revision"] == 1
    assert packet["proposal_fingerprint"] == preview["proposal_fingerprint"]
    assert packet["proposal_as_of"] == AS_OF


def test_exact_replay_finalization_returns_existing_packet(tmp_path):
    commit_ports, _state = _ports(_thesis())
    challenge_ports, _db = _challenge_ports(commit_ports, tmp_path)
    preview = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=commit_ports, as_of=AS_OF
    )
    first = challenge_runtime.finalize_decision_challenge(
        CAMPAIGN_ID, _finalize_payload(preview), ports=challenge_ports
    )
    second = challenge_runtime.finalize_decision_challenge(
        CAMPAIGN_ID, _finalize_payload(preview), ports=challenge_ports
    )
    assert second["challenge"]["challenge_id"] == first["challenge"]["challenge_id"]
    assert second["challenge"]["packet_hash"] == first["challenge"]["packet_hash"]
    assert second["challenge"]["finalized_at"] == first["challenge"]["finalized_at"]


def test_conflicting_replay_same_fingerprint_fails_closed(tmp_path):
    commit_ports, _state = _ports(_thesis())
    challenge_ports, _db = _challenge_ports(commit_ports, tmp_path)
    preview = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=commit_ports, as_of=AS_OF
    )
    challenge_runtime.finalize_decision_challenge(
        CAMPAIGN_ID, _finalize_payload(preview), ports=challenge_ports
    )
    changed = _finalize_payload(preview)
    changed["dimensions"]["STRONGEST_SUPPORTING_EVIDENCE"] = {
        "status": "ANSWERED",
        "text": "完全不同的挑战内容",
    }
    with pytest.raises(challenge_runtime.DecisionChallengeReplayConflictError):
        challenge_runtime.finalize_decision_challenge(
            CAMPAIGN_ID, changed, ports=challenge_ports
        )


def test_corrupt_packet_hash_fails_closed_on_read_and_commit(tmp_path, monkeypatch):
    commit_ports, state = _ports(_thesis())
    challenge_ports, db_path = _challenge_ports(commit_ports, tmp_path)
    preview = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=commit_ports, as_of=AS_OF
    )
    packet = domain.project_challenge_packet(
        challenge_id=CHALLENGE_ID,
        security_code="600519",
        strategy="SWING",
        campaign_id=CAMPAIGN_ID,
        thesis_id=THESIS_ID,
        thesis_revision=1,
        proposal_fingerprint=preview["proposal_fingerprint"],
        proposal_as_of=AS_OF,
        finalized_at=FINALIZED_AT,
        user_dimensions=_dimensions(),
    )
    challenge_store.append_challenge(packet, db_path=db_path)
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE decision_challenges SET packet_hash = ? WHERE challenge_id = ?",
        ("0" * 64, packet["challenge_id"]),
    )
    conn.commit()
    conn.close()
    with pytest.raises(challenge_store.DecisionChallengeStoreCorruptedError):
        challenge_store.get_challenge(packet["challenge_id"], db_path=db_path)
    monkeypatch.setattr(challenge_runtime, "PRODUCTION_PORTS", challenge_ports)
    with pytest.raises(runtime.ChallengeBindingError):
        runtime.commit_decision_proposal(
            CAMPAIGN_ID,
            {
                **_draft(),
                "as_of": AS_OF,
                "expected_proposal_fingerprint": preview["proposal_fingerprint"],
                "user_confirmed": True,
                "challenge_id": packet["challenge_id"],
            },
            ports=commit_ports,
        )
    assert state["writes"] == 0


def test_first_and_second_pass_are_server_derived():
    packet = _packet()
    assert packet["first_pass_ref"] == f"decision_proposal:{'a' * 64}"
    assert packet["first_pass_at"] == AS_OF
    assert packet["second_pass_ref"] == f"decision_challenge:{CHALLENGE_ID}"
    assert packet["second_pass_at"] == FINALIZED_AT
    assert packet["two_pass_state"] == "VALID"


def test_second_pass_before_first_pass_is_rejected():
    with pytest.raises(domain.DecisionChallengeValidationError, match="second_pass_at"):
        domain.project_challenge_packet(
            challenge_id=CHALLENGE_ID,
            security_code="600519",
            strategy="SWING",
            campaign_id=CAMPAIGN_ID,
            thesis_id=THESIS_ID,
            thesis_revision=1,
            proposal_fingerprint="a" * 64,
            proposal_as_of="2026-08-16T00:00:02.000000Z",
            finalized_at="2026-08-16T00:00:01.000000Z",
            user_dimensions=_dimensions(),
        )


def test_commit_without_challenge_retains_existing_behavior():
    ports, state = _ports(_thesis())
    preview = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF
    )
    result = runtime.commit_decision_proposal(
        CAMPAIGN_ID,
        {
            **_draft(),
            "as_of": AS_OF,
            "expected_proposal_fingerprint": preview["proposal_fingerprint"],
            "user_confirmed": True,
        },
        ports=ports,
    )
    assert result["committed"]["source_refs"] == [
        f"{runtime.PROPOSAL_SOURCE_PREFIX}{preview['proposal_fingerprint']}",
        *preview["proposal"]["authority_refs"],
    ]
    assert not any(
        str(item).startswith(runtime.CHALLENGE_SOURCE_PREFIX)
        for item in result["committed"]["source_refs"]
    )
    assert state["writes"] == 1


def test_commit_with_valid_challenge_binds_server_source_ref(tmp_path, monkeypatch):
    commit_ports, state = _ports(_thesis(), committed_at=FINALIZED_AT)
    challenge_ports, _db = _challenge_ports(commit_ports, tmp_path)
    preview = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=commit_ports, as_of=AS_OF
    )
    finalized = challenge_runtime.finalize_decision_challenge(
        CAMPAIGN_ID, _finalize_payload(preview), ports=challenge_ports
    )
    monkeypatch.setattr(
        challenge_runtime,
        "PRODUCTION_PORTS",
        challenge_ports,
    )
    result = runtime.commit_decision_proposal(
        CAMPAIGN_ID,
        {
            **_draft(),
            "as_of": AS_OF,
            "expected_proposal_fingerprint": preview["proposal_fingerprint"],
            "user_confirmed": True,
            "challenge_id": finalized["challenge"]["challenge_id"],
        },
        ports=commit_ports,
    )
    assert (
        f"{runtime.CHALLENGE_SOURCE_PREFIX}{finalized['challenge']['challenge_id']}"
        in result["committed"]["source_refs"]
    )
    assert result["committed"]["next_best_action"] == preview["proposal"]["next_best_action"]
    assert result["committed"]["action_envelope"] == preview["proposal"]["action_envelope"]
    assert state["writes"] == 1
    repeat = runtime.commit_decision_proposal(
        CAMPAIGN_ID,
        {
            **_draft(),
            "as_of": AS_OF,
            "expected_proposal_fingerprint": preview["proposal_fingerprint"],
            "user_confirmed": True,
            "challenge_id": finalized["challenge"]["challenge_id"],
        },
        ports=commit_ports,
    )
    assert repeat["idempotent"] is True
    assert state["writes"] == 1


def test_challenge_finalized_after_commit_time_is_rejected_before_frozen_write(tmp_path, monkeypatch):
    commit_ports, state = _ports(_thesis(), committed_at=AS_OF)
    challenge_ports, _db = _challenge_ports(commit_ports, tmp_path)
    preview = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=commit_ports, as_of=AS_OF
    )
    finalized = challenge_runtime.finalize_decision_challenge(
        CAMPAIGN_ID,
        _finalize_payload(preview),
        ports=challenge_ports,
    )
    monkeypatch.setattr(challenge_runtime, "PRODUCTION_PORTS", challenge_ports)
    with pytest.raises(runtime.ChallengeBindingError, match="finalized_at"):
        runtime.commit_decision_proposal(
            CAMPAIGN_ID,
            {
                **_draft(),
                "as_of": AS_OF,
                "expected_proposal_fingerprint": preview["proposal_fingerprint"],
                "user_confirmed": True,
                "challenge_id": finalized["challenge"]["challenge_id"],
            },
            ports=commit_ports,
        )
    assert state["writes"] == 0


def test_commit_with_foreign_challenge_is_rejected_before_frozen_write(tmp_path, monkeypatch):
    commit_ports, state = _ports(_thesis())
    challenge_ports, _db = _challenge_ports(commit_ports, tmp_path)
    preview = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=commit_ports, as_of=AS_OF
    )
    other = domain.project_challenge_packet(
        challenge_id="decision_challenge_" + "e" * 32,
        security_code="600519",
        strategy="SWING",
        campaign_id="campaign_" + "f" * 32,
        thesis_id=THESIS_ID,
        thesis_revision=1,
        proposal_fingerprint=preview["proposal_fingerprint"],
        proposal_as_of=AS_OF,
        finalized_at=FINALIZED_AT,
        user_dimensions=_dimensions(),
    )
    challenge_store.append_challenge(other, db_path=_db)
    monkeypatch.setattr(challenge_runtime, "PRODUCTION_PORTS", challenge_ports)
    with pytest.raises(runtime.ChallengeBindingError):
        runtime.commit_decision_proposal(
            CAMPAIGN_ID,
            {
                **_draft(),
                "as_of": AS_OF,
                "expected_proposal_fingerprint": preview["proposal_fingerprint"],
                "user_confirmed": True,
                "challenge_id": other["challenge_id"],
            },
            ports=commit_ports,
        )
    assert state["writes"] == 0


def test_finalized_packet_cannot_be_mutated(tmp_path):
    packet = _packet()
    db_path = tmp_path / "decision_challenges.sqlite3"
    stored = challenge_store.append_challenge(packet, db_path=db_path)
    mutated = deepcopy(stored)
    mutated["dimension_results"]["PRE_MORTEM"]["text"] = "mutated after finalize"
    mutated["packet_hash"] = domain.compute_packet_hash(mutated)
    with pytest.raises(challenge_store.DecisionChallengeConflictError):
        challenge_store.append_challenge(mutated, db_path=db_path)
    reread = challenge_store.get_challenge(stored["challenge_id"], db_path=db_path)
    assert reread["dimension_results"]["PRE_MORTEM"]["text"] == stored["dimension_results"]["PRE_MORTEM"]["text"]


def test_challenge_content_does_not_alter_nba_or_authorities(tmp_path):
    commit_ports, _state = _ports(_thesis())
    challenge_ports, _db = _challenge_ports(commit_ports, tmp_path)
    preview = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=commit_ports, as_of=AS_OF
    )
    result = challenge_runtime.finalize_decision_challenge(
        CAMPAIGN_ID, _finalize_payload(preview), ports=challenge_ports
    )
    assert result["next_best_action"] == preview["proposal"]["next_best_action"]
    assert result["action_envelope"] == preview["proposal"]["action_envelope"]
    preview_authorities = json.dumps(
        preview["authority_evaluations"], sort_keys=True, default=str
    )
    result_authorities = json.dumps(
        result["authority_evaluations"], sort_keys=True, default=str
    )
    assert result_authorities == preview_authorities
    assert "decision_quality" not in preview["proposal"]
    assert result["decision_quality"] == "NOT_EVALUATED"
    for token in ("BUY NOW", "quality_score", "process_quality"):
        assert token not in json.dumps(result["challenge"])


def test_finalize_rejects_caller_declared_identity_fields(tmp_path):
    commit_ports, _state = _ports(_thesis())
    challenge_ports, _db = _challenge_ports(commit_ports, tmp_path)
    preview = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=commit_ports, as_of=AS_OF
    )
    payload = _finalize_payload(preview, security_code="600519")
    with pytest.raises(challenge_runtime.DecisionChallengeInputError, match="unknown finalize field"):
        challenge_runtime.finalize_decision_challenge(
            CAMPAIGN_ID, payload, ports=challenge_ports
        )


def test_replay_ignores_retrieval_timestamp_provenance_but_not_identity(tmp_path):
    calls = {"count": 0}

    def critical_data_reader(_campaign, as_of):
        calls["count"] += 1
        return {
            **_critical_data(
                authority_refs=[
                    f"disclosures:fetched_at=2026-08-17T00:00:{calls['count']:02d}.000000Z"
                ]
            ),
            "as_of": as_of,
        }

    commit_ports, _state = _ports(
        _thesis(), critical_data_reader=critical_data_reader
    )
    challenge_ports, db_path = _challenge_ports(commit_ports, tmp_path)
    preview = runtime.preview_decision_proposal(
        CAMPAIGN_ID, _draft(), ports=commit_ports, as_of=AS_OF
    )
    finalized = challenge_runtime.finalize_decision_challenge(
        CAMPAIGN_ID, _finalize_payload(preview), ports=challenge_ports
    )
    assert calls["count"] == 2
    assert finalized["challenge"]["proposal_fingerprint"] == preview["proposal_fingerprint"]
    assert challenge_store.get_challenge(
        finalized["challenge"]["challenge_id"], db_path=db_path
    ) is not None


def _create_store_schema_without_fingerprint_unique(db_path: Path, index_sql: str | None = None):
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO schema_meta(key, value) VALUES ('schema_version', 'decision-challenge-packet.v0.1');
        CREATE TABLE decision_challenges (
            challenge_id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            proposal_fingerprint TEXT NOT NULL,
            proposal_as_of TEXT NOT NULL,
            packet_hash TEXT NOT NULL,
            packet_json TEXT NOT NULL,
            finalized_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    if index_sql:
        conn.execute(index_sql)
    conn.commit()
    conn.close()


@pytest.mark.parametrize(
    "index_sql",
    [
        None,
        "CREATE UNIQUE INDEX partial_fingerprint ON decision_challenges(proposal_fingerprint) WHERE campaign_id IS NOT NULL",
        "CREATE INDEX non_unique_fingerprint ON decision_challenges(proposal_fingerprint)",
    ],
)
def test_store_requires_full_single_column_fingerprint_unique(tmp_path, index_sql):
    db_path = tmp_path / "malformed.sqlite3"
    _create_store_schema_without_fingerprint_unique(db_path, index_sql)
    with pytest.raises(challenge_store.DecisionChallengeStoreCorruptedError):
        challenge_store.get_challenge_by_fingerprint("a" * 64, db_path=db_path)


@pytest.mark.parametrize("column", ["campaign_id", "proposal_fingerprint", "proposal_as_of", "finalized_at"])
def test_store_rejects_row_redundant_field_mismatch(tmp_path, column):
    packet = _packet()
    db_path = tmp_path / "row-mismatch.sqlite3"
    challenge_store.append_challenge(packet, db_path=db_path)
    conn = sqlite3.connect(db_path)
    value = {
        "campaign_id": "campaign_" + "f" * 32,
        "proposal_fingerprint": "b" * 64,
        "proposal_as_of": "2026-08-16T00:00:02.000000Z",
        "finalized_at": "2026-08-16T00:00:02.000000Z",
    }[column]
    conn.execute(f"UPDATE decision_challenges SET {column} = ?", (value,))
    conn.commit()
    conn.close()
    with pytest.raises(challenge_store.DecisionChallengeStoreCorruptedError):
        challenge_store.get_challenge(packet["challenge_id"], db_path=db_path)


def test_store_rejects_noncanonical_created_at(tmp_path):
    packet = _packet()
    db_path = tmp_path / "created-at.sqlite3"
    challenge_store.append_challenge(packet, db_path=db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE decision_challenges SET created_at = ?",
        ("2026-08-16T00:00:01Z",),
    )
    conn.commit()
    conn.close()
    with pytest.raises(challenge_store.DecisionChallengeStoreCorruptedError):
        challenge_store.get_challenge(packet["challenge_id"], db_path=db_path)


def test_finalize_route_exposes_stale_status_and_body(monkeypatch):
    app = FastAPI()
    app.include_router(decision_challenge_router.router)

    def stale(*_args, **_kwargs):
        raise challenge_runtime.DecisionChallengeStaleError("fingerprint mismatch")

    monkeypatch.setattr(
        decision_challenge_router.runtime,
        "finalize_decision_challenge",
        stale,
    )
    payload = {
        "expected_proposal_fingerprint": "a" * 64,
        "as_of": AS_OF,
        "user_confirmed": True,
        "dimensions": _dimensions(),
        **_draft(),
    }
    response = TestClient(app).post(
        f"/api/campaigns/{CAMPAIGN_ID}/decision-challenge/finalize",
        json=payload,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Decision Proposal 已失效，请重新预览后再 Finalize Challenge"
    )
