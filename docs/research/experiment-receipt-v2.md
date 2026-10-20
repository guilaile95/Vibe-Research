# Experiment receipt v2

New explicit recordings use `experiment-record.v2`. No migration, backfill, background
recalculation, or replacement of existing records is performed. V1 remains readable
and digest-validated as originally stored. Old pending records cannot execute under
a new receipt protocol: start a new explicit recording instead. An old empty metric
map is reported as `LEGACY_METRICS_NOT_RETAINED`, never equality or zero.

The `metric_protocol` is `scalar.v1` for existing selected scalar aggregates, or
`cost-groups.v1` for cost comparison. `metric_dimensions` supplies currency, method,
metric name, unit and `SUPPORTED`/`UNKNOWN` state for every cost aggregate. Keys are
validated canonical identifiers, not arbitrary recursively flattened report paths.

Cost receipts retain eight currency-group aggregates per method: remaining cost,
realized/unrealized/economic PnL, market value, paid dividends, dividend receivable,
and fees. Only FIFO and moving average, and only CNY/HKD/USD are accepted (maximum
48 values). Currency is the monetary unit. Missing values stay null. Per-security
rows, trades, quantities and mixed-currency totals are not retained or inferred.
Comparison requires matching metric protocols, dimensions and existing input/rule
identities. Incomplete runs and absent metrics are not comparable.

Signal, rolling-signal and factor rule identities include the indicator schema
version, so results across indicator semantics cannot silently compare as identical.
V1 readers cannot read V2 records: rolling application code back requires a V2-aware
reader or a separately approved data restoration plan, not rewriting new receipts.

Validation: synthetic evaluator-to-store/readback tests, explicit independent FIFO
and moving-average arithmetic, missing/zero/multi-currency cases and immutable V1
read tests. Factor navigation has actual-component deferred-response tests and a
standalone browser fixture `frontend/tests/e2e/factor-navigation.browser.mjs` that
serves the production build and intercepts every API request. The fixture requires
Chromium; it makes no live provider/model calls and starts no backend.
