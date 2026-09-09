# Dragon-Tiger Market Discovery v0.1 — live contract evidence

审计性质：脱敏、只读、受限请求记录。本文不保存完整上游响应、URL、请求头、cookie、token、账户或持仓数据。

## 运行坐标

- Repository: `guilaile95/Vibe-Research`
- Stable branch: `feature/research-system-v01`
- Stable SHA audited: `68e6e9f952849381f4c88ca11e353c32b5778f55`
- Live audit time: `2026-09-09T20:03:20+08:00`
- Existing request path: repository `em_get()` direct session; serial requests with at least 1.25 seconds between calls
- Provider: existing Eastmoney Data Center
- Report: `RPT_DAILYBILLBOARD_DETAILSNEW`

## Request shape proved

The market-level request used `columns=ALL`, an empty `filter` (no `SECURITY_CODE`), `pageNumber`, `pageSize`, `sortColumns=TRADE_DATE`, `sortTypes=-1`, `source=WEB`, and `client=WEB`. The request returned HTTP 200 with top-level keys `code`, `message`, `result`, `success`, and `version`.

The first response contained `result.data` as a list and `result` metadata keys `count`, `data`, and `pages`.

## Date and sort semantics

- Descending market query, page size 50: `count=267986`, `pages=5360`; page 1 dates were `2026-09-09` only. The maximum source date used by the implementation must be derived from returned `TRADE_DATE`, not from wall clock.
- The same query page 2 spanned `2026-09-09` to `2026-09-08`; dates were non-increasing within the page and across the page-1/page-2 boundary.
- Ascending market query, page size 50: page 1 spanned `2004-06-25` to `2004-07-08`, proving `sortTypes=1` reverses the observed date direction.
- Exact date filter `(TRADE_DATE='2026-09-09')`: HTTP 200, `count=66`, `pages=2`, first page returned 50 rows, and every returned row had the requested source date.

## Pagination semantics

- Page 1 and page 2 each returned 50 rows and had zero overlap by `TRADE_ID` identity.
- Last page `5360` returned 36 rows.
- Expected last-page rows: `267986 - (5360 - 1) * 50 = 36`; actual rows matched.
- Page `5361` returned no data with source code `9201`; no row followed the reported last page.
- The implementation may fetch only a fixed bounded number of pages/rows. If the source reports more rows than the bound, the response must remain explicitly truncated/partial rather than implying full-market completeness.

## Empty versus failure

The source uses a non-success HTTP-200 response shape for no data, so `success=false` alone is not sufficient for classification:

- Valid date-shaped non-trading date `(TRADE_DATE='2026-09-06')`: `HTTP=200`, `code=9201`, `result=null`; classified as `EMPTY`.
- Invalid report request: `HTTP=200`, `code=9501`, `result=null`; classified as provider/request failure (`UNAVAILABLE`), not `EMPTY`.
- Transport errors, non-2xx responses, malformed JSON, or malformed result/data shape remain `UNAVAILABLE`.

## Field and row semantics

In a 50-row market sample, these fields were present: `TRADE_DATE`, `SECURITY_CODE`, `SECURITY_NAME_ABBR`, `EXPLANATION`, `BILLBOARD_NET_AMT`, `BILLBOARD_BUY_AMT`, `BILLBOARD_SELL_AMT`, `TURNOVERRATE`, `CLOSE_PRICE`, `CHANGE_RATE`, `TRADE_ID`, and `SECUCODE`. `EXPLANATION` was non-empty in the sampled rows used for the audit.

- `BILLBOARD_NET_AMT` matched `BILLBOARD_BUY_AMT - BILLBOARD_SELL_AMT` for all 50 numeric sample rows. It is therefore the report-level 龙虎榜买卖净额 used by discovery, not the institution-seat net-buy field from the separate seat-detail reports.
- The sample contained no null or exact-zero `BILLBOARD_NET_AMT`; this is a sample observation, not a schema guarantee. The implementation preserves provider nulls and true numeric zeroes, with fixtures covering both distinctions.
- `TURNOVERRATE` had one null in the sample; missing numeric values stay null rather than being converted to zero.
- The sample contained 45 unique `(TRADE_DATE, SECURITY_CODE)` keys and 5 duplicate groups. Every duplicate group had multiple `EXPLANATION` values. Discovery must retain one row per source record/reason and must not deduplicate on date and security alone.

## Contract decision

`PROVEN_FOR_BOUNDED_READ_ONLY_IMPLEMENTATION`.

The implementation may reuse the existing Eastmoney provider and report only. It must not call the per-security seat reports for each market row, add a provider, calculate a score, create a recommendation, or perform a write.
