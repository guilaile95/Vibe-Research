# DS-A2 ashare-lake Semantic Gap Review v0.1

> **Status: READY_FOR_INDEPENDENT_REVIEW (draft).** Documentation-only; no code/provider/DB/PR/production route changed.
>
> Upstream authority: `rootSunc/ashare-lake`, `main`, `a2713c26d0b2ea84b2721d93788fb83be7feac95`; isolated clone `C:\tmp\ashare-lake-a2713c2-new`. Vibe authority: DS-A1 exact head `96d8236c2cb249e7b2b763bd68890da8d1ed6efd`.

## 1. Repository, license and scope

`git ls-remote` fixed `HEAD` and `refs/heads/main` to the pinned SHA. The repository has 42 executable `DatasetSpec(` registrations (`src/ashare_lake/domain/datasets.py`) and overall Apache-2.0 (`LICENSE`). The repository notice identifies vendored `tdxpy 0.2.7` as MIT; this is a dependency notice, not a change to the overall license. No upstream code is copied or vendored here. Provider data terms remain separate (`docs/legal-and-data-sources.md`). All upstream conclusions cite this SHA by exact path/symbol/lines or stable blob URL, e.g. [`DatasetSpec`](https://github.com/rootSunc/ashare-lake/blob/a2713c26d0b2ea84b2721d93788fb83be7feac95/src/ashare_lake/domain/datasets.py#L46-L167).

`COPY_CONCEPT`, `ADAPT`, `REJECT`, `NOT_APPLICABLE`, `UNKNOWN` are decision labels. PIT labels are `PIT_SAFE`, `PARTIAL`, `NOT_PROVEN`, `NOT_SUPPORTED`, `UNKNOWN`.

## 2. Executive conclusion

ashare-lake is a benchmark for registry-driven ingestion, PIT/vintage reads, historical-universe policy, adjustment-at-read, canonical-plus-snapshot separation and layered audit. It is not a Vibe runtime dependency: DS-A1 requires immutable `ProviderObservation`, explicit provider roles, temporal/revision semantics, provenance chains, deterministic `ReconciliationResult` and fail-closed canonicalization. Upstream normalized rows and latest-fetched compaction do not satisfy those invariants.

## 3. A–S work-order review

| ID / task dimension | Classification | PIT | Exact pinned evidence and conclusion |
|---|---|---|---|
| **A Repository / Lake Layout** | ADAPT | UNKNOWN | `storage/layout.py::init_data_layout` L8–26 creates raw/staging/curated/derived/meta; raw is optional and no raw writer is evidenced. |
| **B Storage Formats** | ADAPT | UNKNOWN | `storage/parquet.py::StagingWriter/CuratedWriter/compact_dataset` L18–134; Parquet normalized, JSON state/findings, SQLite manifest, DuckDB views; no CSV/Arrow persistence found. |
| **C DuckDB / Query Plane** | ADAPT | PARTIAL | `query/reader.py::load` L254–367 composes semantics, but `scan` L370–383 bypasses PIT/universe/adjustment; `query/views.py` globs Parquet without commit/as-of relation. |
| **D Dataset Identity / Schema Registry** | ADAPT | UNKNOWN | `domain/datasets.py::DatasetSpec` L46–167; `domain/schemas.py::DATASET_SCHEMAS/PRIMARY_KEYS` L623–742; registry tests L21–49. No independent schema-version/migration identity. |
| **E Raw Observation Preservation** | REJECT | NOT_SUPPORTED | `layout.py` only creates raw; no raw body/header/request/hash writer. `source_snapshots.py::SnapshotStore.write` L33–59 stores validated normalized Parquet and cleanup L116–167 deletes old runs. |
| **F Provenance** | ADAPT | PARTIAL | `schemas.py::PROVENANCE/with_provenance` L7–9, L781–790 gives source/version/fetched_at; ADR-0003 L13–31 separates backup snapshots. Missing observation ID, payload hash, endpoint/request and normalizer chain. |
| **G Temporal Fields** | ADAPT | PARTIAL | Schemas contain trade/report/announce/as_of/publish/fetched fields (`schemas.py` L34–46, L193–203, L331–350, L391–409, L531–557) but no unified valid/system/availability time. |
| **H PIT / Lookahead Controls** | ADAPT | PARTIAL | `query/reader.py::_apply_pit_filters` L226–251 and `load` L323–334 enforce as_of; `adapters/eastmoney/fundamentals.py` L22–27 and `docs/datasets/schema.md` L326–331 admit current-revision backfill lookahead. |
| **I Revision / Restatement Handling** | COPY_CONCEPT | PARTIAL | `domain/schemas.py::PRIMARY_KEYS` L682–714 retains announce vintages; `tests/unit/test_pit_vintages.py` L48–148 selects historical/latest/all vintages. No universal revision ID or old-vintage backfill. |
| **J Instrument Universe** | ADAPT | PARTIAL | `query/universe.py` L25–45, L127–216 applies prefixes/list-delist/status but fails open when instruments/status missing (L183–205); early ST coverage incomplete. |
| **K Membership** | ADAPT | PARTIAL | `derive/industry_index.py::_members_as_of` L167–178, `adapters/sw/industry_history.py::expand_sw_industry_as_of` L146–175, and `adapters/cni/index_constituents_history.py::expand_cni_constituents_as_of` L155–179 use backward intervals; coverage and known-at timestamps are incomplete. |
| **L Corporate Actions / Adjustment** | COPY_CONCEPT | PARTIAL | `reader.py::_apply_adjustment` L171–223 and ADR-0004 L13–50 store hfq/derive qfq; default `strict_adj=False` may return factor=1.0 with inexact marker. |
| **M Provider Architecture** | ADAPT | UNKNOWN | `docs/adr/0005-source-routing-vs-switching.md` L22–38 separates routing/switching; bars gap-fill missing PKs (`steps/bars.py` L185–255, L324–392); registry/steps/config disagree for corporate actions (`domain/datasets.py` L393–400; `steps/events.py` L27–79; `configs/ashare-lake.example.toml` L216–220). |
| **N Incremental Ingestion** | ADAPT | UNKNOWN | `orchestrator/manifest.py::Manifest` L63–120 tracks runs/batches/retries/heartbeats; `start_batch` L170–178 uses operational `INSERT OR REPLACE`, not immutable observation ledger. |
| **O Data Quality** | ADAPT | UNKNOWN | `quality/audit.py::_collect_lake_findings/run_audit` L144–273 is layered; `validate_dataframe` L762–774 uses strict=False cast and warning findings need not block. Vibe disposition: `REUSE_EXISTING` Data Health, `ADAPT_UPSTREAM_CONCEPT` for fact-level checks, and `NEW_FACT_LEVEL_CONTRACT` only where DS-A1 canonicalization needs a deterministic gate; do not replace or extend the existing Data Health record shape in DS-A2. |
| **P Cross-Source Reconciliation** | ADAPT | UNKNOWN | `quality/source_diff.py` L20–223 compares primary/latest backup with tolerances and ≤500-row sampling; mtime/inner-join sampling is not complete temporal reconciliation. |
| **Q Schema Evolution** | ADAPT | UNKNOWN | `schemas.py::DATASET_DATA_VERSION` L15–31 tracks semantic value version (`daily_bars=v2`), but no schema compatibility/migration registry. |
| **R Operational Metadata** | ADAPT | UNKNOWN | Manifest SQLite plus JSON watermarks/findings and snapshot directories; no single committed metadata authority. |
| **S Test Architecture** | ADAPT | UNKNOWN | Registry/PIT/membership/engine tests exist (`tests/unit/test_dataset_registry.py`, `test_pit_vintages.py`, `test_membership_history.py`, `tests/integration/test_engine.py`), but no DS-A1 raw/provenance/revision/reconciliation contract suite. |

A–S classification counts are authoritative for this review: `COPY_CONCEPT=2` (I, L), `ADAPT=16`, `REJECT=1` (E), `NOT_APPLICABLE=0`, `UNKNOWN=0`.

### 3.1 Storage, query, ingestion and evolution details

- **Formats and writers/readers:** normalized staging and curated data are zstd Parquet written by `StagingWriter`/`CuratedWriter` and read through Polars plus DuckDB views (`storage/parquet.py` L18–134; `query/views.py` L67–127). JSON is used for watermarks and exported findings (`storage/state.py` L23–91; `quality/audit.py` L260–336), not as an immutable provider-payload archive. SQLite stores run/batch operational state (`orchestrator/manifest.py` L63–232). CSV is a calendar seed input, and no Arrow IPC/Feather persistence was found. These roles are evidence, not a recommendation to add every format.
- **DuckDB boundary:** the persistent DuckDB file is a view catalog over Parquet, with typed empty views and read-only query connections; no indexes were found. Direct Parquet glob views do not select a committed file set or apply revision/as-of semantics. DS-L1 may copy view-on-Parquet and read-only SQL guarding, but it needs a committed/as-of relation before a DuckDB result can be called canonical.
- **Incremental and atomicity boundary:** `steps/common.py::incremental_window` L20–47 advances from watermark + 1; `storage/state.py` writes monotonic JSON state using a temp file and `os.replace`; compaction sorts by `fetched_at` and keeps the last row per PK (`storage/parquet.py` L100–133). `storage/atomic.py::write_parquet_atomic` L18–42 is single-file atomic, while `steps/finalize.py::_compact_locked` L173–220 publishes multiple partitions, then watermarks and views without one cross-file transaction. This is not immutable repeat-ingest revision detection or run-atomic publication.
- **Schema evolution boundary:** `DATASET_SCHEMAS`/`PRIMARY_KEYS` are centralized and the daily-bars v2 script is an explicit dry-run/apply migration (`scripts/migrate_daily_bars_volume_v2.py` L71–144), but `validate_dataframe` uses `strict=False` and drops extra columns (`domain/schemas.py` L749–774). No general compatibility matrix, migration registry/ledger, schema activation transaction, or old-reader/new-writer policy was found.
- **Test boundary:** upstream tests meaningfully cover atomic file replacement, watermark truth/concurrency, PIT vintages, membership history, schema validation, migration idempotency, DuckDB paths and SQL guards. They do not prove immutable raw replay, unchanged/changed repeat-ingest behavior, multi-partition crash consistency, committed-snapshot isolation, generic schema compatibility, or DuckDB multi-vintage as-of behavior. DS-L1 must add those end-to-end failure-injection contracts rather than mechanically copy upstream tests.

## 4. Semantic-gap matrix (25 task-book contracts)

| # | Required contract | Status | Exact pinned evidence / implication |
|---:|---|---|---|
| 1 | ProviderObservation | ABSENT | No immutable observation envelope; only normalized rows (`schemas.py` L781–790). |
| 2 | CanonicalFact | ABSENT | No DS-A1-like immutable fact with contract revision/provenance chain. |
| 3 | DatasetSpec | PARTIAL | `domain/datasets.py::DatasetSpec` L46–167 exists but lacks DS-A1 route/temporal/revision invariants. |
| 4 | Provider roles | PARTIAL | ADR-0005 routing/switching L22–38; source strings do not encode canonical/verifier/fallback/backfill roles. |
| 5 | TemporalSemantics | PARTIAL | Multiple date columns, no unified enum/availability model (`schemas.py` L34–557). |
| 6 | Required temporal fields | ABSENT | No per-dataset required temporal-field gate equivalent to DS-A1. |
| 7 | PIT availability | PARTIAL | `query/reader.py::_apply_pit_filters` L226–251 and `load` L323–334 enforce a partial boundary; documented backfill lookahead remains. |
| 8 | Revision/vintage | PARTIAL | `domain/schemas.py::PRIMARY_KEYS` L682–714 and `tests/unit/test_pit_vintages.py` L48–148 retain and query announcement vintages; no universal revision identity. |
| 9 | Provenance | PARTIAL | source/version/fetched_at exists; no chain/observation identity. |
| 10 | Payload hash | ABSENT | No raw payload content hash. |
| 11 | Normalizer version | ABSENT | `data_version` is value semantics, not normalizer lineage. |
| 12 | Request fingerprint | ABSENT | No request identity persisted with rows. |
| 13 | Canonical switching governance | PARTIAL | `docs/adr/0003-canonical-curated-with-source-snapshots.md` L13–43 and `docs/adr/0005-source-routing-vs-switching.md` L22–38 forbid automatic switching, but multi-source registry truth conflicts. |
| 14 | ReconciliationResult | PARTIAL | Source diff exists (`quality/source_diff.py` L20–223), not DS-A1 status/evidence contract. |
| 15 | Data Health compatibility | PARTIAL | Layered audit (`quality/audit.py` L144–273) but warning/cast fail-open behavior. |
| 16 | Raw immutable observation | ABSENT | raw directory only; snapshots normalized and retained 14 days. |
| 17 | Normalized Parquet | UPSTREAM_HAS | `storage/parquet.py::StagingWriter/CuratedWriter/compact_dataset` L18–134 validates, partitions and compacts Parquet. |
| 18 | Canonical Fact persistence | ABSENT | Curated rows are storage projections; no immutable DS-A1 fact persistence. |
| 19 | DuckDB query | PARTIAL | Views/read-only SQL exist, but plain glob lacks committed/as-of/revision selection. |
| 20 | SQLite operational metadata | PARTIAL | Manifest is SQLite (`orchestrator/manifest.py::Manifest` L63–120), while watermark, registry and findings remain split. |
| 21 | Historical universe | PARTIAL | `query/universe.py::_all_a_symbol_expr/tradable_symbols_on_date/apply_universe_filter` L25–216 implements the filter with fail-open and missing-coverage caveats. |
| 22 | Historical membership | PARTIAL | `derive/industry_index.py::_members_as_of` L167–178, `adapters/sw/industry_history.py::expand_sw_industry_as_of` L146–175, and `adapters/cni/index_constituents_history.py::expand_cni_constituents_as_of` L155–179 implement as-of interval joins; history is limited and known-at is absent. |
| 23 | Adjustment semantics | UPSTREAM_HAS | hfq is persisted and qfq derived at query time (`query/reader.py::_apply_adjustment` L171–223; `docs/adr/0004-store-hfq-derive-qfq-at-query.md` L13–50). |
| 24 | Schema evolution | PARTIAL | `domain/schemas.py::DATASET_DATA_VERSION` L15–31 and `scripts/migrate_daily_bars_volume_v2.py` L71–144 provide a local semantic version plus one explicit dry-run/apply migration; no general schema version, compatibility matrix, registry or migration ledger exists. |
| 25 | Incremental ingestion | PARTIAL | `steps/common.py::incremental_window` L20–47, `storage/state.py::StateStore` L16–91 and `storage/parquet.py::compact_dataset` L78–134 implement watermark/compact ingestion; no immutable repeat-ingest revision or committed-snapshot boundary exists. |

## 5. Anti-rewheel decision table

| Component | Upstream exact evidence | Upstream semantics | Vibe equivalent/current state | Classification | Reason | Contract conflict | Reuse risk | DS-L1 implication |
|---|---|---|---|---|---|---|---|---|
| DatasetSpec registry | `domain/datasets.py` L46–167 | Registry drives fetch/history/partition | DS-A1 DatasetSpec adds routes/temporal/revision/governance | ADAPT | Central metadata prevents drift | Source strings and IDs cannot express DS-A1 authority | Conflicting route truth | Translate; do not depend on upstream runtime. |
| HistoryMode | `domain/datasets.py` L761–780 | by_date/snapshot/backfill | Same DS-A1 enum/invariants | COPY_CONCEPT | The three modes align | None if DS-A1 backfill-route guards remain | Low | Copy policy and negative tests. |
| Raw observation | `layout.py` L8–26; no writer | raw dir only; snapshots normalized | DS-A1 ProviderObservation immutable/hash-addressed | REJECT | No payload/request envelope exists | Cannot reproduce what provider returned | False auditability | Implement the smaller DS-A1 capture layer. |
| PIT/vintages | `reader.py` L226–251; schemas L682–714 | announce-date filter + latest vintage | DS-A1 as_of/availability/revision gate | ADAPT | Genuine per-dataset PIT pattern | Historical backfill can contain current revisions | False PIT claims | Enable only for evidence-backed datasets. |
| Provenance | `schemas.py` L7–9,L781–790; ADR-0003 | source/version/fetched_at + backups | DS-A1 ProvenanceLink chain | ADAPT | Useful row projection | Missing hash, endpoint, request and observation IDs | Lineage loss | Add observation-envelope fields. |
| Universe/membership | `universe.py` L25–216; as-of helpers | list/delist/status and intervals | DS-A1 survivorship/temporal semantics | ADAPT | Historical filtering logic is reusable | Missing inputs fail open and known-at is absent | Survivorship bias | Gate missing coverage as UNKNOWN/blocker. |
| Adjustment | `reader.py` L171–223; ADR-0004 | hfq stored, qfq query-time | DS-A1 adjustment semantics | COPY_CONCEPT | Raw price remains recoverable | Default inexact fallback is too weak | Silent unadjusted values | Make research reads strict. |
| Routing | ADR-0005 L22–38; bars gapfill L185–392 | gap-fill missing keys, no switching | DS-A1 ProviderRoute roles | ADAPT | Routing/switching distinction is sound | Registry, steps and config disagree on authority | Wrong canonical owner | One versioned route authority per dataset/mode. |
| Manifest | `manifest.py` L63–120 | SQLite run/batch/retry/heartbeat | Vibe DB/migration safety is pending DS-R1 | ADAPT | Operational audit is useful | It is not an immutable fact/commit ledger | Duplicate authority or DB regression | Reuse only after DS-R1. |
| Audit/diff | `audit.py` L144–273; `source_diff.py` L20–223 | layered findings/tolerance sample | Existing Data Health + DS-A1 reconciliation | ADAPT | Findings expose gaps | Sampling/post-ingest warnings cannot certify facts | False green or lost disagreement | Map into fact gates; keep Data Health authoritative. |
| Parquet/compaction | `parquet.py` L78–134 | PK latest fetched_at wins | DS-A1 immutable fact/revision | ADAPT | Storage primitive is efficient | LWW is not semantic canonicalization or revision | History loss | Compact only after fact creation; preserve revisions. |
| DuckDB/live | `reader.py::scan` L370–383; `mcp_server/live.py` | raw/live paths bypass semantics | Deterministic-first query boundary | NOT_APPLICABLE | Useful upstream operational mode | It cannot be called a canonical fact read | Mislabelled facts | Observation-only and explicitly labelled if ever used. |

## 6. Eight required questions

1. **What would Vibe unnecessarily reinvent if it ignored ashare-lake?** Registry metadata, history modes, append-vintage PIT reads, adjustment-at-query, universe/membership intervals, curated-vs-snapshot separation, and run/batch audit scaffolding.
2. **What does ashare-lake not solve?** Immutable raw observations, full provenance, known-at availability, global strict PIT, route authority, schema migration governance and canonical arbitration.
3. **What can be safely copied?** HistoryMode, vintage retention, adjustment derivation, interval universe/membership logic, snapshot separation and layered tests.
4. **What must be adapted?** DatasetSpec, PIT, provenance, provider routes, quality, source diff, manifest and schema/data-version policy into DS-A1 fields/invariants.
5. **What must be rejected?** Normalized rows as raw; latest-fetched compaction as canonical winner; default inexact adjustment; fail-open universe; 14-day snapshots as evidence.
6. **Does this make DS-L1 smaller?** Yes: one raw observation envelope, one dataset, one route, one revision path, one as-of query, minimal Parquet/DuckDB read—no 42-dataset copy.
7. **What minimum new infrastructure is still required?** See the independent block below: raw capture/hash, observation/provenance, temporal/route metadata, revision detection, reconciliation status and DS-R1-safe commit manifest.
8. **What must wait for DS-R1?** Storage/manifest authority, migration/backup behavior, retention/legal terms, provider metadata mapping and any production routing/dependency choice.

### MINIMUM_NEW_DS_L1_INFRA

Do not choose a concrete PoC dataset in DS-A2. Minimum infrastructure is: immutable raw payload + content hash; `ProviderObservation` identity; endpoint/request fingerprint; normalizer/schema version; temporal coordinates; revision detection; `ProvenanceLink`; `ReconciliationResult`; committed file manifest; watermark tied to committed files; DuckDB read of committed/as-of facts; crash/restart tests.

## 7. Exact acceptance field block

```text
UPSTREAM_REPOSITORY_IDENTITY_VERIFIED = TRUE (rootSunc/ashare-lake; default main)
UPSTREAM_EXACT_SHA_PINNED = TRUE (a2713c26d0b2ea84b2721d93788fb83be7feac95)
UPSTREAM_LICENSE_VERIFIED = TRUE (Apache-2.0 overall; vendored tdxpy 0.2.7 MIT notice; no code copied)

DS_A1_EXACT_HEAD_USED = TRUE (96d8236c2cb249e7b2b763bd68890da8d1ed6efd)
DS_A1_INDEPENDENT_REVIEW = APPROVE / SATISFIED PER TASK INSTRUCTION
DS_A1_INVARIANTS_PRESERVED = TRUE

RAW_OBSERVATION_GAP_REVIEW = COMPLETE
PROVENANCE_GAP_REVIEW = COMPLETE
TEMPORAL_GAP_REVIEW = COMPLETE
PIT_GAP_REVIEW = COMPLETE (GLOBAL CLASSIFICATION = PARTIAL)
REVISION_GAP_REVIEW = COMPLETE
UNIVERSE_GAP_REVIEW = COMPLETE
MEMBERSHIP_GAP_REVIEW = COMPLETE
ADJUSTMENT_GAP_REVIEW = COMPLETE
ROUTING_GAP_REVIEW = COMPLETE
RECONCILIATION_GAP_REVIEW = COMPLETE
STORAGE_GAP_REVIEW = COMPLETE
QUERY_PLANE_GAP_REVIEW = COMPLETE
SCHEMA_EVOLUTION_GAP_REVIEW = COMPLETE
INGESTION_GAP_REVIEW = COMPLETE
DATA_QUALITY_GAP_REVIEW = COMPLETE (REUSE_EXISTING DATA HEALTH; DO NOT REPLACE)

ANTI_REWHEEL_DECISION_TABLE_COMPLETE = TRUE (9 REQUIRED COLUMNS)
SEMANTIC_GAP_MATRIX_COMPLETE = TRUE (25 TASK-BOOK CONTRACTS)
MINIMUM_NEW_DS_L1_INFRA_IDENTIFIED = TRUE
PENDING_DS_R1_ITEMS_EXPLICIT = TRUE

COPY_CONCEPT_COUNT = 2
ADAPT_COUNT = 16
REJECT_COUNT = 1
NOT_APPLICABLE_COUNT = 0
UNKNOWN_COUNT = 0

NO_DS_A1_REGRESSION = TRUE
NO_PRODUCTION_CODE_CHANGE = TRUE
NO_RUNTIME_PROVIDER_CHANGE = TRUE
NO_DB_CHANGE = TRUE
REAL_USER_DB = NOT_TOUCHED

LOCAL_TESTS = NOT_RUN (DOCUMENTATION-ONLY)
EXACT_HEAD_CI = NOT_RUN / NOT_COMPLETED AT DOCUMENT AUTHORING (PUBLICATION CI IS RECORDED ON THE DRAFT PR AND FINAL HANDOFF)
PRODUCTION_DEPENDENCY = REJECT FOR CURRENT SLICE; BENCHMARK ONLY
FINAL_STATUS = READY_FOR_INDEPENDENT_REVIEW (DRAFT)
```

## 8. PENDING_DS_R1_CONFIRMATION

- Confirm existing Vibe storage/manifest authority; no second SQLite/Parquet authority.
- Confirm zero-write normal-open, migration, backup immutability and downgrade protections.
- Confirm providers can emit observation ID, endpoint, request fingerprint, payload hash and normalizer version.
- Confirm route ownership per dataset and ingestion mode; resolve source conflicts.
- Confirm historical universe/membership coverage or retain UNKNOWN.
- Confirm data/schema migration authority for units, adjustments and restatements.
- Confirm provider raw-data retention/redistribution terms; Apache-2.0 does not license payloads.

## 9. Stop boundary

DS-A2 is complete for independent review. Further implementation, dependency adoption, provider changes, schema activation, real-user DB migration, production routing or DS-L1 requires separate authorization after DS-R1.
