# Public event pricing and industry source blocks (A20 / A22)

## Product entry and authority

Intel → **事件定价** (`/intel?tab=events`) and **产业公开数据** (`/intel?tab=industry`). Each source has its own immutable receipt blocks, source time/date, collection and local receipt time, coverage gaps, stale/closed/missing state, units and provenance. “重读归档” only rereads the existing archive. It does not fetch providers. Browser Back/Forward preserves the Intel tab.

`GET /api/public-research?source_id=<fixed-source-id>` uses the existing session boundary, existing FactLake snapshots and hash-verified bytes. No write route, filesystem/URL query inputs, orders, accounts, model calls, collector activation, scheduler, new database or data authority. Latest means **latest stored capture**, selected by exact UTC instant; it is retrospective, not historical point-in-time proof. A malformed latest receipt stays unavailable; older data does not silently replace it. Conflicting equal-instant versions and mixed fixture/acquired subjects fail closed.

The bounded archive index uses UTC capture date in the existing generic observation `trade_date` field. This is explicitly an **archive date**, not economic reporting, publication or exchange-session date. The API reads at most 366 capture days / 128 receipts / 16 MiB total; each original response is at most 2 MiB, 5,000 provider rows and 500 normalized display rows. Exceeding a safety budget fails closed rather than advertising complete coverage. Collection and source dates remain separate fields.

## Producer and provider contracts

The explicit `public_research_archive.collect(lake, source, subject, transport=..., fixture=...)` entrypoint constructs a fixed allowlisted request, requires an existing writable FactLake, passes timeout/byte/redirect limits to an injected transport, archives original bytes and their hash, and records HTTP or normalization failure receipts. It never selects a network client. An authorized runtime can supply its approved public HTTP transport later; this release ships no live activation switch. Acceptance uses deterministic injected bytes only.

| ID | Fixed providers / subjects | Qualified meaning |
| --- | --- | --- |
| public_polymarket | Gamma markets, first 100 requested | Question, condition, market, outcome token identities retained; outcome arrays joined by their own index, never “first means Yes”. Missing question ID stays unknown. Provider outcome price is USD-equivalent per share, collateral not independently verified. Never objective probability. |
| public_kalshi | Public trade-api v2 markets, first 200 requested | Event ticker, exact contract ticker and YES outcome; dollar bid/ask midpoint only if both exist, otherwise dollar last trade, otherwise unknown. Legacy cent fields never silently interpreted as dollars. Open-book zero ask is ambiguous: preserve both source sides, withhold midpoint, show only a distinctly labeled positive last trade when available; otherwise unknown. Closed-market zero values retain their explicit historical state. Volume is contracts, not USD. |
| tw_monthly_revenue | FinMind TaiwanStockMonthRevenue; 2383/6274/2368/3081 | TWD, reporting month, publication date and same issuer/month prior-year denominator. FinMind response does not establish consolidation/restatement comparability: same-source-series change is separately labeled; comparable `yoy_pct` remains unknown. Zero/missing denominator stays unknown. |
| dram_spot_thermo | Community DRAMeXchange transcription; DDR5/NAND TLC/DDR4 | Exact grade only when actually provided; otherwise unknown and partial. USD/chip is a community convention, not independently primary-verified. Not HBM price. |
| cn_commodity_futures | Sina continuous CU0/SN0/AL0/NI0/SI0 | Exact series, SHFE/GFEX, CNY/tonne, dated daily close. Continuous series has no known delivery month or verified roll rule; no cross-contract percentage return is computed. Not company procurement price. |
| hiring_anchor_signal | Fixed Greenhouse/Ashby boards | ATS + board + listing ID dedup; conflicting IDs fail closed. Individual updated/published time is distinct from observation date. Listing removals do not establish hires; counts are not capacity. Workday is unconnected, not zero. |

Each provider block is independent. Event responses are **bounded samples**, never a claim of comprehensive macro-market coverage; no classifier or headline-derived probability is invented. Low/unknown liquidity is visible. Closed/settled prices remain labeled historical market state. API/source status and per-row status are separate, so a closed row cannot make the whole source appear fresh/complete.

## Provenance and licenses

Source contract inventory reviewed at [Vibe AStock d5bf80d](https://github.com/simonlin1212/vibe-astock/tree/d5bf80d2ed1629f8fa602058093f8d41bb0c7ace), particularly `.agents/skills/data-access/scripts/sources/{probability,industry,commodity,hiring}.py` and `datasources/industry_tags.json`. These files were read, never executed. New native Python/React implementations replace upstream orchestration, storage, networking and UI rather than copying a second runtime.

Vibe AStock copyright 2026 simonlin1212, Apache-2.0. Preserve [license](../third-party/vibe-astock-LICENSE) and [NOTICE including original MIT provenance](../third-party/vibe-astock-NOTICE). This adaptation changes source identity, archive-only execution, strict parsers, timestamp/size guards, price semantics and React presentation. Public source data has separate provider terms: all blocks declare `PROVIDER_TERMS_NOT_VERIFIED`; source-code licensing does not grant data redistribution rights. Fixture data is explicitly synthetic and contains no actual account or market data.

Sina's inert JSONP wire shape was cross-checked against `akfamily/akshare/akshare/futures/futures_zh_sina.py` blob `8bf926a9c41227eda1a46ba85ea5b5e82fddb8d4`; JSON extraction does not execute downloaded JavaScript or import upstream code.

## Acceptance and remaining evidence

- `backend/tests/test_public_research.py`: fixed provider-shaped raw → producer → temporary FactLake → **registered production app API**; exact golden equality, economics, malformed/HTTP failures, finite/date/identity budgets, immutable read and negative route boundaries
- `frontend/tests/public-research.test.ts`: strict wire acceptance and corrupted identity/units/time/listings rejection
- `frontend/tests/e2e/public-research.browser.mjs`: CI-only actual production Intel page, desktop/mobile, all six source IDs, visible synthetic/caveat/identity/units/source guards, malformed/failure/retry/missing, stale-response ownership and native history/reload; external/unknown requests and WebSockets fail the harness
- Browser harness build-only is permitted without browser execution. Desktop/mobile runtime results remain **NOT_RUN until CI passes**
- Actual provider acquisition, license/terms assessment for live use, historical corpus, real market quality, model evaluation, scheduling, Day 1, deployment and trading are **NOT_EVALUATED / OFF**
