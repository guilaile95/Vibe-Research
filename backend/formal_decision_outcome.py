"""正式决策结果来源投影核心（P0-O1-R1，纯逻辑，零 I/O）。

回答一个问题（provenance first，非评分）：

    "对于这个确切的正式冻结决策，哪些实际手动交易被正式归属给它，
     以及哪些**已经算好的**结果证据属于这些交易 / 这个决策？"

P0-O1-R1（PA1 权威重集成）：

- 绩效证据不再接受调用方自报 ``trade_ids`` / ``source`` 文本：
  证据必须从已接受的 PA1 计算结果（``performance_attribution.v2-provenance.v0.1``）
  本身派生——``input_trade_ids`` 来自 PA1 position、``computation_fingerprint`` /
  ``authority_version`` 来自 PA1 结果顶层。
- 绑定：PA1 position.security_code 必须等于决策 security_code；
  position.input_trade_ids 必须 ⊆ 当前决策的归属交易集；
  混合（决策 A 的 T1 + 决策 B 的 T2）→ 拒绝绩效证据（原 O1 blocker 反例）。
- 证据类型分离：performance evidence 与 feedback evidence 是两个独立维度；
  feedback 证据绝不把 performance_evidence_state 从 NOT_MEASURED 变为 MEASURED。

职责边界（不变）：

- 不决定投资者是否"正确"；不重算 PnL（PA1 是唯一绩效计算权威，只消费其结果）
- 不推断 Thesis 状态、不推断决策有效性、不发明 TTL
- 不修改任何既有子系统（Trade Ledger / Frozen Decision / TB1 / PA1 /
  Performance Attribution / Decision Feedback）

归属权威复用 TB1：``validate_attribution_set``。纯函数：无 SQLite / 文件系统 /
网络 / 环境 / 时钟读 / 行情 / AI / HTTP。同输入 → 同投影（无 UUID / now / random）。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from frozen_decision_store import (
    NEXT_BEST_ACTIONS,
    SNAPSHOT_KEYS,
    STRATEGIES,
    canonical_json,
)
from formal_trade_attribution import (
    DECISION_ANCHOR_FIELDS,
    TRADE_EXECUTION_STATUSES,
    TRADE_OPERATIONS,
    AttributionValidationError,
    FormalTradeAttribution,
    parse_utc_instant,
    to_canonical_utc,
    validate_attribution_set,
    verify_frozen_decision_witness,
)

SCHEMA_VERSION = "formal_decision_outcome.v0.1"

# 已接受的 PA1 权威版本契约（精确匹配，不信任任意 source 文本）
PA1_AUTHORITY_VERSION = "performance_attribution.v2-provenance.v0.1"

# 执行现实状态（规范 15）：全 not_executed → NO_EXECUTED_TRADE（非 0% 收益）
EXECUTION_SUMMARY_STATES = ("EXECUTED_TRADE", "NO_EXECUTED_TRADE")
# 绩效证据可用性（规范 11）：缺失 → NOT_MEASURED，绝不视为 0 收益
PERFORMANCE_EVIDENCE_STATES = ("MEASURED", "NOT_MEASURED")
# 反馈证据可用性（独立维度）
FEEDBACK_EVIDENCE_STATES = ("MEASURED", "NOT_MEASURED")
# 提示性原因码（中性，不构成评分）
REASON_NO_PERFORMANCE_EVIDENCE = "NO_PERFORMANCE_EVIDENCE"
REASON_NO_EXECUTED_TRADE = "NO_EXECUTED_TRADE"
REASON_CODES = (REASON_NO_PERFORMANCE_EVIDENCE, REASON_NO_EXECUTED_TRADE)

_EVIDENCE_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_TRADE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# 深度冻结 / 解冻（P0-O1-R3：集中式递归机制）
# ---------------------------------------------------------------------------

def _deep_freeze(value: Any) -> Any:
    """递归冻结：Mapping → MappingProxyType（键原样，值递归冻结）；
    list/tuple → tuple（元素递归冻结）；原语原样。

    已冻结/验证的投影持有完全不可变的结构，且与原调用方输入零共享引用。
    """
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_unfreeze(value: Any) -> Any:
    """递归解冻为全新普通 JSON 兼容结构：Mapping → dict、tuple → list。

    每次调用返回全新对象（detached copy），调用方对返回值的修改
    绝不影响内部冻结结构。
    """
    if isinstance(value, Mapping):
        return {key: _deep_unfreeze(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep_unfreeze(item) for item in value]
    return value


class FormalDecisionOutcomeError(RuntimeError):
    """正式决策结果来源投影基础异常。"""


class OutcomeValidationError(FormalDecisionOutcomeError, AttributionValidationError):
    """输入验证失败（fail closed）：决策/归属/证据/时间窗任一不合法。"""


class OutcomeEvidenceConflictError(FormalDecisionOutcomeError):
    """证据集合冲突：同 evidence_id 内容不一致（不做 latest-wins）。"""


# ---------------------------------------------------------------------------
# PA1 结果权威校验与绩效证据派生（禁止调用方自报交易绑定）
# ---------------------------------------------------------------------------


def validate_pa1_result(pa1_result: Any) -> dict[str, Any]:
    """校验已接受的 PA1 计算结果（内部一致性，权威契约）。

    校验（fail closed）：
    - authority_version 精确 == performance_attribution.v2-provenance.v0.1
    - computation_fingerprint 为 64 位小写 hex
    - selected_trade_count == len(selected_trade_ids)
    - 每个 position 携带 code 与 input_trade_ids（合法 32 hex）
    - 全部 position 的 input_trade_ids 并集 == selected_trade_ids 集合
      （内部一致：无幽灵输入、无遗漏输入）

    不重算 fingerprint、不重算任何 PnL 数值。
    """
    if not isinstance(pa1_result, Mapping):
        raise OutcomeValidationError("pa1_result：必须是 Mapping")
    if pa1_result.get("authority_version") != PA1_AUTHORITY_VERSION:
        raise OutcomeValidationError(
            f"pa1_result：authority_version 必须精确为 {PA1_AUTHORITY_VERSION}"
        )
    fingerprint = pa1_result.get("computation_fingerprint")
    if not isinstance(fingerprint, str) or not _FINGERPRINT_RE.fullmatch(fingerprint):
        raise OutcomeValidationError("pa1_result：computation_fingerprint 格式不合法")

    selected = pa1_result.get("selected_trade_ids")
    if not isinstance(selected, list) or not all(
        isinstance(t, str) and _TRADE_ID_RE.fullmatch(t) for t in selected
    ):
        raise OutcomeValidationError("pa1_result：selected_trade_ids 不合法")
    if pa1_result.get("selected_trade_count") != len(selected):
        raise OutcomeValidationError(
            "pa1_result：selected_trade_count 与 selected_trade_ids 不一致"
        )

    positions = pa1_result.get("positions")
    if not isinstance(positions, list):
        raise OutcomeValidationError("pa1_result：positions 必须是列表")
    union: set[str] = set()
    for position in positions:
        if not isinstance(position, Mapping):
            raise OutcomeValidationError("pa1_result：position 必须是对象")
        code = position.get("code")
        if not isinstance(code, str) or not _SECURITY_CODE_RE.fullmatch(code):
            raise OutcomeValidationError("pa1_result：position.code 不合法")
        input_ids = position.get("input_trade_ids")
        if not isinstance(input_ids, list) or not all(
            isinstance(t, str) and _TRADE_ID_RE.fullmatch(t) for t in input_ids
        ):
            raise OutcomeValidationError(
                f"pa1_result：position({code}).input_trade_ids 不合法"
            )
        union.update(input_ids)
    if union != set(selected):
        raise OutcomeValidationError(
            "pa1_result：positions 的 input_trade_ids 并集与 selected_trade_ids 不一致"
        )
    return {
        "authority_version": PA1_AUTHORITY_VERSION,
        "computation_fingerprint": fingerprint,
        "selected_trade_ids": list(selected),
        "positions": [dict(p) for p in positions],
    }


def _derive_performance_evidence_id(fingerprint: str, security_code: str) -> str:
    """确定性证据身份：SHA-256(fingerprint + ':' + security_code) 64 hex。

    同一 PA1 结果内不同证券 → 不同 evidence_id；同结果同证券重复 → 幂等。
    不依赖调用方自报身份。
    """
    return hashlib.sha256(
        f"{fingerprint}:{security_code}".encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class PerformanceEvidence:
    """从已接受 PA1 结果派生的绩效证据（P0-O1-R1）。

    由 ``build_performance_evidence`` 构造：trade 绑定来自
    PA1 position.input_trade_ids（计算权威自身产出），调用方不得自报。

    - evidence_id：由 (fingerprint, security_code) 确定性派生
    - input_trade_ids：PA1 position 的精确输入集（该证券）
    - metrics：PA1 position 的既有指标 payload（引用，不重算）
    - measurement 窗口 / as_of：显式输入（PA1 结果不含窗口）
    """

    evidence_id: str
    authority_version: str
    computation_fingerprint: str
    security_code: str
    input_trade_ids: tuple[str, ...]
    metrics: Mapping[str, Any]
    measurement_start: str
    measurement_end: str
    as_of: str

    def __post_init__(self) -> None:
        # P0-O1-R3：深度冻结嵌套结构（metrics），构造后不可变
        object.__setattr__(self, "metrics", _deep_freeze(self.metrics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "authority_version": self.authority_version,
            "computation_fingerprint": self.computation_fingerprint,
            "security_code": self.security_code,
            "input_trade_ids": list(self.input_trade_ids),
            "metrics": _deep_unfreeze(self.metrics),
            "measurement_start": self.measurement_start,
            "measurement_end": self.measurement_end,
            "as_of": self.as_of,
        }


def build_performance_evidence(
    pa1_result: Any,
    *,
    security_code: str,
    measurement_start: str,
    measurement_end: str,
    as_of: str,
) -> PerformanceEvidence:
    """从 PA1 结果构造绩效证据（P0-O1-R2：精确 position 绑定，无外部注入）。

    - ``pa1_result`` 必须是**原始** PA1 计算结果（内部先做完整权威校验）
    - ``security_code``：builder 自己从已验证 PA1 结果中定位精确 position，
      要求**恰好一个**匹配（同 code 伪造 position 无法注入）
    - ``input_trade_ids`` 直接取自 PA1 position 的计算顺序（绝不排序）
    - 时间窗口为显式输入（解析并规范化为 canonical UTC）
    """
    validated = validate_pa1_result(pa1_result)
    if not isinstance(security_code, str) or not _SECURITY_CODE_RE.fullmatch(
        security_code
    ):
        raise OutcomeValidationError("security_code：必须是 6 位数字")
    matches = [p for p in validated["positions"] if p["code"] == security_code]
    if not matches:
        raise OutcomeValidationError(
            f"PA1 结果不含证券 {security_code} 的 position"
        )
    if len(matches) > 1:
        raise OutcomeValidationError(
            f"PA1 结果含多个证券 {security_code} 的 position（异常结果）"
        )
    position = matches[0]
    input_trade_ids = tuple(position["input_trade_ids"])  # 计算顺序，精确保留
    if not input_trade_ids:
        raise OutcomeValidationError(
            "position：input_trade_ids 为空（绩效证据必须绑定非空交易集）"
        )

    return PerformanceEvidence(
        evidence_id=_derive_performance_evidence_id(
            validated["computation_fingerprint"], security_code
        ),
        authority_version=validated["authority_version"],
        computation_fingerprint=validated["computation_fingerprint"],
        security_code=security_code,
        input_trade_ids=input_trade_ids,
        metrics=position,
        measurement_start=to_canonical_utc(measurement_start, "measurement_start"),
        measurement_end=to_canonical_utc(measurement_end, "measurement_end"),
        as_of=to_canonical_utc(as_of, "as_of"),
    )


def performance_evidence_to_dict(evidence: PerformanceEvidence) -> dict[str, Any]:
    """严格规范表示（确定性字段序）。"""
    return evidence.to_dict()


_PERF_RECORD_FIELDS = frozenset(
    {
        "evidence_id",
        "authority_version",
        "computation_fingerprint",
        "security_code",
        "input_trade_ids",
        "metrics",
        "measurement_start",
        "measurement_end",
        "as_of",
    }
)


def performance_evidence_from_dict(
    record: Mapping[str, Any],
    pa1_result: Any,
) -> PerformanceEvidence:
    """反序列化绩效证据（P0-O1-R2）：必须提供 PA1 结果作为权威。

    - record 本身**绝不能**确立 PA1 权威（禁自报 fingerprint / input_trade_ids /
      metrics）
    - 流程：从 record 提取 security_code 与窗口 → 用 PA1 权威派生期望证据 →
      精确比较（含 input_trade_ids 计算顺序）→ 返回期望
    - 任何不一致 → OutcomeValidationError（含顺序错位）
    """
    if not isinstance(record, Mapping):
        raise OutcomeValidationError("record：必须是 Mapping")
    keys = set(record)
    if keys != _PERF_RECORD_FIELDS:
        raise OutcomeValidationError(
            f"record：字段集必须精确为 {sorted(_PERF_RECORD_FIELDS)}"
        )
    security_code = record["security_code"]
    if not isinstance(security_code, str) or not _SECURITY_CODE_RE.fullmatch(
        security_code
    ):
        raise OutcomeValidationError("record：security_code 不合法")
    for ts_field in ("measurement_start", "measurement_end", "as_of"):
        if not isinstance(record[ts_field], str) or not record[ts_field].strip():
            raise OutcomeValidationError(f"record：{ts_field} 必填")

    # 权威派生期望证据（record 的全部权威字段均来自 PA1，窗口来自 record）
    expected = build_performance_evidence(
        pa1_result,
        security_code=security_code,
        measurement_start=record["measurement_start"],
        measurement_end=record["measurement_end"],
        as_of=record["as_of"],
    )
    if dict(record) != expected.to_dict():
        raise OutcomeValidationError(
            "record：与 PA1 权威派生证据不一致（自报 fingerprint / trade_ids / "
            "metrics 被拒绝，含顺序错位）"
        )
    return expected


# ---------------------------------------------------------------------------
# 反馈证据（独立维度：绝不驱动 performance_evidence_state）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackEvidence:
    """决策反馈证据（独立维度；复用既有 decision_feedback 契约的 metrics）。

    仅作为额外观察维度被保留；不参与绩效证据可用性判定。
    """

    evidence_id: str
    security_code: str
    metrics: Mapping[str, Any]
    as_of: str

    def __post_init__(self) -> None:
        # P0-O1-R3：深度冻结嵌套结构（metrics），构造后不可变
        object.__setattr__(self, "metrics", _deep_freeze(self.metrics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "security_code": self.security_code,
            "metrics": _deep_unfreeze(self.metrics),
            "as_of": self.as_of,
        }


_FEEDBACK_FIELDS = frozenset(
    {"evidence_id", "security_code", "metrics", "as_of"}
)
_FEEDBACK_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def validate_feedback_evidence(evidence: Any) -> FeedbackEvidence:
    """严格验证反馈证据形状（独立维度，不影响绩效状态）。"""
    if isinstance(evidence, FeedbackEvidence):
        evidence = evidence.to_dict()
    if not isinstance(evidence, Mapping):
        raise OutcomeValidationError("feedback：必须是 FeedbackEvidence 或 Mapping")
    keys = set(evidence)
    if keys != _FEEDBACK_FIELDS:
        raise OutcomeValidationError(
            f"feedback：字段集必须精确为 {sorted(_FEEDBACK_FIELDS)}"
        )
    evidence_id = evidence["evidence_id"]
    if not isinstance(evidence_id, str) or not _FEEDBACK_ID_RE.fullmatch(evidence_id):
        raise OutcomeValidationError("feedback：evidence_id 必须是 32 位小写 hex")
    security_code = evidence["security_code"]
    if not isinstance(security_code, str) or not _SECURITY_CODE_RE.fullmatch(
        security_code
    ):
        raise OutcomeValidationError("feedback：security_code 不合法")
    metrics = evidence["metrics"]
    if not isinstance(metrics, Mapping):
        raise OutcomeValidationError("feedback：metrics 必须是对象")
    try:
        canonical_json(metrics)
    except (ValueError, TypeError):
        raise OutcomeValidationError(
            "feedback：metrics 含非法 JSON 值（NaN / Infinity）"
        ) from None
    try:
        as_of = to_canonical_utc(evidence["as_of"], "feedback.as_of")
    except AttributionValidationError:
        raise OutcomeValidationError(
            "feedback：as_of 不是合法 UTC 时间戳"
        ) from None
    return FeedbackEvidence(
        evidence_id=evidence_id,
        security_code=security_code,
        metrics=metrics,
        as_of=as_of,
    )


# ---------------------------------------------------------------------------
# 结果来源投影
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FormalDecisionOutcome:
    """不可变结果来源投影记录（派生记录，不持久化、不哈希）。

    维度保持分离：决策身份 / 执行现实 / 行为偏差 / 绩效证据可用性 /
    绩效证据 / 反馈证据 / 测量窗口。不做任何投资质量评分。
    """

    schema_version: str = SCHEMA_VERSION
    decision_id: str = ""
    decision_snapshot_hash: str = ""
    security_code: str = ""
    strategy: str = ""
    campaign_id: str = ""
    thesis_id: str = ""
    thesis_revision: int = 0
    decision_committed_at: str = ""
    decision_review_by: str = ""
    decision_next_best_action: str = ""
    attribution_ids: tuple[str, ...] = ()
    trade_ids: tuple[str, ...] = ()
    execution_summary: Mapping[str, Any] = field(default_factory=dict)
    behavior_deviations: tuple[Mapping[str, str], ...] = ()
    performance_evidence_state: str = PERFORMANCE_EVIDENCE_STATES[1]
    performance_evidences: tuple[Mapping[str, Any], ...] = ()
    feedback_evidence_state: str = FEEDBACK_EVIDENCE_STATES[1]
    feedback_evidences: tuple[Mapping[str, Any], ...] = ()
    measurement: Mapping[str, str] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # P0-O1-R3：深度冻结全部嵌套容器，投影一旦验证完成即不可变
        for field_name in (
            "execution_summary",
            "behavior_deviations",
            "performance_evidences",
            "feedback_evidences",
            "measurement",
        ):
            object.__setattr__(self, field_name, _deep_freeze(getattr(self, field_name)))

    def to_dict(self) -> dict[str, Any]:
        # P0-O1-R3：递归解冻为全新普通 JSON 兼容结构（detached copy）
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "decision_snapshot_hash": self.decision_snapshot_hash,
            "security_code": self.security_code,
            "strategy": self.strategy,
            "campaign_id": self.campaign_id,
            "thesis_id": self.thesis_id,
            "thesis_revision": self.thesis_revision,
            "decision_committed_at": self.decision_committed_at,
            "decision_review_by": self.decision_review_by,
            "decision_next_best_action": self.decision_next_best_action,
            "attribution_ids": list(self.attribution_ids),
            "trade_ids": list(self.trade_ids),
            "execution_summary": _deep_unfreeze(self.execution_summary),
            "behavior_deviations": _deep_unfreeze(self.behavior_deviations),
            "performance_evidence_state": self.performance_evidence_state,
            "performance_evidences": _deep_unfreeze(self.performance_evidences),
            "feedback_evidence_state": self.feedback_evidence_state,
            "feedback_evidences": _deep_unfreeze(self.feedback_evidences),
            "measurement": _deep_unfreeze(self.measurement),
            "reason_codes": list(self.reason_codes),
        }


def project_outcome(
    decision: Mapping[str, Any],
    attributions: Iterable[Any],
    pa1_results: Iterable[Any],
    feedback_evidences: Iterable[Any] = (),
    *,
    measurement_start: str,
    measurement_end: str,
    as_of: str,
) -> FormalDecisionOutcome:
    """投影：精确决策 → 归属交易 → 已算结果证据的来源记录（P0-O1-R1）。

    验证链（任一失败 fail closed）：
    1. 决策见证独立验证（TB1 权威，防伪造）
    2. 归属集合严格验证（TB1 权威）
    3. 每个 PA1 结果通过权威校验（authority_version 精确、内部一致）
    4. 绩效证据派生并绑定：
       - PA1 position.security_code == decision.security_code
       - position.input_trade_ids ⊆ 当前决策归属交易集
       - 混合（含归属外交易）→ REJECT（原 O1 blocker 反例）
       - 证据时间窗合法、不早于决策提交
    5. 反馈证据独立维度验证（不影响绩效状态）
    6. 全局测量窗口：start ≤ end、start ≥ 决策提交、as_of ≥ start

    所有时间戳解析为 UTC instant 后比较；输出确定性。
    """
    anchor = verify_frozen_decision_witness(decision)
    validated = validate_attribution_set(attributions)

    decision_attributions = [
        a for a in validated if a["decision_id"] == anchor["decision_id"]
    ]
    for attribution in decision_attributions:
        for field_name in DECISION_ANCHOR_FIELDS:
            if attribution[field_name] != anchor[field_name]:
                raise OutcomeValidationError(
                    f"归属记录决策锚不一致：{field_name}"
                )

    decision_trade_ids = [a["trade_id"] for a in decision_attributions]
    decision_trade_set = set(decision_trade_ids)
    attribution_ids = tuple(a["attribution_id"] for a in decision_attributions)

    # 全局测量窗口（显式输入；UTC instant 比较）
    start_dt = parse_utc_instant(measurement_start, "measurement_start")
    end_dt = parse_utc_instant(measurement_end, "measurement_end")
    as_of_dt = parse_utc_instant(as_of, "as_of")
    committed_dt = parse_utc_instant(anchor["decision_committed_at"], "decision_committed_at")
    if end_dt < start_dt:
        raise OutcomeValidationError("测量窗口反转：measurement_end 早于 measurement_start")
    if start_dt < committed_dt:
        raise OutcomeValidationError("测量不得先于决策提交（拒绝回填结果证据）")
    if as_of_dt < start_dt:
        raise OutcomeValidationError("as_of 不得早于测量窗口起点")

    # 绩效证据：从 PA1 结果派生（无调用方自报绑定；position 由 builder 精确定位）
    perf_by_id: dict[str, dict[str, Any]] = {}
    for pa1_raw in pa1_results:
        validated_pa1 = validate_pa1_result(pa1_raw)
        if not any(
            p["code"] == anchor["security_code"] for p in validated_pa1["positions"]
        ):
            continue  # 其他证券的 PA1 结果不参与本决策投影（不拒绝，仅忽略）
        evidence = build_performance_evidence(
            pa1_raw,
            security_code=anchor["security_code"],
            measurement_start=measurement_start,
            measurement_end=measurement_end,
            as_of=as_of,
        )
        # 绑定：position 输入集必须 ⊆ 本决策归属交易集（混合 → 拒绝）
        extra = set(evidence.input_trade_ids) - decision_trade_set
        if extra:
            raise OutcomeValidationError(
                "绩效证据被拒绝：PA1 position 包含本决策归属之外的交易"
                f"（混合证据不得拆分或部分采用）：{sorted(extra)}"
            )
        if parse_utc_instant(
            evidence.measurement_start, "evidence.measurement_start"
        ) < committed_dt:
            raise OutcomeValidationError("绩效证据测量不得先于决策提交")
        d = performance_evidence_to_dict(evidence)
        if evidence.evidence_id in perf_by_id:
            if perf_by_id[evidence.evidence_id] != d:
                raise OutcomeEvidenceConflictError(
                    f"绩效证据 {evidence.evidence_id} 内容冲突（不做 latest-wins）"
                )
            continue  # 精确重复：幂等
        perf_by_id[evidence.evidence_id] = d

    # 反馈证据：独立维度（不驱动绩效状态）
    feedback_by_id: dict[str, dict[str, Any]] = {}
    for raw in feedback_evidences:
        feedback = validate_feedback_evidence(raw)
        if feedback.security_code != anchor["security_code"]:
            raise OutcomeValidationError(
                "跨证券反馈证据拒绝：feedback.security_code 与决策不一致"
            )
        if parse_utc_instant(feedback.as_of, "feedback.as_of") < committed_dt:
            raise OutcomeValidationError("反馈证据不得早于决策提交")
        d = feedback.to_dict()
        if feedback.evidence_id in feedback_by_id:
            if feedback_by_id[feedback.evidence_id] != d:
                raise OutcomeEvidenceConflictError(
                    f"反馈证据 {feedback.evidence_id} 内容冲突（不做 latest-wins）"
                )
            continue
        feedback_by_id[feedback.evidence_id] = d

    # 执行现实（规范 15/16）：逐交易保留，不合成
    executed_trade_ids: list[str] = []
    not_executed_trade_ids: list[str] = []
    deviations: list[dict[str, str]] = []
    for attribution in decision_attributions:
        status = attribution["trade_execution_status"]
        if status == "not_executed":
            not_executed_trade_ids.append(attribution["trade_id"])
        else:
            executed_trade_ids.append(attribution["trade_id"])
        deviations.append(
            {
                "trade_id": attribution["trade_id"],
                "decision_next_best_action": attribution["decision_next_best_action"],
                "trade_operation": attribution["trade_operation"],
            }
        )
    has_executed = bool(executed_trade_ids)
    execution_state = (
        EXECUTION_SUMMARY_STATES[0] if has_executed else EXECUTION_SUMMARY_STATES[1]
    )
    execution_summary = {
        "state": execution_state,
        "executed_trade_ids": executed_trade_ids,
        "not_executed_trade_ids": not_executed_trade_ids,
    }

    perf_list = sorted(perf_by_id.values(), key=lambda e: e["evidence_id"])
    feedback_list = sorted(feedback_by_id.values(), key=lambda e: e["evidence_id"])
    performance_state = (
        PERFORMANCE_EVIDENCE_STATES[0]
        if perf_list
        else PERFORMANCE_EVIDENCE_STATES[1]
    )
    feedback_state = (
        FEEDBACK_EVIDENCE_STATES[0] if feedback_list else FEEDBACK_EVIDENCE_STATES[1]
    )
    reason_codes: list[str] = []
    if not perf_list:
        reason_codes.append(REASON_NO_PERFORMANCE_EVIDENCE)
    if not has_executed:
        reason_codes.append(REASON_NO_EXECUTED_TRADE)

    return FormalDecisionOutcome(
        decision_id=anchor["decision_id"],
        decision_snapshot_hash=anchor["decision_snapshot_hash"],
        security_code=anchor["security_code"],
        strategy=anchor["strategy"],
        campaign_id=anchor["campaign_id"],
        thesis_id=anchor["thesis_id"],
        thesis_revision=anchor["thesis_revision"],
        decision_committed_at=anchor["decision_committed_at"],
        decision_review_by=anchor["decision_review_by"],
        decision_next_best_action=anchor["decision_next_best_action"],
        attribution_ids=attribution_ids,
        trade_ids=tuple(decision_trade_ids),
        execution_summary=execution_summary,
        behavior_deviations=tuple(deviations),
        performance_evidence_state=performance_state,
        performance_evidences=tuple(perf_list),
        feedback_evidence_state=feedback_state,
        feedback_evidences=tuple(feedback_list),
        measurement={
            "measurement_start": to_canonical_utc(measurement_start, "measurement_start"),
            "measurement_end": to_canonical_utc(measurement_end, "measurement_end"),
            "as_of": to_canonical_utc(as_of, "as_of"),
        },
        reason_codes=tuple(reason_codes),
    )


# ---------------------------------------------------------------------------
# P0-OL1 Formal Outcome vertical
# ---------------------------------------------------------------------------

OL1_SCHEMA_VERSION = "formal_decision_outcome.ol1.v0.1"
OL1_OUTCOME_STATES = (
    "PENDING",
    "EVALUATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)
ACTUAL_CAPITAL_OUTCOME_STATES = (
    "PENDING",
    "NO_ACTUAL_TRADE",
    "EVALUATED",
    "ERROR",
)
COUNTERFACTUAL_OUTCOME_STATES = (
    "PENDING",
    "EVALUATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)
PROCESS_QUALITY_STATE = "NOT_EVALUATED"


def _ol1_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def build_decision_time_replay(decision: Mapping[str, Any]) -> dict[str, Any]:
    """Build an immutable replay envelope from the Frozen Decision only.

    No evaluation time, Trade Ledger row, attribution, price, outcome, or
    current Thesis/Evidence state is admitted into this pass.
    """
    anchor = verify_frozen_decision_witness(decision)
    snapshot = {
        key: _deep_unfreeze(decision[key])
        for key in sorted(SNAPSHOT_KEYS)
    }
    envelope: dict[str, Any] = {
        "schema_version": OL1_SCHEMA_VERSION,
        "replay_schema_version": "formal_decision_time_replay.v0.1",
        "decision_id": anchor["decision_id"],
        "decision_snapshot_hash": anchor["decision_snapshot_hash"],
        "snapshot": snapshot,
    }
    return {
        **envelope,
        "replay_hash": _ol1_hash(envelope),
    }


def _ol1_actual_outcome(
    *,
    executed_trade_ids: list[str],
    actual_performance: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not executed_trade_ids:
        if actual_performance is not None:
            raise OutcomeValidationError(
                "无实际执行交易时不得提供绩效计算结果"
            )
        return {
            "state": "NO_ACTUAL_TRADE",
            "pnl_state": "NOT_APPLICABLE",
            "trade_count": 0,
            "trade_ids": [],
            "pnl": None,
            "authority_refs": ["tar1:formal_trade_attribution:none"],
            "reason_codes": ["NO_ACTUAL_TRADE"],
        }

    if actual_performance is None:
        return {
            "state": "EVALUATED",
            "pnl_state": "NOT_EVALUATED",
            "trade_count": len(executed_trade_ids),
            "trade_ids": list(executed_trade_ids),
            "pnl": None,
            "authority_refs": ["tar1:formal_trade_attribution", "trade_ledger"],
            "reason_codes": ["CANONICAL_PNL_NOT_AVAILABLE"],
        }

    selected_ids = actual_performance.get("selected_trade_ids")
    if not isinstance(selected_ids, list) or set(selected_ids) != set(executed_trade_ids):
        raise OutcomeValidationError(
            "PA1 结果的 selected_trade_ids 必须精确等于 Formal Attribution 执行交易集"
        )
    positions = actual_performance.get("positions")
    if not isinstance(positions, list):
        raise OutcomeValidationError("PA1 结果 positions 不合法")
    position = next(
        (item for item in positions if isinstance(item, Mapping)),
        None,
    )
    if position is None:
        raise OutcomeValidationError("PA1 结果缺少实际交易 position")
    measured = (
        position.get("closed_quantity", 0) > 0
        or position.get("unrealized_pnl") is not None
    )
    return {
        "state": "EVALUATED",
        "pnl_state": "MEASURED" if measured else "NOT_EVALUATED",
        "trade_count": len(executed_trade_ids),
        "trade_ids": list(executed_trade_ids),
        "pnl": {
            "realized_pnl": position.get("realized_pnl"),
            "unrealized_pnl": position.get("unrealized_pnl"),
            "cost_basis": position.get("cost_basis"),
            "total_fees": position.get("total_fees"),
            "computation_fingerprint": actual_performance.get(
                "computation_fingerprint"
            ),
        },
        "authority_refs": [
            "tar1:formal_trade_attribution",
            "trade_ledger",
            str(actual_performance.get("authority_version")),
        ],
        "reason_codes": [] if measured else ["CANONICAL_PNL_INCOMPLETE"],
    }


def project_ol1_outcome(
    decision: Mapping[str, Any],
    *,
    evaluation_as_of: str,
    attributions: Iterable[Any],
    trades: Iterable[Mapping[str, Any]],
    actual_performance: Mapping[str, Any] | None = None,
    counterfactual: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project OL1 from immutable authorities and an explicit evaluation time.

    This is deterministic and has no I/O or hidden wall-clock reads.  Runtime
    owns loading authorities; this function owns the two-pass contract.
    """
    anchor = verify_frozen_decision_witness(decision)
    replay = build_decision_time_replay(decision)
    evaluation = to_canonical_utc(evaluation_as_of, "evaluation_as_of")
    evaluation_dt = parse_utc_instant(evaluation, "evaluation_as_of")
    committed_dt = parse_utc_instant(
        anchor["decision_committed_at"], "decision.committed_at"
    )
    review_dt = parse_utc_instant(anchor["decision_review_by"], "decision.review_by")
    if evaluation_dt < committed_dt:
        raise OutcomeValidationError(
            "evaluation_as_of 不得早于 Frozen Decision committed_at"
        )

    identity = {
        "schema_version": OL1_SCHEMA_VERSION,
        **anchor,
        "evaluation_as_of": evaluation,
        "decision_time_replay": replay,
        "replay_future_fact_leak": False,
        "process_quality": {
            "state": PROCESS_QUALITY_STATE,
            "reason_codes": ["NO_PROCESS_QUALITY_AUTHORITY"],
        },
    }

    if evaluation_dt < review_dt:
        return {
            **identity,
            "outcome_status": "PENDING",
            "due_state": "NOT_DUE",
            "outcome_reveal": None,
            "actual_capital_outcome": {
                "state": "PENDING",
                "pnl_state": "NOT_APPLICABLE",
                "trade_count": 0,
                "trade_ids": [],
                "pnl": None,
                "authority_refs": ["frozen_decision:review_by"],
                "reason_codes": ["REVIEW_NOT_DUE"],
            },
            "counterfactual_outcome": {
                "state": "PENDING",
                "authority_refs": ["frozen_decision:review_by"],
                "reason_codes": ["REVIEW_NOT_DUE"],
            },
            "reason_codes": ["REVIEW_NOT_DUE"],
        }

    validated_attributions = validate_attribution_set(attributions)
    if any(item["decision_id"] != anchor["decision_id"] for item in validated_attributions):
        raise OutcomeValidationError("Outcome 输入含其他 Frozen Decision 的归属记录")
    for item in validated_attributions:
        for field_name in DECISION_ANCHOR_FIELDS:
            if item[field_name] != anchor[field_name]:
                raise OutcomeValidationError(
                    f"Formal Attribution 决策锚不一致：{field_name}"
                )
    trade_by_id = {}
    for trade in trades:
        if not isinstance(trade, Mapping):
            raise OutcomeValidationError("Trade Ledger row 必须是 Mapping")
        trade_id = trade.get("trade_id")
        if not isinstance(trade_id, str) or trade_id in trade_by_id:
            raise OutcomeValidationError("Trade Ledger row trade_id 不合法或重复")
        trade_by_id[trade_id] = dict(trade)

    expected_ids = {item["trade_id"] for item in validated_attributions}
    if set(trade_by_id) != expected_ids:
        raise OutcomeValidationError(
            "Trade Ledger 输入集必须精确覆盖 Formal Attribution 输入集"
        )

    executed_ids: list[str] = []
    included_attributions: list[str] = []
    for attribution in validated_attributions:
        trade = trade_by_id[attribution["trade_id"]]
        if trade.get("voided_at") is not None:
            continue
        if attribution["trade_execution_status"] in ("full", "partial"):
            executed_ids.append(attribution["trade_id"])
        included_attributions.append(attribution["attribution_id"])

    actual = _ol1_actual_outcome(
        executed_trade_ids=executed_ids,
        actual_performance=actual_performance,
    )
    cf = dict(counterfactual or {
        "state": "NOT_EVALUATED",
        "authority_refs": ["ol1:no-authoritative-future-price-path"],
        "reason_codes": ["NO_AUTHORITATIVE_FUTURE_PRICE"],
    })
    if cf.get("state") not in COUNTERFACTUAL_OUTCOME_STATES:
        raise OutcomeValidationError("counterfactual state 不合法")
    if "pnl" in cf:
        raise OutcomeValidationError(
            "OL1 counterfactual 不接受未由正式价格路径证明的 P&L"
        )

    reveal_base = {
        "schema_version": "formal_outcome_reveal.v0.1",
        "decision_id": anchor["decision_id"],
        "decision_time_replay_hash": replay["replay_hash"],
        "evaluation_as_of": evaluation,
        "attribution_ids": included_attributions,
        "actual_capital_outcome": actual,
        "counterfactual_outcome": cf,
    }
    reveal = {**reveal_base, "outcome_reveal_hash": _ol1_hash(reveal_base)}
    reason_codes = list(actual["reason_codes"]) + list(cf.get("reason_codes", []))
    return {
        **identity,
        "outcome_status": "EVALUATED",
        "due_state": "DUE",
        "outcome_reveal": reveal,
        "actual_capital_outcome": actual,
        "counterfactual_outcome": cf,
        "reason_codes": list(dict.fromkeys(reason_codes)),
    }
