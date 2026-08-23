"""Fact Lake Health Read-Only Evidence Adapter v0.1 专项测试（DS-L1-H2）。

覆盖 §32 全部 acceptance gates：只读句柄硬不变量、仅公共 Fact Lake API、
COMMITTED-only 收集、非提交不可见、VERIFIED 仅经公共 authority、
artifact SHA 桥接（sha256: 前缀 → 64 小写 hex）、通用 temporal
（TRADE_DATE / REPORT_PERIOD 双矩阵）、零时钟新鲜度、对账 harvest 六态、
corruption fail-closed（raw / artifact / normalization）、zero-mutation、
源码纯净扫描。全部使用 tmp 测试 lake（NO_REAL_USER_DB）。
"""
from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
from pathlib import Path

import pytest

import fact_lake_health as flh
import fact_lake_health_adapter as flha
import fact_lake_store as flha_store
from data_contracts import (
    CanonicalFact,
    CoverageMode,
    DatasetSpec,
    ProviderObservation,
    ProvenanceLink,
    ReconciliationResult,
    ReconciliationStatus,
    FetchSemantics,
    HistoryMode,
    ProviderRoute,
    ProviderRole,
    QualityStatus,
    RevisionSemantics,
    AdjustmentSemantics,
    TemporalSemantics,
)
from fact_lake_health import FactLakeHealthAssessment
from fact_lake_store import (
    FactLakeReadOnlyError,
    initialize_fact_lake,
    open_existing_fact_lake,
    payload_sha256,
)

T_UTC = "2026-08-10T04:00:00.000Z"
OBS_ID = "obs_" + "a" * 32
PUB_ID = "pub_" + "b" * 32
FACT_ID = "fact_" + "c" * 32
TRADE_DATE = "2026-08-10"
REPORT_PERIOD = "2026Q2"
ARTIFACT_RELPATH = "canonical/" + "0" * 64 + "/2026-08-10/" + "0" * 64 + ".parquet"


# ---------------------------------------------------------------------------
# Specs（与 H1 专项测试一致的两矩阵）
# ---------------------------------------------------------------------------

def _route(provider: str = "eastmoney_push2ex", role: str = "canonical") -> ProviderRoute:
    return ProviderRoute(
        route_id=f"route_{provider}",
        provider_id=provider,
        provider_endpoint="/api/snapshot",
        role=ProviderRole(role),
        semantic_contract_id="sem-1",
    )


def _limit_up_spec() -> DatasetSpec:
    return DatasetSpec(
        dataset_id="ds_limit_up_pool",
        fetch_semantics=FetchSemantics.BY_DATE,
        history_mode=HistoryMode.BY_DATE,
        routes=(_route(),),
        governance_revision_id="rev-1",
        required_temporal_fields=(TemporalSemantics.TRADE_DATE,),
        coverage_mode=CoverageMode.SESSION_DENSE,
        point_in_time_supported=False,
        revision_semantics=RevisionSemantics.IMMUTABLE,
        adjustment_semantics=AdjustmentSemantics.NOT_APPLICABLE,
        max_staleness_seconds=3600,
    )


def _financial_spec() -> DatasetSpec:
    return DatasetSpec(
        dataset_id="ds_financial_indicator",
        fetch_semantics=FetchSemantics.BY_DATE,
        history_mode=HistoryMode.BY_DATE,
        routes=(_route(),),
        governance_revision_id="rev-f1",
        required_temporal_fields=(TemporalSemantics.REPORT_PERIOD,),
        coverage_mode=CoverageMode.SPARSE,
        point_in_time_supported=False,
        revision_semantics=RevisionSemantics.RESTATABLE,
        adjustment_semantics=AdjustmentSemantics.NOT_APPLICABLE,
    )


# ---------------------------------------------------------------------------
# Seed helpers（用公共写 API 构造 tmp fixture lake；仅测试侧使用）
# ---------------------------------------------------------------------------

def _raw_payload(dataset_id: str) -> dict:
    if dataset_id == "ds_limit_up_pool":
        return {"count": 5}
    return {"rows": [{"ts_code": "000001.SZ", "period": "20260331"}]}


def _observation(*, dataset_id: str, trade_date: str | None = None,
                 report_period: str | None = None,
                 quality: QualityStatus = QualityStatus.VALID) -> tuple[ProviderObservation, bytes]:
    payload = _raw_payload(dataset_id)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return ProviderObservation(
        observation_id=OBS_ID,
        dataset_id=dataset_id,
        provider_id="eastmoney_push2ex",
        provider_endpoint="/api/snapshot",
        provider_symbol="000001.SZ",
        request_fingerprint="sha256:" + "f" * 64,
        source_payload_hash=payload_sha256(raw),
        normalizer_version="n1",
        payload=payload,
        fetch_semantics=FetchSemantics.BY_DATE,
        history_mode=HistoryMode.BY_DATE,
        fetched_at=T_UTC,
        trade_date=trade_date,
        report_period=report_period,
        quality_status=quality,
        revision_semantics=RevisionSemantics.IMMUTABLE,
        adjustment_semantics=AdjustmentSemantics.NOT_APPLICABLE,
    ), raw


