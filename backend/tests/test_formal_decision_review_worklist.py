from __future__ import annotations

import pytest

import formal_decision_outcome_runtime as runtime
import formal_decision_review_worklist as worklist


EVALUATION_AS_OF = "2026-09-01T00:00:00.000000Z"


def row(decision_id: str, review_by: str, due_state: str, **extra):
    return {
        "decision_id": decision_id,
        "decision_snapshot_hash": "a" * 64,
        "security_code": "600519",
        "strategy": "SWING",
        "campaign_id": "campaign_" + "b" * 32,
        "decision_committed_at": "2026-08-01T00:00:00.000000Z",
        "decision_review_by": review_by,
        "due_state": due_state,
        "outcome_status": "EVALUATED" if due_state == "DUE" else "PENDING",
        "reason_codes": [],
        **extra,
    }


def test_projection_preserves_canonical_states_and_orders_each_group():
    result = worklist.project_review_worklist(
        [
            row(
                "decision_" + "b" * 32,
                "2026-09-03T00:00:00.000000Z",
                "DUE",
                decision_next_best_action="WAIT",
            ),
            row(
                "decision_" + "a" * 32,
                "2026-09-02T00:00:00.000000Z",
                "DUE",
                decision_next_best_action="HOLD",
            ),
            row(
                "decision_" + "d" * 32,
                "2026-09-04T00:00:00.000000Z",
                "NOT_DUE",
                decision_next_best_action="EXIT",
            ),
            row("decision_" + "c" * 32, "2026-09-01T00:00:00.000000Z", "NOT_DUE"),
        ],
        evaluation_as_of=EVALUATION_AS_OF,
    )
    assert [item["decision_id"] for item in result["due"]] == [
        "decision_" + "a" * 32,
        "decision_" + "b" * 32,
    ]
    assert [item["decision_id"] for item in result["upcoming"]] == [
        "decision_" + "c" * 32,
        "decision_" + "d" * 32,
    ]
    assert {item["due_state"] for item in result["upcoming"]} == {"NOT_DUE"}
    assert {item["group"] for item in result["upcoming"]} == {"upcoming"}
    assert result["due"][0]["decision_next_best_action"] == "HOLD"
    assert result["due"][1]["decision_next_best_action"] == "WAIT"
    assert result["upcoming"][0]["decision_next_best_action"] is None
    assert result["upcoming"][1]["decision_next_best_action"] == "EXIT"
    assert result["schema_version"] == "formal_decision_review_worklist.v0.2"


def test_missing_or_empty_historical_nba_is_not_inferred():
    result = worklist.project_review_worklist(
        [
            row(
                "decision_" + "a" * 32,
                "2026-09-01T00:00:00.000000Z",
                "DUE",
                decision_next_best_action="",
            ),
            row(
                "decision_" + "b" * 32,
                "2026-09-02T00:00:00.000000Z",
                "NOT_DUE",
                decision_next_best_action=None,
            ),
        ],
        evaluation_as_of=EVALUATION_AS_OF,
    )
    assert result["due"][0]["decision_next_best_action"] == ""
    assert result["upcoming"][0]["decision_next_best_action"] is None


def test_equal_and_after_boundary_are_ol1_due_not_overdue():
    result = worklist.project_review_worklist(
        [
            row("decision_" + "a" * 32, EVALUATION_AS_OF, "DUE"),
            row("decision_" + "b" * 32, "2026-08-31T23:59:59.000000Z", "DUE"),
        ],
        evaluation_as_of=EVALUATION_AS_OF,
    )
    assert all(item["due_state"] == "DUE" for item in result["due"])
    assert all("OVERDUE" not in item.values() for item in result["due"])


def test_error_and_unknown_state_are_unavailable_only():
    result = worklist.project_review_worklist(
        [
            row("decision_" + "a" * 32, "2026-09-01T00:00:00.000000Z", "ERROR", error_code="BROKEN"),
            row("decision_" + "b" * 32, "2026-09-02T00:00:00.000000Z", "FUTURE_STATE"),
        ],
        evaluation_as_of=EVALUATION_AS_OF,
    )
    assert result["due"] == []
    assert result["upcoming"] == []
    assert [item["error_code"] for item in result["unavailable"]] == [
        "BROKEN",
        "UNKNOWN_DUE_STATE",
    ]
    assert all(item["due_state"] == "ERROR" for item in result["unavailable"])


def test_duplicate_and_malformed_rows_fail_closed():
    duplicate = row("decision_" + "a" * 32, "2026-09-01T00:00:00.000000Z", "DUE")
    with pytest.raises(worklist.ReviewWorklistProjectionError):
        worklist.project_review_worklist(
            [duplicate, duplicate], evaluation_as_of=EVALUATION_AS_OF
        )
    with pytest.raises(worklist.ReviewWorklistProjectionError):
        worklist.project_review_worklist(
            [row("not-a-decision", "2026-09-01T00:00:00.000000Z", "DUE")],
            evaluation_as_of=EVALUATION_AS_OF,
        )


def test_runtime_uses_one_server_owned_boundary_and_reads_all_pages(monkeypatch):
    calls: list[tuple[str, str]] = []
    decisions = [
        {"decision_id": f"decision_{index:032x}"}
        for index in range(205)
    ]
    page_offsets: list[int] = []

    def list_decisions(*, limit, offset, **_kwargs):
        assert limit == 100
        page_offsets.append(offset)
        return decisions[offset : offset + limit]

    def evaluate(decision_id, *, evaluation_as_of):
        calls.append((decision_id, evaluation_as_of))
        return row(
            decision_id,
            "2026-09-02T00:00:00.000000Z",
            "DUE",
        )

    monkeypatch.setattr(runtime, "_now", lambda: EVALUATION_AS_OF)
    monkeypatch.setattr(runtime.frozen_decision_service, "list_decisions", list_decisions)
    monkeypatch.setattr(runtime, "evaluate_outcome", evaluate)
    result = runtime.build_review_worklist()

    assert result["counts"]["total"] == 205
    assert page_offsets == [0, 100, 200]
    assert len(calls) == 205
    assert {evaluation_as_of for _, evaluation_as_of in calls} == {EVALUATION_AS_OF}
    assert result["due"][0]["decision_id"] == "decision_" + "0" * 32
    assert result["due"][-1]["decision_id"] == f"decision_{204:032x}"
    assert result["evaluation_as_of"] == EVALUATION_AS_OF


def test_runtime_duplicate_page_fails_closed(monkeypatch):
    decisions = [
        {"decision_id": f"decision_{index:032x}"}
        for index in range(100)
    ]

    def list_decisions(*, limit, offset, **_kwargs):
        if offset == 0:
            return decisions
        return [decisions[0]]

    monkeypatch.setattr(runtime, "_now", lambda: EVALUATION_AS_OF)
    monkeypatch.setattr(runtime.frozen_decision_service, "list_decisions", list_decisions)
    monkeypatch.setattr(runtime, "evaluate_outcome", lambda decision_id, **_kwargs: row(
        decision_id, "2026-09-02T00:00:00.000000Z", "DUE"
    ))
    with pytest.raises(runtime.FormalOutcomeRuntimeError):
        runtime.build_review_worklist()
