# Measured performance work — 2026-10-24

Baseline: `c16ade49174a26597de05244ac9f70d2855c590a` on
`feature/research-system-v01`. This dated measurement note is not a deployment
record or a claim that the user's target computer was tested.

## Changes justified by measurement

| Workload | Baseline P50 / P95 (ms) | Candidate P50 / P95 (ms) | Preserved contract |
|---|---:|---:|---|
| Native Intel trending, 500 items × 20 history observations | 422.15 / 439.91 | 49.45 / 59.87 | All 500 histories and their error checks, same full output hash |
| Native Intel status, service-level fixture | 22.63 / 27.59 | 7.15 / 7.56 | No cross-request configuration cache; original count retry retained |
| Full-market query, 5,000 codes / 322,255 bars | 160.38 / 196.96 | 97.72 / 102.42 | Artifact hash, coverage, source receipt, filtering, stable pagination |
| Report search, 34.4 MB actual SQLite index | 244.47 / 257.46 | 128.88 / 145.45 | One immutable image per operation, source SHA and final unchanged checks |
| Report context preparation, same index | 240.47 / 255.15 | 122.42 / 128.88 | Fresh operation snapshot, current exact hit/chunk eligibility |
| Research restore, 12.7 MB synthetic snapshot, Node scheduler double | 147.31 / 154.93 | 94.66 / 103.48 | All 8 reads and global chain/provenance validation remain |

All figures are isolated Linux measurements with synthetic inputs and warm OS
file cache, not physical disk or external supplier timing. Native Intel / RDP use
20 samples per variant; reports use 25 with a repeated baseline; research restore
uses ABBA with 42 samples per variant. The Node store double is not native
IndexedDB timing. Separate production Chromium measurements establish browser
behavior and remain an integration gate; no browser timing is inferred here.

Initial HTML JavaScript assets decrease from 921,835 to 453,676 bytes by preserving
already-designed dynamic sector imports. Gzip-equivalent bytes are 279,573 to
141,026, not measured compressed transfer. All sector content remains emitted;
total JS increases 12,147 bytes with 20 more lazy chunks. This tradeoff reduces
unrelated startup work, not the amount of research content available.

## Evidence and reproduction

- [Market / Native Intel measurements and correctness](PERFORMANCE_MARKET_INTEL_20261024.md)
- [Report snapshot measurements, raw samples and Runtime no-change decision](REPORT_SNAPSHOT_PERFORMANCE_20261024.md)
- [Frontend production-browser / native IndexedDB / Node benchmark definitions](../../frontend/tests/performance/README.md)
- [Full-app isolated startup / ASGI API harness](../../tools/performance/README.md)

The full-app harness separately measures 12 GET cases at 0/100/1,000 Campaign
rows, 40 serial repeated samples plus first requests, and seven fresh startup
processes. It exercises real routing/middleware/local stores without TCP or live
providers. An empty Native Intel store remains unavailable. Service-level and
ASGI-level numbers have different fixtures and overhead and must not be mixed.

## Decisions not to optimize

- Selection-only rank hydration was rejected: it hid malformed history in an
  unselected row. Connection reuse keeps the existing full-cohort derivation.
- Sub-millisecond Campaign DDL proof memoization was not worth a new safety cache.
- Existing Runtime bounded async probes, 2-second cache and singleflight already
  work. Synthetic real-Node subprocess measurements do not justify more model
  calls, looser budgets or another cache.
- Public-provider concurrency, 12-second response / 210-second job limits,
  freshness, coverage and cross-process cache authority were not relaxed.
- No new state framework, microservice, indexed persistence schema, migration,
  blanket memoization or virtualized list was introduced.

## External and measurement boundaries

One opt-in production overview probe in isolated cloud storage completed in
4.225 seconds with unavailable data after four connection failures. No usable
market content was obtained. This is neither supplier latency nor a successful
refresh distribution. It does not demonstrate improvement to live market first
useful information or full refresh time. The process was reaped; no retry load
test was run. Local full-A processing is measured separately on 6,000 synthetic
rows and cannot substitute for external-source measurements.

No production deployment/restart, real user record, account, trade or paid model
was used. Target Windows performance, physical disk latency, sustained memory
growth, real concurrent research sessions and live model TTFT remain separate
acceptance conditions. CI/native-browser success and ordinary merge must be
verified on the actual final SHA; this note does not predeclare them.

## Benchmark maintenance

The first-phase path-filtered performance workflow compared the candidate with
the immutable c16ade baseline on the same runner, exact dependency lock, and browser.
The subsequent bounded core-route experiment explicitly compares against the
first-phase candidate `2393b8416aee16a88a7edd4e3027d913f27fe846` using the
`route-lazy` comparison mode. Both phase-two builds must retain lazy sector
content; changing the reference does not overwrite the first-phase evidence.
It does not add timing thresholds to ordinary correctness CI. Both full source
trees are sibling checkouts so build identity is not dirtied by nested fixtures.
When dependencies or relevant UI contracts intentionally change, review and
version the baseline/fixtures explicitly; do not delete failing checks, silently
update the historical measurements, or claim this fixed comparison is evergreen.
Ordinary source reversion is sufficient rollback; no data conversion is required.
