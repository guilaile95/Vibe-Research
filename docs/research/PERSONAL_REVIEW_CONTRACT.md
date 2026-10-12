# Personal review: local research companion

## Authority and privacy

The existing Trade Ledger, account opening/corrections and Formal Trade Attribution
remain authoritative. Personal notes and pattern cards are append-only companions
in `VR_DATA_DIR`; no trades, holdings, account policy or Frozen Decisions are
written. No provider requests, model tools or model-page context consume this
feature. Existing explicitly requested portfolio-AI behavior is unchanged.

`GET /api/personal-review` assembles the journal in the existing Trades page.
`PUT /api/personal-review/assessments/{trade_id}` creates an optimistic revision;
`PUT /api/personal-review/patterns/{pattern_id}` appends a version. Identical retry
content is idempotent. GET never creates a database or archives a price source.
Reads use the foundation bounded private SQLite image and preserve source bytes/metadata, including checkpointed WAL; active journals and unsafe link/reparse paths fail closed. Revision/factor row and byte limits fail closed rather than truncate. Episode structure, gross, PA1 net and input fingerprints use one frozen ledger image, with final source-drift rejection.

Local data backups already cover these files through the existing SQLite suffix
collector. No legacy VA files are scanned or imported: A40 requires actual legacy
input and a separately scoped explicit adapter, preview and backup.

## Episodes and denominators

A single account is identified by its canonical ACCOUNT_OPENING event. Initial
inventory is not assumed zero without that event. Legacy inventory is consumed
until flat and that incomplete initial episode is not scored. Exact executions
are ordered by normalized execution instant, creation instant and trade ID;
opposing directions at one instant are excluded, same-side split fills supported.
Later flat-to-flat cycles support additions and partial exits. Over-sells, future
executions, correction-affected instruments and mixed campaign identities are
explicitly unscored. Unknown attribution is displayed, never invented as formal.

Net results and input fingerprints use canonical PA1 exact-trade accounting.
Unknown fees yield unknown net results; a stored historical zero is only
LEDGER_RECORDED, not independent evidence of free trading. Last 10/20/50 refers
to closed eligible episodes, not rows; coverage and insufficient sample counts
are explicit. Win-rate excludes flat results and has its own denominator. The
weekly companion is a local Shanghai-calendar aggregation, excluded from AI.

Environment, close-of-day board rank, judgment, execution, rule violations and
stop scenarios are timestamped retrospective self-assessments. These are not
verified facts, formal compliance, causal attribution or effective trading rules.
An entry-price-to-stop scenario is separate from current risk and equity; no
risk ratio is invented across unaligned data times.

## Pattern versions

Versions take effect on the next **Asia/Shanghai calendar day**, not trading day.
The server sets save/effective time. No backdating, in-place editing or duplicate
same-day publication. Revisions preserve definitions and effective windows.
An assessment can associate only the version effective at that execution date;
association itself remains retrospective. Episode summaries use the opening
execution's self-assessment. Version-performance counts explicitly disclose that
self-selection; they are not unbiased strategy backtests.

## Qualified daily-price bounds

`GET /api/personal-review/episodes/{id}/excursion` reads only pinned local Research
Data Plane artifacts. Exact full-interval MFE/MAE is unknown: daily bars do not
prove intraday holding order or execution opportunities. Entry and exit dates
are excluded. Missing calendar sessions, suspended/missing bars, complex
multi-entry/partial-exit episodes or unqualified price basis do not receive
fabricated return metrics. An unadjusted archive can show only a raw interior
CNY/share range.

Explicit public-market factor capture import has two POST endpoints:
`/api/personal-review/price-basis/preview` and `/price-basis/archive`, each with
`{"raw_json": "...capture JSON..."}`. The Trades UI provides file selection,
preview and explicit archive confirmation. This never requests credentials or
calls a provider. The capture schema is `personal-review-adjustment-capture.v1`:

- `code`: exact six-digit security
- `raw_snapshot_id`, `raw_artifact_sha256`: existing immutable RDP identities
- `provider_id`: matches the raw artifact provider
- `provider_revision`, `adjustment_basis_id`, `source_id`: captured source lineage
- `captured_at`: timezone-qualified, nonfuture capture instant
- `formula`: `ADJUSTED_PRICE_EQUALS_RAW_TIMES_FACTOR`
- `price_unit`: `CNY_PER_SHARE`
- `rows`: ordered unique trading sessions; each contains `trade_date`, finite
  positive `factor`, matching `provider_revision` and `adjustment_basis_id`

The exact capture bytes are SHA-256 identified and archived append-only. The frontend checks response schemas and exact input SHA binding before committing state. A malformed successful write response retains the draft and disables duplicate saves until explicit reread. Factor writes can be reconciled through `GET /api/personal-review/price-basis/receipts/{sha256}` without repeating the write. Same
identity/different bytes conflicts; duplicates, missing sessions, inconsistent
vintages/units and invalid adjusted numeric ranges fail closed. The immutable raw
snapshot must contain corresponding complete symbol/session bars. Full entry-to-
exit factor coverage establishes a **provider-asserted archived research basis**,
not independent corporate-action verification, PIT availability or total return.

For a simple buy/sell cycle, the entry execution reference is multiplied by its
same-capture entry factor. Each interior high/low uses its session's factor.
`bounded_mfe_pct` is max(0, high/reference−1); `bounded_mae_pct` is
min(0, low/reference−1), expressed in percent. These are interior-daily excursion
bounds relative to the first entry, never adjusted versions of canonical P&L.
The exact fields `mfe_pct` and `mae_pct` stay unknown. Split/dividend synthetic
fixtures test conversion separately from unchanged canonical accounting.

## Verification scope

Focused backend tests use temporary synthetic ledgers and socket-denied HTTP
requests. Frontend helper/production component render tests require no browser.
The dedicated CI workflow runs desktop/mobile production-component interactions
against denied-by-default mock endpoints. That is mocked API browser acceptance,
not real-market, live-provider or browser-to-real-database acceptance. No Day 1
observation or deployment is activated.