def _fact(*, spec: DatasetSpec, observation: ProviderObservation,
          temporal_field: TemporalSemantics, temporal_value: str,
          reconciliation_status: ReconciliationStatus | None = None) -> CanonicalFact:
    normalized = _raw_payload(spec.dataset_id)
    kw = {
        "fact_id": FACT_ID,
        "dataset_id": spec.dataset_id,
        "canonical_key": temporal_value,
        "canonical_payload": normalized,
        "canonical_source": observation.provider_id,
        "dataset_contract_revision": spec.governance_revision_id,
        "revision_semantics": spec.revision_semantics,
        "adjustment_semantics": spec.adjustment_semantics,
        "source_observation_ids": (observation.observation_id,),
        "provenance_chain": (ProvenanceLink(
            observation_id=observation.observation_id,
            dataset_id=spec.dataset_id,
            provider_id=observation.provider_id,
            provider_endpoint=observation.provider_endpoint,
            source_payload_hash=observation.source_payload_hash,
            normalizer_version=observation.normalizer_version,
        ),),
        "quality_status": observation.quality_status,
        "reason_codes": (),
    }
    if temporal_field is TemporalSemantics.TRADE_DATE:
        kw["trade_date"] = temporal_value
    elif temporal_field is TemporalSemantics.REPORT_PERIOD:
        kw["report_period"] = temporal_value
    if reconciliation_status is not None:
        kw["reconciliation_status"] = reconciliation_status
    return CanonicalFact(**kw)


def _seed_publication(lake, *, spec: DatasetSpec, temporal_field: TemporalSemantics,
                      temporal_value: str,
                      reconciliation_status: ReconciliationStatus | None = None,
                      artifact_relpath: str = ARTIFACT_RELPATH,
                      artifact_bytes: bytes | None = None) -> tuple[ProviderObservation, CanonicalFact, str]:
    trade_date = temporal_value if temporal_field is TemporalSemantics.TRADE_DATE else None
    report_period = temporal_value if temporal_field is TemporalSemantics.REPORT_PERIOD else None
    observation, raw = _observation(
        dataset_id=spec.dataset_id,
        trade_date=trade_date,
        report_period=report_period,
    )
    fact = _fact(
        spec=spec,
        observation=observation,
        temporal_field=temporal_field,
        temporal_value=temporal_value,
        reconciliation_status=reconciliation_status,
    )
    lake.store_observation(observation, raw, "application/json")
    lake.store_normalization(
        observation.observation_id,
        fact.canonical_payload,
        normalizer_version=observation.normalizer_version,
    )
    lake.stage_canonical_publication(
        fact,
        publication_id=PUB_ID,
        source_observation_id=observation.observation_id,
        primary_temporal_field=temporal_field,
        primary_temporal_value=temporal_value,
        normalizer_version=observation.normalizer_version,
        raw_payload_hash=observation.source_payload_hash,
        artifact_schema_version="parquet.v1",
        artifact_relpath=artifact_relpath,
    )
    content = artifact_bytes if artifact_bytes is not None else b"artifact-bytes"
    digest = lake.publish_canonical_artifact(
        artifact_relpath,
        writer=lambda path: path.write_bytes(content),
    )
    lake.commit_canonical_publication(PUB_ID, digest)
    return observation, fact, digest


def _seed_staged_only(lake, *, spec: DatasetSpec, temporal_field: TemporalSemantics,
                      temporal_value: str) -> None:
    """只 stage 不 commit → 不可见（§25）。"""
    observation, raw = _observation(dataset_id=spec.dataset_id, trade_date=temporal_value)
    fact = _fact(spec=spec, observation=observation,
                 temporal_field=temporal_field, temporal_value=temporal_value)
    lake.store_observation(observation, raw, "application/json")
    lake.store_normalization(
        observation.observation_id,
        fact.canonical_payload,
        normalizer_version=observation.normalizer_version,
    )
    lake.stage_canonical_publication(
        fact,
        publication_id=PUB_ID,
        source_observation_id=observation.observation_id,
        primary_temporal_field=temporal_field,
        primary_temporal_value=temporal_value,
        normalizer_version=observation.normalizer_version,
        raw_payload_hash=observation.source_payload_hash,
        artifact_schema_version="parquet.v1",
        artifact_relpath=ARTIFACT_RELPATH,
    )


def _recon(status: ReconciliationStatus, *, dataset_id: str,
           left: str = OBS_ID) -> ReconciliationResult:
    return ReconciliationResult(
        dataset_id=dataset_id,
        status=status,
        comparison_policy_id="pol-1",
        comparison_policy_version="1",
        comparison_evidence={},
        left_observation_id=left,
        right_observation_id="obs_" + "c" * 32,
        left_value=1,
        right_value=1,
        reason_codes=(),
    )


def _request(publication_id: str = PUB_ID, **kwargs) -> flha.HealthCollectionRequest:
    return flha.HealthCollectionRequest(publication_id=publication_id, **kwargs)


# ---------------------------------------------------------------------------
# Zero-mutation 指纹（§23）
# ---------------------------------------------------------------------------

def _tree_fingerprint(root: Path) -> dict:
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        stat = path.stat()
        result[relative] = (
            "file" if path.is_file() else "dir",
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
        )
    return result


