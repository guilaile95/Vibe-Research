"""Fact Lake Health → Legacy Data Health Semantic Projection Core v0.1 专项测试（DS-L1-H3）。

覆盖 §32 评估矩阵 A-N、§33 集合失败矩阵、§34 legacy parity（status/error_code/
error_summary 全对既有权威）、§9 严格输入、§24 lossiness、§30 determinism、
§35 源码纯净扫描。纯函数调用：不联网、不落库、不读时钟、不写用户数据。
"""
from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

import fact_lake_health_legacy_projection as flhp
from data_health_service import ERROR_SUMMARIES, VALID_STATUSES, error_summary
from fact_lake_health import FactLakeHealthAssessment
from fact_lake_health_adapter import HealthEvidenceCollectionFailure


def _assessment(
    *,
    canonical_admissibility: str = "USABLE",
    publication_visibility: str = "COMMITTED",
    storage_integrity: str = "VERIFIED",
    reproducibility: str = "MATCH",
    semantic_quality: str = "valid",
    freshness: str = "CURRENT",
    reconciliation: str = "match",
    reason_codes: tuple[str, ...] = (),
    dataset_id: str = "ds_limit_up_pool",
    canonical_key: str = "2026-08-10",
    publication_id: str = "pub_" + "b" * 32,
) -> FactLakeHealthAssessment:
    return FactLakeHealthAssessment(
        dataset_id=dataset_id,
        canonical_key=canonical_key,
        publication_id=publication_id,
        publication_visibility=publication_visibility,
        storage_integrity=storage_integrity,
        reproducibility=reproducibility,
        semantic_quality=semantic_quality,
        freshness=freshness,
        reconciliation=reconciliation,
        canonical_admissibility=canonical_admissibility,
        reason_codes=reason_codes,
    )


def _project(assessment: FactLakeHealthAssessment) -> flhp.FactLakeLegacyHealthProjection:
    return flhp.project_fact_lake_health(assessment=assessment)


def _failure(code: str) -> HealthEvidenceCollectionFailure:
    return HealthEvidenceCollectionFailure(code=code, detail="test")


# ---------------------------------------------------------------------------
# A. 评估矩阵（§32）
# ---------------------------------------------------------------------------

def test_matrix_a_clean_usable_to_normal():
    p = _project(_assessment())
    assert p.legacy_status == "normal"
    assert p.legacy_is_stale is False
    assert p.legacy_is_degraded is False
    assert p.legacy_error_code is None
    assert p.legacy_error_summary is None
    assert p.lossiness == flhp.LOSSINESS_EXACT
    assert p.source_kind == flhp.SOURCE_KIND_ASSESSMENT
    assert p.collection_failure_code is None
    assert p.fact_lake_canonical_admissibility == "USABLE"
    assert p.fact_lake_reason_codes == ()


def test_matrix_b_stale_only_to_normal_stale():
    p = _project(_assessment(
        canonical_admissibility="USABLE_WITH_WARNING",
        freshness="STALE",
        reason_codes=("TEMPORAL_VALUE_STALE",),
    ))
    assert p.legacy_status == "normal"  # stale 是独立 legacy 轴
    assert p.legacy_is_stale is True
    assert p.legacy_is_degraded is False
    assert p.legacy_error_code == "SOURCE_STALE"
    assert p.legacy_error_summary == error_summary("SOURCE_STALE")
    assert p.lossiness == flhp.LOSSINESS_EXACT  # stale-only 可精确表达


def test_matrix_c_replay_not_run_to_partial():
    p = _project(_assessment(
        canonical_admissibility="USABLE_WITH_WARNING",
        reason_codes=("REPLAY_NOT_RUN",),
    ))
    assert p.legacy_status == "partial"
    assert p.legacy_is_stale is False
    assert p.legacy_error_code == "SOURCE_PARTIAL"
    assert p.lossiness == flhp.LOSSINESS_LOSSY


def test_matrix_d_quality_degraded_to_source_degraded():
    p = _project(_assessment(
        canonical_admissibility="USABLE_WITH_WARNING",
        semantic_quality="degraded",
        reason_codes=("FACT_QUALITY_DEGRADED",),
    ))
    assert p.legacy_status == "partial"
    assert p.legacy_is_degraded is True
    assert p.legacy_error_code == "SOURCE_DEGRADED"


