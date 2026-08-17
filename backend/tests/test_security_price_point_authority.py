"""CF1 shared PIT price-point and counterfactual contracts."""

from __future__ import annotations

import copy
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, localcontext
import json
from types import SimpleNamespace

import pytest

import formal_decision_outcome as outcome
import security_price_point_authority as authority
from test_formal_decision_outcome import make_decision
from fact_lake_store import initialize_fact_lake, open_existing_fact_lake, payload_sha256
from security_exchange_policy import POLICY_VERSION_V01
from tushare_daily_shadow import (
    DAILY_FIELD_MANIFEST,
    TushareDailyRawResponseCapture,
    TushareDailyRequestContract,
    build_request_fingerprint,
    build_tushare_daily_canonical_fact,
    persist_tushare_daily_evidence,
    publish_tushare_daily_canonical_fact,
)


def _raw_daily(trade_date: str, rows: list[dict[str, object]]) -> bytes:
    defaults = {
        "open": 100.0,
        "high": 110.0,
        "low": 99.0,
        "close": 100.0,
        "pre_close": 99.0,
        "change": 1.0,
        "pct_chg": 1.0,
        "vol": 1000.0,
        "amount": 100000.0,
    }
    items = []
    for row in rows:
        value = {**defaults, "trade_date": trade_date.replace("-", ""), **row}
        items.append([value[field] for field in DAILY_FIELD_MANIFEST])
    return json.dumps(
        {"code": 0, "msg": "synthetic", "data": {
            "fields": list(DAILY_FIELD_MANIFEST), "items": items,
        }},
        separators=(",", ":"),
    ).encode()


def _publish(
    lake,
    trade_date: str,
    *,
    close: object = 100.0,
    fetched_at: str | None = None,
    event: int = 1,
    rows: list[dict[str, object]] | None = None,
):
    fetched_at = fetched_at or f"{trade_date}T08:00:00.000000Z"
    raw = _raw_daily(
        trade_date,
        rows or [{"ts_code": "600519.SH", "close": close}],
    )
    contract = TushareDailyRequestContract(trade_date)
    capture = TushareDailyRawResponseCapture(
        capture_event_id=f"capture-{event:032x}",
        contract=contract,
        raw_bytes=raw,
        request_fingerprint=build_request_fingerprint(contract),
        source_payload_hash=payload_sha256(raw),
        http_status=200,
        content_type="application/json; charset=utf-8",
        fetched_at=fetched_at,
    )
    observation, normalization = persist_tushare_daily_evidence(lake, capture)
    fact = build_tushare_daily_canonical_fact(observation.observation, normalization)
    publication = publish_tushare_daily_canonical_fact(lake, fact)
    return observation, publication


def _point(lake, as_of: str, *, publication_id: str | None = None, code: str = "600519"):
    return authority.resolve_authoritative_price_point(
        lake=open_existing_fact_lake(lake.root, readonly=True),
        security_code=code,
        as_of=as_of,
        security_exchange_policy_version=POLICY_VERSION_V01,
        publication_id=publication_id,
    )


