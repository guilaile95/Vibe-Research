from __future__ import annotations

import json

import pytest

import campaign_ai_draft_service as service


CAMPAIGN_ID = "campaign_" + "a" * 32
THESIS_ID = "b" * 32
ASSET = {"view": "ASSET", "stance": "SUPPORT", "note": "测试观点"}
TRADE = {"view": "TRADE", "stance": "WAIT"}
PORTFOLIO = {"view": "PORTFOLIO", "constraint": "单笔风险未知"}


def _fields() -> dict:
    return {
        "asset_view": ASSET,
        "trade_view": TRADE,
        "portfolio_view": PORTFOLIO,
        "review_by": "2026-09-01T00:00:00.000000Z",
        "key_assumptions": ["假设保持有效"],
        "event_invalidation_conditions": ["事实发生变化"],
        "strategy_horizon": "2 至 4 周",
    }


def _context() -> dict:
    return {
        "schema_version": service.CONTEXT_SCHEMA_VERSION,
        "campaign": {"campaign_id": CAMPAIGN_ID, "security_code": "600519", "strategy": "SWING"},
        "current_thesis": {"thesis_id": THESIS_ID, "original": {"revision": 3}},
        "holding": {"status": "UNKNOWN", "reason_codes": ["TEST"]},
        "account": {"status": "UNKNOWN", "reason_codes": ["TEST"]},
        "critical_data": {"critical_data_state": "UNKNOWN", "critical_data_evaluation": "UNKNOWN"},
    }


def _install_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service,
        "_read_campaign_and_thesis",
        lambda campaign_id: (
            {"campaign_id": campaign_id, "security_code": "600519", "strategy": "SWING"},
            {
                "campaign_id": campaign_id,
                "thesis_id": THESIS_ID,
                "formal_status": "READY",
                "ready": True,
                "original": {"revision": 3},
            },
        ),
    )
    monkeypatch.setattr(service, "_read_context", lambda *args, **kwargs: _context())


def test_generate_returns_uncommitted_server_witness(monkeypatch: pytest.MonkeyPatch):
    _install_context(monkeypatch)
    result = service.generate_ai_draft(
        {"provider": "test", "model": "fake"},
        CAMPAIGN_ID,
        model_runner=lambda _cfg, _messages: json.dumps(_fields(), ensure_ascii=False),
    )

    assert result["draft_status"] == "AI_DRAFT"
    assert result["proposal_status"] == "UNCOMMITTED"
    witness = result["draft_witness"]
    assert witness["draft_id"] == result["draft_id"]
    assert witness["campaign_id"] == CAMPAIGN_ID
    assert witness["thesis_revision"] == 3
    assert witness["context_fingerprint"] == result["context_fingerprint"]
    assert witness["generated_fields"] == _fields()

    validated = service.validate_witness_for_context(
        witness,
        campaign={"campaign_id": CAMPAIGN_ID},
        current_thesis={"thesis_id": THESIS_ID, "original": {"revision": 3}},
        context=_context(),
    )
    provenance = service.provenance_for_draft(validated, _fields())
    assert provenance["asset_view"]["view_origin"] == "MODEL_PROPOSAL"
    assert provenance["trade_view"]["view_origin"] == "MODEL_PROPOSAL"
    assert provenance["portfolio_view"]["view_origin"] == "MODEL_PROPOSAL"

    edited = {**_fields(), "trade_view": {"view": "TRADE", "stance": "OPPOSE"}}
    edited_provenance = service.provenance_for_draft(validated, edited)
    assert edited_provenance["asset_view"]["view_origin"] == "MODEL_PROPOSAL"
    assert edited_provenance["trade_view"]["view_origin"] == "USER_DRAFT"
    assert edited_provenance["portfolio_view"]["view_origin"] == "MODEL_PROPOSAL"


def test_model_output_is_strict_object_with_exact_editable_fields(monkeypatch: pytest.MonkeyPatch):
    _install_context(monkeypatch)
    with pytest.raises(service.CampaignAIDraftOutputError):
        service.generate_ai_draft(
            {"provider": "test", "model": "fake"},
            CAMPAIGN_ID,
            model_runner=lambda _cfg, _messages: json.dumps({**_fields(), "extra": "reject"}),
        )
    with pytest.raises(service.CampaignAIDraftOutputError):
        service.generate_ai_draft(
            {"provider": "test", "model": "fake"},
            CAMPAIGN_ID,
            model_runner=lambda _cfg, _messages: json.dumps([_fields()]),
        )
    with pytest.raises(service.CampaignAIDraftOutputError):
        service.generate_ai_draft(
            {"provider": "test", "model": "fake"},
            CAMPAIGN_ID,
            model_runner=lambda _cfg, _messages: '{"asset_view": NaN}',
        )


