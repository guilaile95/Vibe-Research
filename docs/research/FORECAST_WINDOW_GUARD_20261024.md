# Fixed forecast-window expiry correction — 2026-10-24

## Scope and semantics

The legacy valuation schema explicitly selects 2026 and 2027 EPS. Before this
correction, retained provider rows could still produce current-looking PE,
growth, PEG and digestion scores in 2027, independently of calendar expiry.
An offline production reproduction returned `pe_26e=10` on 2027-01-04.

The fixed 2026→2027 scoring window now expires at Shanghai midnight entering
2027. Expiry sets `forecast_status=EXPIRED`, adds `forecast_note`, and nulls
`pe_26e`, `cagr_pct`, `peg`, and `digest_years`. Explicit-year raw EPS facts and
coverage counts remain source observations; quote, TTM, PB and market cap remain
independent. Missing values are not replaced with zero. This does not generate
2028 estimates, change legacy field meanings, or extend the trading calendar.

Qualification is repeated at producer returns/checkpoints, bounded-provider
results (including partial results), 30-second cache reads, and cockpit scoring.
Cockpit also withholds the expired EPS score. UI and AI context name `26E PE`
explicitly and retain the expiry warning. The AI tool description prohibits
reconstructing current forward estimates from old EPS.

## Verification

- Controlled Shanghai boundary: 2026-12-31 23:59:59 vs 2027-01-01 00:00:00;
  retained rows, missing rows, zero/loss raw EPS, provider failure, quote and
  fundamental preservation, old cockpit snapshot, cached/inflight/partial results.
- Actual AI tool handler and company-research capture retain the expiry metadata.
- Production JSX and AI-context declarations are compiled and executed with
  deterministic current/expired payloads; no global clock changes affect unrelated domains.
- Focused backend regression: 152 tests and 72 subtests passed.
- Frontend suite: 2,198 passed, one skipped, zero failed.
- Frontend production build passed. Browser runtime acceptance was not performed
  in this correction; component execution is not claimed as browser verification.

All inputs are synthetic and provider calls mocked. No live models, market
network, private production data, calendar expansion, or deployment is involved.
