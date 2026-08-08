# BK-11 A-Share Trade Calendar Source Evidence v0.1

## 1. Executive Decision

**Overall**: GO for Blocker-1 closure.

**implementation_allowed (trade calendar)**: true — the offline
`previous_trade_date` module and data artifact may be committed and used.

**implementation_allowed (layered_promotion_rates)**: false — closing
Blocker-1 does not close the remaining eight blockers. Production
layered-promotion-rate computation remains blocked.

**Blocker-1 status**: closed. The unique source, licensing boundary,
supported years, update mechanism, and interface are now defined and
implemented for the 2024-2026 range.

## 2. Scope and Non-goals

**In scope**:
- Selecting the unique authoritative source for A-share trading dates.
- Recording SSE and SZSE official annual holiday announcements for 2024-2026.
- Reconciling SSE and SZSE arrangements.
- Generating an offline JSON artifact of confirmed trading days.
- Implementing `previous_trade_date(current_trade_date: str) -> str | None`.
- Writing tests for the module contract.

**Not in scope**:
- `layered_promotion_rates` or any BK-11 metric computation.
- Limit-up pool source adapters.
- Final snapshot producers.
- API endpoints, frontend, database, scheduler.
- Historical backfill, T+1 closed-loop.
- Runtime network calls or third-party calendar dependencies.
- Integrating the calendar into existing Data Health or market code.

## 3. Primary Source Policy

```
primary authority:
  上海证券交易所 (SSE) 年度及补充休市公告
  +
  深圳证券交易所 (SZSE) 年度及补充休市公告

calendar policy:
  SSE/SZSE official consensus
```

The following sources are **not** accepted as primary authority:
- 国务院办公日历 (State Council general calendar)
- 普通工作日历 (generic work calendars)
- AkShare
- exchange_calendars
- pandas_market_calendars
- Third-party financial websites, blogs, forums

These may be used for offline cross-check only (see §Cross-check).

**Consensus rule**: SSE and SZSE arrangements must be identical for each
year. If any year has a discrepancy or missing evidence, the entire
calendar is NO-GO and the module is not implemented.

## 4. SSE Source Evidence

### SSE 2024

| Field | Value |
|---|---|
| exchange | SSE |
| year | 2024 |
| announcement title | 关于上海证券交易所2024年部分节假日休市安排的通知 |
| announcement date | 2023-12-26 |
| reference number | 上证公告〔2023〕47号 |
| source URL | https://www.sse.com.cn/disclosure/announcement/general/c/c_20231226_5733939.shtml |
| retrieved_at | 2026-08-03T00:00:00Z |
| verification status | verified (direct from sse.com.cn) |

Covered holidays (closed ranges):
- 元旦: 2023-12-30 to 2024-01-01
- 春节: 2024-02-09 to 2024-02-17 (weekend closures: 02-04, 02-18)
- 清明节: 2024-04-04 to 2024-04-06 (weekend closure: 04-07)
- 劳动节: 2024-05-01 to 2024-05-05 (weekend closures: 04-28, 05-11)
- 端午节: 2024-06-10
- 中秋节: 2024-09-15 to 2024-09-17 (weekend closure: 09-14)
- 国庆节: 2024-10-01 to 2024-10-07 (weekend closures: 09-29, 10-12)

Weekend-closure notes: All weekend closures are Saturdays or Sundays that
are explicitly confirmed as non-trading. Government makeup workdays (调休
补班日) that fall on weekends are NOT trading days.

### SSE 2025

| Field | Value |
|---|---|
| exchange | SSE |
| year | 2025 |
| announcement title | 关于上海证券交易所2025年部分节假日休市安排的通知 |
| announcement date | 2024-12-23 |
| reference number | 上证公告〔2024〕38号 |
| source URL | https://www.sse.com.cn/disclosure/announcement/general/c/c_20241223_10767108.shtml |
| retrieved_at | 2026-08-03T00:00:00Z |
| verification status | verified (direct from sse.com.cn) |

Covered holidays (closed ranges):
- 元旦: 2025-01-01
- 春节: 2025-01-28 to 2025-02-04 (weekend closures: 01-26, 02-08)
- 清明节: 2025-04-04 to 2025-04-06
- 劳动节: 2025-05-01 to 2025-05-05 (weekend closure: 04-27)
- 端午节: 2025-05-31 to 2025-06-02
- 国庆节、中秋节: 2025-10-01 to 2025-10-08 (weekend closures: 09-28, 10-11)

### SSE 2026

