"""Deterministic bounded daily hypothetical execution, never arbitrary strategy code."""
from __future__ import annotations

import math
from research_analytics import envelope, metrics, panel_paths
from research_analytics_contract import SimulationRequest, ScenarioRequest

STRATEGY_VERSION = 'next-open-long-only.v1'


def _missing(request):
    missing = []
    for instrument in request.instruments:
        for key in ('lot_size', 'settlement_sessions', 'fee_bps', 'min_fee', 'slippage_bps'):
            if getattr(instrument, key) is None:
                missing.append({'code': instrument.code, 'reason': key.upper() + '_MISSING'})
        if not instrument.corporate_actions_complete:
            missing.append({'code': instrument.code, 'reason': 'CORPORATE_ACTION_CONTRACT_MISSING'})
        bars = {b.date: b for b in instrument.bars}
        for day in request.sessions:
            bar = bars.get(day)
            if bar is None or any(getattr(bar, k) is None for k in ('open', 'close', 'suspended', 'limit_up', 'limit_down')):
                missing.append({'code': instrument.code, 'date': day, 'reason': 'PRICE_OR_EXECUTION_FLAGS_MISSING'})
            if bar is not None and (bar.price_limit_rule is None or (bar.price_limit_rule == 'BOUNDED' and (bar.upper_price_limit is None or bar.lower_price_limit is None))):
                missing.append({'code': instrument.code, 'date': day, 'reason': 'DAILY_PRICE_LIMIT_CONTRACT_MISSING'})
    return missing


def simulation_plan(request: SimulationRequest):
    missing = _missing(request)
    return envelope(request, status='MISSING_INPUTS' if missing else 'READY_TO_CALCULATE',
                    missing=missing, strategy_version=STRATEGY_VERSION,
                    strategy=request.strategy.model_dump(), currency=request.instruments[0].currency,
                    instruments=[i.code for i in sorted(request.instruments, key=lambda i: i.code)],
                    sessions=len(request.sessions), estimated_max_order_attempts=len(request.instruments) * len(request.sessions) + (len(request.instruments) if request.terminal_liquidation else 0),
                    maximum_runs=12 if request.robustness and request.strategy.name == 'SMA_CROSS' else 3 if request.robustness else 1,
                    execution='HYPOTHETICAL_NEXT_OPEN; NO_BROKER_OR_FORMAL_WRITES',
                    terminal_liquidation=request.terminal_liquidation)


