# P0-DC1 Decision Domain v0.1

## Authority inventory

| Authority | DC1 use | Boundary |
| --- | --- | --- |
| `formal_current_thesis.projection.v0.1` | Current Thesis semantic delta and exact Thesis identity | `DISPROVEN` / `INVALIDATED` are terminal; `WEAKENED` creates review pressure but never an automatic `REDUCE` / `EXIT` |
| `decision_evidence_delta.v0.1` | `effective_at` relation to the Frozen Decision boundary | `NEW_AFTER_DECISION` is temporal only; retrieval time is not used |
| `hard_risk_runtime.v0.1` | validated Hard Risk result | `CONFIRMED` creates review pressure and narrows the action envelope; it cannot prove a Material Change or mechanically emit `EXIT` |
| `material_change.projection.v0.1` | independent RA1 material-change result | `CONFIRMED` requires a semantic Thesis delta plus EC1 `NEW_AFTER_DECISION` support |
| `frozen_decision_store.NEXT_BEST_ACTIONS` | Proposal NBA vocabulary | Proposal remains `UNCOMMITTED`; Formal Decision evaluation and commit belong to O / Frozen Decision service |

## Material Change boundary

`project_material_change` consumes a typed `DecisionEvidenceDelta`, the named
Current Thesis envelope, and a `HardRiskEvaluation`. It has no generic
`material_change_state`, severity, or caller-declared conclusion input.

Material Change is `CONFIRMED` only when all of the following hold:

1. Current Thesis has a semantic `WEAKENED`, `DISPROVEN`, or `INVALIDATED`
   delta;
2. the delta is effective after the decision boundary; and
3. EC1 independently reports `NEW_AFTER_DECISION`.

`STABLE` and `STRENGTHENED` are never material merely because evidence is new.
`NEW_AFTER_DECISION` alone is `UNKNOWN`. Pre-existing or temporally unknown
evidence cannot prove a decision-after change. Hard Risk `CONFIRMED` remains
an independent risk fact and returns Material Change `UNKNOWN` when the
after-decision proof is absent; it is available to Proposal and Action
Envelope consumers as risk context, not as temporal materiality proof.

## Production Sell Engine boundary

`project_sell_engine` accepts only three implemented authority results:

* Current Thesis;
* Hard Risk; and
* Material Change.

The seven legacy sell dimensions (`risk_exit`, `expectation_price_in`,
`risk_reward`, `catalyst`, `portfolio_rebalance`, `opportunity_cost`, and
`technical_execution`) are not public function inputs and have no
caller-constructible authority dataclasses. They remain output diagnostics with
`source_contract = NOT_IMPLEMENTED` and `evaluation = NOT_EVALUATED` so that
missing producers cannot be mistaken for positive proof.

Production v0.1 therefore supports these conclusions:

* terminal Current Thesis -> `THESIS_INVALIDATED`;
* Hard Risk `CONFIRMED` -> `WATCH_TO_REDUCE` review pressure only;
* Thesis `WEAKENED` or Material Change `CONFIRMED` -> review pressure only;
* missing legacy dimensions -> `NOT_EVALUATED`.

Production v0.1 cannot prove a positive `HOLD`, and it cannot generate
production `REDUCE` or generic `EXIT` from unimplemented producers. `HOLD`,
`REDUCE`, and generic `EXIT` remain Frozen NBA vocabulary for future contracts.

## Proposal boundary

`project_decision_proposal` consumes typed Current Thesis, Hard Risk, Material
Change, and Sell Engine results plus three independent JSON view payloads. The
top-level `constraint_evaluation` means only that these constraint authorities
were evaluated; it is not Formal Decision evaluation. There is deliberately no
`proposal_evaluation` or `formal_decision_evaluation` field.

`asset_view`, `trade_view`, and `portfolio_view` are independent
`PROPOSED VIEW CONTENT`, not formal authority results. Each output carries a
separate `view_provenance` entry. The current caller-supplied boundary is
marked `view_origin = USER_DRAFT` with empty provenance references; a future
producer may use `MODEL_PROPOSAL` or `DETERMINISTIC_PROPOSAL` through an
explicit adapter.

The Proposal always returns `proposal_status = UNCOMMITTED`, preserves the
literal `as_of`, keeps identity fields exact, and never creates
`decision_id`, `committed_at`, `snapshot_hash`, broker, order, or Formal
Decision fields. User confirmation, frozen-decision commit, committed-record
reread, and same-`as_of` applicability belong to the later O lane.

## Fixtures and limitations

Fixtures explicitly carry `fixture_scope`:

* `PRODUCTION_SUPPORTED`: Hard Risk watch pressure, terminal Thesis, valid
  after-decision Material Change review, `UNKNOWN`, and `NOT_EVALUATED` cases;
* `FUTURE_CONTRACT_ONLY`: clean `HOLD`, generic `REDUCE`, and generic `EXIT`.

DC1 does not implement producers for the seven legacy dimensions, an all-clear
positive action authority, DB/runtime/API wiring, user confirmation, Frozen
Decision commit, frontend, browser E2E, or AI. No future producer is smuggled
into this correction as a registry, token, signature, or allowlist.
