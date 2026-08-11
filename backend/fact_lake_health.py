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
REASON_RECONCILIATION_UNBOUND = "RECONCILIATION_UNBOUND"
REASON_RECONCILIATION_STATUS_DRIFT = "RECONCILIATION_STATUS_DRIFT"

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
    REASON_RECONCILIATION_UNBOUND,
    REASON_RECONCILIATION_STATUS_DRIFT,
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


# 已知 reason codes（严格校验用，防未知 code 混入）
_KNOWN_REASON_CODES = frozenset({
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
    REASON_RECONCILIATION_UNBOUND,
    REASON_RECONCILIATION_STATUS_DRIFT,
})

# 各维度合法枚举值（严格校验用）
_SEMANTIC_QUALITY_VALUES = ("valid", "degraded", "invalid", "unknown")
_RECONCILIATION_VALUES = tuple(s.value for s in ReconciliationStatus) + (
    "not_applicable", "not_run",
)


class FactLakeHealthError(Exception):
    """Fact Lake Health 领域异常基类。"""


class HealthValidationError(FactLakeHealthError):
    """输入非法 / 契约违反（fail closed）。"""


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _require_utc(value: Any, field: str) -> str:
    """真实可解析的 canonical UTC 时间戳（P1-C：非 regex-only）。"""
    if type(value) is not str or _UTC_RE.fullmatch(value) is None:
        raise HealthValidationError(f"{field} 必须是 canonical UTC 时间戳")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HealthValidationError(f"{field} 不是真实 UTC 时间（如 2 月 30 日）") from exc
    return value


def _require_date_only(value: Any, field: str) -> str:
    """真实 ISO 日历日期（P1-C：拒绝 2026-02-31 之类不存在的日期）。"""
    if type(value) is not str or _DATE_RE.fullmatch(value) is None:
        raise HealthValidationError(f"{field} 必须是 ISO 日历日期")
    try:
        parsed = __import__("datetime").date.fromisoformat(value)
    except ValueError as exc:
        raise HealthValidationError(f"{field} 不是真实日历日期（如 2026-02-31）") from exc
    if parsed.isoformat() != value:
        raise HealthValidationError(f"{field} 不是规范 ISO 日历日期")
    return value


def _require_canonical_text(value: Any, field: str) -> str:
    """非空规范文本（REPORT_PERIOD 等；DS-A1 parity：不强制 YYYY-MM-DD）。"""
    if type(value) is not str or not value.strip():
        raise HealthValidationError(f"{field} 必须是非空规范文本")
    return value


