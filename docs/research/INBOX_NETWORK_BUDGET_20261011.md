# Inbox network-wait budget — 2026-10-11

## Scope and root cause

The shared Critical Data runtime already evaluates independent network capabilities
concurrently with a 25-second wall-clock budget. Inbox previously reset that budget
for every sequential campaign. `astock.announcements` makes an uncached provider
request with a 20-second transport timeout; repeated campaign reads could therefore
make the Inbox wait roughly 40 seconds for two provider timeouts. Changing test
transport isolation did not fix that production path.

Inbox now owns one existing 25-second network deadline across its campaign loop.
The shared runtime accepts that optional deadline; standalone callers retain their
existing per-campaign budget. No additional concurrency, cache, refresh, persistence
path, or background task is introduced. Admission and snapshot closure are synchronized under a short request-owned lock;
provider I/O and joins never hold it. A worker admitted before closure owns a pending
read and may execute or finish late if preempted. Its timeout is `ERROR`. A worker
not admitted before closure cannot invoke the provider. Late results cannot change
the returned snapshot. This is an admission guarantee, not a physical guarantee that
all provider instructions execute before the deadline.

## Truth and authority boundaries

- Every campaign remains in the snapshot. Local price, Current Thesis, Hard Risk,
  Frozen Decision and derived authorities still run after the network budget expires.
- An admitted network capability that misses the deadline returns `ERROR`.
- A capability not admitted because the deadline expired or the snapshot closed returns `NOT_EVALUATED`.
- Both carry `critical-data:network-budget-exhausted` provenance. Neither means a
  successful empty provider response, clean risk, or complete coverage.
- Completed capability results retain their actual state and literal snapshot time.
- Unknown dependency IDs and malformed local/authority results still fail closed.

The existing composition order is retained: earlier campaigns may receive fresh
provider results while later campaigns have explicit missing coverage. This is a
bounded-wait tradeoff, not a fairness policy. The 25-second value is existing policy,
not an instant-response target. It bounds network waiting, not local storage or pure
projection execution, and it does not bound the lifetime of already-admitted providers.

## Read-only terminology

The Inbox source header says “zero writes,” but the explicit Critical Data activation
contract and production-wrapper acceptance tests require Data Health observation
persistence on reads. This change preserves that existing diagnostic behavior,
including late observations. The inherited Push2 read-only context remains active
inside workers and still prevents unauthorized source refresh/accounting writes.
No formal decision/ledger authority writes are added. The generic header is an existing
documentation ambiguity; this slice does not redefine the observability contract.

## Offline verification

Controlled provider-delay reproduction used three campaigns, a scaled 150ms shared
budget, and 120ms disclosure reads. Before: 365ms, three successful reads. After:
151ms, all three rows retained with disclosure states `USABLE`, `ERROR`,
`NOT_EVALUATED`. These timings demonstrate budget ownership, not live-market latency.

Regression tests cover shared total waiting, no provider invocation from unadmitted workers after closure,
explicit skipped/timed-out results, preserved local price and confirmed Hard Risk,
fast successful campaigns, deterministic deadline reuse, late snapshot immutability,
read-only context propagation, and retained diagnostic observations. All providers
are offline fakes; no real provider, model, credentials, account or holdings are used.

Validation scope: the focused authority/API/Hard Risk regression group passed 149
cases; the final CCD/Inbox group passed 67 cases including the added real
`astock.announcements` transport-boundary fake. `git diff --check` passed.
A broader `pytest backend/tests -m 'not live'` run was stopped by the execution
reviewer after an unexpected external market-provider HTTPS attempt. It is not a
full-suite pass; the quiet output did not identify the exact test or destination.
No retry or alternate transport was used. Full aggregate acceptance remains pending.

Independent review found and repaired a worker-preemption race between admission
and snapshot closure. Two deterministic trace-based regressions verify both sides
of the ownership boundary without delaying return on a provider. Final focused
CCD/Inbox tests: 69 passed after that repair.
