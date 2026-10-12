# Existing archive inspection

Daily Review's **归档证据检查** inspects the page's exact trading date against the
server's already configured FactLake and canonical fact store. It does not offer
an arbitrary path, file browser, upload, import, provider activation or schedule.
The history detail uses its selected historical date; no date is inferred from
an empty response or replaced by today's date.

`GET /api/market/evidence-readiness?trade_date=YYYY-MM-DD` is inside the existing
local API boundary. Extra/duplicate parameters are rejected. Missing sources are
not initialized. Errors do not expose paths, credentials, SQL or provider text.

Qualification stays with `short_term_seal_quality_service`,
`cohort_identity_service`, and the journal's shared pure record qualifier.
Canonical facts are read with the existing bounded, no-sidecar immutable reader.
The three inspections run sequentially; this is not a cross-store atomic snapshot.

Statuses mean unconfigured, missing, insufficient/ineligible, busy, or readable.
Seal-quality partial field coverage is reported as insufficient, not zero.
Journal readable means **at least one selected-day prior metric is readable now**.
The per-metric flags identify which one. It does not mean a prediction was saved,
that evidence existed before an old prediction, that target-day evidence exists,
or that a result/baseline/statistical advantage is established. The separate
calendar-derived window is informational; the journal write endpoint still owns
and rechecks the actual save boundary.

## When evidence is missing

- Seal quality needs the exact-date committed raw receipt and successful replay,
  plus complete fields for each displayed metric.
- Two-day identity needs adjacent, complete eligible v0.2 membership archives;
  a shortlist from Daily Review cannot replace either full list.
- Tomorrow verification needs qualifying facts before the user writes a condition,
  then target-day facts after close. Historical predictions cannot be backdated.

This slice inspects existing archives only. It does not acquire genuine market
evidence, authorize upstream collection, change credentials/settings, or activate
Product Reality. Hash consistency does not authenticate arbitrary upstream data.
Offline fixture acceptance is software evidence, not real-market acceptance.
