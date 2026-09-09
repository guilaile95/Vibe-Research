# Dragon-Tiger Discovery R2 — exact-date pagination integrity evidence

审计性质：脱敏、只读、受限请求记录。本文件不保存完整 provider payload、明文 `TRADE_ID`、URL、请求头、cookie、token、账户或持仓数据。

## 运行坐标

- Repository: `guilaile95/Vibe-Research`
- Stable branch: `feature/research-system-v01`
- Stable SHA audited: `6ff711e825536c021a3863756f1335aa6c202ced`
- Audit date: `2026-09-10`
- Provider: existing Eastmoney Data Center
- Report: `RPT_DAILYBILLBOARD_DETAILSNEW`
- Request path: repository `astock.em_get()` direct session, serial calls
- Filter: `(TRADE_DATE='2026-09-09')`
- Page size: `50`

## Evidence distinction

### Unfiltered pagination evidence — context only

The earlier [Dragon-Tiger v0.1 live contract evidence](dragon-tiger-discovery1-live-contract-2026-09-09.md) records an unfiltered market query with `count=267986/pages=5360`. Its page 2 crosses from `2026-09-09` into `2026-09-08`; therefore its page-1/page-2 identity non-overlap does **not** prove completeness for the production exact-date path.

That unfiltered evidence remains valid for the bounded market-query/date-order contract, but is not reused as exact-date pagination proof.

### Exact-date pagination evidence — R2 proof

The R2 audit made real, serial requests for exact-date page 1 and page 2, then repeated the same two-page read once. Only counts and SHA-256 summaries of sorted identity sets were retained.

| field | run 1 | repeated run |
|---|---:|---:|
| page 1 HTTP / code / success | `200 / 0 / true` | `200 / 0 / true` |
| page 2 HTTP / code / success | `200 / 0 / true` | `200 / 0 / true` |
| page 1 row count | `50` | `50` |
| page 2 row count | `16` | `16` |
| source count | `66` | `66` |
| source pages | `2` | `2` |
| page 1 `TRADE_ID` set size | `50` | `50` |
| page 2 `TRADE_ID` set size | `16` | `16` |
| cross-page intersection size | `0` | `0` |
| cross-page union size | `66` | `66` |
| union size equals source count | `YES` | `YES` |
| rows without `TRADE_ID` | `0` | `0` |

The identity-set summaries were stable across the repeated execution:

- page 1 set SHA-256: `bfdd3237d519d17b300a70064e99e87e78c11955e8fb868d2b04427367ae8d47`
- page 2 set SHA-256: `a0660ce815242639fc7889823c3bc4f34c1cfbd508281338ace4be0d76505e3e`
- union set SHA-256: `fc6c7361a48a9fd4f916aa26f69fa81466169815fff3a48734f8bfd772818fb9`
- repeated execution identity sets stable: `YES`

The provider therefore supports this observed exact-date two-page contract. R2 still adds a runtime integrity guard: observed live non-overlap is evidence, not a substitute for checking every future response.

## R2 implementation acceptance

For each raw record collected during pagination, production code derives the existing `source_record_identity` and maintains a cross-page `seen` set. It does not deduplicate by `(TRADE_DATE, SECURITY_CODE)`. Same security/date rows with distinct `TRADE_ID` values remain separate source records.

For an untruncated read, `COMPLETE` now additionally requires:

1. provider `count/pages` and each page length are valid;
2. page metadata is consistent across the read;
3. every reported source page was read;
4. raw row count equals source count;
5. unique source-identity count equals source count; and
6. no source identity overlaps another read page (or another row in the read window).

An overlap fails closed as `UNAVAILABLE` with the fixed limitation `SOURCE_PAGE_IDENTITY_OVERLAP`. A bounded/truncated read remains `PARTIAL` with completeness `TRUNCATED`; an overlap found in its read window adds the same integrity limitation and is never silently accepted as complete.

## No-write boundary

This audit and the R2 read model are read-only. No Candidate, Campaign, Evidence, Decision, account, portfolio, trade, scheduler, alert, broker, or other formal state write is performed.