| Field | Value |
|---|---|
| exchange | SSE |
| year | 2026 |
| announcement title | 关于上海证券交易所2026年部分节假日休市安排的通知 |
| announcement date | 2025-12-22 |
| reference number | 上证公告〔2025〕45号 |
| source URL | https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml |
| retrieved_at | 2026-08-03T00:00:00Z |
| verification status | verified (direct from sse.com.cn) |

Covered holidays (closed ranges):
- 元旦: 2026-01-01 to 2026-01-03 (weekend closure: 01-04)
- 春节: 2026-02-15 to 2026-02-23 (weekend closures: 02-14, 02-28)
- 清明节: 2026-04-04 to 2026-04-06
- 劳动节: 2026-05-01 to 2026-05-05 (weekend closure: 05-09)
- 端午节: 2026-06-19 to 2026-06-21
- 中秋节: 2026-09-25 to 2026-09-27
- 国庆节: 2026-10-01 to 2026-10-07 (weekend closures: 09-20, 10-10)

## 5. SZSE Source Evidence

### SZSE 2024

| Field | Value |
|---|---|
| exchange | SZSE |
| year | 2024 |
| announcement title | 关于2024年部分节假日休市安排的通知 |
| announcement date | 2023-12-26 |
| reference number | 深证会〔2023〕409号 |
| source URL | https://www.szse.cn/disclosure/notice/general/t20231226_605108.html |
| retrieved_at | 2026-08-03T00:00:00Z |
| verification status | verified_direct_official (direct annual notice on szse.cn) |

Covered holidays: identical to SSE 2024.

### SZSE 2025

| Field | Value |
|---|---|
| exchange | SZSE |
| year | 2025 |
| announcement title | 关于2025年部分节假日休市安排的通知 |
| announcement date | 2024-12-23 |
| reference number | 深证会〔2024〕413号 |
| source URL | https://www.szse.cn/disclosure/notice/general/t20241223_611283.html |
| retrieved_at | 2026-08-03T00:00:00Z |
| verification status | verified (direct from szse.cn) |

Covered holidays: identical to SSE 2025.

### SZSE 2026

| Field | Value |
|---|---|
| exchange | SZSE |
| year | 2026 |
| announcement title | 关于2026年部分节假日休市安排的通知 |
| announcement date | 2025-12-22 |
| reference number | 深证会〔2025〕481号 |
| source URL | https://www.szse.cn/disclosure/notice/general/t20251222_618087.html |
| retrieved_at | 2026-08-03T00:00:00Z |
| verification status | verified_direct_official (direct annual notice on szse.cn; references 证监办发〔2025〕130号) |

Covered holidays: identical to SSE 2026.

## 6. SSE/SZSE Reconciliation

For each year (2024, 2025, 2026), the SSE and SZSE annual holiday
arrangements were compared date-by-date.

**Result**: SSE and SZSE arrangements are **identical** for all three
years. No mismatches found.

- 2024: SSE closed ranges == SZSE closed ranges. Match.
- 2025: SSE closed ranges == SZSE closed ranges. Match.
- 2026: SSE closed ranges == SZSE closed ranges. Match.

Both exchanges publish on the same day each year (2023-12-26, 2024-12-23,
2025-12-22) and reference the same CSRC notice. No union, intersection, or
guessing was applied.

## 7. Supported Date Range

```
supported_start_date: 2024-01-01
supported_end_date:   2026-12-31
timezone:             Asia/Shanghai
```

- 2024-2026 is the complete v0.1 supported range.
- Dates outside this range return `None`.
- Future years are not auto-inferred.
- 2027 and beyond require new official announcements and a version update.

Although the static file contains dates beyond the current date that fall
within the 2026 official arrangement, the public function still enforces:
```
future date (relative to Asia/Shanghai today) → None
```

## 8. Session Generation Rule

```
candidate dates =
  all dates from supported_start_date to supported_end_date

base trading days =
  Monday through Friday

final sessions =
  base trading days
  − SSE/SZSE official holiday closed dates
  − subsequent supplementary-announcement temporary closures
```

Not added to sessions:
- Saturdays
- Sundays
- Government makeup workdays (调休补班日)
- Dates not officially confirmed by the exchanges

## 9. Weekend and Holiday Semantics

- **Weekends**: Saturday and Sunday are always non-trading, regardless of
  government makeup-workday designations.
- **Government makeup workdays (调休补班日)**: The State Council may
  designate certain weekends as makeup workdays for general workers. SSE
  and SZSE explicitly state these are "周末休市" (weekend closures) — they
  are NOT trading days.
- **Official holidays**: Dates within official closed ranges are
  non-trading, even if they fall on a weekday.

