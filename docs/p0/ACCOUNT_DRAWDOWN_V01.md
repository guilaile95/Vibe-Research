# P0-DD1 Account Drawdown State Core v0.1

## Product question

> Given an upstream-proven current Account NAV and recent NAV Peak, what
> is the current account drawdown, and which North-Star Drawdown State
> does it belong to?

```text
DRAWDOWN STATE
=
PORTFOLIO RISK CONTEXT
!=
INVESTMENT ACTION
```

Not BUY/SELL/HOLD/REDUCE/EXIT, Action Envelope, Risk Budget mutation,
position sizing, Asset View, Trade View, or NAV / Peak engine.

## Anti-rewheel

```text
EXISTING_FORMAL_DRAWDOWN_AUTHORITY = NO
```

Related but non-equivalent surfaces on live stable:

| Surface | Why not DD authority |
| --- | --- |
| North Star §7.3 | Product law only; no production core |
| `account_reality_service` | Settled NAV *candidate*; explicitly does not build NAV history / drawdown |
| `decision_cockpit_signals._max_drawdown` | Security K-line max drawdown (float bars), not account NAV state |
| `decision_inbox` `hard_risk_state` | Campaign hard-risk axis, not account drawdown |
| `portfolio_advice_*` / `top_risk_*` / `account_execution_policy` | No formal peak / drawdown-state authority |

## Decision unit

```text
Account (NAV + recent Peak)
```

Not Campaign drawdown, Security drawdown, or Position loss.

## Versioned policy

```text
policy_version = dd.account_drawdown.v0.1
policy_authority_ref = dd:account_drawdown_policy:v0.1
```

- `policy_version` is **required** (no default / latest).
- `as_of` does **not** select policy version.
- Unknown well-formed version → `drawdown_evaluation=NOT_EVALUATED` /
  `POLICY_VERSION_NOT_AVAILABLE`.

### v0.1 frozen bands

| State | Interval |
| --- | --- |
| NORMAL | `0 <= d < 0.10` |
| CAUTION | `0.10 <= d < 0.18` |
| HIGH_RISK | `0.18 <= d < 0.25` |
| DEFENSIVE | `0.25 <= d < 0.30` |
| CRITICAL_DRAWDOWN | `d >= 0.30` |

No fuzzy epsilon. Compare the frozen Decimal `drawdown_ratio`, never a
formatted percent string.

## Formula

```text
drawdown_ratio
=
(recent_nav_peak - current_account_nav) / recent_nav_peak
```

When `current_account_nav == recent_nav_peak` → `0`.

```text
PEAK_SOURCE = EXPLICIT_UPSTREAM_FACT
PEAK_ENGINE_IMPLEMENTED = NO
DD1 != NAV ENGINE
```

## NAV eligibility

| Basis | Formal drawdown |
| --- | --- |
| current `OFFICIAL_SETTLED` + peak `OFFICIAL_SETTLED` | Eligible for `EVALUATED` (when policy known and facts consistent) |
| current `ESTIMATED_INTRADAY` | `NOT_EVALUATED` / `INTRADAY_NAV_QUALITY_NOT_PROVEN` |
| peak not `OFFICIAL_SETTLED` | `NOT_EVALUATED` / `NAV_PEAK_BASIS_NOT_FORMAL` |

```text
INTRADAY_TO_SETTLED_FALLBACK = NO
RUNTIME_INTRADAY_NAV_QUALITY = OUT_OF_SCOPE
```

## Consistency and zero NAV

- `current_account_nav > recent_nav_peak` → `NOT_EVALUATED` /
  `NAV_PEAK_INCONSISTENT` (no silent peak repair, no silent `drawdown=0`).
- `current_account_nav = 0` with `peak > 0` → ratio `1` →
  `CRITICAL_DRAWDOWN`.
- `current_account_nav < 0` → validation reject.
- `recent_nav_peak <= 0` → validation reject.

```text
CURRENT_NAV_GT_PEAK = FAIL_CLOSED
ZERO_CURRENT_NAV = SUPPORTED
NEGATIVE_CURRENT_NAV = REJECTED
```

## Time coordinates

- `as_of` and `nav_peak_at` are required UTC zero-offset instants.
- `nav_peak_at <= as_of`; future peak → validation reject.
- No wall clock. No invented peak TTL / lookback window.

## Numeric discipline

Decimal arithmetic under frozen v0.1 numeric context
(`DETERMINISTIC FIXED-CONTEXT DECIMAL PROJECTION`).

```text
NUMERIC_CONTEXT = FROZEN_V0.1
NUMERIC_CONTEXT_VERSION = dd.numeric.v0.1
NUMERIC_PRECISION = 50
NUMERIC_ROUNDING = ROUND_HALF_EVEN
GLOBAL_DECIMAL_CONTEXT_DEPENDENCE = NO
HIDDEN_PERCENT_ROUNDING = NO
```

Implemented inside this module. Does not import PR #109.

## Provenance

Evaluated formal drawdown requires non-empty:

- `current_nav_authority_refs`
- `nav_peak_authority_refs`
- `policy_authority_ref` (when policy known)

```text
authority_refs = provenance witnesses
NAKED_SELF_ASSERTED_PROOF = REJECTED
UPSTREAM_AUTHORITY_REF_REQUIRED = YES
UPSTREAM_AUTHORITY_BINDING_VERIFIED = NO
```

## Evaluation precedence

1. Validate structural input (illegal → `AccountDrawdownValidationError`).
2. Identify policy availability.
3. Identify NAV / peak eligibility and consistency.

Reasons accumulate. Never fake-choose latest policy.

## Explicit non-goals

NAV engine, Peak engine, Intraday NAV Quality Envelope, Action Envelope,
Risk Budget mutation, position sizing, Sell Engine, BUY Engine,
CDA / DDA / CCD / DI, AI, persistence.

## Files

```text
backend/account_drawdown_projection.py
backend/tests/test_account_drawdown_projection.py
docs/p0/ACCOUNT_DRAWDOWN_V01.md
```
