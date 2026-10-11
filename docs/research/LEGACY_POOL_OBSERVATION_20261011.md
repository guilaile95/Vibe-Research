# Legacy four-pool date and missingness repair — 2026-10-11

## Scope and evidence

Baseline tree: `55d67fa6cb54432267d5864ac5b4ddc6315b8242` (Draft #400).
Source assessment pinned Simon to [`d643728e79b955dfdcdcd8b0dd362bd7c90c35c8`](https://github.com/simonlin1212/Vibe-Research/blob/d643728e79b955dfdcdcd8b0dd362bd7c90c35c8/.agents/skills/data-access/scripts/sources/eastmoney.py).
Its guards establish useful failure distinctions, but its comments and implementation specifically treat historical `qdate` as the provider's latest session, not the pool's business date. Its missing-pool and empty handling is not adopted wholesale.

Offline baseline fixtures proved:
- Friday rows returned for a Saturday query were labeled Saturday by emotion, overview and whole-review `trade_date`; history's date-format validation accepted that date
- Holiday and pre-open results had the same content-driven date problem
- Secondary pool business/transport failures became zero counts, 100% sealing and normal review/overview status
- The API, AI tool and cockpit research context propagated these facts
- Explicit empty today caused scanning backward to a nonempty response

These are synthetic contract reproductions, not evidence about today's market or permission to repair stored history.

## Compatibility contract

`astock.em_zt_topic_pool` remains a list-returning legacy wrapper with its original failure behavior. All current production aggregation callers migrate to adjacent `em_zt_topic_observation`, sharing the existing `em_get` transport. No provider framework or persistence is added.

The observation retains requested query session, as-of/fetched-at, HTTP status, structured failure reasons, reported date metadata, observed row count and explicit-empty state. Business/HTTP/JSON/shape/invalid-row failures do not become zero. `pool=[]` remains `observed_empty=true`, `observed_row_count=0`, but visible count/rates stay null: it is not independently certified complete-market zero.

Generic `date`/`trade_date` fields are consistency checks only. Without a pinned provider row-binding contract, even matching supplied dates do not establish `date_verified` or `source_business_date`. Nonempty usable responses remain **partial / requested_session_inferred**. `qdate` is stored separately as `provider_latest_trade_date`; a requested session later than it is unavailable. No new date or complete-market authority is invented.

Market aggregation selects one session using the existing local `trade_calendar.observation_trade_date_at` policy (09:30 Shanghai). Weekends, holidays and pre-open resolve through that calendar before any pool request. No first-nonempty search remains. All four pools query the same resolved session. A failed pool nulls its count and only dependent rates; usable unrelated pool facts survive.

Qualified, nonempty observations may be cached without upgrading their partial status. Failures and unexplained empty observations retry. Emotion and overview caches respect session boundaries; outer partial overview caching cannot suppress failed-pool retries. Read-only overview-cache behavior and response top-level shape are preserved for both legacy normal and fully usable qualified-partial results; qualified caching never upgrades partial to normal. Independent review caught and corrected the initial production-shaped partial/read-only cache gap. Whole-review memory freshness also ends at the existing observation-session boundary; disk latest remains stale display data until refreshed. A versioned provenance correction can replace a pre-repair normal latest cache only with all four pools usable and all other components normal; it cannot bypass protection for real failure or current verified data.

## Source-to-sink changes

- `astock.py`: structured observation plus shared legacy transport; strict shape/date/failure distinctions
- `market.py`: calendar resolution, per-pool counts/dependent rates, provenance, warnings and session-aware cache behavior; overview carries emotion provenance and partial status
- `daily_review_cache.py`: a narrow, versioned latest-cache migration permits a fully usable four-pool result whose only limitation is date qualification to replace a legacy unverified normal; actual component envelopes and row counts are checked, and current verified normal/real degradation remain protected. No history snapshot is modified
- `daily_review.py`: preserves partial/unavailable, additive provenance even with `data=null`, and excludes inferred emotion date from whole-review date authority
- `daily_review_lead.py`: inferred display date stays visible as a caveat but cannot become AI lead source `trade_date`
- `decision_cockpit_service.py` / `decision_cockpit_signals.py`: metadata-only unavailable emotion cannot become healthy context or unavailable ladder candidates
- API `/api/market/emotion` and `ai_tools._market(scope=emotion)` retain their existing pass-through contracts, now tested with qualified results
- Frontend count types become nullable; existing lead/detail labels identify inferred dates and unknown ladders. Existing zero-valued saved projections lacking new metadata retain their old display behavior and are not mutated

No BK-11 adapter, byte replay, legal-zero/final ledger, calendar authority, saved review history or formal decision state is changed. No provider/model call or browser acceptance is claimed. This repair does not certify source coverage or manufacture historical business-date proof.

## Bounded acceptance

The new `test_market_pool_observation.py` covers pool/transport/HTTP/rc/JSON/row failures; matching reported date without authority; historical newer qdate; explicit empty in all four endpoints; calendar holiday/weekend/pre-open/09:30 boundaries; unavailable calendar; independent metrics; review/overview/API/AI/cockpit propagation; old projections; and cache retry/session transitions. Existing lead tests additionally verify inferred date is not source truth.

Backend bounded set: market-pool observation, market sentiment, daily review and API, lead projection/API/stream, decision cockpit, fixes, strict limit-up adapter, limit-up replay/shadow Push2 guard, latest-cache persistence/refresh and review history. **559 passed, 3 deselected** under a socket guard and temporary `VR_DATA_DIR`. The three deselected loopback-stream tests explicitly need local socket IO; an initial all-guarded attempt failed those transport fixtures, not pool assertions. Later bounded regressions caught and corrected outer-cache read-only compatibility and API top-level-shape issues before the passing run.

Frontend: production-code SSR for inferred date/unknown counts and old zero-valued records, production empty-ladder JSX, lead-context stream and daily-review refresh tests: **14 passed**. TypeScript `tsc --noEmit` passed. No full pytest, live provider/model, public deployment or real-user runtime validation was performed.

## Prepared full-app browser acceptance (CI-only execution)

The existing `daily-review-refresh.browser.mjs` and its isolated backend harness now support `--pool-provenance-only`. This mode runs the real production market and daily-review aggregation with synthetic provider bytes through the real app API, then ordinary page navigation, detail expansion and explicit refresh. It does not restate the repaired result as a frontend route fixture.

Scenarios: qualified nonempty partial (rows/rates retained), failed secondary pools (unknown counts/rates), and explicit-empty ZT (observed empty metadata and unknown ladder). The frozen observation is Saturday `2026-10-10T04:10:00Z`; the inferred query session/provider latest day is Friday `2026-10-09`, while source business date and whole-review trade date remain unknown. Rendered partial status, inferred-date labels and warnings must survive. External browser/backend connections are blocked; no model interaction is invoked.

After the existing prepared CI job builds frontend and installs Playwright Chromium, run from `frontend`:

```sh
DAILY_REVIEW_SCREENSHOT_DIR="$RUNNER_TEMP/market-pool-provenance-evidence" \
VR_E2E_PYTHON=python \
node --import ./tests/e2e/runtime-env.mjs tests/e2e/daily-review-refresh.browser.mjs --pool-provenance-only
```

Upload that directory on success or failure. It contains three scenario screenshots, `market-pool-summary.json`, backend diagnostics and a failure screenshot when available. The separate `test_daily_review_pool_browser_harness.py` validates all three actual-app API/aggregation scenarios in a socket-isolated subprocess without a browser; it passed locally. JavaScript syntax validation passed. **Rendered browser execution remains pending CI; no local browser launch was attempted.**
