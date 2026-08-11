# DS-L1-S3 Dataset Selection Evidence v0.1

Task: DS-L1-S3 — Existing Integrated Dataset Canonicalization PoC v0.1

This document records the mechanical dataset selection required by
DS-L1-S3 §17.  It is implementation evidence, not final architecture
authority.

## Candidates Evaluated

### Candidate 1: `cn_a_share_trade_calendar` (Trading Calendar)

- Existing provider path: `backend/trade_calendar.py` (local static JSON
  artifact `cn_a_share_trade_calendar_v01.json`).
- Raw-byte capture availability: **NONE**.  The dataset is read from a
  static local file; there is no existing transport client that fetches
  provider response bytes, so exact-raw capture would require inventing a
  new fetch path (Gate B FAIL).
- Temporal coordinate: trade calendar days; expressible as TRADE_DATE in
  principle (Gate C would pass).
- Revision semantics: no provider evidence available through the local
  artifact (Gate I uncertain).
- PIT evidence: none.
- Verdict: **REJECTED** — fails Gate B (no existing transport to capture
  exact raw bytes without transport reinvention).

### Candidate 2: `northbound_capital_flow` (Northbound Capital Flow)

- Existing provider path: `backend/northbound_capital_flow.py`, uses
  `requests.get` directly against the HKEX JS endpoint.
- Raw-byte capture availability: **NONE**.  The direct `requests.get`
  path has no raw-response capture sink; adding one means modifying the
  existing transport (Gate B FAIL).
- Temporal coordinate: trade date (Gate C would pass).
- Revision semantics: no provider restatement signal (Gate I uncertain).
- PIT evidence: none.
- Verdict: **REJECTED** — fails Gate B (existing transport cannot expose
  exact bytes without transport modification).

### Candidate 3: `ds_tushare_daily` (Tushare Daily Stock Quotes)

- Existing provider path: `TushareClient.query("daily", {"trade_date": ...},
  fields, raw_response_sink=...)` in `backend/tushare_pro_client.py`,
  already used by the BK-11 ingestion path (`bk11_tushare_facts_adapter.py`)
  against `{"trade_date": <YYYYMMDD>}`.
- Raw-byte capture availability: **YES** — `TushareClient.query` already
  accepts `raw_response_sink`, which receives the exact provider response
  bytes at the transport boundary (Gate B PASS).
- Temporal coordinate: `TemporalSemantics.TRADE_DATE` — the exchange
  trading date explicitly bound by the provider contract (Gate C PASS).
- Revision semantics: Tushare `daily` returns unadjusted OHLCV rows for a
  completed trade date, but the provider contract does not establish
  historical revision semantics; the conservative state is
  `RevisionSemantics.UNKNOWN` (Gate I PASS, no revision invented).
- Row identity: `(ts_code, trade_date)` is the authoritative row identity;
  exact duplicates collapse with `exact_duplicate_count`, same-identity
  conflicts fail closed (no silent provider-revision claim).
- Adjustment semantics: `AdjustmentSemantics.UNADJUSTED` — the `daily`
  endpoint serves unadjusted quotes; no adjustment claim is made.
- PIT: `point_in_time_supported = False`; no as_of implementation (Gate H
  PASS).
- No `data_contracts.py` change (Gate D PASS).
- No Fact Lake schema bump; `fact_lake_control_v3` reused as-is (Gate E
  PASS).
- No new runtime dependency (Gate F PASS).
- No new provider credential (Gate G PASS) — `TUSHARE_TOKEN` already
  exists for the BK-11 path.
- Production path unchanged when shadow capture is disabled (Gate I PASS).
- Research value: daily OHLCV cross-sections are the core input of the
  existing short-term facts stack (Gate J PASS).
- Verdict: **ACCEPTED**.

## SELECTED_DATASET

`ds_tushare_daily`

## Contract Summary

- `DATASET_ID` = `ds_tushare_daily`
- `NORMALIZER_VERSION` = `ds-tushare-daily-normalizer-v0.1`
- `DATASET_CONTRACT_REVISION` = `ds-tushare-daily-contract-v0.1`
- `ARTIFACT_SCHEMA_VERSION` = `ds-tushare-daily-parquet-v0.1`
- Provider: `tushare_pro` endpoint `daily`, role `CANONICAL`, single route
- Temporal: `TRADE_DATE`, BY_DATE, no PIT
- Revision: `UNKNOWN` (not established by provider contract); Adjustment:
  `UNADJUSTED`
- Fact Lake schema: `fact_lake_control_v3` (reused, no bump)

## Boundary

- Shadow/offline PoC only.  No scheduler, no production route, no
  automatic capture, no real credential in tests, no real-user DB
  migration, no provider switching.
