from __future__ import annotations

from decision_clock_fixtures import historical_decision_server_clock as _historical_decision_server_clock  # noqa: F401

import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import campaign_ai_draft_router
import campaign_ai_draft_service as draft_service
import decision_commit_router
import decision_commit_runtime as commit_runtime


CAMPAIGN_ID = "campaign_" + "a" * 32
THESIS_ID = "b" * 32
AS_OF = "2026-08-16T00:00:00.000000Z"


def _draft() -> dict:
    return {
        "asset_view": {"view": "ASSET", "stance": "WAIT"},
        "trade_view": {"view": "TRADE", "stance": "WAIT"},
        "portfolio_view": {"view": "PORTFOLIO", "constraint": "unknown"},
        "review_by": "2026-08-30T00:00:00.000000Z",
        "key_assumptions": ["assumption"],
        "event_invalidation_conditions": ["invalidation"],
        "strategy_horizon": "2 至 4 周",
    }


def _app(*routers) -> FastAPI:
    app = FastAPI()
    for router in routers:
        app.include_router(router.router)
    return app


def test_preview_route_accepts_optional_witness_and_forbids_unknown_fields(monkeypatch):
    witness = {
        "schema_version": "campaign_ai_draft.witness.v0.1",
        "draft_id": "campaign_ai_draft_" + "d" * 32,
        "campaign_id": CAMPAIGN_ID,
        "thesis_id": THESIS_ID,
        "thesis_revision": 1,
        "context_fingerprint": "a" * 64,
        "generated_fields": _draft(),
    }
    seen: dict = {}

    def preview(campaign_id, payload):
        seen["campaign_id"] = campaign_id
        seen["payload"] = payload
        return {"proposal_fingerprint": "a" * 64, "draft_witness": witness}

    monkeypatch.setattr(decision_commit_router.runtime, "preview_decision_proposal", preview)
    client = TestClient(_app(decision_commit_router))
    response = client.post(
        f"/api/campaigns/{CAMPAIGN_ID}/decision-proposal/preview",
        json={**_draft(), "draft_witness": witness},
    )
    assert response.status_code == 200
    assert seen["payload"]["draft_witness"] == witness

    extra = client.post(
        f"/api/campaigns/{CAMPAIGN_ID}/decision-proposal/preview",
        json={**_draft(), "unknown": True},
    )
    assert extra.status_code == 422
    assert "unknown" in extra.text


