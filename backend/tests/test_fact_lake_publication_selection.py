from __future__ import annotations

import json
from dataclasses import replace
from itertools import permutations

import pytest

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
from fact_lake_publication_selection import (
    SELECTION_SCHEMA_VERSION,
    CanonicalPublicationSelection,
    PublicationSelectionAmbiguousError,
    PublicationSelectionBasis,
    PublicationSelectionError,
    PublicationSelectionInputError,
    PublicationSelectionMode,
    PublicationSelectionNotFoundError,
    PublicationSelectionPitError,
    PublicationSelectionRequest,
    select_canonical_publications,
)
from fact_lake_store import StoredCanonicalPublication


def _spec(
    *,
    dataset_id: str = "ds_test",
    revision: RevisionSemantics = RevisionSemantics.UNKNOWN,
    pit: bool = False,
) -> DatasetSpec:
    return DatasetSpec(
        dataset_id=dataset_id,
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
        point_in_time_supported=pit,
        revision_semantics=revision,
        adjustment_semantics=AdjustmentSemantics.UNADJUSTED,
        survivorship_semantics=(
            "explicit survivorship contract" if pit else None
        ),
    )


def _fact(
    *,
    dataset_id: str = "ds_test",
    canonical_key: str = "ds_test:2026-07-30",
    revision: RevisionSemantics = RevisionSemantics.UNKNOWN,
    observation_id: str = "obs-1",
) -> CanonicalFact:
    link = ProvenanceLink(
        observation_id=observation_id,
        dataset_id=dataset_id,
        provider_id="test_provider",
        provider_endpoint="test_endpoint",
        source_payload_hash="sha256:" + ("a" * 64),
        normalizer_version="ds-test-normalizer-v0.1",
    )
    return CanonicalFact(
        fact_id=f"fact-{observation_id}",
        dataset_id=dataset_id,
        canonical_key=canonical_key,
        canonical_payload={"rows": []},
        canonical_source="test_provider",
        dataset_contract_revision="ds-test-contract-v0.1",
        revision_semantics=revision,
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
    dataset_id: str = "ds_test",
    canonical_key: str = "ds_test:2026-07-30",
    temporal_field: str = "trade_date",
    temporal_value: str = "2026-07-30",
    contract_revision: str = "ds-test-contract-v0.1",
    normalizer_version: str = "ds-test-normalizer-v0.1",
    artifact_schema_version: str = "ds-test-parquet-v0.1",
    revision: RevisionSemantics = RevisionSemantics.UNKNOWN,
    commit_state: str = "COMMITTED",
    observation_id: str = "obs-1",
) -> StoredCanonicalPublication:
    return StoredCanonicalPublication(
        publication_id=publication_id,
        dataset_id=dataset_id,
        canonical_key=canonical_key,
        primary_temporal_field=temporal_field,
        primary_temporal_value=temporal_value,
        vintage_sequence=vintage,
        fact=_fact(
            dataset_id=dataset_id,
            canonical_key=canonical_key,
            revision=revision,
            observation_id=observation_id,
        ),
        source_observation_id=observation_id,
        dataset_contract_revision=contract_revision,
        normalizer_version=normalizer_version,
        raw_payload_hash="sha256:" + ("a" * 64),
        artifact_schema_version=artifact_schema_version,
        artifact_relpath=f"canonical/{publication_id}.parquet",
        artifact_sha256="sha256:" + ("b" * 64),
        commit_state=commit_state,
    )


def _request(
    *,
    mode: PublicationSelectionMode,
    dataset_id: str = "ds_test",
    canonical_key: str = "ds_test:2026-07-30",
    temporal: TemporalSemantics = TemporalSemantics.TRADE_DATE,
    temporal_value: str = "2026-07-30",
    publication_id: str | None = None,
    as_of: str | None = None,
) -> PublicationSelectionRequest:
    return PublicationSelectionRequest(
        dataset_id=dataset_id,
        canonical_key=canonical_key,
        primary_temporal_field=temporal,
        primary_temporal_value=temporal_value,
        mode=mode,
        publication_id=publication_id,
        as_of=as_of,
    )


