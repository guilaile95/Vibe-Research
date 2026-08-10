# Canonical Data Source Contract v0.1

> Status: DS-A1 contract baseline. Architecture and pure-domain validation only.
>
> Authority: [`PRODUCT_NORTH_STAR_V01.md`](../PRODUCT_NORTH_STAR_V01.md), section 30.
>
> Runtime impact: none. This document does not change a provider, route, ingestion
> path, database, scheduler, Data Health API, or canonical source.

## 1. Purpose

Vibe-Research distinguishes a provider response from a fact that may be used in
research, evidence, thesis, or decision workflows:

```text
Provider
  → Raw Observation
  → Normalization
  → Canonical Fact
  → Temporal Qualification
  → Provenance
  → Data Health
  → Cross-source Reconciliation
  → Research / Evidence / Thesis / Decision
```

The governing rule is:

```text
Provider Response != Canonical Fact
```

A response remains a `ProviderObservation` until a dataset-specific contract has
validated identity, semantics, temporal applicability, provenance and quality.
Canonicalization is an explicit domain transition; it is not a field rename.

## 2. Reuse classification

DS-A1 starts from the current repository rather than introducing a parallel data
platform.

| Component | Classification | Decision |
|---|---|---|
| `DataHealthRecord` and its strict validator | `REUSE_EXISTING` | Preserve its exact source/module-health API shape. Do not add fact/provenance fields. |
| Existing Data Health registry, summaries and safe error codes | `REUSE_EXISTING` | Continue to report whether a source/module is currently healthy. |
| Tushare/Eastmoney/BK-11 envelopes | `EXTEND_EXISTING` conceptually | Use their trade-date, legal-zero, coverage and reason-code behavior as inputs to the new contract; do not change their current output. |
| Existing source identifiers, endpoint metadata and timestamps | `EXTEND_EXISTING` conceptually | Wrap in a future observation projection; do not rewrite provider output in DS-A1. |
| `DatasetSpec` / dataset routing | `NEW_CONTRACT_REQUIRED` | No existing type defines canonical/verifier/fallback/backfill roles per dataset. |
| Temporal/PIT/history contract | `NEW_CONTRACT_REQUIRED` | Current freshness logic does not establish fact availability, vintage or historical truth. |
| Provenance contract | `NEW_CONTRACT_REQUIRED` | Existing `source_ids` are useful inputs but do not form a complete trace. |
| Reconciliation policy/result | `NEW_CONTRACT_REQUIRED` | Current limit-up comparison is dataset-specific and has no reusable result contract. |

The pure reference implementation lives in
[`backend/data_contracts.py`](../../backend/data_contracts.py). It is not imported
by a runtime provider in DS-A1.

The North Star names conceptual contracts rather than requiring one class per
heading. DS-A1 keeps the executable surface smaller by composing them as follows:

| North Star concept | Executable v0.1 form |
|---|---|
| `DatasetSpec` | `DatasetSpec` |
| `ObservationEnvelope` | `ProviderObservation` |
| `TemporalSemantics` | distinct temporal fields plus the `TemporalSemantics` field-name enum |
| `ProvenanceEnvelope` | the fact's ordered `ProvenanceLink` entries |
| `SourceRoutePolicy` | `DatasetSpec` invariants over its `ProviderRoute` entries |
| `ReconciliationPolicy` | the fixed `exact-pairwise/v1` function contract plus `ReconciliationResult` |

This is an intentional composition, not a claim that a configurable routing or
reconciliation policy engine already exists.

## 3. ProviderObservation

`ProviderObservation` records what a provider returned and what Vibe knows about
that retrieval. It is evidence for canonicalization, not the canonical result.

### 3.1 Identity

Required identity fields:

```text
observation_id
dataset_id
provider_id
provider_endpoint
provider_symbol
request_fingerprint
```

`observation_id` is required in addition to the work-order fields because a
`CanonicalFact` must refer to stable observation identities. Provider and endpoint
are separate: one provider may expose several endpoints with different semantics.

### 3.2 Temporal fields

The following fields remain separate even when two happen to contain the same
value:

| Field | Authoritative meaning |
|---|---|
| `effective_at` | When the fact applies to, or becomes effective for, its economic/business object. It may be later than publication. |
| `published_at` | When the original publishing authority officially released the information. Unknown is `null`. |
| `observed_at` | When the provider/API states the observation existed, changed or was snapshotted. It is not the local request time. |
| `fetched_at` | When Vibe actually received and recorded the provider response. It is locally knowable and required for an observation. |
| `trade_date` | The exchange trading date explicitly bound by the dataset contract. It is not inferred from `fetched_at`. |
| `report_period` | The reporting/economic period stated by the source. It is not an alias for publication or trade date. |

