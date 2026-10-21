# Bounded rolling signal validation

Signals → Historical Validation includes a descriptive rolling/holdout study built on the existing local historical signal evaluator. It does not introduce a strategy optimizer, executable rule language, backtest engine, provider call, or formal research/trade write.

## Declaration and identity

Before prices are read, the request declares ordered, disjoint selection and frozen holdout date ranges, a calendar segment size, one primary SMA parameter, and the fixed three-member `sma-fast-neighbors-v1` preset (15/60, 20/60, 25/60). Every parameter is displayed; no best parameter is selected. Snapshot plus declaration plus evaluator version and horizons determine the input fingerprint. Changing any declaration or snapshot creates a different experiment. No claim is made that a user has never inspected the holdout elsewhere. Inspecting the holdout neighbors consumes its unseen-data status for subsequent selection.

The manifest is resolved once. Every sample/benchmark page must return that same snapshot receipt. A benchmark cannot also be one of the selected sample codes. All returns reuse the fixed evaluator's exact signal-date and label-end-date benchmark joins without filling missing endpoints.

## Time and leakage boundaries

The 5/20 forward horizons and 15/20/25/60 SMA lengths count stored observations, not trading days. Rolling segments partition each declared range into calendar-day blocks, including a final partial block. Each aggregate and rolling segment scores only signals whose forward label ends within that segment. Crossing labels are retained as `PURGED_LABEL_END`, with return and benchmark-derived values cleared. Missing exits and immature observations remain distinct. Worst-observation flags are recomputed within the eligible segment.

All pre-segment observations are retained for causal indicator warmup. This differs deliberately from resetting indicators at every segment boundary. Coverage reports stored/evaluable observations, actual first/last dates, prior observation count, and calendar spacing. Calendar gaps do not prove missing trading sessions. Gap details show the first 20 with the complete count and omitted count.

## Bounds and cancellation

The request permits at most 20 sample codes, 48 total aggregate/rolling segments, ten calendar years of declared range, and 5,000 stored observations per code. Evaluation rejects work beyond 300,000 observation × parameter × segment units. It never truncates observations to fabricate a completed study. No arbitrary parameter grid or user-supplied code is accepted.

The existing explicit experiment ledger can persist compact receipts. Recorded cancellation is checked between read pages, parameter evaluations, and segment evaluations. An individual fixed-evaluator call is not interrupted mid-call. The unrecorded UI cancel stops receiving the result; underlying bounded read-only work may finish. Input changes/unmount invalidate stale display responses. Full reports are not persisted in the compact ledger.

## Validity limits

Historical constituent universe, corporate-action reconstruction, and investable backtest validation remain `NOT_EVALUATED`; overall historical validity remains `NOT_PROVEN`. Returns are descriptive observations, not executable trading returns. No fills, costs, limit constraints, survivorship reconstruction, or performance claims are inferred.

Tests use synthetic/offline fixtures only. Browser runtime acceptance remains separate from source/component checks and production build verification.