def _latest_selection(selection: CanonicalPublicationSelection):
    assert selection.selected_publication_ids
    return selection.selected_publication_ids[-1]


def test_modes_are_explicit_no_ambiguous_latest():
    assert {mode.value for mode in PublicationSelectionMode} == {
        "all",
        "publication_id",
        "local_latest",
    }
    assert {basis.value for basis in PublicationSelectionBasis} == {
        "all_committed",
        "exact_publication_id",
        "local_vintage_sequence",
    }


def test_request_strict_validation():
    with pytest.raises(PublicationSelectionInputError):
        _request(mode=PublicationSelectionMode.ALL, publication_id="pub-1")
    with pytest.raises(PublicationSelectionInputError):
        _request(
            mode=PublicationSelectionMode.LOCAL_LATEST,
            publication_id="pub-1",
        )
    with pytest.raises(PublicationSelectionInputError):
        _request(mode=PublicationSelectionMode.PUBLICATION_ID)
    with pytest.raises(PublicationSelectionInputError):
        PublicationSelectionRequest(
            dataset_id="ds_test",
            canonical_key="ds_test:2026-07-30",
            primary_temporal_field=TemporalSemantics.TRADE_DATE,
            primary_temporal_value="2026-07-30",
            mode="latest",  # type: ignore[arg-type]
        )
    with pytest.raises(PublicationSelectionInputError):
        PublicationSelectionRequest(
            dataset_id="",
            canonical_key="ds_test:2026-07-30",
            primary_temporal_field=TemporalSemantics.TRADE_DATE,
            primary_temporal_value="2026-07-30",
            mode=PublicationSelectionMode.ALL,
        )


def test_request_dataset_must_match_spec():
    spec = _spec(dataset_id="ds_test")
    request = _request(
        mode=PublicationSelectionMode.ALL,
        dataset_id="ds_other",
    )
    with pytest.raises(PublicationSelectionInputError, match="must match"):
        select_canonical_publications(spec, request, ())


def test_matrix_a_single_publication_local_latest():
    spec = _spec()
    publications = (_publication(publication_id="pub-1", vintage=1),)
    selection = select_canonical_publications(
        spec,
        _request(mode=PublicationSelectionMode.LOCAL_LATEST),
        publications,
    )
    assert selection.selected_publication_ids == ("pub-1",)
    assert selection.selected_vintage_sequences == (1,)
    assert selection.selection_basis == "local_vintage_sequence"


def test_matrix_b_shuffled_local_latest_picks_greatest_vintage():
    spec = _spec()
    publications = (
        _publication(publication_id="pub-3", vintage=3),
        _publication(publication_id="pub-1", vintage=1),
        _publication(publication_id="pub-2", vintage=2),
    )
    selection = select_canonical_publications(
        spec,
        _request(mode=PublicationSelectionMode.LOCAL_LATEST),
        publications,
    )
    assert selection.selected_publication_ids == ("pub-3",)
    assert selection.selected_vintage_sequences == (3,)


def test_matrix_c_all_deterministic_order():
    spec = _spec()
    publications = (
        _publication(publication_id="pub-3", vintage=3),
        _publication(publication_id="pub-1", vintage=1),
        _publication(publication_id="pub-2", vintage=2),
    )
    selection = select_canonical_publications(
        spec,
        _request(mode=PublicationSelectionMode.ALL),
        publications,
    )
    assert selection.selected_publication_ids == ("pub-1", "pub-2", "pub-3")
    assert selection.selected_vintage_sequences == (1, 2, 3)
    assert selection.selection_basis == "all_committed"


def test_matrix_d_publication_id_exact_middle():
    spec = _spec()
    publications = (
        _publication(publication_id="pub-1", vintage=1),
        _publication(publication_id="pub-2", vintage=2),
        _publication(publication_id="pub-3", vintage=3),
    )
    selection = select_canonical_publications(
        spec,
        _request(
            mode=PublicationSelectionMode.PUBLICATION_ID,
            publication_id="pub-2",
        ),
        publications,
    )
    assert selection.selected_publication_ids == ("pub-2",)
    assert selection.selected_vintage_sequences == (2,)
    assert selection.selection_basis == "exact_publication_id"


