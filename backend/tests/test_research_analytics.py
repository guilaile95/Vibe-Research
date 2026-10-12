import copy
import math
import pytest
from pydantic import ValidationError
from research_analytics import METRIC_KEYS, performance, scenario, xirr
from research_analytics_contract import SimulationRequest, ScenarioRequest, PerformanceRequest, LedgerPerformanceRequest
from research_analytics_examples import example_input
from research_analytics_simulation import simulate
from research_analytics_adapters import ledger_performance


def sim(**updates):
    value = example_input('simulation')
    value.update(updates)
    return SimulationRequest.model_validate(value)


def compact(prices=(10, 11, 12, 13), **updates):
    body = example_input('simulation')
    body['sessions'] = body['sessions'][:len(prices)]
    i = body['instruments'][0]
    i.update(weight=1.0, lot_size=1, fee_bps=0.0, min_fee=0.0, slippage_bps=0.0)
    i['bars'] = [{**b, 'open': float(p), 'close': float(p)} for b, p in zip(i['bars'], prices)]
    body.update(benchmark=None, robustness=False, strategy={'name': 'BUY_AND_HOLD'}, initial_cash=1100.0)
    body.update(updates)
    return body


def test_simulator_next_open_mtm_no_terminal_sale_and_twenty_metrics():
    result = simulate(SimulationRequest.model_validate(compact()))
    assert result['status'] == 'CALCULATED'
    assert result['fills'][0]['date'] == '2025-01-03'
    assert result['fills'][0]['signal_date'] == '2025-01-02'
    assert result['fills'][0]['price'] == 11
    assert result['fills'][0]['quantity'] == 100
    assert result['curve'][-1]['nav'] == 1300
    assert result['realized_pnl'] == 0
    assert result['unrealized_pnl'] == 200
    assert result['open_positions'][0]['quantity'] == 100
    assert result['metrics']['win_rate']['value'] is None
    assert set(result['metrics']) == set(METRIC_KEYS) and len(METRIC_KEYS) == 20
    assert abs(result['pnl_reconciliation_error']) < 1e-8
    assert result['formal_writes'] == 0 and result['historical_availability'] == 'NOT_PROVEN'


def test_sma_future_changes_cannot_change_prior_fills():
    body = example_input('simulation')
    original = simulate(SimulationRequest.model_validate(body))
    for bar in body['instruments'][0]['bars'][30:]:
        bar['close'] *= 3
        bar['open'] *= 3
    changed = simulate(SimulationRequest.model_validate(body))
    cutoff = body['sessions'][30]
    assert [f for f in original['fills'] if f['date'] < cutoff] == [f for f in changed['fills'] if f['date'] < cutoff]


@pytest.mark.parametrize('field', ['fee_bps', 'min_fee', 'slippage_bps', 'lot_size', 'settlement_sessions'])
def test_unknown_execution_contract_never_zero(field):
    body = compact()
    body['instruments'][0][field] = None
    result = simulate(SimulationRequest.model_validate(body))
    assert result['status'] == 'MISSING_INPUTS' and result['metrics'] is None


def test_missing_corporate_actions_and_missing_session_price_fail_closed():
    body = compact()
    body['instruments'][0]['corporate_actions_complete'] = False
    body['instruments'][0]['bars'].pop(1)
    result = simulate(SimulationRequest.model_validate(body))
    assert result['status'] == 'MISSING_INPUTS'
    assert len(result['missing']) >= 2


@pytest.mark.parametrize('field,reason', [('suspended', 'SUSPENDED'), ('limit_up', 'LIMIT_UP')])
def test_execution_day_constraints(field, reason):
    body = compact()
    body['instruments'][0]['bars'][1][field] = True
    report = simulate(SimulationRequest.model_validate(body))
    assert report['rejections'][0]['reason'] == reason
    assert report['fills'][0]['date'] == body['sessions'][2]


def test_terminal_liquidation_t_plus_one_rejected_and_later_succeeds():
    body = compact((10, 11), terminal_liquidation=True)
    result = simulate(SimulationRequest.model_validate(body))
    assert result['rejections'][-1]['reason'] == 'SETTLEMENT_T_PLUS_RESTRICTION'
    assert result['open_positions']
    later = simulate(SimulationRequest.model_validate(compact(terminal_liquidation=True)))
    assert not later['open_positions']
    assert later['realized_pnl'] == 200


