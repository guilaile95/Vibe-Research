# Fact Lake Publication Selection Semantics v0.1 (DS-L1-Q1)

Pure selection semantics core for choosing among multiple COMMITTED Fact
Lake canonical publications.

## Core Distinction

    LOCAL PUBLICATION ORDER
    != PROVIDER REVISION ORDER
    != SOURCE CHRONOLOGY
    != POINT-IN-TIME TRUTH.

`vintage_sequence` is a local publication reservation/order sequence only.
It is NOT provider revision, source correction chronology, PIT revision,
as-of truth, or "most correct" fact.

## Modes

- `ALL` — every matching COMMITTED publication for the exact coordinate,
  deterministic local order (`vintage_sequence` ascending with
  publication_id identity tie-break).  No revision claim.
- `PUBLICATION_ID` — one exact committed publication identity; 0 matches
  → `NOT_FOUND`, >1 matches → fail closed.  No fallback to local latest.
- `LOCAL_LATEST` — the COMMITTED publication with the greatest valid local
  `vintage_sequence` among the already-filtered exact coordinate.  It is
  ONLY latest local publication.

No generic ambiguous `LATEST` / `CURRENT` / `BEST` mode exists.

## Frozen Policies

- Committed-only: non-`COMMITTED` candidates are rejected.
- Exact coordinate: `dataset_id` + `canonical_key` + (when supplied)
  `primary_temporal_field` / `primary_temporal_value`; no cross-date or
  cross-report-period selection.
- `vintage_sequence` must be a positive integer (bool rejected); duplicate
  vintage with different publication IDs within the coordinate fails closed.
- Contract revision drift: `LOCAL_LATEST` requires all candidates for the
  coordinate to share one `dataset_contract_revision`, otherwise
  `CONTRACT_REVISION_AMBIGUOUS`; `ALL` preserves each revision;
  `PUBLICATION_ID` surfaces the exact revision.
- No winner rules: normalizer version, artifact schema version, quality,
  reconciliation status, provider and row count never rank candidates.
- Revision semantics is descriptive context only; it never turns
  `LOCAL_LATEST` into provider revision / restatement / PIT truth.
- No synthesized `revision_id` / `data_version`; no wall clock; no PIT /
  as_of reconstruction in v0.1.

## Claims

Every selection output carries explicit negative claims:

    provider_revision_claim = NONE
    point_in_time_claim = NONE

## Implementation Status

- `backend/fact_lake_publication_selection.py` — pure core, no runtime
  integration, no Fact Lake schema change, no `data_contracts.py` change.
- Existing per-dataset query helpers (`query_financial_indicators`,
  `query_tushare_daily`) are NOT rewired in Q1; a later Q2 slice may
  replace ambiguous per-dataset selection logic after independent review.
