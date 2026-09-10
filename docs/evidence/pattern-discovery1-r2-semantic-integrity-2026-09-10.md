# Pattern Discovery R2 · Semantic Integrity Evidence

任务：`PLANNING-PARITY-PATTERN-DISCOVERY1-R2-SEMANTIC-INTEGRITY`

日期：2026-09-10

## Scope and starting truth

- Starting stable was re-resolved live as `feature/research-system-v01@be04d62848917548ba0c5d470ec18e88749b4161`.
- PR #303 remains the merged implementation; R2 does not roll back the Pattern read model or UI. It corrects only the pre-existing volume boundary and CI proof placement identified by the latest #203 PM correction.
- Pre-#303 stable `c4d7513a6313c5368b2f584a13ac1fbf70efdf5e` is the baseline for the existing single-stock `volume_spike` contract.
- Owner checkout is not used for execution. No real Owner data is read or written.

## Frozen volume boundary contract

```text
PRE_303_BASELINE = volume_spike > 2.0
PR_303_DRIFT = volume_spike >= 2.0
R2_CORRECTION = restore > 2.0
CURRENT_SINGLE_STOCK_CONTRACT = > 2.0
CURRENT_SET_BASED_CONTRACT = > 2.0
```

The user-visible label is now `5/20 日均量比超过 2.0`; it does not describe equality as a trigger.

The direct boundary contract is tested independently in both implementations:

| ratio | single-stock `volume_spike` | set-based `volume_surge` |
| --- | --- | --- |
| exactly `2.0` | `NO_TRIGGER` | `NO_TRIGGER` |
| greater than `2.0` | `TRIGGER` | `TRIGGER` |

The cross-implementation parity test remains, but it is not the only proof: the frozen strict-`GT_2_0` assertions directly encode the pre-#303 baseline.

## Other Pattern semantics

R2 does not modify:

- `close_above_20d_high` current-day exclusion or strict `>` comparison;
- `close_below_20d_low` current-day exclusion or strict `<` comparison;
- `sma20_cross_above_sma60` previous/current window or equality boundary;
- `sma20_cross_below_sma60` previous/current window or equality boundary;
- missing-data and `NOT_EVALUABLE` handling;
- artifact-derived `as_of` and future-row cutoff;
- set-based/no-provider/no-per-security-N+1 execution;
- read-only/no-formal-state-write behavior.

## Browser and CI proof wiring

The existing `frontend/tests/e2e/pattern-discovery.browser.mjs` and `npm run test:e2e:patterns` are reused. No second E2E or new CI job is created. The existing `Playwright smoke E2E` job runs an explicit `Run Pattern Discovery E2E` step next to Dragon-Tiger and Full-Market Discovery.

The existing vertical continues to cover real FastAPI, production frontend build, temporary deterministic RDP artifact, discoverable Pattern tab, event rendering, `NOT_EVALUABLE`, historical `as_of`, duplicate identity fail-closed, desktop/narrow viewports, no pageerror, no console error and no overflow. Its fixture now includes:

- an exact `volume_ratio == 2.0` code that must not render `volume_surge`;
- a `volume_ratio > 2.0` code that must render `volume_surge`.

Exact-head and post-merge CI run URLs are recorded in the GitHub #203 verified closure after the R2 branch is merged; no other SHA's CI is reused as proof.

## Authority boundary

```text
NEW_PROVIDER = NO
BLACK_BOX_SCORE = NO
AI_RANKING = NO
BUY_SELL = NO
NEW_INVESTMENT_AUTHORITY = NO
FORMAL_STATE_WRITES = ZERO
```