def test_limit_down_blocks_terminal_sale():
    body = compact(terminal_liquidation=True)
    body['instruments'][0]['bars'][-1]['limit_down'] = True
    report = simulate(SimulationRequest.model_validate(body))
    assert report['rejections'][-1]['reason'] == 'LIMIT_DOWN'
    assert report['open_positions']


def test_explicit_fee_cash_sufficiency_and_residual_cash():
    body = compact()
    i = body['instruments'][0]
    i.update(min_fee=10.0, lot_size=100)
    result = simulate(SimulationRequest.model_validate(body))
    assert not result['fills']  # cannot buy 100 shares + fee with only 1100
    assert result['curve'][-1]['cash'] == 1100
    assert result['metrics']['sharpe']['value'] is None
    assert result['metrics']['profit_factor']['value'] is None


def test_split_and_dividend_receivable_no_false_profit():
    body = compact((10, 10, 4.5, 4.5))
    i = body['instruments'][0]
    i['actions'] = [{'ex_date': body['sessions'][2], 'pay_date': '2025-02-01', 'split_ratio': 2.0, 'dividend_per_old_share': 1.0}]
    report = simulate(SimulationRequest.model_validate(body))
    assert report['curve'][-1]['nav'] == 1100
    assert report['curve'][-1]['dividend_receivable'] == 110
    assert report['open_positions'][0]['quantity'] == 220
    assert report['dividend_entitlements'] == 110
    assert abs(report['pnl_reconciliation_error']) < 1e-8


def test_robustness_reproducible_no_optimization_and_constant_ratio_undefined():
    body = compact((10,) * 30, robustness=True)
    # Compact needs 30 sessions; fixture has enough.
    a = simulate(SimulationRequest.model_validate(body))
    b = simulate(SimulationRequest.model_validate(body))
    assert a == b
    assert len(a['robustness']) == 2
    assert a['metrics']['sharpe']['status'] == 'UNDEFINED'
    assert a['metrics']['annual_return']['value'] is None
    assert a['validation']['bootstrap_sharpe_ci']['status'] == 'UNDEFINED'


@pytest.mark.parametrize('mutation', ['code', 'duplicate', 'currency', 'negative', 'nan', 'bool', 't0', 'calendar', 'script', 'leverage'])
def test_invalid_inputs_rejected(mutation):
    body = compact()
    i = body['instruments'][0]
    if mutation == 'code': body['strategy'] = {'name': '__import__("os").system("x")'}
    if mutation == 'script': body['python_code'] = 'print(1)'
    if mutation == 'duplicate': i['bars'][1]['date'] = i['bars'][0]['date']
    if mutation == 'currency': body['instruments'].append({**copy.deepcopy(i), 'code': 'SECOND', 'currency': 'USD', 'weight': 0.0})
    if mutation == 'negative': i['bars'][0]['close'] = -1.0
    if mutation == 'nan': i['fee_bps'] = float('nan')
    if mutation == 'bool': i['fee_bps'] = True
    if mutation == 't0': i['settlement_sessions'] = 0
    if mutation == 'calendar': i['bars'][1]['date'] = '2025-01-04'
    if mutation == 'leverage': i['weight'] = 1.1
    with pytest.raises(ValidationError): SimulationRequest.model_validate(body)


def test_twr_delayed_end_cashflow_not_counted_as_return():
    body = example_input('performance')
    result = performance(PerformanceRequest.model_validate(body))
    assert result['twr'] == pytest.approx(.21)
    assert result['mwr']['status'] == 'SUPPORTED'
    assert result['mwr']['annual_rate'] is not None
    body['fees_complete'] = False
    assert performance(PerformanceRequest.model_validate(body))['twr'] is None


def test_xirr_multi_roots_and_no_root_and_short_window():
    multi = xirr([('2020-01-01', -100), ('2021-01-01', 230), ('2022-01-01', -132)])
    assert multi['reason'] == 'MULTIPLE_ROOTS_POSSIBLE'
    assert multi['annual_rate'] is None
    assert xirr([('2020-01-01', 100), ('2021-01-01', 100)])['reason'] == 'NO_SIGN_CHANGE'
    short = xirr([('2025-01-01', -100), ('2025-02-01', 110)])
    assert short['annual_rate'] is None
    assert short['period_return'] == pytest.approx(.1)