def test_matrix_e_freshness_unknown_to_partial():
    p = _project(_assessment(
        canonical_admissibility="USABLE_WITH_WARNING",
        freshness="UNKNOWN",
        reason_codes=("FRESHNESS_UNKNOWN",),
    ))
    assert p.legacy_status == "partial"
    assert p.legacy_is_stale is False
    assert p.legacy_error_code == "SOURCE_PARTIAL"


def test_matrix_f_reconciliation_mismatch_to_partial():
    p = _project(_assessment(
        canonical_admissibility="USABLE_WITH_WARNING",
        reconciliation="mismatch",
        reason_codes=("RECONCILIATION_MISMATCH",),
    ))
    assert p.legacy_status == "partial"
    assert p.legacy_error_code == "SOURCE_PARTIAL"
    assert p.legacy_is_degraded is False  # §15：非 quality degraded 不全量标 degraded


def test_matrix_g_stale_plus_replay_not_run_partial():
    p = _project(_assessment(
        canonical_admissibility="USABLE_WITH_WARNING",
        freshness="STALE",
        reason_codes=("TEMPORAL_VALUE_STALE", "REPLAY_NOT_RUN"),
    ))
    assert p.legacy_status == "partial"
    assert p.legacy_is_stale is True
    assert p.legacy_error_code == "SOURCE_PARTIAL"  # §16：stale+其他 warning → 非 SOURCE_STALE


def test_matrix_h_stale_plus_quality_degraded():
    p = _project(_assessment(
        canonical_admissibility="USABLE_WITH_WARNING",
        freshness="STALE",
        semantic_quality="degraded",
        reason_codes=("TEMPORAL_VALUE_STALE", "FACT_QUALITY_DEGRADED"),
    ))
    assert p.legacy_status == "partial"
    assert p.legacy_is_stale is True  # is_stale 仍 True
    assert p.legacy_is_degraded is True
    assert p.legacy_error_code == "SOURCE_DEGRADED"  # degraded 优先


def test_matrix_i_storage_corrupted_unavailable():
    p = _project(_assessment(
        canonical_admissibility="BLOCKED",
        storage_integrity="CORRUPTED",
        reason_codes=("ARTIFACT_HASH_MISMATCH",),
    ))
    assert p.legacy_status == "unavailable"
    assert p.legacy_error_code == "SOURCE_CORRUPTED"


def test_matrix_j_schema_incompatible_unavailable():
    p = _project(_assessment(
        canonical_admissibility="BLOCKED",
        reason_codes=("ARTIFACT_SCHEMA_MISMATCH",),
    ))
    assert p.legacy_status == "unavailable"
    assert p.legacy_error_code == "SOURCE_SCHEMA_INCOMPATIBLE"


def test_matrix_k_replay_mismatch_unavailable():
    p = _project(_assessment(
        canonical_admissibility="BLOCKED",
        reproducibility="MISMATCH",
        reason_codes=("REPLAY_MISMATCH",),
    ))
    assert p.legacy_status == "unavailable"
    assert p.legacy_error_code == "SOURCE_UNAVAILABLE"  # 不误标为 corruption


def test_matrix_l_reconciliation_drift_unavailable():
    p = _project(_assessment(
        canonical_admissibility="BLOCKED",
        reason_codes=("RECONCILIATION_STATUS_DRIFT",),
    ))
    assert p.legacy_status == "unavailable"
    assert p.legacy_error_code == "SOURCE_UNAVAILABLE"


def test_matrix_m_usable_claim_storage_corrupted_floor():
    """§10/§11：USABLE 声称 + CORRUPTED 维度 → 地板保守 unavailable。"""
    p = _project(_assessment(
        canonical_admissibility="USABLE",
        storage_integrity="CORRUPTED",
        reason_codes=(),
    ))
    assert p.legacy_status == "unavailable"
    assert p.legacy_error_code == "SOURCE_CORRUPTED"


