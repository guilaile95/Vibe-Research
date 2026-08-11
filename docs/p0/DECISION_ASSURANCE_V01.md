# Decision Assurance Coverage v0.1 (P0-RA1)

## Question

> For this Campaign, were the required decision dimensions actually evaluated?

## Non-goals

Does **not** answer safety, Hard Risk content, Material Change content, or
investment recommendation generation.

```text
COVERAGE != SAFETY
```

## Authority

```text
backend/decision_assurance_projection.py
```

Pure domain only. Consumes normalized evaluation statuses; no I/O and no domain
reimplementation.

## Required dimensions (v0.1)

```text
FORMAL_THESIS
FORMAL_DECISION
HARD_RISK
MATERIAL_CHANGE
CRITICAL_DATA
```

## Evaluation states

```text
EVALUATED      = authority ran for as_of and produced a legal result (any severity)
UNKNOWN        = authority ran for as_of but could not adjudicate
NOT_EVALUATED  = not run / not wired / capability missing / cannot prove applicability
ERROR          = integrity / corruption / unexpected failure on eval path
```

```text
UNKNOWN != NOT_EVALUATED
ERROR != UNKNOWN
```

## Same-as_of temporal applicability (R1 freeze)

All five evaluation statuses must be normalized by the **caller** against the
**same** supplied `as_of` and must remain **semantically applicable at that
instant**.

```text
evaluation status applicable AS OF supplied as_of
```

Not:

```text
“authority historically ran at some other time”
```

Forbidden false-coverage pattern:

```text
Hard Risk last ran 3 days ago
→ HARD_RISK = EVALUATED at as_of = T
→ coverage_complete = true
```

unless the caller can prove the result is still applicable at `T`.

RA1 does **not** implement domain TTL / freshness. That remains adapter policy.

## as_of canonical UTC contract (R1)

`as_of` must be an explicit UTC **zero-offset** instant string.

Accepted forms:

```text
2026-08-12T00:00:00Z
2026-08-12T00:00:00.000000Z
2026-08-12T00:00:00+00:00
2026-08-12T00:00:00.000000+00:00
```

Rejected:

```text
date-only
naive local datetime
non-zero offsets (including +08:00) without prior caller normalization
arbitrary text / empty / whitespace-padded
```

No silent timezone conversion inside RA1. Exact accepted string is preserved.

## coverage_complete

```text
true
iff all five dimensions are EVALUATED or UNKNOWN
```

`UNKNOWN` counts as completed coverage but remains in `unknown_dimensions`.

`NOT_EVALUATED` and `ERROR` make coverage incomplete.

## Consumers

Decision Inbox (or other orchestrators) combine:

```text
coverage_complete
+ domain states from real authorities
```

RA1 never emits `NO_ACTION_REQUIRED` / SAFE / CLEAR / BUY / SELL.