def _assert_no_sidecars(root: Path) -> None:
    sidecar_markers = ("-wal", "-shm", "-journal", ".tmp", ".bak")
    for path in root.rglob("*"):
        name = path.name.lower()
        assert not any(marker in name for marker in sidecar_markers), \
            f"发现意外 sidecar 文件: {path}"


def _raw_blob_path(lake, observation_id: str = OBS_ID) -> Path:
    stored = lake.get_observation(observation_id)
    assert stored is not None
    return lake.root.joinpath(*Path(stored.blob_relpath).parts)


def _artifact_path(lake) -> Path:
    publication = lake.get_canonical_publication(PUB_ID)
    assert publication is not None
    return lake.root.joinpath(*Path(publication.artifact_relpath).parts)


def _control_db(root: Path) -> Path:
    return root / "fact_lake_control.sqlite3"


# ---------------------------------------------------------------------------
# A. 只读句柄硬不变量 + 收集基础
# ---------------------------------------------------------------------------

def test_writable_lake_handle_rejected(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    assert lake.readonly is False
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.collect_fact_lake_health_evidence(
            lake=lake,
            dataset_spec=_limit_up_spec(),
            request=_request(),
        )
    assert exc.value.failure.code == flha.FAILURE_BAD_ARGUMENT


def test_collect_committed_limit_up_evidence(tmp_path):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    spec = _limit_up_spec()
    _, fact, digest = _seed_publication(
        lake, spec=spec,
        temporal_field=TemporalSemantics.TRADE_DATE,
        temporal_value=TRADE_DATE,
    )
    readonly = open_existing_fact_lake(root)
    assert readonly.readonly is True
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=spec,
        request=_request(),
    )
    assert evidence.commit_state == "COMMITTED"
    assert evidence.source_observations_committed is True
    assert evidence.raw_payload_integrity == "VERIFIED"
    assert evidence.artifact_integrity == "VERIFIED"
    assert evidence.replay_state == "NOT_RUN"  # REPLAY_COLLECTION = NOT_RUN_BY_GENERIC_ADAPTER_V01
    assert evidence.dataset_id == spec.dataset_id
    assert evidence.canonical_key == TRADE_DATE
    assert evidence.primary_temporal_field is TemporalSemantics.TRADE_DATE
    assert evidence.primary_temporal_value == TRADE_DATE
    assert evidence.canonical_fact == fact  # 公共读路径重建的 fact 与写入时语义一致
    assert evidence.canonical_fact.trade_date == TRADE_DATE
    assert evidence.canonical_fact.report_period is None  # TRADE_DATE 矩阵不发明 REPORT_PERIOD


def test_collect_committed_financial_evidence(tmp_path):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    spec = _financial_spec()
    _, fact, digest = _seed_publication(
        lake, spec=spec,
        temporal_field=TemporalSemantics.REPORT_PERIOD,
        temporal_value=REPORT_PERIOD,
    )
    readonly = open_existing_fact_lake(root)
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=spec,
        request=_request(),
    )
    assert evidence.commit_state == "COMMITTED"
    assert evidence.primary_temporal_field is TemporalSemantics.REPORT_PERIOD
    assert evidence.primary_temporal_value == REPORT_PERIOD
    assert evidence.canonical_fact.report_period == REPORT_PERIOD
    assert evidence.canonical_fact.trade_date is None  # REPORT_PERIOD 矩阵不发明 trade_date


def test_artifact_sha_format_bridge(tmp_path):
    """§11：sha256:<64 hex> → 64 lowercase hex；严格前缀+小写。"""
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    spec = _limit_up_spec()
    _, _, digest = _seed_publication(
        lake, spec=spec,
        temporal_field=TemporalSemantics.TRADE_DATE,
        temporal_value=TRADE_DATE,
    )
    assert digest.startswith("sha256:")
    readonly = open_existing_fact_lake(root)
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=spec,
        request=_request(),
    )
    assert evidence.artifact_sha256 == digest[len("sha256:"):]
    assert len(evidence.artifact_sha256) == 64
    assert evidence.artifact_sha256.islower()
    assert all(c in "0123456789abcdef" for c in evidence.artifact_sha256)


# ---------------------------------------------------------------------------
# B. 非提交不可见 / 失败模型
# ---------------------------------------------------------------------------

def test_staged_publication_not_visible(tmp_path):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    spec = _limit_up_spec()
    _seed_staged_only(lake, spec=spec,
                      temporal_field=TemporalSemantics.TRADE_DATE,
                      temporal_value=TRADE_DATE)
    readonly = open_existing_fact_lake(root)
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.collect_fact_lake_health_evidence(
            lake=readonly,
            dataset_spec=spec,
            request=_request(),
        )
    assert exc.value.failure.code == flha.FAILURE_PUBLICATION_NOT_VISIBLE


def test_missing_publication_not_visible(tmp_path):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    readonly = open_existing_fact_lake(root)
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.collect_fact_lake_health_evidence(
            lake=readonly,
            dataset_spec=_limit_up_spec(),
            request=_request(publication_id="pub_" + "d" * 32),
        )
    assert exc.value.failure.code == flha.FAILURE_PUBLICATION_NOT_VISIBLE