def test_matrix_e_publication_id_absent_not_found():
    spec = _spec()
    publications = (
        _publication(publication_id="pub-1", vintage=1),
        _publication(publication_id="pub-2", vintage=2),
    )
    with pytest.raises(PublicationSelectionNotFoundError):
        select_canonical_publications(
            spec,
            _request(
                mode=PublicationSelectionMode.PUBLICATION_ID,
                publication_id="pub-missing",
            ),
            publications,
        )


def test_matrix_f_duplicate_vintage_fail_closed():
    spec = _spec()
    publications = (
        _publication(publication_id="pub-a", vintage=2),
        _publication(publication_id="pub-b", vintage=2),
    )
    for mode in (
        PublicationSelectionMode.ALL,
        PublicationSelectionMode.LOCAL_LATEST,
    ):
        with pytest.raises(
            PublicationSelectionAmbiguousError,
            match="duplicate vintage",
        ):
            select_canonical_publications(
                spec,
                _request(mode=mode),
                publications,
            )


def test_matrix_g_mixed_canonical_key_only_exact_coordinate_participates():
    spec = _spec()
    publications = (
        _publication(publication_id="pub-1", vintage=1),
        _publication(
            publication_id="pub-other",
            vintage=9,
            canonical_key="ds_test:2026-07-29",
            temporal_value="2026-07-29",
        ),
    )
    selection = select_canonical_publications(
        spec,
        _request(mode=PublicationSelectionMode.ALL),
        publications,
    )
    assert selection.selected_publication_ids == ("pub-1",)
    assert selection.selected_vintage_sequences == (1,)


def test_matrix_h_mixed_temporal_values_never_cross_select():
    spec = _spec()
    publications = (
        _publication(publication_id="pub-1", vintage=1),
        _publication(
            publication_id="pub-other",
            vintage=99,
            temporal_value="2026-06-30",
            canonical_key="ds_test:2026-06-30",
        ),
    )
    selection = select_canonical_publications(
        spec,
        _request(mode=PublicationSelectionMode.ALL),
        publications,
    )
    assert selection.selected_publication_ids == ("pub-1",)


def test_matrix_i_contract_revision_drift_local_latest_fails_closed():
    spec = _spec()
    publications = (
        _publication(
            publication_id="pub-1",
            vintage=1,
            contract_revision="ds-test-contract-v0.1",
        ),
        _publication(
            publication_id="pub-2",
            vintage=2,
            contract_revision="ds-test-contract-v0.2",
        ),
    )
    with pytest.raises(
        PublicationSelectionAmbiguousError,
        match="CONTRACT_REVISION_AMBIGUOUS",
    ):
        select_canonical_publications(
            spec,
            _request(mode=PublicationSelectionMode.LOCAL_LATEST),
            publications,
        )


def test_matrix_j_contract_revision_drift_all_preserves_revisions():
    spec = _spec()
    publications = (
        _publication(
            publication_id="pub-1",
            vintage=1,
            contract_revision="ds-test-contract-v0.1",
        ),
        _publication(
            publication_id="pub-2",
            vintage=2,
            contract_revision="ds-test-contract-v0.2",
        ),
    )
    selection = select_canonical_publications(
        spec,
        _request(mode=PublicationSelectionMode.ALL),
        publications,
    )
    assert selection.selected_publication_ids == ("pub-1", "pub-2")
    assert selection.dataset_contract_revisions == (
        "ds-test-contract-v0.1",
        "ds-test-contract-v0.2",
    )


def test_matrix_j2_publication_id_surfaces_its_exact_contract_revision():
    spec = _spec()
    publications = (
        _publication(
            publication_id="pub-1",
            vintage=1,
            contract_revision="ds-test-contract-v0.1",
        ),
        _publication(
            publication_id="pub-2",
            vintage=2,
            contract_revision="ds-test-contract-v0.2",
        ),
    )
    selection = select_canonical_publications(
        spec,
        _request(
            mode=PublicationSelectionMode.PUBLICATION_ID,
            publication_id="pub-2",
        ),
        publications,
    )
    assert selection.dataset_contract_revisions == ("ds-test-contract-v0.2",)


