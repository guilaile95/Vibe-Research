"""Read-only FIFO vs moving-average research projection; never canonical accounting.

Adapted algorithm concepts from vibe-astock d5bf80d2 holdings.ts:replayTrades.
Changed: unknown fees fail closed, currencies explicit/separate, no skipped-row totals,
server-owned frozen ledger mode, strict input/source boundaries. Apache notices in docs.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, localcontext
import math
import re
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import Field, StrictBool, model_validator
from research_analytics import digest, envelope, metric
from research_analytics_contract import Contract, Code, Currency, Day, Number, Positive, Nonnegative, Action
from research_analytics_ledger import UTC_STAMP, read_frozen_ledger


class OpeningLot(Contract):
    lot_id: Code
    acquired_date: Day
    sequence: Annotated[int, Field(strict=True, ge=0, le=10000)]
    quantity: Positive
    unit_cost: Number | None = None  # explicitly qualified adjusted opening cost may be negative

    @model_validator(mode='after')
    def actual_day(self):
        date.fromisoformat(self.acquired_date)
        return self


class CostSecurity(Contract):
    code: Code
    currency: Currency | None = None
    timezone: Literal['Asia/Shanghai', 'Asia/Hong_Kong', 'America/New_York']
    opening_quantity: Nonnegative | None = None
    opening_lots_complete: StrictBool = False
    opening_lots: list[OpeningLot] = Field(default_factory=list, max_length=2000)
    fees_confirmed: StrictBool = False
    corporate_actions_complete: StrictBool = False
    actions: list[Action] = Field(default_factory=list, max_length=200)
    terminal_price: Positive | None = None
    terminal_price_date: Day | None = None


class ResearchTrade(Contract):
    trade_id: Code
    code: Code
    executed_at: Annotated[str, Field(min_length=20, max_length=40)]
    sequence: Annotated[int, Field(strict=True, ge=0, le=10000)] | None = None
    operation: Literal['buy', 'sell']
    quantity: Positive
    price: Positive
    fee: Nonnegative | None = None
    other_cost: Nonnegative | None = None

    @model_validator(mode='after')
    def instant(self):
        if not UTC_STAMP.fullmatch(self.executed_at):
            raise ValueError('research trade must use a canonical UTC timestamp')
        datetime.fromisoformat(self.executed_at.replace('Z', '+00:00'))
        return self


class CostComparisonRequest(Contract):
    mode: Literal['FROZEN_LEDGER', 'QUALIFIED_RESEARCH']
    source_label: Annotated[str, Field(min_length=1, max_length=120)]
    date_from: Day
    date_to: Day
    securities: list[CostSecurity] = Field(min_length=1, max_length=20)
    trades: list[ResearchTrade] | None = Field(default=None, max_length=10000)

    @model_validator(mode='after')
    def contract(self):
        if self.date_from > self.date_to:
            raise ValueError('invalid date window')
        if self.mode == 'FROZEN_LEDGER' and self.trades is not None:
            raise ValueError('ledger trades are server-owned; caller rows forbidden')
        if self.mode == 'QUALIFIED_RESEARCH' and self.trades is None:
            raise ValueError('explicit research trade rows required')
        codes = [s.code for s in self.securities]
        if self.mode == 'FROZEN_LEDGER' and any(not re.fullmatch(r'\d{6}', code) for code in codes):
            raise ValueError('canonical ledger securities require six-digit identities')
        if self.mode == 'FROZEN_LEDGER' and any(
            s.currency not in (None, 'CNY') or s.timezone != 'Asia/Shanghai' or s.code.startswith(('900', '200'))
            for s in self.securities
        ):
            raise ValueError('canonical ledger qualification requires CNY A-shares and Asia/Shanghai')
        if len(set(codes)) != len(codes):
            raise ValueError('duplicate security identity')
        if sum(len(s.opening_lots) for s in self.securities) > 2000:
            raise ValueError('maximum 2000 total opening lots')
        if self.trades and (len({t.trade_id for t in self.trades}) != len(self.trades) or any(t.code not in codes for t in self.trades)):
            raise ValueError('duplicate trade identity or undeclared security')
        for security in self.securities:
            if len({l.lot_id for l in security.opening_lots}) != len(security.opening_lots):
                raise ValueError('duplicate opening lot identity')
            if len({(l.acquired_date, l.sequence) for l in security.opening_lots}) != len(security.opening_lots):
                raise ValueError('opening lot acquisition order must be explicit and unique')
            if any(l.acquired_date >= self.date_from for l in security.opening_lots):
                raise ValueError('opening lots must predate the first replay day')
            action_days = [a.ex_date for a in security.actions]
            if len(set(action_days)) != len(action_days) or any(not self.date_from <= d <= self.date_to for d in action_days):
                raise ValueError('duplicate or out-of-window action')
            if security.terminal_price_date:
                date.fromisoformat(security.terminal_price_date)
        return self


def _bounded(*numbers):
    if any(not math.isfinite(value) or abs(value) > 1e15 for value in numbers):
        raise ValueError('DERIVED_NUMBER_OUT_OF_BOUNDS')


def _decimal(value):
    return Decimal(str(value))


def _json_numbers(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _json_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_numbers(v) for v in value]
    return value


def _security_result(security, trades, request):
    with localcontext() as context:
        context.prec = 50
        return _json_numbers(_security_decimal(security, trades, request))


def _security_decimal(security, trades, request):
    missing = []
    if any(l.unit_cost is None for l in security.opening_lots):
        missing.append('OPENING_LOT_COST_UNKNOWN')
    if security.currency is None:
        missing.append('CURRENCY_NOT_QUALIFIED')
    if not security.opening_lots_complete or security.opening_quantity is None:
        missing.append('OPENING_LOTS_NOT_COMPLETE')
    elif sum((_decimal(l.quantity) for l in security.opening_lots), Decimal(0)) != _decimal(security.opening_quantity):
        missing.append('OPENING_LOTS_DO_NOT_RECONCILE_QUANTITY')
    if not security.fees_confirmed:
        missing.append('LEGACY_FEES_NOT_CONFIRMED')
    if not security.corporate_actions_complete:
        missing.append('CORPORATE_ACTION_CONTRACT_MISSING')
    if {l.lot_id for l in security.opening_lots} & {t['trade_id'] for t in trades}:
        missing.append('OPENING_LOT_DUPLICATES_SELECTED_TRADE')
    instants = {}
    for trade in trades:
        if trade['fee'] is None or trade['other_cost'] is None:
            missing.append('UNKNOWN_FEE_OR_OTHER_COST')
        instants.setdefault(trade['executed_at'], []).append(trade)
    for rows in instants.values():
        if len(rows) > 1 and (any(r['sequence'] is None for r in rows) or len({r['sequence'] for r in rows}) != len(rows)):
            missing.append('AMBIGUOUS_SAME_INSTANT_ORDER')
    result = {'code': security.code, 'currency': security.currency, 'status': 'MISSING_INPUTS' if missing else 'CALCULATED',
              'missing': sorted(set(missing)), 'trade_ids': [t['trade_id'] for t in trades],
              'fifo': None, 'moving_average': None, 'method_difference': None}
    if missing:
        return result
    lots = [{'lot_id': l.lot_id, 'date': l.acquired_date, 'quantity': _decimal(l.quantity), 'cost': _decimal(l.quantity) * _decimal(l.unit_cost)}
            for l in sorted(security.opening_lots, key=lambda l: (l.acquired_date, l.sequence, l.lot_id))]
    qty = _decimal(security.opening_quantity)
    avg_cost = sum((l['cost'] for l in lots), Decimal(0))
    initial_cost = avg_cost
    fifo_realized = avg_realized = fees = paid_dividends = receivables = buys = net_sales = Decimal(0)
    closed = []
    events = [(a.ex_date, 0, '', 0, 'action', a) for a in security.actions]
    events.extend((t['day'], 1, t['executed_at'], t['sequence'] or 0, 'trade', t) for t in trades)
    try:
        _bounded(qty, avg_cost)
        for _, _, _, _, kind, event in sorted(events, key=lambda e: e[:4]):
            if kind == 'action':
                amount = qty * _decimal(event.dividend_per_old_share)
                if event.pay_date <= request.date_to:
                    paid_dividends += amount
                else:
                    receivables += amount
                qty *= _decimal(event.split_ratio)
                for lot in lots:
                    lot['quantity'] *= _decimal(event.split_ratio)
                _bounded(qty, amount, paid_dividends, receivables)
                if qty and qty < 1e-12:
                    raise ValueError('DERIVED_QUANTITY_UNDERFLOW')
                continue
            trade = event
            number, price = _decimal(trade['quantity']), _decimal(trade['price'])
            fee = _decimal(trade['fee']) + _decimal(trade['other_cost'])
            if trade['operation'] == 'buy':
                cost = number * price + fee
                lots.append({'lot_id': trade['trade_id'], 'date': trade['day'], 'quantity': number, 'cost': cost})
                qty += number
                avg_cost += cost
                buys += cost
            else:
                if number > qty:
                    raise ValueError('SELL_EXCEEDS_QUALIFIED_QUANTITY')
                if qty <= 0:
                    raise ValueError('NO_QUALIFIED_OPENING_INVENTORY')
                average_used = avg_cost * number / qty
                left, fifo_used = number, Decimal(0)
                consumed = []
                for lot in lots:
                    if left == 0:
                        break
                    taken = min(left, lot['quantity'])
                    cost = lot['cost'] * taken / lot['quantity']
                    fifo_used += cost
                    consumed.append({'lot_id': lot['lot_id'], 'quantity': taken, 'cost': cost})
                    lot['cost'] -= cost
                    lot['quantity'] -= taken
                    left -= taken
                if left != 0:
                    raise ValueError('FIFO_LOTS_DO_NOT_RECONCILE')
                lots = [l for l in lots if l['quantity'] > 0]
                net = number * price - fee
                fifo_realized += net - fifo_used
                avg_realized += net - average_used
                net_sales += net
                qty -= number
                avg_cost -= average_used
                if qty == 0:
                    qty, avg_cost, lots = Decimal(0), Decimal(0), []
                closed.append({'trade_id': trade['trade_id'], 'date': trade['day'], 'quantity': number,
                    'net_proceeds': net, 'fifo_cost': fifo_used, 'average_cost': average_used,
                    'fifo_pnl': net - fifo_used, 'average_pnl': net - average_used, 'fifo_lots_consumed': consumed})
            fees += fee
            _bounded(qty, avg_cost, fifo_realized, avg_realized, fees, buys, net_sales)
        fifo_cost = sum((l['cost'] for l in lots), Decimal(0))
        _bounded(fifo_cost)
        if sum((l['quantity'] for l in lots), Decimal(0)) != qty:
            raise ValueError('METHOD_QUANTITIES_DO_NOT_RECONCILE')
    except (ValueError, ArithmeticError) as exc:
        return {**result, 'status': 'UNDEFINED', 'missing': [str(exc) if isinstance(exc, ValueError) else 'NUMERIC_ERROR']}
    price_ok = security.terminal_price is not None and security.terminal_price_date == request.date_to
    market_value = qty * _decimal(security.terminal_price) if price_ok else Decimal(0) if qty == 0 else None
    try:
        _bounded(*(v for v in (market_value, fifo_cost, avg_cost) if v is not None))
    except ValueError:
        return {**result, 'status': 'UNDEFINED', 'missing': ['DERIVED_NUMBER_OUT_OF_BOUNDS']}
    for name, cost, realized in [('fifo', fifo_cost, fifo_realized), ('moving_average', avg_cost, avg_realized)]:
        unrealized = market_value - cost if market_value is not None else None
        economic = realized + unrealized + paid_dividends + receivables if unrealized is not None else None
        result[name] = {'quantity': qty, 'remaining_cost': cost, 'unit_cost': cost / qty if qty else None,
                        'realized_pnl': realized, 'unrealized_pnl': unrealized, 'market_value': market_value,
                        'paid_dividends': paid_dividends, 'dividend_receivable': receivables, 'fees': fees,
                        'economic_pnl': economic,
                        'unrealized_return': metric(float(unrealized / cost) if unrealized is not None and cost > 0 else None, 'NONPOSITIVE_COST_OR_MISSING_TERMINAL_PRICE'),
                        'cost_reconciliation_error': initial_cost + buys - cost - (net_sales - realized)}
    errors = [result[m]['cost_reconciliation_error'] for m in ('fifo', 'moving_average')]
    economic_delta = result['fifo']['economic_pnl'] - result['moving_average']['economic_pnl'] if market_value is not None else Decimal(0)
    if any(abs(v) > Decimal('1e-18') for v in [*errors, economic_delta]):
        return {**result, 'status': 'UNDEFINED', 'missing': ['METHOD_COST_OR_ECONOMIC_RECONCILIATION_FAILED'],
                'fifo': None, 'moving_average': None}
    lots = [{**l, 'unit_cost': l['cost'] / l['quantity']} for l in lots]
    result.update(closed_trades=closed, remaining_fifo_lots=lots,
                  method_difference={'realized_pnl': fifo_realized - avg_realized,
                                     'remaining_cost': fifo_cost - avg_cost,
                                     'economic_pnl': result['fifo']['economic_pnl'] - result['moving_average']['economic_pnl'] if market_value is not None else None})
    if market_value is None:
        result['status'] = 'PARTIAL_VALUATION'
        result['missing'] = ['MISSING_EXACT_TERMINAL_PRICE']
    return result


def compare_costs(request: CostComparisonRequest):
    snapshot, events, source_rows = None, [], []
    authority = 'CALLER_QUALIFIED_RESEARCH_NOT_LEDGER'
    if request.mode == 'FROZEN_LEDGER':
        import trade_ledger_service as ledger
        try:
            snapshot, source_rows, events = read_frozen_ledger(ledger.resolve_db_path())
        except Exception:
            return envelope(request, status='MISSING_INPUTS', missing=['AUTHORITATIVE_LEDGER_UNAVAILABLE'], groups=[], securities=[])
        if any(e['event_type'] == 'CORRECTION' for e in events):
            return envelope(request, status='MISSING_INPUTS', missing=['ACTIVE_CORRECTION_REQUIRES_GOVERNED_RECONCILIATION'], groups=[], securities=[])
        authority = 'FROZEN_LEDGER_TRADES_WITH_CALLER_QUALIFIED_CURRENCY_LOTS_ACTIONS'
    else:
        source_rows = [t.model_dump() for t in request.trades]
    securities = {s.code: s for s in request.securities}
    selected, normalized, by_code = [], [], {s.code: [] for s in request.securities}
    try:
        for row in source_rows:
            if row['code'] not in securities or row.get('execution_status') == 'not_executed':
                continue
            timestamp = row['executed_at']
            if not UTC_STAMP.fullmatch(timestamp):
                raise ValueError('invalid execution time')
            instant = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            security = securities[row['code']]
            day = instant.astimezone(ZoneInfo(security.timezone)).date().isoformat()
            if not request.date_from <= day <= request.date_to:
                continue
            if request.mode == 'FROZEN_LEDGER':
                normalized_row = ResearchTrade(trade_id=row['trade_id'], code=row['code'], executed_at=timestamp,
                    operation='buy' if row['operation'] in {'buy', 'add'} else 'sell', quantity=row['actual_quantity'],
                    price=row['actual_price'], fee=row['fee'], other_cost=row['other_cost']).model_dump()
                normalized_row['created_at'] = row['created_at']
            else:
                normalized_row = dict(row)
            normalized_row['executed_at'] = instant.isoformat(timespec='microseconds')
            normalized_row['day'] = day
            by_code[row['code']].append(normalized_row)
            selected.append(row)
        for rows in by_code.values():
            if request.mode == 'FROZEN_LEDGER':
                # Recorded creation time is available canonical order evidence;
                # tied execution+creation instants do NOT acquire an invented ID order.
                instants = {}
                for row in rows:
                    instants.setdefault(row['executed_at'], []).append(row)
                for group in instants.values():
                    creation = [datetime.fromisoformat(r['created_at'].replace('Z', '+00:00')) for r in group]
                    if len(set(creation)) == len(creation):
                        for index, r in enumerate(sorted(group, key=lambda t: datetime.fromisoformat(t['created_at'].replace('Z', '+00:00')))):
                            r['sequence'] = index
            rows.sort(key=lambda t: (t['executed_at'], t['sequence'] if t['sequence'] is not None else -1, t['trade_id']))
            normalized.extend(rows)
    except (ValueError, TypeError, KeyError):
        return envelope(request, status='MISSING_INPUTS', missing=['INVALID_QUALIFIED_TRADE_INPUT'], groups=[], securities=[])
    results = [_security_result(s, by_code[s.code], request) for s in request.securities]
    groups = []
    unassigned = [r['code'] for r in results if r['currency'] is None]
    for currency in sorted({s.currency for s in request.securities if s.currency is not None}):
        members = [r for r in results if r['currency'] == currency]
        complete = not unassigned and all(r['status'] == 'CALCULATED' for r in members)
        accounting_complete = not unassigned and all(r['fifo'] is not None for r in members)
        row = {'currency': currency, 'codes': [r['code'] for r in members], 'unassigned_currency_codes': unassigned, 'status': 'COMPLETE' if complete else 'INCOMPLETE',
               'coverage': {'requested': len(members), 'accounting_defined': sum(r['fifo'] is not None for r in members), 'valuation_complete': sum(r['status'] == 'CALCULATED' for r in members)}}
        for method in ('fifo', 'moving_average'):
            row[method] = {key: math.fsum(r[method][key] for r in members) if (complete if key in {'unrealized_pnl', 'market_value', 'economic_pnl'} else accounting_complete) else None
                           for key in ('remaining_cost', 'realized_pnl', 'unrealized_pnl', 'market_value', 'economic_pnl', 'paid_dividends', 'dividend_receivable', 'fees')}
        groups.append(row)
    if snapshot:
        try:
            snapshot.assert_unchanged()
        except Exception:
            return envelope(request, status='MISSING_INPUTS', missing=['AUTHORITATIVE_LEDGER_CHANGED_DURING_READ'], groups=[], securities=[])
    missing = [{'code': r['code'], 'reason': reason} for r in results for reason in r['missing']]
    result = envelope(request, status='CALCULATED' if not missing else 'PARTIAL_COVERAGE', groups=groups, securities=results,
        missing=missing, authority=authority, scope='CURRENCY_SEPARATED_STOCK_BASKET_COST_COMPARISON',
        selected_trade_ids=[r['trade_id'] for r in selected], whole_account_total=None, cross_currency_total=None,
        canonical_cost_method_unchanged=True,
        methods={'fifo': 'Oldest qualified acquisition lot first; buy costs included, sale costs deducted',
                 'moving_average': 'Research moving weighted-average on exactly the same sequence; does not replace canonical PA1'},
        rounding_policy='DECIMAL50_INTERNAL_NO_INTERMEDIATE_MONEY_ROUNDING; strict quantities; JSON numeric display rounding; reconciliation limit1e-18',
        ordering='split/ex-dividend entitlement before same-day trades; instant then explicit/recorded sequence; ambiguous ties blocked',
        source_authentication='NOT_PROVEN')
    result['input_fingerprint'] = digest({'version': result['schema_version'], 'algorithm': 'cost-comparison.v1',
        'request': request.model_dump(), 'selected_source_rows': selected, 'events': events, 'normalized_sequence': normalized})
    return result