def _require_text_or_date(semantics: TemporalSemantics, value: Any, field: str) -> str:
    """按语义校验值：TRADE_DATE 用真实日期，REPORT_PERIOD 用非空规范文本，其余 UTC。"""
    if semantics is TemporalSemantics.TRADE_DATE:
        return _require_date_only(value, field)
    if semantics is TemporalSemantics.REPORT_PERIOD:
        return _require_canonical_text(value, field)
    return _require_utc(value, field)


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
    # P1-A：显式调用方提供的 UTC 评估/参考时间（无墙钟读取；仅连续时间戳新鲜度使用）
    freshness_reference_at: str | None = None
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
                type(self.artifact_sha256) is not str
                or len(self.artifact_sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.artifact_sha256)):
            raise HealthValidationError("artifact_sha256 必须是 64 位小写 hex 或 None")
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
                _require_text_or_date(self.freshness_semantics, self.freshness_value,
                                      "freshness_value")
        if self.freshness_reference_at is not None:
            _require_utc(self.freshness_reference_at, "freshness_reference_at")
        if self.primary_temporal_field is not None and not isinstance(
                self.primary_temporal_field, TemporalSemantics):
            raise HealthValidationError("primary_temporal_field 必须是 TemporalSemantics")
        if self.primary_temporal_value is not None:
            if self.primary_temporal_field is None:
                raise HealthValidationError("提供 primary_temporal_value 必须同时提供 primary_temporal_field")
            if self.primary_temporal_field is TemporalSemantics.TRADE_DATE:
                _require_date_only(self.primary_temporal_value, "primary_temporal_value")
            elif self.primary_temporal_field is TemporalSemantics.REPORT_PERIOD:
                _require_canonical_text(self.primary_temporal_value, "primary_temporal_value")
            else:
                _require_utc(self.primary_temporal_value, "primary_temporal_value")
        if self.expected_primary_temporal_value is not None:
            if self.primary_temporal_field is None:
                raise HealthValidationError(
                    "提供 expected_primary_temporal_value 必须同时提供 primary_temporal_field（fail closed）")
            if self.primary_temporal_field is TemporalSemantics.TRADE_DATE:
                _require_date_only(self.expected_primary_temporal_value,
                                   "expected_primary_temporal_value")
            elif self.primary_temporal_field is TemporalSemantics.REPORT_PERIOD:
                _require_canonical_text(self.expected_primary_temporal_value,
                                        "expected_primary_temporal_value")
            else:
                _require_utc(self.expected_primary_temporal_value,
                             "expected_primary_temporal_value")


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
        """严格反序列化（P1-D 校验权威）：exact field set / exact types /
        非空 str / 已知枚举 / 已知 reason codes / 无重复 / 无未知字段。"""
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
        # 非空 str 标识字段
        for field_name in ("dataset_id", "canonical_key", "publication_id"):
            value = data[field_name]
            if type(value) is not str or not value.strip():
                raise HealthValidationError(f"{field_name} 必须是非空 str")
        for field_name, allowed in (
            ("publication_visibility", PublicationVisibility),
            ("storage_integrity", StorageIntegrity),
            ("reproducibility", Reproducibility),
            ("semantic_quality", _SEMANTIC_QUALITY_VALUES),
            ("freshness", Freshness),
            ("reconciliation", _RECONCILIATION_VALUES),
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
        unknown_codes = sorted(set(codes) - _KNOWN_REASON_CODES)
        if unknown_codes:
            raise HealthValidationError(f"reason_codes 含未知 code: {unknown_codes}")
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
    """新鲜度（P1-A）：仅显式权威 basis + 显式 reference 时间才可能 CURRENT/STALE。

    - freshness_semantics / freshness_value 缺失 → UNKNOWN；
    - 连续时间戳新鲜度（EFFECTIVE/PUBLISHED/OBSERVED/FETCHED）：
      * 缺 `freshness_reference_at` → UNKNOWN（不猜墙钟）；
      * 有 reference_at 且 max_staleness_seconds 定义 → 按实际年龄判
        CURRENT/STALE（边界冻结：age == threshold 视为 STALE，fail closed）；
      * 有 reference_at 无 max_staleness_seconds → UNKNOWN：时间戳+reference
        只证明 age，无数据集新鲜度策略阈值则不能证明该 age 是否可接受；
        绝不推断隐式无限阈值（reference_at < freshness_value 仍 fail closed）；
    - 坐标新鲜度（TRADE_DATE/REPORT_PERIOD）：expected 匹配 → 坐标 CURRENT；
      expected 缺失/不匹配 → UNKNOWN/STALE；
    - 两路保守合并：STALE 支配 UNKNOWN 支配 CURRENT；
    - SNAPSHOT_ONLY：禁止伪造历史覆盖，但**不抹除显式可评估的连续 staleness
      契约**（若调用方显式提供 freshness basis + reference_at，仍按连续语义评估）。
    """
    # 连续时间戳新鲜度（可独立评估，SNAPSHOT_ONLY 也不抹除）
    continuous: str | None = None
    if evidence.freshness_semantics in (
        TemporalSemantics.EFFECTIVE_AT,
        TemporalSemantics.PUBLISHED_AT,
        TemporalSemantics.OBSERVED_AT,
        TemporalSemantics.FETCHED_AT,
    ):
        if evidence.freshness_value is None:
            continuous = "UNKNOWN"
        elif evidence.freshness_reference_at is None:
            continuous = "UNKNOWN"  # 无显式 reference → 不猜墙钟
        else:
            ref = _parse_utc(evidence.freshness_reference_at)
            val = _parse_utc(evidence.freshness_value)
            if ref < val:
                # reference 早于 freshness_value → 不可能历史，fail closed
                raise HealthValidationError(
                    "freshness_reference_at 早于 freshness_value（不可能的时间序）"
                )
            age_seconds = (ref - val).total_seconds()
            if dataset_spec.max_staleness_seconds is not None:
                # 边界冻结：age >= threshold → STALE（fail closed，不宽松）
                continuous = ("CURRENT" if age_seconds < dataset_spec.max_staleness_seconds
                              else "STALE")
            else:
                # R2：无新鲜度策略阈值 → UNKNOWN。时间戳+reference 只证明 age，
                # 无阈值策略不能证明该 age 可接受；不推断隐式无限阈值。
                continuous = "UNKNOWN"

    # 坐标新鲜度（TRADE_DATE/REPORT_PERIOD）；SNAPSHOT_ONLY 禁止伪造历史覆盖
    coordinate: str | None = None
    if dataset_spec.history_mode is not HistoryMode.SNAPSHOT_ONLY:
        if evidence.expected_primary_temporal_value is None:
            coordinate = "UNKNOWN"  # 无显式期望 → 不猜期望日期
        elif evidence.primary_temporal_value is not None and \
                evidence.primary_temporal_value == evidence.expected_primary_temporal_value:
            coordinate = "CURRENT"
        else:
            coordinate = "STALE"

    # SNAPSHOT_ONLY：无连续契约 → NOT_APPLICABLE；有显式连续契约 → 保留评估（不抹除）
    if dataset_spec.history_mode is HistoryMode.SNAPSHOT_ONLY:
        if continuous is None:
            return "NOT_APPLICABLE"
        if continuous == "STALE":
            reasons.append(REASON_TEMPORAL_VALUE_STALE)
        elif continuous == "UNKNOWN":
            reasons.append(REASON_FRESHNESS_UNKNOWN)
        return continuous

    # 保守合并：STALE 支配 UNKNOWN 支配 CURRENT；无任何证据 → UNKNOWN
    candidates = [c for c in (continuous, coordinate) if c is not None]
    if not candidates:
        reasons.append(REASON_FRESHNESS_UNKNOWN)
        return "UNKNOWN"
    if "STALE" in candidates:
        reasons.append(REASON_TEMPORAL_VALUE_STALE)
        return "STALE"
    if "UNKNOWN" in candidates:
        reasons.append(REASON_FRESHNESS_UNKNOWN)
        return "UNKNOWN"
    return "CURRENT"


def _assess_reconciliation(
    dataset_spec: DatasetSpec,
    evidence: FactLakeHealthEvidence,
    reasons: list[str],
) -> str:
    """对账（P1-B）：persisted 状态始终可见 + 绑定身份 + drift fail-closed。

    优先级（persisted fact.reconciliation_status 是持久化证据，其可见性
    不依赖 DatasetSpec 是否含 verifier 路由）：

    1. 提供 ReconciliationResult 时：强制身份绑定（与 DS-A1
       attach_reconciliation 语义一致：dataset 绑定 + 至少一个 observation
       在 fact.source_observation_ids 内），未绑定 → 显式 fail-closed
       （REASON_RECONCILIATION_UNBOUND）；
    2. 绑定通过且 supplied 状态与 persisted 冲突 →
       RECONCILIATION_STATUS_DRIFT → BLOCKED，绝不静默采用任何一方；
    3. persisted 状态 != UNKNOWN → 始终保留可见（不因无 verifier 或
       NOT_RUN 而静默抹除）；
    4. 仅 persisted UNKNOWN：无 verifier → NOT_APPLICABLE（不惩罚）；
       有 verifier 无 supplied result → NOT_RUN（不伪造 MATCH）；
       有 verifier + 有效 supplied result → supplied 状态。
    """
    fact = evidence.canonical_fact
    has_verifier = any(
        route.role.value == "verifier" for route in dataset_spec.routes)
    persisted = fact.reconciliation_status
    result = evidence.reconciliation_result

    # 1) 提供 result：强制身份绑定（与 DS-A1 attach_reconciliation 一致）
    bound = False
    if result is not None:
        if result.dataset_id == dataset_spec.dataset_id and \
                result.dataset_id == evidence.dataset_id and \
                result.dataset_id == fact.dataset_id:
            obs_ids = set(fact.source_observation_ids)
            bound = result.left_observation_id in obs_ids or \
                result.right_observation_id in obs_ids
        if not bound:
            reasons.append(REASON_RECONCILIATION_UNBOUND)

    if bound:
        supplied = result.status
        if persisted is not ReconciliationStatus.UNKNOWN and \
                supplied is not persisted:
            # persisted 与 supplied 冲突 → fail closed：绝不静默采用任何一方
            # （R1：persisted MATCH + supplied MISMATCH 绝不返回 match）
            reasons.append(REASON_RECONCILIATION_STATUS_DRIFT)
            reasons.append(REASON_RECONCILIATION_NOT_RUN)
            return "not_run"
        code = _RECONCILIATION_REASON.get(supplied)
        if code is not None:
            reasons.append(code)
        if supplied is ReconciliationStatus.MATCH:
            return "match"
        return supplied.value

    # 2) 无有效 supplied 结果（None / 未绑定）：persisted 状态始终可见
    if persisted is ReconciliationStatus.MATCH:
        return "match"
    if persisted is not ReconciliationStatus.UNKNOWN:
        code = _RECONCILIATION_REASON.get(persisted)
        if code is not None:
            reasons.append(code)
        return persisted.value

    # 3) 仅 persisted UNKNOWN：无 verifier 不惩罚；有 verifier 无结果 → NOT_RUN
    if not has_verifier:
        return "not_applicable"
    reasons.append(REASON_RECONCILIATION_NOT_RUN)
    return "not_run"


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
    REASON_RECONCILIATION_UNBOUND,
    REASON_RECONCILIATION_STATUS_DRIFT,
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
    """严格集合校验（P1-D）：不信任 dataclass 类型，经 to_dict→from_dict 权威重建。

    直接构造的非法 dataclass（非法 admissibility / 未知 reason code / 空 id）会在
    round-trip 中被拒绝，投影绝不基于未校验对象。
    """
    if not isinstance(assessments, list):
        raise HealthValidationError("assessments 必须是列表")
    for a in assessments:
        if not isinstance(a, FactLakeHealthAssessment):
            raise HealthValidationError("assessments 元素必须是 FactLakeHealthAssessment")
        # 权威重建：to_dict → strict from_dict（校验 exact 字段/枚举/reason codes/hash）
        rebuilt = FactLakeHealthAssessment.from_dict(a.to_dict())
        if rebuilt != a:
            raise HealthValidationError("assessment 与严格反序列化重建不一致")
