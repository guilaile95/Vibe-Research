"""Deterministic alert rule domain contract tests. No network/filesystem."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

import alert_rules as ar


def metrics(
    *,
    close=10.0,
    sma20=9.5,
    sma60=9.0,
    kdj_k=50.0,
    kdj_d=50.0,
    kdj_j=50.0,
) -> ar.AlertMetricSnapshot:
    return ar.AlertMetricSnapshot(
        close=close,
        sma20=sma20,
        sma60=sma60,
        kdj_k=kdj_k,
        kdj_d=kdj_d,
        kdj_j=kdj_j,
    )


def snapshot(
    *,
    code="000001",
    trade_date="2026-08-01",
    technical_status="normal",
    metric_values=None,
    triggers=(),
    data_health=(),
) -> ar.AlertFactSnapshot:
    return ar.AlertFactSnapshot(
        code=code,
        trade_date=trade_date,
        technical_status=technical_status,
        metrics=metric_values or metrics(),
        triggers=triggers,
        data_health=data_health,
    )


def rule(
    condition,
    *,
    rule_id="rule.1",
    code="000001",
    enabled=True,
) -> ar.AlertRule:
    return ar.AlertRule(
        rule_id=rule_id,
        code=code,
        enabled=enabled,
        condition=condition,
    )


# ---------------------------------------------------------------------------
# Model strictness
# ---------------------------------------------------------------------------


def test_schema_defaults_and_frozen_forbid_extra():
    r = rule(ar.TechnicalTriggerCondition(kind="technical_trigger", trigger="sma_golden_cross"))
    s = snapshot()
    e = ar.evaluate_alert_rule(r, s)
    assert r.schema_version == "alert-rule.v0.1"
    assert s.schema_version == "alert-facts.v0.1"
    assert e.schema_version == "alert-evaluation.v0.1"
    with pytest.raises(ValidationError):
        ar.AlertRule(
            rule_id="r1",
            code="000001",
            condition={"kind": "technical_trigger", "trigger": "sma_golden_cross"},
            unexpected=1,
        )
    with pytest.raises(ValidationError):
        r.enabled = False  # frozen


@pytest.mark.parametrize(
    "rule_id,ok",
    [
        ("a", True),
        ("Rule_1.x-2", True),
        ("", False),
        (" rule1", False),
        ("-bad", False),
        ("x" * 65, False),
    ],
)
def test_rule_id_contract(rule_id, ok):
    payload = {
        "rule_id": rule_id,
        "code": "000001",
        "condition": {"kind": "technical_trigger", "trigger": "sma_golden_cross"},
    }
    if ok:
        ar.AlertRule.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            ar.AlertRule.model_validate(payload)


@pytest.mark.parametrize(
    "code,ok",
    [
        ("000001", True),
        ("600000", True),
        ("sh600000", False),
        ("12345", False),
        (" 000001", False),
        ("０００００１", False),
        ("１２３４５６", False),
    ],
)
def test_code_contract(code, ok):
    payload = {
        "rule_id": "r1",
        "code": code,
        "condition": {"kind": "technical_trigger", "trigger": "sma_golden_cross"},
    }
    if ok:
        ar.AlertRule.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            ar.AlertRule.model_validate(payload)
    snapshot_payload = {
        "code": code,
        "trade_date": "2026-08-01",
        "technical_status": "normal",
        "metrics": metrics().model_dump(),
    }
    if ok:
        ar.AlertFactSnapshot.model_validate(snapshot_payload)
    else:
        with pytest.raises(ValidationError):
            ar.AlertFactSnapshot.model_validate(snapshot_payload)


@pytest.mark.parametrize("enabled", [0, 1, "true", "false", None])
def test_enabled_strict_bool_rejects_coercion(enabled):
    with pytest.raises(ValidationError):
        ar.AlertRule.model_validate(
            {
                "rule_id": "r1",
                "code": "000001",
                "enabled": enabled,
                "condition": {"kind": "technical_trigger", "trigger": "sma_golden_cross"},
            }
        )


@pytest.mark.parametrize(
    "trade_date,ok",
    [
        ("2026-08-01", True),
        ("2026-02-31", False),
        ("2026-8-1", False),
        ("2026/08/01", False),
        (" 2026-08-01", False),
        ("2026-08-01T00:00:00", False),
    ],
)
def test_trade_date_contract(trade_date, ok):
    payload = {
        "code": "000001",
        "trade_date": trade_date,
        "technical_status": "normal",
        "metrics": metrics().model_dump(),
    }
    if ok:
        ar.AlertFactSnapshot.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            ar.AlertFactSnapshot.model_validate(payload)


@pytest.mark.parametrize(
    "source_id,ok",
    [
        ("technical_indicators", True),
        ("northbound_capital_flow", True),
        ("portfolio_quotes", True),
        ("", False),
        ("Technical_Indicators", False),
        ("tech indicators", False),
        ("tech/indicators", False),
        ("x" * 65, False),
    ],
)
def test_source_id_contract(source_id, ok):
    payload = {"source_id": source_id, "status": "partial"}
    if ok:
        ar.DataHealthFact.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            ar.DataHealthFact.model_validate(payload)


# ---------------------------------------------------------------------------
# Strict numbers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [10, 10.5])
def test_accepts_real_numbers(value):
    m = metrics(close=value, sma20=value, sma60=value, kdj_k=value, kdj_d=value, kdj_j=value)
    assert m.close == float(value)


@pytest.mark.parametrize("value", [True, False, "10", "", float("nan"), float("inf"), float("-inf")])
def test_rejects_invalid_metric_values(value):
    with pytest.raises(ValidationError):
        metrics(close=value)


@pytest.mark.parametrize("field", ["close", "sma20", "sma60"])
def test_price_fields_must_be_positive(field):
    kwargs = {field: 0}
    with pytest.raises(ValidationError):
        metrics(**kwargs)
    kwargs = {field: -1}
    with pytest.raises(ValidationError):
        metrics(**kwargs)


def test_kdj_j_allows_outside_0_100_and_threshold_allows_extremes():
    m = metrics(kdj_j=-20)
    assert m.kdj_j == -20
    m2 = metrics(kdj_j=130)
    assert m2.kdj_j == 130
    c1 = ar.MetricThresholdCondition(kind="metric_threshold", metric="kdj_j", operator="gt", threshold=-5)
    c2 = ar.MetricThresholdCondition(kind="metric_threshold", metric="kdj_j", operator="lt", threshold=120)
    assert c1.threshold == -5
    assert c2.threshold == 120


@pytest.mark.parametrize("threshold", [True, "1.0", float("nan"), float("inf")])
def test_threshold_rejects_invalid(threshold):
    with pytest.raises(ValidationError):
        ar.MetricThresholdCondition(kind="metric_threshold", metric="close", operator="gt", threshold=threshold)


# ---------------------------------------------------------------------------
# Condition discrimination
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "technical_trigger", "trigger": "close_above_20d_high"},
        {"kind": "metric_threshold", "metric": "close", "operator": "gt", "threshold": 1},
        {"kind": "metric_comparison", "left": "close", "operator": "gt", "right": "sma20"},
        {"kind": "technical_status", "status": "partial"},
        {"kind": "data_health_status", "source_id": "technical_indicators", "status": "unavailable"},
    ],
)
def test_condition_kinds_parse(payload):
    r = ar.AlertRule(rule_id="r1", code="000001", condition=payload)
    assert r.condition.kind == payload["kind"]


def test_unknown_or_missing_kind_and_bad_fields_rejected():
    with pytest.raises(ValidationError):
        ar.AlertRule(rule_id="r1", code="000001", condition={"kind": "unknown"})
    with pytest.raises(ValidationError):
        ar.AlertRule(rule_id="r1", code="000001", condition={"trigger": "sma_golden_cross"})
    with pytest.raises(ValidationError):
        ar.MetricThresholdCondition(kind="metric_threshold", metric="close", operator="gt", threshold=1, extra=1)
    with pytest.raises(ValidationError):
        ar.MetricComparisonCondition(kind="metric_comparison", left="close", operator="gt", right="close")
    with pytest.raises(ValidationError):
        snapshot(triggers=("sma_golden_cross", "sma_golden_cross"))
    with pytest.raises(ValidationError):
        snapshot(
            data_health=(
                ar.DataHealthFact(source_id="technical_indicators", status="partial"),
                ar.DataHealthFact(source_id="technical_indicators", status="unavailable"),
            )
        )


# ---------------------------------------------------------------------------
# Evaluation semantics
# ---------------------------------------------------------------------------


def test_disabled_and_code_mismatch_priority():
    r_disabled = rule(
        ar.TechnicalTriggerCondition(kind="technical_trigger", trigger="sma_golden_cross"),
        enabled=False,
        code="000001",
    )
    s = snapshot(code="600000")
    out = ar.evaluate_alert_rule(r_disabled, s)
    assert out.state == "disabled"
    assert out.reason_code == "RULE_DISABLED"
    assert out.actual is None and out.expected is None

    r = rule(ar.TechnicalTriggerCondition(kind="technical_trigger", trigger="sma_golden_cross"), code="000001")
    out2 = ar.evaluate_alert_rule(r, s)
    assert out2.state == "not_evaluable"
    assert out2.reason_code == "SNAPSHOT_CODE_MISMATCH"
    assert out2.actual == "600000"
    assert out2.expected == "000001"


@pytest.mark.parametrize(
    "trigger",
    [
        "close_above_20d_high",
        "close_below_20d_low",
        "sma_golden_cross",
        "sma_death_cross",
    ],
)
def test_technical_trigger_present_and_absent(trigger):
    r = rule(ar.TechnicalTriggerCondition(kind="technical_trigger", trigger=trigger))
    present = ar.evaluate_alert_rule(r, snapshot(triggers=(trigger,)))
    assert present.state == "matched"
    assert present.reason_code == "TECHNICAL_TRIGGER_PRESENT"
    assert present.actual == trigger
    assert present.expected == trigger

    absent = ar.evaluate_alert_rule(r, snapshot(triggers=()))
    assert absent.state == "not_matched"
    assert absent.reason_code == "TECHNICAL_TRIGGER_ABSENT"
    assert absent.actual is None
    assert absent.expected == trigger


@pytest.mark.parametrize(
    "operator,actual,threshold,matched",
    [
        ("gt", 11, 10, True),
        ("gt", 10, 10, False),
        ("gte", 10, 10, True),
        ("gte", 9, 10, False),
        ("lt", 9, 10, True),
        ("lt", 10, 10, False),
        ("lte", 10, 10, True),
        ("lte", 11, 10, False),
    ],
)
def test_metric_threshold_operators(operator, actual, threshold, matched):
    r = rule(
        ar.MetricThresholdCondition(
            kind="metric_threshold",
            metric="close",
            operator=operator,
            threshold=threshold,
        )
    )
    out = ar.evaluate_alert_rule(r, snapshot(metric_values=metrics(close=actual)))
    assert out.state == ("matched" if matched else "not_matched")
    assert out.reason_code == ("METRIC_THRESHOLD_MATCH" if matched else "METRIC_THRESHOLD_MISMATCH")
    assert out.actual == actual
    assert out.expected == threshold


def test_metric_threshold_unavailable_and_kdj_extremes():
    r = rule(ar.MetricThresholdCondition(kind="metric_threshold", metric="kdj_k", operator="lt", threshold=20))
    out = ar.evaluate_alert_rule(r, snapshot(metric_values=metrics(kdj_k=None)))
    assert out.state == "not_evaluable"
    assert out.reason_code == "METRIC_UNAVAILABLE"
    assert out.actual is None
    assert out.expected == 20

    r_hi = rule(ar.MetricThresholdCondition(kind="metric_threshold", metric="kdj_j", operator="gt", threshold=100))
    out_hi = ar.evaluate_alert_rule(r_hi, snapshot(metric_values=metrics(kdj_j=120)))
    assert out_hi.state == "matched"
    assert out_hi.actual == 120

    r_lo = rule(ar.MetricThresholdCondition(kind="metric_threshold", metric="kdj_j", operator="lt", threshold=0))
    out_lo = ar.evaluate_alert_rule(r_lo, snapshot(metric_values=metrics(kdj_j=-5)))
    assert out_lo.state == "matched"
    assert out_lo.actual == -5


def test_metric_comparison_paths():
    base = metrics(close=11, sma20=10, sma60=9)
    cases = [
        ("close", "sma20", True),
        ("close", "sma60", True),
        ("sma20", "sma60", True),
    ]
    for left, right, matched in cases:
        r = rule(ar.MetricComparisonCondition(kind="metric_comparison", left=left, operator="gt", right=right))
        out = ar.evaluate_alert_rule(r, snapshot(metric_values=base))
        assert out.state == ("matched" if matched else "not_matched")
        assert out.reason_code == ("METRIC_COMPARISON_MATCH" if matched else "METRIC_COMPARISON_MISMATCH")
        assert out.actual == getattr(base, left)
        assert out.expected == getattr(base, right)

    out_left_none = ar.evaluate_alert_rule(
        rule(ar.MetricComparisonCondition(kind="metric_comparison", left="close", operator="gt", right="sma20")),
        snapshot(metric_values=metrics(close=None)),
    )
    assert out_left_none.state == "not_evaluable"
    assert out_left_none.reason_code == "METRIC_UNAVAILABLE"
    assert out_left_none.actual is None
    assert out_left_none.expected == 9.5

    out_right_none = ar.evaluate_alert_rule(
        rule(ar.MetricComparisonCondition(kind="metric_comparison", left="close", operator="gt", right="sma20")),
        snapshot(metric_values=metrics(sma20=None)),
    )
    assert out_right_none.state == "not_evaluable"
    assert out_right_none.actual == 10.0
    assert out_right_none.expected is None

    out_both_none = ar.evaluate_alert_rule(
        rule(ar.MetricComparisonCondition(kind="metric_comparison", left="close", operator="gt", right="sma20")),
        snapshot(metric_values=metrics(close=None, sma20=None)),
    )
    assert out_both_none.state == "not_evaluable"
    assert out_both_none.actual is None
    assert out_both_none.expected is None


def test_technical_status_matching():
    r_partial = rule(ar.TechnicalStatusCondition(kind="technical_status", status="partial"))
    r_unavail = rule(ar.TechnicalStatusCondition(kind="technical_status", status="unavailable"))

    assert ar.evaluate_alert_rule(r_partial, snapshot(technical_status="partial")).reason_code == "TECHNICAL_STATUS_MATCH"
    assert ar.evaluate_alert_rule(r_unavail, snapshot(technical_status="unavailable")).reason_code == "TECHNICAL_STATUS_MATCH"
    assert ar.evaluate_alert_rule(r_partial, snapshot(technical_status="normal")).reason_code == "TECHNICAL_STATUS_MISMATCH"
    assert ar.evaluate_alert_rule(r_partial, snapshot(technical_status="unavailable")).reason_code == "TECHNICAL_STATUS_MISMATCH"

    with pytest.raises(ValidationError):
        ar.TechnicalStatusCondition(kind="technical_status", status="normal")


def test_data_health_matching_and_missing():
    dh = (
        ar.DataHealthFact(source_id="technical_indicators", status="partial"),
        ar.DataHealthFact(source_id="northbound_capital_flow", status="unavailable"),
    )
    s = snapshot(data_health=dh)

    r1 = rule(ar.DataHealthStatusCondition(kind="data_health_status", source_id="technical_indicators", status="partial"))
    out1 = ar.evaluate_alert_rule(r1, s)
    assert out1.state == "matched"
    assert out1.reason_code == "DATA_HEALTH_STATUS_MATCH"
    assert out1.actual == "partial"

    r2 = rule(
        ar.DataHealthStatusCondition(
            kind="data_health_status",
            source_id="northbound_capital_flow",
            status="unavailable",
        )
    )
    out2 = ar.evaluate_alert_rule(r2, s)
    assert out2.state == "matched"
    assert out2.actual == "unavailable"

    r3 = rule(
        ar.DataHealthStatusCondition(
            kind="data_health_status",
            source_id="technical_indicators",
            status="unavailable",
        )
    )
    out3 = ar.evaluate_alert_rule(r3, s)
    assert out3.state == "not_matched"
    assert out3.reason_code == "DATA_HEALTH_STATUS_MISMATCH"
    assert out3.actual == "partial"

    r4 = rule(ar.DataHealthStatusCondition(kind="data_health_status", source_id="portfolio_quotes", status="partial"))
    out4 = ar.evaluate_alert_rule(r4, s)
    assert out4.state == "not_evaluable"
    assert out4.reason_code == "DATA_HEALTH_SOURCE_MISSING"
    assert out4.actual is None
    assert out4.expected == "partial"


def test_batch_evaluation_order_and_independence():
    s = snapshot(code="000001", triggers=("sma_golden_cross",))
    rules = [
        rule(ar.TechnicalTriggerCondition(kind="technical_trigger", trigger="sma_golden_cross"), rule_id="a"),
        rule(ar.TechnicalTriggerCondition(kind="technical_trigger", trigger="sma_death_cross"), rule_id="b", enabled=False),
        rule(ar.TechnicalTriggerCondition(kind="technical_trigger", trigger="sma_death_cross"), rule_id="a"),  # duplicate id allowed
        rule(ar.MetricThresholdCondition(kind="metric_threshold", metric="close", operator="gt", threshold=100), rule_id="c"),
    ]
    assert ar.evaluate_alert_rules([], s) == []
    out = ar.evaluate_alert_rules(rules, s)
    assert [x.rule_id for x in out] == ["a", "b", "a", "c"]
    assert out[0].state == "matched"
    assert out[1].state == "disabled"
    assert out[2].state == "not_matched"
    assert out[3].state == "not_matched"


def test_deterministic_and_immutable():
    r = rule(
        ar.MetricComparisonCondition(kind="metric_comparison", left="close", operator="gt", right="sma20"),
        rule_id="det.1",
    )
    s = snapshot(
        triggers=("close_above_20d_high",),
        data_health=(ar.DataHealthFact(source_id="technical_indicators", status="partial"),),
    )
    before_r = r.model_dump()
    before_s = s.model_dump()
    first = ar.evaluate_alert_rule(r, s).model_dump()
    for _ in range(100):
        assert ar.evaluate_alert_rule(r, s).model_dump() == first
    assert r.model_dump() == before_r
    assert s.model_dump() == before_s
    with pytest.raises(ValidationError):
        r.rule_id = "x"
    with pytest.raises(ValidationError):
        s.trade_date = "2026-08-02"


def test_no_advice_or_trading_words_in_module_source():
    source = Path(ar.__file__).read_text(encoding="utf-8").lower()
    for forbidden in ["buy", "sell", "买入", "卖出", "仓位", "自动交易"]:
        assert forbidden not in source
