from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

import decision_draft_service as service
import decision_draft_store as store
from app import app


CAMPAIGN_ID = "campaign_" + "a" * 32
THESIS_ID = "b" * 32
DRAFT_ID = "decision_draft_" + "c" * 32
FP = "d" * 64
AS_OF = "2026-08-24T00:00:00.000000Z"


def _payload() -> dict:
    return {
        "asset_view": {"view": "ASSET", "stance": "SUPPORT", "note": "需求仍有韧性"},
        "trade_view": {"view": "TRADE", "stance": "WAIT", "note": "等待验证条件"},
        "portfolio_view": {"view": "PORTFOLIO", "constraint": "不扩大当前风险暴露"},
        "key_assumptions": ["现金流继续覆盖投入"],
        "event_invalidation_conditions": ["核心需求连续两个观察期转弱"],
        "limitations": ["Critical Data 仍有 UNKNOWN 项"],
    }


def _record(**overrides) -> dict:
    value = {
        "schema_version": store.DRAFT_SCHEMA_VERSION,
        "draft_id": DRAFT_ID,
        "campaign_id": CAMPAIGN_ID,
        "security_code": "600519",
        "strategy": "SWING",
        "thesis_id": THESIS_ID,
        "thesis_revision": 1,
        "holding_fingerprint": FP,
        "context_fingerprint": "e" * 64,
        "context_as_of": AS_OF,
        "generated_at": AS_OF,
        "model_provider": "test-provider",
        "model_name": "test-model",
        "prompt_version": service.PROMPT_VERSION,
        "analysis_policy_version": service.ANALYSIS_POLICY_VERSION,
        "payload": _payload(),
    }
    value.update(overrides)
    return value


def test_store_append_only_roundtrip_and_missing_read_is_zero_write(tmp_path):
    db = tmp_path / "drafts.sqlite3"
    assert store.get(DRAFT_ID, db) is None
    assert not db.exists()

    saved = store.append(_record(), db)
    assert saved["record_hash"] == store.get(DRAFT_ID, db)["record_hash"]
    assert store.append(_record(), db) == saved

    with pytest.raises(store.DecisionDraftConflictError):
        store.append(_record(model_name="different-model"), db)


def test_store_fails_closed_on_tampered_record(tmp_path):
    db = tmp_path / "drafts.sqlite3"
    store.append(_record(), db)
    with sqlite3.connect(db) as conn:
        raw = json.loads(conn.execute(
            "SELECT record_json FROM decision_drafts WHERE draft_id = ?", (DRAFT_ID,)
        ).fetchone()[0])
        raw["payload"]["asset_view"]["note"] = "tampered"
        conn.execute(
            "UPDATE decision_drafts SET record_json = ? WHERE draft_id = ?",
            (json.dumps(raw, ensure_ascii=False), DRAFT_ID),
        )
    with pytest.raises(store.DecisionDraftCorruptedError):
        store.get(DRAFT_ID, db)


def test_model_contract_rejects_formal_authority_fields():
    malicious = {**_payload(), "next_best_action": "BUY NOW"}
    with pytest.raises(service.DecisionDraftModelOutputError):
        service.validate_model_payload(malicious)


def test_generation_persists_only_validated_draft_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_RESEARCH_DECISION_DRAFT_DB", str(tmp_path / "drafts.sqlite3"))
    monkeypatch.setattr(
        service,
        "_build_context",
        lambda _campaign_id: (
            {"safe": "server-owned-context"},
            {
                "campaign_id": CAMPAIGN_ID,
                "security_code": "600519",
                "strategy": "SWING",
                "thesis_id": THESIS_ID,
                "thesis_revision": 1,
                "holding_fingerprint": FP,
                "context_as_of": AS_OF,
                "context_fingerprint": "e" * 64,
            },
        ),
    )
    raw = json.dumps(_payload(), ensure_ascii=False)
    generated = service.generate_campaign_decision_draft(
        CAMPAIGN_ID,
        {
            "provider": "test-provider",
            "baseURL": "https://example.invalid/v1",
            "apiKey": "must-not-persist",
            "model": "test-model",
        },
        model_runner=lambda _cfg, _messages: raw,
    )
    reread = store.get(generated["draft_id"])
    assert reread is not None
    encoded = store.canonical_json(reread)
    assert "must-not-persist" not in encoded
    assert "example.invalid" not in encoded
    assert reread["payload"] == _payload()


def test_generate_api_rejects_client_context_injection():
    client = TestClient(app)
    response = client.post(
        f"/api/campaigns/{CAMPAIGN_ID}/decision-draft",
        json={
            "llm": {"provider": "x", "baseURL": "x", "apiKey": "x", "model": "m"},
            "context": {"next_best_action": "BUY NOW"},
        },
    )
    assert response.status_code == 422