Examples of makeup workday weekends excluded from sessions:
- 2024-02-04 (Sun), 2024-04-28 (Sun), 2024-05-11 (Sat)
- 2025-01-26 (Sun), 2025-02-08 (Sat), 2025-04-27 (Sun)
- 2026-02-14 (Sat), 2026-02-28 (Sat), 2026-05-09 (Sat)

## 10. Extraordinary Closure Policy

Extraordinary (temporary) market closures may occur due to:
- Severe weather (typhoon, snowstorm)
- System failure
- National mourning days
- Other unforeseen events

These closures are announced via supplementary SSE/SZSE announcements and
are NOT included in the annual holiday arrangement.

**v0.1 policy**: The offline artifact includes only annual-holiday-based
closures. Extraordinary closures that occurred within 2024-2026 are not
incorporated unless they were already reflected in the annual announcement.

Future versions may add a supplementary-closure update mechanism.

## 10a. Supplementary Notice Audit (2024-01-01 to 2026-08-03)

**Search scope**:
- SSE official site (sse.com.cn): disclosure/announcement listings, news releases
- SZSE official site (szse.cn): disclosure/notice listings, news releases
- CSRC (csrc.gov.cn): national-level trading suspension notices
- Time window: 2024-01-01 to current review date (2026-08-03)

**Official notices found that change A-share whole-market sessions**: none.

Between 2024-01-01 and 2026-08-03, no supplementary SSE/SZSE announcements
were identified that altered A-share whole-market sessions beyond the
already-documented annual holiday arrangements. Specifically:
- Typhoon-related closures in 2024 (e.g., Yagi in September) affected only
  the Hong Kong Stock Exchange; SSE and SZSE remained open.
- National mourning or system-failure full-market closures did not occur.
- No CSRC supplementary closure directive was issued for A-share whole-market
  sessions within the review window.

**Artifact impact**: none; the offline calendar does not need adjustment.

**Limitations**:
- This audit was performed via web-based searches on szse.cn, sse.com.cn
  and CSRC announcement listings.
- The reviewer did not exhaustively scrape every page of the two exchanges'
  news archives; the result is best-effort, not a guaranteed-complete scan.
- A future round should perform a structured supplementary-notice sweep
  (e.g., RSS or official API) before each artifact version bump.

## 11. Licensing and Redistribution Boundary

本仓库只提交自行标准化的事实性日期集合、来源元数据和短篇概括。

未取得交易所对公告正文的明确再分发许可。

不提交公告全文、完整 HTML、PDF 或大段逐字内容。

本文件不作版权或再分发法律结论。

It does NOT contain:
- Cookie, Token, or access-control parameters
- Full webpage HTML, PDF, or raw response bodies
- Complete copied text of official announcements
- Any copyrighted material beyond factual date data and source metadata

## 12. Offline Artifact Schema

File: `backend/data/cn_a_share_trade_calendar_v01.json`

```json
{
  "schema_version": "cn-a-share-trade-calendar-v0.1",
  "calendar_id": "CN_A_SHARE",
  "timezone": "Asia/Shanghai",
  "source_policy": "SSE_SZSE_OFFICIAL_CONSENSUS",
  "supported_start_date": "2024-01-01",
  "supported_end_date": "2026-12-31",
  "generated_at": "2026-08-03T00:00:00Z",
  "source_checked_at": "2026-08-03T00:00:00Z",
  "sources": [
    {
      "exchange": "SSE|SZSE",
      "year": 2024|2025|2026,
      "title": "...",
      "announcement_date": "YYYY-MM-DD",
      "URL": "...",
      "retrieved_at": "YYYY-MM-DDTHH:MM:SSZ"
    }
  ],
  "sessions": ["YYYY-MM-DD", ...]
}
```

Session constraints:
- `YYYY-MM-DD` strings
- Strictly ascending
- No duplicates
- All within supported range
- All Monday–Friday
- No official holiday dates

Generated artifact: 727 sessions, first `2024-01-02`, last `2026-12-31`.

## 13. previous_trade_date Contract

```python
def previous_trade_date(current_trade_date: str) -> str | None:
    ...
```

**Input**: strict `YYYY-MM-DD` string. The date is interpreted in
Asia/Shanghai timezone.

**current_trade_date** must itself be a confirmed trading day in the
offline calendar.

**Output**: the most recent confirmed trading day strictly before
`current_trade_date`, as a `YYYY-MM-DD` string.

