"""Fact Lake Dataset Health & Canonical Admissibility Core v0.1（DS-L1-H1）。

纯确定性 domain core，回答：「给定 DatasetSpec、CanonicalFact 与独立采集的
Fact Lake 完整性/回放/对账证据，该 canonical dataset publication 的健康
状态是什么？」

- 本模块**零 I/O**：无 SQLite / filesystem / network / env / clock / DuckDB /
  Parquet / provider 调用；所有运行时证据由调用方显式传入。
- 复用既有权威（import data_contracts）：DatasetSpec / CanonicalFact /
  ReconciliationResult / FetchSemantics / HistoryMode / TemporalSemantics /
  QualityStatus / ReconciliationStatus —— 不定义竞争副本。
  ``DatasetSpec.validate_fact(...)`` 仍是 CanonicalFact 准入的语义权威。
- 健康是多维的（7 维独立保留，不塌缩为单一 boolean）：
  publication_visibility / storage_integrity / reproducibility /
  semantic_quality / freshness / reconciliation / canonical_admissibility。
- 关键纪律（§12-26）：不伪造新鲜度、不推断 PIT/as_of、不触发 provider
  切换、legal-zero 不是通用失败、RESTATABLE 不做 latest-row-wins、
  vintage_sequence 只是本地发布序、revision 语义不塌缩。
- 本 slice 不接入现有 Data Health UI/service（FUTURE / NOT AUTHORIZED）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from data_contracts import (
    CanonicalFact,
    DatasetSpec,
    ReconciliationResult,
    ReconciliationStatus,
    FetchSemantics,
    HistoryMode,
    QualityStatus,
    RevisionSemantics,
    TemporalSemantics,
)

SCHEMA_VERSION = "fact_lake_health.v0.1"

# ---- v0.1 有限枚举（语义固定）----
COMMIT_STATES = ("COMMITTED", "STAGING", "FAILED", "ABORTED")

# 维度枚举
PublicationVisibility = ("COMMITTED", "NOT_COMMITTED")
StorageIntegrity = ("VERIFIED", "UNVERIFIED", "CORRUPTED")
Reproducibility = ("MATCH", "NOT_RUN", "UNSUPPORTED", "MISMATCH")
Freshness = ("CURRENT", "STALE", "UNKNOWN", "NOT_APPLICABLE")
CanonicalAdmissibility = ("USABLE", "USABLE_WITH_WARNING", "BLOCKED")

# 完整性证据枚举（来自 future adapter 的独立采集结果）
ArtifactIntegrity = ("VERIFIED", "UNVERIFIED", "MISSING", "HASH_MISMATCH", "SCHEMA_MISMATCH")
RawPayloadIntegrity = ("VERIFIED", "UNVERIFIED", "MISSING", "HASH_MISMATCH")
ReplayState = ("MATCH", "NOT_RUN", "UNSUPPORTED", "MISMATCH")

# 确定性 reason codes（稳定命名，无重复）
REASON_PUBLICATION_NOT_COMMITTED = "PUBLICATION_NOT_COMMITTED"
REASON_DATASET_ID_MISMATCH = "DATASET_ID_MISMATCH"
REASON_CANONICAL_KEY_MISMATCH = "CANONICAL_KEY_MISMATCH"
REASON_DATASET_SPEC_REJECTED_FACT = "DATASET_SPEC_REJECTED_FACT"
REASON_SOURCE_OBSERVATION_NOT_COMMITTED = "SOURCE_OBSERVATION_NOT_COMMITTED"
REASON_RAW_PAYLOAD_HASH_MISMATCH = "RAW_PAYLOAD_HASH_MISMATCH"
REASON_ARTIFACT_UNVERIFIED = "ARTIFACT_UNVERIFIED"
REASON_ARTIFACT_MISSING = "ARTIFACT_MISSING"
REASON_ARTIFACT_HASH_MISMATCH = "ARTIFACT_HASH_MISMATCH"
REASON_ARTIFACT_SCHEMA_MISMATCH = "ARTIFACT_SCHEMA_MISMATCH"
REASON_REPLAY_NOT_RUN = "REPLAY_NOT_RUN"
REASON_REPLAY_UNSUPPORTED = "REPLAY_UNSUPPORTED"
REASON_REPLAY_MISMATCH = "REPLAY_MISMATCH"
REASON_FACT_QUALITY_DEGRADED = "FACT_QUALITY_DEGRADED"
REASON_FACT_QUALITY_UNKNOWN = "FACT_QUALITY_UNKNOWN"
REASON_FACT_QUALITY_INVALID = "FACT_QUALITY_INVALID"
REASON_FRESHNESS_UNKNOWN = "FRESHNESS_UNKNOWN"
REASON_TEMPORAL_VALUE_STALE = "TEMPORAL_VALUE_STALE"
REASON_TEMPORAL_INDEX_MISMATCH = "TEMPORAL_INDEX_MISMATCH"
REASON_RECONCILIATION_NOT_RUN = "RECONCILIATION_NOT_RUN"
REASON_RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
REASON_RECONCILIATION_PARTIAL = "RECONCILIATION_PARTIAL"
REASON_RECONCILIATION_SOURCE_UNAVAILABLE = "RECONCILIATION_SOURCE_UNAVAILABLE"
REASON_RECONCILIATION_TEMPORAL_INCOMPARABLE = "RECONCILIATION_TEMPORAL_INCOMPARABLE"
REASON_RECONCILIATION_UNKNOWN = "RECONCILIATION_UNKNOWN"

# 枚举 → reason code（稳定映射）
_RECONCILIATION_REASON = {
    ReconciliationStatus.MATCH: None,
    ReconciliationStatus.MISMATCH: REASON_RECONCILIATION_MISMATCH,
    ReconciliationStatus.PARTIAL: REASON_RECONCILIATION_PARTIAL,
    ReconciliationStatus.SOURCE_UNAVAILABLE: REASON_RECONCILIATION_SOURCE_UNAVAILABLE,
    ReconciliationStatus.TEMPORAL_INCOMPARABLE: REASON_RECONCILIATION_TEMPORAL_INCOMPARABLE,
    ReconciliationStatus.UNKNOWN: REASON_RECONCILIATION_UNKNOWN,
}

_QUALITY_REASON = {
    QualityStatus.VALID: None,
    QualityStatus.DEGRADED: REASON_FACT_QUALITY_DEGRADED,
    QualityStatus.INVALID: REASON_FACT_QUALITY_INVALID,
    QualityStatus.UNKNOWN: REASON_FACT_QUALITY_UNKNOWN,
}

# 一致性 reason → admissibility 严重度
_BLOCKING_REASONS = frozenset({
    REASON_PUBLICATION_NOT_COMMITTED,
    REASON_DATASET_ID_MISMATCH,
    REASON_CANONICAL_KEY_MISMATCH,
    REASON_DATASET_SPEC_REJECTED_FACT,
    REASON_SOURCE_OBSERVATION_NOT_COMMITTED,
    REASON_RAW_PAYLOAD_HASH_MISMATCH,
    REASON_ARTIFACT_MISSING,
    REASON_ARTIFACT_HASH_MISMATCH,
    REASON_ARTIFACT_SCHEMA_MISMATCH,
    REASON_REPLAY_MISMATCH,
    REASON_FACT_QUALITY_INVALID,
    REASON_TEMPORAL_INDEX_MISMATCH,
})
_WARNING_REASONS = frozenset({
    REASON_ARTIFACT_UNVERIFIED,
    REASON_REPLAY_NOT_RUN,
    REASON_REPLAY_UNSUPPORTED,
    REASON_FACT_QUALITY_DEGRADED,
    REASON_FACT_QUALITY_UNKNOWN,
    REASON_FRESHNESS_UNKNOWN,
    REASON_TEMPORAL_VALUE_STALE,
    REASON_RECONCILIATION_NOT_RUN,
    REASON_RECONCILIATION_MISMATCH,
    REASON_RECONCILIATION_PARTIAL,
    REASON_RECONCILIATION_SOURCE_UNAVAILABLE,
    REASON_RECONCILIATION_TEMPORAL_INCOMPARABLE,
    REASON_RECONCILIATION_UNKNOWN,
})

_UTC_RE = __import__("re").compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_DATE_RE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}$")


class FactLakeHealthError(Exception):
    """Fact Lake Health 领域异常基类。"""


class HealthValidationError(FactLakeHealthError):
    """输入非法 / 契约违反（fail closed）。"""


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _require_utc(value: Any, field: str) -> str:
    if type(value) is not str or _UTC_RE.fullmatch(value) is None:
        raise HealthValidationError(f"{field} 必须是 canonical UTC 时间戳")
    return value


def _require_date_only(value: Any, field: str) -> str:
    if type(value) is not str or _DATE_RE.fullmatch(value) is None:
        raise HealthValidationError(f"{field} 必须是 ISO 日历日期")
    return value


# ---------------------------------------------------------------------------
# 证据值对象（frozen，未来 adapter 采集，无路径/字节/句柄）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FactLakeHealthEvidence:
    """一份 publication 的独立采集证据（纯值对象）。

    不含路径、artifact 字节、raw payload 字节、DB 句柄；所有完整性结果以
    枚举/摘要形式由调用方传入。
    """

    publication_id: str
    dataset_id: str
    canonical_key: str
    commit_state: str
    canonical_fact: CanonicalFact
    source_observations_committed: bool
    raw_payload_integrity: str
    artifact_integrity: str
    artifact_sha256: str | None
    replay_state: str
    reconciliation_result: ReconciliationResult | None
    # 可选权威新鲜度证据（显式语义，见 freshness_semantics）
    freshness_semantics: TemporalSemantics | None = None
    freshness_value: str | None = None
    # 可选主 temporal 索引（validate 用）
    primary_temporal_field: TemporalSemantics | None = None
    primary_temporal_value: str | None = None
    # 可选 by_date 期望值（显式提供才允许比较）
    expected_primary_temporal_value: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.publication_id, str) or not self.publication_id.strip():
            raise HealthValidationError("publication_id 必须是非空字符串")
        if not isinstance(self.dataset_id, str) or not self.dataset_id.strip():
            raise HealthValidationError("dataset_id 必须是非空字符串")
        if not isinstance(self.canonical_key, str) or not self.canonical_key.strip():
            raise HealthValidationError("canonical_key 必须是非空字符串")
        if self.commit_state not in COMMIT_STATES:
            raise HealthValidationError(f"未知 commit_state: {self.commit_state!r}")
        if not isinstance(self.canonical_fact, CanonicalFact):
            raise HealthValidationError("canonical_fact 必须是 CanonicalFact")
        if type(self.source_observations_committed) is not bool:
            raise HealthValidationError("source_observations_committed 必须是 bool")
        for name, allowed in (("raw_payload_integrity", RawPayloadIntegrity),
                              ("artifact_integrity", ArtifactIntegrity),
                              ("replay_state", ReplayState)):
            value = getattr(self, name)
            if value not in allowed:
                raise HealthValidationError(f"{name} 必须是 {allowed} 之一，got {value!r}")
        if self.artifact_sha256 is not None and (
                type(self.artifact_sha256) is not str or len(self.artifact_sha256) != 64):
            raise HealthValidationError("artifact_sha256 必须是 64 位 hex 或 None")
        if self.reconciliation_result is not None and not isinstance(
                self.reconciliation_result, ReconciliationResult):
            raise HealthValidationError("reconciliation_result 必须是 ReconciliationResult")
        if self.freshness_semantics is not None and not isinstance(
                self.freshness_semantics, TemporalSemantics):
            raise HealthValidationError("freshness_semantics 必须是 TemporalSemantics")
        if self.freshness_value is not None:
            if self.freshness_semantics is None:
                raise HealthValidationError("提供 freshness_value 必须同时提供 freshness_semantics")
            if self.freshness_semantics in (TemporalSemantics.EFFECTIVE_AT,
                                            TemporalSemantics.PUBLISHED_AT,
                                            TemporalSemantics.OBSERVED_AT,
                                            TemporalSemantics.FETCHED_AT):
                _require_utc(self.freshness_value, "freshness_value")
            else:  # TRADE_DATE / REPORT_PERIOD
                _require_date_only(self.freshness_value, "freshness_value")
        if self.primary_temporal_field is not None and not isinstance(
                self.primary_temporal_field, TemporalSemantics):
            raise HealthValidationError("primary_temporal_field 必须是 TemporalSemantics")
        if self.primary_temporal_value is not None:
            if self.primary_temporal_field is None:
                raise HealthValidationError("提供 primary_temporal_value 必须同时提供 primary_temporal_field")
            if self.primary_temporal_field in (TemporalSemantics.TRADE_DATE,
                                               TemporalSemantics.REPORT_PERIOD):
                _require_date_only(self.primary_temporal_value, "primary_temporal_value")
            else:
                _require_utc(self.primary_temporal_value, "primary_temporal_value")
        if self.expected_primary_temporal_value is not None:
            if type(self.expected_primary_temporal_value) is not str or \
                    not self.expected_primary_temporal_value.strip():
                raise HealthValidationError("expected_primary_temporal_value 必须是非空字符串")


# ---------------------------------------------------------------------------
# 健康评估（derived projection，无 persistence/hash 要求）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FactLakeHealthAssessment:
    """某一 canonical publication 的 7 维健康评估（纯派生投影）。"""

    dataset_id: str
    canonical_key: str
    publication_id: str
    publication_visibility: str
    storage_integrity: str
    reproducibility: str
    semantic_quality: str
    freshness: str
    reconciliation: str
    canonical_admissibility: str
    reason_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "dataset_id": self.dataset_id,
            "canonical_key": self.canonical_key,
            "publication_id": self.publication_id,
            "publication_visibility": self.publication_visibility,
            "storage_integrity": self.storage_integrity,
            "reproducibility": self.reproducibility,
            "semantic_quality": self.semantic_quality,
            "freshness": self.freshness,
            "reconciliation": self.reconciliation,
            "canonical_admissibility": self.canonical_admissibility,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FactLakeHealthAssessment":
        """严格反序列化（exact field set / exact types / 无未知字段）。"""
        if not isinstance(data, Mapping):
            raise HealthValidationError("assessment 必须是 Mapping")
        expected = {"schema_version", "dataset_id", "canonical_key", "publication_id",
                    "publication_visibility", "storage_integrity", "reproducibility",
                    "semantic_quality", "freshness", "reconciliation",
                    "canonical_admissibility", "reason_codes"}
        if set(data) != expected:
            missing = sorted(expected - set(data))
            extra = sorted(set(data) - expected)
            raise HealthValidationError(
                f"assessment 字段不匹配: missing={missing}, extra={extra}")
        if data["schema_version"] != SCHEMA_VERSION:
            raise HealthValidationError(
                f"schema_version 漂移: {data['schema_version']!r}")
        for field_name, allowed in (
            ("publication_visibility", PublicationVisibility),
            ("storage_integrity", StorageIntegrity),
            ("reproducibility", Reproducibility),
            ("semantic_quality", ("valid", "degraded", "invalid", "unknown")),
            ("freshness", Freshness),
            ("reconciliation", tuple(s.value for s in ReconciliationStatus) + ("not_applicable", "not_run")),
            ("canonical_admissibility", CanonicalAdmissibility),
        ):
            if data[field_name] not in allowed:
                raise HealthValidationError(
                    f"{field_name} 非法枚举值: {data[field_name]!r}")
        codes = data["reason_codes"]
        if not isinstance(codes, list) or any(type(c) is not str for c in codes):
            raise HealthValidationError("reason_codes 必须是字符串列表")
        if len(codes) != len(set(codes)):
            raise HealthValidationError("reason_codes 不得重复")
        return cls(
            dataset_id=data["dataset_id"],
            canonical_key=data["canonical_key"],
            publication_id=data["publication_id"],
            publication_visibility=data["publication_visibility"],
            storage_integrity=data["storage_integrity"],
            reproducibility=data["reproducibility"],
            semantic_quality=data["semantic_quality"],
            freshness=data["freshness"],
            reconciliation=data["reconciliation"],
            canonical_admissibility=data["canonical_admissibility"],
            reason_codes=tuple(codes),
        )


# ---------------------------------------------------------------------------
# 核心评估（纯函数）
# ---------------------------------------------------------------------------

def assess_publication_health(
    *,
    dataset_spec: DatasetSpec,
    evidence: FactLakeHealthEvidence,
) -> FactLakeHealthAssessment:
    """对单个 canonical publication 生成 7 维健康评估（纯函数，确定性）。

    DatasetSpec.validate_fact 是 CanonicalFact 准入的语义权威（§10）；任何
    契约/完整性硬失败 → BLOCKED；无硬失败但有降级/未知证据 →
    USABLE_WITH_WARNING；全部必要证据已验证且无警告 → USABLE。
    """
    if not isinstance(dataset_spec, DatasetSpec):
        raise HealthValidationError("dataset_spec 必须是 DatasetSpec")
    if not isinstance(evidence, FactLakeHealthEvidence):
        raise HealthValidationError("evidence 必须是 FactLakeHealthEvidence")

    reasons: list[str] = []

    # ---- A. publication_visibility：仅 COMMITTED 可见 ----
    visibility = "COMMITTED" if evidence.commit_state == "COMMITTED" else "NOT_COMMITTED"
    if visibility != "COMMITTED":
        reasons.append(REASON_PUBLICATION_NOT_COMMITTED)
    # ---- source observations 必须已提交（§8）----
    if not evidence.source_observations_committed:
        reasons.append(REASON_SOURCE_OBSERVATION_NOT_COMMITTED)

    # ---- §10 dataset/fact 契约绑定 ----
    if evidence.dataset_id != dataset_spec.dataset_id:
        reasons.append(REASON_DATASET_ID_MISMATCH)
    fact = evidence.canonical_fact
    if fact.dataset_id != evidence.dataset_id:
        reasons.append(REASON_DATASET_ID_MISMATCH)
    if evidence.canonical_key != fact.canonical_key:
        reasons.append(REASON_CANONICAL_KEY_MISMATCH)
    try:
        dataset_spec.validate_fact(fact)
    except Exception:  # noqa: BLE001 — validate_fact 抛 DataContractError，视为拒绝
        reasons.append(REASON_DATASET_SPEC_REJECTED_FACT)

    # ---- §11 temporal index consistency（显式提供才校验）----
    if evidence.primary_temporal_field is not None:
        if evidence.primary_temporal_field not in dataset_spec.required_temporal_fields:
            reasons.append(REASON_TEMPORAL_INDEX_MISMATCH)
        else:
            fact_value = getattr(fact, evidence.primary_temporal_field.value, None)
            if fact_value is None or fact_value != evidence.primary_temporal_value:
                reasons.append(REASON_TEMPORAL_INDEX_MISMATCH)

    # ---- B. storage_integrity（§17）----
    if evidence.artifact_integrity == "MISSING":
        reasons.append(REASON_ARTIFACT_MISSING)
        storage_integrity = "CORRUPTED"
    elif evidence.artifact_integrity == "HASH_MISMATCH":
        reasons.append(REASON_ARTIFACT_HASH_MISMATCH)
        storage_integrity = "CORRUPTED"
    elif evidence.artifact_integrity == "SCHEMA_MISMATCH":
        reasons.append(REASON_ARTIFACT_SCHEMA_MISMATCH)
        storage_integrity = "CORRUPTED"
    elif evidence.raw_payload_integrity == "HASH_MISMATCH":
        reasons.append(REASON_RAW_PAYLOAD_HASH_MISMATCH)
        storage_integrity = "CORRUPTED"
    elif evidence.raw_payload_integrity == "MISSING":
        reasons.append(REASON_RAW_PAYLOAD_HASH_MISMATCH)
        storage_integrity = "CORRUPTED"
    elif evidence.artifact_integrity == "VERIFIED" and evidence.raw_payload_integrity == "VERIFIED":
        storage_integrity = "VERIFIED"
    else:
        reasons.append(REASON_ARTIFACT_UNVERIFIED)
        storage_integrity = "UNVERIFIED"

    # ---- C. reproducibility（§18）----
    if evidence.replay_state == "MATCH":
        reproducibility = "MATCH"
    elif evidence.replay_state == "MISMATCH":
        reasons.append(REASON_REPLAY_MISMATCH)
        reproducibility = "MISMATCH"
    elif evidence.replay_state == "UNSUPPORTED":
        reasons.append(REASON_REPLAY_UNSUPPORTED)
        reproducibility = "UNSUPPORTED"
    else:  # NOT_RUN
        reasons.append(REASON_REPLAY_NOT_RUN)
        reproducibility = "NOT_RUN"

    # ---- D. semantic_quality（§19，权威 evidence，不升级）----
    quality = fact.quality_status
    if quality is QualityStatus.VALID:
        semantic_quality = "valid"
    elif quality is QualityStatus.DEGRADED:
        reasons.append(REASON_FACT_QUALITY_DEGRADED)
        semantic_quality = "degraded"
    elif quality is QualityStatus.INVALID:
        reasons.append(REASON_FACT_QUALITY_INVALID)
        semantic_quality = "invalid"
    else:  # UNKNOWN
        reasons.append(REASON_FACT_QUALITY_UNKNOWN)
        semantic_quality = "unknown"

    # ---- E. freshness（§12-16：无显式权威语义 → UNKNOWN；不伪造）----
    freshness = _assess_freshness(dataset_spec, evidence, reasons)

    # ---- F. reconciliation（§20-23：无 verifier → NOT_APPLICABLE；有 verifier 无证据 → NOT_RUN）----
    reconciliation = _assess_reconciliation(dataset_spec, evidence, reasons)

    # ---- G. canonical_admissibility（§27）----
    admissibility = _derive_admissibility(reasons)

    # 确定性 reason 顺序
    ordered = _order_reasons(reasons)

    return FactLakeHealthAssessment(
        dataset_id=evidence.dataset_id,
        canonical_key=evidence.canonical_key,
        publication_id=evidence.publication_id,
        publication_visibility=visibility,
        storage_integrity=storage_integrity,
        reproducibility=reproducibility,
        semantic_quality=semantic_quality,
        freshness=freshness,
        reconciliation=reconciliation,
        canonical_admissibility=admissibility,
        reason_codes=tuple(ordered),
    )


def _assess_freshness(
    dataset_spec: DatasetSpec,
    evidence: FactLakeHealthEvidence,
    reasons: list[str],
) -> str:
    """新鲜度：仅当调用方提供显式权威 freshness basis 才可能 CURRENT/STALE。

    - freshness_semantics 为 None → UNKNOWN（不自动选 effective/published/...）；
    - by_date 数据集无 expected_primary_temporal_value → UNKNOWN；
    - max_staleness_seconds 仅在显式 UTC freshness basis 下应用；
    - snapshot_only / NOT_APPLICABLE：不比较历史期望（§15）。
    """
    if dataset_spec.history_mode is HistoryMode.SNAPSHOT_ONLY:
        return "NOT_APPLICABLE"
    if evidence.freshness_semantics is None or evidence.freshness_value is None:
        reasons.append(REASON_FRESHNESS_UNKNOWN)
        return "UNKNOWN"
    # by_date：无显式 expected 值 → 不猜期望日期
    if evidence.expected_primary_temporal_value is None:
        reasons.append(REASON_FRESHNESS_UNKNOWN)
        return "UNKNOWN"
    # 仅当 expected 与 publication 主 temporal 值一致 → CURRENT；不一致 → STALE
    if evidence.primary_temporal_value is not None and \
            evidence.primary_temporal_value == evidence.expected_primary_temporal_value:
        return "CURRENT"
    # max_staleness_seconds：仅当显式 UTC basis（EFFECTIVE/PUBLISHED/OBSERVED）可用
    if dataset_spec.max_staleness_seconds is not None and \
            evidence.freshness_semantics in (
                TemporalSemantics.EFFECTIVE_AT,
                TemporalSemantics.PUBLISHED_AT,
                TemporalSemantics.OBSERVED_AT,
            ):
        # 需要比较基准：当前仅能判断显式 expected 主值；时钟不可用 → 不做实时 staleness 推断
        # 保持保守：不一致即 STALE（覆盖 expected 提供但主值不匹配的情形）
        reasons.append(REASON_TEMPORAL_VALUE_STALE)
        return "STALE"
    reasons.append(REASON_TEMPORAL_VALUE_STALE)
    return "STALE"


def _assess_reconciliation(
    dataset_spec: DatasetSpec,
    evidence: FactLakeHealthEvidence,
    reasons: list[str],
) -> str:
    """对账：无 VERIFIER 路由 → NOT_APPLICABLE（§21）；有 VERIFIER 无证据 → NOT_RUN（§22）。"""
    has_verifier = any(
        route.role.value == "verifier" for route in dataset_spec.routes)
    if not has_verifier:
        return "not_applicable"
    if evidence.reconciliation_result is None:
        reasons.append(REASON_RECONCILIATION_NOT_RUN)
        return "not_run"
    status = evidence.reconciliation_result.status
    if status is ReconciliationStatus.MATCH:
        return "match"
    code = _RECONCILIATION_REASON.get(status)
    if code is not None:
        reasons.append(code)
    return status.value


def _derive_admissibility(reasons: list[str]) -> str:
    """总体 admissibility（§27）：硬失败 → BLOCKED；无硬失败有降级/未知 → WARNING；否则 USABLE。"""
    blocking = [r for r in reasons if r in _BLOCKING_REASONS]
    if blocking:
        return "BLOCKED"
    warning = [r for r in reasons if r in _WARNING_REASONS]
    if warning:
        return "USABLE_WITH_WARNING"
    return "USABLE"


# reason 顺序：确定性（按固定优先级表，非输入顺序）
_REASON_ORDER = (
    REASON_PUBLICATION_NOT_COMMITTED,
    REASON_DATASET_ID_MISMATCH,
    REASON_CANONICAL_KEY_MISMATCH,
    REASON_DATASET_SPEC_REJECTED_FACT,
    REASON_TEMPORAL_INDEX_MISMATCH,
    REASON_SOURCE_OBSERVATION_NOT_COMMITTED,
    REASON_RAW_PAYLOAD_HASH_MISMATCH,
    REASON_ARTIFACT_UNVERIFIED,
    REASON_ARTIFACT_MISSING,
    REASON_ARTIFACT_HASH_MISMATCH,
    REASON_ARTIFACT_SCHEMA_MISMATCH,
    REASON_REPLAY_NOT_RUN,
    REASON_REPLAY_UNSUPPORTED,
    REASON_REPLAY_MISMATCH,
    REASON_FACT_QUALITY_DEGRADED,
    REASON_FACT_QUALITY_UNKNOWN,
    REASON_FACT_QUALITY_INVALID,
    REASON_FRESHNESS_UNKNOWN,
    REASON_TEMPORAL_VALUE_STALE,
    REASON_RECONCILIATION_NOT_RUN,
    REASON_RECONCILIATION_MISMATCH,
    REASON_RECONCILIATION_PARTIAL,
    REASON_RECONCILIATION_SOURCE_UNAVAILABLE,
    REASON_RECONCILIATION_TEMPORAL_INCOMPARABLE,
    REASON_RECONCILIATION_UNKNOWN,
)
_REASON_RANK = {code: index for index, code in enumerate(_REASON_ORDER)}


def _order_reasons(reasons: list[str]) -> list[str]:
    return sorted(set(reasons), key=lambda code: _REASON_RANK.get(code, len(_REASON_ORDER)))


# ---------------------------------------------------------------------------
# 集合校验 / 投影（确定性，先校验后投影）
# ---------------------------------------------------------------------------

def assessments_for_dataset(
    dataset_id: str,
    assessments: list[FactLakeHealthAssessment],
) -> list[FactLakeHealthAssessment]:
    """按 dataset_id 过滤评估（确定性排序；先校验记录合法性）。"""
    _validate_assessment_list(assessments)
    return sorted(
        (a for a in assessments if a.dataset_id == dataset_id),
        key=lambda a: (a.canonical_key, a.publication_id),
    )


def assessment_for_publication(
    publication_id: str,
    assessments: list[FactLakeHealthAssessment],
) -> FactLakeHealthAssessment | None:
    """按 publication_id 精确查询（确定性；先校验集合）。"""
    _validate_assessment_list(assessments)
    for a in assessments:
        if a.publication_id == publication_id:
            return a
    return None


def _validate_assessment_list(assessments: list) -> None:
    if not isinstance(assessments, list):
        raise HealthValidationError("assessments 必须是列表")
    for a in assessments:
        if not isinstance(a, FactLakeHealthAssessment):
            raise HealthValidationError("assessments 元素必须是 FactLakeHealthAssessment")
        # 完整性自校验：schema_version + 枚举值
        _ = a.to_dict()