def _simulate(request, cost_multiplier=1.0):
    instruments = sorted(request.instruments, key=lambda i: i.code)
    bars = {i.code: {b.date: b for b in i.bars} for i in instruments}
    holdings = {i.code: [] for i in instruments}
    cash, receivables, dividends = request.initial_cash, [], 0.0
    fills, rejected, completed, curve, turnovers = [], [], [], [], []
    total_fee, total_slippage, realized = 0.0, 0.0, 0.0
    entered = set()
    adjusted_paths, path_missing = panel_paths(request)
    if path_missing:
        return {'status': 'UNDEFINED', 'missing': path_missing}


    def quantity(code):
        return sum(lot['quantity'] for lot in holdings[code])

    def trade(instrument, side, qty, reference, idx, day, terminal=False):
        nonlocal cash, total_fee, total_slippage, realized
        code, bar = instrument.code, bars[instrument.code][day]
        reason = ('SUSPENDED' if bar.suspended else
                  'LIMIT_UP' if side == 'BUY' and bar.limit_up else
                  'LIMIT_DOWN' if side == 'SELL' and bar.limit_down else None)
        if side == 'SELL' and qty > sum(lot['quantity'] for lot in holdings[code]
                                        if idx - lot['session'] >= instrument.settlement_sessions) + 1e-8:
            reason = reason or 'SETTLEMENT_T_PLUS_RESTRICTION'
        if reason:
            rejected.append({'date': day, 'code': code, 'side': side, 'reason': reason, 'terminal': terminal})
            return 0.0
        slip = instrument.slippage_bps * cost_multiplier / 10000
        price = reference * (1 + slip if side == 'BUY' else 1 - slip)
        if bar.price_limit_rule == 'BOUNDED' and not bar.lower_price_limit <= price <= bar.upper_price_limit:
            rejected.append({'date': day, 'code': code, 'side': side, 'reason': 'FILL_OUTSIDE_DECLARED_PRICE_LIMIT', 'terminal': terminal})
            return 0.0
        fee_rate = instrument.fee_bps * cost_multiplier / 10000
        minimum = instrument.min_fee * cost_multiplier
        if side == 'BUY':
            # Both proportional and minimum fee inequalities must hold; never borrow.
            affordable = min(cash / (price * (1 + fee_rate)), max(0, cash - minimum) / price)
            qty = math.floor(min(qty, affordable) / instrument.lot_size) * instrument.lot_size
            if qty <= 0:
                rejected.append({'date': day, 'code': code, 'side': side, 'reason': 'INSUFFICIENT_CASH_OR_LOT', 'terminal': terminal})
                return 0.0
        fee = max(minimum, qty * price * fee_rate)
        notional = qty * price
        if side == 'SELL' and cash + notional < fee:
            rejected.append({'date': day, 'code': code, 'side': side, 'reason': 'INSUFFICIENT_CASH_FOR_FEE', 'terminal': terminal})
            return 0.0
        if side == 'BUY':
            cash -= notional + fee
            holdings[code].append({'quantity': qty, 'session': idx, 'unit_cost': (notional + fee) / qty})
            entered.add(code)
        else:
            remaining, cost, holding_sum = qty, 0.0, 0.0
            for lot in holdings[code]:
                if remaining <= 1e-8:
                    break
                sold = min(remaining, lot['quantity'])
                cost += sold * lot['unit_cost']
                holding_sum += sold * (idx - lot['session'])
                lot['quantity'] -= sold
                remaining -= sold
            holdings[code] = [lot for lot in holdings[code] if lot['quantity'] > 1e-8]
            cash += notional - fee
            pnl = notional - fee - cost
            realized += pnl
            completed.append({'code': code, 'date': day, 'net_pnl': pnl,
                              'holding_sessions': holding_sum / qty})
        total_fee += fee
        total_slippage += qty * abs(price - reference)
        fills.append({'date': day, 'code': code, 'side': side, 'quantity': qty,
                      'price': price, 'fee': fee, 'reference_price': reference,
                      'terminal': terminal, 'signal_date': request.sessions[idx - 1] if not terminal else None})
        return notional

    for idx, day in enumerate(request.sessions):
        if idx:
            for instrument in instruments:
                for action in instrument.actions:
                    if action.ex_date == day:
                        old = quantity(instrument.code)
                        entitlement = old * action.dividend_per_old_share
                        receivables.append({'pay_date': action.pay_date, 'amount': entitlement})
                        dividends += entitlement
                        for lot in holdings[instrument.code]:
                            lot['quantity'] *= action.split_ratio
                            lot['unit_cost'] /= action.split_ratio
            due = [r for r in receivables if r['pay_date'] <= day]
            cash += sum(r['amount'] for r in due)
            receivables = [r for r in receivables if r['pay_date'] > day]
            targets = {}
            for instrument in instruments:
                code = instrument.code
                if request.strategy.name == 'BUY_AND_HOLD':
                    targets[code] = True
                elif idx < request.strategy.slow:
                    targets[code] = False
                else:
                    # Explicitly exclude execution-day prices from signal calculation.
                    history = adjusted_paths[code]
                    targets[code] = (math.fsum(history[idx - request.strategy.fast:idx]) / request.strategy.fast >
                                     math.fsum(history[idx - request.strategy.slow:idx]) / request.strategy.slow)
            traded = 0.0
            for instrument in instruments:
                qty = quantity(instrument.code)
                if qty and not targets[instrument.code]:
                    traded += trade(instrument, 'SELL', qty, bars[instrument.code][day].open, idx, day)
            for instrument in instruments:
                code = instrument.code
                if targets[code] and quantity(code) <= 1e-8 and instrument.weight > 0 and not (
                        request.strategy.name == 'BUY_AND_HOLD' and code in entered):
                    # Prior close NAV is known before next-open order; deterministic code priority.
                    budget = curve[-1]['nav'] * instrument.weight
                    qty = math.floor(budget / bars[code][day].open / instrument.lot_size) * instrument.lot_size
                    traded += trade(instrument, 'BUY', qty, bars[code][day].open, idx, day)
            if request.terminal_liquidation and idx == len(request.sessions) - 1:
                for instrument in instruments:
                    qty = quantity(instrument.code)
                    if qty:
                        traded += trade(instrument, 'SELL', qty, bars[instrument.code][day].close, idx, day, terminal=True)
        else:
            traded = 0.0
        market_value = sum(quantity(i.code) * bars[i.code][day].close for i in instruments)
        receivable = sum(r['amount'] for r in receivables)
        nav = cash + market_value + receivable
        if not math.isfinite(nav) or not 0 < nav <= 1e15:
            return {'status': 'UNDEFINED', 'missing': [{'reason': 'NONPOSITIVE_OR_OVERFLOW_NAV'}]}
        turnovers.append(traded / (2 * (curve[-1]['nav'] if curve else request.initial_cash)))
        curve.append({'date': day, 'nav': nav, 'cash': cash, 'market_value': market_value, 'dividend_receivable': receivable})
    remaining = [{'code': i.code, 'quantity': quantity(i.code),
                  'market_value': quantity(i.code) * bars[i.code][request.sessions[-1]].close,
                  'cost_basis': sum(l['quantity'] * l['unit_cost'] for l in holdings[i.code])}
                 for i in instruments if quantity(i.code) > 1e-8]
    unrealized = sum(p['market_value'] - p['cost_basis'] for p in remaining)
    benchmark, benchmark_missing = None, []
    if request.benchmark:
        if request.benchmark.currency != instruments[0].currency or request.benchmark.market != instruments[0].market:
            raise ValueError('benchmark currency/market must match')
        panel = ScenarioRequest(sessions=request.sessions, calendar_source=request.calendar_source,
                                source_label=request.source_label, price_basis=request.price_basis, instruments=[request.benchmark])
        paths, benchmark_missing = panel_paths(panel)
        benchmark = paths.get(request.benchmark.code)
    return {'status': 'CALCULATED', 'strategy_version': STRATEGY_VERSION, 'curve': curve,
            'fills': fills, 'rejections': rejected, 'completed_trades': completed,
            'open_positions': remaining, 'realized_pnl': realized, 'unrealized_pnl': unrealized,
            'dividend_entitlements': dividends, 'total_fees': total_fee, 'slippage_cost': total_slippage,
            'metrics': metrics([r['nav'] for r in curve], request.sessions, completed, benchmark, turnovers),
            'benchmark_missing': benchmark_missing,
            'benchmark_semantics': 'MATCHED_CLOSE_DATES_TOTAL_RETURN_SLEEVE; NO_EXECUTION_COSTS',
            'pnl_reconciliation_error': curve[-1]['nav'] - request.initial_cash - realized - unrealized - dividends}