def test_matrix_n_reason_order_independent():
    """§30：reason code 顺序不影响 legacy_status/is_stale/is_degraded/error_code/lossiness。
    （fact_lake_reason_codes 本身按 §25 保留原顺序。）"""
    a = _assessment(
        canonical_admissibility="USABLE_WITH_WARNING",
        freshness="STALE",
        reason_codes=("TEMPORAL_VALUE_STALE", "REPLAY_NOT_RUN"),
    )
    b = replace(a, reason_codes=("REPLAY_NOT_RUN", "TEMPORAL_VALUE_STALE"))
    pa, pb = _project(a), _project(b)
    assert pa.legacy_status == pb.legacy_status
    assert pa.legacy_is_stale == pb.legacy_is_stale
    assert pa.legacy_is_degraded == pb.legacy_is_degraded
    assert pa.legacy_error_code == pb.legacy_error_code
    assert pa.lossiness == pb.lossiness


# ---------------------------------------------------------------------------
# B. 硬失败地板其余维度（§11）
# ---------------------------------------------------------------------------

def test_hard_fail_not_committed_floor():
    p = _project(_assessment(
        publication_visibility="NOT_COMMITTED",
        canonical_admissibility="BLOCKED",
        reason_codes=("PUBLICATION_NOT_COMMITTED",),
    ))
    assert p.legacy_status == "unavailable"
    assert p.legacy_error_code == "SOURCE_UNAVAILABLE"


def test_hard_fail_semantic_invalid_floor():
    p = _project(_assessment(
        canonical_admissibility="USABLE",
        semantic_quality="invalid",
        reason_codes=("FACT_QUALITY_INVALID",),
    ))
    assert p.legacy_status == "unavailable"
    assert p.legacy_error_code == "SOURCE_UNAVAILABLE"


def test_hard_fail_reproducibility_mismatch_floor():
    p = _project(_assessment(
        canonical_admissibility="USABLE",
        reproducibility="MISMATCH",
        reason_codes=("REPLAY_MISMATCH",),
    ))
    assert p.legacy_status == "unavailable"
    assert p.legacy_error_code == "SOURCE_UNAVAILABLE"


# ---------------------------------------------------------------------------
# C. 多 blocker 优先级（§18）：CORRUPTED > SCHEMA > UNAVAILABLE
# ---------------------------------------------------------------------------

def test_multi_blocker_corrupted_wins_over_schema():
    p = _project(_assessment(
        canonical_admissibility="BLOCKED",
        storage_integrity="CORRUPTED",
        reason_codes=("ARTIFACT_HASH_MISMATCH", "ARTIFACT_SCHEMA_MISMATCH"),
    ))
    assert p.legacy_error_code == "SOURCE_CORRUPTED"


def test_multi_blocker_schema_wins_over_generic():
    p = _project(_assessment(
        canonical_admissibility="BLOCKED",
        reason_codes=("ARTIFACT_SCHEMA_MISMATCH", "REPLAY_MISMATCH"),
    ))
    assert p.legacy_error_code == "SOURCE_SCHEMA_INCOMPATIBLE"


def test_multi_blocker_generic_default():
    p = _project(_assessment(
        canonical_admissibility="BLOCKED",
        reason_codes=("RECONCILIATION_UNBOUND", "REPLAY_MISMATCH"),
    ))
    assert p.legacy_error_code == "SOURCE_UNAVAILABLE"


# ---------------------------------------------------------------------------
# D. 集合失败矩阵（§20/§21）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code,expected", [
    ("FACT_LAKE_NOT_INITIALIZED", "SOURCE_NOT_INITIALIZED"),
    ("FACT_LAKE_SCHEMA_UNSUPPORTED", "SOURCE_SCHEMA_INCOMPATIBLE"),
    ("FACT_LAKE_CORRUPTED", "SOURCE_CORRUPTED"),
    ("FACT_LAKE_PATH_UNSAFE", "SOURCE_CORRUPTED"),
    ("FACT_LAKE_BUSY", "SOURCE_UNAVAILABLE"),
    ("PUBLICATION_NOT_VISIBLE", "SOURCE_UNAVAILABLE"),
    ("RECONCILIATION_AMBIGUOUS", "SOURCE_UNAVAILABLE"),
])
def test_collection_failure_mapping(code, expected):
    p = flhp.project_fact_lake_health(collection_failure=_failure(code))
    assert p.legacy_status == "unavailable"
    assert p.legacy_error_code == expected
    assert p.source_kind == flhp.SOURCE_KIND_COLLECTION_FAILURE
    assert p.collection_failure_code == code
    assert p.lossiness == flhp.LOSSINESS_LOSSY
    assert p.fact_lake_canonical_admissibility is None
    assert p.legacy_is_stale is False


