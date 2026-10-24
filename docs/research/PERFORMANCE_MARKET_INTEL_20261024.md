# Measured market / Native Intel local performance — 2026-10-24

## Scope and baseline

Baseline: `c16ade49174a26597de05244ac9f70d2855c590a` on
`feature/research-system-v01`. Measurements below are isolated Linux cloud-executor
results, **not the user's Windows machine or live provider response distribution**.
No deployment, real user data, model calls or production service restart.

The same standalone harness, deterministic input sizes, normal production SQLite
settings and installed DuckDB version were used before and after. Each case has
one separately recorded first call, 20 repeated measured calls, and (for SQLite)
one separate SQL-instrumented call. P95 is nearest-rank, not the fastest sample.
OS caches were not forcibly purged. Other performance workers paused during this
measurement window. Instrumented-call durations are not mixed into percentiles.

## Implemented changes and measured results

All times are milliseconds. These are local function paths with real SQLite or
Parquet, not HTTP/browser end-to-end timings.

| Path / synthetic scale | Before P50 / P95 | After P50 / P95 | CPU P50 before / after |
| --- | ---: | ---: | ---: |
| Native Intel trending, 50 items × 20 historical observations, top 20 | 44.38 / 48.78 | 8.73 / 10.59 | 44.38 / 8.73 |
| Native Intel trending, 500 items × 20 observations, top 20 | 422.15 / 439.91 | 49.45 / 59.87 | 422.10 / 49.45 |
| Native Intel status, same 500-item SQLite file | 22.63 / 27.59 | 7.15 / 7.56 | 22.62 / 7.16 |
| Full-market filtered page, 5,000 securities / 322,255 bars / 65 dates | 160.38 / 196.96 | 97.72 / 102.42 | 638.75 / 279.56 |

Whole response hashes match between versions for every measured fixture, including
rank history, count, source status, data coverage and replay receipts. All 20
samples within each version also produce the same response hash. Native status
hash normalizes only the synthetic temporary database filename.

### Native Intel rank reads

`trending()` previously initialized the schema and opened two SQLite connections
for each ranked item, before final sorting/slicing. The full 500-row cohort is
still derived and validated. A bounded batch now reuses one initialized SQLite
connection and the **same extracted single-item derivation body**. The original
single-item API remains a wrapper over that body.

- 500-item case: connections **1,012 → 14**, executed SQL statements
  **22,747 → 2,787**, rank derivations **500 → 500**.
- 50-item case: connections **112 → 14**, statements **2,497 → 537**.
- Source/item identity, full history, disabled/re-enabled, unknown, stale,
  off-list and no-rank states are retained. Existing malformed rank/timestamp and
  database-corruption failures are not hidden.
- The SQLite lock now spans the bounded batch (maximum 500 IDs); there is no
  network call inside it. This reduces setup overhead, not the selected data.
- An initially faster “hydrate only returned rows” experiment was rejected:
  unselected corrupt history could stop raising an existing error. Those earlier
  experimental timings are **not** the accepted result above.

### Native Intel status

Display, proxy and status fields reuse the same operation-local configuration
read, and directory size is read once. No persistent cache or TTL was introduced.
The separate item-count read is retained to preserve the existing error path.
SQLite connections fall **66 → 25**, statements **1,669 → 601**. The independent
freshness-count helper still performs its own existing configuration read.

### DuckDB full-market computation

One full-market request previously repeated the historical window aggregation
three times for coverage, page and filtered count. It now materializes the
computed cross-section once in a private in-memory temporary table, then applies
identical coverage, filter, sort and pagination queries.

- Window aggregation executions **3 → 1** per request.
- Manifest/artifact hash, metadata validation and source identity checks remain
  on every call. There is no cross-request unchecked cache.
- The private connection closes in `finally`, including exceptions; its temporary
  table does not survive the request.
- The temporary table retains one row per security, not the historical bar set.
  Precise native-memory peak/target-device resource limits remain unmeasured;
  CPU reduction is measured, not an assertion that every resource decreases.
- Discovery still pins the same immutable snapshot across all pages. This patch
  does **not** skip page receipts, coverage validation or historical data.

## Market overview boundaries, not a fabricated speedup

The unmodified full-A source path requests 500 rows/page. A synthetic 6,000-row
input therefore uses 12 page calls. With network and pacing deliberately replaced
by fixed in-memory page responses, production mapping/coverage calculations cost:

| Local path | P50 | P95 |
| --- | ---: | ---: |
| Full-A page mapping + complete row/identity validation | 54.35 | 62.64 |
| Application-cold breadth (includes mapping and defensive copies) | 167.64 | 174.66 |
| Warm breadth from the existing snapshot cache | 63.14 | 65.98 |
| Warm market cloud aggregation | 60.80 | 65.57 |

These times **exclude** real networking, provider pacing, retries and subprocess
startup. No optimization claim is made for these unchanged paths. Empty and
failed snapshots remain unavailable and uncached; insufficient coverage remains
partial. The one opt-in live probe failed to obtain usable provider data, so it
cannot establish provider latency percentiles or a first-useful-content speedup.

The existing overview workflow remains: full-A snapshot/breadth, four emotion
pools, then industry funds. It retains the 12-second response bound, one shared
refresh, 210-second hard worker lifetime, existing request budget/throttling,
cache qualification and process reap. Internal breadth completion is distinct
from client-visible aggregate completion. No limits or coverage checks were
loosened to manufacture better timings.

## Reproduction

Use the project-pinned Python environment and a clean baseline checkout. Each
script creates and removes only its own temporary synthetic data directories,
strips inherited application credentials and does not start application lifespan.
The offline scripts reject network connection/DNS helpers; the live probe is
separate, explicit opt-in and must not be used as a throughput test.

```sh
python tools/performance/benchmark_native_intel.py --source-root ../baseline --rows 500 --samples 20 --output before-intel.json
python tools/performance/benchmark_native_intel.py --rows 500 --samples 20 --output after-intel.json
python tools/performance/benchmark_native_intel.py --source-root ../baseline --operation status --samples 20 --output before-status.json
python tools/performance/benchmark_native_intel.py --operation status --samples 20 --output after-status.json
python tools/performance/benchmark_full_market.py --source-root ../baseline --samples 20 --output before-rdp.json
python tools/performance/benchmark_full_market.py --samples 20 --output after-rdp.json
python tools/performance/benchmark_market_compute.py --samples 20 --output market-local.json
```

The full-market harness creates a real synthetic Parquet fixture outside the timed
region, rather than timing CSV ingestion. Its fixture includes stale securities,
insufficient history, filters, null metrics and a bounded 1,000-row page.

## Correctness gates and remaining limits

Focused contracts cover stable ordering/ties, bounds, full history, unchanged
cohort count, selected **and unselected** malformed ranks, naive timestamps,
corrupt databases, all rank-state families, request-local configuration reuse,
one materialization per full-market request, immutable receipt pagination,
per-call validation and connection closure. The focused local gate passed **58 tests**. The broader Native Intel / RDP /
Discovery / market gate passed **645 tests, with 2 existing environment/legacy skips**. The final integrated CI result and stable SHA belong to the task's final
report, not this baseline measurement note.

The target Windows machine, live provider latency distribution, browser-visible
market refresh speed, real concurrent user workloads and native peak memory still
require their respective environments. Network call count is unchanged by these
three optimizations. No model/token-cost tradeoff was made. Higher-risk cross-
process snapshot sharing, source concurrency increases, validation removal and
bulk-import redesign were deliberately not introduced.
