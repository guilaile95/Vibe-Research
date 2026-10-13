# A12 and A25 public source input adoption · 2026-10-12

## Delivered source contract

Read-only dated archive projections use the existing immutable FactLake, its bounded snapshot/read APIs, raw hashes, failure receipts, and explicit injected transport producer. No scheduler, provider transport, account, model, or credentials are activated. A missing archive has a functioning producer and qualified offline acceptance rather than a permanently empty stub.

- `GET /api/public-research/market-context?as_of=YYYY-MM-DD`: nine index series, CSI300 valuation and treasury curve; explicit business cutoff owned by DailyReview/current or historical snapshot
- `GET /api/public-research/company-inputs?market=A|US|HK&symbol=...&as_of=YYYY-MM-DD`: selected company source families; explicit date input on StockData
- `public_research_extended_service.archive_company_plan(market,symbol,as_of=None)`: A25 frozen input tuple interface; reads one validated immutable image before constructing detached source callbacks
- `public_research_archive.collect(...,transport=...,fixture=...)`: bounded fixed-provider producer; no built-in network transport; raw failures retained

### Exact feature and endpoint mapping

| Adoption | Pinned endpoint | Native source ID | Contract retained |
|---|---|---|---|
| A12 | `em_market_trend` | `em_market_trend` | eight indexes plus Shenzhen composite turnover; 5/20/60/250 session returns, true prior-year-close YTD, moving averages and 250-session extrema; expected/observed/missing dates; no gap skipping |
| A12 | `index_valuation` | `index_valuation` | official CSI300 XLS; total-share and calculation-share PE/dividend yield; signed PE, no cheapness inference; PB unknown |
| A12 | `chinabond_yield_curve` | `chinabond_yield_curve` | exact treasury curve/date, eight tenors, signed percent yield; no price or holding-return claim |
| A25 | `fetch_quote` | `cn_quote_ref` | reused Tencent parser, independently verified stock and Shanghai benchmark returned keys/codes; Asia/Shanghai source timestamps, CNY share quote, raw hash |
| A25 | `fetch_financials` | `cn_financials_ytd` | alternate Eastmoney income statement with returned issuer identity; statutory YTD periods, notice cutoff, raw values and absent deducted earnings retained |
| A25 | `fetch_estimates` | `cn_consensus` | THS annual EPS table: returned issuer page title plus metric/unit heading, fiscal-year end, mean/low/high and analyst coverage |
| A25 | `global_quote_ref` | `global_quote_ref` | single Tencent response, independently verified US/HK stock and benchmark identities, exchange-local clocks, quote currency versus index points, stale and after-cutoff diagnostics |
| A25 | `global_financials_pit` | `global_financials_pit` | GMAININDICATOR notice/end cutoff, period code/duration, quarter versus YTD, reporting currency and excluded/unclassified counts |
| A25 | `yahoo_consensus` | `yahoo_consensus` | exact annual horizon and fiscal end, returned issuer, reporting versus quote currency, EPS bounds/revenue/analyst coverage; no recommendations |

## Qualifications

These are CURRENT_ARCHIVED_POSTHOC inputs, with point_in_time_claim NONE. The cutoff is a selection request, not evidence that this captured revision was available historically. Eastmoney can restate values and replace old notice dates. Treasury data has no complete bond-calendar claim; index calculations use the existing explicit exchange calendar and one raw vintage. Quote clock phases are not authoritative exchange-session calendars. Stock or benchmark dates later than the requested cutoff are retained only as diagnostic evidence and are unavailable to the A25 selected-date basis.

Financial income/profit values are retained with `amount_unit=PROVIDER_RAW_SCALE_UNVERIFIED` and `amount_scale_to_currency_units=null`: pinned code does not establish their monetary multiplier. The UI keeps this limitation adjacent to values. No monetary conversion, TTM arithmetic or valuation is certified from these inputs. Consensus EPS and provider reporting currency are separate from live quote currency. Incomplete identities, dates, metric headings, units, source revisions, malformed spreadsheets or unsupported periods fail closed with raw evidence retained where capture is valid.

## Bounded/offline verification

- Synthetic provider-shaped fixtures include genuine inert BIFF8 workbook bytes, HTML tables, GBK Tencent responses and raw datacenter/Yahoo JSON
- `backend/tests/test_extended_public_research.py` tests fixed producers, raw failure retention, exact date/exchange/issuer identity, session gaps, signed domains, period/notice filtering, bounded XLSX expansion and sparse BIFF cells, one-snapshot A25 callbacks and actual registered API
- `test_exact_registered_api_golden` seeds a temporary FactLake and compares actual registered API output exactly with `frontend/tests/fixtures/extended-public-research.golden.json`; only random observation IDs are normalized
- `frontend/tests/extended-public-research.test.ts` validates that same golden and malformed response rejection, unknown economics, context ownership and rendering contracts
- Mounted desktop/mobile browser coverage is a separate CI-only acceptance artifact; local browser execution is not claimed
- Live data, model quality, real user workflow and collector operation remain NOT_EVALUATED

## Provenance and licensing

Pinned source repository: `simonlin1212/vibe-astock`, commit `d5bf80d2ed1629f8fa602058093f8d41bb0c7ace`. The implementation reads pinned source contracts but does not execute upstream downloaded code. Exact blob identities and links are in the adjacent JSON ledger. Upstream Apache-2.0 LICENSE and NOTICE are preserved at `docs/third-party/vibe-astock-LICENSE` and `docs/third-party/vibe-astock-NOTICE`; existing canonical copies are reused. Provider data licenses are not established by the upstream code license. Raw provider access and redistribution terms are explicitly `PROVIDER_TERMS_NOT_VERIFIED`; committed examples are synthetic.
