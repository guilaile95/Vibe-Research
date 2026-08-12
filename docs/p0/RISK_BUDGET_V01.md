# P0-RB1 Risk Budget & Risk Allowed Cap v0.1

## Product question

> For Security + Strategy + Campaign, given explicit Account NAV and explicit
> Entry-to-Invalidation Distance under a pinned Risk Budget Policy, what is the
> maximum risk capital this Campaign may expose?

```text
RISK ALLOWED CAP
=
risk constraint (notional capital)
```

Not BUY/SELL, Asset Optimal Position, Portfolio Adjusted Position, Recommended
Position, or Executable Quantity.

## Anti-rewheel

```text
EXISTING_FORMAL_RISK_BUDGET_AUTHORITY = NO
```

Related but non-equivalent surfaces:

| Surface | Why not RB authority |
| --- | --- |
| `account_execution_policy` | Account execution constraints (lot, cash reserve, single-stock allocation); not Campaign risk budget formula |
| `portfolio_advice_*` | AI advice + metrics; not formal Risk Allowed Cap |
| `top_risk_*` | Contextual risk analysis; not position-cap formula |
| North Star §7 | Product law only; no production core before RB1 |

## Decision unit

```text
Security + Strategy + Campaign
```

No security-wide cap broadcast.

## Versioned policy

```text
policy_version = rb.risk_budget.v0.1
policy_authority_ref = rb:risk_budget_policy:v0.1
```

- `policy_version` is **required** (no default / latest).
- `as_of` does **not** select policy version.
- Unknown well-formed version → `cap_evaluation=NOT_EVALUATED` (no implicit latest).

### v0.1 frozen table

| Strategy | risk_budget_ratio | policy_backstop_ratio |
| --- | --- | --- |
| SHORT | 0.0075 | 0.07 |
| SWING | 0.0100 | 0.12 |
| MEDIUM | 0.0125 | 0.20 |

Do not silent-mutate v0.1; calibration requires a new version.

## Formula

```text
risk_allowed_cap_notional
=
account_nav × risk_budget_ratio ÷ entry_to_invalidation_distance_ratio
```

Example:

```text
NAV=1_000_000, SWING budget=1%, distance=10%
→ Risk Allowed Cap = 100_000
```

## Entry-to-invalidation distance

- Explicit upstream input only.
- Must be `> 0`.
- Core does **not** invent stop from K-line / ATR / MA / thesis NLP / backstop.

```text
BACKSTOP != DEFAULT INVALIDATION DISTANCE
```

## Backstop

Independent policy fact. Output:

- `policy_backstop_ratio`
- `backstop_comparison`: `WITHIN_BACKSTOP` / `AT_BACKSTOP` / `BEYOND_BACKSTOP`

Rules:

- comparison only — no SELL/EXIT/REDUCE generation
- no silent replace of distance with backstop
- no silent alter of Risk Allowed Cap when beyond backstop

## Risk cap ≠ portfolio cap

If computed cap > Account NAV, retain **raw** cap.

```text
NO silent clamp to 100% NAV
```

`risk_allowed_cap_nav_ratio` is exposed for explainability only.

## NAV

- Upstream supplied only (no NAV engine).
- `nav_basis`: `OFFICIAL_SETTLED` | `ESTIMATED_INTRADAY`
- Estimated must not silently alias Official.

## Provenance

Evaluated formal cap requires:

- `nav_authority_refs` (non-empty)
- `invalidation_authority_refs` (non-empty)
- `policy_authority_ref` (when policy known)

```text
authority_refs = provenance witnesses
authority_refs != runtime binding verification

NAKED_SELF_ASSERTED_PROOF = REJECTED
UPSTREAM_AUTHORITY_REF_REQUIRED = YES
UPSTREAM_AUTHORITY_BINDING_VERIFIED = NO
RUNTIME_AUTHORITY_BINDING = OUT_OF_SCOPE
```

## Numeric discipline

- Exact `Decimal` arithmetic.
- No hidden cents rounding, no share-lot conversion.
- Output ratios/notionals as exact decimal strings (no scientific notation).

## Pure domain

`backend/risk_budget_projection.py`

- no I/O / AI / wall clock / persistence
- keyword-only `project_risk_budget(...)`

## Explicit non-goals

Sell Engine, BUY Engine, DI/CDA, Hard Risk, Material Change, Portfolio
Optimizer, Marginal Capital Allocation, Replacement Engine, Trade Execution,
Lot-size, Broker, Auto Trading, NAV engine, Drawdown engine, AI.

## Files

```text
backend/risk_budget_projection.py
backend/tests/test_risk_budget_projection.py
docs/p0/RISK_BUDGET_V01.md
```
