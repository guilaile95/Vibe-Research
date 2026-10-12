# Bounded research analytics, 2026-10-12

## Scope and source

A27/A31/A32/A33/A57 add an offline calculation surface at `/research-analytics` and
`/api/research-analytics` (including separate `/simulation-plan` validation and `/simulation` calculation). It complements, and does not relabel, historical signal
validation, P&L attribution or current hard-risk authority. No provider calls, models,
collectors, arbitrary code, persistence, trades, or formal mutations occur here.

Adaptation concepts and reviewed formula contracts come from
[simonlin1212/vibe-astock](https://github.com/simonlin1212/vibe-astock/tree/d5bf80d2ed1629f8fa602058093f8d41bb0c7ace/backtest)
at `d5bf80d2ed1629f8fa602058093f8d41bb0c7ace`, specifically `metrics.py`,
`portfolio_perf.py`, `benchmark.py`, `constraints.py`, `cost_compare.py`, `sensitivity.py`,
`validation.py`, `risk_xray.py`, `portfolio_xray.py`, `scenario_replay.py`, `event_study.py`
and `gate.py`. Downloaded source was read, never executed. This is a changed local
implementation with strict bounded inputs and deliberate missingness differences.
Original Apache 2.0 [LICENSE](../third-party/vibe-astock-LICENSE) and
[NOTICE](../third-party/vibe-astock-NOTICE), copyright 2026 simonlin1212, are preserved.
License Git blob: `d645695673349e3947e8e5ae42332d0ac3164cd7`;
NOTICE: `fb76b6b1e9874e440d543814ee56217bee223917`.

The old “43 metrics” title had no supported inventory and is withdrawn. The fixed
`metrics.py:calc_metrics` returns **20** named outputs. `/catalog` and each simulation
map exactly those names. SUPPORTED means defined for that input; UNDEFINED always
carries null and a reason. Supplemental capabilities and explicit UNSUPPORTED gaps
are separately inventoried, never padded to a claimed count.

## Executable contracts

- Inputs use strict declarative Pydantic contracts, unknown fields forbidden. One
  currency and one market calendar per panel. 20 instruments, 2000 sessions, 10,000
  ledger rows / 20,000 account events, 200 bootstrap and permutation resamples, 50 event dates.
  Simulation robustness uses at most 12 runs including the base; permutation accepts 3–2000 closed trades. All numeric inputs finite
  and bounded. Positive money/prices are at least 0.000001; zero valuations allowed.
- The session calendar is supplied explicitly; weekday guessing and observed RDP
  dates are never promoted to an official calendar. All inputs and corporate-action
  declarations remain unverified. Historical availability always NOT_PROVEN.
- Missing prices are never stale-carried. Unknown costs, lot sizes, settlements,
  suspension/directional limits, numeric daily limits or explicit no-limit session
  declaration block simulation. CN settlement is at least one declared session;
  HK/US lot and fee rules are supplied, not inferred constants.
- Daily long-only BUY_AND_HOLD and SMA_CROSS only. First valuation is initial cash
  at the first close. Strictly prior completed observations generate a signal, next
  open is the hypothetical fill. SMA uses total-return-adjusted observations derived
  only through each signal date. Sales precede buys, each in ascending instrument
  identity. Fees = max(explicit minimum, notional × explicit bps), each side; slippage
  is adverse. Buy size is lot-rounded, affordable including costs. A slippage-adjusted
  fill outside declared daily limits is rejected. Borrowing/shorting is unsupported.
- Suspended or directional-limit-blocked orders reject, with reasons. Full-position
  odd-lot sales are an explicit simplification, not universal exchange permission.
  No liquidity/volume queue or market-impact model exists. These are hypothetical
  results, never a claim of realizable performance.
- Split updates quantity and unit cost before session orders. Cash dividend entitlement
  is per pre-action share at ex-date, enters NAV as receivable and becomes cash on the
  supplied pay date. Opening-day actions are already incorporated in opening valuation.
  Terminal positions remain marked to market unless liquidation is explicitly selected;
  liquidation can still fail settlement or market constraints. Trade P&L excludes cash
  dividends, shown separately; realized + unrealized + dividends reconciles total P&L.
- Benchmark is a matched-calendar, same-currency, total-return sleeve without execution
  costs. Benchmark gaps leave benchmark metrics null without erasing strategy results.
  Zero-cost counterfactual, double-cost and bounded 3×3 SMA grid are same-sample descriptions,
  never parameter recommendations or out-of-sample evidence. IID bootstrap explicitly
  ignores serial dependence. Chronological subwindows match the pinned upstream walk_forward_analysis: path slices, close-date trade assignment and consistency statistics, not optimized train/test. Bounded fixed-seed trade-order Monte Carlo reorders only closed net P&L, excludes open positions/dividends/market timing, and gives descriptive permutation ranks rather than strategy-significance claims; nonpositive paths fail closed. Optimized training is not a feature of that upstream function.

## Performance and ledger ownership

Direct `performance` accepts explicit net valuations, currency and scope. Opening
value is market valuation, never historical cost. TWR interval factor is
`(end_NAV - END_flow)/(previous_NAV + BEGIN_flow)`. BEGIN means the previous valuation
date/start of the interval; END means the current valuation date/end of the interval.
MWR uses those exact declared dates, signs from the investor perspective, and terminal
value exactly once. Fees, actions and valuation coverage must be explicitly complete.

The separate `ledger-performance` adapter reuses existing PA1 ledger identity
contracts, excluding void/unexecuted trades and binding exact authoritative IDs. Trades and account events are read from the same private immutable SQLite image via the accepted P6 shared Snapshot helper; active corrections fail closed pending governed reconciliation. Source SQLite is never opened, and the image is rechecked before returning results. Absent databases, missing canonical tables/columns, missing primary-key identity, and duplicate IDs are unavailable rather than silently verified-empty. Genuine existing empty canonical ledgers remain distinguishable. It
currently supports CNY A-share stock baskets only; it never claims whole-account
performance, deposits or cash history. Its opening quantities are explicitly a complete
**first-session post-close** snapshot, priced at that close. First-session trades are
listed as incorporated into that opening snapshot. Other basket trades are replayed
on actual Asia/Shanghai session dates. Unknown costs, oversells, non-session dates,
missing prices or opening contracts fail closed. Legacy fee zeros require explicit
confirmation because old records could have defaulted them.

Ledger TWR is explicitly a DAILY_APPROXIMATION: purchases including costs are treated
before close-to-close return, net sales and paid dividends after. It does not have
intraday valuation evidence. **Ledger XIRR retains actual execution/payment dates**,
not the previous close dates used by a different caller-input convention. Raw-price
splits and dividend receivables use the same declared action adapter. No amounts or
research inputs are saved, sent to models or logged by this surface.

XIRR coalesces same-day flows, requires one sign change to prove uniqueness, searches
log(1+r) in [-20,20] using bounded bisection, and reports no root/possible multiple roots
as undefined. More than one sign change is deliberately conservative, even where a
specific stream might in fact have one root. Annual MWR and annual return are withheld
for windows shorter than one year; interval MWR remains available when uniquely solved.

## Descriptive risk, scenarios and event windows

Initial user weights are replayed through raw-price total-return sleeves; weights drift
without rebalancing, residual cash earns zero by explicit assumption. Dividends are
reinvested on ex-date for this descriptive sleeve calculation, unlike simulation cash
receipt handling. This is **hypothetical current/declared weights through a historical
window**, never historical holdings. Gross/net/cash weights and original covered weight
are returned without renormalization. Partial coverage exposes covered contribution but
no whole-portfolio return/NAV/VaR. Missing securities are never cash or zero returns.

Aligned daily correlation/covariance require at least three observations and nonzero
variance. No inverse covariance or optimizer is exposed. Static-weight covariance rank is diagnosed; singular matrices leave variance contributions undefined. Diversification and variance contribution explicitly use fixed one-period weights, separately from the drifted scenario path. Constant/too-short ratios stay
undefined. HHI/top weights retain original weights; volatility uses 252-session
annualization. Historical VaR 95 and expected shortfall require 20 complete returns and
are empirical statistics, not guaranteed loss limits. Equal-weight comparison and an
optional explicit benchmark yield descriptive single-factor beta, not causal factor
attribution. Multi-factor fundamental exposures remain unsupported without an input
factor model. Explicit event dates use exact sessions or an explicit NEXT_SESSION alignment option, forward returns, matching benchmark excess return, pre/post daily abnormal and cumulative-abnormal paths, mean/median/positive-share summaries and mean complete-event path. Missing windows remain undefined; overlapping event windows are not treated as independent observations. Live event discovery is out of this offline adapter.

## Source-to-sink and verification

- Contracts: `backend/research_analytics_contract.py`
- Simulation and accounting: `research_analytics_simulation.py:simulate/_simulate`
- TWR/XIRR, metrics, scenario: `research_analytics.py`
- RDP and authoritative ledger: `research_analytics_adapters.py`
- Bootstrap/subwindows: `research_analytics_validation.py`
- HTTP: `research_analytics_router.py`, mounted in `app.py`; private errors redact inputs
- UI: `frontend/src/pages/ResearchAnalytics.tsx`, route and Trades subnavigation
- Negative/arithmetic/API tests: `backend/tests/test_research_analytics*.py`
- UI presentation/input tests: `frontend/tests/research-analytics.test.ts`
- Desktop/mobile CI-only runtime: `frontend/tests/e2e/research-analytics.browser.mjs`
  uses the production page/API client and synthetic fixture; fixture equality to current
  backend calculations is separately tested. This is not live data or market acceptance.

Focused guarded tests and build evidence belong to the exact source receipt. Browser
runtime is not claimed until the CI run actually passes. Real-market/PIT/realizable
performance and model-quality evidence remain NOT_PROVEN/NOT_EVALUATED as applicable.

## Integration dependency

The source imports the accepted P6 `personal_review_snapshot.Snapshot` helper (P6 final `c45b5bd`). Integrate the P6 chain before this lane. Its exact helper bytes are reused for isolated validation, not copied into this lane as a second implementation. RDP adapter requires an existing archived current snapshot and cannot create one implicitly.
