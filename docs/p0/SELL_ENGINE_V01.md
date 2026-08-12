# P0-SE1 Sell Engine v0.1

## Decision information

Sell Engine answers:

> For a real holding Campaign (`Security + Strategy + Campaign`), given
> already-normalized Thesis / Hard Risk / Expectation / R/R / Catalyst /
> Portfolio / Opportunity Cost / Technical conclusions, what is the current
> **sell-side** state and why?

It is the **deterministic sell-side semantic authority**.

It is **not**:

- BUY Engine
- Hard Risk Engine
- Thesis Engine
- Material Change Engine
- Expectation / Catalyst producer
- Portfolio optimizer
- Technical trading system
- AI recommendation engine

## Anti-rewheel result

```text
EXISTING_FORMAL_SELL_ENGINE_AUTHORITY = NO
```

Existing related surfaces that are **not** Sell Engine authority:

| Surface | Why not Sell Engine |
| --- | --- |
| `portfolio_advice_*` | AI portfolio advice + sellable quantity advisory; not campaign sell authority |
| `top_risk_*` | Contextual top-risk analysis; shadow mode; not Hard Risk / Sell |
| `decision_cockpit_*` | Value/trend/short sensors; not sell-side decision authority |
| Trade ledger `reduce/sell` | Execution facts, not sell recommendation authority |
| Formal Thesis Projection | Owns thesis delta states; not sell action states |
| Decision Inbox | Owns user-attention workflow states; consumes risk/thesis, does not own sell |

## Decision unit

```text
Security + Strategy + Campaign
```

Same security, different campaigns are independent:

```text
600519 SWING  !=  600519 MEDIUM
```

No security-wide SELL broadcast.

## Sell states

Domain action axis:

- `HOLD`
- `WATCH_TO_REDUCE`
- `REDUCE`
- `EXIT`
- `THESIS_INVALIDATED`

Evaluation completeness axis (separate):

- `EVALUATED`
- `UNKNOWN`
- `NOT_EVALUATED`
- `ERROR`

```text
domain sell_state
!=
sell_evaluation
```

When required dimensions are incomplete and no confirmed sell pressure exists:

```text
sell_state = null
hold_positive_proof = false
sell_evaluation = UNKNOWN | NOT_EVALUATED | ERROR
```

Never invent `HOLD` from absence of sell signals.

## Reason categories (North Star)

1. `THESIS_INVALIDATION`
2. `RISK_EXIT`
3. `EXPECTATION_PRICE_IN`
4. `RISK_REWARD_DETERIORATION`
5. `CATALYST_FAILURE`
6. `PORTFOLIO_REBALANCE`
7. `OPPORTUNITY_COST`
8. `TECHNICAL_EXECUTION`

## Input boundary

Keyword-only normalized dimensions:

| Input | Allowed states (v0.1) | Owner |
| --- | --- | --- |
| `thesis` | STABLE / STRENGTHENED / WEAKENED / DISPROVEN / INVALIDATED / UNKNOWN / NOT_EVALUATED / ERROR / NOT_READY | Formal Current Thesis |
| `hard_risk` | CLEAR / CONFIRMED / UNKNOWN / NOT_EVALUATED / ERROR | Hard Risk (when formal) |
| `expectation_price_in` | NONE / WATCH / REDUCE / EXIT / UNKNOWN / NOT_EVALUATED / ERROR | Expectation authority (upstream) |
| `risk_reward` | NONE / WATCH / REDUCE / EXIT / UNKNOWN / NOT_EVALUATED / ERROR | R/R authority (upstream) |
| `catalyst` | NONE / FAILED / NOT_YET / UNKNOWN / NOT_EVALUATED / ERROR / NOT_APPLICABLE | Catalyst authority |
| `portfolio_rebalance` | NONE / WATCH / REDUCE / EXIT / UNKNOWN / NOT_EVALUATED / ERROR | Portfolio authority |
| `opportunity_cost` | NONE / WATCH / REDUCE / EXIT / UNKNOWN / NOT_EVALUATED / ERROR | Opportunity authority |
| `technical_execution` | NONE / WATCH / REDUCE / EXIT / UNKNOWN / NOT_EVALUATED / ERROR / NOT_APPLICABLE | Technical sensor normalization |

Rules:

- PnL / price / AI payloads are rejected (`unsupported keys`).
- Missing upstream authority → pass `NOT_EVALUATED` / `UNKNOWN`; do **not** implement that authority inside Sell Engine.
- `as_of` is required UTC zero-offset instant; no wall clock.

## Dimension semantics (v0.1)

### Thesis invalidation

Consumes Formal Thesis vocabulary:

| Thesis state | Sell effect |
| --- | --- |
| DISPROVEN / INVALIDATED | `THESIS_INVALIDATED` + reason `THESIS_INVALIDATION` |
| WEAKENED | `WATCH_TO_REDUCE` |
| STABLE / STRENGTHENED | no sell pressure (HOLD-positive) |
| UNKNOWN / NOT_EVALUATED / ERROR / NOT_READY | incomplete; blocks HOLD |

```text
DISPROVEN | INVALIDATED  →  sell_state THESIS_INVALIDATED
```

Loss / MA break / market weakness must not substitute thesis invalidation.

### Risk exit

| Hard risk | Sell effect |
| --- | --- |
| CONFIRMED | `EXIT` + `RISK_EXIT` |
| CLEAR | HOLD-positive |
| UNKNOWN / NOT_EVALUATED / ERROR | incomplete |

Hard Risk authority ≠ Sell Engine authority.

### Expectation / price-in

Consumes normalized pressure only. Forbidden inside engine:

- 重大利好落地 → SELL
- 涨很多了 → PRICE_IN_CONFIRMED

### R/R deterioration

North Star thresholds remain upstream. Inside Sell Engine:

```text
R/R EXIT input  →  capped to REDUCE
```

No mechanical EXIT from R/R alone.

### Catalyst failure

| Catalyst | Effect |
| --- | --- |
| FAILED + SHORT | EXIT |
| FAILED + SWING/MEDIUM | REDUCE |
| NOT_YET / NONE | no failure |
| NOT_APPLICABLE | **only MEDIUM** (no short catalyst required) |

```text
MEDIUM + NO CATALYST  !=  CATALYST_FAILURE
```

### Portfolio rebalance

May produce REDUCE/EXIT with reason `PORTFOLIO_REBALANCE` without rewriting Asset View.

### Opportunity cost

Respects Replacement Hurdle + NO-TRADE ZONE (evaluated upstream).

```text
OPPORTUNITY_COST EXIT input  →  capped to REDUCE
```

No “another stock looks better → EXIT”.

### Technical execution

Sensor only. Strategy caps:

| Strategy | Cap |
| --- | --- |
| SHORT | max REDUCE (EXIT capped) |
| SWING | EXIT capped to REDUCE; WATCH/REDUCE allowed |
| MEDIUM | any technical pressure capped to WATCH_TO_REDUCE |

```text
technical-only MEDIUM  !=  THESIS_INVALIDATED
technical-only MEDIUM  !=  EXIT
```

## HOLD positive proof

```text
NO SELL SIGNAL  !=  PROVEN HOLD
```

`HOLD` requires:

1. every applicable required dimension `EVALUATED`
2. each is clear / NONE / NOT_APPLICABLE (where allowed)
3. no confirmed sell pressure
4. `sell_evaluation == EVALUATED`

Then:

```text
sell_state = HOLD
hold_positive_proof = true
reason includes HOLD_POSITIVE_PROOF
```

Otherwise incomplete → `sell_state = null` (not HOLD).

## Precedence (primary reason)

Frozen minimal order among **confirmed** sell categories:

```text
1. THESIS_INVALIDATION
2. RISK_EXIT
3. CATALYST_FAILURE
4. RISK_REWARD_DETERIORATION
5. EXPECTATION_PRICE_IN
6. PORTFOLIO_REBALANCE
7. OPPORTUNITY_COST
8. TECHNICAL_EXECUTION
```

Rules:

- Primary selects one category for explainability.
- Supporting reasons are **cumulative**; primary is not exclusive.
- Domain state severity uses max pressure:
  `THESIS_INVALIDATED > EXIT > REDUCE > WATCH_TO_REDUCE > HOLD`

## Explainability output

```text
schema_version
authority_ref
security_code / strategy / campaign_id / as_of
sell_state
sell_evaluation
primary_reason
reason_codes
supporting_reasons
opposing_reasons
uncertainties
hold_positive_proof
authority_refs
dimensions{...}
```

## Pure domain

Module: `backend/sell_engine_projection.py`

- no I/O / SQLite / filesystem / env / network / FastAPI / AI / wall clock
- pure function `project_sell_engine(...)`
- detached deep-copied output
- zero mutation of inputs

## Explicit non-goals

BUY Engine, Opportunity Engine, Hard Risk Engine, Material Change Engine,
Critical Data Adapter, Decision Inbox/DI2, Portfolio Optimizer, Expectation
Engine, Catalyst Engine, AI pipeline, providers, datasets, scheduler, broker
integration, auto trading.

## Files

```text
backend/sell_engine_projection.py
backend/tests/test_sell_engine_projection.py
docs/p0/SELL_ENGINE_V01.md
```
