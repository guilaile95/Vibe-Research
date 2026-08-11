# Decision Assurance Coverage v0.1 (P0-RA1)

## Question

> For this Campaign, were the required decision dimensions actually evaluated?

## Non-goals

Does **not** answer safety, Hard Risk content, Material Change content, BUY/SELL, or Inbox visible state.

```text
COVERAGE != SAFETY
```

## Authority

```text
backend/decision_assurance_projection.py
```

Pure domain only. Consumes normalized evaluation statuses; no I/O and no domain reimplementation.

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
EVALUATED      = authority ran and produced a legal result (any severity)
UNKNOWN        = authority ran but could not adjudicate
NOT_EVALUATED  = not run / not wired / capability missing
ERROR          = integrity / corruption / unexpected failure on eval path
```

```text
UNKNOWN != NOT_EVALUATED
ERROR != UNKNOWN
```

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
