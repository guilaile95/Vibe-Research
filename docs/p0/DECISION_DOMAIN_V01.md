# P0-DC1 Decision Domain v0.1

## Authority inventory

| Authority | DC1 use | Boundary |
| --- | --- | --- |
| `formal_current_thesis.projection.v0.1` | Current Thesis semantic delta and exact Thesis identity | `DISPROVEN` / `INVALIDATED` are terminal; `WEAKENED` is a review-worthy change but never an automatic `REDUCE` / `EXIT` |
| `decision_evidence_delta.v0.1` | `effective_at` relation to the Frozen Decision boundary | `NEW_AFTER_DECISION` is temporal only; retrieval time is not used |
| `hard_risk_runtime.v0.1` | validated Hard Risk result | `CONFIRMED` narrows actions and creates sell-side review pressure; it does not mechanically emit `EXIT` |
| `frozen_decision_store.NEXT_BEST_ACTIONS` | Proposal NBA vocabulary | Proposal remains `UNCOMMITTED`; commit identity belongs to O / Frozen Decision service |

## Input / output contract

`project_material_change` consumes a typed `DecisionEvidenceDelta`, the named
Current Thesis envelope, and a `HardRiskEvaluation`. It has no generic
`material_change_state`, severity, or positive-proof input.

Material Change is `CONFIRMED` only for a named Current Thesis `WEAKENED` or
terminal delta with `NEW_AFTER_DECISION` temporal support, or a validated Hard
Risk `CONFIRMED` result. A new evidence bucket without either semantic
authority is `UNKNOWN`; a pre-existing bucket cannot create a decision-after
change; a Thesis delta whose EC1 relation is pre-existing/absent is kept
`UNKNOWN`; unknown temporal relation fails closed. Terminal Thesis and Hard
Risk are one review conclusion, not additive severity.

`project_sell_engine` preserves the #107 states and reason categories. The
legacy naked pressure mapping is replaced by distinct named adapter contracts
(`RiskExitAuthority`, `ExpectationPriceInAuthority`, `RiskRewardAuthority`,
`CatalystAuthority`, `PortfolioRebalanceAuthority`, `OpportunityCostAuthority`,
and `TechnicalExecutionAuthority`). A missing adapter is `NOT_EVALUATED`; a
plain mapping cannot declare `WATCH`, `REDUCE`, or `EXIT`.

`project_decision_proposal` consumes typed Material Change, Hard Risk, Sell
Engine, and Current Thesis results plus three independent view payloads. It
returns:

* `proposal_status = UNCOMMITTED`;
* exact `security_code / strategy / campaign_id / thesis_id / thesis_revision / as_of`;
* independent `asset_view`, `trade_view`, and `portfolio_view`;
* the existing Frozen Decision NBA vocabulary; and
* a deterministic Action Envelope with allowed / blocked actions and
  maintain / upgrade / downgrade / invalidation conditions.

`UNKNOWN`, `NOT_EVALUATED`, and `ERROR` only narrow the envelope. No Proposal
output contains `decision_id`, `committed_at`, `snapshot_hash`, broker, or
order fields.

## Known limitations

DC1 does not implement producers for expectation/price-in, risk-reward,
catalyst, portfolio-rebalance, opportunity-cost, or technical-execution
authority. The named adapter types are composition contracts only; they are not
a registry or a source of facts. DC1 also does not create an all-clear Hard
Risk authority or any positive BUY authority. DB, runtime/API wiring, user
confirmation, Frozen Decision commit, frontend, browser E2E, and AI remain
outside this lane.
