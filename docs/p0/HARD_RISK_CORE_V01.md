# Formal Hard Risk Core v0.1

Status: HR1 correction — named Current Thesis authority only.

## Supported formal authority

HR1 v0.1 accepts one input authority:

```text
formal_current_thesis.projection.v0.1
```

The runtime receives an explicit Current Thesis authority envelope together
with the backend Campaign record and a literal UTC `as_of`. The envelope must
carry:

- the exact `campaign_id`, `security_code`, and `strategy` scope;
- the exact literal `as_of` used for the evaluation;
- non-empty `authority_refs` provenance; and
- the existing Current Thesis `projection` payload.

`campaign_id` is only a locator. The backend Campaign record is authoritative
for `security_code` and `strategy`; caller-supplied envelope identity cannot
override it.

## v0.1 derivation

```text
formal_status = READY
terminal = true
effective_state = DISPROVEN
    -> CONFIRMED + EVALUATED

formal_status = READY
terminal = true
effective_state = INVALIDATED
    -> CONFIRMED + EVALUATED
```

The corresponding Thesis reason code and authority provenance are retained in
the output. Terminal facts, schema, identity, UTC scope, and lookahead checks
are all validated before confirmation.

Valid non-terminal Thesis states (`STABLE`, `STRENGTHENED`, `WEAKENED`) mean
that the Current Thesis authority ran, but they do not prove trading
eligibility, solvency, financial authenticity, regulatory safety, or data
integrity. They therefore return `UNKNOWN`, never `CLEAR`.

An `UNKNOWN` projection returns `UNKNOWN`. A missing or not-ready Thesis
authority returns `NOT_EVALUATED`. Scope mismatch, literal `as_of` mismatch,
lookahead, terminal-flag inconsistency, bad schema, and missing provenance fail
closed and cannot produce a clean result.

## CLEAR boundary

HR1 v0.1 production produces no `CLEAR` result. The shared contract keeps the
`CLEAR` enum for cross-lane compatibility and future semantics, but this core
has no all-clear authority and no input path that can synthesize one.

## Not yet authoritative

The following remain outside HR1 v0.1 because the repository does not yet have
named deterministic classifiers that can prove them:

- trading eligibility / special status;
- going concern / solvency;
- financial authenticity;
- core-business regulatory risk;
- data integrity / availability as a Hard Risk classification;
- top-risk scores and technical signals;
- raw disclosures or financial retrieval results.

They do not enter this evaluator as context or as caller-declared conclusions.
When a future classifier is genuinely implemented, it must add its own named
deterministic domain adapter and derive Hard Risk from domain facts; HR1 v0.1
does not reserve a generic proof or registry path for it.

## Pure boundary

`backend/hard_risk_runtime.py` has no I/O, database, filesystem, provider,
AI, randomness, or wall-clock dependency. It returns the frozen
`HardRiskEvaluation` contract or its detached `to_dict()` mapping and never
emits an investment action.