def test_xirr_terminal_once_and_begin_end_convention():
    req = PerformanceRequest.model_validate({'currency': 'USD', 'scope': 'WHOLE_ACCOUNT', 'source_label': 'fixture',
        'fees_complete': True, 'corporate_actions_complete': True, 'coverage_complete': True,
        'valuations': [{'date': '2024-01-01', 'value': 100.0}, {'date': '2025-01-01', 'value': 200.0, 'flow_begin': 100.0}]})
    result = performance(req)
    assert result['twr'] == 0
    assert result['mwr']['period_return'] == pytest.approx(0, abs=1e-12)


def test_risk_missing_asset_retains_original_denominator():
    body = example_input('scenario')
    second = copy.deepcopy(body['instruments'][0])
    second.update(code='MISSING', weight=.3, bars=[])
    body['instruments'].append(second)
    result = scenario(ScenarioRequest.model_validate(body))
    assert result['total_return'] is None
    assert result['coverage']['covered_weight'] == .6
    assert result['coverage']['original_weight'] == pytest.approx(.9)
    assert result['cash_weight'] == pytest.approx(.1)
    assert result['coverage']['renormalized'] is False
    assert all(r['nav_index'] is None for r in result['curve'])


def test_risk_cash_weight_and_historical_not_current_holdings_and_event_missing():
    body = example_input('scenario')
    result = scenario(ScenarioRequest.model_validate(body))
    first, last = body['instruments'][0]['bars'][0]['close'], body['instruments'][0]['bars'][-1]['close']
    assert result['total_return'] == pytest.approx(.6 * (last / first - 1))
    assert result['event_study'][-1]['status'] == 'UNDEFINED'
    assert result['historical_var_95']['status'] == 'SUPPORTED'
    assert result['scope'] == 'HYPOTHETICAL_INITIAL_WEIGHT_BUY_HOLD_REPLAY'


def test_ledger_authority_adapter_uses_initial_value_not_cost():
    body = compact((10, 11, 12, 13))
    for k in ('strategy', 'initial_cash', 'benchmark', 'terminal_liquidation', 'robustness'): body.pop(k)
    body.update(opening=[{'code': 'SYNTH_A', 'quantity': 100.0}], ledger_fees_confirmed=True, opening_positions_complete=True)
    result = ledger_performance(LedgerPerformanceRequest.model_validate(body), trades=[])
    assert result['twr'] == pytest.approx(.3)
    assert result['curve'][0]['value'] == 1000
    assert result['whole_account_performance'] is False


def test_ledger_unknown_cost_oversell_and_non_session_rejected():
    body = compact()
    for k in ('strategy', 'initial_cash', 'benchmark', 'terminal_liquidation', 'robustness'): body.pop(k)
    body.update(opening=[], ledger_fees_confirmed=True, opening_positions_complete=True)
    row = {'trade_id': 'a' * 32, 'code': 'SYNTH_A', 'operation': 'sell', 'actual_quantity': 100,
           'actual_price': 11.0, 'fee': 0.0, 'other_cost': 0.0, 'executed_at': '2025-01-03T06:00:00Z'}
    req = LedgerPerformanceRequest.model_validate(body)
    assert ledger_performance(req, trades=[row])['status'] == 'MISSING_INPUTS'
    row['fee'] = None
    assert 'INVALID_OR_UNKNOWN_LEDGER_FEE' in ledger_performance(req, trades=[row])['missing']
    row['fee'] = 0.0
    row['executed_at'] = '2025-01-04T06:00:00Z'
    assert 'LEDGER_TRADE_OUTSIDE_SESSION_CALENDAR' in ledger_performance(req, trades=[row])['missing']


def test_slippage_cannot_cross_explicit_daily_price_bounds():
    body = compact()
    instrument = body['instruments'][0]
    instrument['slippage_bps'] = 20.0
    for bar in instrument['bars']:
        bar.update(price_limit_rule='BOUNDED', lower_price_limit=bar['open'] * .9, upper_price_limit=bar['open'])
    report = simulate(SimulationRequest.model_validate(body))
    assert not report['fills']
    assert {r['reason'] for r in report['rejections']} == {'FILL_OUTSIDE_DECLARED_PRICE_LIMIT'}


