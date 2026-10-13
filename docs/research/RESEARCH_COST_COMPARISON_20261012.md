# A30 read-only cost-method comparison, 2026-10-12

## Verified upstream delta

Pinned source `simonlin1212/vibe-astock@d5bf80d2ed1629f8fa602058093f8d41bb0c7ace`:

- `orchestrator/src/finance/holdings.ts:replayTrades`, blob
  `718766a24f96587e8938cc690adc5df2007495f5`: FIFO / moving-average, acquisition lots,
  buy costs in basis, sell costs against proceeds, separate dividends and splits
- `orchestrator/src/finance/holdings_view.ts:holdingsView`, blob
  `3942c14413895600851c2d9233a69584d7c46339`: chosen cost method read view
- `desktop/src/verticals/finance/pages/Portfolio.tsx`, blob
  `4a771812437b9a240503ed5ccc6ea66f4c188c10`: method selector and currency-separated totals

Sources were inspected, not executed. Adapted and changed local implementation;
[Apache License](../third-party/vibe-astock-LICENSE) and
[NOTICE](../third-party/vibe-astock-NOTICE) retain upstream attribution. Existing local
PA1 moving-average formal authority is not replaced. No new ledger is created.

## Entry points and authority

`POST /api/research-analytics/cost-comparison`, available in the research laboratory's
“FIFO / 均价比较” tab, produces both methods from one exact input sequence.

- `FROZEN_LEDGER`: caller trade rows are forbidden. The shared
  `research_analytics_ledger.read_frozen_ledger` validates a bounded private immutable
  image of both canonical trade and account-event tables. It reuses accepted P6
  `personal_review_snapshot.Snapshot` / foundation `_ControlSnapshot`, existing formal
  trade validators and PA1 ID validation. No source SQLite connection/sidecar is opened.
  Active corrections fail closed until governed reconciliation. Canonical dates/IDs,
  primary keys and schema are validated; absent/corrupt source is not verified empty.
  The source is checked unchanged before returning. Each method uses exactly the same
  selected authoritative rows, cost declarations and actions. Inputs with fractional
  timestamp formatting sort by parsed UTC instants, not lexicographic text.
- `QUALIFIED_RESEARCH`: bounded explicit non-authoritative trade adapter, including
  multiple currencies. Qualified synthetic examples yield real calculations. It never
  masquerades as formal ledger records or writes them to the ledger.

The canonical ledger has no currency field. Per-security currency is therefore an
explicit unverified input, never inferred from a six-digit symbol. FROZEN_LEDGER only
accepts CNY with Asia/Shanghai and excludes B-share prefixes 200/900; callers cannot
relabel canonical trades as foreign-currency or shift their market session dates.
Multicurrency research remains available through QUALIFIED_RESEARCH. Missing currencies
remain visible; they also prevent misleading complete currency-group totals. No FX
conversion, cross-currency sum or whole-account total is supplied. FROZEN_LEDGER
outputs explicitly say that currency, opening lots and actions are caller-qualified.

## Accounting contract

- Opening inventory is at the **start of `date_from`**, unlike the separate TWR
  adapter's first-close convention. Complete lot identities, pre-window acquisition
  dates, explicit within-date sequence, quantities and unit costs are required, and
  lot quantity must reconcile the declared opening quantity. Unknown cost is null,
  not zero. Confirmed negative adjusted opening cost is supported, with percentage
  P&L undefined when cost is nonpositive. The opening lot cannot duplicate a selected
  replay trade identity.
- Canonical execution instants govern replay. Same-instant caller trades need unique
  explicit sequence numbers. Frozen rows use distinct canonical creation instants as
  recorded-order evidence; identical execution/creation instants are ambiguous and
  block calculation. UUID ordering does not invent economic order.
- Split/ex-dividend entitlement precedes that day's trades. Split multiplies lot and
  total quantities and divides FIFO unit costs; total basis stays unchanged. Dividend
  entitlement uses pre-action shares and is reported separately as paid income or
  pending receivable according to the declared payment date, never reducing cost basis.
- Buy fees and other costs enter acquisition basis; sell fees and other costs reduce
  net proceeds. Legacy costs require explicit confirmation. Missing costs block the
  affected security; no invalid row is skipped into a plausible complete total.
- FIFO consumes oldest qualified acquisition lots, exposing each partial lot consumed.
  Moving-average reallocates total remaining basis after buys and proportionally on
  sells. It is a **research comparison**, not a new canonical PA1 result.
- Oversells, unknown opening inventory/actions, ambiguity, nonfinite/overflow-derived
  values fail closed. Both methods reconcile quantity and initial basis + buys −
  remaining basis − released basis. With complete terminal price, realized + unrealized
  + paid dividends + receivables is identical across cost methods; method differences
  change allocation of cost/P&L, not overall economic gain.
- Terminal price must carry the exact requested terminal date. Missing/stale prices
  preserve independently defined realized cost results but make group unrealized and
  economic totals null. No missing-security renormalization or price carry-forward.
- Internal Decimal precision-50 calculations preserve lot total cost without intermediate
  money rounding. Quantity reconciliation and oversell checks are strict; positive
  residual lots are never discarded as dust. Method cost/economic reconciliation
  errors above 1e-18 fail closed. JSON numbers are converted only for display/output. This
  view is not tax reporting or broker settlement accounting.

## Bounds and verification

20 securities, 10,000 selected/source trades, 20,000 canonical account events, 2,000
opening lots total, and 200 actions per security. Strict DTOs reject extra fields,
nonfinite numbers, unknown modes, duplicate identities and contradictory source modes.
No storage, migration, deletion, provider/model/collector action or authority mutation.

`backend/tests/test_research_cost_comparison.py` covers method reconciliation, partial
exits over multiple lots, split/dividend handling, unknown fees/currency/cost, negative
opening cost, stale valuation, oversells, ambiguous times, identical frozen sequence,
no source writes, source drift and active corrections. Existing P1 tests are rerun
because its immutable reader is shared. Browser fixture and runtime parser cover
nonempty currency groups and reject malformed/fake authoritative totals. Desktop/mobile
runtime is CI-only, not claimed until its run passes. PIT and caller authenticity remain
NOT_PROVEN; synthetic arithmetic is not real-account or market acceptance.