def simulate(request: SimulationRequest):
    plan = simulation_plan(request)
    if plan['missing']:
        return envelope(request, status='MISSING_INPUTS', missing=plan['missing'], metrics=None)
    result = _simulate(request)
    robustness = []
    if request.robustness and result['status'] == 'CALCULATED':
        variants = [('ZERO_COST_COUNTERFACTUAL', request, 0.0), ('DOUBLE_EXPLICIT_COSTS', request, 2.0)]
        if request.strategy.name == 'SMA_CROSS':
            for fast in sorted({max(1, request.strategy.fast - 1), request.strategy.fast, min(100, request.strategy.fast + 1)}):
                for slow in sorted({max(2, request.strategy.slow - 1), request.strategy.slow, min(250, request.strategy.slow + 1)}):
                    if fast >= slow:
                        robustness.append({'variant': f'SMA_FAST_{fast}_SLOW_{slow}', 'status': 'UNDEFINED', 'reason': 'FAST_MUST_BE_LESS_THAN_SLOW', 'total_return': None})
                        continue
                    altered = request.model_copy(deep=True)
                    altered.strategy = type(request.strategy)(name='SMA_CROSS', fast=fast, slow=slow)
                    variants.append((f'SMA_FAST_{fast}_SLOW_{slow}', altered, 1.0))
        for label, variant, cost in variants:
            report = _simulate(variant, cost)
            robustness.append({'variant': label, 'status': report['status'],
                               'total_return': report.get('metrics', {}).get('total_return'),
                               'sharpe': report.get('metrics', {}).get('sharpe'),
                               'max_drawdown': report.get('metrics', {}).get('max_drawdown'),
                               'trade_count': report.get('metrics', {}).get('trade_count'),
                               'fill_count': len(report.get('fills', [])),
                               'fees': report.get('total_fees'),
                               'return_difference_from_base': report['metrics']['total_return']['value'] - result['metrics']['total_return']['value'] if report['status'] == 'CALCULATED' else None,
                               'interpretation': 'DESCRIPTIVE_SAME_SAMPLE_PERTURBATION_NOT_OPTIMIZATION_OR_OUT_OF_SAMPLE'})
    from research_analytics_validation import validation_report
    validation = validation_report([row['nav'] for row in result.get('curve', [])], request.sessions, result.get('completed_trades', [])) if result['status'] == 'CALCULATED' else None
    return envelope(request, **result, robustness=robustness, validation=validation,
                    scope='HYPOTHETICAL_LONG_ONLY_CASH_ACCOUNT', currency=request.instruments[0].currency,
                    gross_target_weight=sum(i.weight for i in request.instruments),
                    residual_cash_target=1 - sum(i.weight for i in request.instruments),
                    execution_contract={'timing': 'SIGNAL_PRIOR_CLOSE_FILL_NEXT_OPEN',
                        'priority': 'SELLS_THEN_BUYS_ASCENDING_CODE', 'cash_interest': 'ZERO_HYPOTHETICAL_ASSUMPTION',
                        'settlement': 'DECLARED_SESSION_CALENDAR', 'terminal_liquidation': request.terminal_liquidation,
                        'fees': 'MAX_MINIMUM_OR_NOTIONAL_BPS_EACH_SIDE', 'liquidity_market_impact': 'NOT_MODELED',
                        'odd_lots': 'FULL_POSITION_SELL_ALLOWED_EXPLICIT_SIMPLIFICATION',
                        'availability_and_constraints': 'CALLER_DECLARED_UNVERIFIED', 'maximum_order_attempts': 40020},
                    metric_inventory={'source': 'pinned backtest/metrics.py:calc_metrics', 'verified_output_count': 20,
                                      'claimed_43_inventory': 'WITHDRAWN_UNSUPPORTED_COUNT_IN_PRIOR_AUDIT'})
