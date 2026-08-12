# P0-SE1 Sell Engine v0.1 (R1)

## Decision information

Sell Engine answers:

> For a real holding Campaign (`Security + Strategy + Campaign`), given
> already-normalized sell-side dimension conclusions, what is the current
> **sell-side** state and why?

```text
Sell Engine
=
normalized sell-pressure composition authority
```

Not:

- BUY Engine / Hard Risk Engine / Thesis Engine / Material Change Engine
- Expectation / Catalyst **producer**
- Portfolio optimizer / technical trading system / AI recommender

R1: composition of normalized pressures — **not** inventing action severity
from raw upstream domain facts (except the Product-Authority thesis terminal
map).

## Anti-rewheel

```text
EXISTING_FORMAL_SELL_ENGINE_AUTHORITY = NO
```

`portfolio_advice_*`, `top_risk_*`, `decision_cockpit_*`, trade ledger
`reduce/sell` are not formal Sell Engine authority.

## Decision unit

```text
Security + Strategy + Campaign
```

## Sell states

Domain:

- `HOLD`
- `WATCH_TO_REDUCE`
- `REDUCE`
- `EXIT`
- `THESIS_INVALIDATED`

Evaluation axis (separate):

- `EVALUATED` / `UNKNOWN` / `NOT_EVALUATED` / `ERROR`

```text
NO SELL SIGNAL  !=  PROVEN HOLD
```

Incomplete applicable dimensions without confirmed pressure →
`sell_state = null` (never false HOLD).

## Reason categories

1. `THESIS_INVALIDATION`
2. `RISK_EXIT`
3. `EXPECTATION_PRICE_IN`
4. `RISK_REWARD_DETERIORATION`
5. `CATALYST_FAILURE`
6. `PORTFOLIO_REBALANCE`
7. `OPPORTUNITY_COST`
8. `TECHNICAL_EXECUTION`

## Inputs (R1)

| Input | Role | States |
| --- | --- | --- |
| `thesis` | Formal thesis effective_state | STABLE/STRENGTHENED/WEAKENED/DISPROVEN/INVALIDATED/UNKNOWN/NOT_EVALUATED/ERROR/NOT_READY |
| `risk_exit` | **Normalized** risk-exit sell pressure (not raw Hard Risk) | NONE/WATCH/REDUCE/EXIT/UNKNOWN/NOT_EVALUATED/ERROR/NOT_APPLICABLE |
| `expectation_price_in` | Normalized pressure | same pressure vocab |
| `risk_reward` | Normalized pressure | same |
| `catalyst` | Normalized pressure + NOT_YET | NONE/NOT_YET/WATCH/REDUCE/EXIT/UNKNOWN/NOT_EVALUATED/ERROR/NOT_APPLICABLE |
| `portfolio_rebalance` | Normalized pressure | pressure vocab |
| `opportunity_cost` | Normalized pressure | pressure vocab |
| `technical_execution` | Normalized pressure | pressure vocab |

Removed from public API: raw `hard_risk` / `CONFIRMED` auto-EXIT.

### Provenance (P1)

Any evaluated semantic assertion that can:

- support HOLD positive proof
- produce WATCH / REDUCE / EXIT / THESIS_INVALIDATED
- declare NONE / CLEAR-equivalent / NOT_APPLICABLE

**must** carry ≥1 non-empty trimmed `authority_refs`.

```text
UNKNOWN / NOT_EVALUATED / ERROR / NOT_READY
may omit authority_refs
```

Caller self-asserted clean or self-asserted sell pressure is rejected.

## Thesis boundary (P2)

| Thesis | Sell Engine |
| --- | --- |
| DISPROVEN / INVALIDATED | → `THESIS_INVALIDATED` + `THESIS_INVALIDATION` (Product Authority) |
| WEAKENED | **not** THESIS_INVALIDATION; no auto WATCH/REDUCE/EXIT; `hold_positive_proof=false`; reason `THESIS_WEAKENED` |
| STABLE / STRENGTHENED | no sell pressure; HOLD-positive when proven |

```text
WEAKENED  !=  THESIS_INVALIDATION
```

## No unsupported pressure transforms (P3–P5)

Removed invented transforms:

- HARD_RISK CONFIRMED → EXIT
- CATALYST_FAILED + strategy → EXIT/REDUCE
- R/R EXIT → forced REDUCE
- Opportunity EXIT → forced REDUCE
- Technical MEDIUM/SHORT strategy caps
- Strategy-owned catalyst NOT_APPLICABLE-only-MEDIUM

Normalized upstream WATCH/REDUCE/EXIT pass through without silent downgrade.

Catalyst `NOT_APPLICABLE` is **upstream-owned** for any strategy (with refs).

## Required dimensions (P6)

```text
SELL ENGINE DOES NOT OWN
WHICH DIMENSIONS ARE APPLICABLE TO THIS CAMPAIGN
```

HOLD positive proof =

- all **applicable** dimensions evaluated clean (authority-backed), and
- all **NOT_APPLICABLE** dimensions properly proven (authority-backed), and
- no unresolved applicable incomplete dimension, and
- no confirmed sell pressure

Optional / NOT_APPLICABLE dimensions do not invent a universal 8-dim
prerequisite beyond what the caller supplies as applicable.

## Primary reason (P7)

1. Compute **final** `sell_state` first (max pressure rank).
2. `primary_reason` ∈ categories whose pressure **equals** that final state.
3. No full eight-level semantic investment precedence.

Co-drivers:

- `primary_reason_selection = SOLE_DRIVER` when one driver
- else `DISPLAY_TIE_BREAK_NOT_SEMANTIC_PRIORITY` + `co_driving_reasons`

Terminal `THESIS_INVALIDATED` naturally primaries `THESIS_INVALIDATION`.

Counterexample (must pass):

```text
catalyst = REDUCE
expectation = EXIT
→ sell_state = EXIT
→ primary_reason = EXPECTATION_PRICE_IN
  (not CATALYST_FAILURE)
```

## Explainability output

```text
sell_state / sell_evaluation
primary_reason / primary_reason_selection / co_driving_reasons
reason_codes / supporting_reasons / opposing_reasons / uncertainties
hold_positive_proof / authority_refs / dimensions
```

## Pure domain

`backend/sell_engine_projection.py` — zero I/O / AI / wall clock / persistence.

## Files

```text
backend/sell_engine_projection.py
backend/tests/test_sell_engine_projection.py
docs/p0/SELL_ENGINE_V01.md
```
