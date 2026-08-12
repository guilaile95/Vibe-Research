# Campaign Critical Data Usability Projection v0.1 (P0-CCD1)

## Question

> Given an explicitly resolved required dependency set for
> Security + Strategy + Campaign, and normalized per-dependency evaluation
> results applicable at the same `as_of`, what is this Campaign's Critical
> Data usability?

## Authority

```text
backend/campaign_critical_data_projection.py
```

Pure domain only. No I/O. No provider / Fact Lake / Data Health imports.

## New decision information

```text
dataset/source health facts
  → campaign-specific required dependency evaluation
  → campaign-level decision usability
```

```text
GLOBAL DATA HEALTH
!=
CAMPAIGN CRITICAL DATA USABILITY
```

## Non-goals

- Does **not** define which dependencies a strategy should require
- Does **not** persist dependency sets
- Does **not** collect provider / Fact Lake health
- Does **not** implement Decision Inbox precedence
- Does **not** reimplement RA1 coverage
- Does **not** classify Hard Risk / Material Change
- Does **not** invent investment requirements from available data

## Dependency definition authority

```text
DEPENDENCY_DEFINITION_AUTHORITY = UPSTREAM / EXPLICIT INPUT ONLY
```

CCD1 accepts a normalized dependency-set input. It must not infer required
dependencies from strategy, thesis, holdings, or available datasets.

## Dependency set states

```text
RESOLVED
UNKNOWN
NOT_EVALUATED
ERROR
```

```text
UNKNOWN != NOT_EVALUATED
ERROR != UNKNOWN
```

### RESOLVED requires authority provenance

Any:

```text
dependency_set_state == RESOLVED
```

must include at least one valid `dependency_set_authority_refs` entry.

This applies to:

```text
RESOLVED + empty required set
RESOLVED + non-empty required set
```

Empty refs for `RESOLVED` is integrity failure (`CriticalDataIntegrityError`),
not business `UNKNOWN` / `NOT_EVALUATED`, and never silent `USABLE`.

Non-`RESOLVED` set states (`UNKNOWN` / `NOT_EVALUATED` / `ERROR`) do **not**
require authority refs in v0.1; `NOT_EVALUATED` may legitimately mean the
dependency authority is missing or unwired.

### Authoritative empty set

`RESOLVED + required_dependencies = ()` is legal only with non-empty
`dependency_set_authority_refs`.

Result:

```text
critical_data_state = USABLE
critical_data_evaluation = EVALUATED
reason = DEPENDENCY_SET_AUTHORITATIVELY_EMPTY
```

## Per-dependency result states

```text
USABLE
BLOCKED
STALE
UNKNOWN
NOT_EVALUATED
ERROR
```

These are already-normalized Campaign-dependency evidence. Future adapters map
H1 / Data Health outputs into this enum. CCD1 does not own
`H1.USABLE_WITH_WARNING` policy.

## Same-as_of contract

Top-level `as_of = T`. Every dependency result `as_of` must equal `T`.

No wall clock. No TTL invention. No mixed historical evaluation times.

## Domain aggregation (DI-facing)

For a `RESOLVED` set:

```text
BLOCKED > STALE > UNKNOWN > USABLE
```

`NOT_EVALUATED` / `ERROR` dependency results collapse to DI `UNKNOWN`.

DI still consumes only:

```text
USABLE / BLOCKED / UNKNOWN / STALE
```

## Evaluation aggregation (RA1-facing)

```text
ERROR > NOT_EVALUATED > UNKNOWN > EVALUATED
```

Completed evaluation path includes:

```text
USABLE  + EVALUATED
BLOCKED + EVALUATED
STALE   + EVALUATED
```

```text
COVERAGE != SAFETY
```

Legal mixed example:

```text
critical_data_state = BLOCKED
critical_data_evaluation = ERROR
```

## Exact cover

When `dependency_set_state = RESOLVED`, dependency results must exactly cover
required IDs: no missing, extra, or duplicate IDs. Missing is integrity failure,
not business `UNKNOWN`.

## Identity

```text
Security + Strategy + Campaign
```

No security-only aggregation. Same security with different strategy/campaign
must evaluate independently.

## Outputs

```text
schema_version
security_code
strategy
campaign_id
as_of
dependency_set_state
dependency_set_authority_refs
required_dependency_ids
dependency_results
critical_data_state
critical_data_evaluation
reason_codes
authority_refs
```

Reasons are cumulative and deterministically ordered.
