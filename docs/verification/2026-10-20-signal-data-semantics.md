# Signal data semantics, 2026-10-20

Scope: offline synthetic verification of dated missing observations and candidate freshness. No live-provider/model evaluation, historical-data migration, publication or deployment is implied.

## Technical indicators v0.3

- Preserve each valid dated observation even when close is missing/non-finite. Deduplication still prefers a usable close on the same date, then completeness/timestamp/canonical tie-breaks. Undated rows remain unusable; absent calendar dates are not invented.
- SMA/Bollinger require every close in their observation window. Volume ratio independently requires its volume window. Breakout/breakdown independently require the preceding 20 high/low observations and today's close; a missing close does not shift that window.
- EMA retains the existing first-value seed on complete inputs. A gap emits unknown and clears recurrence; after a gap, a newly first-value-seeded EMA emits only after N consecutive valid observations. MACD requires both EMA12 and EMA26; DEA resets on unknown DIF and requires 9 consecutive valid DIF values. Thus post-gap histogram resumes on the 34th consecutive valid close.
- Wilder RSI clears state at a gap and restarts from 14 changes / 15 consecutive closes. KDJ clears K/D state to 50 on any invalid required window, and restarts only after 9 complete close/high/low observations.
- Missing latest close is unavailable at its actual date, not the previous available date. Unknown indicators are not filled with zero or earlier results. Complete valid inputs retain their existing calculations, including finite zero close handling.

## Candidate screener v0.2

The batch pins a snapshot and its coverage-end cutoff once. A stock is current only if its observed last date equals that cutoff, matching Full Market's equality policy. This is snapshot-relative, not wall-clock or exchange-calendar freshness. Suspension and missing tails cannot be distinguished from these bars and are both stale.

Readable stale samples remain available as data, but are in the unavailable signal bucket with matched=null and technical_status=stale. Each condition is unevaluable for current matching; explicitly labelled last_known evidence is retained for inspection. Coverage exposes current/stale/unknown freshness and a separate stale_count. Stale rows never increment fully_evaluable_count. Artifact readability and current-signal availability remain separate.

The UI labels stale observations as non-current, shows the pinned cutoff and stale exclusion count, and calls matches current matches. Missing legacy freshness counts are unknown, not fabricated zero.

Synthetic tests cover interior/latest/repeated/non-finite gaps, fixed and recursive recovery windows, prefix causality, complete-series independent calculations, zero/ordering/duplicates, HTTP propagation, candidate-to-Full-Market stale parity, missing samples, and explicitly pinned historical cutoffs. Frontend production-JSX rendering verifies stale labels and counts.

## Verification evidence

The core indicator/screener suite passed 162 tests, followed by 80 passing focused revalidation tests covering the final stale-classifier guard and KDJ limitation wording. Related historical, factor, rolling, alert and data-health adapter suites passed 148 tests. Frontend source-to-render/unit suites passed 31 tests and TypeScript project build passed. Backend runs used fresh isolated storage roots and a Python socket/DNS guard; HTTP tests used in-process clients without starting the production lifespan. These are offline contracts, not a full browser/live-provider acceptance claim.

Consumer compatibility scan found no production hard-coded old schema literals outside the updated screener output model. Frontend API readers accept string schema versions; a legacy screener-v0.1 fixture remains covered. Historical/factor/rolling calculations and alert schemas are separate contracts. Archived experiment rules/receipts are not rewritten by these fixes; experiment protocol tagging is maintained by the experiment-ledger change.
