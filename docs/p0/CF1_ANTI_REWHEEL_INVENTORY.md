# P0-CF1 Anti-Rewheel Inventory

Base: `6708f9b96fdc8c999ea559409adb254020a195fc`

Branch: `feat/p0-cf1-counterfactual-price-path-v0.1`

Issue: `#144 — PIT Price Point Authority & Counterfactual Outcome Activation`

## Existing authorities to reuse

| Concern | Existing authority | CF1 action |
| --- | --- | --- |
| Completed A-share session boundary | `backend/trade_calendar.py` / `completed_trade_date_at` | Reuse for both explicit `start_as_of` and `evaluation_as_of`; no wall clock or invented session date. |
| Security exchange routing | `backend/security_exchange_policy.py` / `resolve_security_exchange` | Reuse SSE/SZSE routing; unresolved/BSE unsupported paths remain `NOT_EVALUATED`. |
| Fact Lake publication metadata and immutable artifact verification | `backend/fact_lake_store.py` | Read-only access through public Fact Lake APIs only. |
| Canonical publication selection semantics | `backend/fact_lake_publication_selection.py` | Reuse exact-coordinate filtering and its explicit no-provider-revision/no-PIT claims; do not use local vintage order as a winner. |
| Publication health | `backend/fact_lake_health.py` + `backend/fact_lake_health_adapter.py` | Reuse replay, artifact, raw, quality, reconciliation and admissibility evidence. Blocked health is an error; non-usable health remains non-evaluated. |
| Tushare daily canonical route | `backend/tushare_daily_shadow.py` | Reuse the existing canonical daily dataset, normalization replay, publication read and `close` payload. No new provider or network call. |
| Existing CCD price capability | `backend/critical_data_price_reference_adapter.py` | Extract the truth-producing price-point chain where practical. Preserve its outward capability schema and state semantics. |
| Frozen Decision authority | `backend/frozen_decision_store.py` / `backend/frozen_decision_service.py` and OL1 witness/hash | Derive `start_as_of` only from verified `FrozenDecision.committed_at`. Replay envelope remains snapshot-only. |
| OL1 outcome projection/runtime/API/UI | `backend/formal_decision_outcome.py`, `backend/formal_decision_outcome_runtime.py`, `backend/formal_decision_outcome_router.py`, `frontend/src/components/outcome/FormalOutcomeSection.tsx` | Reuse OL1 two-pass boundary, exact actual-trade semantics, reveal hashing, API and Formal Outcome section; add only counterfactual price-path detail. |

## Current gap and CF1 boundary

`critical_data_price_reference_adapter.evaluate_price_reference_capability` currently
proves only a CCD capability result. It already composes the required chain but
does not expose a price, completed trade date, publication identity, or observation
provenance. `fact_lake_publication_selection` explicitly rejects `as_of` selection
and declares that local vintage order is not provider revision or PIT truth.

CF1 therefore needs one neutral read-only primitive that:

1. validates canonical UTC `as_of` and resolved SSE/SZSE identity;
2. obtains the completed session from `completed_trade_date_at(as_of)`;
3. loads all exact-coordinate committed canonical publications;
4. loads each source observation and filters visibility by `fetched_at <= as_of` before
   any selection decision;
5. returns `NOT_EVALUATED` when no visible publication exists or more than one visible
   publication remains, because no formal provider-revision winner exists;
6. reuses the existing Tushare replay, health, canonical artifact and exact security-row
   close validation; and
7. returns the close plus complete point/provenance authority references.

The primitive must not call a provider, write Fact Lake, use mtime/current time,
select latest-wins, or claim that a later historical backfill was known earlier.

## OL1 integration boundary

- `start_as_of = FrozenDecision.committed_at`.
- `end_as_of = OL1 evaluation_as_of`.
- Both price points belong to Outcome Reveal / Counterfactual only; they must not be
  added to `decision_time_replay` or its hash.
- The metric is only `SECURITY_CLOSE_TO_CLOSE_RETURN = end_close / start_close - 1`,
  computed with deterministic Decimal arithmetic.
- No quantity, weight, capital, fill, slippage, execution-quality or decision-quality
  field is introduced.
- If the end completed trade date is not strictly after the start date, return
  `NOT_EVALUATED / NO_POST_DECISION_COMPLETED_SESSION`; never emit fake zero return.
- Actual Capital Outcome continues to use OL1/TAR1/Trade Ledger authority and is
  independent of the security path.

## Required regression protection

The inventory requires targeted tests for future-fetched observations, late backfill,
ambiguous visible publications, missing/duplicate/invalid security rows, health and
replay failures, unresolved exchange, missing session, non-forward end date, caller
injection, replay-hash stability, actual/counterfactual independence, legacy analytics
non-authority, Fact Lake corruption, and unchanged CCD adapter output.

No new market-data provider, schema, accounting engine, portfolio hypothetical P&L,
strategy horizon parser, AI score, Thesis mutation, broker integration, Home/Mobile
redesign, or security redesign is in scope.
