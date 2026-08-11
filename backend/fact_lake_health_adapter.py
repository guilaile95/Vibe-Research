"""Fact Lake Health Read-Only Evidence Adapter v0.1（DS-L1-H2）。

把已验收的 Fact Lake v3（S2）公共只读 authority 桥接进已验收的 Fact Lake
Health Core（H1）：

    FactLake committed public read APIs
        ↓
    collect_fact_lake_health_evidence(...)
        ↓
    FactLakeHealthEvidence
        ↓
    assess_publication_health(...)（H1 语义权威，不重复实现）
        ↓
    FactLakeHealthAssessment

- **只读句柄硬不变量**：仅接受 ``lake.readonly is True``；可写句柄 → 拒绝。
  生产代码零写操作（Fact Lake 全部写入口均不得调用，见 §28 源码扫描）。
- **仅公共 Fact Lake API**：``open_existing_fact_lake`` /
  ``get_canonical_publication`` / ``get_observation`` / ``get_normalization`` /
  ``verify_canonical_artifact`` / ``list_reconciliations``；不 import SQLite、
  不直接查表、不解析 control DB、不重复 schema/path/blob hashing 权威
  （那些权威由 Fact Lake Store 拥有，本模块只消费其结果）。
- **COMMITTED-only**：``get_canonical_publication`` 只返回已提交 publication；
  STAGING / FAILED / ABORTED 天然不可见 → ``PUBLICATION_NOT_VISIBLE`` 失败。
- **集合失败 ≠ 维度分类**：公共 getter fail-closed（FactLakeCorruptedError /
  PathError / SchemaVersionError / BusyError 等）统一映射为确定性
  ``HealthEvidenceCollectionError`` code；绝不把未知来源的损坏猜测成
  artifact/raw HASH_MISMATCH（§9 NO_FAKE_DIMENSION_CLASSIFICATION）。
- **零时钟**：不读墙钟 / mtime / 序 / vintage 推断新鲜度；只有调用方显式
  提供 ``freshness_semantics`` 与 ``freshness_reference_at`` 时，才按精确语义
  从 committed source 采集对应值（FETCHED_AT 来自 observation.fetched_at；
  TRADE_DATE/REPORT_PERIOD 来自 fact 精确坐标；无值 → None → H1 保持 UNKNOWN）。
- **对账 harvest**：只从 ``list_reconciliations`` 采集与当前 fact
  ``source_observation_ids`` 绑定的结果；0 个 → None（H1 用 persisted 状态）；
  1 个唯一语义 → 提供给 H1；多个精确重复 → 确定性去重；多个不同 → 失败
  ``RECONCILIATION_AMBIGUOUS``。绝不 latest/sequence/winner 选择。
- **replay**：Fact Lake Store v3 无通用跨数据集 replay 公共权威 →
  ``replay_state = NOT_RUN``（REPLAY_COLLECTION = NOT_RUN_BY_GENERIC_ADAPTER_V01）。
- 本 slice 不接入 Data Health UI/API/service/frontend（FUTURE / NOT AUTHORIZED）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from data_contracts import (
    DatasetSpec,
    ReconciliationResult,
    TemporalSemantics,
)
from fact_lake_health import (
    FactLakeHealthAssessment,
    FactLakeHealthEvidence,
    assess_publication_health,
)
from fact_lake_store import (
    FactLake,
    FactLakeBusyError,
    FactLakeCorruptedError,
    FactLakeHashMismatchError,
    FactLakeNotInitializedError,
    FactLakePathError,
    FactLakeSchemaVersionError,
    StoredCanonicalPublication,
)


# ---------------------------------------------------------------------------
# 确定性集合失败模型（§9）：集合失败 → NO FactLakeHealthEvidence / NO fake assessment
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HealthEvidenceCollectionFailure:
    """一次证据收集的确定性失败结果（绝不产出证据或评估）。"""

    code: str
    detail: str

    def to_dict(self) -> dict:
        return {"code": self.code, "detail": self.detail}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HealthEvidenceCollectionFailure":
        if not isinstance(data, Mapping):
            raise TypeError("failure 必须是 Mapping")
        expected = {"code", "detail"}
        if set(data) != expected:
            raise ValueError(f"failure 字段不匹配: {sorted(set(data) - expected)}")
        code = data["code"]
        detail = data["detail"]
        if code not in _KNOWN_FAILURE_CODES:
            raise ValueError(f"未知 collection failure code: {code!r}")
        if type(detail) is not str or not detail.strip():
            raise ValueError("detail 必须是非空 str")
        return cls(code=code, detail=detail)


class HealthEvidenceCollectionError(Exception):
    """集合失败（确定性的失败边界；生产代码只在无法构造失败值时抛出）。"""

    def __init__(self, failure: HealthEvidenceCollectionFailure):
        super().__init__(failure.detail)
        self.failure = failure


# 确定性失败 codes（稳定命名）
FAILURE_NOT_INITIALIZED = "FACT_LAKE_NOT_INITIALIZED"
FAILURE_SCHEMA_UNSUPPORTED = "FACT_LAKE_SCHEMA_UNSUPPORTED"
FAILURE_BUSY = "FACT_LAKE_BUSY"
FAILURE_CORRUPTED = "FACT_LAKE_CORRUPTED"
FAILURE_PATH_UNSAFE = "FACT_LAKE_PATH_UNSAFE"
FAILURE_PUBLICATION_NOT_VISIBLE = "PUBLICATION_NOT_VISIBLE"
FAILURE_RECONCILIATION_AMBIGUOUS = "RECONCILIATION_AMBIGUOUS"
FAILURE_BAD_ARGUMENT = "BAD_ARGUMENT"
FAILURE_INTERNAL = "INTERNAL"

_KNOWN_FAILURE_CODES = frozenset({
    FAILURE_NOT_INITIALIZED,
    FAILURE_SCHEMA_UNSUPPORTED,
    FAILURE_BUSY,
    FAILURE_CORRUPTED,
    FAILURE_PATH_UNSAFE,
    FAILURE_PUBLICATION_NOT_VISIBLE,
    FAILURE_RECONCILIATION_AMBIGUOUS,
    FAILURE_BAD_ARGUMENT,
    FAILURE_INTERNAL,
})

# Fact Lake Store fail-closed 异常 → 确定性 code（不把未知来源的损坏猜成某维度）
_STORE_FAILURE_CODE = (
    (FactLakeNotInitializedError, FAILURE_NOT_INITIALIZED),
    (FactLakeSchemaVersionError, FAILURE_SCHEMA_UNSUPPORTED),
    (FactLakeBusyError, FAILURE_BUSY),
    (FactLakePathError, FAILURE_PATH_UNSAFE),
    (FactLakeCorruptedError, FAILURE_CORRUPTED),
    (FactLakeHashMismatchError, FAILURE_CORRUPTED),
)


# ---------------------------------------------------------------------------
# 参数契约（调用方显式提供的策略上下文，§17/§19：adapter 不做任何自动推断）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FreshnessRequest:
    """显式新鲜度请求（无墙钟 / mtime / 序 / 日期推断）。"""

    semantics: TemporalSemantics
    reference_at: str | None = None


@dataclass(frozen=True)
class HealthCollectionRequest:
    """证据收集的显式参数：唯一必填 publication_id，其余全部可选策略上下文。"""

    publication_id: str
    freshness: FreshnessRequest | None = None
    expected_primary_temporal_value: str | None = None


# 精确语义 → 值来源（§18：无 cross-semantic substitution）
_EFFECTIVE_AT = TemporalSemantics.EFFECTIVE_AT
_PUBLISHED_AT = TemporalSemantics.PUBLISHED_AT
_OBSERVED_AT = TemporalSemantics.OBSERVED_AT
_FETCHED_AT = TemporalSemantics.FETCHED_AT
_TRADE_DATE = TemporalSemantics.TRADE_DATE
_REPORT_PERIOD = TemporalSemantics.REPORT_PERIOD

_CONTINUOUS_SEMANTICS = frozenset({
    _EFFECTIVE_AT, _PUBLISHED_AT, _OBSERVED_AT, _FETCHED_AT,
})

_SHA256_PREFIX_RE = re.compile(r"^sha256:(?P<digest>[0-9a-f]{64})$")


def _require_nonempty_text(value: Any, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} 必须是非空规范文本")
    return value


def _require_publication_id(request: HealthCollectionRequest) -> None:
    if not isinstance(request, HealthCollectionRequest):
        raise TypeError("request 必须是 HealthCollectionRequest")
    _require_nonempty_text(request.publication_id, "publication_id")
    if request.expected_primary_temporal_value is not None:
        _require_nonempty_text(
            request.expected_primary_temporal_value,
            "expected_primary_temporal_value",
        )


def _normalize_failure(exc: BaseException, fallback_code: str) -> HealthEvidenceCollectionFailure:
    for exc_type, code in _STORE_FAILURE_CODE:
        if isinstance(exc, exc_type):
            return HealthEvidenceCollectionFailure(code=code, detail=str(exc))
    return HealthEvidenceCollectionFailure(
        code=fallback_code,
        detail=f"{type(exc).__name__}: {exc}",
    )


# ---------------------------------------------------------------------------
# 内部证据构造（严格 64 位小写 hex；仅 `sha256:` 前缀表示桥接，§11）
# ---------------------------------------------------------------------------

def _bridge_artifact_sha256(stored: StoredCanonicalPublication) -> str | None:
    """Fact Lake `sha256:<64 hex>` → H1 `64 lowercase hex`（严格，无静默接受）。"""
    value = stored.artifact_sha256
    if value is None:
        return None
    match = _SHA256_PREFIX_RE.fullmatch(value)
    if match is None:
        raise HealthEvidenceCollectionError(HealthEvidenceCollectionFailure(
            code=FAILURE_CORRUPTED,
            detail=f"artifact_sha256 格式不支持（仅接受 sha256:<64 lowercase hex>）: {value!r}",
        ))
    return match.group("digest")


def _harvest_reconciliation(
    lake: FactLake,
    bound: Sequence[ReconciliationResult],
) -> ReconciliationResult | None:
    """对已绑定结果去重（R2 语义 key）并拒绝语义冲突（§14）。"""
    if not bound:
        return None
    seen: dict[tuple[Any, ...], ReconciliationResult] = {}
    for result in bound:
        key = (
            result.dataset_id,
            result.status.value,
            result.comparison_policy_id,
            result.comparison_policy_version,
            result.left_observation_id,
            result.right_observation_id,
            _canonical_json(result.comparison_evidence),
            result.left_value,
            result.right_value,
        )
        previous = seen.get(key)
        if previous is not None:
            if previous != result:
                # 同一语义 key 但结果不同（契约不允许）→ 不静默选择
                raise HealthEvidenceCollectionError(HealthEvidenceCollectionFailure(
                    code=FAILURE_RECONCILIATION_AMBIGUOUS,
                    detail="绑定对账结果语义重复但内容不同",
                ))
            continue
        seen[key] = result
    unique = list(seen.values())
    if len(unique) == 1:
        return unique[0]
    raise HealthEvidenceCollectionError(HealthEvidenceCollectionFailure(
        code=FAILURE_RECONCILIATION_AMBIGUOUS,
        detail=f"存在 {len(unique)} 个不同语义的绑定对账结果（不允许 winner/latest 选择）",
    ))


def _canonical_json(value: Any) -> str:
    """本地 canonical JSON（仅用于对账去重 key，不重复 Fact Lake blob 权威）。"""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


# ---------------------------------------------------------------------------
# 公共只读 API 映射
# ---------------------------------------------------------------------------

def _map_failure(exc: BaseException) -> HealthEvidenceCollectionFailure:
    return _normalize_failure(exc, FAILURE_INTERNAL)


def _collect_evidence_from_lake(
    lake: FactLake,
    spec: DatasetSpec,
    request: HealthCollectionRequest,
) -> FactLakeHealthEvidence:
    """内部实现：仅公共只读 API + 零写；异常映射为确定性失败。"""
    _require_publication_id(request)
    if not isinstance(lake, FactLake):
        raise TypeError("lake 必须是 FactLake")
    if not isinstance(spec, DatasetSpec):
        raise TypeError("spec 必须是 DatasetSpec")
    if not lake.readonly:
        raise HealthEvidenceCollectionError(HealthEvidenceCollectionFailure(
            code=FAILURE_BAD_ARGUMENT,
            detail="Fact Lake 句柄必须为只读（readonly=True）",
        ))

    publication = lake.get_canonical_publication(request.publication_id)
    if publication is None:
        raise HealthEvidenceCollectionError(HealthEvidenceCollectionFailure(
            code=FAILURE_PUBLICATION_NOT_VISIBLE,
            detail=f"publication 不可见（仅允许已提交 publication 进入健康证据）: {request.publication_id!r}",
        ))
    if publication.commit_state != "COMMITTED":
        # 公共只读 API 保证只返回 committed；出现其他状态 = 契约漂移，fail closed
        raise HealthEvidenceCollectionError(HealthEvidenceCollectionFailure(
            code=FAILURE_CORRUPTED,
            detail=f"committed-only 读取返回了非 COMMITTED 状态: {publication.commit_state!r}",
        ))

    fact = publication.fact
    # 仅返回已提交 source observation（get_observation 已 verify blob）
    source = lake.get_observation(publication.source_observation_id)
    if source is None:
        raise HealthEvidenceCollectionError(HealthEvidenceCollectionFailure(
            code=FAILURE_CORRUPTED,
            detail="committed publication 缺少已提交 source observation",
        ))

    normalization = lake.get_normalization(publication.source_observation_id)
    if normalization is None:
        # 集合失败：normalization 权威缺失（不猜测维度）
        raise HealthEvidenceCollectionError(HealthEvidenceCollectionFailure(
            code=FAILURE_CORRUPTED,
            detail="committed publication 缺少 persisted normalized evidence",
        ))

    # artifact：仅在公共 authority 已验证后桥接表示（verify_canonical_artifact）
    artifact_sha256 = _bridge_artifact_sha256(publication)
    try:
        lake.verify_canonical_artifact(
            publication.artifact_relpath,
            publication.artifact_sha256 or "",
        )
    except FactLakeCorruptedError as exc:
        raise HealthEvidenceCollectionError(
            _normalize_failure(exc, FAILURE_CORRUPTED)) from exc
    except FactLakePathError as exc:
        raise HealthEvidenceCollectionError(
            _normalize_failure(exc, FAILURE_PATH_UNSAFE)) from exc

    # 对账 harvest（仅公共 list_reconciliations + 绑定过滤）
    recon = _harvest_reconciliation(
        lake,
        list(_bound_reconciliations(lake, publication, fact)),
    )

    # 新鲜度（仅显式请求；无值 → None → H1 保持 UNKNOWN；无 cross-semantic）
    freshness_semantics: TemporalSemantics | None = None
    freshness_value: str | None = None
    freshness_reference_at: str | None = None
    freshness_request = request.freshness
    if freshness_request is not None:
        semantics = freshness_request.semantics
        if semantics in _CONTINUOUS_SEMANTICS:
            value = _freshness_value_for(semantics, fact, source.observation)
            if value is not None:
                freshness_semantics = semantics
                freshness_value = value
                freshness_reference_at = freshness_request.reference_at
        else:  # TRADE_DATE / REPORT_PERIOD
            value = getattr(fact, semantics.value, None)
            if value is not None:
                freshness_semantics = semantics
                freshness_value = value
                freshness_reference_at = None

    return FactLakeHealthEvidence(
        publication_id=publication.publication_id,
        dataset_id=publication.dataset_id,
        canonical_key=publication.canonical_key,
        commit_state="COMMITTED",
        canonical_fact=fact,
        source_observations_committed=True,
        raw_payload_integrity="VERIFIED",
        artifact_integrity="VERIFIED",
        artifact_sha256=artifact_sha256,
        replay_state="NOT_RUN",
        reconciliation_result=recon,
        freshness_semantics=freshness_semantics,
        freshness_value=freshness_value,
        freshness_reference_at=freshness_reference_at,
        primary_temporal_field=TemporalSemantics(publication.primary_temporal_field),
        primary_temporal_value=publication.primary_temporal_value,
        expected_primary_temporal_value=request.expected_primary_temporal_value,
    )


def _bound_reconciliations(
    lake: FactLake,
    publication: StoredCanonicalPublication,
    fact,
):
    """从公共 list_reconciliations 中过滤与当前 fact source observations 绑定的结果。"""
    observation_ids = set(fact.source_observation_ids)
    for stored in lake.list_reconciliations(dataset_id=publication.dataset_id):
        result = stored.result
        if result.left_observation_id in observation_ids or \
                result.right_observation_id in observation_ids:
            yield result


def _freshness_value_for(
    semantics: TemporalSemantics,
    fact,
    observation,
) -> str | None:
    """精确语义 → 精确字段（§18：FETCHED_AT → observation.fetched_at；其余 fact 字段）。"""
    if semantics is _FETCHED_AT:
        return observation.fetched_at
    return getattr(fact, semantics.value, None)


# ---------------------------------------------------------------------------
# 双层公共 API（§21）：A 收集 / B 收集+评估
# ---------------------------------------------------------------------------

def collect_fact_lake_health_evidence(
    *,
    lake: FactLake,
    dataset_spec: DatasetSpec,
    request: HealthCollectionRequest,
) -> FactLakeHealthEvidence:
    """A. 只读收集一份 committed publication 的健康证据（零写）。

    集合失败 → 抛 ``HealthEvidenceCollectionError``（携带确定性
    ``HealthEvidenceCollectionFailure.code``）；绝不返回伪造证据。
    """
    try:
        return _collect_evidence_from_lake(lake, dataset_spec, request)
    except HealthEvidenceCollectionError:
        raise
    except Exception as exc:  # 兜底：不泄露内部细节、不伪造维度分类
        raise HealthEvidenceCollectionError(
            _map_failure(exc)) from exc


def assess_fact_lake_publication(
    *,
    lake: FactLake,
    dataset_spec: DatasetSpec,
    request: HealthCollectionRequest,
) -> FactLakeHealthAssessment:
    """B. 收集 + H1 语义评估（不重复 H1 健康推导，§21）。

    集合失败 → 同 ``collect_fact_lake_health_evidence``；评估阶段出现
    ``HealthValidationError`` 时转换为确定性失败（BAD_ARGUMENT / INTERNAL）。
    """
    evidence = collect_fact_lake_health_evidence(
        lake=lake,
        dataset_spec=dataset_spec,
        request=request,
    )
    try:
        return assess_publication_health(dataset_spec=dataset_spec, evidence=evidence)
    except HealthEvidenceCollectionError:
        raise
    except Exception as exc:
        raise HealthEvidenceCollectionError(
            _map_failure(exc)) from exc