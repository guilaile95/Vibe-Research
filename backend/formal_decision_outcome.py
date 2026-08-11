"""正式决策结果来源投影核心（P0-O1，纯逻辑，零 I/O）。

回答一个问题（provenance first，非评分）：

    "对于这个确切的正式冻结决策，哪些实际手动交易被正式归属给它，
     以及哪些**已经算好的**结果证据属于这些交易 / 这个决策？"

职责边界：

- 不决定投资者是否"正确"；不做投资质量判断
- 不重算 PnL / 收益 / 基准：已有性能系统（performance_attribution）的
  输出作为**调用方显式提供的证据**被绑定与引用，本模块不做第二套计算
- 不推断 Thesis 状态、不推断决策有效性（review_by 仅作证据保留）、
  不发明 TTL
- 不修改任何既有子系统（Trade Ledger / Frozen Decision / TB1 /
  Performance Attribution / Decision Feedback）

归属权威复用 TB1：``validate_attribution_set``。无效归属集合 fail closed。

纯函数：无 SQLite / 文件系统 / 网络 / 环境 / 时钟读 / 行情 / AI / HTTP。
所有时间戳与参考时间均为显式输入。同输入 → 同投影（无 UUID / now / random）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from frozen_decision_store import NEXT_BEST_ACTIONS, STRATEGIES, canonical_json
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

# 执行现实状态（规范 15）：全 not_executed → NO_EXECUTED_TRADE（非 0% 收益）
EXECUTION_SUMMARY_STATES = ("EXECUTED_TRADE", "NO_EXECUTED_TRADE")
# 绩效证据可用性（规范 11）：缺失 → NOT_MEASURED，绝不视为 0 收益
PERFORMANCE_EVIDENCE_STATES = ("MEASURED", "NOT_MEASURED")
# 提示性原因码（中性，不构成评分）
REASON_NO_PERFORMANCE_EVIDENCE = "NO_PERFORMANCE_EVIDENCE"
REASON_NO_EXECUTED_TRADE = "NO_EXECUTED_TRADE"
REASON_CODES = (REASON_NO_PERFORMANCE_EVIDENCE, REASON_NO_EXECUTED_TRADE)

_EVIDENCE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_TRADE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SECURITY_CODE_RE = re.compile(r"^\d{6}$")


class FormalDecisionOutcomeError(RuntimeError):
    """正式决策结果来源投影基础异常。"""


class OutcomeValidationError(FormalDecisionOutcomeError, AttributionValidationError):
    """输入验证失败（fail closed）：决策/归属/证据/时间窗任一不合法。"""


class OutcomeEvidenceConflictError(FormalDecisionOutcomeError):
    """证据集合冲突：同 evidence_id 内容不一致（不做 latest-wins）。"""


# ---------------------------------------------------------------------------
# 证据契约：既有性能系统的输出作为受绑定证据
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PerformanceEvidence:
    """已计算结果的绑定证据（由调用方/既有性能系统显式提供）。

    - ``evidence_id``：32 位小写 hex，证据身份（集合冲突判定依据）
    - ``security_code``：证据覆盖的证券（必须与决策精确一致）
    - ``trade_ids``：证据覆盖的精确交易集（必须 ⊆ 该决策的归属交易集）
    - ``measurement_start`` / ``measurement_end``：测量窗口（显式 UTC）
    - ``as_of``：数据截至时刻（显式 UTC）
    - ``metrics``：既有性能系统输出 payload（只引用，不重算；canonical 可序列化）
    - ``source``：既有权威系统标识（如 "performance_attribution.v2"）
    """

    evidence_id: str
    security_code: str
    trade_ids: tuple[str, ...]
    measurement_start: str
    measurement_end: str
    as_of: str
    metrics: Mapping[str, Any]
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "security_code": self.security_code,
            "trade_ids": list(self.trade_ids),
            "measurement_start": self.measurement_start,
            "measurement_end": self.measurement_end,
            "as_of": self.as_of,
            "metrics": self.metrics,
            "source": self.source,
        }


_EVIDENCE_FIELDS = frozenset(
    {
        "evidence_id",
        "security_code",
        "trade_ids",
        "measurement_start",
        "measurement_end",
        "as_of",
        "metrics",
        "source",
    }
)


def validate_evidence(evidence: Any) -> PerformanceEvidence:
    """严格验证证据形状与绑定能力；任何不符 fail closed。

    实例与 Mapping 统一走同一严格校验路径（不信任 dataclass 类型本身）：
    - trade_ids 必须非空（半绑定证据拒绝）
    - 时间戳必须为可解析 UTC 并规范化为 canonical 形式
    - metrics 必须 canonical 可序列化（拒绝 NaN / Infinity）

    本函数只做形状/身份校验；与具体决策/归属集的绑定在投影内完成。
    """
    if isinstance(evidence, PerformanceEvidence):
        evidence = evidence.to_dict()
    if not isinstance(evidence, Mapping):
        raise OutcomeValidationError("evidence：必须是 PerformanceEvidence 或 Mapping")
    keys = set(evidence)
    if keys != _EVIDENCE_FIELDS:
        raise OutcomeValidationError(
            f"evidence：字段集必须精确为 {sorted(_EVIDENCE_FIELDS)}"
        )
    evidence_id = evidence["evidence_id"]
    if not isinstance(evidence_id, str) or not _EVIDENCE_ID_RE.fullmatch(evidence_id):
        raise OutcomeValidationError("evidence：evidence_id 必须是 32 位小写 hex")
    security_code = evidence["security_code"]
    if not isinstance(security_code, str) or not _SECURITY_CODE_RE.fullmatch(
        security_code
    ):
        raise OutcomeValidationError("evidence：security_code 必须是 6 位数字")
    trade_ids_raw = evidence["trade_ids"]
    if not isinstance(trade_ids_raw, (list, tuple)) or not trade_ids_raw:
        raise OutcomeValidationError(
            "evidence：trade_ids 必须是非空交易集（半绑定证据拒绝）"
        )
    trade_ids: set[str] = set()
    for tid in trade_ids_raw:
        if not isinstance(tid, str) or not _TRADE_ID_RE.fullmatch(tid):
            raise OutcomeValidationError("evidence：trade_ids 元素必须是 32 位小写 hex")
        trade_ids.add(tid)
    for ts_field in ("measurement_start", "measurement_end", "as_of"):
        value = evidence[ts_field]
        if not isinstance(value, str) or not value.strip():
            raise OutcomeValidationError(f"evidence：{ts_field} 必填")
        try:
            parse_utc_instant(value, f"evidence.{ts_field}")
        except AttributionValidationError:
            raise OutcomeValidationError(
                f"evidence：{ts_field} 不是合法 UTC 时间戳"
            ) from None
    metrics = evidence["metrics"]
    if not isinstance(metrics, Mapping):
        raise OutcomeValidationError("evidence：metrics 必须是 JSON 对象")
    try:
        canonical_json(metrics)
    except (ValueError, TypeError):
        raise OutcomeValidationError(
            "evidence：metrics 含非法 JSON 值（NaN / Infinity / 非 JSON 结构）"
        ) from None
    source = evidence["source"]
    if not isinstance(source, str) or not source.strip():
        raise OutcomeValidationError("evidence：source 必须是规范非空字符串")
    return PerformanceEvidence(
        evidence_id=evidence_id,
        security_code=security_code,
        trade_ids=tuple(sorted(trade_ids)),
        measurement_start=to_canonical_utc(
            evidence["measurement_start"], "evidence.measurement_start"
        ),
        measurement_end=to_canonical_utc(
            evidence["measurement_end"], "evidence.measurement_end"
        ),
        as_of=to_canonical_utc(evidence["as_of"], "evidence.as_of"),
        metrics=metrics,
        source=source,
    )


# ---------------------------------------------------------------------------
# 结果来源投影
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FormalDecisionOutcome:
    """不可变结果来源投影记录（派生记录，不持久化、不哈希）。

    维度保持分离（规范 12）：决策身份 / 执行现实 / 行为偏差 / 绩效证据
    可用性 / 绩效证据 / 测量窗口。不做任何投资质量评分。
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
    evidences: tuple[Mapping[str, Any], ...] = ()
    measurement: Mapping[str, str] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
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
            "execution_summary": dict(self.execution_summary),
            "behavior_deviations": [dict(d) for d in self.behavior_deviations],
            "performance_evidence_state": self.performance_evidence_state,
            "evidences": [dict(e) for e in self.evidences],
            "measurement": dict(self.measurement),
            "reason_codes": list(self.reason_codes),
        }


