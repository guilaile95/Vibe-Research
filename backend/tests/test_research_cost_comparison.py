import copy
import json
import sqlite3

import pytest
from pydantic import ValidationError

from research_cost_comparison import CostComparisonRequest, compare_costs
from research_analytics_examples import example_input
from test_research_analytics_api import call


def request(**updates):
    body = example_input('cost-comparison')
    body.update(updates)
    return CostComparisonRequest.model_validate(body)


def one():
    body = example_input('cost-comparison')
    body['securities'] = body['securities'][:1]
    body['trades'] = body['trades'][:3]
    return body


def test_fifo_and_average_differ_but_total_economic_pnl_reconciles():
    report = compare_costs(request())
    assert report['status'] == 'CALCULATED'
    assert report['authority'] == 'CALLER_QUALIFIED_RESEARCH_NOT_LEDGER'
    assert [g['currency'] for g in report['groups']] == ['CNY', 'USD']
    assert report['cross_currency_total'] is None and report['whole_account_total'] is None
    for security in report['securities']:
        fifo, average = security['fifo'], security['moving_average']
        assert fifo['quantity'] == average['quantity'] == 100
        assert fifo['realized_pnl'] == pytest.approx(998)
        assert average['realized_pnl'] == pytest.approx(498)
        assert fifo['remaining_cost'] == pytest.approx(2001)
        assert average['remaining_cost'] == pytest.approx(1501)
        assert fifo['economic_pnl'] == pytest.approx(average['economic_pnl'])
        assert fifo['cost_reconciliation_error'] == pytest.approx(0)
        assert average['cost_reconciliation_error'] == pytest.approx(0)
        assert security['method_difference']['economic_pnl'] == pytest.approx(0)


def test_partial_sale_consumes_two_fifo_lots_with_fee_allocation():
    body = one()
    body['trades'][-1]['quantity'] = 150.0
    report = compare_costs(CostComparisonRequest.model_validate(body))
    security = report['securities'][0]
    assert security['fifo']['quantity'] == 50
    assert len(security['closed_trades'][0]['fifo_lots_consumed']) == 2
    assert security['closed_trades'][0]['fifo_cost'] == pytest.approx(1001 + 1000.5)
    assert security['fifo']['remaining_cost'] == pytest.approx(1000.5)


def test_opening_multilot_split_and_paid_pending_dividends():
    body = one(); body['trades'] = []
    s = body['securities'][0]
    s.update(opening_quantity=200.0, opening_lots=[
        {'lot_id': 'old_a', 'acquired_date': '2024-01-01', 'sequence': 0, 'quantity': 100.0, 'unit_cost': 10.0},
        {'lot_id': 'old_b', 'acquired_date': '2024-02-01', 'sequence': 0, 'quantity': 100.0, 'unit_cost': 20.0}],
        actions=[{'ex_date': '2025-01-03', 'pay_date': '2025-01-05', 'split_ratio': 2.0, 'dividend_per_old_share': 1.0},
                 {'ex_date': '2025-01-06', 'pay_date': '2025-03-01', 'dividend_per_old_share': .5}])
    report = compare_costs(CostComparisonRequest.model_validate(body))
    security = report['securities'][0]
    assert security['fifo']['quantity'] == 400
    assert security['fifo']['remaining_cost'] == security['moving_average']['remaining_cost'] == 3000
    assert security['fifo']['paid_dividends'] == 200
    assert security['fifo']['dividend_receivable'] == 200
    assert [l['unit_cost'] for l in security['remaining_fifo_lots']] == [5, 10]


