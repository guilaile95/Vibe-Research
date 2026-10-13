# Dividend cash unit contract — 2026-10-11

## Source and local mismatch

This bounded adaptation follows Simon's [immutable dividend adapter](https://github.com/simonlin1212/Vibe-Research/blob/d643728e79b955dfdcdcd8b0dd362bd7c90c35c8/.agents/skills/data-access/scripts/sources/eastmoney.py#L374-L379), reviewed at v2.2.1. It identifies `PRETAX_BONUS_RMB` as pretax CNY per **10 shares** and preserves the provider value. [Upstream MIT license](https://github.com/simonlin1212/Vibe-Research/blob/d643728e79b955dfdcd8b0dd362bd7c90c35c8/LICENSE), Copyright (c) 2026 simonlin1212, is already retained by this repository. This is a local contract adaptation, not a wholesale upstream merge.

At local baseline `f7a2e2f965e0012deece5dd8716acafa20307359`, `astock.dividend_history` returned the raw field, while its docstring and `query_dividend` tool schema said per share. For synthetic provider value 12.5, the correct quantity is 12.5 CNY per 10 shares (1.25 per share); interpreting 12.5 as per share is a tenfold error. No claim is made that a real model actually made that error. StockData already used a per-10-share label; calendar details had no cash unit. Active bundled skill examples repeated the incorrect unit.

## Adaptation and compatibility

- Keep existing row arrays, field names, request parameters and 12-row tool cap. Preserve supplied raw zero and fractional values without multiplication/division or rounding
- Add `bonus_rmb_unit: "CNY/10_shares"` to adapter/tool rows and read-only calendar details; correct tool description, active skill examples and UI labels
- Separately correct absent `PRETAX_BONUS_RMB` from invented zero to null. Explicit null already stayed null. Nullable frontend rendering shows unknown; no other missing-data fields are changed
- Remove the tool schema's unsupported claim that the result contains dividend yield
- Preserve calendar source-record identity inputs and status/date classification, formal cash events, ledger history and historical changelog. No cash entitlement, accounting or tax computation is added

## Verification and limits

Synthetic tests replace the provider boundary and block socket connections/DNS. The seven core contract cases on the unchanged baseline produce 6 failures and 1 pass; adapted backend dividend/calendar suite passes 40 tests (including active bundled guidance). Coverage includes omitted/null/zero/fractional cash, unchanged raw numbers, empty results, the tool row cap and calendar historical classification. The frontend suite passes 1,123 tests, including production JSX dividend rendering and extracted production calendar detail formatting; TypeScript/Vite build passes (existing chunk-size warning).

No full backend suite, browser runtime QA, live market source, model call, credentials, real financial transaction, merge or deployment was performed. Synthetic tests establish local contracts only; they do not validate real market completeness or model answer quality.