@pytest.mark.parametrize("code", ["BAD_ARGUMENT", "INTERNAL"])
def test_non_data_health_failure_rejected(code):
    """§21：编程/调用方错误绝不投影为数据源健康状态。"""
    with pytest.raises(flhp.LegacyProjectionError):
        flhp.project_fact_lake_health(collection_failure=_failure(code))


def test_no_fake_timeout():
    """§22：本地集合失败绝不发明 SOURCE_TIMEOUT。"""
    assert "SOURCE_TIMEOUT" not in flhp._COLLECTION_FAILURE_MAPPING.values()


# ---------------------------------------------------------------------------
# E. 严格输入权威（§9）
# ---------------------------------------------------------------------------

def test_strict_input_mapping_accepted():
    """Mapping 输入也经严格 H1 from_dict。"""
    a = _assessment()
    p = flhp.project_fact_lake_health(assessment=a.to_dict())
    assert p.legacy_status == "normal"


def test_strict_input_unknown_reason_rejected():
    bad = replace(_assessment(), reason_codes=("NOT_A_REAL_CODE",))
    with pytest.raises(flhp.LegacyProjectionError):
        _project(bad)


def test_strict_input_invalid_enum_rejected():
    bad = replace(_assessment(), semantic_quality="weird")
    with pytest.raises(flhp.LegacyProjectionError):
        _project(bad)


def test_strict_input_bad_schema_rejected():
    data = _assessment().to_dict()
    data["schema_version"] = "other.v1"
    with pytest.raises(flhp.LegacyProjectionError):
        flhp.project_fact_lake_health(assessment=data)


def test_must_provide_exactly_one_source():
    with pytest.raises(flhp.LegacyProjectionError):
        flhp.project_fact_lake_health()
    with pytest.raises(flhp.LegacyProjectionError):
        flhp.project_fact_lake_health(
            assessment=_assessment(),
            collection_failure=_failure("FACT_LAKE_BUSY"),
        )


# ---------------------------------------------------------------------------
# F. Legacy parity（§34）
# ---------------------------------------------------------------------------

def test_legacy_parity_all_emitted_values():
    """所有输出的 status/error_code/error_summary 对既有权威完全一致。"""
    samples = [
        _project(_assessment()),
        _project(_assessment(
            canonical_admissibility="USABLE_WITH_WARNING", freshness="STALE",
            reason_codes=("TEMPORAL_VALUE_STALE",))),
        _project(_assessment(
            canonical_admissibility="USABLE_WITH_WARNING",
            reason_codes=("REPLAY_NOT_RUN",))),
        _project(_assessment(
            canonical_admissibility="USABLE_WITH_WARNING",
            semantic_quality="degraded",
            reason_codes=("FACT_QUALITY_DEGRADED",))),
        _project(_assessment(
            canonical_admissibility="BLOCKED",
            storage_integrity="CORRUPTED",
            reason_codes=("ARTIFACT_HASH_MISMATCH",))),
        _project(_assessment(
            canonical_admissibility="BLOCKED",
            reason_codes=("ARTIFACT_SCHEMA_MISMATCH",))),
        _project(_assessment(
            canonical_admissibility="BLOCKED",
            reason_codes=("REPLAY_MISMATCH",))),
    ]
    for code in ("FACT_LAKE_NOT_INITIALIZED", "FACT_LAKE_CORRUPTED",
                 "PUBLICATION_NOT_VISIBLE", "RECONCILIATION_AMBIGUOUS"):
        samples.append(flhp.project_fact_lake_health(
            collection_failure=_failure(code)))
    for p in samples:
        assert p.legacy_status in VALID_STATUSES
        assert p.legacy_error_code is None or p.legacy_error_code in ERROR_SUMMARIES
        if p.legacy_error_code is not None:
            assert p.legacy_error_summary == error_summary(p.legacy_error_code)
        else:
            assert p.legacy_error_summary is None


# ---------------------------------------------------------------------------
# G. 原 H1 证据存活 + lossiness（§24/§25）
# ---------------------------------------------------------------------------