Unknown temporal fields remain `null`. `fetched_at`, current time, file time or
another provider's timestamp must not fill them. There is no universal ordering
such as `effective_at <= published_at`: a corporate action may be announced before
it becomes effective.

### 3.3 Version and semantics

```text
revision_id
data_version
fetch_semantics
history_mode
adjustment_semantics
revision_semantics
```

The authoritative axes are deliberately separate:

```text
fetch_semantics = by_date | snapshot
history_mode     = by_date | snapshot_with_backfill | snapshot_only
```

`snapshot` is not a `history_mode`. Treating it as one would collapse how data is
fetched into what historical truth is available.

### 3.4 Provenance and quality

```text
source_payload_hash
normalizer_version
quality_status
reason_codes
```

`source_payload_hash` carries the digest recorded by the future raw-observation
boundary, while `normalizer_version` identifies the transformation contract. The
pure DS-A1 value object requires both identifiers but does not possess the original
provider response bytes, so it does **not** claim to recompute or authenticate that
digest. Digest creation and verification belong to the future ingestion/storage
boundary. A non-valid quality state must retain its reason codes. Codes are not
silently sorted, discarded or translated into Data Health error codes.

### 3.5 Null and unknown discipline

```text
UNKNOWN stays UNKNOWN
NULL stays NULL
```

Missing or unknown values must not be converted to `0`, `false`, `[]`, `""`, the
current value, or a historical value. A JSON payload with nested `null` values must
round-trip without coercion.

## 4. CanonicalFact

A `CanonicalFact` is a dataset-qualified result with an explicit reason it may be
treated as canonical.

Minimum fields:

```text
fact_id
dataset_id
canonical_key
canonical_payload

effective_at
published_at
observed_at

canonical_source
source_observation_ids
dataset_contract_revision

revision_id
revision_semantics
provenance_chain
quality_status
reason_codes
reconciliation_status
```

The required answer to “why is this canonical?” is:

1. the fact names the `DatasetSpec` revision;
2. the selected source is the canonical route in that revision;
3. every source observation ID has a matching provenance entry;
4. each provenance entry names the same dataset and an approved provider endpoint;
5. temporal semantics satisfy that dataset's required fields;
6. quality and reconciliation status do not overstate certainty;
7. later revisions append a new vintage rather than rewriting the old one.

DS-A1 validates this self-contained contract shape. It does not yet own an
observation registry, so proving that every referenced observation row physically
exists is a future storage-boundary responsibility (`DS-L1`).

A verifier observation cannot independently become a canonical fact. A canonical
source failure also does not authorize a verifier to become canonical. A permitted
equivalent fallback may supply a fact only when the `DatasetSpec` explicitly grants
that route and provenance still names the fallback source.

## 5. DatasetSpec and routing

Routing is defined per dataset, not as a global provider list.

### 5.1 Provider roles

```text
canonical
verifier
fallback
historical_backfill
```

Each route identifies `route_id`, provider, endpoint, role, semantic-contract ID,
optional retirement time and whether automatic routing is permitted. A dataset has
exactly one canonical route. Verifier and backfill routes are never generic
fallback routes.

An automatic fallback is allowed only when all of the following are explicit:

- the dataset lists the fallback route;
- the route is marked automatically routable;
- it explicitly points to the canonical `route_id` as its equivalence target;
- it uses the same semantic-contract ID as that canonical route;
- it is not retired for the requested time.

There is no universal “A failed, try B, then C” mechanism.

The v0.1 validator deliberately treats the semantic-contract ID as the approved
equivalence boundary. It does not implement a unit-conversion registry or infer
equivalence from provider names.

### 5.2 Routing is not switching

`ROUTING` chooses an already-approved route within one immutable dataset contract.

`SWITCHING` changes which provider defines canonical truth. It requires a new,
explicit governance/config revision with an effective boundary and rationale.

```text
CANONICAL SOURCE SWITCHING MUST NEVER HAPPEN AUTOMATICALLY
```

Provider failure, stale health, null output or one reconciliation mismatch does
not authorize switching. The old provider remains in historical provenance after
a future governance-approved switch.

## 6. Temporal, PIT and history contract

### 6.1 Point-in-time availability