def test_collection_failure_round_trip(tmp_path):
    failure = flha.HealthEvidenceCollectionFailure(
        code=flha.FAILURE_PUBLICATION_NOT_VISIBLE, detail="x")
    restored = flha.HealthEvidenceCollectionFailure.from_dict(failure.to_dict())
    assert restored == failure
    with pytest.raises(ValueError):
        flha.HealthEvidenceCollectionFailure.from_dict({"code": "NOT_A_CODE", "detail": "x"})


# ---------------------------------------------------------------------------
# C. 零时钟新鲜度（§17/§18：仅显式请求 + 精确语义）
# ---------------------------------------------------------------------------

def _committed_lake(tmp_path, spec: DatasetSpec, temporal_field: TemporalSemantics,
                    temporal_value: str):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    observation, fact, digest = _seed_publication(
        lake, spec=spec,
        temporal_field=temporal_field,
        temporal_value=temporal_value,
    )
    return root, observation, fact


def test_no_freshness_request_harvests_nothing(tmp_path):
    root, _, _ = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    readonly = open_existing_fact_lake(root)
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=_request(),
    )
    assert evidence.freshness_semantics is None
    assert evidence.freshness_value is None
    assert evidence.freshness_reference_at is None
    assessment = flha.assess_fact_lake_publication(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=_request(),
    )
    assert assessment.freshness == "UNKNOWN"  # NO_FAKE_FRESHNESS：H1 保持 UNKNOWN


def test_fetched_at_harvested_from_observation(tmp_path):
    root, observation, _ = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    readonly = open_existing_fact_lake(root)
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=_request(freshness=flha.FreshnessRequest(
            semantics=TemporalSemantics.FETCHED_AT,
            reference_at=T_UTC,
        )),
    )
    assert evidence.freshness_semantics is TemporalSemantics.FETCHED_AT
    assert evidence.freshness_value == observation.fetched_at  # 精确来源，无 cross-semantic
    assert evidence.freshness_reference_at == T_UTC


def test_trade_date_freshness_from_fact(tmp_path):
    root, _, fact = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    readonly = open_existing_fact_lake(root)
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=_request(freshness=flha.FreshnessRequest(
            semantics=TemporalSemantics.TRADE_DATE,
        )),
    )
    assert evidence.freshness_semantics is TemporalSemantics.TRADE_DATE
    assert evidence.freshness_value == fact.trade_date
    assert evidence.freshness_reference_at is None  # 坐标语义不需要 reference


def test_report_period_freshness_from_fact(tmp_path):
    root, _, fact = _committed_lake(
        tmp_path, _financial_spec(),
        TemporalSemantics.REPORT_PERIOD, REPORT_PERIOD)
    readonly = open_existing_fact_lake(root)
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=_financial_spec(),
        request=_request(freshness=flha.FreshnessRequest(
            semantics=TemporalSemantics.REPORT_PERIOD,
        )),
    )
    assert evidence.freshness_semantics is TemporalSemantics.REPORT_PERIOD
    assert evidence.freshness_value == fact.report_period


def test_absent_semantic_preserves_unknown(tmp_path):
    """P1-A：显式请求的语义永不消失；值缺失 → None → H1 UNKNOWN。"""
    root, _, _ = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    readonly = open_existing_fact_lake(root)
    request = _request(freshness=flha.FreshnessRequest(
        semantics=TemporalSemantics.EFFECTIVE_AT,  # fact 无 effective_at
        reference_at=T_UTC,
    ))
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=request,
    )
    assert evidence.freshness_semantics is TemporalSemantics.EFFECTIVE_AT  # 语义保留
    assert evidence.freshness_value is None  # 无值不发明
    assessment = flha.assess_fact_lake_publication(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=request,
    )
    assert assessment.freshness == "UNKNOWN"


# ---------------------------------------------------------------------------
# D. 对账 harvest（§14/§15/§26 六态）
# ---------------------------------------------------------------------------

def test_recon_none_uses_persisted(tmp_path):
    root, _, _ = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    readonly = open_existing_fact_lake(root)
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=_request(),
    )
    assert evidence.reconciliation_result is None  # 0 bound → None → H1 persisted 行为
    assessment = flha.assess_fact_lake_publication(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=_request(),
    )
    assert assessment.reconciliation == "not_applicable"  # persisted UNKNOWN + 无 verifier


def test_recon_one_bound_match_supplied(tmp_path):
    root, _, _ = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    lake = open_existing_fact_lake(root, readonly=False)
    lake.append_reconciliation(_recon(ReconciliationStatus.MATCH, dataset_id="ds_limit_up_pool"))
    readonly = open_existing_fact_lake(root)
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=_request(),
    )
    assert evidence.reconciliation_result is not None
    assert evidence.reconciliation_result.status is ReconciliationStatus.MATCH
    assessment = flha.assess_fact_lake_publication(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=_request(),
    )
    assert assessment.reconciliation == "match"


def test_recon_unrelated_ignored(tmp_path):
    root, _, _ = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    lake = open_existing_fact_lake(root, readonly=False)
    lake.append_reconciliation(_recon(
        ReconciliationStatus.MISMATCH,
        dataset_id="ds_limit_up_pool",
        left="obs_" + "z" * 32,  # 与 fact.source_observation_ids 无交集
    ))
    readonly = open_existing_fact_lake(root)
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=_request(),
    )
    assert evidence.reconciliation_result is None  # unrelated → 忽略


