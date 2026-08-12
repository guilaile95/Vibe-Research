# P0-DC1 Decision Challenge Coverage Authority v0.1

## Product question

> For a Security + Strategy + Campaign Formal Decision, if upstream already
> requires a Decision Challenge, are the four required counter-evidence
> dimensions actually evaluated, and is Two-Pass Review structurally present?

```text
CHALLENGE COVERAGE
!=
DECISION CORRECTNESS
!=
DECISION APPROVAL
```

## Anti-rewheel

```text
EXISTING_FORMAL_DECISION_CHALLENGE_AUTHORITY = NO
```

Related but non-equivalent surfaces on live stable:

| Surface | Why not DC authority |
| --- | --- |
| North Star §16 | Product law only |
| RA1 `decision_assurance_projection` | Coverage of thesis/decision/hard-risk/material-change/critical-data; no challenge packet |
| EC1 `decision_evidence_delta_projection` | Temporal newness of evidence; not strongest/opposing/pre-mortem |
| Frozen Decision ledger | Identity + snapshot persistence; no challenge completeness |
| Decision Inbox / Formal Thesis / Outcome | Other decision axes |

## Formal Decision identity

Reused from stable `frozen_decision_store` contract (regex copied; store not imported):

```text
security_code = 6-digit A-share
strategy      = SHORT | SWING | MEDIUM
campaign_id   = campaign_<32 lowercase hex>
decision_id   = decision_<32 lowercase hex>
```

```text
FORMAL_DECISION_IDENTITY_SOURCE = frozen_decision_store contract
```

## Challenge requirement

DC1 does **not** decide importance or infer REQUIRED from BUY/SELL.

```text
CHALLENGE_REQUIREMENT_SOURCE = EXPLICIT_UPSTREAM_INPUT
DC1_DECIDES_IMPORTANCE = NO
```

| Upstream `challenge_requirement` | Packet |
| --- | --- |
| `REQUIRED` | Evaluate four dimensions + Two-Pass structure |
| `NOT_REQUIRED` | `NOT_APPLICABLE` (requirement authority refs still required) |
| `UNKNOWN` | `INCOMPLETE` / `UNKNOWN` — never `NOT_APPLICABLE` |
| `NOT_EVALUATED` | `INCOMPLETE` / `NOT_EVALUATED` — never `NOT_APPLICABLE` |
| `ERROR` | `INCOMPLETE` / `ERROR` — never `NOT_APPLICABLE` |

## Four required dimensions

When `REQUIRED`:

1. `STRONGEST_SUPPORTING_EVIDENCE`
2. `STRONGEST_OPPOSING_EVIDENCE`
3. `PRE_MORTEM`
4. `INVALIDATION_FACTS`

```text
STRONGEST_EVIDENCE_SELECTION_OWNED_BY_DC1 = NO
STRONGEST_SELECTION_BINDING_VERIFIED = NO
UPSTREAM_SELECTION_WITNESS_PRESENT = YES  (authority_refs)
```

`EVALUATED` / `UNKNOWN` dimensions must carry non-empty `authority_refs`.
Naked self-asserted EVALUATED is rejected.

```text
UNKNOWN counts as dimension coverage
UNKNOWN != NOT_EVALUATED
UNKNOWN_EQUALS_POSITIVE_EVIDENCE = NO
```

## Two-Pass structure

When challenge is `REQUIRED`, consume:

- `first_pass_ref` / `first_pass_at`
- `second_pass_ref` / `second_pass_at`

Rules:

- refs must be distinct
- `first_pass_at <= second_pass_at <= as_of`
- UTC zero-offset only; no wall clock

```text
TWO_PASS_STRUCTURE_VERIFIED = YES   (when state = VALID)
TWO_PASS_SEMANTIC_INDEPENDENCE_VERIFIED = NO
```

Stable Formal Decision has no frozen review-purpose field. DC1 does not invent
a Review System. `second_pass_ref` is a structural witness only.

## Coverage result

| Condition | `challenge_packet_state` | `challenge_evaluation` |
| --- | --- | --- |
| REQUIRED + 4× EVALUATED + Two-Pass VALID | COMPLETE | EVALUATED |
| REQUIRED + all covered + ≥1 UNKNOWN + Two-Pass VALID | COMPLETE | UNKNOWN |
| REQUIRED + any NOT_EVALUATED | INCOMPLETE | NOT_EVALUATED |
| REQUIRED + any ERROR | INCOMPLETE | ERROR |
| REQUIRED + Two-Pass missing | INCOMPLETE | NOT_EVALUATED |
| NOT_REQUIRED | NOT_APPLICABLE | EVALUATED |
| Requirement UNKNOWN / NOT_EVALUATED / ERROR (known policy) | INCOMPLETE | preserved |
| Unknown well-formed policy | INCOMPLETE | NOT_EVALUATED |

COMPLETE means structurally covered, not safe / correct / approved.

Reasons accumulate. Policy version is explicit
(`dc.decision_challenge.v0.1`); no implicit latest.

## Unknown policy (no v0.1 packet fallback)

Policy-independent validation only: identity, `as_of`, `policy_version`
syntax, `challenge_requirement` enum, requirement authority refs.

If `policy_version` is well-formed but unknown:

```text
challenge_packet_state = INCOMPLETE
challenge_evaluation   = NOT_EVALUATED
policy_authority_ref   = None
POLICY_SEMANTICS_APPLIED = NO
```

Do **not** apply v0.1 four dimensions or Two-Pass structure. Optional
caller packet inputs are ignored for completeness. Never emit
`CHALLENGE_PACKET_COMPLETE` / `CHALLENGE_PACKET_COVERED_WITH_UNKNOWN`.
`explainability.required_dimensions` is `[]`.

`challenge_requirement` is preserved. Requirement reasons accumulate
(`CHALLENGE_REQUIREMENT_UNKNOWN` / `_NOT_EVALUATED` / `_ERROR`).
Unknown policy + `NOT_REQUIRED` is still `INCOMPLETE` / `NOT_EVALUATED`,
never `NOT_APPLICABLE`.

## Explicit non-goals

Decision importance, evidence truth / materiality / arbitration / strength,
pre-mortem generation, invalidation discovery, Action Envelope, Risk Budget,
Drawdown, Sell Engine, AI, persistence.

## Files

```text
backend/decision_challenge_projection.py
backend/tests/test_decision_challenge_projection.py
docs/p0/DECISION_CHALLENGE_V01.md
```
