"""CF1 production OL1 integration tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

import formal_decision_outcome_runtime as runtime
import frozen_decision_store as fd_store
from app import app
from fact_lake_store import initialize_fact_lake
from test_formal_decision_outcome import make_decision
from test_security_price_point_authority import _publish


EVALUATION_AS_OF = "2026-08-26T08:30:00.000000Z"


def _install_env(monkeypatch, tmp_path):
    frozen = tmp_path / "frozen.sqlite3"
    monkeypatch.setenv("VIBE_RESEARCH_FROZEN_DECISION_DB", str(frozen))
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    return frozen


def _write_decision(path):
    return fd_store.write_frozen_decision(path, make_decision())


def test_runtime_builds_counterfactual_from_fact_lake_and_preserves_replay(
    tmp_path, monkeypatch
):
    frozen = _install_env(monkeypatch, tmp_path)
    lake = initialize_fact_lake(tmp_path / "lake")
    _publish(lake, "2026-08-07", close=100.0, event=1)
    _publish(lake, "2026-08-26", close=110.0, event=2)
    monkeypatch.setenv("VR_FACT_LAKE_ROOT", str(lake.root))
    decision = _write_decision(frozen)

    result = runtime.evaluate_outcome(
        decision["decision_id"], evaluation_as_of=EVALUATION_AS_OF
    )
    cf = result["counterfactual_outcome"]

    assert cf["state"] == "EVALUATED"
    assert cf["metric_kind"] == "SECURITY_CLOSE_TO_CLOSE_RETURN"
    assert cf["start_price_point"]["trade_date"] == "2026-08-07"
    assert cf["end_price_point"]["trade_date"] == "2026-08-26"
    assert cf["start_price_point"]["close"] == 100.0
    assert cf["end_price_point"]["close"] == 110.0
    assert cf["security_return"] == "0.1"
    assert result["actual_capital_outcome"]["state"] == "NO_ACTUAL_TRADE"
    assert "price" not in result["decision_time_replay"]
    assert result["replay_future_fact_leak"] is False

    replay_hash = result["decision_time_replay"]["replay_hash"]
    later = runtime.evaluate_outcome(
        decision["decision_id"], evaluation_as_of=EVALUATION_AS_OF
    )
    assert later["decision_time_replay"]["replay_hash"] == replay_hash
    assert later["outcome_reveal"]["outcome_reveal_hash"] == result[
        "outcome_reveal"
    ]["outcome_reveal_hash"]


def test_public_api_does_not_accept_caller_counterfactual_fields(
    tmp_path, monkeypatch
):
    frozen = _install_env(monkeypatch, tmp_path)
    decision = _write_decision(frozen)
    client = TestClient(app)

    response = client.get(
        f"/api/formal-decisions/{decision['decision_id']}/outcome",
        params={
            "evaluation_as_of": EVALUATION_AS_OF,
            "start_close": "999999",
            "end_close": "999999",
            "security_return": "999999",
            "counterfactual_state": "EVALUATED",
            "publication_id": "caller-forged",
        },
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["counterfactual_outcome"]["state"] == "NOT_EVALUATED"
    assert body["counterfactual_outcome"].get("security_return") is None


def test_fact_lake_corruption_fails_counterfactual_closed(tmp_path, monkeypatch):
    frozen = _install_env(monkeypatch, tmp_path)
    lake = initialize_fact_lake(tmp_path / "lake")
    _, start_publication = _publish(lake, "2026-08-07", close=100.0, event=1)
    _publish(lake, "2026-08-26", close=110.0, event=2)
    lake.canonical_artifact_path(start_publication.artifact_relpath).write_bytes(
        b"corrupt"
    )
    monkeypatch.setenv("VR_FACT_LAKE_ROOT", str(lake.root))
    decision = _write_decision(frozen)

    result = runtime.evaluate_outcome(
        decision["decision_id"], evaluation_as_of=EVALUATION_AS_OF
    )

    assert result["counterfactual_outcome"]["state"] == "ERROR"
    assert result["actual_capital_outcome"]["state"] == "NO_ACTUAL_TRADE"