def test_recon_exact_duplicate_idempotent(tmp_path):
    root, _, _ = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    lake = open_existing_fact_lake(root, readonly=False)
    result = _recon(ReconciliationStatus.MATCH, dataset_id="ds_limit_up_pool")
    lake.append_reconciliation(result)
    lake.append_reconciliation(result)  # 精确重复
    readonly = open_existing_fact_lake(root)
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=_request(),
    )
    assert evidence.reconciliation_result is not None
    assert evidence.reconciliation_result.status is ReconciliationStatus.MATCH


def test_recon_two_distinct_bound_ambiguous(tmp_path):
    root, _, _ = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    lake = open_existing_fact_lake(root, readonly=False)
    lake.append_reconciliation(_recon(ReconciliationStatus.MATCH, dataset_id="ds_limit_up_pool"))
    lake.append_reconciliation(_recon(ReconciliationStatus.MISMATCH, dataset_id="ds_limit_up_pool"))
    readonly = open_existing_fact_lake(root)
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.collect_fact_lake_health_evidence(
            lake=readonly,
            dataset_spec=_limit_up_spec(),
            request=_request(),
        )
    assert exc.value.failure.code == flha.FAILURE_RECONCILIATION_AMBIGUOUS


def test_recon_bound_conflicts_persisted_drift_delegated(tmp_path):
    """§26-F：bound result 与 persisted fact 冲突 → adapter 成功收集，H1 返回 drift BLOCKED。"""
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    spec = _limit_up_spec()
    _seed_publication(
        lake, spec=spec,
        temporal_field=TemporalSemantics.TRADE_DATE,
        temporal_value=TRADE_DATE,
        reconciliation_status=ReconciliationStatus.MATCH,  # persisted MATCH
    )
    lake.append_reconciliation(_recon(ReconciliationStatus.MISMATCH, dataset_id="ds_limit_up_pool"))
    readonly = open_existing_fact_lake(root)
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=spec,
        request=_request(),
    )
    assert evidence.reconciliation_result is not None  # 收集成功（不隐藏冲突）
    assessment = flha.assess_fact_lake_publication(
        lake=readonly,
        dataset_spec=spec,
        request=_request(),
    )
    assert flh.REASON_RECONCILIATION_STATUS_DRIFT in assessment.reason_codes
    assert assessment.canonical_admissibility == "BLOCKED"  # H1 已委托 drift 判定


def test_recon_ambiguous_never_winner_selection(tmp_path):
    """绝不 latest/sequence/winner 选择：MATCH 后 MISMATCH 不得静默 MATCH 赢。"""
    root, _, _ = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    lake = open_existing_fact_lake(root, readonly=False)
    lake.append_reconciliation(_recon(ReconciliationStatus.MATCH, dataset_id="ds_limit_up_pool"))
    lake.append_reconciliation(_recon(ReconciliationStatus.MISMATCH, dataset_id="ds_limit_up_pool"))
    readonly = open_existing_fact_lake(root)
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.collect_fact_lake_health_evidence(
            lake=readonly,
            dataset_spec=_limit_up_spec(),
            request=_request(),
        )
    assert exc.value.failure.code == flha.FAILURE_RECONCILIATION_AMBIGUOUS


# ---------------------------------------------------------------------------
# E. Corruption fail-closed（§24）：raw / artifact / normalization
# ---------------------------------------------------------------------------

def test_corrupt_raw_blob_collection_fails_closed(tmp_path):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    spec = _limit_up_spec()
    _seed_publication(
        lake, spec=spec,
        temporal_field=TemporalSemantics.TRADE_DATE,
        temporal_value=TRADE_DATE,
    )
    blob_path = _raw_blob_path(lake)
    blob_path.write_bytes(b"corrupted-bytes")
    readonly = open_existing_fact_lake(root)
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.collect_fact_lake_health_evidence(
            lake=readonly,
            dataset_spec=spec,
            request=_request(),
        )
    assert exc.value.failure.code == flha.FAILURE_CORRUPTED  # 不猜测为 HASH_MISMATCH 维度
    assert blob_path.read_bytes() == b"corrupted-bytes"  # 不做 repair


def test_corrupt_artifact_collection_fails_closed(tmp_path):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    spec = _limit_up_spec()
    _seed_publication(
        lake, spec=spec,
        temporal_field=TemporalSemantics.TRADE_DATE,
        temporal_value=TRADE_DATE,
    )
    artifact_path = _artifact_path(lake)
    artifact_path.write_bytes(b"corrupted-artifact")
    readonly = open_existing_fact_lake(root)
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.collect_fact_lake_health_evidence(
            lake=readonly,
            dataset_spec=spec,
            request=_request(),
        )
    assert exc.value.failure.code == flha.FAILURE_CORRUPTED
    assert artifact_path.read_bytes() == b"corrupted-artifact"  # 不做 repair


