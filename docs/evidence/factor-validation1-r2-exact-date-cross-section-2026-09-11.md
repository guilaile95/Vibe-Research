# Factor Validation R2 · Exact-Date Cross-Section Evidence

任务：`PLANNING-PARITY-FACTOR-VALIDATION1-R2-EXACT-DATE-CROSS-SECTION`

日期：2026-09-11

## Starting truth and correction boundary

- Live starting stable was re-resolved as `feature/research-system-v01@abab2766c768b950b657d25b7ca12ee1d22f7602` before the worktree was created.
- The PM correction on #203 identified that PR #307 could include a Full Market row with `latest_date < factor_date` in that factor-date cross-section. This R2 corrects only Factor Validation eligibility and its directly related evidence/tests/UI.
- `research_data_plane.query_full_market(as_of=T, latest=false)` is intentionally unchanged. Its existing global contract still returns each security's last stored observation at or before `T`; Factor Validation now filters the returned rows before pair construction.
- Owner checkout was not used for execution, reset, clean, stash, rebase, force push, or cleanup. No real Owner account, portfolio, research, or trading data was read or written.

## Exact-date factor contract

```text
FACTOR_DATE_CROSS_SECTION = EXACT_DATE_ONLY
EXACT_DATE_ELIGIBILITY = row.latest_date == factor_date
STALE_SOURCE_ROW = row.latest_date < factor_date
STALE_SOURCE_ROW = EXCLUDED_AND_COUNTED
STALE_SOURCE_ROW_CAN_ENTER_IC = NO
STALE_SOURCE_ROW_CAN_ENTER_HIGH_LOW = NO
STALE_SOURCE_ROW_COUNTS_AS_FACTOR_NULL = NO
STALE_SOURCE_ROW_COUNTS_AS_IMMATURE = NO
FUTURE_ROW_AT_FACTOR_DATE = FAIL_CLOSED
```

`universe_count` now means the exact-date universe and the per-date response also exposes `source_asof_row_count`, `exact_date_universe_count`, and `stale_source_row_count`. The sample and aggregate layers carry the corresponding totals. Stale rows remain visible in the reason/limitation path instead of being silently discarded. They do not enter factor-value pairs, forward outcomes, Spearman IC, high bucket, low bucket, or high-low spread.

The forward outcome anchor is `index_by_code[code][factor_date]`. A valid pair uses the close at the exact factor date and the close at the security's fifth/twentieth later stored observation. The stored-observation window, average-rank Spearman, top-20%-minus-bottom-20% bucket semantics, null-versus-zero behavior, `UNADJUSTED`, `HISTORICAL_VALIDITY = NOT_PROVEN`, six direct Full Market source metrics, max-250-date bound, and zero formal writes remain unchanged.

## Core regression fixture

The backend fixture contains three securities and forty stored dates. Security B is absent on `2026-01-10` but has a row on `2026-01-09` and resumes on `2026-01-11` with enough subsequent observations.

At factor date `T = 2026-01-10`:

```text
Full Market as-of rows = 3
exact-date rows = 2
stale source rows = 1 (B)
factor-null rows = 0
immature outcome rows = 0
invalid outcome rows = 0
pair count = 2
high bucket count = 1
low bucket count = 1
```

The test captures the actual IC inputs and asserts that they equal only the two exact-date Full Market source metrics. It also asserts forward returns anchored from T at both 5 and 20 stored observations. B's previous-date factor and previous-date anchor cannot enter the T observation.

At `T+1 = 2026-01-11`, B has an exact stored observation again:

```text
exact-date rows = 3
stale source rows = 0
5-observation pair count = 3
20-observation pair count = 3
```

This proves temporary missing-date exclusion rather than permanent security exclusion.

## Browser source-to-sink evidence

The existing `frontend/tests/e2e/factor-validation.browser.mjs` was reused with a deterministic isolated RDP artifact containing 61 securities and 90 dates. One security (`600060`) is absent on `2026-03-02` and resumes on `2026-03-03`; another existing fixture security remains an immature forward-outcome control.

