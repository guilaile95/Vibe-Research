# Financial observation compatibility boundaries

This narrow inspection uses the repository-pinned AKShare 1.18.83 source,
`akshare/stock_fundamental/stock_finance_ths.py`, without live provider calls.

## Supported evidence

The three `stock_financial_*_new_ths` adapters always construct `report_date`,
`report_name`, `report_period`, `quarter_name`, and `metric_name`, then append
dynamic metric dictionary fields (or `value` for scalar payloads). The adapters
do not define fixed unit, scale, consolidation-scope or revision identifiers.
Their presence or semantics cannot be inferred from arbitrary hypothetical keys.
The older summary adapter preserves source cells, including numeric zero.

`astock.financials(include_health=True)` requests all four sources with
`indicator="按报告期"`, joins statement facts only by exact report date, rejects
duplicate date/metric pairs and invalid/non-finite numeric statement values,
and preserves missing/zero distinctions. Tests verify these boundaries. Summary
strings containing units remain display values and are not parsed into operands.
Optional statement failure preserves the reliable summary.

The enriched API caller is `/api/financials`; the user-facing consumer is the
Stock Data `EarningsSnapshot` and its history table. Legacy batch consumers leave
statement enrichment disabled. Snapshot and no-PIT disclosures remain.

## Confirmed defect and minimal repair

The frontend treated both numeric-zero revenue/profit as empty and individual
zero summary facts as unknown (`!value` / `value || fallback`). Failing state and
render regressions reproduced this despite correct backend preservation. The
repair distinguishes finite numbers (including zero/negative) and nonempty text
from unavailable values, and aligns frontend summary types with source values.
It changes display presence only, not arithmetic or investment conclusions.

## Unresolved evidence limits

No live mixed-unit, mixed-scope or mixed-revision provider payload was observed.
Unknown metadata is a semantic assurance gap, not proof that a current calculated
number is wrong. New unit/scale/scope/version rejection or conversion rules would
need a real supported-field contract and representative authorized fixture first.
`data_quality.status="normal"` describes field availability, not verification of
all accounting comparability assumptions. This work does not introduce PIT,
single-quarter reconstruction, financial scoring, or automated recommendations.

## Display disclosure (2026-10-11)

The existing Data Quality section distinguishes selected-field availability from
verified accounting comparability. `normal` does not mean every displayed or
derived field exists: the backend required-field list does not include the
income operands `revenue_amount` and `net_profit_amount`.

Exact report-date alignment is not verification of common currency, amount scale,
consolidation scope or revision. The pinned adapter coerces numeric-looking values;
it does not normalize currency or units. The UI labels its existing amount
formatting assumption: values displayed as 亿元 are treated as CNY base units and
divided by 1e8. This disclosure does not apply that conversion to legacy summary
strings, nor claim that source units have been independently verified.

The period note distinguishes report-period cumulative profit/cash flows from
period-end balance-sheet amounts. The history note cautions against treating
unequal cumulative lengths as directly comparable trends. It does not reconstruct
single quarters, annualize flows, use average assets, or validate upstream metric
definitions. Metadata absence alone is not evidence of incorrect values.

This is a copy-only qualification of the existing display. No financial values,
formulas, thresholds, availability states, or provider requests change. Offline
render tests exercise the actual component, including zero/negative/unknown
values, normal/partial states, and the history disclosure; they do not establish
provider accounting semantics or browser visual acceptance.
