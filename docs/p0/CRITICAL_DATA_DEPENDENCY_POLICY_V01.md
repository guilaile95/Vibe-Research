# Critical Data Dependency Policy v0.1 (P0-DDA1)

## Question

> For this Security + Strategy + Campaign, given an explicitly pinned
> dependency-policy version, what Strategy-baseline critical-data
> capabilities are required?

## Authority

```text
backend/critical_data_dependency_policy.py
```

```text
DDA1 =
STRATEGY BASELINE DEPENDENCY DEFINITION AUTHORITY
```

Pure domain only. No I/O. No provider / Fact Lake / Data Health / CCD / RA / DI imports.

## Scope

```text
CRITICAL_DATA_SCOPE_V01 =
STRATEGY_BASELINE_CRITICAL_CONTEXT
```

```text
BASELINE CRITICAL DATA
!=
ALL DATA NEEDED BY THIS CAMPAIGN
```

Does **not** own:

- Campaign-specific catalyst requirements
- Thesis-specific evidence requirements
- Material Change condition-specific facts
- Hard Risk adjudication
- generic Evidence completeness
- capability usability evaluation

## Policy version

```text
POLICY_VERSION = dda.strategy_dependency.v0.1
```

`policy_version` is a **required** input.

Forbidden:

```text
default current
latest
implicit active
wall-clock policy selection
as_of policy selection
```

### Version semantics

| Condition | Result |
|---|---|
| missing / empty `policy_version` | `DependencyPolicyValidationError` |
| unknown non-empty `policy_version` | `dependency_set_state = NOT_EVALUATED` + empty required set |
| known version integrity failure | `dependency_set_state = ERROR` + empty required set |
| success | `dependency_set_state = RESOLVED` |

```text
UNKNOWN_USED_BY_V01 = NO
AS_OF_SELECTS_POLICY = NO
```

`as_of` only binds the declaration for same-as_of downstream composition with CCD1.

## Capability IDs (v0.1)

```text
cap.security.price_reference
cap.context.market_sector
cap.security.disclosures
cap.security.financials
```

Provider-independent. Dataset-independent. Exact string identity.

### Semantics

- `cap.security.price_reference` — security price reference applicable to supplied as_of; DDA does not choose quote vs close or judge freshness.
- `cap.context.market_sector` — composite market + sector regime context for SHORT/SWING baseline interpretation; DDA does not combine sources.
- `cap.security.disclosures` — availability of authoritative disclosure/announcement facts for baseline corporate-event awareness; no Material Change / Hard Risk classification.
- `cap.security.financials` — structured financial/fundamental facts for MEDIUM baseline completeness.

## Required sets

Policy order is the contract (not alphabetical):

```text
SHORT =
cap.security.price_reference
cap.context.market_sector
cap.security.disclosures

SWING =
cap.security.price_reference
cap.context.market_sector
cap.security.disclosures

MEDIUM =
cap.security.price_reference
cap.security.disclosures
cap.security.financials
```

```text
EMPTY_SET_ALLOWED_BY_DDA_V01 = NO
```

## Authority provenance

On success:

```text
dependency_set_authority_refs =
("dda:strategy_dependency_policy:v0.1",)
```

Generated internally by DDA1. Caller cannot inject authority refs.

```text
CALLER_CANNOT_SELF_ASSERT_DDA_PROVENANCE = YES
```

## Output

```text
schema_version
security_code
strategy
campaign_id
as_of
policy_version
dependency_set_state
dependency_set_authority_refs
required_dependency_ids
reason_codes
```

CCD1-compatible:

```text
NOT_EVALUATED / ERROR → required_dependency_ids empty
RESOLVED → exact required set + non-empty authority refs
```

## Authority chain

```text
DDA1 → required capability set
adapter (future) → normalized per-dependency usability evidence
CCD1 → campaign critical data state/evaluation
RA1 → coverage meta
DI → visible state
```