def test_witness_context_drift_fails_closed(monkeypatch: pytest.MonkeyPatch):
    _install_context(monkeypatch)
    result = service.generate_ai_draft(
        {"provider": "test", "model": "fake"},
        CAMPAIGN_ID,
        model_runner=lambda _cfg, _messages: json.dumps(_fields()),
    )
    drifted = {**_context(), "critical_data": {"critical_data_state": "USABLE"}}
    with pytest.raises(service.CampaignAIDraftWitnessStaleError):
        service.validate_witness_for_context(
            result["draft_witness"],
            campaign={"campaign_id": CAMPAIGN_ID},
            current_thesis={"thesis_id": THESIS_ID, "original": {"revision": 3}},
            context=drifted,
        )


def test_context_fingerprint_ignores_retrieval_time_authority_refs_but_not_facts():
    first = {
        **_context(),
        "critical_data": {
            "critical_data_state": "USABLE",
            "critical_data_evaluation": "EVALUATED",
            "authority_refs": [
                "critical_data:disclosures:v0.3",
                "disclosures:fetched_at=2026-08-26T00:00:00Z",
                "market-breadth:observed_at=2026-08-26 08:00:00",
            ],
        },
    }
    second = {
        **first,
        "critical_data": {
            **first["critical_data"],
            "authority_refs": [
                "critical_data:disclosures:v0.3",
                "disclosures:fetched_at=2026-08-26T00:05:00Z",
                "market-breadth:observed_at=2026-08-26 08:05:00",
            ],
        },
    }
    assert service.context_fingerprint(first) == service.context_fingerprint(second)

    changed_fact = {
        **second,
        "critical_data": {**second["critical_data"], "critical_data_state": "UNKNOWN"},
    }
    assert service.context_fingerprint(first) != service.context_fingerprint(changed_fact)


def test_consent_preview_is_model_free_and_context_drift_blocks_transmission(monkeypatch):
    _install_context(monkeypatch)
    monkeypatch.setattr(service, "_default_model_runner", lambda *args: pytest.fail("model reached"))
    receipt = service.preview_ai_draft_consent(CAMPAIGN_ID)
    assert set(receipt) == {"campaign_id", "context_fingerprint", "scope"}
    assert receipt["context_fingerprint"] == service.context_fingerprint(_context())
    changed = _context()
    changed["account"] = {"status": "AVAILABLE", "snapshot": {"cash": 98765}}
    monkeypatch.setattr(service, "_read_context", lambda *args, **kwargs: changed)
    with pytest.raises(service.CampaignAIDraftWitnessStaleError):
        service.generate_ai_draft({}, CAMPAIGN_ID, expected_context_fingerprint=receipt["context_fingerprint"])


def test_matching_consent_preserves_intended_private_analysis(monkeypatch):
    _install_context(monkeypatch)
    receipt = service.preview_ai_draft_consent(CAMPAIGN_ID)
    seen = []
    def model(cfg, messages):
        seen.append(messages)
        return json.dumps(_fields())
    result = service.generate_ai_draft({}, CAMPAIGN_ID, expected_context_fingerprint=receipt["context_fingerprint"], model_runner=model)
    assert len(seen) == 1
    assert result["context_fingerprint"] == receipt["context_fingerprint"]


def test_consent_preview_can_read_public_capabilities_but_never_transmits_private_context(monkeypatch):
    monkeypatch.setattr(service, "_read_campaign_and_thesis", lambda _: (
        {"campaign_id": CAMPAIGN_ID, "security_code": "600519", "strategy": "SWING"},
        {"thesis_id": THESIS_ID, "original": {"revision": 3}}))
    monkeypatch.setattr(service.position_reality_service, "read_current_holdings_snapshot", lambda: {"private": "synthetic-private-holding"})
    monkeypatch.setattr(service.account_reality_service, "get_account_reality", lambda: {"private": "synthetic-private-account"})
    public_reads = []
    def capability(**kwargs):
        public_reads.append(kwargs)
        return {"critical_data_state": "UNKNOWN", "reason_codes": ["SYNTHETIC_PUBLIC_CAPABILITY"]}
    monkeypatch.setattr(service.campaign_critical_data_runtime, "project_campaign_critical_data", capability)
    monkeypatch.setattr(service, "_default_model_runner", lambda *args: pytest.fail("model transmission before consent"))
    receipt = service.preview_ai_draft_consent(CAMPAIGN_ID)
    assert len(public_reads) == 1
    assert public_reads[0]["campaign"]["campaign_id"] == CAMPAIGN_ID
    assert set(receipt) == {"campaign_id", "context_fingerprint", "scope"}
    assert "synthetic-private" not in json.dumps(receipt)