The real FastAPI route and production frontend build produced the following assertions:

```text
Full Market as-of 2026-03-02: code 600060 present, latest_date = 2026-03-01
Factor date 2026-03-02: source_asof_row_count = 61
Factor date 2026-03-02: exact_date_universe_count = 60
Factor date 2026-03-02: stale_source_row_count = 1
Factor date 2026-03-02: factor_null_count = 0
Factor date 2026-03-02: pair_count = 59
Factor date 2026-03-03: exact_date_universe_count = 61
Factor date 2026-03-03: stale_source_row_count = 0
Factor date 2026-03-03: pair_count = 60
fixture source rows = 5490
fixture exact-date factor values = 5463
fixture stale source rows = 27
```

The UI displays `当日有效横截面累计`, `排除旧日期数据`, and the readable explanation that a security with only earlier last-known data does not participate in that factor date's IC or High-Low. Desktop `1440×900` and narrow `390×844` were exercised; the test checked no document-level horizontal overflow, no page errors, and no console errors. Screenshots were written outside the repository to `C:\Users\DINOL\AppData\Local\Temp\vr-factor-validation-e2e-evidence` and are not source-data artifacts.

The browser plugin was unavailable in this environment, so the repository's existing regular Playwright path was used. This is a tooling-path note, not a claim that browser validation was skipped.

## Local validation

```text
backend Factor focused tests: 8 passed
RDP / Historical Signal Validation / Pattern / Screener regressions: 60 passed
frontend focused + Signals / Pattern / Screener tests: 639 passed, 0 failed
production build (tsc -b && vite build): passed
Factor browser E2E: passed
git diff --check: passed
```

Commands:

```text
py -3 -m pytest tests/test_factor_validation.py -q
py -3 -m pytest tests/test_research_data_plane_full_market.py tests/test_historical_signal_validation.py tests/test_research_data_plane_patterns.py tests/test_screener.py tests/test_screener_api.py -q
npm test -- --test-name-pattern="factor validation|historical validation|Full Market|result grouping"
npm run build
npm run test:e2e:factor-validation
git diff --check
```

## Independent Gate

```text
FACTOR_DATE_CROSS_SECTION = EXACT_DATE_ONLY
EXACT_DATE_ELIGIBILITY = ROW_LATEST_DATE_EQUALS_FACTOR_DATE
STALE_SOURCE_ROW = EXCLUDED_AND_COUNTED
STALE_SOURCE_ROW_CAN_ENTER_IC = NO
STALE_SOURCE_ROW_CAN_ENTER_HIGH_LOW = NO
STALE_SOURCE_ROW_COUNTS_AS_FACTOR_NULL = NO
STALE_SOURCE_ROW_COUNTS_AS_IMMATURE = NO
TEMPORARY_MISSING_T_RESUME_T_PLUS_1 = PROVEN
FORWARD_RETURN_ANCHOR = EXACT_FACTOR_DATE
FORWARD_WINDOWS = 5_AND_20_STORED_OBSERVATIONS
FACTOR_VALUE_PARITY_WITH_FULL_MARKET = PROVEN_FOR_EXACT_DATE_ROWS
GLOBAL_FULL_MARKET_SEMANTICS_CHANGED = NO
IC_METHOD = CROSS_SECTIONAL_SPEARMAN
TIE_RANKING = AVERAGE_RANK
RDP_ADJUSTMENT = UNADJUSTED
HISTORICAL_VALIDITY = NOT_PROVEN
PER_SECURITY_HTTP_N_PLUS_ONE = NO
NEW_PROVIDER = NO
NEW_DEPENDENCY = NO
BLACK_BOX_SCORE = NO
BUY_SELL = NO
FORMAL_STATE_WRITES = ZERO
```

Local implementation and vertical evidence support `INDEPENDENT_GATE = ACCEPT`. Current-base revalidation, exact-head CI, Ready/ordinary merge, post-merge exact-stable CI, #203 recovery update, and Notion correction closure remain pending until the Draft PR lifecycle is completed; no pending item is represented here as verified.