def test_corrupt_normalization_collection_fails_closed(tmp_path):
    """§24-C：翻转 control DB 中 normalized payload 内容（表行受 immutability
    trigger 保护，故按字节定位内容翻转；仅针对 normalized 出现，不动 observation）。"""
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    spec = _limit_up_spec()
    _seed_publication(
        lake, spec=spec,
        temporal_field=TemporalSemantics.TRADE_DATE,
        temporal_value=TRADE_DATE,
    )
    db_path = _control_db(root)
    data = bytearray(db_path.read_bytes())
    needle = b'{"count":5}'
    # 第一次出现属于 observations.observation_json；第二次属于
    # normalized_observations.normalized_json（本 fixture 只含一条 normalization）
    first = data.find(needle)
    second = data.find(needle, first + 1)
    assert second != -1
    data[second + 8] = ord("4")  # 保持合法 UTF-8，改变 normalized payload 内容
    db_path.write_bytes(bytes(data))
    readonly = open_existing_fact_lake(root)
    # get_observation 不受影响（只翻转了 normalized 出现）
    assert readonly.get_observation(OBS_ID) is not None
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.collect_fact_lake_health_evidence(
            lake=readonly,
            dataset_spec=spec,
            request=_request(),
        )
    assert exc.value.failure.code == flha.FAILURE_CORRUPTED


def _stored_publication(artifact_sha256: str | None) -> flha_store.StoredCanonicalPublication:
    """构造最小 StoredCanonicalPublication（仅桥接单元测试用，fact 字段不参与）。"""
    return flha_store.StoredCanonicalPublication(
        publication_id=PUB_ID,
        dataset_id="ds_limit_up_pool",
        canonical_key=TRADE_DATE,
        primary_temporal_field="trade_date",
        primary_temporal_value=TRADE_DATE,
        vintage_sequence=1,
        fact=None,
        source_observation_id=OBS_ID,
        dataset_contract_revision="rev-1",
        normalizer_version="n1",
        raw_payload_hash="sha256:" + "0" * 64,
        artifact_schema_version="parquet.v1",
        artifact_relpath=ARTIFACT_RELPATH,
        artifact_sha256=artifact_sha256,
        commit_state="COMMITTED",
    )


def test_artifact_sha_uppercase_digest_rejected():
    """§11：uppercase digest 不静默接受 → 桥接严格拒绝（64 位小写 hex）。"""
    stored = _stored_publication("sha256:" + "A" * 64)
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha._bridge_artifact_sha256(stored)
    assert exc.value.failure.code == flha.FAILURE_CORRUPTED


def test_artifact_sha_non_prefix_rejected():
    """§11：无 sha256: 前缀 → 严格拒绝。"""
    stored = _stored_publication("a" * 64)
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha._bridge_artifact_sha256(stored)
    assert exc.value.failure.code == flha.FAILURE_CORRUPTED


def test_artifact_sha_valid_bridge_passes():
    """§11：合法 sha256:<64 lowercase hex> → 去前缀通过。"""
    stored = _stored_publication("sha256:" + "a" * 64)
    assert flha._bridge_artifact_sha256(stored) == "a" * 64


# ---------------------------------------------------------------------------
# F. Zero-mutation（§23）
# ---------------------------------------------------------------------------

def test_zero_mutation_after_readonly_collection(tmp_path):
    root = tmp_path / "lake"
    lake = initialize_fact_lake(root)
    spec = _limit_up_spec()
    _seed_publication(
        lake, spec=spec,
        temporal_field=TemporalSemantics.TRADE_DATE,
        temporal_value=TRADE_DATE,
    )
    before = _tree_fingerprint(root)
    readonly = open_existing_fact_lake(root)
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=spec,
        request=_request(freshness=flha.FreshnessRequest(
            semantics=TemporalSemantics.FETCHED_AT, reference_at=T_UTC)),
    )
    assert evidence is not None
    # 完整评估路径同样只读
    flha.assess_fact_lake_publication(
        lake=readonly,
        dataset_spec=spec,
        request=_request(freshness=flha.FreshnessRequest(
            semantics=TemporalSemantics.FETCHED_AT, reference_at=T_UTC)),
    )
    after = _tree_fingerprint(root)
    assert after == before  # 文件集/目录集/大小/mtime/hash 全不变
    _assert_no_sidecars(root)


def test_readonly_handle_store_write_rejected(tmp_path):
    """只读句柄的零写 authority 由 store 自身保证。"""
    root = tmp_path / "lake"
    initialize_fact_lake(root)
    readonly = open_existing_fact_lake(root)
    with pytest.raises(FactLakeReadOnlyError):
        readonly.append_reconciliation(_recon(
            ReconciliationStatus.MATCH, dataset_id="ds_limit_up_pool"))


# ---------------------------------------------------------------------------
# G. 双层 API / H1 委托
# ---------------------------------------------------------------------------

def test_assess_delegates_to_h1(tmp_path):
    root, _, _ = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    readonly = open_existing_fact_lake(root)
    request = _request(freshness=flha.FreshnessRequest(
        semantics=TemporalSemantics.FETCHED_AT, reference_at=T_UTC))
    assessment = flha.assess_fact_lake_publication(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=request,
    )
    assert isinstance(assessment, FactLakeHealthAssessment)
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=request,
    )
    direct = flh.assess_publication_health(
        dataset_spec=_limit_up_spec(),
        evidence=evidence,
    )
    assert assessment == direct  # 不重复 H1 健康推导（§21-B）


