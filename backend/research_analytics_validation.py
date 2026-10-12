"""Bounded descriptive robustness adapted from pinned validation.py; no predictive claim."""
import math
import random
import statistics
from research_analytics import metric, returns, drawdown


def _sharpe(rows, annualization=252):
    sd = statistics.stdev(rows) if len(rows) >= 2 else 0
    return statistics.mean(rows) / sd * math.sqrt(annualization) if sd > 1e-12 else None


def _quantile(values, q):
    values = sorted(values)
    pos = q * (len(values) - 1)
    lo = int(pos)
    return values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (pos - lo)


def trade_permutation(trades, initial_cash):
    base = {'seed': 1729, 'n_simulations': 200, 'n_trades': len(trades),
            'assumption': 'CLOSED_NET_PNL_ORDER_ONLY; OPEN_POSITIONS_DIVIDENDS_MARKET_TIMING_EXCLUDED; NOT_STRATEGY_SIGNIFICANCE',
            'sharpe_unit': 'PER_CLOSED_TRADE_NOT_ANNUALIZED'}
    if not 3 <= len(trades) <= 2000:
        return {**base, 'status': 'UNDEFINED', 'reason': 'REQUIRES_3_TO_2000_CLOSED_TRADES', 'p_value_sharpe': None, 'p_value_max_dd': None}
    pnls = [t['net_pnl'] for t in trades]
    def path_metrics(values):
        path = [initial_cash]
        for p in values:
            path.append(path[-1] + p)
        if any(not math.isfinite(p) or p <= 1e-12 for p in path):
            return None
        return _sharpe(returns(path), 1), drawdown(path)
    actual = path_metrics(pnls)
    if actual is None:
        return {**base, 'status': 'UNDEFINED', 'reason': 'NONPOSITIVE_CLOSED_TRADE_PATH', 'p_value_sharpe': None, 'p_value_max_dd': None}
    rng, sharpes, drawdowns = random.Random(1729), [], []
    for _ in range(200):
        shuffled = pnls.copy(); rng.shuffle(shuffled)
        result = path_metrics(shuffled)
        if result is None:
            # Conditioning away insolvent permutations would bias the comparison.
            return {**base, 'status': 'UNDEFINED', 'reason': 'NONPOSITIVE_PERMUTATION_PATH', 'p_value_sharpe': None, 'p_value_max_dd': None}
        sharpe, dd = result
        if sharpe is not None:
            sharpes.append(sharpe)
        drawdowns.append(dd)
    return {**base, 'status': 'SUPPORTED', 'actual_sharpe': actual[0], 'actual_max_dd': actual[1],
            'p_value_sharpe': (sum(s >= actual[0] for s in sharpes) + 1) / (len(sharpes) + 1) if actual[0] is not None and sharpes else None,
            'p_value_max_dd': (sum(d >= actual[1] for d in drawdowns) + 1) / 201,
            'simulated_sharpe_mean': statistics.mean(sharpes) if sharpes else None,
            'simulated_sharpe_std': statistics.pstdev(sharpes) if sharpes else None,
            'simulated_sharpe_p5': _quantile(sharpes, .05) if sharpes else None,
            'simulated_sharpe_p95': _quantile(sharpes, .95) if sharpes else None,
            'n_sharpe_defined': len(sharpes)}


def validation_report(nav, days=None, trades=None):
    ret, trades = returns(nav), trades or []
    seed, simulations = 1729, 200
    bootstrap = {'status': 'UNDEFINED', 'reason': 'AT_LEAST_20_RETURNS_AND_NONZERO_VARIANCE', 'ci_lower': None, 'ci_upper': None}
    if len(ret) >= 20 and _sharpe(ret) is not None:
        rng = random.Random(seed)
        values = [_sharpe(rng.choices(ret, k=len(ret))) for _ in range(simulations)]
        valid = [value for value in values if value is not None and math.isfinite(value)]
        if valid:
            bootstrap = {'status': 'SUPPORTED', 'observed_sharpe': _sharpe(ret),
                         'ci_lower': _quantile(valid, .025), 'ci_upper': _quantile(valid, .975),
                         'confidence': .95, 'n_bootstrap': simulations, 'n_valid': len(valid), 'seed': seed,
                         'assumption': 'IID_RESAMPLING_IGNORES_SERIAL_DEPENDENCE_NOT_SIGNIFICANCE_PROOF'}
    windows = []
    if len(ret) >= 6:
        for part in range(3):
            left, right = part * len(ret) // 3, (part + 1) * len(ret) // 3
            subset = ret[left:right]
            closed = [t for t in trades if days and days[left + 1] <= t['date'] <= days[right]]
            windows.append({'return_start_index': left, 'return_end_exclusive': right,
                            'start': days[left + 1] if days else None, 'end': days[right] if days else None,
                            'total_return': math.prod(1 + r for r in subset) - 1,
                            'max_drawdown': drawdown(nav[left:right + 1]), 'trade_count': len(closed),
                            'win_rate': metric(sum(t['net_pnl'] > 0 for t in closed) / len(closed) if closed else None, 'NO_CLOSED_TRADES'),
                            'sharpe': metric(_sharpe(subset), 'ZERO_VARIANCE_OR_SHORT_WINDOW')})
    wr = [w['total_return'] for w in windows]
    ws = [w['sharpe']['value'] for w in windows if w['sharpe']['value'] is not None]
    consistency = {'n_windows': len(windows), 'profitable_windows': sum(r > 0 for r in wr),
                   'consistency_rate': metric(sum(r > 0 for r in wr) / len(wr) if wr else None),
                   'return_mean': metric(statistics.mean(wr) if wr else None),
                   'return_std': metric(statistics.pstdev(wr) if wr else None),
                   'sharpe_mean': metric(statistics.mean(ws) if ws else None),
                   'sharpe_std': metric(statistics.pstdev(ws) if ws else None)}
    return {'bootstrap_sharpe_ci': bootstrap, 'chronological_subwindows': windows,
            'consistency': consistency,
            'subwindow_semantics': 'PINNED_UPSTREAM_WALK_FORWARD_MEANS_CHRONOLOGICAL_PATH_SLICES; NOT_TRAIN_TEST; CLOSED_TRADES_ASSIGNED_BY_EXIT_DATE',
            'monte_carlo_trade_shuffle': trade_permutation(trades, nav[0])}