def test_stale_missing_price_never_forward_filled():
    body = example_input('scenario')
    body['instruments'][0]['bars'][-1]['close'] = None
    report = scenario(ScenarioRequest.model_validate(body))
    assert report['total_return'] is None
    assert report['missing'][0]['reason'] == 'MISSING_EXACT_SESSION_PRICE'


def test_zero_initial_and_final_valuation_diagnostics():
    body = example_input('performance')
    body['valuations'] = [{'date': '2025-01-02', 'value': 0.0}, {'date': '2025-01-03', 'value': 100.0}]
    assert performance(PerformanceRequest.model_validate(body))['status'] == 'UNDEFINED'
    body['valuations'] = [{'date': '2025-01-02', 'value': 100.0}, {'date': '2025-01-03', 'value': 0.0}]
    assert performance(PerformanceRequest.model_validate(body))['twr'] == -1


def test_ledger_mwr_actual_dates_not_shifted_to_previous_close():
    body = compact((10, 10, 10, 11))
    for k in ('strategy', 'initial_cash', 'benchmark', 'terminal_liquidation', 'robustness'): body.pop(k)
    body.update(opening=[{'code': 'SYNTH_A', 'quantity': 100.0}], ledger_fees_confirmed=True, opening_positions_complete=True)
    row = {'trade_id': 'a' * 32, 'code': 'SYNTH_A', 'operation': 'buy', 'actual_quantity': 100,
           'actual_price': 10.0, 'fee': 0.0, 'other_cost': 0.0, 'executed_at': '2025-01-06T06:00:00Z'}
    report = ledger_performance(LedgerPerformanceRequest.model_validate(body), trades=[row])
    exact = xirr([('2025-01-02', -1000), ('2025-01-06', -1000), ('2025-01-07', 2200)])
    wrong = xirr([('2025-01-02', -1000), ('2025-01-03', -1000), ('2025-01-07', 2200)])
    assert report['mwr'] == exact
    assert report['mwr']['period_return'] != pytest.approx(wrong['period_return'])


@pytest.mark.parametrize('ratio', [1e12, 1e-6])
def test_derived_path_overflow_underflow_explicit_undefined(ratio):
    body = example_input('simulation')
    body.update(strategy={'name': 'SMA_CROSS', 'fast': 1, 'slow': 2}, robustness=False)
    body['instruments'][0]['actions'] = [{'ex_date': d, 'pay_date': d, 'split_ratio': ratio} for d in body['sessions'][1:5]]
    result = simulate(SimulationRequest.model_validate(body))
    assert result['status'] == 'UNDEFINED'
    assert result['missing'][0]['reason'] == 'NUMERIC_BOUND_EXCEEDED'
    scenario_body = {k: v for k, v in body.items() if k not in {'strategy', 'initial_cash', 'robustness', 'terminal_liquidation', 'benchmark'}}
    risk = scenario(ScenarioRequest.model_validate(scenario_body))
    assert risk['total_return'] is None


def test_closed_trade_shuffle_and_chronological_exit_assignment():
    from research_analytics_validation import trade_permutation, validation_report
    trades = [{'date': '2025-01-03', 'net_pnl': -10.0}, {'date': '2025-01-06', 'net_pnl': 20.0}, {'date': '2025-01-07', 'net_pnl': -5.0}]
    result = trade_permutation(trades, 100.0)
    assert result['status'] == 'SUPPORTED'
    assert result == trade_permutation(trades, 100.0)
    assert 0 < result['p_value_max_dd'] <= 1
    assert trade_permutation([{'net_pnl': 0.0}] * 3, 100)['p_value_sharpe'] is None
    assert trade_permutation([{'net_pnl': -200.0}] * 3, 100)['status'] == 'UNDEFINED'
    days = ['2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07', '2025-01-08', '2025-01-09', '2025-01-10']
    report = validation_report([100, 90, 110, 105, 110, 115, 120], days, trades)
    windows = report['chronological_subwindows']
    assert math.prod(1 + w['total_return'] for w in windows) == pytest.approx(1.2)
    assert windows[0]['trade_count'] == 2 and windows[1]['trade_count'] == 1
    assert windows[2]['win_rate']['value'] is None


