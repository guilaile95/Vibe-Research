"""Fact Lake Dataset Health & Canonical Admissibility Core v0.1 专项测试（DS-L1-H1）。

覆盖 §32 两个必需数据集矩阵（ds_limit_up_pool / ds_financial_indicator）+
§36 全部 acceptance gates + §12-26 关键纪律（无伪造新鲜度 / 无 PIT / 无
provider 切换 / legal-zero / RESTATABLE / 本地 vintage / 无隐式时钟）。
全部纯函数调用：不联网、不落库、不读时钟、不写用户数据。
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest

import fact_lake_health as flh
from data_contracts import (
    CanonicalFact,
    DatasetSpec,
    ProviderRoute,
    ReconciliationResult,
    ReconciliationStatus,
    FetchSemantics,
    HistoryMode,
    ProviderRole,
    QualityStatus,
    RevisionSemantics,
    AdjustmentSemantics,
    TemporalSemantics,
    ProvenanceLink,
)

T_UTC = "2026-08-10T04:00:00.000Z"
OBS_ID = "obs_" + "a" * 32
FACT_ID = "fact_" + "a" * 32


def _route(provider: str = "eastmoney_push2ex", role: str = "canonical") -> ProviderRoute:
    return ProviderRoute(
        route_id=f"route_{provider}",
        provider_id=provider,
        provider_endpoint="/api/snapshot",
        role=ProviderRole(role),
        semantic_contract_id="sem-1",
    )


def _verifier_route() -> ProviderRoute:
    return _route(provider="hithink", role="verifier")


def _link(provider: str = "eastmoney_push2ex", endpoint: str = "/api/snapshot",
          dataset_id: str = "ds_limit_up_pool") -> ProvenanceLink:
    return ProvenanceLink(
        observation_id=OBS_ID,
        dataset_id=dataset_id,
        provider_id=provider,
        provider_endpoint=endpoint,
        source_payload_hash="0" * 64,
        normalizer_version="n1",
    )


def _limit_up_spec(*, with_verifier: bool = False) -> DatasetSpec:
    routes = [_route()]
    if with_verifier:
        routes.append(_verifier_route())
    return DatasetSpec(
        dataset_id="ds_limit_up_pool",
        fetch_semantics=FetchSemantics.BY_DATE,
        history_mode=HistoryMode.BY_DATE,
        routes=tuple(routes),
        governance_revision_id="rev-1",
        required_temporal_fields=(TemporalSemantics.TRADE_DATE,),
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
        point_in_time_supported=False,
        revision_semantics=RevisionSemantics.RESTATABLE,
        adjustment_semantics=AdjustmentSemantics.NOT_APPLICABLE,
    )


def _fact(*, spec: DatasetSpec, quality: QualityStatus = QualityStatus.VALID,
          canonical_key: str = "2026-08-10",
          temporal_field: TemporalSemantics = TemporalSemantics.TRADE_DATE,
          temporal_value: str = "2026-08-10",
          revision_id: str | None = None,
          report_period: str | None = None) -> CanonicalFact:
    kw = {
        "fact_id": FACT_ID,
        "dataset_id": spec.dataset_id,
        "canonical_key": canonical_key,
        "canonical_payload": {"count": 5},
        "canonical_source": "eastmoney_push2ex",
        "dataset_contract_revision": spec.governance_revision_id,
        "revision_semantics": spec.revision_semantics,
        "adjustment_semantics": spec.adjustment_semantics,
        "source_observation_ids": (OBS_ID,),
        "provenance_chain": (_link(provider="eastmoney_push2ex",
                                   dataset_id=spec.dataset_id),),
        "quality_status": quality,
        "reason_codes": ("quality-unknown",) if quality is not QualityStatus.VALID else (),
    }
    if temporal_field is TemporalSemantics.TRADE_DATE:
        kw["trade_date"] = temporal_value
    elif temporal_field is TemporalSemantics.REPORT_PERIOD:
        kw["report_period"] = report_period or temporal_value
    if revision_id is not None:
        kw["revision_id"] = revision_id
    return CanonicalFact(**kw)


def _evidence(
    *,
    spec: DatasetSpec,
    fact: CanonicalFact | None = None,
    commit_state: str = "COMMITTED",
    observations_committed: bool = True,
    raw_integrity: str = "VERIFIED",
    artifact_integrity: str = "VERIFIED",
    replay: str = "MATCH",
    reconciliation: ReconciliationResult | None = None,
    freshness_semantics: TemporalSemantics | None = None,
    freshness_value: str | None = None,
    freshness_reference_at: str | None = None,
    primary_field: TemporalSemantics | None = None,
    primary_value: str | None = None,
    expected: str | None = None,
) -> flh.FactLakeHealthEvidence:
    if fact is None:
        fact = _fact(spec=spec)
    return flh.FactLakeHealthEvidence(
        publication_id="pub_" + "b" * 32,
        dataset_id=spec.dataset_id,
        canonical_key=fact.canonical_key,
        commit_state=commit_state,
        canonical_fact=fact,
        source_observations_committed=observations_committed,
        raw_payload_integrity=raw_integrity,
        artifact_integrity=artifact_integrity,
        artifact_sha256="0" * 64,
        replay_state=replay,
        reconciliation_result=reconciliation,
        freshness_semantics=freshness_semantics,
        freshness_value=freshness_value,
        freshness_reference_at=freshness_reference_at,
        primary_temporal_field=primary_field,
        primary_temporal_value=primary_value,
        expected_primary_temporal_value=expected,
    )


def _recon(status: ReconciliationStatus) -> ReconciliationResult:
    return ReconciliationResult(
        dataset_id="ds_limit_up_pool",
        status=status,
        comparison_policy_id="pol-1",
        comparison_policy_version="1",
        comparison_evidence={},
        left_observation_id=OBS_ID,
        right_observation_id="obs_" + "c" * 32,
        left_value=1,
        right_value=1,
        reason_codes=(),
    )


# ---------------------------------------------------------------------------
# A. 健康核心 / 多维
# ---------------------------------------------------------------------------

def test_committed_all_verified_usable():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec, primary_field=TemporalSemantics.TRADE_DATE,
                   primary_value="2026-08-10", expected="2026-08-10",
                   freshness_semantics=TemporalSemantics.FETCHED_AT,
                   freshness_value=T_UTC, freshness_reference_at=T_UTC)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.publication_visibility == "COMMITTED"
    assert a.storage_integrity == "VERIFIED"
    assert a.reproducibility == "MATCH"
    assert a.semantic_quality == "valid"
    assert a.canonical_admissibility == "USABLE"


def test_multidimensional_not_collapsed_to_bool():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert all(isinstance(getattr(a, f), str) for f in (
        "publication_visibility", "storage_integrity", "reproducibility",
        "semantic_quality", "freshness", "reconciliation", "canonical_admissibility"))


# ---------------------------------------------------------------------------
# B. COMMITTED-only / 契约绑定
# ---------------------------------------------------------------------------

def test_staging_never_healthy():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec, commit_state="STAGING")
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.publication_visibility == "NOT_COMMITTED"
    assert a.canonical_admissibility == "BLOCKED"
    assert flh.REASON_PUBLICATION_NOT_COMMITTED in a.reason_codes


def test_dataset_id_mismatch_blocks():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec)
    ev = flh.FactLakeHealthEvidence(
        publication_id=ev.publication_id, dataset_id="ds_other",
        canonical_key=ev.canonical_key, commit_state="COMMITTED",
        canonical_fact=ev.canonical_fact,
        source_observations_committed=True, raw_payload_integrity="VERIFIED",
        artifact_integrity="VERIFIED", artifact_sha256=None, replay_state="MATCH",
        reconciliation_result=None,
    )
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.canonical_admissibility == "BLOCKED"
    assert flh.REASON_DATASET_ID_MISMATCH in a.reason_codes


def test_canonical_key_mismatch_blocks():
    spec = _limit_up_spec()
    fact = _fact(spec=spec, canonical_key="2026-08-09")
    ev = _evidence(spec=spec, fact=fact)
    ev = flh.FactLakeHealthEvidence(
        publication_id=ev.publication_id, dataset_id=ev.dataset_id,
        canonical_key="2026-08-10",  # 与 fact.canonical_key 不一致
        commit_state="COMMITTED", canonical_fact=fact,
        source_observations_committed=True, raw_payload_integrity="VERIFIED",
        artifact_integrity="VERIFIED", artifact_sha256=None, replay_state="MATCH",
        reconciliation_result=None,
    )
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert flh.REASON_CANONICAL_KEY_MISMATCH in a.reason_codes
    assert a.canonical_admissibility == "BLOCKED"


def test_spec_rejects_fact_blocks():
    spec = _limit_up_spec()
    # required temporal 缺失（TRADE_DATE 为 None）→ validate_fact 抛
    fact = _fact(spec=spec)
    fact = CanonicalFact(
        fact_id=FACT_ID, dataset_id=spec.dataset_id, canonical_key="2026-08-10",
        canonical_payload={"count": 5}, canonical_source="eastmoney_push2ex",
        dataset_contract_revision=spec.governance_revision_id,
        revision_semantics=spec.revision_semantics,
        adjustment_semantics=spec.adjustment_semantics,
        source_observation_ids=(OBS_ID,),
        provenance_chain=(_link(),),
        quality_status=QualityStatus.VALID,
        trade_date=None,  # 缺 required TRADE_DATE
    )
    ev = _evidence(spec=spec, fact=fact)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert flh.REASON_DATASET_SPEC_REJECTED_FACT in a.reason_codes
    assert a.canonical_admissibility == "BLOCKED"


def test_source_observations_not_committed_blocks():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec, observations_committed=False)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert flh.REASON_SOURCE_OBSERVATION_NOT_COMMITTED in a.reason_codes
    assert a.canonical_admissibility == "BLOCKED"


# ---------------------------------------------------------------------------
# C. 存储完整性（§17）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("artifact_integrity,expected_code", [
    ("MISSING", flh.REASON_ARTIFACT_MISSING),
    ("HASH_MISMATCH", flh.REASON_ARTIFACT_HASH_MISMATCH),
    ("SCHEMA_MISMATCH", flh.REASON_ARTIFACT_SCHEMA_MISMATCH),
])
def test_artifact_corruption_blocks(artifact_integrity, expected_code):
    spec = _limit_up_spec()
    ev = _evidence(spec=spec, artifact_integrity=artifact_integrity)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.storage_integrity == "CORRUPTED"
    assert expected_code in a.reason_codes
    assert a.canonical_admissibility == "BLOCKED"


def test_raw_payload_hash_mismatch_blocks():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec, raw_integrity="HASH_MISMATCH")
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.storage_integrity == "CORRUPTED"
    assert flh.REASON_RAW_PAYLOAD_HASH_MISMATCH in a.reason_codes
    assert a.canonical_admissibility == "BLOCKED"


def test_artifact_unverified_not_healthy():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec, artifact_integrity="UNVERIFIED")
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.storage_integrity == "UNVERIFIED"
    assert flh.REASON_ARTIFACT_UNVERIFIED in a.reason_codes
    assert a.canonical_admissibility == "USABLE_WITH_WARNING"


# ---------------------------------------------------------------------------
# D. 回放 / 可复现性（§18）
# ---------------------------------------------------------------------------

def test_replay_mismatch_blocks():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec, replay="MISMATCH")
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.reproducibility == "MISMATCH"
    assert flh.REASON_REPLAY_MISMATCH in a.reason_codes
    assert a.canonical_admissibility == "BLOCKED"


def test_replay_not_run_warning_not_verified():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec, replay="NOT_RUN")
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.reproducibility == "NOT_RUN"
    assert flh.REASON_REPLAY_NOT_RUN in a.reason_codes
    assert a.canonical_admissibility == "USABLE_WITH_WARNING"


def test_replay_unsupported_not_corruption():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec, replay="UNSUPPORTED")
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.reproducibility == "UNSUPPORTED"
    assert a.storage_integrity == "VERIFIED"  # 不是 corruption
    assert flh.REASON_REPLAY_UNSUPPORTED in a.reason_codes


# ---------------------------------------------------------------------------
# E. 语义质量（§19）
# ---------------------------------------------------------------------------

def test_quality_degraded_warning():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec, fact=_fact(spec=spec, quality=QualityStatus.DEGRADED))
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.semantic_quality == "degraded"
    assert flh.REASON_FACT_QUALITY_DEGRADED in a.reason_codes
    assert a.canonical_admissibility == "USABLE_WITH_WARNING"


def test_quality_invalid_blocks():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec, fact=_fact(spec=spec, quality=QualityStatus.INVALID))
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.semantic_quality == "invalid"
    assert flh.REASON_FACT_QUALITY_INVALID in a.reason_codes
    assert a.canonical_admissibility == "BLOCKED"


def test_quality_unknown_not_upgraded():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec, fact=_fact(spec=spec, quality=QualityStatus.UNKNOWN))
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.semantic_quality == "unknown"
    assert flh.REASON_FACT_QUALITY_UNKNOWN in a.reason_codes
    assert a.canonical_admissibility == "USABLE_WITH_WARNING"


# ---------------------------------------------------------------------------
# F. 新鲜度（§12-16：无伪造）
# ---------------------------------------------------------------------------

def test_no_freshness_basis_unknown():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec)  # 无 freshness_semantics
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.freshness == "UNKNOWN"
    assert flh.REASON_FRESHNESS_UNKNOWN in a.reason_codes


def test_by_date_no_expected_value_unknown():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec, freshness_semantics=TemporalSemantics.FETCHED_AT,
                   freshness_value=T_UTC)  # 无 expected
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.freshness == "UNKNOWN"


def test_by_date_expected_match_current():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec, primary_field=TemporalSemantics.TRADE_DATE,
                   primary_value="2026-08-10", expected="2026-08-10",
                   freshness_semantics=TemporalSemantics.FETCHED_AT,
                   freshness_value=T_UTC, freshness_reference_at=T_UTC)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.freshness == "CURRENT"


def test_snapshot_only_freshness_not_applicable():
    spec = DatasetSpec(
        dataset_id="ds_snapshot",
        fetch_semantics=FetchSemantics.SNAPSHOT,
        history_mode=HistoryMode.SNAPSHOT_ONLY,
        routes=(_route(),),
        governance_revision_id="rev-s",
        required_temporal_fields=(TemporalSemantics.TRADE_DATE,),
        revision_semantics=RevisionSemantics.IMMUTABLE,
        adjustment_semantics=AdjustmentSemantics.NOT_APPLICABLE,
    )
    ev = _evidence(spec=spec)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.freshness == "NOT_APPLICABLE"


def test_no_implicit_clock_freshness():
    spec = _limit_up_spec()
    # 无显式 freshness basis、无 expected：绝不从当前时间伪造 CURRENT
    ev = _evidence(spec=spec)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.freshness != "CURRENT"


# ---------------------------------------------------------------------------
# G. 对账（§20-23）
# ---------------------------------------------------------------------------

def test_no_verifier_not_penalized():
    spec = _limit_up_spec(with_verifier=False)
    ev = _evidence(spec=spec, reconciliation=None)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.reconciliation == "not_applicable"
    assert flh.REASON_RECONCILIATION_NOT_RUN not in a.reason_codes
    assert a.canonical_admissibility != "BLOCKED"  # 无 verifier 不是失败


def test_verifier_present_no_result_not_run():
    spec = _limit_up_spec(with_verifier=True)
    ev = _evidence(spec=spec, reconciliation=None)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.reconciliation == "not_run"
    assert flh.REASON_RECONCILIATION_NOT_RUN in a.reason_codes


def test_reconciliation_mismatch_warning_not_corruption():
    spec = _limit_up_spec(with_verifier=True)
    ev = _evidence(spec=spec, reconciliation=_recon(ReconciliationStatus.MISMATCH))
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.reconciliation == "mismatch"
    assert flh.REASON_RECONCILIATION_MISMATCH in a.reason_codes
    assert a.storage_integrity == "VERIFIED"  # 不是 storage corruption
    assert a.canonical_admissibility == "USABLE_WITH_WARNING"


def test_no_provider_switch_on_mismatch():
    spec = _limit_up_spec(with_verifier=True)
    ev = _evidence(spec=spec, reconciliation=_recon(ReconciliationStatus.MISMATCH))
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    # 仅产生 warning 维度，绝不触发 provider 切换（本核心无任何切换副作用）
    assert "switch" not in str(a.to_dict()).lower()
    assert a.canonical_admissibility == "USABLE_WITH_WARNING"


# ---------------------------------------------------------------------------
# H. legal-zero / RESTATABLE / 本地 vintage（§24-26）
# ---------------------------------------------------------------------------

def test_legal_zero_not_generic_failure():
    spec = _limit_up_spec()
    fact = _fact(spec=spec, canonical_key="2026-08-10")
    fact = CanonicalFact(
        fact_id=FACT_ID, dataset_id=spec.dataset_id, canonical_key="2026-08-10",
        canonical_payload=[],  # legal zero
        canonical_source="eastmoney_push2ex",
        dataset_contract_revision=spec.governance_revision_id,
        revision_semantics=spec.revision_semantics,
        adjustment_semantics=spec.adjustment_semantics,
        source_observation_ids=(OBS_ID,),
        provenance_chain=(_link(),),
        quality_status=QualityStatus.VALID,
        trade_date="2026-08-10",
    )
    ev = _evidence(spec=spec, fact=fact)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.canonical_admissibility != "BLOCKED"  # 空 payload 不是通用失败
    assert flh.REASON_DATASET_SPEC_REJECTED_FACT not in a.reason_codes


def test_restatable_multiple_revisions_not_corruption():
    spec = _financial_spec()
    for rev in ("rev-1", "rev-2"):
        fact = _fact(spec=spec, temporal_field=TemporalSemantics.REPORT_PERIOD,
                     temporal_value="2026-06-30", report_period="2026-06-30",
                     revision_id=rev, canonical_key=f"2026-06-30-{rev}")
        ev = _evidence(spec=spec, fact=fact,
                       primary_field=TemporalSemantics.REPORT_PERIOD,
                       primary_value="2026-06-30")
        a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
        assert a.canonical_admissibility != "BLOCKED"  # 多 revision 合法，非 corruption
        assert a.storage_integrity != "CORRUPTED"


def test_report_period_no_trade_date_required():
    spec = _financial_spec()
    fact = _fact(spec=spec, temporal_field=TemporalSemantics.REPORT_PERIOD,
                 temporal_value="2026-06-30", report_period="2026-06-30")
    ev = _evidence(spec=spec, fact=fact)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert flh.REASON_DATASET_SPEC_REJECTED_FACT not in a.reason_codes  # 不需要 trade_date


def test_no_latest_row_wins_restatable():
    spec = _financial_spec()
    # 两条不同 revision 的 fact 各自评估 → 各自独立健康，不做 latest-wins 合并
    f1 = _fact(spec=spec, temporal_field=TemporalSemantics.REPORT_PERIOD,
               temporal_value="2026-06-30", report_period="2026-06-30",
               revision_id="rev-1", canonical_key="k-1")
    f2 = _fact(spec=spec, temporal_field=TemporalSemantics.REPORT_PERIOD,
               temporal_value="2026-06-30", report_period="2026-06-30",
               revision_id="rev-2", canonical_key="k-2")
    a1 = flh.assess_publication_health(dataset_spec=spec, evidence=_evidence(spec=spec, fact=f1))
    a2 = flh.assess_publication_health(dataset_spec=spec, evidence=_evidence(spec=spec, fact=f2))
    assert a1.canonical_key == "k-1" and a2.canonical_key == "k-2"  # 各自保留


def test_vintage_not_provider_revision():
    # 健康核心不解释 vintage_sequence —— 只评估传入的 fact/evidence
    spec = _limit_up_spec()
    ev = _evidence(spec=spec)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert "vintage" not in str(a.to_dict()).lower()


# ---------------------------------------------------------------------------
# I. temporal index consistency（§11）
# ---------------------------------------------------------------------------

def test_temporal_index_mismatch_blocks():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec, primary_field=TemporalSemantics.TRADE_DATE,
                   primary_value="2026-08-09")  # 与 fact 的 2026-08-10 不一致
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert flh.REASON_TEMPORAL_INDEX_MISMATCH in a.reason_codes
    assert a.canonical_admissibility == "BLOCKED"


def test_temporal_index_absent_no_fail():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec)  # 未提供 primary temporal
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert flh.REASON_TEMPORAL_INDEX_MISMATCH not in a.reason_codes


# ---------------------------------------------------------------------------
# J. 确定性 / 严格序列化 / reason codes / 纯性
# ---------------------------------------------------------------------------

def test_deterministic_same_inputs():
    spec = _limit_up_spec()
    ev1 = _evidence(spec=spec)
    ev2 = _evidence(spec=spec)
    a1 = flh.assess_publication_health(dataset_spec=spec, evidence=ev1)
    a2 = flh.assess_publication_health(dataset_spec=spec, evidence=ev2)
    assert a1 == a2
    assert a1.reason_codes == a2.reason_codes


def test_reason_codes_deterministic_order_no_duplicates():
    spec = _limit_up_spec(with_verifier=True)
    ev = _evidence(spec=spec, commit_state="STAGING", raw_integrity="HASH_MISMATCH",
                   artifact_integrity="MISSING", replay="MISMATCH",
                   fact=_fact(spec=spec, quality=QualityStatus.INVALID))
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert len(a.reason_codes) == len(set(a.reason_codes))  # 无重复
    # 确定性顺序：按固定优先级表，非输入顺序
    assert a.reason_codes == tuple(sorted(set(a.reason_codes),
                                          key=lambda c: flh._REASON_RANK.get(c, 999)))


def test_assessment_round_trip_strict():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    restored = flh.FactLakeHealthAssessment.from_dict(a.to_dict())
    assert restored == a
    # 未知字段拒绝
    with pytest.raises(flh.HealthValidationError):
        flh.FactLakeHealthAssessment.from_dict({**a.to_dict(), "bogus": 1})


def test_evidence_rejects_unknown_enum():
    spec = _limit_up_spec()
    with pytest.raises(flh.HealthValidationError):
        _evidence(spec=spec, commit_state="WHATEVER")


def test_module_imports_no_fact_lake_store_or_data_health():
    source = inspect.getsource(flh)
    for forbidden in ("fact_lake_store", "data_health_service", "data_health_adapters"):
        assert forbidden not in source, f"health 模块不得引用 {forbidden}"


def test_module_import_zero_filesystem_side_effects():
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    watch_dir = os.environ["VR_DATA_DIR"]  # conftest 指向 mkdtemp
    script = (
        "import os, sys\n"
        "sys.path.insert(0, r'%s')\n"
        "watch = r'%s'\n"
        "before = set(os.listdir(watch))\n"
        "import fact_lake_health\n"
        "after = set(os.listdir(watch))\n"
        "assert not (after - before), 'import 产生文件副作用'\n"
        "print('CLEAN_IMPORT')\n"
    ) % (backend_dir, watch_dir)
    env = dict(os.environ)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          env=env, timeout=120, cwd=backend_dir)
    assert proc.returncode == 0, proc.stderr
    assert "CLEAN_IMPORT" in proc.stdout


def test_projection_prevalidation():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    with pytest.raises(flh.HealthValidationError):
        flh.assessments_for_dataset("ds_limit_up_pool", [a, "not-an-assessment"])
    assert flh.assessments_for_dataset("ds_limit_up_pool", [a]) == [a]
    assert flh.assessment_for_publication(a.publication_id, [a]) == a


# ---------------------------------------------------------------------------
# R1：P1-A 新鲜度（显式 reference + max_staleness 实际年龄）
# ---------------------------------------------------------------------------

OBSERVED_9H = "2026-08-09T19:00:00.000Z"   # reference 前 9 小时
REFERENCE = "2026-08-10T04:00:00.000Z"     # = T_UTC（9h = 32400s）


def _stale_spec(max_staleness: int = 300) -> DatasetSpec:
    return DatasetSpec(
        dataset_id="ds_limit_up_pool",
        fetch_semantics=FetchSemantics.BY_DATE,
        history_mode=HistoryMode.BY_DATE,
        routes=(_route(),),
        governance_revision_id="rev-1",
        required_temporal_fields=(TemporalSemantics.TRADE_DATE,),
        point_in_time_supported=False,
        revision_semantics=RevisionSemantics.IMMUTABLE,
        adjustment_semantics=AdjustmentSemantics.NOT_APPLICABLE,
        max_staleness_seconds=max_staleness,
    )


def test_r1a_expected_match_but_old_observed_stale():
    """expected TRADE_DATE 匹配，但 OBSERVED_AT 9h old + max_staleness=300 +
    显式 reference_at → STALE，绝不 CURRENT。"""
    spec = _stale_spec(max_staleness=300)
    ev = _evidence(spec=spec, primary_field=TemporalSemantics.TRADE_DATE,
                   primary_value="2026-08-10", expected="2026-08-10",
                   freshness_semantics=TemporalSemantics.OBSERVED_AT,
                   freshness_value=OBSERVED_9H, freshness_reference_at=REFERENCE)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.freshness == "STALE"
    assert a.freshness != "CURRENT"


def test_r1b_reference_absent_unknown():
    """同条件但 reference_at 缺失 → UNKNOWN（不猜墙钟）。"""
    spec = _stale_spec(max_staleness=300)
    ev = _evidence(spec=spec, primary_field=TemporalSemantics.TRADE_DATE,
                   primary_value="2026-08-10", expected="2026-08-10",
                   freshness_semantics=TemporalSemantics.OBSERVED_AT,
                   freshness_value=OBSERVED_9H)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.freshness == "UNKNOWN"
    assert a.freshness != "CURRENT"


def test_r1c_age_exactly_threshold_frozen_stale():
    """age 恰好等于 threshold → 冻结边界为 STALE（fail closed，不宽松）。"""
    spec = _stale_spec(max_staleness=300)
    exact = "2026-08-10T03:55:00.000Z"  # 距 REFERENCE 恰好 300s
    ev = _evidence(spec=spec, primary_field=TemporalSemantics.TRADE_DATE,
                   primary_value="2026-08-10", expected="2026-08-10",
                   freshness_semantics=TemporalSemantics.OBSERVED_AT,
                   freshness_value=exact, freshness_reference_at=REFERENCE)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.freshness == "STALE"


def test_r1d_reference_before_freshness_value_reject():
    """reference_at 早于 freshness_value → fail closed。"""
    spec = _stale_spec()
    ev = _evidence(spec=spec, primary_field=TemporalSemantics.TRADE_DATE,
                   primary_value="2026-08-10", expected="2026-08-10",
                   freshness_semantics=TemporalSemantics.OBSERVED_AT,
                   freshness_value=REFERENCE,  # 晚于 reference
                   freshness_reference_at=OBSERVED_9H)
    with pytest.raises(flh.HealthValidationError):
        flh.assess_publication_health(dataset_spec=spec, evidence=ev)


def test_r1e_snapshot_only_continuous_freshness_preserved():
    """SNAPSHOT_ONLY：显式连续 staleness 契约不被抹除（保留评估）。"""
    spec = DatasetSpec(
        dataset_id="ds_snapshot",
        fetch_semantics=FetchSemantics.SNAPSHOT,
        history_mode=HistoryMode.SNAPSHOT_ONLY,
        routes=(_route(),),
        governance_revision_id="rev-s",
        required_temporal_fields=(TemporalSemantics.TRADE_DATE,),
        revision_semantics=RevisionSemantics.IMMUTABLE,
        adjustment_semantics=AdjustmentSemantics.NOT_APPLICABLE,
        max_staleness_seconds=300,
    )
    ev = _evidence(spec=spec, freshness_semantics=TemporalSemantics.OBSERVED_AT,
                   freshness_value=OBSERVED_9H, freshness_reference_at=REFERENCE)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.freshness == "STALE"  # 连续契约可评估，不因 snapshot_only 抹除


# ---------------------------------------------------------------------------
# R1：P1-B 对账身份绑定 + persisted 保留
# ---------------------------------------------------------------------------

def test_r1b_other_dataset_match_rejected():
    spec = _limit_up_spec(with_verifier=True)
    other = ReconciliationResult(
        dataset_id="ds_other", status=ReconciliationStatus.MATCH,
        comparison_policy_id="p", comparison_policy_version="1",
        comparison_evidence={}, left_observation_id=OBS_ID,
        right_observation_id="obs_" + "c" * 32, left_value=1, right_value=1,
        reason_codes=())
    ev = _evidence(spec=spec, reconciliation=other)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert flh.REASON_RECONCILIATION_UNBOUND in a.reason_codes
    assert a.canonical_admissibility == "BLOCKED"


def test_r1b_unrelated_observation_match_rejected():
    spec = _limit_up_spec(with_verifier=True)
    unrelated = ReconciliationResult(
        dataset_id="ds_limit_up_pool", status=ReconciliationStatus.MATCH,
        comparison_policy_id="p", comparison_policy_version="1",
        comparison_evidence={}, left_observation_id="obs_" + "x" * 32,
        right_observation_id="obs_" + "y" * 32, left_value=1, right_value=1,
        reason_codes=())
    ev = _evidence(spec=spec, reconciliation=unrelated)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert flh.REASON_RECONCILIATION_UNBOUND in a.reason_codes
    assert a.canonical_admissibility == "BLOCKED"


def test_r1b_persisted_mismatch_no_verifier_observable():
    """fact.reconciliation_status=MISMATCH + 无 verifier → mismatch 保持可见（不静默抹除）。"""
    spec = _limit_up_spec(with_verifier=False)
    fact = _fact(spec=spec, quality=QualityStatus.VALID)
    fact = CanonicalFact(
        fact_id=FACT_ID, dataset_id=spec.dataset_id, canonical_key="2026-08-10",
        canonical_payload={"count": 5}, canonical_source="eastmoney_push2ex",
        dataset_contract_revision=spec.governance_revision_id,
        revision_semantics=spec.revision_semantics,
        adjustment_semantics=spec.adjustment_semantics,
        source_observation_ids=(OBS_ID,),
        provenance_chain=(_link(dataset_id=spec.dataset_id),),
        quality_status=QualityStatus.VALID,
        reconciliation_status=ReconciliationStatus.MISMATCH,
        reason_codes=("recon-mismatch",),
        trade_date="2026-08-10",
    )
    ev = _evidence(spec=spec, fact=fact)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert a.reconciliation == "mismatch"  # persisted 状态保留可见
    assert flh.REASON_RECONCILIATION_MISMATCH in a.reason_codes


def test_r1b_persisted_match_supplied_mismatch_drift_rejected():
    """persisted MATCH + supplied MISMATCH → 证据不一致 fail-closed，绝不静默 MATCH/USABLE。"""
    spec = _limit_up_spec(with_verifier=True)
    fact = _fact(spec=spec, quality=QualityStatus.VALID)
    fact = CanonicalFact(
        fact_id=FACT_ID, dataset_id=spec.dataset_id, canonical_key="2026-08-10",
        canonical_payload={"count": 5}, canonical_source="eastmoney_push2ex",
        dataset_contract_revision=spec.governance_revision_id,
        revision_semantics=spec.revision_semantics,
        adjustment_semantics=spec.adjustment_semantics,
        source_observation_ids=(OBS_ID,),
        provenance_chain=(_link(dataset_id=spec.dataset_id),),
        quality_status=QualityStatus.VALID,
        reconciliation_status=ReconciliationStatus.MATCH,
        reason_codes=(),
        trade_date="2026-08-10",
    )
    ev = _evidence(spec=spec, fact=fact, reconciliation=_recon(ReconciliationStatus.MISMATCH))
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert flh.REASON_RECONCILIATION_STATUS_DRIFT in a.reason_codes
    assert a.canonical_admissibility == "BLOCKED"
    assert a.reconciliation != "match"  # 绝不静默 MATCH


# ---------------------------------------------------------------------------
# R1：P1-C temporal 权威（REPORT_PERIOD 非强制 YYYY-MM-DD / 真实校验）
# ---------------------------------------------------------------------------

def test_r1c_report_period_q2_quarter_valid():
    """REPORT_PERIOD='2026Q2' 在 DS-A1 下有效 → H1 接受。"""
    spec = _financial_spec()
    fact = _fact(spec=spec, temporal_field=TemporalSemantics.REPORT_PERIOD,
                 temporal_value="2026Q2", report_period="2026Q2")
    ev = _evidence(spec=spec, fact=fact)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert flh.REASON_DATASET_SPEC_REJECTED_FACT not in a.reason_codes
    assert a.canonical_admissibility != "BLOCKED"


def test_r1c_invalid_trade_date_rejected():
    """TRADE_DATE 2026-02-31（不存在）→ reject。"""
    spec = _limit_up_spec()
    with pytest.raises(flh.HealthValidationError):
        _evidence(spec=spec, primary_field=TemporalSemantics.TRADE_DATE,
                  primary_value="2026-02-31")


def test_r1c_impossible_utc_rejected():
    """不可能 UTC 时间戳（2026-02-31T00:00:00Z）→ reject。"""
    spec = _limit_up_spec()
    with pytest.raises(flh.HealthValidationError):
        _evidence(spec=spec, freshness_semantics=TemporalSemantics.OBSERVED_AT,
                  freshness_value="2026-02-31T00:00:00.000Z")


def test_r1c_invalid_expected_for_trade_date_rejected():
    """expected TRADE_DATE 非法日期 → reject。"""
    spec = _limit_up_spec()
    with pytest.raises(flh.HealthValidationError):
        _evidence(spec=spec, primary_field=TemporalSemantics.TRADE_DATE,
                  primary_value="2026-08-10", expected="not-a-date")


def test_r1c_expected_without_primary_field_rejected():
    """提供 expected 但无 primary field 契约 → fail closed。"""
    spec = _limit_up_spec()
    with pytest.raises(flh.HealthValidationError):
        _evidence(spec=spec, expected="2026-08-10")


def test_r1c_financial_yyyy_mm_dd_fixture_preserved():
    """既有 financial YYYY-MM-DD fixture 仍有效。"""
    spec = _financial_spec()
    fact = _fact(spec=spec, temporal_field=TemporalSemantics.REPORT_PERIOD,
                 temporal_value="2026-06-30", report_period="2026-06-30")
    ev = _evidence(spec=spec, fact=fact)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    assert flh.REASON_DATASET_SPEC_REJECTED_FACT not in a.reason_codes


# ---------------------------------------------------------------------------
# R1：P1-D 严格 assessment 校验（from_dict + projection 不信任 dataclass）
# ---------------------------------------------------------------------------

def test_r1d_direct_dataclass_invalid_admissibility_projection_reject():
    """直接构造非法 dataclass（非法 admissibility）→ projection 拒绝。"""
    spec = _limit_up_spec()
    ev = _evidence(spec=spec)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    from dataclasses import replace
    bad = replace(a, canonical_admissibility="WEIRD")
    with pytest.raises(flh.HealthValidationError):
        flh.assessments_for_dataset("ds_limit_up_pool", [bad])


def test_r1d_integer_dataset_id_from_dict_reject():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    data = a.to_dict()
    data["dataset_id"] = 123
    with pytest.raises(flh.HealthValidationError):
        flh.FactLakeHealthAssessment.from_dict(data)


def test_r1d_unknown_reason_code_from_dict_reject():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    data = a.to_dict()
    data["reason_codes"] = ["NOT_A_REAL_CODE"]
    with pytest.raises(flh.HealthValidationError):
        flh.FactLakeHealthAssessment.from_dict(data)


def test_r1d_valid_assessment_round_trip_remains_pass():
    spec = _limit_up_spec()
    ev = _evidence(spec=spec)
    a = flh.assess_publication_health(dataset_spec=spec, evidence=ev)
    restored = flh.FactLakeHealthAssessment.from_dict(a.to_dict())
    assert restored == a
    assert flh.assessment_for_publication(a.publication_id, [a]) == a