def test_original_h1_dimensions_preserved():
    a = _assessment(
        canonical_admissibility="USABLE_WITH_WARNING",
        freshness="STALE",
        reason_codes=("TEMPORAL_VALUE_STALE", "REPLAY_NOT_RUN"),
    )
    p = _project(a)
    assert p.fact_lake_canonical_admissibility == a.canonical_admissibility
    assert p.fact_lake_reason_codes == a.reason_codes
    assert p.fact_lake_publication_visibility == a.publication_visibility
    assert p.fact_lake_storage_integrity == a.storage_integrity
    assert p.fact_lake_reproducibility == a.reproducibility
    assert p.fact_lake_semantic_quality == a.semantic_quality
    assert p.fact_lake_freshness == a.freshness
    assert p.fact_lake_reconciliation == a.reconciliation


def test_lossiness_flags():
    assert _project(_assessment()).lossiness == flhp.LOSSINESS_EXACT
    stale_only = _project(_assessment(
        canonical_admissibility="USABLE_WITH_WARNING",
        freshness="STALE",
        reason_codes=("TEMPORAL_VALUE_STALE",)))
    assert stale_only.lossiness == flhp.LOSSINESS_EXACT
    partial = _project(_assessment(
        canonical_admissibility="USABLE_WITH_WARNING",
        reason_codes=("REPLAY_NOT_RUN",)))
    assert partial.lossiness == flhp.LOSSINESS_LOSSY
    blocked = _project(_assessment(
        canonical_admissibility="BLOCKED",
        reason_codes=("REPLAY_MISMATCH",)))
    assert blocked.lossiness == flhp.LOSSINESS_LOSSY


# ---------------------------------------------------------------------------
# H. 严格输出契约（§31）：from_dict round-trip + 非法拒绝
# ---------------------------------------------------------------------------

def test_projection_round_trip():
    for p in (_project(_assessment()),
              _project(_assessment(
                  canonical_admissibility="USABLE_WITH_WARNING", freshness="STALE",
                  reason_codes=("TEMPORAL_VALUE_STALE",))),
              flhp.project_fact_lake_health(
                  collection_failure=_failure("FACT_LAKE_CORRUPTED"))):
        restored = flhp.FactLakeLegacyHealthProjection.from_dict(p.to_dict())
        assert restored == p


def test_projection_from_dict_rejects_unknown_enum():
    data = _project(_assessment()).to_dict()
    data["legacy_status"] = "degraded"
    with pytest.raises(flhp.LegacyProjectionError):
        flhp.FactLakeLegacyHealthProjection.from_dict(data)


def test_projection_from_dict_rejects_unknown_error_code():
    data = _project(_assessment(
        canonical_admissibility="BLOCKED",
        reason_codes=("REPLAY_MISMATCH",))).to_dict()
    data["legacy_error_code"] = "SOURCE_NEW_CODE"
    data["legacy_error_summary"] = "x"
    with pytest.raises(flhp.LegacyProjectionError):
        flhp.FactLakeLegacyHealthProjection.from_dict(data)


def test_projection_from_dict_rejects_summary_drift():
    data = _project(_assessment(
        canonical_admissibility="BLOCKED",
        reason_codes=("REPLAY_MISMATCH",))).to_dict()
    data["legacy_error_summary"] = "手写文本"
    with pytest.raises(flhp.LegacyProjectionError):
        flhp.FactLakeLegacyHealthProjection.from_dict(data)


def test_projection_from_dict_rejects_duplicate_reasons():
    data = _project(_assessment(
        canonical_admissibility="BLOCKED",
        reason_codes=("REPLAY_MISMATCH",))).to_dict()
    data["fact_lake_reason_codes"] = ["REPLAY_MISMATCH", "REPLAY_MISMATCH"]
    with pytest.raises(flhp.LegacyProjectionError):
        flhp.FactLakeLegacyHealthProjection.from_dict(data)


def test_projection_from_dict_rejects_assessment_with_failure_code():
    data = _project(_assessment()).to_dict()
    data["collection_failure_code"] = "FACT_LAKE_BUSY"
    with pytest.raises(flhp.LegacyProjectionError):
        flhp.FactLakeLegacyHealthProjection.from_dict(data)


def test_projection_from_dict_rejects_unknown_source_kind():
    data = _project(_assessment()).to_dict()
    data["source_kind"] = "OTHER"
    with pytest.raises(flhp.LegacyProjectionError):
        flhp.FactLakeLegacyHealthProjection.from_dict(data)