def test_ledger_mwr_weekend_dividend_uses_payment_date_not_next_session():
    body = compact((10, 9, 9, 9.9))
    for k in ('strategy', 'initial_cash', 'benchmark', 'terminal_liquidation', 'robustness'): body.pop(k)
    body.update(opening=[{'code': 'SYNTH_A', 'quantity': 100.0}], ledger_fees_confirmed=True, opening_positions_complete=True)
    body['instruments'][0]['actions'] = [{'ex_date': '2025-01-03', 'pay_date': '2025-01-04', 'dividend_per_old_share': 1.0}]
    report = ledger_performance(LedgerPerformanceRequest.model_validate(body), trades=[])
    expected = xirr([('2025-01-02', -1000), ('2025-01-04', 100), ('2025-01-07', 990)])
    shifted = xirr([('2025-01-02', -1000), ('2025-01-06', 100), ('2025-01-07', 990)])
    assert report['mwr'] == expected
    assert expected['period_return'] != pytest.approx(shifted['period_return'])


def test_event_pre_post_abnormal_path_and_non_session_alignment():
    body = example_input('scenario')
    body['benchmark'] = copy.deepcopy(body['instruments'][0])
    body['benchmark']['weight'] = 1.0
    body['event_dates'] = ['2025-01-18']  # Saturday
    body['event_alignment'] = 'NEXT_SESSION'
    report = scenario(ScenarioRequest.model_validate(body))
    event = report['event_study'][0]
    assert event['day0'] == '2025-01-20'
    assert event['abnormal_path'][0]['offset'] == -5
    assert event['abnormal_path'][-1]['offset'] == 5
    assert report['event_summary']['return']['n'] == 1
    assert report['event_summary']['mean_cumulative_abnormal_path'][-1]['n'] == 1


def test_singular_covariance_diagnostic_not_invertible_risk_claim():
    body = example_input('scenario')
    body['instruments'][0]['weight'] = .4
    second = copy.deepcopy(body['instruments'][0]); second['code'] = 'SYNTH_DUPLICATE_PATH'
    body['instruments'].append(second)
    report = scenario(ScenarioRequest.model_validate(body))
    assert report['risk_matrix_diagnostics']['singular'] is True
    assert report['risk_contribution']['status'] == 'UNDEFINED'
    assert report['risk_contribution']['shares'] is None


@pytest.mark.parametrize('fast,slow', [(1, 2), (2, 3), (99, 100), (100, 250)])
def test_sensitivity_grid_validates_atomic_adjacent_windows(fast, slow):
    report = simulate(sim(strategy={'name': 'SMA_CROSS', 'fast': fast, 'slow': slow}))
    assert report['status'] == 'CALCULATED'
    assert any(r['variant'] == 'ZERO_COST_COUNTERFACTUAL' for r in report['robustness'])
    for row in report['robustness']:
        if row['status'] == 'UNDEFINED':
            assert row['total_return'] is None


@pytest.mark.parametrize('timestamp', ['2025-01-03T06:00:00+01:60', '2025-01-03T06:00:00', '2025-01-03T06:00:00+24:00', '2025-02-30T06:00:00Z'])
def test_malformed_execution_offsets_never_normalized_into_session(timestamp):
    body = compact()
    for k in ('strategy', 'initial_cash', 'benchmark', 'terminal_liquidation', 'robustness'): body.pop(k)
    body.update(opening=[{'code': 'SYNTH_A', 'quantity': 100.0}], ledger_fees_confirmed=True, opening_positions_complete=True)
    row = {'trade_id': 'a' * 32, 'code': 'SYNTH_A', 'operation': 'buy', 'actual_quantity': 100,
           'actual_price': 10.0, 'fee': 0.0, 'other_cost': 0.0, 'executed_at': timestamp}
    result = ledger_performance(LedgerPerformanceRequest.model_validate(body), trades=[row])
    assert result['status'] == 'MISSING_INPUTS'
    assert 'LEDGER_EXECUTION_TIME_INVALID' in result['missing']


def test_next_session_cannot_invent_calendar_before_declared_window():
    body = example_input('scenario')
    body.update(event_dates=['2020-01-01', '2030-01-01'], event_alignment='NEXT_SESSION')
    result = scenario(ScenarioRequest.model_validate(body))
    assert all(e['status'] == 'UNDEFINED' and e['reason'] == 'EVENT_OUTSIDE_DECLARED_CALENDAR_WINDOW' for e in result['event_study'])
    assert all(e['return'] is None for e in result['event_study'])
