# Versioned shortline research adoption — 2026-10-12

## Scope and authority

This is the P2 software adaptation of Vibe-Astock commit
`d5bf80d2ed1629f8fa602058093f8d41bb0c7ace`, features A04/A08/A10/A11/A41/A42/A46.
It preserves the existing FrozenGate, promotion coverage gate, daily snapshot
ledger, legacy cohort identity and formal decision authority. It is not Day 1,
provider acquisition acceptance, historical point-in-time truth or an execution model.

The data plane reuses existing FactLake immutable raw receipts. There is no second
market ledger, shadow activation, scheduler registration, credential change or
new runtime. Exact-date GET `/api/market/shortline-research` replays raw receipts
through a frozen control snapshot and verifies the source remained unchanged.
Selection is `CURRENT_STORED_POSTHOC`; `point_in_time_claim=NONE`. A local receive
time is not a commit time. Historical results may change after source revisions.

## Implemented contracts

- EastMoney `getTopicZTPool`, `getTopicZBPool`, `getTopicDTPool`: original bytes,
  source business date, explicit source total, unique identities, page accounting,
  source finality and raw field catalogue retained before display pagination.
  Explicit date-bound source total zero is the only positive zero proof. Multi-page
  completeness additionally needs one source revision across all pages.
- Tushare `daily` and `stk_limit`: explicit requested identity batch, same-day
  source dates, CNY/share OHLC and source upper/lower limits. Daily `pre_close` is
  the provider's ex-right reference for that session. Positive source volume is
  required before treating a daily row as traded. Halted, delisted, stale/zero-volume,
  invalid and absent rows remain unknown. This is not an adjusted cross-day series.
  See [the provider's daily contract](https://tushare.pro/document/2?doc_id=27).
- `persist_capture` stores exact bytes, including failed normalization receipts.
  Metadata cannot contain credentials or arbitrary endpoints. `capture_close_batch`
  accepts an explicitly configured transport callback, proves the prior complete
  cohort from receipts, binds the requested identity set, adds today's captured
  limit-up identities, attempts five source families independently, and retains
  failed/partial receipt evidence. It does not configure or activate that transport.
- The upstream five derived close-fetch outputs are adapted to these five shared
  raw source families. Daily metrics, settled-cohort feedback, structure, facts
  and ladder views are reproducible projections of the same receipts, rather than
  five duplicated derived archives. A missing previous full cohort is a producer
  prerequisite, never permission to collect only today's survivors.
- Bounded enumeration uses explicit dataset/date range, COMMITTED receipts and
  hashes. Research requests cap total replay at 64 MiB/2,048 receipts and 512 per
  source family. Exceeding a bound is unavailable, never silent truncation.

## Arithmetic and coverage

Returns and opening premiums are percentage points from the same-session provider
reference, using Decimal arithmetic. Yesterday's full limit-up/broken union is the
fixed denominator; overlap flags and per-pool denominators remain separate. Missing
prices are not non-promotion, losses or zero returns. Full coverage is required for
cohort means/medians/rates. Return coverage and outcome-classification coverage are
separate. Conflicting pool/price evidence cannot classify or promote a member.

Source consecutive-board transitions are descriptive and do not overwrite the
existing gate or treat N-days/M-boards as a streak. Limit status uses complete pool
membership and exact source cent prices, never loose +9.8/-9.8 thresholds.

A04/A41: counts, money/loss effects, opening premiums, consecutive-board premium,
layered transitions, gaps, first/last seal, reopen counts and seal money are exposed.
Fields that do not cover the full relevant denominator remain unknown. Broken-pool
rate and the within-limit-up reopened proportion have different denominators.

A08: 10/20/30/60 fixed prior trading-session windows, midpoint-tie percentile
`(less + 0.5 * equal) / N`. Missing dates are disclosed, never replaced by older valid
dates; full-window coverage is required for the reported statistic.

A10: 20/30/60/90 entry-session windows, complete entry limit-up cohorts, next-session
returns, entry-date last-seal/board/environment grouping. Missing entire entry
cohorts suppress window aggregates, including grouped aggregates. Counts then only
cover known entry cohorts. No queue, fill, cost, slippage or prediction claim.

A11: nonoverlapping recent 10 versus preceding 20 sessions, full-window mean and
median counts, source-price-band share medians. A price band only says both source
limits equal a candidate percentage rounded to cents; it does not certify a legal
regime. Ambiguous/missing matches remain unknown. This preserves the established
Shanghai/Shenzhen universe rather than silently adding Beijing stocks. Descriptive
35% relative-count and 10-point share comparisons are not significance tests.
Field drift compares actual nonempty raw field sets within source/endpoint/request/
normalizer groups and exposes version spans. Missing keys are not retired fields;
null values and empty pools are distinct.

## Manual regime annotations

Upstream regime events are user-entered notes, not automatically verified rules.
The adaptation uses a distinct `user_annotation` FactLake dataset. Explicit POST
`/api/market/shortline-research/regime-events` saves an immutable, idempotent note
with effective/announcement dates, bounded title/note and optional credential-free
HTTP(S) link. No link is fetched. The UI labels every event `USER_AUTHORED_UNVERIFIED`;
future dates are plans, not confirmed policy. Reading spans ±183 effective-date
days around the selected day. Corrections are new notes; originals are not changed.
No archive is initialized by either viewing or saving. Existing local API guards apply.

## Entry points and remaining acceptance

`ShortlineResearchCard` is mounted by the cumulative integrator in current and
history DailyReview views. It supports date-owned cancellation/retry, full-cohort
pagination without denominator changes, history/sample windows, source evidence,
field versions and explicit annotation save. Missing setup lists concrete required
inputs; fixtures are explicitly marked synthetic.

Offline provider-adapter fixtures, temporary-store guarded tests, Python-produced
API golden DTOs, TypeScript validation and build-only component checks cover the
software. The dedicated browser harness is CI-only; no local browser or full local
backend suite was run. Real provider transport/configuration, live collection,
15:35 production scheduling, authentic historical sample accumulation and real-user
acceptance remain separate activation/data gates. They are not claimed complete.
