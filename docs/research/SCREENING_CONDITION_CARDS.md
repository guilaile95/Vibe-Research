# Named screening condition cards

The Full Market tab provides an explicit local workflow: save current conditions as a named version, select that immutable version, run it at the selected cutoff, save the result, and compare two saved runs. Refresh and readback do not execute or modify screens.

## Boundaries

- Uses the existing RDP `query_full_market` computed metrics, named metric/operator allowlists, snapshot pinning, and replay receipts. No expression parser, second universe, provider call, or per-security calculation engine is introduced.
- Each run reads the complete pinned cross-section in bounded pages. More than 10,000 securities, incomplete pages, inconsistent snapshots, or an oversized result fail closed without saving a partial run.
- Condition evidence records threshold, observed value, unit, PASS/FAIL/UNKNOWN and missingness. Source price and volume units are explicitly undeclared where RDP does not specify them; returns and moving-average deviations are fractions and volume ratio is dimensionless.
- Eligibility requires every condition to PASS. Any missing, insufficient, or stale metric makes eligibility UNKNOWN. This is deliberately stricter than legacy Full Market SQL numeric matching, which can retain stale observations.
- Comparison reports changed conditions, changed snapshot/cutoff, and missing/stale coverage separately. These are observed differences, not causal attribution. Exiting due to UNKNOWN never establishes fundamental deterioration.
- Cards and runs use append-only application operations in the existing observation materialization database. This is research persistence, not formal decision authority. No watchlist, portfolio, or trade writes occur.
- Stored records undergo duplicate-key/nonfinite rejection, integrity and identity checks, rule validation, and condition/result consistency checks. Hashes detect accidental content drift; they are not cryptographic authenticity proof.
- Local save time and replay receipts do not prove historical publication-vintage availability.

## Validation

Focused tests cover save/readback/versioning, rule/data/coverage changes, stale and missing values, malformed conditions, malformed persisted evidence, index mismatch, truncated pages, and sanitized HTTP errors. The existing offline Full Market browser vertical also exercises condition-card version saves, saved runs, exit explanations, and persistence after refresh.