def test_projection_from_dict_rejects_unknown_lossiness():
    data = _project(_assessment()).to_dict()
    data["lossiness"] = "MAYBE"
    with pytest.raises(flhp.LegacyProjectionError):
        flhp.FactLakeLegacyHealthProjection.from_dict(data)


# ---------------------------------------------------------------------------
# I. 源码纯净扫描（§35）
# ---------------------------------------------------------------------------

def test_source_purity():
    source = inspect.getsource(flhp)
    forbidden = (
        "import sqlite3",
        "import duckdb",
        "sqlite3.",
        "duckdb.",
        "datetime.now",
        "date.today",
        "SOURCE_REGISTRY",
        "DataHealthRecord",
        "aggregate_health(",
    )
    for marker in forbidden:
        assert marker not in source, f"生产 H3 源码包含禁止内容: {marker!r}"


# ---------------------------------------------------------------------------
# R1：P1-A 维度严重度不得消失（不一致但结构合法的 assessment 也保守）
# ---------------------------------------------------------------------------

def test_r1a_usable_quality_degraded_empty_reasons_partial_degraded():
    """A1：USABLE + semantic_quality=degraded + 空 reason_codes → partial/degraded，绝不 normal。"""
    p = _project(_assessment(
        canonical_admissibility="USABLE",
        semantic_quality="degraded",
        reason_codes=(),
    ))
    assert p.legacy_status == "partial"
    assert p.legacy_is_degraded is True
    assert p.legacy_error_code == "SOURCE_DEGRADED"


def test_r1a_usable_stale_empty_reasons_normal_stale():
    """A2：USABLE + freshness=STALE + 空 reasons + 其他 clean → normal + is_stale=True + SOURCE_STALE。"""
    p = _project(_assessment(
        canonical_admissibility="USABLE",
        freshness="STALE",
        reason_codes=(),
    ))
    assert p.legacy_status == "normal"
    assert p.legacy_is_stale is True
    assert p.legacy_error_code == "SOURCE_STALE"


def test_r1a_usable_reproducibility_not_run_partial():
    """A3：USABLE + reproducibility=NOT_RUN + 空 reasons → partial / SOURCE_PARTIAL。"""
    p = _project(_assessment(
        canonical_admissibility="USABLE",
        reproducibility="NOT_RUN",
        reason_codes=(),
    ))
    assert p.legacy_status == "partial"
    assert p.legacy_error_code == "SOURCE_PARTIAL"


def test_r1a_usable_storage_unverified_partial():
    """A4：USABLE + storage_integrity=UNVERIFIED + 空 reasons → partial / SOURCE_PARTIAL。"""
    p = _project(_assessment(
        canonical_admissibility="USABLE",
        storage_integrity="UNVERIFIED",
        reason_codes=(),
    ))
    assert p.legacy_status == "partial"
    assert p.legacy_error_code == "SOURCE_PARTIAL"


def test_r1a_usable_reconciliation_mismatch_partial():
    """A5：USABLE + reconciliation=mismatch + 空 reasons → partial / SOURCE_PARTIAL。"""
    p = _project(_assessment(
        canonical_admissibility="USABLE",
        reconciliation="mismatch",
        reason_codes=(),
    ))
    assert p.legacy_status == "partial"
    assert p.legacy_error_code == "SOURCE_PARTIAL"


def test_r1a_blocking_reason_floor_drift_unavailable():
    """A6：USABLE_WITH_WARNING + (RECONCILIATION_STATUS_DRIFT,) → unavailable / SOURCE_UNAVAILABLE。
    blocking reason 本身建立 floor，绝不因 caller 改成 WITH_WARNING 而变 partial。"""
    p = _project(_assessment(
        canonical_admissibility="USABLE_WITH_WARNING",
        reason_codes=("RECONCILIATION_STATUS_DRIFT",),
    ))
    assert p.legacy_status == "unavailable"
    assert p.legacy_error_code == "SOURCE_UNAVAILABLE"


def test_r1a_blocking_reason_floor_corruption_unavailable():
    """A7：USABLE + (ARTIFACT_HASH_MISMATCH,) + storage=VERIFIED → unavailable / SOURCE_CORRUPTED。
    不信任与 blocking reason 不一致的 storage 维度。"""
    p = _project(_assessment(
        canonical_admissibility="USABLE",
        storage_integrity="VERIFIED",
        reason_codes=("ARTIFACT_HASH_MISMATCH",),
    ))
    assert p.legacy_status == "unavailable"
    assert p.legacy_error_code == "SOURCE_CORRUPTED"