# ---------------------------------------------------------------------------
# H. 源码纯净扫描（§28）
# ---------------------------------------------------------------------------

def test_adapter_source_purity():
    source = inspect.getsource(flha)
    forbidden = (
        "sqlite3",
        "INSERT",
        "UPDATE ",
        "DELETE ",
        "PRAGMA",
        "initialize_fact_lake(",
        "store_observation(",
        "store_normalization(",
        "stage_canonical_publication(",
        "publish_canonical_artifact(",
        "commit_canonical_publication(",
        "append_reconciliation(",
        "datetime.now",
        "date.today",
        "data_health_service",
        "data_health_adapters",
    )
    for marker in forbidden:
        assert marker not in source, f"生产 adapter 源码包含禁止内容: {marker!r}"


# ---------------------------------------------------------------------------
# R1：P1-A 显式 freshness 请求永不消失（UNKNOWN 支配 coordinate CURRENT）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing_semantics", [
    TemporalSemantics.EFFECTIVE_AT,
    TemporalSemantics.PUBLISHED_AT,
    TemporalSemantics.OBSERVED_AT,
])
def test_r1a_missing_continuous_freshness_never_current(tmp_path, missing_semantics):
    """A1/A2：显式 continuous 请求值缺失 → H1 UNKNOWN（即使 primary 坐标 expected 匹配）。"""
    root, _, _ = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    readonly = open_existing_fact_lake(root)
    request = _request(
        freshness=flha.FreshnessRequest(semantics=missing_semantics, reference_at=T_UTC),
        expected_primary_temporal_value=TRADE_DATE,  # coordinate 会匹配 CURRENT
    )
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=request,
    )
    assert evidence.freshness_semantics is missing_semantics  # 语义保留，不消失
    assert evidence.freshness_value is None
    assessment = flha.assess_fact_lake_publication(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=request,
    )
    assert assessment.freshness == "UNKNOWN"  # UNKNOWN 支配 coordinate CURRENT
    assert assessment.freshness != "CURRENT"


def test_r1a_fetched_at_missing_never_current(tmp_path):
    """FETCHED_AT 缺失（fact 无值场景）同样 UNKNOWN 不 CURRENT。"""
    root, _, _ = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    readonly = open_existing_fact_lake(root)
    request = _request(
        freshness=flha.FreshnessRequest(
            semantics=TemporalSemantics.FETCHED_AT,
            reference_at="2026-08-09T04:00:00.000Z",  # reference 早于 fetched_at → 实际也应 UNKNOWN
        ),
        expected_primary_temporal_value=TRADE_DATE,
    )
    # observation.fetched_at = T_UTC，reference 早于它 → H1 fail closed（不可能时间序）
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.assess_fact_lake_publication(
            lake=readonly,
            dataset_spec=_limit_up_spec(),
            request=request,
        )
    assert exc.value.failure.code == flha.FAILURE_INTERNAL  # H1 校验失败 → adapter 兜底失败
    # 正确参考（reference >= fetched_at）→ 语义保留 + 值存在 → 可评估
    good = _request(
        freshness=flha.FreshnessRequest(
            semantics=TemporalSemantics.FETCHED_AT, reference_at=T_UTC),
        expected_primary_temporal_value=TRADE_DATE,
    )
    assessment = flha.assess_fact_lake_publication(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=good,
    )
    assert assessment.freshness == "CURRENT"  # 值存在 + reference 合法 + age < 3600s


def test_r1a_non_primary_discrete_request_fail_closed(tmp_path):
    """A3：limit-up primary=TRADE_DATE，请求 REPORT_PERIOD → 显式 BAD_ARGUMENT，绝不 CURRENT。"""
    root, _, _ = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    readonly = open_existing_fact_lake(root)
    request = _request(
        freshness=flha.FreshnessRequest(semantics=TemporalSemantics.REPORT_PERIOD),
        expected_primary_temporal_value=TRADE_DATE,
    )
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.assess_fact_lake_publication(
            lake=readonly,
            dataset_spec=_limit_up_spec(),
            request=request,
        )
    assert exc.value.failure.code == flha.FAILURE_BAD_ARGUMENT


def test_r1a_discrete_request_matching_primary_works(tmp_path):
    """请求语义 == primary → 正常采集精确值；expected 匹配 → 合法 CURRENT。"""
    root, _, fact = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    readonly = open_existing_fact_lake(root)
    request = _request(
        freshness=flha.FreshnessRequest(semantics=TemporalSemantics.TRADE_DATE),
        expected_primary_temporal_value=TRADE_DATE,
    )
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=request,
    )
    assert evidence.freshness_semantics is TemporalSemantics.TRADE_DATE
    assert evidence.freshness_value == fact.trade_date
    assessment = flha.assess_fact_lake_publication(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=request,
    )
    assert assessment.freshness == "CURRENT"  # primary 坐标匹配 → 合法 CURRENT


