# Explicit experiment comparison

The experiment ledger is a compact, persistent research manifest in the existing
local service facts database. Open **Research Analytics**, **Historical Signal
Validation**, or **Factor Validation**, enter an existing supported research
request, and choose **运行当前输入并记录实验**. Ordinary calculation remains
unrecorded. The explicit action runs the existing evaluator and records its
server-produced receipt and selected metrics; it does not import browser reports
or create another evaluator. Existing unsaved outputs cannot be retroactively
presented as durable experiments.

Select exactly two saved records in the same panel to inspect rule version,
subject, sample, requested window, benchmark, source snapshot, request/input
identity, currency, scope, outcome status, and changed dimensions. Comparison is
read-only and never fetches providers, recomputes a run, modifies formal state,
or selects a winning strategy. Matching numeric values do not prove matching
inputs. Metrics with different identities or dimensions, missing receipts,
undefined values, or incomplete runs are explicitly incomparable; no delta is
calculated. Metric values retain their source units (signal returns are percent;
analytics returns and factor spreads use their evaluator conventions).

## Persistence and boundaries

- At most 500 compact records, each at most 64 KiB, with schema/identity and
  integrity checks. Reaching the limit preserves history and rejects new saves;
  there is no automatic eviction. Raw requests, private full reports, price
  arrays, command lines, Git diffs, executable objects and credentials are absent.
- The same local backend archive is available to clients connected to that
  backend. This is not cloud synchronization between independent installations.
- Pending, running, failed, incomplete and cancelled records remain visible.
  A restart does not infer success. The explicit cancellation action prevents
  accepting late results; it does not promise interruption of an already-running
  synchronous read-only calculation. A completed record cannot be overwritten.
- Source snapshots come from the actual evaluator receipt, not a later lookup
  of the latest pointer. Signal sample and benchmark pagination use one pinned
  snapshot. Missing snapshots remain missing and cannot support comparison.
- Analytics' input fingerprint proves an input identity, not external source
  authentication. RDP observed cross-sections are not historical investable
  universes. These are **descriptive historical research results, not strategy
  validation**, predictions, return rankings, recommendations or formal decisions.
- The recorder concept is informed by Qlib's separation of run metadata and
  results. No Qlib runtime, MLflow service, pickle loading or model training is
  introduced.

The manifest deliberately retains only selected aggregate metrics. Full event
ledgers and detailed reports remain the existing evaluator UI's responsibility.
No real provider/model/trade execution is required by this feature's tests.
