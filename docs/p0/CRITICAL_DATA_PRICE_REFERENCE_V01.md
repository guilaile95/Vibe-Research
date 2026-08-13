# Critical Data Price Reference Capability v0.1

`cap.security.price_reference` answers one narrow question: whether the
existing canonical data chain positively proves that a daily price reference
is usable for a supplied security, campaign, and UTC `as_of`. It is not a
quote service, a provider capability, a valuation signal, or a recommendation.

## Authority chain

A `USABLE` result requires every link below to succeed:

1. TCA1 resolves the completed A-share trade date from the explicit `as_of`.
2. SER1 resolves the six-digit security code to `SSE` or `SZSE` under an
   explicitly pinned policy version.
3. The provider-alias adapter mechanically maps that resolved exchange to the
   current `ds_tushare_daily` identity (`.SH` or `.SZ`).
4. Q1 selects one exact committed publication for `ds_tushare_daily`, its
   canonical trade-date key, and the completed trade date.
5. H2 collects stored evidence and H1 assesses canonical admission, artifact
   integrity, semantic quality, and coordinate freshness; independent S3 raw
   replay must be `MATCH`.
6. The selected artifact contains exactly one row for the provider alias, and
   its canonical `close` is finite and positive.
7. The result cites the real calendar, exchange, alias, selection,
   publication, observation, dataset, normalizer, and health authorities used.

Missing proof at any link forbids `USABLE`. The adapter emits the exact CCD1
dependency-result shape:

```text
dependency_id = cap.security.price_reference
state         = USABLE | NOT_EVALUATED | ERROR
as_of         = the supplied canonical UTC instant
authority_refs
```

`NOT_EVALUATED` means the available authority is insufficient to complete the
evaluation. `ERROR` is reserved for an authoritative integrity or evaluation
failure. The adapter does not manufacture `BLOCKED`, `STALE`, or `UNKNOWN`
merely to cover the CCD1 enum.

## Temporal and identity boundaries

- Publication selection is by the exact completed trade date. There is no
  generic latest-file, latest-retrieval, closest-date, or backward-row search.
- `as_of` is not passed to the dataset as a PIT query. `ds_tushare_daily`
  remains `BY_DATE` and does not claim provider chronology or point-in-time
  reconstruction.
- A source observation fetched after `as_of` cannot support that evaluation.
- A target session's final close cannot be supported by an observation fetched
  before that session completed; TCA1 applies the same 15:00 Asia/Shanghai
  boundary to receipt chronology. Later historical backfill remains admissible
  only when its receipt is visible by the supplied `as_of`.
- An absent security row is `NOT_EVALUATED`; it does not prove suspension,
  blockage, or permission to reuse a previous close.
- SER1 proves exchange routing, not instrument existence, listing status,
  tradability, or data coverage.
- Legacy BSE `4xx`/`8xx` codes remain `NOT_EVALUATED`: SER1 does not establish
  legacy-to-current `920xxx` instrument identity.
- Current BSE `920xxx` codes also remain `NOT_EVALUATED`: TCA1's accepted
  SSE/SZSE calendar provenance does not establish BSE calendar applicability.

## Campaign composition boundary

CDA1A evaluates only the price-reference dependency. Other v0.1 critical-data
capabilities remain independent:

```text
cap.context.market_sector = NOT_EVALUATED
cap.security.disclosures  = NOT_EVALUATED
cap.security.financials   = NOT_EVALUATED
```

Consequently, a real `USABLE` price result does not make a SWING or MEDIUM
Campaign clean. CCD1 still returns `critical_data_state=UNKNOWN` and
`critical_data_evaluation=NOT_EVALUATED` while any required dependency lacks
evaluation. Separate Campaigns for the same security are projected from their
own DDA1 definition and result set; no process-global campaign state is used.

## Non-goals

This slice adds no provider, dataset, Fact Lake schema, migration, scheduler,
runtime assembler, Decision Inbox UI, market-sector/disclosure/financial
adapter, suspension inference, arbitrary TTL, or wall-clock dependency. DDA1
and CCD1 semantics remain unchanged.