@pytest.mark.parametrize('change,reason', [('fee', 'UNKNOWN_FEE_OR_OTHER_COST'), ('currency', 'CURRENCY_NOT_QUALIFIED'), ('lots', 'OPENING_LOTS_DO_NOT_RECONCILE_QUANTITY'), ('oversell', 'SELL_EXCEEDS_QUALIFIED_QUANTITY'), ('confirmed', 'LEGACY_FEES_NOT_CONFIRMED')])
def test_missingness_never_silently_renormalizes_group(change, reason):
    body = example_input('cost-comparison')
    if change == 'fee': body['trades'][0]['fee'] = None
    if change == 'currency': body['securities'][0]['currency'] = None
    if change == 'lots': body['securities'][0]['opening_quantity'] = 1.0
    if change == 'oversell': body['trades'][2]['quantity'] = 201.0
    if change == 'confirmed': body['securities'][0]['fees_confirmed'] = False
    report = compare_costs(CostComparisonRequest.model_validate(body))
    assert report['status'] == 'PARTIAL_COVERAGE'
    assert reason in report['securities'][0]['missing']
    assert report['securities'][0]['fifo'] is None
    if change == 'currency':
        assert all(g['status'] == 'INCOMPLETE' and g['fifo']['economic_pnl'] is None for g in report['groups'])
    else:
        assert next(g for g in report['groups'] if g['currency'] == 'CNY')['fifo']['realized_pnl'] is None


def test_missing_terminal_price_preserves_realized_but_not_whole_group_valuation():
    body = one(); body['securities'][0]['terminal_price_date'] = '2025-01-30'
    report = compare_costs(CostComparisonRequest.model_validate(body))
    assert report['securities'][0]['status'] == 'PARTIAL_VALUATION'
    assert report['groups'][0]['fifo']['realized_pnl'] == pytest.approx(998)
    assert report['groups'][0]['fifo']['unrealized_pnl'] is None
    assert report['groups'][0]['fifo']['economic_pnl'] is None


def test_same_instant_without_explicit_sequence_is_ambiguous():
    body = one()
    body['trades'][1]['executed_at'] = body['trades'][0]['executed_at']
    body['trades'][0]['sequence'] = body['trades'][1]['sequence'] = None
    report = compare_costs(CostComparisonRequest.model_validate(body))
    assert 'AMBIGUOUS_SAME_INSTANT_ORDER' in report['securities'][0]['missing']
    body['trades'][0]['sequence'], body['trades'][1]['sequence'] = 0, 1
    assert compare_costs(CostComparisonRequest.model_validate(body))['status'] == 'CALCULATED'


def test_qualified_negative_opening_cost_no_fake_return_ratio():
    body = one(); body['trades'] = []
    body['securities'][0].update(opening_quantity=100.0, opening_lots=[{'lot_id': 'adjusted', 'acquired_date': '2024-01-01', 'sequence': 0, 'quantity': 100.0, 'unit_cost': -2.0}])
    row = compare_costs(CostComparisonRequest.model_validate(body))['securities'][0]
    assert row['fifo']['remaining_cost'] == -200
    assert row['fifo']['unrealized_return']['value'] is None


def test_frozen_mode_cannot_accept_caller_owned_trade_rows():
    with pytest.raises(ValidationError): request(mode='FROZEN_LEDGER')


def test_duplicate_lot_trade_and_opening_order_rejected():
    body = one()
    body['trades'][1]['trade_id'] = body['trades'][0]['trade_id']
    with pytest.raises(ValidationError): CostComparisonRequest.model_validate(body)
    body = one(); body['securities'][0]['opening_lots'] = [
        {'lot_id': 'a', 'acquired_date': '2024-01-01', 'sequence': 0, 'quantity': 1.0, 'unit_cost': 1.0},
        {'lot_id': 'b', 'acquired_date': '2024-01-01', 'sequence': 0, 'quantity': 1.0, 'unit_cost': 2.0}]
    with pytest.raises(ValidationError): CostComparisonRequest.model_validate(body)