def test_preview_route_maps_stale_witness_to_409_before_any_write(monkeypatch):
    writes = {"campaign": 0, "formal": 0, "frozen": 0, "trade": 0}

    def stale(*_args, **_kwargs):
        raise commit_runtime.ProposalStaleError("witness context drift")

    monkeypatch.setattr(decision_commit_router.runtime, "preview_decision_proposal", stale)
    response = TestClient(_app(decision_commit_router)).post(
        f"/api/campaigns/{CAMPAIGN_ID}/decision-proposal/preview",
        json=_draft(),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Formal Decision Proposal 已失效，请重新预览"
    assert writes == {"campaign": 0, "formal": 0, "frozen": 0, "trade": 0}


@pytest.mark.parametrize("operation", ["preview", "commit"])
def test_decision_routes_map_terminal_campaign_to_stable_409(monkeypatch, operation):
    def terminal(*_args, **_kwargs):
        raise commit_runtime.TerminalCampaignDecisionConflictError("terminal")

    monkeypatch.setattr(
        decision_commit_router.runtime,
        f"{operation}_decision_proposal",
        terminal,
    )
    body = _draft()
    if operation == "commit":
        body = {
            **body,
            "as_of": AS_OF,
            "expected_proposal_fingerprint": "a" * 64,
            "user_confirmed": True,
        }
    response = TestClient(_app(decision_commit_router)).post(
        f"/api/campaigns/{CAMPAIGN_ID}/decision-proposal/{operation}",
        json=body,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "本轮研究已结束，历史记录仍可查看；如需形成新判断，请新建一轮研究。"
    )


def test_preview_runtime_rejects_non_strict_json_and_does_not_write():
    from test_decision_commit_runtime import _ports, _thesis

    ports, state = _ports(_thesis())
    payload = {**_draft(), "key_assumptions": [float("nan")]}
    with pytest.raises(commit_runtime.DecisionCommitInputError, match="strict JSON"):
        commit_runtime.preview_decision_proposal(
            CAMPAIGN_ID, payload, ports=ports, as_of=AS_OF
        )
    assert state["writes"] == 0


def test_campaign_ai_draft_generate_route_is_strict_and_ephemeral(monkeypatch):
    generated = {
        "schema_version": draft_service.SCHEMA_VERSION,
        "draft_status": "AI_DRAFT",
        "proposal_status": "UNCOMMITTED",
        "draft_id": "campaign_ai_draft_" + "d" * 32,
        "campaign_id": CAMPAIGN_ID,
        "thesis_id": THESIS_ID,
        "thesis_revision": 1,
        "context_fingerprint": "a" * 64,
        "generated_fields": _draft(),
        "draft_witness": {"draft_id": "campaign_ai_draft_" + "d" * 32},
    }
    monkeypatch.setitem(
        sys.modules,
        "app",
        SimpleNamespace(
            LLMConfig=SimpleNamespace(
                model_validate=lambda value: SimpleNamespace(
                    **value, model_dump=lambda: value,
                )
            ),
            _require_llm_ready=lambda _llm: False,
        ),
    )
    monkeypatch.setattr(
        campaign_ai_draft_router.service,
        "generate_ai_draft",
        lambda _cfg, campaign_id, **kwargs: generated,
    )
    client = TestClient(_app(campaign_ai_draft_router))
    response = client.post(
        f"/api/campaigns/{CAMPAIGN_ID}/ai-draft/generate",
        json={"llm": {"model": "test", "apiKey": "secret", "baseURL": "http://example.test"}, "confirm_private_context": True, "expected_context_fingerprint": "a" * 64},
    )
    assert response.status_code == 200
    assert response.json() == {"data": generated}

    invalid = client.post(
        f"/api/campaigns/{CAMPAIGN_ID}/ai-draft/generate",
        json={"llm": {"model": "test", "apiKey": "secret", "baseURL": "http://example.test", "extra": True}, "confirm_private_context": True, "expected_context_fingerprint": "a" * 64},
    )
    assert invalid.status_code == 422
    assert "secret" not in invalid.text


@pytest.mark.parametrize("confirm", [None, False, 1, "true"])
def test_private_context_confirmation_required_before_any_model(monkeypatch, confirm):
    monkeypatch.setattr(draft_service, "generate_ai_draft", lambda *args, **kwargs: pytest.fail("model reached"))
    body = {"llm": {"model": "synthetic"}, "expected_context_fingerprint": "a" * 64}
    if confirm is not None:
        body["confirm_private_context"] = confirm
    response = TestClient(_app(campaign_ai_draft_router)).post(f"/api/campaigns/{CAMPAIGN_ID}/ai-draft/generate", json=body)
    assert response.status_code == 422


def test_real_app_missing_confirmation_sanitizes_credential_input(monkeypatch):
    import app
    monkeypatch.setattr(draft_service, "generate_ai_draft", lambda *args, **kwargs: pytest.fail("model reached"))
    response = TestClient(app.app).post(f"/api/campaigns/{CAMPAIGN_ID}/ai-draft/generate", json={"llm": {"model": "synthetic", "apiKey": "synthetic-secret"}})
    assert response.status_code == 422
    assert "synthetic-secret" not in response.text

@pytest.mark.parametrize("base_url", ["https://user:secret@example.test/v1", "https://example.test/v1?key=secret", "https://example.test/v1#hidden"])
def test_ambiguous_destination_rejected_before_readiness_or_model(monkeypatch, base_url):
    import app
    monkeypatch.setattr(app, "_require_llm_ready", lambda *args: pytest.fail("readiness reached"))
    monkeypatch.setattr(draft_service, "generate_ai_draft", lambda *args, **kwargs: pytest.fail("model reached"))
    response = TestClient(app.app).post(f"/api/campaigns/{CAMPAIGN_ID}/ai-draft/generate", json={
        "llm": {"model": "synthetic", "apiKey": "synthetic-secret", "baseURL": base_url},
        "confirm_private_context": True, "expected_context_fingerprint": "a" * 64})
    assert response.status_code == 400
    assert "secret" not in response.text