Returns `None` when:
- Input is not a string, is empty, or is not strict `YYYY-MM-DD`
- The date does not exist (e.g., 2024-02-30)
- The date is a weekend
- The date is an official holiday
- The date is a government makeup-workday weekend
- The date is before the supported range
- The date is after the supported range
- The date is a future date relative to Asia/Shanghai today
- The date is not in the sessions list (not a confirmed trading day)
- There is no prior trading day (first session in the range)
- The data file is missing
- JSON parsing fails
- `schema_version` does not match
- `calendar_id` does not match
- `sessions` is empty, unsorted, has duplicates, contains weekends,
  contains out-of-range dates, or contains invalid date strings

The function does NOT:
- Auto-roll non-trading days to the nearest trading day
- Use `calendar_date - 1`
- Make runtime network requests
- Call AkShare or exchange websites
- Write caches or modify the data file
- Raise unhandled exceptions

## 14. Update Mechanism

**When to update**: When SSE and SZSE publish the next year's annual
holiday arrangement (typically in December of the preceding year).

**How to update**:
1. Retrieve the new SSE and SZSE annual announcements.
2. Reconcile both exchanges' arrangements.
3. If identical, extend `supported_end_date` and add new sessions.
4. Bump `schema_version` (e.g., to `v0.2`).
5. Update `source_checked_at` and add new source entries.
6. Re-run the mechanical validation script.
7. Re-run the test suite.

**What not to do**: Do not auto-infer future years. Do not patch the
existing file in place without a version bump.

## 15. Failure Semantics

The module is **fail-closed**: any error condition returns `None`.

- File I/O errors → `None`
- JSON parse errors → `None`
- Schema mismatches → `None`
- Session validation failures → `None`
- Invalid input → `None`
- Future dates → `None`

No exceptions are raised to the caller for any input or data condition.

## 16. Test Matrix

### Normal paths
- Consecutive trading days
- Across weekends (Friday → previous = Thursday)
- After each holiday (New Year, Spring Festival, Qingming, Labor Day,
  Dragon Boat, Mid-Autumn, National Day) for each year

### Input boundaries
- `None`, integer, boolean, empty string, whitespace-padded, `YYYYMMDD`,
  slash dates, invalid month/day, datetime strings

### Non-trading days
- Saturday, Sunday, holiday weekdays, makeup-workday weekends
- Before supported range, after supported range, future dates

### Data integrity
- Bad `schema_version`, bad `calendar_id`, missing file, invalid JSON,
  empty sessions, duplicate sessions, unsorted sessions, weekend in
  sessions, out-of-range sessions, invalid date strings in sessions

### Invariants
- Return value is strictly before input date
- Return value is in the sessions list
- Deterministic on repeated calls
- Input object is not modified
- No exceptions raised for any input
- No network calls

### Year boundaries
- First session → `None`
- 2024→2025 boundary
- 2025→2026 boundary
- 2026 last past session (with monkeypatched today)

## 17. Blocker-1 Closure Decision

**Blocker-1**: 交易日历的唯一来源、许可、覆盖年份、更新机制和接口尚未实现

**Status**: **CLOSED**.

Closure evidence:
- Unique source: SSE/SZSE official consensus (§3)
- Licensing boundary: documented (§11)
- Supported years: 2024-2026 (§7)
- Update mechanism: documented (§14)
- Interface: `previous_trade_date` implemented and tested (§13)

**Remaining blockers (2-9)**: NOT closed by this slice. See
`BK11_LAYERED_PROMOTION_FEASIBILITY_V01.md` §17.1 for the complete
nine-blocker list.

---

## Cross-check

Third-party tools (AkShare, exchange_calendars, pandas_market_calendars)
were NOT used for cross-check in this round. The calendar is based solely
on SSE/SZSE official announcements. A future round may perform an offline
cross-check; if conflicts arise, official announcements take precedence.

## Note on SZSE Annual Notice URLs

Both SZSE 2024 and SZSE 2026 direct annual-notice URLs on szse.cn
have been located and verified by opening each page directly:

- SZSE 2024: https://www.szse.cn/disclosure/notice/general/t20231226_605108.html
  (深证会〔2023〕409号, published 2023-12-26)
- SZSE 2025: https://www.szse.cn/disclosure/notice/general/t20241223_611283.html
  (深证会〔2024〕413号, published 2024-12-23)
- SZSE 2026: https://www.szse.cn/disclosure/notice/general/t20251222_618087.html
  (深证会〔2025〕481号, published 2025-12-22)

Previous placeholder sub-notice URLs (t20240201_605828.html for 2024 and
t20260423_620142.html for 2026) have been replaced with the direct annual
notice URLs. Third-party media sources previously used for cross-check
(中国经济网, 上观新闻, 财联社, 经济日报, 证券时报, 央广网) are no
longer part of the authoritative evidence chain.
