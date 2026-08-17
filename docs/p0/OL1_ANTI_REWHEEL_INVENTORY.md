# P0-OL1 Anti-Rewheel Inventory

Base: `87cf692e1aa80c2eaa29d7e4999ce7657c949c34`

## Authority ownership

| Area | Existing authority | OL1 decision |
| --- | --- | --- |
| Frozen Decision identity, snapshot, hash, `committed_at`, `review_by` | `frozen_decision_store.py` / `frozen_decision_service.py` | Reuse as the only formal decision authority. |
| Formal attribution identity and TB1 witness validation | `formal_trade_attribution.py` / `formal_trade_attribution_store.py` | Reuse exact `decision_id` + `snapshot_hash` attribution records. |
| Trade-to-decision resolution | `trade_attribution_runtime.py` / TAR1 stores | Reuse; no same-security, time, FIFO, or AI inference. |
| Actual Trade Ledger facts and void state | `trade_ledger_store.py` / `trade_ledger_service.py` | Read exact attributed Trade rows; exclude voided and `not_executed`. |
| Existing O1 Formal Decision projection | `formal_decision_outcome.py` | Extend/reuse provenance-first validation and immutable projection patterns; do not create a second Frozen Decision authority. |
| Existing portfolio P&L | `performance_attribution_service.py` / `performance_attribution_store.py` | Reuse only through an exact trade-id input boundary; never use its global advice/performance view as Formal Outcome identity. |
| Legacy advice analytics | `decision_analytics_service.py` / `decision_analytics_router.py` | Keep explicitly legacy; never relabel as Formal Decision Outcome. |
| Legacy decision feedback | `decision_feedback_service.py` / `decision_feedback_store.py` | Keep explicitly legacy advice feedback; no automatic conversion to Formal Outcome. |
| Existing price/Fact Lake capability | `critical_data_price_reference_adapter.py`, Fact Lake and trade-calendar authorities | Inventory only. No existing OL1 point-in-time close-value contract is available on the exact base, so v0.1 counterfactual remains honest `NOT_EVALUATED` when no authoritative price path is present. |
| Existing UI surfaces | `DecisionPerformance.tsx`, `DecisionFeedback.tsx`, `PerformanceAttribution.tsx` | Add a clearly separated Formal Decision Outcome section; preserve legacy labels and semantics. |

## Rejected rewheels

- No second Frozen Decision store.
- No second Trade Attribution or origin authority.
- No new portfolio accounting engine.
- No legacy T+1/T+5/T+20 horizon reuse as Formal Outcome horizon.
- No AI quality score, automatic lesson, Thesis mutation, or policy mutation.
- No durable Outcome store in v0.1: the projection is read-only and deterministic from immutable authorities plus explicit `evaluation_as_of`.

## OL1 ownership boundary

OL1 owns only the Formal Decision Outcome projection/runtime/API/UI boundary:

1. Decision-Time Replay is derived solely from the verified Frozen Decision snapshot.
2. Outcome Reveal reads later facts only after the replay envelope is fixed.
3. Actual Capital Outcome consumes only exact TAR1-attributed, non-voided, executed Trade Ledger rows.
4. Decision Counterfactual Outcome is independent and remains `NOT_EVALUATED` without an authoritative future price path.
5. Process quality remains `NOT_EVALUATED`; P&L never becomes a decision-quality grade.
