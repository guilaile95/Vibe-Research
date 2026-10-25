# Market acceptance: bounded diagnosis, 2026-10-25

## Evidence identity and result

Base: `8c141d554507b6228627271f1ef759485040591d`. This lane changes only
the explicit opt-in measurement harness and its offline tests/documentation.
No application data source, completeness policy, retry limit, concurrency,
cache lifetime or source cooldown was changed. No production deployment,
private data access, credentials or paid API calls were performed.

The current Linux cloud observation failed on the first full-A page:
three `ConnectionError` attempts, then the existing source cooldown stopped
further Eastmoney work. One independent industry-fund-flow request also failed.
The aggregate completed in 3.788 seconds with breadth `unavailable`, null stock
and valid counts, zero sector rows, and its worker reaped. Four HTTP attempts
were recorded; none returned a provider payload. This is **not** a performance
improvement or proof that the providers themselves are down. The executor's
restricted outbound environment cannot establish current Windows availability.
No route override, policy bypass or repeated probe after failure was attempted.

The raw artifact was recorded with the v2 page diagnostics before the later
exception-cause-type extension; it does not contain that extension's fields.
The extension is covered by offline failure-path tests, not a second live run.

## Recovered target-machine evidence, not a new Windows test

The prior original JSON and JSONL were recovered from the delivered raw evidence
ZIP. Their SHA-256 values match the separate context record:

- JSON: `db68e64deeff785a0468e067afd6628bb39b650ece0ea40a64d88a8d0a5f6b70`.
- Events: `828c9d46dd038447665d67607ab1d47a99d89dabe9ea11e00939c692fa7f389e`.

That one Windows sample returned `SOURCE_REFRESH_PENDING` at 12.188 seconds and
finished at 24.391 seconds with breadth unavailable. Its 90 rows were
**industry fund-flow records from `data.10jqka.com.cn`**, produced by `_sectors`,
not 90 stocks or complete stock-market coverage. The full-A path used Eastmoney.
Its 12 HTTP 200 responses were followed by three connection failures and a
source-cooldown exception. Existing safeguards correctly did not publish the
incomplete stock list as a complete market result.

The old events lacked page numbers, response totals and page row counts.
Therefore they cannot prove which distinct page failed, how many stocks were
received, whether the provider capped page size, or whether retries explain any
of the HTTP 200 responses. Those details must not be reconstructed by guessing.

## Minimal diagnostic improvement

The existing opt-in probe now records allowlisted page number, requested size,
provider total, raw row count, unique observed identities and overlap counts.
It counts identities in memory but never emits security codes, response rows,
query strings, credentials or raw exception messages. Bounded exception type
chains distinguish DNS/TLS/proxy/network failures when those types are present.
Diagnostic failures preserve the original response and remain diagnostic only.
The output identifies the actual platform instead of hardcoding cloud scope.
Network and diagnostic processing times are separate; end-to-end times still
include instrumentation. Observed unique counts are not certified completeness.

## Existing alternate paths: no silent substitution

- `push2delay` is already an alternate Eastmoney host, not an independent vendor.
  Its shared cooldown must not be bypassed after refusal or repeated failures.
- The existing BK-11 Tushare adapter targets a completed trade date and has
  explicit credentials/permission requirements. Its code universe excludes BSE,
  unlike the current Shanghai/Shenzhen/Beijing full-A snapshot. It cannot be
  silently substituted for the same realtime breadth contract. No credential
  was inspected or request sent.
- The existing BaoStock research probe is historical evidence, not current
  production acceptance. Its date-bound daily data and custom TCP transport
  require separate availability, universe and resource validation. No new
  installation, live call or automatic source switch was made.
- Local immutable research snapshots can support their declared historical
  scope, but cannot be relabeled as current full-market observations.

These contracts favor diagnosing the actual target connection first, not
introducing a new provider/cache architecture to disguise an inaccessible source.

## Official 2027 calendars

On 2026-10-25 UTC, the [SSE official closure listing](https://www.sse.com.cn/disclosure/dealinstruc/closed/list/)
still showed the 2026 annual notice and 2026 holiday notices. Targeted searches
did not yield a verifiable 2027 SSE/SZSE annual pair. The
[SZSE official notice listing](https://www.szse.cn/www/disclosure/notice/general/)
and known [2026 annual notice](https://www.szse.cn/disclosure/notice/general/t20251222_618087.html)
timed out on direct web retrieval; search-index evidence surfaced 2026 material.
This bounded search does not prove no 2027 notice exists. No dates were inferred
or added; the existing 2024–2026 coverage and expiry behavior remain unchanged.

## Gate and remaining acceptance

The unchanged snapshot paging, breadth, snapshot concurrency, market remediation,
source guard and calendar suites passed: 335 tests. New diagnostic regression
checks cover page/total/unique distinctions, repeated responses, invalid counts,
unrelated bodies, bounded parsing, failure-message redaction and preservation of
successful responses when diagnostics fail. Their CI result belongs to the
integrated task's final exact-head receipt, not this local evidence note.

Still needed: a source-accessible authorized environment, safe repeated samples
across actual use, provider-date/coverage verification and browser-visible first
useful content. A successful HTTP response alone is insufficient. Dino was
offline at this round's environment check, so no new Windows reliability claim
is made. If all providers remain unavailable, report that state and its verified
cause without weakening the completeness contract.