For Vibe's local knowledge, an observation cannot be used at `as_of=T` if
`fetched_at > T`; the pure v0.1 code enforces this for every history mode. An
official-publication PIT claim would additionally require `published_at` to be
known and not later than `T`, but DS-A1 does not yet expose such a policy and
therefore makes no official-publication PIT claim.

An API returning an old report period today does not prove that Vibe or the market
knew the value during that old period. Revision/vintage semantics and publication
availability remain separate requirements.

### 6.2 History modes

#### `by_date`

The provider accepts an explicit business date/period. Requested and returned
coordinates must match. Historical retrieval alone does not prove PIT correctness.

#### `snapshot_with_backfill`

The live/snapshot route and historical backfill route are distinct. Their rows
retain their original provider, endpoint, fetch time, revision and normalizer
provenance. Overlap is reconciled; backfill is not relabeled as live canonical data.

#### `snapshot_only`

Only actually observed snapshots are valid. The local history floor is the first
real observation, not an arbitrary earlier date.

```text
SNAPSHOT_ONLY MUST NEVER FABRICATE HISTORICAL TRUTH
```

A current concept/index/industry membership snapshot must not be copied backward
and represented as past membership. `snapshot_only` cannot declare a historical
backfill route.

### 6.3 History metadata

The v0.1 `DatasetSpec` records, when applicable:

```text
history_floor
history_horizon
revision / vintage behavior
point_in_time_supported
survivorship behavior
source_retired_at
adjustment semantics
max_staleness_seconds
```

Unknown survivorship behavior means the dataset cannot claim a complete historical
universe. A retired source may continue to support historical reads, but cannot
create new observations after its retirement boundary.

For `snapshot_only`, `history_floor` is intentionally not predeclared in the static
specification. Its real floor must be derived later from the first persisted
observation; accepting a configured older floor here would risk fabricated history.

## 7. Reconciliation contract

Reconciliation compares a canonical observation/fact candidate with a verifier;
it does not create a consensus value.

Supported deterministic statuses:

| Status | Meaning |
|---|---|
| `MATCH` | Both sides are complete, temporally comparable and exactly equal under the v0.1 reference policy. |
| `MISMATCH` | Both sides are complete and comparable, but their values differ. |
| `PARTIAL` | Comparable evidence exists, but fields or coverage are incomplete. |
| `UNKNOWN` | A value or comparison basis is unknown; no stronger conclusion is allowed. |
| `SOURCE_UNAVAILABLE` | A required comparison source did not produce an observation. |
| `TEMPORAL_INCOMPARABLE` | Trade date, report period, effective coordinate, vintage or required temporal basis cannot be compared. |

Temporal comparability is evaluated before value equality. Equal numbers from
different trade dates are not a match; different numbers from incomparable dates
are not a mismatch.

The result preserves:

```text
canonical observation ID and value
verifier observation ID and value
comparison policy/version
reason codes
comparison evidence
```

It never averages, selects the newest value, selects the non-null value, deletes a
disagreement, or changes the canonical provider.

The executable v0.1 reconciler is intentionally narrow: `exact-pairwise/v1` uses
JSON equality after temporal, revision, adjustment and quality guards. The policy
ID/version and comparison evidence are explicit in the result. Custom comparators,
tolerances, unit conversion and dataset-specific field coverage are future policy
implementations, not capabilities claimed by DS-A1.

The existing `short_term_daily_facts_v02` behavior is the project reference:
Tushare remains the limit-up fact source; Eastmoney remains a verifier/ladder
source; a count disagreement is visible and degrades the combined result. DS-A1
generalizes that rule without modifying the current code path.

## 8. Dataset examples

These are contract examples, not runtime configuration changes.

### 8.1 `limit_up_count`

```yaml
dataset_id: limit_up_count
fetch_semantics: by_date
history_mode: by_date
canonical: tushare
verifier: eastmoney
fallback: null
switch_on_mismatch: false
```

Tushare and Eastmoney observations are preserved independently. A discrepancy is
reported; one mismatch does not switch the canonical provider.

### 8.2 `valuation_daily`

```yaml
dataset_id: valuation_daily
fetch_semantics: snapshot
history_mode: snapshot_with_backfill
canonical: configured_live_snapshot_provider
historical_backfill: configured_historical_provider
verifier: optional_explicit_provider
```

The placeholder provider IDs intentionally avoid claiming an unapproved runtime
source. Live and backfilled data retain their original provenance across the seam.

### 8.3 `ths_concept_membership`

```yaml
dataset_id: ths_concept_membership
fetch_semantics: snapshot
history_mode: snapshot_only
historical_backfill: null
```

