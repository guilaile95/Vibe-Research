"""Offline research calculations; no provider, model, persistence or trading access.

Adaptation concepts: simonlin1212/vibe-astock d5bf80d2, backtest/{metrics,
portfolio_perf,risk_xray,scenario_replay,event_study}.py. See docs/research/
RESEARCH_ANALYTICS_20261012.md for provenance and deliberate contract differences.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import date
from typing import Any

from research_analytics_contract import PerformanceRequest, ScenarioRequest

VERSION = 'research-analytics.v1'
LIMITATIONS = [
    '仅为只读研究计算，不改变正式交易、持仓、决策或硬风险权威。',
    '输入来源、日历、费用及公司行为声明未经本计算认证；历史可得性 NOT_PROVEN。',
    '历史统计及假设成交不是可实现收益或投资建议；不代表样本外有效。',
]
METRIC_KEYS = (
    'final_value', 'total_return', 'annual_return', 'max_drawdown', 'sharpe',
    'calmar', 'sortino', 'win_rate', 'profit_loss_ratio', 'profit_factor',
    'max_consecutive_loss', 'avg_holding_days', 'trade_count', 'benchmark_return',
    'excess_return', 'information_ratio', 'tracking_error', 'benchmark_beta',
    'avg_turnover', 'total_turnover',
)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def envelope(request, **result):
    return {'schema_version': VERSION, 'research_only': True,
            'historical_availability': 'NOT_PROVEN', 'source_authentication': 'NOT_PROVEN',
            'formal_writes': 0, 'input_fingerprint': digest({'version': VERSION, 'input': request.model_dump()}),
            'limitations': list(LIMITATIONS), **result}


def metric(value, reason='UNDEFINED'):
    if value is None or not math.isfinite(value):
        return {'status': 'UNDEFINED', 'value': None, 'reason': reason}
    return {'status': 'SUPPORTED', 'value': value, 'reason': None}


def returns(values):
    return [b / a - 1 for a, b in zip(values, values[1:])]


def drawdown(values):
    peak, worst = values[0], 0.0
    for value in values:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst


def metrics(values, days, trades=None, benchmark=None, turnovers=None):
    """Daily observed returns exclude a fabricated zero initial return. Units: fractions."""
    trades = trades or []
    result = {key: metric(None, 'MISSING_REQUIRED_SAMPLE') for key in METRIC_KEYS}
    ret = returns(values)
    total = values[-1] / values[0] - 1
    dd = drawdown(values)
    result.update(final_value=metric(values[-1]), total_return=metric(total), max_drawdown=metric(dd),
                  trade_count=metric(len(trades)))
    elapsed = (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days
    # Short windows do not get a misleading headline annual return.
    exponent = math.log(values[-1] / values[0]) * 365.25 / elapsed if elapsed >= 365 else None
    ann = math.expm1(exponent) if exponent is not None and exponent < 700 else None
    result['annual_return'] = metric(ann, 'SHORT_WINDOW_UNDER_ONE_YEAR')
    if len(ret) >= 2:
        sd = statistics.stdev(ret)
        mean = statistics.mean(ret)
        downside = math.sqrt(statistics.mean(min(0, r) ** 2 for r in ret))
        result['sharpe'] = metric(mean / sd * math.sqrt(252) if sd > 1e-12 else None, 'ZERO_VARIANCE')
        result['sortino'] = metric(mean / downside * math.sqrt(252) if downside > 1e-12 else None, 'NO_DOWNSIDE')
    result['calmar'] = metric(ann / abs(dd) if ann is not None and dd < -1e-12 else None,
                              'NO_DRAWDOWN_OR_SHORT_WINDOW')
    if trades:
        pnls = [t['net_pnl'] for t in trades]
        wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p < 0]
        run, worst = 0, 0
        for p in pnls:
            run = run + 1 if p < 0 else 0
            worst = max(worst, run)
        result.update(win_rate=metric(len(wins) / len(pnls)),
                      profit_loss_ratio=metric(statistics.mean(wins) / -statistics.mean(losses)
                                               if wins and losses else None, 'NO_WIN_OR_LOSS_SAMPLE'),
                      profit_factor=metric(sum(wins) / -sum(losses) if losses else None, 'NO_LOSS_SAMPLE'),
                      max_consecutive_loss=metric(worst),
                      avg_holding_days=metric(statistics.mean(t['holding_sessions'] for t in trades)))
    if benchmark is not None:
        bret = returns(benchmark)
        if len(bret) != len(ret):
            raise ValueError('benchmark calendar mismatch')
        result['benchmark_return'] = metric(benchmark[-1] / benchmark[0] - 1)
        result['excess_return'] = metric(total - (benchmark[-1] / benchmark[0] - 1))
        if len(ret) >= 2:
            active = [r - b for r, b in zip(ret, bret)]
            sd, bv = statistics.stdev(active), statistics.variance(bret)
            result['tracking_error'] = metric(sd * math.sqrt(252))
            result['information_ratio'] = metric(statistics.mean(active) / sd * math.sqrt(252)
                                                  if sd > 1e-12 else None, 'ZERO_ACTIVE_VARIANCE')
            result['benchmark_beta'] = metric(statistics.covariance(ret, bret) / bv
                                               if bv > 1e-12 else None, 'ZERO_BENCHMARK_VARIANCE')
    if turnovers is not None:
        result['total_turnover'] = metric(sum(turnovers))
        result['avg_turnover'] = metric(statistics.mean(turnovers) if turnovers else None)
    return result


def xirr(flows):
    """Conventional dated flows only: detect ambiguity before bounded log-rate bisection.

    >1 sign changes admits multiple roots, including even roots a sign scan misses.
    We deliberately report undefined rather than claiming the first scanned root unique.
    """
    grouped = {}
    for day, amount in flows:
        grouped[day] = grouped.get(day, 0.0) + amount
    items = [(d, a) for d, a in sorted(grouped.items()) if abs(a) > 1e-10]
    if len(items) < 2 or len({a > 0 for _, a in items}) < 2:
        return {'status': 'UNDEFINED', 'reason': 'NO_SIGN_CHANGE', 'annual_rate': None, 'period_return': None}
    changes = sum((a > 0) != (b > 0) for (_, a), (_, b) in zip(items, items[1:]))
    if changes != 1:
        return {'status': 'UNDEFINED', 'reason': 'MULTIPLE_ROOTS_POSSIBLE', 'annual_rate': None, 'period_return': None,
                'sign_changes': changes}
    start = date.fromisoformat(items[0][0])
    times = [((date.fromisoformat(d) - start).days / 365.25, a) for d, a in items]
    span = times[-1][0]
    if span <= 0:
        return {'status': 'UNDEFINED', 'reason': 'ZERO_DURATION', 'annual_rate': None, 'period_return': None}
    # Scale exponential terms before summation, preserving sign without overflow.
    def npv(log_rate):
        powers = [-t * log_rate for t, _ in times]
        largest = max(powers)
        return math.fsum(a * math.exp(p - largest) for p, (_, a) in zip(powers, times))
    lo, hi = -20.0, 20.0
    vlo, vhi = npv(lo), npv(hi)
    if vlo * vhi > 0:
        return {'status': 'UNDEFINED', 'reason': 'NO_ROOT_IN_BOUNDED_DOMAIN', 'annual_rate': None, 'period_return': None,
                'log_rate_bounds': [lo, hi]}
    for _ in range(160):
        mid = (lo + hi) / 2
        vm = npv(mid)
        if (vm > 0) == (vlo > 0):
            lo, vlo = mid, vm
        else:
            hi = mid
    log_rate = (lo + hi) / 2
    period = math.expm1(log_rate * span) if log_rate * span < 700 else None
    return {'status': 'SUPPORTED', 'reason': None, 'annual_rate': math.expm1(log_rate) if span >= 1 else None,
            'period_return': period, 'short_window_annualization': 'WITHHELD' if span < 1 else 'NOT_APPLICABLE',
            'root_contract': 'ONE_SIGN_CHANGE_UNIQUE_ROOT_WITHIN_LOG_RATE_MINUS20_PLUS20',
            'flow_signs': 'investor contributions negative; withdrawals and terminal value positive'}


def performance(request: PerformanceRequest):
    missing = [name for name in ('fees_complete', 'corporate_actions_complete', 'coverage_complete')
               if not getattr(request, name)]
    if missing:
        return envelope(request, status='MISSING_INPUTS', missing=missing, twr=None, mwr=None)
    rows = request.valuations
    growth, indices = 1.0, [1.0]
    flows = [(rows[0].date, -rows[0].value)]
    for previous, current in zip(rows, rows[1:]):
        denominator = previous.value + current.flow_begin
        numerator = current.value - current.flow_end
        if denominator <= 0 or numerator < 0:
            return envelope(request, status='UNDEFINED', missing=['NONPOSITIVE_FLOW_ADJUSTED_NAV'], twr=None, mwr=None)
        growth *= numerator / denominator
        if not math.isfinite(growth) or growth > 1e12:
            return envelope(request, status='UNDEFINED', missing=['NUMERIC_BOUND_EXCEEDED'], twr=None, mwr=None)
        indices.append(growth)
        # BEGIN means the start of this valuation interval, not a guessed intraday timestamp.
        flows.append((previous.date, -current.flow_begin))
        flows.append((current.date, -current.flow_end))
    flows.append((rows[-1].date, rows[-1].value))  # terminal valuation exactly once
    return envelope(request, status='CALCULATED', scope=request.scope, currency=request.currency,
                    coverage={'complete': True}, twr=growth - 1, mwr=xirr(flows),
                    curve=[{'date': r.date, 'value': r.value, 'twr_index': v} for r, v in zip(rows, indices)],
                    flow_convention='BEGIN flows at previous valuation date before interval return; END flows at current valuation date after interval return; opening NAV is valuation, not cost',
                    authority='EXPLICIT_UNVERIFIED_VALUATION_ADAPTER')


def panel_paths(request):
    """Total-return sleeves from raw prices and explicit split/dividend entitlement."""
    available, missing = {}, []
    for instrument in request.instruments:
        bars = {b.date: b for b in instrument.bars}
        reason = None
        if not instrument.corporate_actions_complete:
            reason = 'CORPORATE_ACTION_CONTRACT_MISSING'
        elif any(day not in bars or bars[day].close is None for day in request.sessions):
            reason = 'MISSING_EXACT_SESSION_PRICE'
        if reason:
            missing.append({'code': instrument.code, 'weight': instrument.weight, 'reason': reason})
            continue
        actions = {a.ex_date: a for a in instrument.actions}
        path = [1.0]
        for previous, day in zip(request.sessions, request.sessions[1:]):
            action = actions.get(day)
            split = action.split_ratio if action else 1.0
            dividend = action.dividend_per_old_share if action else 0.0
            factor = (bars[day].close * split + dividend) / bars[previous].close
            value = path[-1] * factor
            if not math.isfinite(value) or not 1e-12 <= value <= 1e12:
                reason = 'NUMERIC_BOUND_EXCEEDED'
                break
            path.append(value)
        if reason:
            missing.append({'code': instrument.code, 'weight': instrument.weight, 'reason': reason})
        else:
            available[instrument.code] = path
    return available, missing


def _matrix_rank(matrix):
    rows = [row.copy() for row in matrix]
    if not rows:
        return 0
    tolerance = max(abs(v) for row in rows for v in row) * 1e-12
    rank = 0
    for col in range(len(rows[0])):
        pivot = max(range(rank, len(rows)), key=lambda r: abs(rows[r][col])) if rank < len(rows) else None
        if pivot is None or abs(rows[pivot][col]) <= tolerance:
            continue
        rows[rank], rows[pivot] = rows[pivot], rows[rank]
        scale = rows[rank][col]
        rows[rank] = [v / scale for v in rows[rank]]
        for r in range(rank + 1, len(rows)):
            factor = rows[r][col]
            rows[r] = [a - factor * b for a, b in zip(rows[r], rows[rank])]
        rank += 1
    return rank


def scenario(request: ScenarioRequest):
    paths, missing = panel_paths(request)
    weights = {i.code: i.weight for i in request.instruments}
    invested = sum(weights.values())
    covered = sum(weights[c] for c in paths)
    cash = max(0.0, 1 - invested)
    # Uncovered weight never becomes cash; partial contribution is not a portfolio return.
    contribution = [sum(weights[c] * (paths[c][t] - 1) for c in paths) for t in range(len(request.sessions))]
    complete = not missing
    curve = [1 + c for c in contribution] if complete else None
    correlations, covariance = [], []
    ret = {c: returns(p) for c, p in paths.items()}
    for a in paths:
        for b in paths:
            reason = 'TOO_FEW_RETURNS' if len(ret[a]) < 3 else 'ZERO_VARIANCE'
            adequate = len(ret[a]) >= 3 and statistics.variance(ret[a]) > 1e-12 and statistics.variance(ret[b]) > 1e-12
            correlations.append({'left': a, 'right': b, **metric(statistics.correlation(ret[a], ret[b]) if adequate else None, reason)})
            covariance.append({'left': a, 'right': b, **metric(statistics.covariance(ret[a], ret[b]) if adequate else None, reason)})
    portfolio_returns = returns(curve) if curve else []
    # Linear-interpolated empirical fifth percentile; VaR can be negative in all-gain samples.
    var = None
    if len(portfolio_returns) >= 20:
        ordered = sorted(portfolio_returns)
        pos = .05 * (len(ordered) - 1)
        low = int(pos)
        var = -(ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (pos - low))
    sd = statistics.stdev(portfolio_returns) if len(portfolio_returns) >= 3 else None
    tail = [r for r in portfolio_returns if var is not None and r <= -var]
    risk_metrics = {
        'hhi_original_weights': metric(sum(w * w for w in weights.values())),
        'top1_weight': metric(max(weights.values())),
        'top3_weight': metric(sum(sorted(weights.values(), reverse=True)[:3])),
        'daily_vol': metric(sd, 'INCOMPLETE_COVERAGE_OR_SHORT_SAMPLE'),
        'annualized_vol': metric(sd * math.sqrt(252) if sd is not None else None, 'INCOMPLETE_COVERAGE_OR_SHORT_SAMPLE'),
        'expected_shortfall_95': metric(-statistics.mean(tail) if tail else None, 'AT_LEAST_20_COMPLETE_RETURNS_REQUIRED'),
    }
    beta = None
    if complete and len(ret) >= 2 and len(portfolio_returns) >= 3:
        equal_weight = [statistics.mean(ret[c][t] for c in ret) for t in range(len(portfolio_returns))]
        bv = statistics.variance(equal_weight)
        if bv > 1e-12:
            beta = statistics.covariance(portfolio_returns, equal_weight) / bv
    risk_metrics['effective_n_cash_inclusive'] = metric(1 / (sum(w*w for w in weights.values()) + cash*cash) if sum(w*w for w in weights.values()) + cash*cash > 0 else None)
    risk_metrics['downside_deviation_annualized'] = metric(math.sqrt(statistics.mean(min(0, r)**2 for r in portfolio_returns) * 252) if portfolio_returns else None, 'INCOMPLETE_COVERAGE')
    risk_contribution = {'status': 'UNDEFINED', 'reason': 'INCOMPLETE_COVERAGE_OR_SHORT_SAMPLE', 'shares': None}
    matrix_diagnostics = {'sample_returns': len(request.sessions) - 1, 'rank': None, 'dimension': len(paths),
                          'method': 'DECLARED_STATIC_WEIGHTS_ONE_PERIOD_COVARIANCE_NOT_DRIFTED_SCENARIO'}
    if complete and len(portfolio_returns) >= 3:
        codes = list(paths)
        matrix = [[statistics.covariance(ret[a], ret[b]) for b in codes] for a in codes]
        rank = _matrix_rank(matrix)
        matrix_diagnostics['rank'] = rank
        matrix_diagnostics['singular'] = rank < len(codes)
        static_returns = [sum(weights[c] * ret[c][t] for c in codes) for t in range(len(portfolio_returns))]
        variance = statistics.variance(static_returns)
        asset_vols = {c: statistics.stdev(ret[c]) for c in codes}
        risk_metrics['diversification_ratio_static_weights'] = metric(sum(weights[c] * asset_vols[c] for c in codes) / math.sqrt(variance) if len(codes) >= 2 and variance > 1e-12 else None, 'NEEDS_TWO_ASSETS_AND_NONZERO_PORTFOLIO_VARIANCE')
        for c in codes:
            risk_metrics['asset_vol_annualized:' + c] = metric(asset_vols[c] * math.sqrt(252))
        if rank == len(codes) and variance > 1e-12:
            shares = {c: weights[c] * sum(matrix[j][k] * weights[d] for k, d in enumerate(codes)) / variance for j, c in enumerate(codes)}
            risk_contribution = {'status': 'SUPPORTED', 'reason': None, 'shares': shares}
        else:
            risk_contribution['reason'] = 'SINGULAR_COVARIANCE_OR_ZERO_PORTFOLIO_VARIANCE'
    defined_pairs = [r for r in correlations if r['left'] < r['right'] and r['value'] is not None]
    risk_metrics['avg_pairwise_abs'] = metric(statistics.mean(abs(r['value']) for r in defined_pairs) if defined_pairs else None, 'NO_DEFINED_PAIR')
    risk_metrics['max_pairwise_abs'] = metric(max(abs(r['value']) for r in defined_pairs) if defined_pairs else None, 'NO_DEFINED_PAIR')
    risk_metrics['beta_to_equal_weight'] = metric(beta, 'NEEDS_TWO_ASSETS_AND_NONCONSTANT_COMPARATOR')
    benchmark_path = None
    benchmark_missing = []
    if request.benchmark:
        if request.benchmark.currency != request.instruments[0].currency or request.benchmark.market != request.instruments[0].market:
            raise ValueError('benchmark currency/market must match')
        benchmark_request = request.model_copy(update={'instruments': [request.benchmark], 'benchmark': None})
        benchmark_paths, benchmark_missing = panel_paths(benchmark_request)
        benchmark_path = benchmark_paths.get(request.benchmark.code)
    factor_beta = None
    if benchmark_path and portfolio_returns and len(portfolio_returns) >= 3:
        bret = returns(benchmark_path)
        bv = statistics.variance(bret)
        if bv > 1e-12:
            factor_beta = statistics.covariance(portfolio_returns, bret) / bv
    risk_metrics['single_factor_benchmark_beta'] = metric(factor_beta, 'MISSING_OR_ZERO_VARIANCE_BENCHMARK')
    events = []
    if len(set(request.event_dates)) != len(request.event_dates):
        raise ValueError('duplicate event date')
    for day in request.event_dates:
        date.fromisoformat(day)
        if day < request.sessions[0] or day > request.sessions[-1]:
            events.append({'date': day, 'status': 'UNDEFINED', 'reason': 'EVENT_OUTSIDE_DECLARED_CALENDAR_WINDOW', 'return': None})
            continue
        eligible = [d for d in request.sessions if d >= day] if request.event_alignment == 'NEXT_SESSION' else [day] if day in request.sessions else []
        if not eligible:
            events.append({'date': day, 'status': 'UNDEFINED', 'reason': 'NOT_IN_SESSION_CALENDAR', 'return': None})
            continue
        aligned_day = eligible[0]
        idx = request.sessions.index(aligned_day)
        end = idx + request.event_horizon
        value = curve[end] / curve[idx] - 1 if curve and end < len(curve) else None
        benchmark_return = benchmark_path[end] / benchmark_path[idx] - 1 if benchmark_path and end < len(benchmark_path) else None
        abnormal_path, cumulative = [], 0.0
        baseline = idx - request.pre_event_horizon - 1
        if curve and benchmark_path and baseline >= 0 and end < len(curve):
            for t in range(baseline + 1, end + 1):
                abnormal = (curve[t] / curve[t-1] - 1) - (benchmark_path[t] / benchmark_path[t-1] - 1)
                cumulative += abnormal
                abnormal_path.append({'offset': t - idx, 'abnormal_return': abnormal, 'cumulative_abnormal_return': cumulative})
        events.append({'date': day, 'day0': aligned_day, 'alignment': request.event_alignment,
                       'status': 'SUPPORTED' if value is not None else 'UNDEFINED', 'return': value,
                       'benchmark_return': benchmark_return,
                       'excess_return': value - benchmark_return if value is not None and benchmark_return is not None else None,
                       'abnormal_path': abnormal_path or None,
                       'abnormal_path_reason': None if abnormal_path else 'MISSING_BENCHMARK_OR_COMPLETE_PRE_POST_WINDOW',
                       'reason': None if value is not None else 'INCOMPLETE_EVENT_WINDOW_OR_COVERAGE'})
    event_summary = {}
    for key in ('return', 'excess_return'):
        values = [e[key] for e in events if e.get(key) is not None]
        event_summary[key] = {'n': len(values), 'mean': metric(statistics.mean(values) if values else None, 'NO_COMPLETE_EVENT_WINDOWS'),
                              'median': metric(statistics.median(values) if values else None, 'NO_COMPLETE_EVENT_WINDOWS'),
                              'positive_share': metric(sum(v > 0 for v in values) / len(values) if values else None, 'NO_COMPLETE_EVENT_WINDOWS')}
    paths = [e['abnormal_path'] for e in events if e.get('abnormal_path')]
    event_summary['mean_cumulative_abnormal_path'] = [{'offset': paths[0][t]['offset'], 'mean': statistics.mean(p[t]['cumulative_abnormal_return'] for p in paths), 'n': len(paths)} for t in range(len(paths[0]))] if paths else None
    return envelope(request, status='CALCULATED' if complete else 'PARTIAL_COVERAGE',
                    currency=request.instruments[0].currency, scope='HYPOTHETICAL_INITIAL_WEIGHT_BUY_HOLD_REPLAY',
                    gross_weight=invested, net_weight=invested, cash_weight=cash, leverage=invested,
                    coverage={'original_weight': invested, 'covered_weight': covered,
                              'fraction': covered / invested if invested else None, 'renormalized': False},
                    missing=missing, total_return=curve[-1] - 1 if curve else None,
                    covered_contribution=contribution[-1],
                    curve=[{'date': day, 'nav_index': curve[t] if curve else None,
                            'covered_contribution': contribution[t]} for t, day in enumerate(request.sessions)],
                    correlation=correlations, covariance=covariance, risk_metrics=risk_metrics,
                    benchmark_missing=benchmark_missing, risk_contribution=risk_contribution, risk_matrix_diagnostics=matrix_diagnostics, factor_method="DESCRIPTIVE_SINGLE_FACTOR_OLS_BETA_NO_CAUSAL_OR_FUNDAMENTAL_FACTOR_CLAIM",
                    historical_var_95=metric(var, 'AT_LEAST_20_COMPLETE_RETURNS_REQUIRED'),
                    max_drawdown=metric(drawdown(curve) if curve else None, 'INCOMPLETE_COVERAGE'),
                    event_study=events, event_summary=event_summary, sample_returns=len(request.sessions) - 1,
                    methods=['Initial weights drift; no daily rebalancing; residual cash earns zero by explicit hypothetical convention',
                             'Dividend entitlement is reinvested in total-return sleeves on ex-date; not an executable strategy',
                             'Historical VaR is an empirical statistic, never a guaranteed loss limit',
                             'Correlation is descriptive, not causal; event windows may overlap and are not independent',
                             'Covariance entries are descriptive; no inverse/optimizer, singular-matrix inference unsupported'])