def test_real_frozen_ledger_cost_comparison_no_writes_and_same_sequence(tmp_path, monkeypatch):
    import trade_ledger_service as ledger
    import trade_ledger_store as store
    import account_event_store
    db = tmp_path / 'source.sqlite3'
    conn = sqlite3.connect(db); conn.execute(store._CREATE_TABLE_SQL); conn.execute(account_event_store._CREATE_TABLE_SQL)
    for n, operation, price in [(1, 'buy', 10), (2, 'add', 20), (3, 'reduce', 20)]:
        timestamp = f'2025-01-{[3,6,7][n-1]:02d}T06:00:00Z'
        conn.execute("INSERT INTO trade_records(trade_id,code,name,operation,execution_status,actual_price,actual_quantity,executed_at,fee,other_cost,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (str(n) * 32, '000001', 'SYNTHETIC', operation, 'full', price, 100, timestamp, 1, 0, timestamp))
    conn.commit(); conn.close()
    before = db.read_bytes(); monkeypatch.setattr(ledger, 'resolve_db_path', lambda: db)
    body = one(); body.pop('trades'); body['mode'] = 'FROZEN_LEDGER'; body['securities'][0]['code'] = '000001'
    report = compare_costs(CostComparisonRequest.model_validate(body))
    assert report['status'] == 'CALCULATED'
    assert report['authority'] == 'FROZEN_LEDGER_TRADES_WITH_CALLER_QUALIFIED_CURRENCY_LOTS_ACTIONS'
    assert report['selected_trade_ids'] == [str(n) * 32 for n in range(1,4)]
    assert report['securities'][0]['fifo']['realized_pnl'] == pytest.approx(998)
    assert db.read_bytes() == before and list(tmp_path.iterdir()) == [db]


def test_source_drift_and_active_corrections_fail_closed(monkeypatch):
    import research_cost_comparison as module
    class Frozen:
        def assert_unchanged(self): raise ValueError('changed source')
    body = one(); body.pop('trades'); body['mode'] = 'FROZEN_LEDGER'; body['securities'][0]['code'] = '000001'
    monkeypatch.setattr(module, 'read_frozen_ledger', lambda _: (Frozen(), [], []))
    report = compare_costs(CostComparisonRequest.model_validate(body))
    assert report['missing'] == ['AUTHORITATIVE_LEDGER_CHANGED_DURING_READ']
    monkeypatch.setattr(module, 'read_frozen_ledger', lambda _: (Frozen(), [], [{'event_type': 'CORRECTION'}]))
    assert compare_costs(CostComparisonRequest.model_validate(body))['missing'] == ['ACTIVE_CORRECTION_REQUIRES_GOVERNED_RECONCILIATION']


def test_cost_api_and_example_are_real_nonempty_calculations():
    body = call('/api/research-analytics/example/cost-comparison').json()['input']
    response = call('/api/research-analytics/cost-comparison', body)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['groups'][0]['fifo']['realized_pnl'] != response.json()['groups'][0]['moving_average']['realized_pnl']
    assert response.json()['canonical_cost_method_unchanged'] is True


def test_unknown_opening_lot_cost_visible_not_zero():
    body = one(); body['trades'] = []
    body['securities'][0].update(opening_quantity=100.0, opening_lots=[{'lot_id': 'unknown', 'acquired_date': '2024-01-01', 'sequence': 0, 'quantity': 100.0, 'unit_cost': None}])
    report = compare_costs(CostComparisonRequest.model_validate(body))
    assert report['securities'][0]['fifo'] is None
    assert report['securities'][0]['missing'] == ['OPENING_LOT_COST_UNKNOWN']


def test_frozen_tied_creation_does_not_invent_fifo_order(monkeypatch):
    import research_cost_comparison as module
    class Frozen:
        def assert_unchanged(self): pass
    body = one(); body.pop('trades'); body['mode'] = 'FROZEN_LEDGER'; body['securities'][0]['code'] = '000001'
    rows = [{'trade_id': str(n) * 32, 'code': '000001', 'execution_status': 'full', 'executed_at': '2025-01-03T06:00:00Z', 'created_at': '2025-01-03T07:00:00Z',
             'actual_price': price, 'actual_quantity': 100, 'fee': 1, 'other_cost': 0, 'operation': op}
            for n, price, op in [(1, 10, 'buy'), (2, 20, 'sell')]]
    monkeypatch.setattr(module, 'read_frozen_ledger', lambda _: (Frozen(), rows, []))
    report = compare_costs(CostComparisonRequest.model_validate(body))
    assert report['securities'][0]['missing'] == ['AMBIGUOUS_SAME_INSTANT_ORDER']
    rows[1]['created_at'] = '2025-01-03T07:00:00.000001Z'
    assert compare_costs(CostComparisonRequest.model_validate(body))['status'] == 'CALCULATED'


def test_cost_price_overflow_blocks_numeric_projection():
    body = one(); body['trades'] = []
    body['securities'][0].update(opening_quantity=1e12, terminal_price=1e12, opening_lots=[{'lot_id': 'large', 'acquired_date': '2024-01-01', 'sequence': 0, 'quantity': 1e12, 'unit_cost': 1.0}])
    report = compare_costs(CostComparisonRequest.model_validate(body))
    assert report['securities'][0]['status'] == 'UNDEFINED'
    assert report['securities'][0]['fifo'] is None


def test_qualified_opening_lot_cannot_duplicate_selected_trade():
    body = one()
    body['securities'][0].update(opening_quantity=100.0, opening_lots=[{'lot_id': body['trades'][0]['trade_id'], 'acquired_date': '2024-01-01', 'sequence': 0, 'quantity': 100.0, 'unit_cost': 10.0}])
    report = compare_costs(CostComparisonRequest.model_validate(body))
    assert 'OPENING_LOT_DUPLICATES_SELECTED_TRADE' in report['securities'][0]['missing']


@pytest.mark.parametrize('currency,timezone,code', [('USD', 'Asia/Shanghai', '000001'), ('CNY', 'America/New_York', '000001'), ('CNY', 'Asia/Shanghai', '900001'), ('CNY', 'Asia/Shanghai', '200001')])
def test_frozen_currency_market_and_session_cannot_be_relabelled(currency, timezone, code):
    body = one(); body.pop('trades'); body['mode'] = 'FROZEN_LEDGER'
    body['securities'][0].update(currency=currency, timezone=timezone, code=code)
    with pytest.raises(ValidationError): CostComparisonRequest.model_validate(body)


def high_value_sale(quantity):
    body = one(); body['trades'] = [body['trades'][-1]]
    body['trades'][0].update(quantity=quantity, price=1e12, fee=0.0, other_cost=0.0)
    body['securities'][0].update(opening_quantity=1.0, terminal_price=1e12, opening_lots=[
        {'lot_id': 'valuable', 'acquired_date': '2024-01-01', 'sequence': 0, 'quantity': 1.0, 'unit_cost': 1e12}])
    return body


def test_sub_tolerance_high_value_oversell_is_rejected():
    row = compare_costs(CostComparisonRequest.model_validate(high_value_sale(1.000000001)))['securities'][0]
    assert row['status'] == 'UNDEFINED'
    assert row['missing'] == ['SELL_EXCEEDS_QUALIFIED_QUANTITY']
    assert row['fifo'] is None and row['moving_average'] is None


def test_sub_tolerance_high_value_residual_is_preserved():
    row = compare_costs(CostComparisonRequest.model_validate(high_value_sale(.999999999)))['securities'][0]
    assert row['status'] == 'CALCULATED'
    for method in ('fifo', 'moving_average'):
        assert row[method]['quantity'] == 1e-9
        assert row[method]['remaining_cost'] == 1000
        assert row[method]['market_value'] == 1000
        assert row[method]['cost_reconciliation_error'] == 0
        assert row[method]['economic_pnl'] == 0
    assert row['remaining_fifo_lots'][0]['quantity'] == 1e-9


def test_opening_quantity_requires_exact_decimal_reconciliation():
    body = high_value_sale(1.0)
    body['securities'][0]['opening_quantity'] = 1.000000001
    row = compare_costs(CostComparisonRequest.model_validate(body))['securities'][0]
    assert row['missing'] == ['OPENING_LOTS_DO_NOT_RECONCILE_QUANTITY']
