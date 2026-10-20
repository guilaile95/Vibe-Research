# Manual prediction journal

This is a personal review tool, not evidence of model quality, trading ability or calibrated forecasts. It does not call models/providers, infer outcomes or change Thesis, campaign, formal decisions, account authority or trades.

## Recording and resolution

The Personal Review panel has a manual binary-question journal. A user supplies a subject/reference, explicit criterion, probability in [0,1], future deadline, evidence context and an assertion that the outcome is not already known. UI inputs probabilities in percent; API/storage use unit fractions. User assertions and user-entered source references are labeled separately; neither is automatically verified.

Server time is captured inside the existing facts-database write transaction, after acquiring the lock. Past/equal deadlines and caller-provided recording timestamps are rejected. This establishes local recording order only: the user's actual prior knowledge cannot be verified. Forecast rows cannot be edited or deleted through this API. There are no historical imports. A mistaken forecast remains visible; users can record a new distinct question but cannot replace the original probability.

Manual TRUE/FALSE/INDETERMINATE resolutions append revisions with expected-revision CAS, evidence, explicit reason, a user-asserted evidence-availability timestamp and server recording time. Original forecasts and earlier resolution revisions remain intact. Conservative product rule: a resolution's evidence availability must be at or after the deadline and no later than server recording. Earlier event observations must wait until the deadline and be checked again. This rule intentionally does not support early settlement.

GET `as_of` exposes only forecasts locked by then and revisions both recorded and available by then. A late-entered outcome cannot change an earlier view. A correction replaces the current displayed result only from its recording time onward; history remains visible. Historical views are read-only in the UI. Future as-of queries fail closed.

The journal uses `prediction_forecasts` and `prediction_resolutions` tables through the existing `observation_workflow_store` SQLite authority under the configured local data root. It is not browser storage. Read-before-write validation, digest checks, bounded history, no-store responses, explicit reload and stale-generation protection prevent silently presenting unverified or late responses as current. A failed or uncertain write disables further submissions until authoritative reload. Forecast identities survive retries; duplicate insertion conflicts rather than overwrites.

## Descriptive measures and limitations

- Brier is the mean of `(probability - binary outcome)^2`, unitless in [0,1], on currently resolved binary forecasts only. Lower means less squared error on that sample; no universal cutoff implies misleading predictions or quality
- Total, binary-resolved, unresolved and indeterminate counts are separate. No binary outcomes means Brier unavailable, never zero
- Optional user-asserted base-rate probability plus population/time/source context must be frozen with the original forecast. Benchmark Brier and forecast Brier are shown only on the matching subset, with its count. Missing or unsuitable benchmark contexts are not manufactured from outcomes. Context suitability and independence are unverified; the comparison is not a skill score
- Ten fixed bins are [0,.1), …, [.9,1]. Identical probabilities never split, including 0 and 1. Empty bins have null means/frequencies. All probabilities/frequencies use the same unit, rendered as percent
- Fewer than 20 resolved observations overall or in a bin produces a sample caution. This is a product display rule, not a statistical significance threshold or proof of calibration above 20. No ability ranking, calibrated classification or model-quality guarantee is produced
- Selection bias, correlated forecasts, heterogeneity, subjective criteria and manual adjudication remain limitations. No confidence interval is claimed for a non-independent heterogeneous journal

Limits: 500 forecasts, 100 resolution revisions each. Existing history is retained when limits are reached. Focused tests use synthetic fixtures with network prohibited; they establish software behavior only. Browser runtime acceptance is separate from unit/source-contract tests and production build verification.

## Local verification, 2026-10-19

- Focused backend journal suite: 22 passed, including concurrent CAS and delayed transaction/deadline regression
- Journal + existing experiment ledger + personal review backend suites: 98 passed
- Frontend validator/generation/readback helper suite: 8 passed
- Actual PredictionJournal component executed with synthetic hooks/transport: 4 passed (double submit, authoritative readback, failed readback/reload, historical filter, unmount suppression). This is not a real React DOM/browser test
- Full frontend suite before the four additional component tests: 1,946 passed, 1 existing skip
- Production TypeScript/Vite build: passed; existing large-chunk warning remains
- Browser runtime acceptance: NOT_EVALUATED; no browser retry, provider/model/key call, real outcome evidence, push, PR, merge or deployment performed
