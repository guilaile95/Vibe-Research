# Manual reverse DCF — 2026-10-19

## Entry and scope

Stock Data → an explicitly selected A/HK/US company → Six-stage Company Research →
“反向 DCF · 价格隐含假设（不调用 AI）”. This calculator runs independently of evidence
capture and AI generation. It does not fetch providers, use model credentials,
persist input, alter formal research authority, or emit investment actions.

POST `/api/company-research/reverse-dcf` accepts manually entered observations
(price, annual **unlevered FCFF**, net debt, diluted shares), each with source,
as-of date, currency and unit. Sources are declarations, not verified facts.
No field is prefilled from AI prose, earnings, financial adapters with unverified
unit scales, or default growth estimates. Industry and FCFF basis default to unknown.

## Model and numerical boundaries

With annual end-of-period cash flows, explicit horizon `N`, constant growth `g`,
WACC `r`, and perpetual growth `t`:

- EV = sum(FCFF₀ × (1+g)^year / (1+r)^year), years 1..N,
  plus FCFF₀ × (1+g)^N × (1+t) / ((r−t) × (1+r)^N)
- Target EV = price × diluted shares + net debt (debt minus cash)
- Bounded 100-step bisection solves `g`; positive FCFF and valid discount rates
  make the objective monotonic
- Each manually specified WACC sensitivity scenario independently solves `g`
  at the same target price and other assumptions
- Intermediate values are not rounded; the UI shows percentages to two decimals
- Net debt and shares remain fixed; there is no FX conversion, forecast dilution,
  changing capital structure, cyclic normalization, or financial-sector model

Every WACC must exceed terminal growth. Spreads below 1e-8 are rejected for
numerical stability, never silently adjusted. Horizon is 1–30 integer years;
explicit growth bounds must be ordered and above −100%, with upper bound at most
300%; WACC is in (0,100%], terminal growth is in (−100%,20%]. Each numeric input
must be finite. Booleans and numeric strings are rejected as numeric observations.
Amounts use base or million units; shares have a distinct share unit and no currency.
All monetary input currencies must match.

Out-of-bounds roots return `NO_ROOT` and null; financial firms, nonpositive FCFF
or nonpositive target EV return `INAPPLICABLE`; unknown sector/basis or stale/future
observations return `UNKNOWN`. None is replaced by zero, a proxy, or a growth guess.
Maximum ages measured against the server UTC calculation date: price 7 days,
annual FCFF 550 days, net debt and diluted shares 180 days. These explicit screening
windows do not establish comparability or factual verification of different dates.

## Validation

Synthetic offline tests cover forward/reverse parity including bounds, an
independent perpetuity formula, monotonicity, no-root cases, WACC sensitivity,
units/currencies, finite values, missing source inputs, temporal boundaries,
financial/unknown industry, and API isolation from capture/generation.
Frontend tests cover request/response binding, display rounding, actionable
validation errors, empty defaults, repeated submission, editing, cancellation,
subject changes, unmounting, late responses and retry after an error.

Production frontend build is checked separately. Component harness results are
not browser runtime acceptance or real-market validation. No browser launch was
attempted in this slice because the environment's known browser restriction
remains in effect. No provider/model/key calls, remote publication or deployment.