@pytest.mark.parametrize(
    "revision",
    [
        RevisionSemantics.UNKNOWN,
        RevisionSemantics.RESTATABLE,
        RevisionSemantics.VERSIONED,
        RevisionSemantics.IMMUTABLE,
    ],
)
def test_local_latest_never_claims_revision_or_pit_for_any_semantics(revision):
    spec = _spec(revision=revision)
    publications = (
        _publication(publication_id="pub-1", vintage=1, revision=revision),
        _publication(publication_id="pub-2", vintage=2, revision=revision),
    )
    selection = select_canonical_publications(
        spec,
        _request(mode=PublicationSelectionMode.LOCAL_LATEST),
        publications,
    )
    assert _latest_selection(selection) == "pub-2"
    assert selection.provider_revision_claim == "NONE"
    assert selection.point_in_time_claim == "NONE"
    assert selection.revision_semantics == revision.value


def test_matrix_n_as_of_on_pit_unsupported_fails_closed():
    spec = _spec(pit=False)
    with pytest.raises(
        PublicationSelectionPitError,
        match="DATASET_PIT_UNSUPPORTED",
    ):
        select_canonical_publications(
            spec,
            _request(
                mode=PublicationSelectionMode.ALL,
                as_of="2026-07-30T00:00:00Z",
            ),
            (),
        )


def test_matrix_o_as_of_on_pit_supported_still_not_implemented():
    spec = _spec(
        pit=True,
        revision=RevisionSemantics.RESTATABLE,
    )
    with pytest.raises(
        PublicationSelectionPitError,
        match="SELECTION_PIT_NOT_IMPLEMENTED",
    ):
        select_canonical_publications(
            spec,
            _request(
                mode=PublicationSelectionMode.ALL,
                as_of="2026-07-30T00:00:00Z",
            ),
            (),
        )


def test_matrix_p_non_committed_candidate_rejected():
    spec = _spec()
    for state in ("STAGING", "FAILED", "ABORTED"):
        publications = (
            _publication(
                publication_id="pub-1",
                vintage=1,
                commit_state=state,
            ),
        )
        with pytest.raises(
            PublicationSelectionInputError,
            match="committed publications only",
        ):
            select_canonical_publications(
                spec,
                _request(mode=PublicationSelectionMode.ALL),
                publications,
            )


def test_matrix_q_permutation_identical_selection():
    spec = _spec()
    publications = (
        _publication(publication_id="pub-1", vintage=1),
        _publication(publication_id="pub-2", vintage=2),
        _publication(publication_id="pub-3", vintage=3),
    )
    baseline_all = select_canonical_publications(
        spec,
        _request(mode=PublicationSelectionMode.ALL),
        publications,
    )
    baseline_latest = select_canonical_publications(
        spec,
        _request(mode=PublicationSelectionMode.LOCAL_LATEST),
        publications,
    )
    for permuted in permutations(publications):
        all_selection = select_canonical_publications(
            spec,
            _request(mode=PublicationSelectionMode.ALL),
            tuple(permuted),
        )
        latest_selection = select_canonical_publications(
            spec,
            _request(mode=PublicationSelectionMode.LOCAL_LATEST),
            tuple(permuted),
        )
        assert all_selection.to_dict() == baseline_all.to_dict()
        assert latest_selection.to_dict() == baseline_latest.to_dict()


def test_no_quality_or_version_winner():
    spec = _spec()
    publications = (
        _publication(
            publication_id="pub-1",
            vintage=1,
            normalizer_version="ds-test-normalizer-v0.9",
        ),
        _publication(
            publication_id="pub-2",
            vintage=2,
            normalizer_version="ds-test-normalizer-v0.1",
        ),
    )
    selection = select_canonical_publications(
        spec,
        _request(mode=PublicationSelectionMode.LOCAL_LATEST),
        publications,
    )
    assert _latest_selection(selection) == "pub-2"
    assert selection.normalizer_versions == (
        "ds-test-normalizer-v0.1",
    )