Until independently verified historical evidence exists, only observed membership
snapshots may be stored. No prior membership is inferred.

## 9. Data Health compatibility boundary

Existing Data Health is retained unchanged.

```text
CURRENT
  provider/module/source health
  → DataHealthRecord

FUTURE ADAPTER BOUNDARY
  dataset/observation/fact temporal + provenance + reconciliation health
  → explicit projection to the existing DataHealthRecord shape
```

`DataHealthRecord` currently has a strict fixed key set, registry identity, safe
error codes, timestamp formats, coverage invariants and advice-gate rules. DS-A1
does not extend those keys or change any API.

The future projection may downgrade a source/module health record when a dataset
contract is degraded, but it must not expose raw payloads, invent a trade date, or
replace Data Health's stable public error-code vocabulary.

Known gaps remain explicit: several event-backed sources currently have
`data_trade_date=null` even when descriptive freshness text mentions trade-date
logic. DS-A1 does not fill those fields from the fetch day.

## 10. Local Research Fact Lake boundary

DS-A1 defines responsibilities only; it does not build storage.

```text
Raw Observation      → immutable JSON / Parquet
Normalized Data      → Parquet
Analytical Query     → DuckDB
Operational Metadata → SQLite
```

Candidate datasets for DS-L1 include financial statements, valuation, corporate
actions, instrument universe, index/industry/concept membership, fund holdings,
shareholder/share-structure data and raw observation metadata.

Explicitly excluded here: ticks, full-market real-time order books, an all-news
lake, broker connectivity, execution, scheduling and automated trading.

## 11. Fail-closed rules

- Invalid structured data is rejected or marked degraded; it is not accepted as
  free text.
- Missing provenance cannot produce a valid canonical fact.
- Unknown temporal meaning stays `UNKNOWN`/`null`.
- Missing values are not legal zero without dataset-specific proof.
- Temporal incompatibility produces `TEMPORAL_INCOMPARABLE`, not `MISMATCH`.
- Verifier disagreement is retained rather than repaired.
- Canonical source changes require a new governance revision.
- No DS-A1 type performs network, file, database, scheduler or provider actions.

## 12. DS-A1 implementation and non-goals

Implemented in this slice:

- pure enums and frozen top-level domain records;
- strict validation and serialization-safe round trips;
- dataset-level route validation;
- snapshot-only history guards;
- provenance-qualified canonicalization;
- deterministic exact-pairwise reference reconciliation.

The records are frozen at the dataclass level. Nested JSON payloads are validated
as JSON-safe values but are not deep-frozen; durable immutability belongs to the
future append-only observation store.

Not implemented:

- runtime projection from current providers;
- provider selection or switching;
- real ingestion;
- a DuckDB/Parquet lake;
- database migration;
- scheduler, frontend, broker or trading behavior.

The next phases (`DS-H1`, `DS-L1`, `DS-A2`) require separate authorization.

## 13. Acceptance mapping

| Acceptance | Contract evidence |
|---|---|
| `OBSERVATION_IS_NOT_FACT` | Separate immutable runtime types and explicit canonicalization. |
| `UNKNOWN_NOT_COERCED` | Strict JSON-safe payload preservation and no truthy/default coercion. |
| `TEMPORAL_FIELDS_DISTINCT` | Named temporal contract; all fields serialize independently. |
| `SNAPSHOT_NO_FAKE_HISTORY` | `snapshot_only` forbids backfill and backward use before actual fetch. |
| `DATASET_LEVEL_ROUTING` | Routes are owned by one versioned `DatasetSpec`. |
| `NO_GENERIC_PROVIDER_FALLBACK` | Fallback requires an explicit equivalent route. |
| `CANONICAL_SWITCH_FAIL_CLOSED` | Source mismatch/failure cannot mutate canonical role. |
| `PROVENANCE_CHAIN_EXPLICIT` | Fact source IDs map to dataset- and endpoint-qualified provenance entries; physical row existence is deferred to storage integration. |
| `RECONCILIATION_PRESERVES_DISAGREEMENT` | Result retains both IDs, values, status and reasons. |
| `TEMPORAL_INCOMPARABLE_NOT_MISMATCH` | Temporal comparison precedes value comparison. |
| `DATA_HEALTH_COMPATIBILITY` | Existing fixed DataHealthRecord/API remains unchanged. |
| `EXISTING_PROVIDER_BEHAVIOR_UNCHANGED` | No existing provider/adaptor file is modified. |
| `NO_RUNTIME_PROVIDER_CHANGE` | DS-A1 code is pure and has no runtime integration. |
