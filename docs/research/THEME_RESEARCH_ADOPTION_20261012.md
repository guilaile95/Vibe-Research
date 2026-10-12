# Theme research adoption contract v1 — 2026-10-12

Scope: A07 and A43 from `simonlin1212/vibe-astock` at
`d5bf80d2ed1629f8fa602058093f8d41bb0c7ace`, specifically
`shortline_themes.py`, `shortline_boards.py`, and `shortline/weekly.ts`.
The implementation extends the existing FastAPI / DailyReview surface; it does
not introduce the upstream Node runtime, a second database, or another collector.

## Delivered software

- GET `/api/market/theme-research?trade_date=YYYY-MM-DD`, current and historical
  DailyReview cards, read-only reload, strict response/date checks and request
  ownership guards
- Per-stock dated provider-editorial tag tree and first-board list; labels remain
  separate and exact (delimiter splitting and whitespace trimming are explicit)
- Exactly five official exchange sessions, with holiday gaps preserved, observed
  heat, tag counts and count-based competition ranks; all ties and disappeared
  tags retained, not only today's survivors
- Prior-session tagged-member continuation with fixed cohort provenance; today's
  broken/down outcomes of those dated members are explicitly labelled as cohort
  outcomes, never invented current-day editorial attribution
- All daily highest-consecutive-board ties, de-duplicated by first appearance in
  the fixed window, with same-response adjusted-price lineage when available
- Actual immutable FactLake receipts and pure provider adapters, not placeholder
  in-memory data. Pool replay/selection is shared with P2's
  `shortline_research_archive.load_research_days`

## Input and authority contracts

`short_term_theme_capture.store_ths_theme_capture` consumes **already captured**
original THS page bytes and validates the complete batch before persistence.
Each original response is stored through `FactLake.store_observation` with its
page index/count, ordered hashes, capture batch identity, provider, source total,
normalizer and synthetic-fixture flag. Every stock's epoch first-seal timestamp
must belong to the requested Shanghai trading date and valid session time.
Empty undated pages, duplicate identities, changing totals and partial pagination
are rejected. No industry fallback, synonym merge, current-label historical
backfill, or secret-bearing transport metadata is permitted.

Dataset `research_shortline_themes`, normalizer `ths-theme-pages-v1`, capture
manifest `theme-capture-manifest-v1`. The source is THS's
`https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool` response shape.
The labels are `PROVIDER_EDITORIAL_NOT_COMPANY_FACT`; publication time and
source finality remain unknown unless actually established. A post-close local
capture is not proof of a source-final market snapshot.

`store_tencent_forward_capture` consumes one original Tencent daily-K response
for an exact stock identity, never an HTTP client. Dataset
`research_shortline_leader_prices`, normalizer
`tencent-forward-captured-series-v1`, capture schema `leader-price-capture-v1`.
Only that symbol's `qfqday` is accepted, never an unadjusted `day` fallback.
Strict ordered exchange-session dates, positive finite OHLC, OHLC consistency
and explicit volume are required. Zero-volume rows remain unknown.

Prices are CNY/share. A raw response hash identifies a common **provider-asserted
within-response** forward-adjustment basis, not independently verified corporate
actions. Separate captures are never joined into one series. Price changes are
not total return, executed P&L, a trading recommendation, or historical PIT truth.
The exact appearance-date base and each session's close are required; missing
endpoints never silently become a shorter-period return. Peak/drawdown require
all window prices and at least two observed points.

The archive service reads one frozen control snapshot, verifies original blobs,
replays versioned adapters, and checks the source control identity again before
returning. It exposes `CURRENT_STORED_POSTHOC` and `point_in_time_claim=NONE`.
It does not accept caller paths, refresh, as-of or arbitrary selection parameters.
Source IDs, hashes, dates, provider, capture times and fixture flags remain visible.
Synthetic and real inputs cannot be mixed into one result.

## Metric definitions and unknown states

- Theme count: distinct stock IDs with the exact label. Multi-label stocks appear
  once in each applicable label; labels are overlapping sets
- Coverage denominator: all distinct qualified pool stocks, never theme membership
  totals. A missing tag means zero only with complete pool and tag coverage;
  otherwise absence is null and present counts are lower bounds
- Theme concentration: largest exact-tag stock count / all qualified pool stocks,
  only with complete pool and attribution coverage and nonzero denominator
- Rank: one plus number of labels with strictly larger counts, including all
  ties. Partial days are unranked; observed/top-three day counts are not forecasts
- Continuation: yesterday's attributed stock IDs still in today's complete pool /
  yesterday's attributed member count. Partial prior attribution is labelled
  sample-only. Membership source dates are retained even if today's label changed
- Highest-board leader: exact source consecutive-board maximum, all ties retained;
  unknown board heights prevent an authoritative maximum, not silently default 1
- First board: source consecutive count exactly 1, independent of rebound patterns

## Setup and non-activation boundary

The software requires an existing initialized FactLake selected by the existing
`VR_FACT_LAKE_ROOT` configuration. Production setup must provide source-dated
complete pool captures through P2 and complete THS raw pages; adjusted prices are
optional and remain unknown when absent. Provider access/terms and credentials
must be arranged separately through the existing authorized runtime. These
adapters are not automatically registered with providers or schedules.

GET never initializes a database, persists observations, starts a collector,
requests a provider/model, or changes formal decisions. No real provider/model
request, credential configuration, runtime switch, schedule, merge or deployment
was performed for this lane. No historical as-of accessor is offered because the
archive lacks an immutable historical local-commit frontier.

## Acceptance evidence

- 57 focused Python checks across this lane plus shared P2/listing dependencies:
  exact raw capture, every-row source-date rejection, pagination/duplicate guards,
  holiday-calendar validation, all ties, multi-label denominators, missing-day
  nulls, yesterday-only labels, changed-label continuation, missing/paused closes,
  price basis, exact registered API golden, read-only source-byte invariance,
  mutation-race fail-closed, and response-parameter whitelist
- Four focused Node contract checks use the committed actual-API synthetic golden
- TypeScript project compilation passed
- Production component CI adapter build passed; local browser execution NOT_RUN
- CI-only Playwright lane added for desktop/mobile, real production component,
  partial/absent data, wrong-date data, late parsed response after abort, cleared
  dates, unmount, read-only/external-request audit, and screenshots

These checks are synthetic software evidence. They do not establish real market
reliability, provider completeness, live model quality, or Day 1 usage acceptance.

## Independent-review repair pass

The repair rejects pre-close complete pool sets (they are not close-pool lower
bounds), checks fixture identity on every used up/broken/down source, suppresses
contradictory overlapping-pool broken-rate/outcome claims, and finite-checks all
price-return arithmetic. Missing or overflowing returns stay null.

Receipt replay verifies the entire observation identity, provider/endpoint/symbol,
normalizer, metadata allowlist, source-total proof, and ordered page/hash manifest.
The shared `list_observations(max_payload_bytes=...)` enforces budgets **before**
blob reads. Bounds: 200 theme receipts, 128 MiB theme receipt window, 32 MiB theme
batch, 10,000 rows, 64 tags per stock, 256 characters per label, 1,024 distinct
projected tags, 50,000 window memberships; price receipts are limited to 1,000 /
64 MiB and each price response to 1 MiB. Oversize fails closed; nothing is silently
truncated. Strict UI checks cover every rendered provenance operand and actual
calendar-date validity. CI scenarios exercise malformed response → recoverable
error → successful retry on the production component without a React crash.
