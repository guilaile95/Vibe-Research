# Formal Hard Risk Core v0.1

Status: HR1 pure authority implementation boundary.

## Scope

`backend/hard_risk_runtime.py` evaluates one explicit `Security + Strategy +
Campaign + as_of` unit and returns the frozen contract from
`backend/hard_risk_contract.py`:

```text
CLEAR | CONFIRMED | UNKNOWN | NOT_EVALUATED
```

The function is pure. It does not read a Campaign, call a provider, inspect a
score, use a clock, invoke AI, persist data, or emit an investment action.

`campaign_id` is only the locator. The backend Campaign record is authoritative
for `security_code` and `strategy`; every accepted authority envelope must
repeat and match all three values and the exact caller-supplied UTC `as_of`.

## Proof boundary

The input envelopes are runtime composition inputs, not a new persisted schema.

`formal_thesis_projection` wraps the existing
`formal_thesis_projection_core` result with scope, `as_of`, and
`authority_refs`. A `READY` terminal projection (`DISPROVEN` or `INVALIDATED`)
is a high-severity positive proof of the Hard Risk type
`THESIS_CORE_FACT`; a stable/non-terminal projection is not a clear proof.

`hard_risk_proofs` accepts an already normalized proof from a formal upstream
authority. `CONFIRMED` requires:

- `hard_risk_evaluation = EVALUATED`;
- `severity = HIGH` or `CRITICAL`;
- `positive_proof = true`; and
- non-empty `authority_refs` and `reason_codes`.

`CLEAR` requires an explicit positive proof plus
`coverage = [ALL_IMPLEMENTED_HARD_RISK_CHECKS]`. Empty data, “no finding”,
usable Critical Data, normal Data Health, or a stable Thesis cannot satisfy
this condition.

Missing/unwired authority is `NOT_EVALUATED`. An authority that ran but is
ambiguous is `UNKNOWN`; an explicit authority error remains
`UNKNOWN + ERROR` on the evaluation axis. Conflicting duplicate proofs and
confirmed-vs-clear proofs fail closed to `UNKNOWN`; mismatched Campaign or
`as_of` inputs are rejected from the candidate set and cannot create a clean
result.

## Anti-rewheel boundary

The core reuses the existing Hard Risk contract, Campaign identity shape,
Current Thesis projection state, UTC temporal convention, and provenance
(`authority_refs`) pattern. Existing Critical Data, Data Health, disclosures,
financials, security exchange routing, raw eligibility/special-status facts,
and `top_risk_*` values remain inputs/context only. In particular, score,
weighted score, crowding, runup, valuation thresholds, and shadow signals are
not Hard Risk authority.

The repository currently lacks formal high-severity eligibility, going-concern,
financial-authenticity, regulatory, and all-clear classifiers. HR1 therefore
does not invent those rules: callers without a positive formal authority proof
remain `UNKNOWN` or `NOT_EVALUATED`.
