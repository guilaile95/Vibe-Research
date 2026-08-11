"""Project Consolidation Gate — integrated coexistence regression.

These tests intentionally import across independently accepted domains to prove
they coexist on one exact head. They do not authorize Ready/Merge or real-user
migration.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
from pathlib import Path

from data_contracts import (
    AdjustmentSemantics,
    CanonicalFact,
    DatasetSpec,
    FetchSemantics,
    HistoryMode,
    ProvenanceLink,
    ProviderRole,
    ProviderRoute,
    QualityStatus,
    ReconciliationStatus,
    RevisionSemantics,
    TemporalSemantics,
)
from data_health_service import error_summary
from fact_lake_health import FactLakeHealthAssessment
from fact_lake_health_legacy_projection import project_fact_lake_health
from fact_lake_publication_selection import (
    PublicationSelectionMode,
    PublicationSelectionRequest,
    select_canonical_publications,
)
from fact_lake_store import StoredCanonicalPublication


BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent


def _spec(
    *,
    revision: RevisionSemantics = RevisionSemantics.UNKNOWN,
) -> DatasetSpec:
    return DatasetSpec(
        dataset_id="ds_test",
        fetch_semantics=FetchSemantics.BY_DATE,
        history_mode=HistoryMode.BY_DATE,
        routes=(
            ProviderRoute(
                route_id="test-route",
                provider_id="test_provider",
                provider_endpoint="test_endpoint",
                role=ProviderRole.CANONICAL,
                semantic_contract_id="test-contract-v0.1",
            ),
        ),
        governance_revision_id="ds-test-contract-v0.1",
        required_temporal_fields=(TemporalSemantics.TRADE_DATE,),
        point_in_time_supported=False,
        revision_semantics=revision,
        adjustment_semantics=AdjustmentSemantics.UNADJUSTED,
        survivorship_semantics=None,
    )


def _fact(observation_id: str = "obs-1") -> CanonicalFact:
    link = ProvenanceLink(
        observation_id=observation_id,
        dataset_id="ds_test",
        provider_id="test_provider",
        provider_endpoint="test_endpoint",
        source_payload_hash="sha256:" + ("a" * 64),
        normalizer_version="ds-test-normalizer-v0.1",
    )
    return CanonicalFact(
        fact_id=f"fact-{observation_id}",
        dataset_id="ds_test",
        canonical_key="ds_test:2026-07-30",
        canonical_payload={"rows": []},
        canonical_source="test_provider",
        dataset_contract_revision="ds-test-contract-v0.1",
        revision_semantics=RevisionSemantics.UNKNOWN,
        adjustment_semantics=AdjustmentSemantics.UNADJUSTED,
        source_observation_ids=(observation_id,),
        provenance_chain=(link,),
        trade_date="2026-07-30",
        report_period=None,
        published_at=None,
        observed_at=None,
        effective_at=None,
        revision_id=None,
        data_version=None,
        quality_status=QualityStatus.VALID,
        reconciliation_status=ReconciliationStatus.UNKNOWN,
        reason_codes=(),
    )


def _publication(
    *,
    publication_id: str,
    vintage: int,
    observation_id: str,
) -> StoredCanonicalPublication:
    return StoredCanonicalPublication(
        publication_id=publication_id,
        dataset_id="ds_test",
        canonical_key="ds_test:2026-07-30",
        primary_temporal_field="trade_date",
        primary_temporal_value="2026-07-30",
        vintage_sequence=vintage,
        fact=_fact(observation_id),
        source_observation_id=observation_id,
        dataset_contract_revision="ds-test-contract-v0.1",
        normalizer_version="ds-test-normalizer-v0.1",
        raw_payload_hash="sha256:" + ("a" * 64),
        artifact_schema_version="ds-test-parquet-v0.1",
        artifact_relpath=f"canonical/{publication_id}.parquet",
        artifact_sha256="sha256:" + ("b" * 64),
        commit_state="COMMITTED",
    )


def _request(mode: PublicationSelectionMode, publication_id: str | None = None):
    return PublicationSelectionRequest(
        dataset_id="ds_test",
        canonical_key="ds_test:2026-07-30",
        primary_temporal_field=TemporalSemantics.TRADE_DATE,
        primary_temporal_value="2026-07-30",
        mode=mode,
        publication_id=publication_id,
        as_of=None,
    )


def _assessment(**kwargs) -> FactLakeHealthAssessment:
    base = dict(
        dataset_id="ds_limit_up_pool",
        canonical_key="2026-08-10",
        publication_id="pub_" + "b" * 32,
        publication_visibility="COMMITTED",
        storage_integrity="VERIFIED",
        reproducibility="MATCH",
        semantic_quality="valid",
        freshness="CURRENT",
        reconciliation="match",
        canonical_admissibility="USABLE",
        reason_codes=(),
    )
    base.update(kwargs)
    return FactLakeHealthAssessment(**base)


# ---------------------------------------------------------------------------
# Cross-domain import / authority surface
# ---------------------------------------------------------------------------


def test_cross_domain_modules_import_together():
    modules = [
        "formal_thesis_projection",
        "formal_thesis_projection_core",
        "evidence_thesis_store",
        "evidence_thesis_migration",
        "campaign_lineage",
        "frozen_decision_store",
        "formal_trade_attribution",
        "performance_attribution_service",
        "formal_decision_outcome",
        "fact_lake_store",
        "fact_lake_publication_selection",
        "fact_lake_health",
        "fact_lake_health_adapter",
        "fact_lake_health_legacy_projection",
        "data_contracts",
    ]
    for name in modules:
        importlib.import_module(name)


def test_runtime_current_thesis_authority_is_integrated_adapter_only():
    """OPTION B: campaign router uses integrated projection, not pure core."""
    router_path = BACKEND / "campaign_router.py"
    source = router_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "formal_thesis_projection" in imported
    assert "formal_thesis_projection_core" not in imported

    import formal_thesis_projection as runtime
    import formal_thesis_projection_core as pure

    runtime_params = list(inspect.signature(runtime.project_current_thesis).parameters)
    pure_params = list(inspect.signature(pure.project_current_thesis).parameters)
    assert runtime_params == ["campaign_id"]
    assert "binding" in pure_params
    assert "frozen_original" in pure_params


# ---------------------------------------------------------------------------
# Fact Lake selection + health coexistence (Q1 + H3)
# ---------------------------------------------------------------------------


def test_q1_modes_coexist_with_none_claims():
    pubs = [
        _publication(publication_id="p1", vintage=1, observation_id="obs-1"),
        _publication(publication_id="p2", vintage=3, observation_id="obs-2"),
        _publication(publication_id="p3", vintage=2, observation_id="obs-3"),
    ]
    spec = _spec()

    pubs_t = tuple(pubs)
    all_sel = select_canonical_publications(
        spec,
        _request(PublicationSelectionMode.ALL),
        pubs_t,
    )
    assert all_sel.provider_revision_claim == "NONE"
    assert all_sel.point_in_time_claim == "NONE"
    assert len(all_sel.selected_publication_ids) == 3

    latest = select_canonical_publications(
        spec,
        _request(PublicationSelectionMode.LOCAL_LATEST),
        pubs_t,
    )
    assert latest.selected_publication_ids == ("p2",)
    assert latest.provider_revision_claim == "NONE"
    assert latest.point_in_time_claim == "NONE"

    by_id = select_canonical_publications(
        spec,
        _request(PublicationSelectionMode.PUBLICATION_ID, publication_id="p1"),
        pubs_t,
    )
    assert by_id.selected_publication_ids == ("p1",)
    assert by_id.provider_revision_claim == "NONE"
    assert by_id.point_in_time_claim == "NONE"


def test_h3_warning_with_empty_reasons_not_washed_to_normal():
    """USABLE_WITH_WARNING must not become normal merely because reasons are empty."""
    assessment = _assessment(
        canonical_admissibility="USABLE_WITH_WARNING",
        semantic_quality="degraded",
        reason_codes=(),
    )
    legacy = project_fact_lake_health(assessment=assessment)
    assert legacy.legacy_status == "partial"
    assert legacy.legacy_status != "normal"


def test_h3_mapping_usable_warning_blocked():
    clean = project_fact_lake_health(assessment=_assessment())
    assert clean.legacy_status == "normal"

    # stale-only warning maps to normal + is_stale (exact lossiness), never unavailable
    stale = project_fact_lake_health(
        assessment=_assessment(
            canonical_admissibility="USABLE_WITH_WARNING",
            freshness="STALE",
            reason_codes=("TEMPORAL_VALUE_STALE",),
        )
    )
    assert stale.legacy_status == "normal"
    assert stale.legacy_is_stale is True
    assert stale.legacy_error_code == "SOURCE_STALE"
    assert stale.legacy_error_summary == error_summary("SOURCE_STALE")

    quality_warning = project_fact_lake_health(
        assessment=_assessment(
            canonical_admissibility="USABLE_WITH_WARNING",
            semantic_quality="degraded",
            reason_codes=("FACT_QUALITY_DEGRADED",),
        )
    )
    assert quality_warning.legacy_status == "partial"

    blocked = project_fact_lake_health(
        assessment=_assessment(
            canonical_admissibility="BLOCKED",
            storage_integrity="CORRUPTED",
            reason_codes=("ARTIFACT_HASH_MISMATCH",),
        )
    )
    assert blocked.legacy_status == "unavailable"


def test_selection_and_health_modules_coexist():
    import fact_lake_health as health
    import fact_lake_publication_selection as selection
    import fact_lake_store as store

    assert hasattr(selection, "select_canonical_publications")
    assert hasattr(health, "FactLakeHealthAssessment")
    assert hasattr(store, "StoredCanonicalPublication")


# ---------------------------------------------------------------------------
# Decision / thesis semantic surface smoke
# ---------------------------------------------------------------------------


def test_decision_chain_modules_expose_expected_surfaces():
    attribution = importlib.import_module("formal_trade_attribution")
    outcome = importlib.import_module("formal_decision_outcome")
    decision_store = importlib.import_module("frozen_decision_store")

    assert any("error" in name.lower() for name in dir(attribution))
    assert any("outcome" in name.lower() for name in dir(outcome))
    assert any("decision" in name.lower() for name in dir(decision_store))


def test_registry_files_present_and_machine_readable():
    root = ROOT / "docs" / "integration"
    accepted = json.loads((root / "accepted_heads.json").read_text(encoding="utf-8"))
    supersession = json.loads(
        (root / "supersession_registry.json").read_text(encoding="utf-8")
    )
    assert accepted["not_runtime_authority"] is True
    assert accepted["stable"]["exact_head"] == (
        "1be2ecba505a8108740c311c103a2c72d3bcd444"
    )
    pr91 = next(e for e in supersession["entries"] if e["pr"] == 91)
    assert pr91["superseded_by"] == 95
    assert pr91["do_not_integrate"] is True
    pr72 = next(e for e in supersession["entries"] if e["pr"] == 72)
    assert pr72["authority_decision"] == "B"
    assert pr72["superseded_by"] == 73
