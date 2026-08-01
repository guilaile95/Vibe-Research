"""告警规则领域模型与纯函数求值器。

不访问网络、不访问磁盘、不读取环境变量、不调用时间函数。
同一规则与同一事实快照必须产生完全相同的结果。
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

ALERT_RULE_SCHEMA_VERSION = "alert-rule.v0.1"
ALERT_FACTS_SCHEMA_VERSION = "alert-facts.v0.1"
ALERT_EVALUATION_SCHEMA_VERSION = "alert-evaluation.v0.1"

AlertMetric = Literal[
    "close",
    "sma20",
    "sma60",
    "kdj_k",
    "kdj_d",
    "kdj_j",
]

ComparisonOperator = Literal[
    "gt",
    "gte",
    "lt",
    "lte",
]

TechnicalTrigger = Literal[
    "close_above_20d_high",
    "close_below_20d_low",
    "sma_golden_cross",
    "sma_death_cross",
]

TechnicalStatus = Literal[
    "normal",
    "partial",
    "unavailable",
]

DataHealthStatus = Literal[
    "normal",
    "partial",
    "unavailable",
]

EvaluationState = Literal[
    "matched",
    "not_matched",
    "not_evaluable",
    "disabled",
]

AlertReasonCode = Literal[
    "RULE_DISABLED",
    "SNAPSHOT_CODE_MISMATCH",
    "TECHNICAL_TRIGGER_PRESENT",
    "TECHNICAL_TRIGGER_ABSENT",
    "METRIC_UNAVAILABLE",
    "METRIC_THRESHOLD_MATCH",
    "METRIC_THRESHOLD_MISMATCH",
    "METRIC_COMPARISON_MATCH",
    "METRIC_COMPARISON_MISMATCH",
    "TECHNICAL_STATUS_MATCH",
    "TECHNICAL_STATUS_MISMATCH",
    "DATA_HEALTH_SOURCE_MISSING",
    "DATA_HEALTH_STATUS_MATCH",
    "DATA_HEALTH_STATUS_MISMATCH",
]

_RULE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CODE_RE = re.compile(r"^\d{6}$")
_SOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_PRICE_METRICS = frozenset({"close", "sma20", "sma60"})


def _strict_finite_number(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be a finite number")
    return number


def _validate_source_id(value: str) -> str:
    if not isinstance(value, str) or not _SOURCE_ID_RE.fullmatch(value):
        raise ValueError("source_id must match ^[a-z][a-z0-9_]{0,63}$")
    return value


def _validate_code(value: str) -> str:
    if not isinstance(value, str) or not _CODE_RE.fullmatch(value):
        raise ValueError("code must be exactly 6 digits")
    return value


def _validate_trade_date(value: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise ValueError("trade_date must be strict YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("trade_date must be a real calendar date") from exc
    return value


def _compare(left: float, operator: ComparisonOperator, right: float) -> bool:
    if operator == "gt":
        return left > right
    if operator == "gte":
        return left >= right
    if operator == "lt":
        return left < right
    return left <= right


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )


class TechnicalTriggerCondition(_StrictModel):
    kind: Literal["technical_trigger"]
    trigger: TechnicalTrigger


class MetricThresholdCondition(_StrictModel):
    kind: Literal["metric_threshold"]
    metric: AlertMetric
    operator: ComparisonOperator
    threshold: StrictFloat | StrictInt

    @field_validator("threshold")
    @classmethod
    def _threshold_finite(cls, value: Any) -> float:
        return _strict_finite_number(value, field_name="threshold")


class MetricComparisonCondition(_StrictModel):
    kind: Literal["metric_comparison"]
    left: AlertMetric
    operator: ComparisonOperator
    right: AlertMetric

    @model_validator(mode="after")
    def _left_not_right(self) -> "MetricComparisonCondition":
        if self.left == self.right:
            raise ValueError("left and right metrics must differ")
        return self


class TechnicalStatusCondition(_StrictModel):
    kind: Literal["technical_status"]
    status: Literal["partial", "unavailable"]


class DataHealthStatusCondition(_StrictModel):
    kind: Literal["data_health_status"]
    source_id: StrictStr
    status: Literal["partial", "unavailable"]

    @field_validator("source_id")
    @classmethod
    def _check_source_id(cls, value: str) -> str:
        return _validate_source_id(value)


AlertCondition = Annotated[
    Union[
        TechnicalTriggerCondition,
        MetricThresholdCondition,
        MetricComparisonCondition,
        TechnicalStatusCondition,
        DataHealthStatusCondition,
    ],
    Field(discriminator="kind"),
]


class AlertRule(_StrictModel):
    schema_version: Literal["alert-rule.v0.1"] = ALERT_RULE_SCHEMA_VERSION
    rule_id: StrictStr
    code: StrictStr
    enabled: StrictBool = True
    condition: AlertCondition

    @field_validator("rule_id")
    @classmethod
    def _check_rule_id(cls, value: str) -> str:
        if not isinstance(value, str) or not _RULE_ID_RE.fullmatch(value):
            raise ValueError("rule_id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
        return value

    @field_validator("code")
    @classmethod
    def _check_code(cls, value: str) -> str:
        return _validate_code(value)


class AlertMetricSnapshot(_StrictModel):
    close: StrictFloat | StrictInt | None
    sma20: StrictFloat | StrictInt | None
    sma60: StrictFloat | StrictInt | None
    kdj_k: StrictFloat | StrictInt | None
    kdj_d: StrictFloat | StrictInt | None
    kdj_j: StrictFloat | StrictInt | None

    @field_validator("close", "sma20", "sma60", "kdj_k", "kdj_d", "kdj_j", mode="before")
    @classmethod
    def _check_metric_values(cls, value: Any, info) -> float | None:
        if value is None:
            return None
        number = _strict_finite_number(value, field_name=info.field_name)
        if info.field_name in _PRICE_METRICS and number <= 0:
            raise ValueError(f"{info.field_name} must be > 0 when present")
        return number


class DataHealthFact(_StrictModel):
    source_id: StrictStr
    status: DataHealthStatus

    @field_validator("source_id")
    @classmethod
    def _check_source_id(cls, value: str) -> str:
        return _validate_source_id(value)


class AlertFactSnapshot(_StrictModel):
    schema_version: Literal["alert-facts.v0.1"] = ALERT_FACTS_SCHEMA_VERSION
    code: StrictStr
    trade_date: StrictStr
    technical_status: TechnicalStatus
    metrics: AlertMetricSnapshot
    triggers: tuple[TechnicalTrigger, ...] = ()
    data_health: tuple[DataHealthFact, ...] = ()

    @field_validator("code")
    @classmethod
    def _check_code(cls, value: str) -> str:
        return _validate_code(value)

    @field_validator("trade_date")
    @classmethod
    def _check_trade_date(cls, value: str) -> str:
        return _validate_trade_date(value)

    @field_validator("triggers")
    @classmethod
    def _check_triggers(cls, value: tuple[TechnicalTrigger, ...]) -> tuple[TechnicalTrigger, ...]:
        if len(value) != len(set(value)):
            raise ValueError("triggers must not contain duplicates")
        return value

    @field_validator("data_health")
    @classmethod
    def _check_data_health(cls, value: tuple[DataHealthFact, ...]) -> tuple[DataHealthFact, ...]:
        source_ids = [item.source_id for item in value]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("data_health source_id must be unique")
        return value


class AlertEvaluation(_StrictModel):
    schema_version: Literal["alert-evaluation.v0.1"] = ALERT_EVALUATION_SCHEMA_VERSION
    rule_id: StrictStr
    code: StrictStr
    trade_date: StrictStr
    state: EvaluationState
    reason_code: AlertReasonCode
    actual: StrictFloat | StrictInt | StrictStr | None
    expected: StrictFloat | StrictInt | StrictStr | None

    @field_validator("actual", "expected", mode="before")
    @classmethod
    def _check_actual_expected(cls, value: Any) -> float | str | None:
        if value is None or isinstance(value, str):
            return value
        return _strict_finite_number(value, field_name="actual/expected")


def _metric_value(snapshot: AlertFactSnapshot, metric: AlertMetric) -> float | None:
    return getattr(snapshot.metrics, metric)


def _evaluation(
    *,
    rule: AlertRule,
    snapshot: AlertFactSnapshot,
    state: EvaluationState,
    reason_code: AlertReasonCode,
    actual: float | str | None,
    expected: float | str | None,
) -> AlertEvaluation:
    return AlertEvaluation(
        rule_id=rule.rule_id,
        code=rule.code,
        trade_date=snapshot.trade_date,
        state=state,
        reason_code=reason_code,
        actual=actual,
        expected=expected,
    )


def evaluate_alert_rule(rule: AlertRule, snapshot: AlertFactSnapshot) -> AlertEvaluation:
    """Evaluate one alert rule against a normalized fact snapshot."""
    if not rule.enabled:
        return _evaluation(
            rule=rule,
            snapshot=snapshot,
            state="disabled",
            reason_code="RULE_DISABLED",
            actual=None,
            expected=None,
        )

    if rule.code != snapshot.code:
        return _evaluation(
            rule=rule,
            snapshot=snapshot,
            state="not_evaluable",
            reason_code="SNAPSHOT_CODE_MISMATCH",
            actual=snapshot.code,
            expected=rule.code,
        )

    condition = rule.condition

    if isinstance(condition, TechnicalTriggerCondition):
        present = condition.trigger in snapshot.triggers
        if present:
            return _evaluation(
                rule=rule,
                snapshot=snapshot,
                state="matched",
                reason_code="TECHNICAL_TRIGGER_PRESENT",
                actual=condition.trigger,
                expected=condition.trigger,
            )
        return _evaluation(
            rule=rule,
            snapshot=snapshot,
            state="not_matched",
            reason_code="TECHNICAL_TRIGGER_ABSENT",
            actual=None,
            expected=condition.trigger,
        )

    if isinstance(condition, MetricThresholdCondition):
        actual = _metric_value(snapshot, condition.metric)
        if actual is None:
            return _evaluation(
                rule=rule,
                snapshot=snapshot,
                state="not_evaluable",
                reason_code="METRIC_UNAVAILABLE",
                actual=None,
                expected=condition.threshold,
            )
        matched = _compare(actual, condition.operator, float(condition.threshold))
        return _evaluation(
            rule=rule,
            snapshot=snapshot,
            state="matched" if matched else "not_matched",
            reason_code="METRIC_THRESHOLD_MATCH" if matched else "METRIC_THRESHOLD_MISMATCH",
            actual=actual,
            expected=condition.threshold,
        )

    if isinstance(condition, MetricComparisonCondition):
        left = _metric_value(snapshot, condition.left)
        right = _metric_value(snapshot, condition.right)
        if left is None or right is None:
            return _evaluation(
                rule=rule,
                snapshot=snapshot,
                state="not_evaluable",
                reason_code="METRIC_UNAVAILABLE",
                actual=left,
                expected=right,
            )
        matched = _compare(left, condition.operator, right)
        return _evaluation(
            rule=rule,
            snapshot=snapshot,
            state="matched" if matched else "not_matched",
            reason_code="METRIC_COMPARISON_MATCH" if matched else "METRIC_COMPARISON_MISMATCH",
            actual=left,
            expected=right,
        )

    if isinstance(condition, TechnicalStatusCondition):
        matched = snapshot.technical_status == condition.status
        return _evaluation(
            rule=rule,
            snapshot=snapshot,
            state="matched" if matched else "not_matched",
            reason_code="TECHNICAL_STATUS_MATCH" if matched else "TECHNICAL_STATUS_MISMATCH",
            actual=snapshot.technical_status,
            expected=condition.status,
        )

    # DataHealthStatusCondition
    found = None
    for item in snapshot.data_health:
        if item.source_id == condition.source_id:
            found = item
            break
    if found is None:
        return _evaluation(
            rule=rule,
            snapshot=snapshot,
            state="not_evaluable",
            reason_code="DATA_HEALTH_SOURCE_MISSING",
            actual=None,
            expected=condition.status,
        )
    matched = found.status == condition.status
    return _evaluation(
        rule=rule,
        snapshot=snapshot,
        state="matched" if matched else "not_matched",
        reason_code="DATA_HEALTH_STATUS_MATCH" if matched else "DATA_HEALTH_STATUS_MISMATCH",
        actual=found.status,
        expected=condition.status,
    )


def evaluate_alert_rules(
    rules: tuple[AlertRule, ...] | list[AlertRule],
    snapshot: AlertFactSnapshot,
) -> list[AlertEvaluation]:
    """Evaluate rules in input order without sorting, deduping, or short-circuiting."""
    return [evaluate_alert_rule(rule, snapshot) for rule in rules]