def project_outcome(
    decision: Mapping[str, Any],
    attributions: Iterable[Any],
    evidences: Iterable[Any],
    *,
    measurement_start: str,
    measurement_end: str,
    as_of: str,
) -> FormalDecisionOutcome:
    """投影：精确决策 → 归属交易 → 已算结果证据的来源记录。

    验证链（任一失败 fail closed）：
    1. 决策见证独立验证（TB1 权威，防伪造）
    2. 归属集合严格验证（TB1 权威，无效集合拒绝）
    3. 只纳入归属到本决策的交易；证据引用的交易必须 ∈ 本决策归属集
    4. 决策锚一致性：归属记录的 DECISION_ANCHOR_FIELDS 与决策见证完全一致
    5. 证据绑定：security 精确匹配；trade 集非空且 ⊆ 归属集；时间窗合法；
       测量不早于决策提交；同 evidence_id 冲突内容拒绝
    6. 全局测量窗口：start ≤ end、start ≥ 决策提交、as_of ≥ start

    所有时间戳解析为 UTC instant 后比较；输出确定性（归属/交易/证据
    均按固定顺序）。无 UUID / now / random。
    """
    anchor = verify_frozen_decision_witness(decision)
    validated = validate_attribution_set(attributions)

    # 本决策的归属（跨决策归属存在但被排除，不影响本决策投影）
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

    # 测量窗口（显式输入；UTC instant 比较）
    start_dt = parse_utc_instant(measurement_start, "measurement_start")
    end_dt = parse_utc_instant(measurement_end, "measurement_end")
    as_of_dt = parse_utc_instant(as_of, "as_of")
    committed_dt = parse_utc_instant(anchor["decision_committed_at"], "decision_committed_at")
    if end_dt < start_dt:
        raise OutcomeValidationError("测量窗口反转：measurement_end 早于 measurement_start")
    if start_dt < committed_dt:
        raise OutcomeValidationError(
            "测量不得先于决策提交（拒绝回填结果证据）"
        )
    if as_of_dt < start_dt:
        raise OutcomeValidationError("as_of 不得早于测量窗口起点")

    # 证据集合：严格验证 + 同 id 冲突拒绝 + 精确重复幂等
    evidence_dicts: dict[str, dict[str, Any]] = {}
    for raw in evidences:
        evidence = validate_evidence(raw)
        if evidence.security_code != anchor["security_code"]:
            raise OutcomeValidationError(
                "跨证券证据拒绝：evidence.security_code 与决策不一致"
            )
        extra = set(evidence.trade_ids) - decision_trade_set
        if extra:
            raise OutcomeValidationError(
                f"证据引用的交易不属于本决策归属集：{sorted(extra)}"
            )
        if evidence.measurement_start > evidence.measurement_end:
            raise OutcomeValidationError("证据测量窗口反转")
        if parse_utc_instant(evidence.measurement_start, "evidence.measurement_start") < committed_dt:
            raise OutcomeValidationError("证据测量不得先于决策提交")
        if parse_utc_instant(evidence.as_of, "evidence.as_of") < parse_utc_instant(
            evidence.measurement_start, "evidence.measurement_start"
        ):
            raise OutcomeValidationError("证据 as_of 不得早于其测量窗口起点")
        d = evidence.to_dict()
        if evidence.evidence_id in evidence_dicts:
            if evidence_dicts[evidence.evidence_id] != d:
                raise OutcomeEvidenceConflictError(
                    f"evidence_id {evidence.evidence_id} 内容冲突（不做 latest-wins）"
                )
            continue  # 精确重复：幂等
        evidence_dicts[evidence.evidence_id] = d

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
        # 归属 ≠ 合规：决策 NBA 与实际交易操作成对保留（中性事实，不判定）
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

    evidence_list = sorted(evidence_dicts.values(), key=lambda e: e["evidence_id"])
    has_evidence = bool(evidence_list)
    performance_state = (
        PERFORMANCE_EVIDENCE_STATES[0]
        if has_evidence
        else PERFORMANCE_EVIDENCE_STATES[1]
    )
    reason_codes: list[str] = []
    if not has_evidence:
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
        evidences=tuple(evidence_list),
        measurement={
            "measurement_start": to_canonical_utc(measurement_start, "measurement_start"),
            "measurement_end": to_canonical_utc(measurement_end, "measurement_end"),
            "as_of": to_canonical_utc(as_of, "as_of"),
        },
        reason_codes=tuple(reason_codes),
    )