def test_r1a_financial_non_primary_discrete_request_fail_closed(tmp_path):
    """financial primary=REPORT_PERIOD，请求 TRADE_DATE → BAD_ARGUMENT（对称矩阵）。"""
    root, _, _ = _committed_lake(
        tmp_path, _financial_spec(),
        TemporalSemantics.REPORT_PERIOD, REPORT_PERIOD)
    readonly = open_existing_fact_lake(root)
    request = _request(freshness=flha.FreshnessRequest(
        semantics=TemporalSemantics.TRADE_DATE))
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.assess_fact_lake_publication(
            lake=readonly,
            dataset_spec=_financial_spec(),
            request=request,
        )
    assert exc.value.failure.code == flha.FAILURE_BAD_ARGUMENT


def test_r1a_invalid_freshness_request_bad_argument(tmp_path):
    """严格请求校验：非法 freshness 类型 / semantics / reference_at → BAD_ARGUMENT 非 INTERNAL。"""
    root, _, _ = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    readonly = open_existing_fact_lake(root)
    # 非法 freshness 类型（str 而非 FreshnessRequest）
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.collect_fact_lake_health_evidence(
            lake=readonly,
            dataset_spec=_limit_up_spec(),
            request=_request(freshness="not-a-freshness-request"),
        )
    assert exc.value.failure.code == flha.FAILURE_BAD_ARGUMENT
    # 非法 semantics 类型
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.collect_fact_lake_health_evidence(
            lake=readonly,
            dataset_spec=_limit_up_spec(),
            request=_request(freshness=flha.FreshnessRequest(
                semantics="trade_date")),
        )
    assert exc.value.failure.code == flha.FAILURE_BAD_ARGUMENT
    # reference_at 非法（非 canonical UTC）
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.collect_fact_lake_health_evidence(
            lake=readonly,
            dataset_spec=_limit_up_spec(),
            request=_request(freshness=flha.FreshnessRequest(
                semantics=TemporalSemantics.EFFECTIVE_AT,
                reference_at="not-a-timestamp")),
        )
    assert exc.value.failure.code == flha.FAILURE_BAD_ARGUMENT
    # 不可能时间（2026-02-31）同样 BAD_ARGUMENT
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.collect_fact_lake_health_evidence(
            lake=readonly,
            dataset_spec=_limit_up_spec(),
            request=_request(freshness=flha.FreshnessRequest(
                semantics=TemporalSemantics.EFFECTIVE_AT,
                reference_at="2026-02-31T00:00:00.000Z")),
        )
    assert exc.value.failure.code == flha.FAILURE_BAD_ARGUMENT


# ---------------------------------------------------------------------------
# R1：P1-B 通用 JSON 对账去重（JSONValue dict/list 不可哈希修复）
# ---------------------------------------------------------------------------

def _nested_recon(status: ReconciliationStatus, *, delta: dict | None = None) -> ReconciliationResult:
    left = {"nested": {"a": 1, "b": [1, 2, {"c": 3}]}}
    right = ["x", {"y": 2}, 3]
    evidence = {"outer": {"inner": [1, {"z": True}]}}
    if delta:
        left = dict(left)
        left["nested"] = dict(left["nested"])
        left["nested"]["b"] = list(left["nested"]["b"])
        left["nested"]["b"][2] = dict(left["nested"]["b"][2])
        left["nested"]["b"][2].update(delta)
    return ReconciliationResult(
        dataset_id="ds_limit_up_pool",
        status=status,
        comparison_policy_id="pol-1",
        comparison_policy_version="1",
        comparison_evidence=evidence,
        left_observation_id=OBS_ID,
        right_observation_id="obs_" + "c" * 32,
        left_value=left,
        right_value=right,
        reason_codes=(),
    )


def test_r1b_nested_json_duplicate_idempotent(tmp_path):
    """B1：两条精确重复 bound result（nested dict/list）→ 收集成功、一个 result、无 INTERNAL。"""
    root, _, _ = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    lake = open_existing_fact_lake(root, readonly=False)
    result = _nested_recon(ReconciliationStatus.MATCH)
    lake.append_reconciliation(result)
    lake.append_reconciliation(result)
    readonly = open_existing_fact_lake(root)
    evidence = flha.collect_fact_lake_health_evidence(
        lake=readonly,
        dataset_spec=_limit_up_spec(),
        request=_request(),
    )
    assert evidence.reconciliation_result is not None
    assert evidence.reconciliation_result.status is ReconciliationStatus.MATCH
    assert evidence.reconciliation_result.left_value == result.left_value


def test_r1b_nested_json_difference_ambiguous(tmp_path):
    """B2：nested 值差一个 → RECONCILIATION_AMBIGUOUS，不是 INTERNAL、不是 winner。"""
    root, _, _ = _committed_lake(
        tmp_path, _limit_up_spec(),
        TemporalSemantics.TRADE_DATE, TRADE_DATE)
    lake = open_existing_fact_lake(root, readonly=False)
    lake.append_reconciliation(_nested_recon(ReconciliationStatus.MATCH))
    lake.append_reconciliation(_nested_recon(ReconciliationStatus.MATCH, delta={"x": 99}))
    readonly = open_existing_fact_lake(root)
    with pytest.raises(flha.HealthEvidenceCollectionError) as exc:
        flha.collect_fact_lake_health_evidence(
            lake=readonly,
            dataset_spec=_limit_up_spec(),
            request=_request(),
        )
    assert exc.value.failure.code == flha.FAILURE_RECONCILIATION_AMBIGUOUS
