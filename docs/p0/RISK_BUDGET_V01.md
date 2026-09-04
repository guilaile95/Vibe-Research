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
- Unknown well-formed version → `cap_evaluation=NOT_EVALUATED` /
  `POLICY_VERSION_NOT_AVAILABLE` (no implicit latest).

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

```text
NAV_BASIS_PRESERVED = YES
INTRADAY_TO_SETTLED_FALLBACK = NO
```

### Formal-cap eligibility (v0.1)

| `nav_basis` | Formal Risk Allowed Cap |
| --- | --- |
| `OFFICIAL_SETTLED` | Eligible for `EVALUATED` (when policy is known) |
| `ESTIMATED_INTRADAY` | Recognized input; formal cap **unavailable** in RB1 v0.1 |

`ESTIMATED_INTRADAY` is syntactically valid, not illegal. It is Best-Effort
intraday risk perception and cannot form a formal evaluated cap until a
future **Intraday NAV Quality Envelope** exists (Coverage, Freshness,
Confidence).

```text
nav_basis = ESTIMATED_INTRADAY
→ cap_evaluation = NOT_EVALUATED
→ risk_allowed_cap_notional = None
→ risk_allowed_cap_nav_ratio = None
→ reason_codes includes INTRADAY_NAV_QUALITY_NOT_PROVEN
```

Do not raise ERROR. Do not rewrite basis to `OFFICIAL_SETTLED`. Do not
read another NAV. Do not invent Coverage / Freshness / Confidence.

```text
RUNTIME_INTRADAY_NAV_QUALITY = OUT_OF_SCOPE
INTRADAY_NAV_QUALITY_ENGINE_IMPLEMENTED = NO
```

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

Decimal arithmetic under frozen v0.1 numeric context
(`DETERMINISTIC FIXED-CONTEXT DECIMAL PROJECTION`).

```text
NUMERIC_CONTEXT = FROZEN_V0.1
NUMERIC_CONTEXT_VERSION = rb.numeric.v0.1
NUMERIC_PRECISION = 50
NUMERIC_ROUNDING = ROUND_HALF_EVEN
GLOBAL_DECIMAL_CONTEXT_DEPENDENCE = NO
HIDDEN_MONEY_ROUNDING = NO
MATHEMATICALLY_EXACT_INFINITE_DECIMAL_CLAIM = NO
```

- All non-terminating projections (`risk_allowed_cap_notional`,
  `risk_allowed_cap_nav_ratio`) run inside
  `localcontext(RISK_BUDGET_DECIMAL_CONTEXT)`.
- The core must not call `getcontext()`, must not mutate process-global
  Decimal state, must not use default precision=28, must not adapt
  precision to input length, must not `quantize` to cents, must not
  convert through `float`, and must not use `round()`.
- Risk Allowed Cap is not a payment amount; do not impose a money-cents
  contract.
- Output ratios/notionals as canonical non-scientific decimal strings.

Non-terminating examples (`0.06`, `0.12`, `0.15` as divisors) are
deterministic under this context, not mathematically exact infinite
decimals.

## Evaluation precedence

1. Validate structural input (illegal → `RiskBudgetValidationError`).
2. Identify policy availability.
3. Identify NAV eligibility.

Unknown well-formed `policy_version` → `POLICY_VERSION_NOT_AVAILABLE`.
`ESTIMATED_INTRADAY` → `INTRADAY_NAV_QUALITY_NOT_PROVEN`.
Both gaps may appear together in `reason_codes`. Never fake-choose latest
policy.

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
