"""Fact Lake Health → Legacy Data Health Semantic Projection Core v0.1（DS-L1-H3）。

冻结 Fact Lake 健康（H1 7 维 + canonical_admissibility）与既有 Data Health
词汇（normal / partial / unavailable + is_stale / is_degraded / error_code）
之间的**语义兼容契约**——回答「如何在不撒谎的前提下，把 Fact Lake 健康结果
放进既有 Data Health 词汇」。

- **纯 projection core**：零 I/O（无 SQLite / filesystem / network / env /
  clock / DuckDB / Parquet / provider）；不重复任何健康推导（H1 拥有
  freshness / reconciliation / storage / replay 权威，H3 只投影其结论）。
- **复用既有权威**：``data_health_service.VALID_STATUSES`` /
  ``ERROR_SUMMARIES`` / ``error_summary(...)`` 是 legacy 词汇唯一来源；
  ``fact_lake_health.FactLakeHealthAssessment``（严格 from_dict 校验）与
  ``fact_lake_health_adapter.HealthEvidenceCollectionFailure`` 是输入权威。
- **两种 source kind**：ASSESSMENT（H1 评估）与 COLLECTION_FAILURE（H2
  集合失败）；调用方/编程错误（BAD_ARGUMENT / INTERNAL）绝不投影为数据
  源健康状态（→ raise，无 projection）。
- **bridge 级严重度地板**：即使 assessment 声称 USABLE，只要任何维度显示
  硬失败（NOT_COMMITTED / CORRUPTED / MISMATCH / invalid），保守投影
  unavailable；绝不静默信任内部不一致的 assessment。
- 不产出数据健康记录、不注册 source_id、不改源注册表、不接运行时/API/UI
  （FUTURE / NOT AUTHORIZED）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from data_health_service import ERROR_SUMMARIES, VALID_STATUSES, error_summary
from fact_lake_health import FactLakeHealthAssessment
from fact_lake_health_adapter import HealthEvidenceCollectionFailure

SCHEMA_VERSION = "fact_lake_legacy_projection.v0.1"

# 两种来源种类（§8）
SOURCE_KIND_ASSESSMENT = "ASSESSMENT"
SOURCE_KIND_COLLECTION_FAILURE = "COLLECTION_FAILURE"

# 兼容/损失性标记（§24，仅诊断元数据，不改变严重度）
LOSSINESS_EXACT = "EXACT"
LOSSINESS_LOSSY = "LOSSY"

# ---- 投影使用的 legacy error codes（全部 ∈ data_health_service.ERROR_SUMMARIES）----
CODE_NOT_INITIALIZED = "SOURCE_NOT_INITIALIZED"
CODE_STALE = "SOURCE_STALE"
CODE_PARTIAL = "SOURCE_PARTIAL"
CODE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
CODE_CORRUPTED = "SOURCE_CORRUPTED"
CODE_SCHEMA_INCOMPATIBLE = "SOURCE_SCHEMA_INCOMPATIBLE"
CODE_DEGRADED = "SOURCE_DEGRADED"

# H2 集合失败 → legacy（§20）；不含 BAD_ARGUMENT / INTERNAL（§21 拒绝）
_COLLECTION_FAILURE_MAPPING = {
    "FACT_LAKE_NOT_INITIALIZED": (CODE_NOT_INITIALIZED,),
    "FACT_LAKE_SCHEMA_UNSUPPORTED": (CODE_SCHEMA_INCOMPATIBLE,),
    "FACT_LAKE_CORRUPTED": (CODE_CORRUPTED,),
    "FACT_LAKE_PATH_UNSAFE": (CODE_CORRUPTED,),
    "FACT_LAKE_BUSY": (CODE_UNAVAILABLE,),
    "PUBLICATION_NOT_VISIBLE": (CODE_UNAVAILABLE,),
    "RECONCILIATION_AMBIGUOUS": (CODE_UNAVAILABLE,),
}
_NON_DATA_HEALTH_CODES = frozenset({"BAD_ARGUMENT", "INTERNAL"})

# H1 blocking reasons（只读引用权威；顺序无关，按 frozenset 判定）
BLOCKING_REASON_CODES = frozenset({
    "PUBLICATION_NOT_COMMITTED", "DATASET_ID_MISMATCH",
    "CANONICAL_KEY_MISMATCH", "DATASET_SPEC_REJECTED_FACT",
    "SOURCE_OBSERVATION_NOT_COMMITTED", "RAW_PAYLOAD_HASH_MISMATCH",
    "ARTIFACT_MISSING", "ARTIFACT_HASH_MISMATCH",
    "ARTIFACT_SCHEMA_MISMATCH", "REPLAY_MISMATCH",
    "FACT_QUALITY_INVALID", "TEMPORAL_INDEX_MISMATCH",
    "RECONCILIATION_UNBOUND", "RECONCILIATION_STATUS_DRIFT",
})
# H1 warning reasons（含 stale；§13/§16 判定用）
WARNING_REASON_CODES = frozenset({
    "ARTIFACT_UNVERIFIED", "REPLAY_NOT_RUN", "REPLAY_UNSUPPORTED",
    "FACT_QUALITY_DEGRADED", "FACT_QUALITY_UNKNOWN", "FRESHNESS_UNKNOWN",
    "TEMPORAL_VALUE_STALE", "RECONCILIATION_NOT_RUN",
    "RECONCILIATION_MISMATCH", "RECONCILIATION_PARTIAL",
    "RECONCILIATION_SOURCE_UNAVAILABLE",
    "RECONCILIATION_TEMPORAL_INCOMPARABLE", "RECONCILIATION_UNKNOWN",
})
_KNOWN_REASON_CODES = BLOCKING_REASON_CODES | WARNING_REASON_CODES

# stale-only 定义（§13）：仅 TEMPORAL_VALUE_STALE 这一个 warning，无其他非 stale warning
_STALE_WARNING_REASON = "TEMPORAL_VALUE_STALE"


class LegacyProjectionError(Exception):
    """投影/桥接错误：编程/调用方契约违反（BAD_ARGUMENT / INTERNAL），
    或输入无法被严格权威重建。绝无投影输出（§21）。"""


# ---------------------------------------------------------------------------
# 冻结输出值对象（§7/§31）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FactLakeLegacyHealthProjection:
    """一份 legacy 兼容视图（不是新的健康权威；原 H1 评估保持权威）。"""

    schema_version: str
    dataset_id: str | None
    canonical_key: str | None
    publication_id: str | None
    # legacy 视图
    legacy_status: str
    legacy_is_stale: bool
    legacy_is_degraded: bool
    legacy_error_code: str | None
    legacy_error_summary: str | None
    # 原 Fact Lake 证据（必须存活，§25）
    fact_lake_canonical_admissibility: str | None
    fact_lake_reason_codes: tuple[str, ...]
    fact_lake_publication_visibility: str | None
    fact_lake_storage_integrity: str | None
    fact_lake_reproducibility: str | None
    fact_lake_semantic_quality: str | None
    fact_lake_freshness: str | None
    fact_lake_reconciliation: str | None
    # 来源元数据
    source_kind: str
    collection_failure_code: str | None
    lossiness: str

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "canonical_key": self.canonical_key,
            "publication_id": self.publication_id,
            "legacy_status": self.legacy_status,
            "legacy_is_stale": self.legacy_is_stale,
            "legacy_is_degraded": self.legacy_is_degraded,
            "legacy_error_code": self.legacy_error_code,
            "legacy_error_summary": self.legacy_error_summary,
            "fact_lake_canonical_admissibility": self.fact_lake_canonical_admissibility,
            "fact_lake_reason_codes": list(self.fact_lake_reason_codes),
            "fact_lake_publication_visibility": self.fact_lake_publication_visibility,
            "fact_lake_storage_integrity": self.fact_lake_storage_integrity,
            "fact_lake_reproducibility": self.fact_lake_reproducibility,
            "fact_lake_semantic_quality": self.fact_lake_semantic_quality,
            "fact_lake_freshness": self.fact_lake_freshness,
            "fact_lake_reconciliation": self.fact_lake_reconciliation,
            "source_kind": self.source_kind,
            "collection_failure_code": self.collection_failure_code,
            "lossiness": self.lossiness,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FactLakeLegacyHealthProjection":
        """严格反序列化（exact field set / exact types / 已知枚举 / 无重复 / 无未知）。"""
        if not isinstance(data, Mapping):
            raise LegacyProjectionError("projection 必须是 Mapping")
        expected = set(cls.__dataclass_fields__)
        if set(data) != expected:
            missing = sorted(expected - set(data))
            extra = sorted(set(data) - expected)
            raise LegacyProjectionError(
                f"projection 字段不匹配: missing={missing}, extra={extra}")
        if data["schema_version"] != SCHEMA_VERSION:
            raise LegacyProjectionError(
                f"schema_version 漂移: {data['schema_version']!r}")
        status = data["legacy_status"]
        if status not in VALID_STATUSES:
            raise LegacyProjectionError(
                f"legacy_status 非法（复用 data_health_service.VALID_STATUSES）: {status!r}")
        for name in ("legacy_is_stale", "legacy_is_degraded"):
            if type(data[name]) is not bool:
                raise LegacyProjectionError(f"{name} 必须是 bool")
        code = data["legacy_error_code"]
        if code is not None:
            if type(code) is not str or code not in ERROR_SUMMARIES:
                raise LegacyProjectionError(
                    f"legacy_error_code 必须是既有 Data Health 公开错误码: {code!r}")
            if data["legacy_error_summary"] != error_summary(code):
                raise LegacyProjectionError(
                    "legacy_error_summary 必须精确等于 data_health_service.error_summary(code)")
        else:
            if data["legacy_error_summary"] is not None:
                raise LegacyProjectionError("无 error code 时 summary 必须为 None")
        for name in ("dataset_id", "canonical_key", "publication_id",
                     "fact_lake_canonical_admissibility",
                     "fact_lake_publication_visibility", "fact_lake_storage_integrity",
                     "fact_lake_reproducibility", "fact_lake_semantic_quality",
                     "fact_lake_freshness", "fact_lake_reconciliation"):
            value = data[name]
            if value is not None and (type(value) is not str or not value.strip()):
                raise LegacyProjectionError(f"{name} 必须是非空 str 或 None")
        codes = data["fact_lake_reason_codes"]
        if not isinstance(codes, list) or any(type(c) is not str for c in codes):
            raise LegacyProjectionError("fact_lake_reason_codes 必须是字符串列表")
        if len(codes) != len(set(codes)):
            raise LegacyProjectionError("fact_lake_reason_codes 不得重复")
        unknown = sorted(set(codes) - _KNOWN_REASON_CODES)
        if unknown:
            raise LegacyProjectionError(f"fact_lake_reason_codes 含未知 code: {unknown}")
        if data["source_kind"] not in (
                SOURCE_KIND_ASSESSMENT, SOURCE_KIND_COLLECTION_FAILURE):
            raise LegacyProjectionError(f"未知 source_kind: {data['source_kind']!r}")
        failure_code = data["collection_failure_code"]
        if data["source_kind"] == SOURCE_KIND_COLLECTION_FAILURE:
            if failure_code not in _COLLECTION_FAILURE_MAPPING:
                raise LegacyProjectionError(
                    f"collection failure 投影必须携带可映射失败码: {failure_code!r}")
        elif failure_code is not None:
            raise LegacyProjectionError("ASSESSMENT 投影不得携带 collection_failure_code")
        if data["lossiness"] not in (LOSSINESS_EXACT, LOSSINESS_LOSSY):
            raise LegacyProjectionError(f"未知 lossiness: {data['lossiness']!r}")
        return cls(
            schema_version=data["schema_version"],
            dataset_id=data["dataset_id"],
            canonical_key=data["canonical_key"],
            publication_id=data["publication_id"],
            legacy_status=status,
            legacy_is_stale=data["legacy_is_stale"],
            legacy_is_degraded=data["legacy_is_degraded"],
            legacy_error_code=code,
            legacy_error_summary=data["legacy_error_summary"],
            fact_lake_canonical_admissibility=data["fact_lake_canonical_admissibility"],
            fact_lake_reason_codes=tuple(codes),
            fact_lake_publication_visibility=data["fact_lake_publication_visibility"],
            fact_lake_storage_integrity=data["fact_lake_storage_integrity"],
            fact_lake_reproducibility=data["fact_lake_reproducibility"],
            fact_lake_semantic_quality=data["fact_lake_semantic_quality"],
            fact_lake_freshness=data["fact_lake_freshness"],
            fact_lake_reconciliation=data["fact_lake_reconciliation"],
            source_kind=data["source_kind"],
            collection_failure_code=failure_code,
            lossiness=data["lossiness"],
        )


# ---------------------------------------------------------------------------
# 输入权威（§9/§21）：不信任 Python 类型，严格 from_dict 重建
# ---------------------------------------------------------------------------

def _rebuild_assessment(assessment: FactLakeHealthAssessment | Mapping[str, Any]) -> FactLakeHealthAssessment:
    """assessment 输入必须经 to_dict → 严格 from_dict 权威重建。"""
    try:
        if isinstance(assessment, FactLakeHealthAssessment):
            data = assessment.to_dict()
        else:
            data = assessment
        return FactLakeHealthAssessment.from_dict(data)
    except Exception as exc:
        raise LegacyProjectionError(
            f"assessment 无法通过 H1 严格 from_dict（未知枚举/字段/reason/schema）: {exc}"
        ) from exc


def _rebuild_failure(
    failure: HealthEvidenceCollectionFailure | Mapping[str, Any],
) -> HealthEvidenceCollectionFailure:
    try:
        if isinstance(failure, HealthEvidenceCollectionFailure):
            data = failure.to_dict()
        else:
            data = failure
        return HealthEvidenceCollectionFailure.from_dict(data)
    except Exception as exc:
        raise LegacyProjectionError(
            f"collection failure 无法通过 H2 严格 from_dict: {exc}") from exc


# ---------------------------------------------------------------------------
# 确定性 legacy 映射（§10-§18）
# ---------------------------------------------------------------------------

def _blocked_error_code(
    storage_integrity: str,
    reason_codes: frozenset[str],
) -> str:
    """BLOCKED 错误码优先级（§17/§18）：SOURCE_CORRUPTED > SCHEMA > UNAVAILABLE。"""
    if storage_integrity == "CORRUPTED" or \
            "RAW_PAYLOAD_HASH_MISMATCH" in reason_codes or \
            "ARTIFACT_MISSING" in reason_codes or \
            "ARTIFACT_HASH_MISMATCH" in reason_codes:
        return CODE_CORRUPTED
    if "ARTIFACT_SCHEMA_MISMATCH" in reason_codes:
        return CODE_SCHEMA_INCOMPATIBLE
    return CODE_UNAVAILABLE


def _is_stale_only(*, freshness: str, reason_codes: frozenset[str]) -> bool:
    """§13 stale-only：freshness=STALE 且无非 stale warning reason、无 blocking reason。"""
    return (
        freshness == "STALE"
        and not (reason_codes & BLOCKING_REASON_CODES)
        and not (reason_codes & (WARNING_REASON_CODES - {_STALE_WARNING_REASON}))
    )


def _project_assessment(
    assessment: FactLakeHealthAssessment,
) -> FactLakeLegacyHealthProjection:
    """Assessment 路径（§10-§19）——确定性映射，reason 顺序无关（§30）。"""
    reasons = frozenset(assessment.reason_codes)
    storage = assessment.storage_integrity
    quality = assessment.semantic_quality
    freshness = assessment.freshness

    # §11 硬失败维度地板（bridge 级，绝不 normal/partial usable）
    hard_fail = (
        assessment.publication_visibility == "NOT_COMMITTED"
        or storage == "CORRUPTED"
        or assessment.reproducibility == "MISMATCH"
        or quality == "invalid"
    )
    if hard_fail or assessment.canonical_admissibility == "BLOCKED":
        status = "unavailable"
        error_code = _blocked_error_code(storage, reasons)
        return FactLakeLegacyHealthProjection(
            schema_version=SCHEMA_VERSION,
            dataset_id=assessment.dataset_id,
            canonical_key=assessment.canonical_key,
            publication_id=assessment.publication_id,
            legacy_status=status,
            legacy_is_stale=(freshness == "STALE"),
            legacy_is_degraded=False,
            legacy_error_code=error_code,
            legacy_error_summary=error_summary(error_code),
            fact_lake_canonical_admissibility=assessment.canonical_admissibility,
            fact_lake_reason_codes=assessment.reason_codes,
            fact_lake_publication_visibility=assessment.publication_visibility,
            fact_lake_storage_integrity=storage,
            fact_lake_reproducibility=assessment.reproducibility,
            fact_lake_semantic_quality=quality,
            fact_lake_freshness=freshness,
            fact_lake_reconciliation=assessment.reconciliation,
            source_kind=SOURCE_KIND_ASSESSMENT,
            collection_failure_code=None,
            lossiness=LOSSINESS_LOSSY,
        )

    stale = freshness == "STALE"
    if assessment.canonical_admissibility == "USABLE":
        if reasons:
            # 防御：声称 USABLE 却带 warning/block reason（内部不一致）→ 保守 partial
            return FactLakeLegacyHealthProjection(
                schema_version=SCHEMA_VERSION,
                dataset_id=assessment.dataset_id,
                canonical_key=assessment.canonical_key,
                publication_id=assessment.publication_id,
                legacy_status="partial",
                legacy_is_stale=stale,
                legacy_is_degraded=False,
                legacy_error_code=CODE_PARTIAL,
                legacy_error_summary=error_summary(CODE_PARTIAL),
                fact_lake_canonical_admissibility=assessment.canonical_admissibility,
                fact_lake_reason_codes=assessment.reason_codes,
                fact_lake_publication_visibility=assessment.publication_visibility,
                fact_lake_storage_integrity=storage,
                fact_lake_reproducibility=assessment.reproducibility,
                fact_lake_semantic_quality=quality,
                fact_lake_freshness=freshness,
                fact_lake_reconciliation=assessment.reconciliation,
                source_kind=SOURCE_KIND_ASSESSMENT,
                collection_failure_code=None,
                lossiness=LOSSINESS_LOSSY,
            )
        # 干净 USABLE（§19）：normal
        return FactLakeLegacyHealthProjection(
            schema_version=SCHEMA_VERSION,
            dataset_id=assessment.dataset_id,
            canonical_key=assessment.canonical_key,
            publication_id=assessment.publication_id,
            legacy_status="normal",
            legacy_is_stale=False,
            legacy_is_degraded=False,
            legacy_error_code=None,
            legacy_error_summary=None,
            fact_lake_canonical_admissibility=assessment.canonical_admissibility,
            fact_lake_reason_codes=(),
            fact_lake_publication_visibility=assessment.publication_visibility,
            fact_lake_storage_integrity=storage,
            fact_lake_reproducibility=assessment.reproducibility,
            fact_lake_semantic_quality=quality,
            fact_lake_freshness=freshness,
            fact_lake_reconciliation=assessment.reconciliation,
            source_kind=SOURCE_KIND_ASSESSMENT,
            collection_failure_code=None,
            lossiness=LOSSINESS_EXACT,
        )

    # USABLE_WITH_WARNING（§14-§16）
    if quality == "degraded":
        error_code = CODE_DEGRADED
        status = "partial"
        is_degraded = True
        lossiness = LOSSINESS_LOSSY
    elif _is_stale_only(freshness=freshness, reason_codes=reasons):
        error_code = CODE_STALE
        status = "normal"
        is_degraded = False
        lossiness = LOSSINESS_EXACT
    else:
        error_code = CODE_PARTIAL
        status = "partial"
        is_degraded = False
        lossiness = LOSSINESS_LOSSY
    return FactLakeLegacyHealthProjection(
        schema_version=SCHEMA_VERSION,
        dataset_id=assessment.dataset_id,
        canonical_key=assessment.canonical_key,
        publication_id=assessment.publication_id,
        legacy_status=status,
        legacy_is_stale=stale,
        legacy_is_degraded=is_degraded,
        legacy_error_code=error_code,
        legacy_error_summary=error_summary(error_code),
        fact_lake_canonical_admissibility=assessment.canonical_admissibility,
        fact_lake_reason_codes=assessment.reason_codes,
        fact_lake_publication_visibility=assessment.publication_visibility,
        fact_lake_storage_integrity=storage,
        fact_lake_reproducibility=assessment.reproducibility,
        fact_lake_semantic_quality=quality,
        fact_lake_freshness=freshness,
        fact_lake_reconciliation=assessment.reconciliation,
        source_kind=SOURCE_KIND_ASSESSMENT,
        collection_failure_code=None,
        lossiness=lossiness,
    )


def _project_collection_failure(
    failure: HealthEvidenceCollectionFailure,
) -> FactLakeLegacyHealthProjection:
    """Collection failure 路径（§20-§22）。"""
    if failure.code in _NON_DATA_HEALTH_CODES:
        raise LegacyProjectionError(
            f"{failure.code} 是编程/调用方错误，不是数据源健康状态（不投影）")
    mapping = _COLLECTION_FAILURE_MAPPING.get(failure.code)
    if mapping is None:
        raise LegacyProjectionError(f"未知 collection failure code: {failure.code!r}")
    error_code = mapping[0]
    return FactLakeLegacyHealthProjection(
        schema_version=SCHEMA_VERSION,
        dataset_id=None,
        canonical_key=None,
        publication_id=None,
        legacy_status="unavailable",
        legacy_is_stale=False,
        legacy_is_degraded=False,
        legacy_error_code=error_code,
        legacy_error_summary=error_summary(error_code),
        fact_lake_canonical_admissibility=None,
        fact_lake_reason_codes=(),
        fact_lake_publication_visibility=None,
        fact_lake_storage_integrity=None,
        fact_lake_reproducibility=None,
        fact_lake_semantic_quality=None,
        fact_lake_freshness=None,
        fact_lake_reconciliation=None,
        source_kind=SOURCE_KIND_COLLECTION_FAILURE,
        collection_failure_code=failure.code,
        lossiness=LOSSINESS_LOSSY,
    )


# ---------------------------------------------------------------------------
# 公共 API（§21 双层：严格输入 → 冻结输出）
# ---------------------------------------------------------------------------

def project_fact_lake_health(
    *,
    assessment: FactLakeHealthAssessment | Mapping[str, Any] | None = None,
    collection_failure: HealthEvidenceCollectionFailure | Mapping[str, Any] | None = None,
) -> FactLakeLegacyHealthProjection:
    """把 H1 评估或 H2 集合失败投影为 legacy Data Health 视图。

    必须且只能提供一种来源（assessment XOR collection_failure）。
    非法/编程/未知输入 → ``LegacyProjectionError``（无投影输出）。
    """
    if (assessment is None) == (collection_failure is None):
        raise LegacyProjectionError("必须且只能提供 assessment 或 collection_failure 之一")
    if assessment is not None:
        rebuilt = _rebuild_assessment(assessment)
        return _project_assessment(rebuilt)
    failure = _rebuild_failure(collection_failure)
    return _project_collection_failure(failure)