def test_r1a_stale_plus_warning_dimension_partial():
    """STALE + 其他 warning 维度（reason 缺失）→ partial + is_stale=True（非 normal）。"""
    p = _project(_assessment(
        canonical_admissibility="USABLE",
        freshness="STALE",
        reconciliation="not_run",  # warning 维度，无 reason codes
        reason_codes=(),
    ))
    assert p.legacy_status == "partial"
    assert p.legacy_is_stale is True
    assert p.legacy_error_code == "SOURCE_PARTIAL"


# ---------------------------------------------------------------------------
# R1：P1-B 严格输出边界（序列化 payload 不能覆盖投影权威）
# ---------------------------------------------------------------------------

def test_r1b_from_dict_rejects_unknown_dimension_value():
    """B1：fact_lake_storage_integrity="banana" → REJECT。"""
    data = _project(_assessment()).to_dict()
    data["fact_lake_storage_integrity"] = "banana"
    with pytest.raises(flhp.LegacyProjectionError):
        flhp.FactLakeLegacyHealthProjection.from_dict(data)


def test_r1b_from_dict_rejects_admissibility_mutation():
    """B2：canonical_admissibility 改成 BLOCKED 但 legacy 保持 normal → REJECT。"""
    data = _project(_assessment()).to_dict()
    data["fact_lake_canonical_admissibility"] = "BLOCKED"
    with pytest.raises(flhp.LegacyProjectionError):
        flhp.FactLakeLegacyHealthProjection.from_dict(data)


def test_r1b_from_dict_rejects_semantic_projection_drift():
    """B3：CORRUPTED 投影把 error_code 改成 SOURCE_UNAVAILABLE（summary 合法）→ REJECT。"""
    p = _project(_assessment(
        canonical_admissibility="BLOCKED",
        storage_integrity="CORRUPTED",
        reason_codes=("ARTIFACT_HASH_MISMATCH",),
    ))
    assert p.legacy_error_code == "SOURCE_CORRUPTED"
    data = p.to_dict()
    data["legacy_error_code"] = "SOURCE_UNAVAILABLE"
    data["legacy_error_summary"] = flhp.error_summary("SOURCE_UNAVAILABLE")
    with pytest.raises(flhp.LegacyProjectionError):
        flhp.FactLakeLegacyHealthProjection.from_dict(data)


def test_r1b_from_dict_rejects_collection_failure_extra_shape():
    """B4：COLLECTION_FAILURE + dataset_id 非 None → REJECT。"""
    p = flhp.project_fact_lake_health(
        collection_failure=HealthEvidenceCollectionFailure(
            code="FACT_LAKE_BUSY", detail="test"))
    data = p.to_dict()
    data["dataset_id"] = "fake"
    with pytest.raises(flhp.LegacyProjectionError):
        flhp.FactLakeLegacyHealthProjection.from_dict(data)
    # 任一 H1 维度非 None 同样拒绝
    data2 = p.to_dict()
    data2["fact_lake_freshness"] = "CURRENT"
    with pytest.raises(flhp.LegacyProjectionError):
        flhp.FactLakeLegacyHealthProjection.from_dict(data2)


def test_r1b_valid_round_trip_exact():
    """B5：to_dict → from_dict 精确相等（normal / stale-only / blocked / failure）。"""
    samples = [
        _project(_assessment()),
        _project(_assessment(
            canonical_admissibility="USABLE_WITH_WARNING", freshness="STALE",
            reason_codes=("TEMPORAL_VALUE_STALE",))),
        _project(_assessment(
            canonical_admissibility="BLOCKED",
            storage_integrity="CORRUPTED",
            reason_codes=("ARTIFACT_HASH_MISMATCH",))),
        flhp.project_fact_lake_health(
            collection_failure=HealthEvidenceCollectionFailure(
                code="PUBLICATION_NOT_VISIBLE", detail="test")),
    ]
    for p in samples:
        restored = flhp.FactLakeLegacyHealthProjection.from_dict(p.to_dict())
        assert restored == p