def test_vintage_bool_rejected():
    spec = _spec()
    publications = (
        _publication(publication_id="pub-1", vintage=True),  # type: ignore[arg-type]
    )
    with pytest.raises(PublicationSelectionInputError, match="positive integer"):
        select_canonical_publications(
            spec,
            _request(mode=PublicationSelectionMode.ALL),
            publications,
        )


def test_vintage_zero_rejected():
    spec = _spec()
    publications = (
        _publication(publication_id="pub-1", vintage=0),
    )
    with pytest.raises(PublicationSelectionInputError, match="positive integer"):
        select_canonical_publications(
            spec,
            _request(mode=PublicationSelectionMode.ALL),
            publications,
        )


def test_output_strict_roundtrip_and_claims():
    spec = _spec()
    publications = (
        _publication(publication_id="pub-1", vintage=1),
        _publication(publication_id="pub-2", vintage=2),
    )
    selection = select_canonical_publications(
        spec,
        _request(mode=PublicationSelectionMode.ALL),
        publications,
    )
    assert selection.schema_version == SELECTION_SCHEMA_VERSION
    assert selection.provider_revision_claim == "NONE"
    assert selection.point_in_time_claim == "NONE"
    document = selection.to_dict()
    assert json.loads(json.dumps(document, sort_keys=True)) == document
    restored = CanonicalPublicationSelection.from_dict(document)
    assert restored.to_dict() == document
    assert restored == selection


def test_output_roundtrip_rejects_unknown_claims():
    spec = _spec()
    publications = (_publication(publication_id="pub-1", vintage=1),)
    selection = select_canonical_publications(
        spec,
        _request(mode=PublicationSelectionMode.ALL),
        publications,
    )
    document = selection.to_dict()
    document["provider_revision_claim"] = "LATEST_REVISION"
    with pytest.raises(PublicationSelectionInputError):
        CanonicalPublicationSelection.from_dict(document)


def test_s3_generic_parity_unknown_revision_local_latest():
    spec = _spec(revision=RevisionSemantics.UNKNOWN)
    publications = (
        _publication(
            publication_id="pub-1",
            vintage=1,
            revision=RevisionSemantics.UNKNOWN,
            observation_id="obs-1",
        ),
        _publication(
            publication_id="pub-2",
            vintage=2,
            revision=RevisionSemantics.UNKNOWN,
            observation_id="obs-2",
        ),
    )
    selection = select_canonical_publications(
        spec,
        _request(mode=PublicationSelectionMode.LOCAL_LATEST),
        publications,
    )
    assert _latest_selection(selection) == "pub-2"
    assert selection.selected_vintage_sequences == (2,)
    assert selection.provider_revision_claim == "NONE"
    assert selection.point_in_time_claim == "NONE"
    assert selection.revision_semantics == "unknown"


def test_s2_generic_parity_restatable_local_latest_is_local_only():
    spec = _spec(revision=RevisionSemantics.RESTATABLE)
    publications = (
        _publication(
            publication_id="pub-1",
            vintage=1,
            revision=RevisionSemantics.RESTATABLE,
        ),
        _publication(
            publication_id="pub-2",
            vintage=2,
            revision=RevisionSemantics.RESTATABLE,
        ),
        _publication(
            publication_id="pub-3",
            vintage=3,
            revision=RevisionSemantics.RESTATABLE,
        ),
    )
    selection = select_canonical_publications(
        spec,
        _request(mode=PublicationSelectionMode.LOCAL_LATEST),
        publications,
    )
    assert _latest_selection(selection) == "pub-3"
    assert selection.selected_vintage_sequences == (3,)
    assert selection.provider_revision_claim == "NONE"
    assert selection.point_in_time_claim == "NONE"
    assert selection.revision_semantics == "restatable"


def test_output_contains_no_paths_or_bytes():
    spec = _spec()
    publications = (
        _publication(publication_id="pub-1", vintage=1),
        _publication(publication_id="pub-2", vintage=2),
    )
    selection = select_canonical_publications(
        spec,
        _request(mode=PublicationSelectionMode.ALL),
        publications,
    )
    serialized = json.dumps(selection.to_dict())
    assert "artifact_relpath" not in serialized
    assert "raw_payload_hash" not in serialized
    assert ".parquet" not in serialized