def test_exact_visible_start_and_end_points_evaluate_security_return(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _publish(lake, "2026-07-29", close=100.0, event=1)
    _publish(lake, "2026-07-30", close=110.0, event=2)

    start = _point(lake, "2026-07-29T08:30:00Z")
    end = _point(lake, "2026-07-30T08:30:00Z")
    result = outcome.build_security_close_to_close_counterfactual(start, end)

    assert start["state"] == "USABLE"
    assert end["state"] == "USABLE"
    assert result["state"] == "EVALUATED"
    assert result["metric_kind"] == "SECURITY_CLOSE_TO_CLOSE_RETURN"
    assert result["security_return"] == "0.1"
    assert result["start_price_point"]["close"] == 100.0
    assert result["end_price_point"]["close"] == 110.0


def test_future_fetched_observation_cannot_prove_start_point(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _publish(lake, "2026-07-29", fetched_at="2026-07-29T08:31:00.000000Z")

    start = _point(lake, "2026-07-29T08:30:00Z")

    assert start["state"] == "NOT_EVALUATED"
    assert start["reason_codes"] == ["PUBLICATION_NOT_VISIBLE_BY_AS_OF"]
    assert start["close"] is None


def test_later_backfill_does_not_rewrite_earlier_visibility(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _publish(lake, "2026-07-29", fetched_at="2026-07-29T08:31:00.000000Z")
    before = _point(lake, "2026-07-29T08:30:00Z")
    _publish(lake, "2026-07-30", close=105.0, event=2)
    after_same_as_of = _point(lake, "2026-07-29T08:30:00Z")

    assert before["state"] == "NOT_EVALUATED"
    assert after_same_as_of["state"] == "NOT_EVALUATED"
    assert before["as_of"] == after_same_as_of["as_of"]


def test_multiple_visible_publications_without_winner_are_not_evaluated(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _, first = _publish(lake, "2026-07-29", close=100.0, event=1)
    _publish(lake, "2026-07-29", close=101.0, event=2)

    unpinned = _point(lake, "2026-07-29T08:30:00Z")
    pinned = _point(lake, "2026-07-29T08:30:00Z", publication_id=first.publication_id)

    assert unpinned["state"] == "NOT_EVALUATED"
    assert unpinned["reason_codes"] == ["MULTIPLE_VISIBLE_PUBLICATIONS_NO_WINNER"]
    assert pinned["state"] == "USABLE"


def test_missing_security_row_is_not_evaluated(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _publish(lake, "2026-07-29", rows=[{"ts_code": "000001.SZ", "close": 100.0}])

    result = _point(lake, "2026-07-29T08:30:00Z")

    assert result["state"] == "NOT_EVALUATED"
    assert result["reason_codes"] == ["SECURITY_ROW_MISSING"]


def test_duplicate_target_security_row_is_error(tmp_path, monkeypatch):
    lake = initialize_fact_lake(tmp_path / "lake")
    _publish(lake, "2026-07-29")
    original = authority.query_tushare_daily

    def duplicate_rows(*args, **kwargs):
        result = list(original(*args, **kwargs))
        value = copy.deepcopy(result[0])
        value["canonical_payload"]["rows"].append(
            copy.deepcopy(value["canonical_payload"]["rows"][0])
        )
        return tuple(result + [value])

    monkeypatch.setattr(authority, "query_tushare_daily", duplicate_rows)
    result = _point(lake, "2026-07-29T08:30:00Z")

    assert result["state"] == "ERROR"


@pytest.mark.parametrize(
    ("close", "expected"),
    [(None, "NOT_EVALUATED"), (0.0, "ERROR"), (-1.0, "ERROR")],
)
def test_missing_or_invalid_close_fails_closed(tmp_path, close, expected):
    lake = initialize_fact_lake(tmp_path / "lake")
    _publish(lake, "2026-07-29", close=close)

    result = _point(lake, "2026-07-29T08:30:00Z")

    assert result["state"] == expected


def test_replay_failure_and_blocked_health_are_not_usable(tmp_path, monkeypatch):
    lake = initialize_fact_lake(tmp_path / "lake")
    _publish(lake, "2026-07-29")
    monkeypatch.setattr(
        authority,
        "verify_tushare_daily_normalization_replay",
        lambda *_: SimpleNamespace(status="MISMATCH"),
    )
    replay_result = _point(lake, "2026-07-29T08:30:00Z")
    assert replay_result["state"] == "ERROR"

    monkeypatch.setattr(
        authority,
        "verify_tushare_daily_normalization_replay",
        lambda *_: SimpleNamespace(status="MATCH"),
    )
    monkeypatch.setattr(
        authority,
        "assess_publication_health",
        lambda **_: SimpleNamespace(canonical_admissibility="BLOCKED"),
    )
    health_result = _point(lake, "2026-07-29T08:30:00Z")
    assert health_result["state"] == "ERROR"


def test_unresolved_exchange_and_no_completed_date_are_not_evaluated(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")

    bse = _point(lake, "2026-07-29T08:30:00Z", code="920001")
    no_session = _point(lake, "1970-01-01T00:00:00Z")

    assert bse["state"] == "NOT_EVALUATED"
    assert no_session["state"] == "NOT_EVALUATED"


def test_end_date_not_after_start_never_emits_zero_return():
    point = {
        "state": "USABLE",
        "security_code": "600519",
        "trade_date": "2026-07-29",
        "close": 100.0,
        "authority_refs": ["test"],
    }

    result = outcome.build_security_close_to_close_counterfactual(point, point)

    assert result["state"] == "NOT_EVALUATED"
    assert result["reason_codes"] == ["NO_POST_DECISION_COMPLETED_SESSION"]
    assert result["security_return"] is None


def test_counterfactual_is_independent_of_actual_trade_inputs():
    start = {
        "state": "USABLE", "security_code": "600519",
        "trade_date": "2026-07-29", "close": 100.0,
        "authority_refs": ["start"],
    }
    end = {
        "state": "USABLE", "security_code": "600519",
        "trade_date": "2026-07-30", "close": 110.0,
        "authority_refs": ["end"],
    }
    first = outcome.build_security_close_to_close_counterfactual(start, end)
    second = outcome.build_security_close_to_close_counterfactual(start, end)

    assert first == second
    assert "trade_ids" not in first
    assert "pnl" not in first


def test_replay_hash_does_not_include_price_points():
    decision = make_decision()
    first = outcome.build_decision_time_replay(decision)
    second = outcome.build_decision_time_replay(decision)

    assert first["replay_hash"] == second["replay_hash"]
    assert "price" not in json.dumps(first).lower()


def test_counterfactual_rejects_synthetic_pnl_in_ol1_projection():
    decision = make_decision()
    with pytest.raises(outcome.OutcomeValidationError):
        outcome.project_ol1_outcome(
            decision,
            evaluation_as_of="2099-01-01T00:00:00Z",
            attributions=[],
            trades=[],
            counterfactual={
                "state": "EVALUATED",
                "metric_kind": "SECURITY_CLOSE_TO_CLOSE_RETURN",
                "pnl": {"realized": 1},
            },
        )


def test_counterfactual_decimal_payload_is_ambient_context_independent():
    start = {
        "state": "USABLE", "security_code": "600519",
        "trade_date": "2026-07-29", "close": 3,
        "authority_refs": ["start"],
    }
    end = {
        "state": "USABLE", "security_code": "600519",
        "trade_date": "2026-07-30", "close": 4,
        "authority_refs": ["end"],
    }
    decision = make_decision()
    outputs = []
    for precision, rounding in (
        (2, ROUND_DOWN),
        (7, ROUND_CEILING),
        (80, ROUND_FLOOR),
    ):
        with localcontext() as ambient:
            ambient.prec = precision
            ambient.rounding = rounding
            counterfactual = outcome.build_security_close_to_close_counterfactual(
                start, end
            )
            projection = outcome.project_ol1_outcome(
                decision,
                evaluation_as_of="2099-01-01T00:00:00Z",
                attributions=[],
                trades=[],
                counterfactual=counterfactual,
            )
            outputs.append((counterfactual, projection["outcome_reveal"][
                "outcome_reveal_hash"
            ]))

    assert outputs[0] == outputs[1] == outputs[2]
    assert outputs[0][0]["security_return"].startswith("0.333333333333")
