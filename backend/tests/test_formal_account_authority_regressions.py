"""Synthetic offline regression coverage for correction/cash/as-of authority boundaries."""
import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import account_event_store as events
import cash_event_router
import cash_event_service as cash
import formal_decision_outcome_runtime as outcome
import formal_trade_attribution as fta
import formal_trade_attribution_store as attribution_store
import frozen_decision_store as frozen
import performance_attribution_service as pa
import performance_attribution_store as snapshots
import position_reality_service as positions
import trade_ledger_store as trades
from test_formal_decision_outcome import make_decision, make_trade


@pytest.fixture
def env(tmp_path, monkeypatch):
    for key, name in [("VIBE_RESEARCH_TRADE_LEDGER_DB", "trades"),
                      ("VIBE_RESEARCH_PERFORMANCE_ATTRIBUTION_DB", "pa"),
                      ("VIBE_RESEARCH_FROZEN_DECISION_DB", "frozen"),
                      ("VIBE_RESEARCH_TRADE_ATTRIBUTION_DB", "attributions")]:
        monkeypatch.setenv(key, str(tmp_path / (name + '.sqlite3')))
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    return tmp_path


def seed(env):
    positions.bootstrap_commit({'ledger_start_at': '2026-08-01', 'opening_cash': 10000, 'positions': []})
    buy = make_trade(actual_price=10, planned_price=10, actual_quantity=100)
    sell = make_trade(trade_id='2'*32, operation='sell', actual_price=15, planned_price=15,
                      actual_quantity=100, executed_at='2026-08-12T06:00:00+00:00')
    for trade in (buy, sell):
        trades.insert_record(env / 'trades.sqlite3', trade)
    return buy, sell


def correction(trade_id, payload):
    return positions.create_correction({'target_event_type':'trade', 'target_event_id':trade_id,
                                       'after_payload':payload, 'reason':'synthetic correction'})


def test_correction_scoped_unavailable_and_snapshot_immutable(env):
    buy, sell = seed(env)
    original = pa.compute_attribution()
    saved = pa.save_attribution_snapshot(original)
    before = snapshots.get_snapshot(env/'pa.sqlite3', saved['snapshot_id'])
    correction(buy['trade_id'], {'actual_price':20})
    result = pa.compute_attribution()
    assert result['measurement_state'] == 'UNAVAILABLE'
    assert result['totals'] is None
    assert set(result['selected_trade_ids']) == {buy['trade_id'], sell['trade_id']}
    assert result['affected_trade_ids'] == [buy['trade_id']]
    with pytest.raises(pa.PerformanceAttributionProvenanceError):
        pa.save_attribution_snapshot(result)
    assert pa.compute_attribution_for_trade_ids([sell['trade_id']])['totals'] is not None
    detail = pa.get_attribution_snapshot(saved['snapshot_id'])
    assert detail['snapshot']['current_applicability']['state'] == 'REQUIRES_RECONCILIATION'
    assert snapshots.get_snapshot(env/'pa.sqlite3', saved['snapshot_id']) == before
    assert pa.list_attribution_snapshots()[0]['current_applicability']['state'] == 'REQUIRES_RECONCILIATION'


@pytest.mark.parametrize('value', [0, -1, True, float('nan'), float('inf')])
def test_invalid_price_correction_leaves_no_event(env, value):
    buy, _ = seed(env)
    before = events.list_events(env/'trades.sqlite3')
    with pytest.raises(positions.PositionValidationError):
        correction(buy['trade_id'], {'actual_price':value})
    assert events.list_events(env/'trades.sqlite3') == before


def test_cash_requires_opening_and_rejection_does_not_block_bootstrap(env):
    app = FastAPI()
    app.include_router(cash_event_router.router)
    with TestClient(app) as client:
        response = client.post('/api/account/cash-events', json={'event_type':'CASH_DEPOSIT','amount':100})
    assert response.status_code == 409
    assert events.list_events(env/'trades.sqlite3') == []
    positions.bootstrap_commit({'ledger_start_at':'2026-08-01','opening_cash':10000,'positions':[]})
    assert cash.create_cash_event({'event_type':'CASH_DEPOSIT','amount':100})['amount'] == 100


def formal_seed(env, *, execution='2026-08-11T06:00:00+00:00', recorded='2026-08-11T06:00:00+00:00', attributed='2026-08-11T07:00:00.000000Z'):
    decision = make_decision()
    frozen.write_frozen_decision(env/'frozen.sqlite3', decision)
    trade = make_trade(executed_at=execution, created_at=recorded)
    trades.insert_record(env/'trades.sqlite3', trade)
    attribution = fta.create_attribution(decision, trade, attribution_id='trade_attribution_'+'a'*32, created_at=attributed).to_dict()
    attribution_store.write_attribution(db_path=env/'attributions.sqlite3', record=attribution)
    return decision, trade


@pytest.mark.parametrize('kwargs', [
    {'execution':'2026-09-10T06:00:00+00:00', 'recorded':'2026-09-10T06:00:00+00:00', 'attributed':'2026-09-10T07:00:00.000000Z'},
    {'recorded':'2026-09-10T06:00:00+00:00', 'attributed':'2026-09-10T07:00:00.000000Z'},
    {'attributed':'2026-09-10T07:00:00.000000Z'},
])
def test_future_or_later_recorded_facts_not_counted(env, kwargs):
    decision, _ = formal_seed(env, **kwargs)
    result = outcome.evaluate_outcome(decision['decision_id'], evaluation_as_of='2026-09-01T00:00:00.000000Z')
    assert result['actual_capital_outcome']['state'] == 'NO_ACTUAL_TRADE'
    assert result['actual_capital_outcome']['pnl'] is None


def test_later_correction_and_void_are_historical_unavailable(env):
    decision, trade = formal_seed(env)
    correction(trade['trade_id'], {'actual_price':20})
    result = outcome.evaluate_outcome(decision['decision_id'], evaluation_as_of='2026-09-01T00:00:00.000000Z')
    assert result['actual_capital_outcome']['pnl_state'] == 'NOT_EVALUATED'
    assert 'HISTORICAL_ACTUAL_NOT_RECONSTRUCTIBLE' in result['reason_codes']
    trades.void_record_atomic(env/'trades.sqlite3', trade['trade_id'], 'synthetic void')
    result = outcome.evaluate_outcome(decision['decision_id'], evaluation_as_of='2026-09-01T00:00:00.000000Z')
    assert result['actual_capital_outcome']['pnl_state'] == 'NOT_EVALUATED'
    assert 'HISTORICAL_ACTUAL_NOT_RECONSTRUCTIBLE' in result['reason_codes']


def test_selected_rows_and_corrections_share_one_read_snapshot(env, monkeypatch):
    buy, _ = seed(env)
    with sqlite3.connect(env/'trades.sqlite3') as conn:
        conn.execute('PRAGMA journal_mode=WAL')
    original = events.list_corrections_on_connection
    wrote = False

    def interleave(conn, target_type, target_id):
        nonlocal wrote
        if not wrote:
            wrote = True
            correction(buy['trade_id'], {'actual_price':20})
        return original(conn, target_type, target_id)

    monkeypatch.setattr(events, 'list_corrections_on_connection', interleave)
    first = pa.compute_attribution()
    assert first['totals'] is not None  # coherent pre-write read snapshot
    assert pa.compute_attribution()['totals'] is None  # next snapshot sees correction


def test_effective_full_trade_checked_and_zero_costs_allowed(env):
    buy, _ = seed(env)
    correction(buy['trade_id'], {'actual_price':20, 'fee':0, 'other_cost':0})
    # Synthetic persisted legacy damage must not be laundered by patching another field.
    with sqlite3.connect(env/'trades.sqlite3') as conn:
        conn.execute("UPDATE account_events SET after_payload = ? WHERE event_type = 'CORRECTION'", (json.dumps({'actual_price':0}),))
    before = events.list_events(env/'trades.sqlite3')
    with pytest.raises(positions.PositionValidationError):
        correction(buy['trade_id'], {'fee':1})
    assert events.list_events(env/'trades.sqlite3') == before
    with pytest.raises(positions.PositionDerivationError):
        positions.derive_positions()
    correction(buy['trade_id'], {'actual_price':20})  # explicit valid repair remains possible


def test_current_correction_gives_scoped_not_evaluated_and_reveal_consistent(env):
    decision, trade = formal_seed(env)
    correction(trade['trade_id'], {'actual_price':20})
    result = outcome.evaluate_outcome(decision['decision_id'], evaluation_as_of='2027-09-01T00:00:00.000000Z')
    actual = result['actual_capital_outcome']
    assert actual['pnl'] is None
    assert actual['reason_codes'] == ['CORRECTED_TRADE_REQUIRES_RECONCILIATION']
    assert result['outcome_reveal']['actual_capital_outcome'] == actual
    import formal_decision_outcome as domain
    reveal = dict(result['outcome_reveal'])
    saved_hash = reveal.pop('outcome_reveal_hash')
    assert domain._ol1_hash(reveal) == saved_hash


def test_multiple_openings_reject_cash_without_mutation(env):
    positions.bootstrap_commit({'ledger_start_at':'2026-08-01','opening_cash':10000,'positions':[]})
    opening = events.list_events(env/'trades.sqlite3')[0]
    events.insert_event(env/'trades.sqlite3', {**opening, 'event_id':'aev_duplicate'})
    before = events.list_events(env/'trades.sqlite3')
    with pytest.raises(cash.CashEventBootstrapRequiredError):
        cash.create_cash_event({'event_type':'CASH_DEPOSIT','amount':100})
    assert events.list_events(env/'trades.sqlite3') == before


def test_concurrent_bootstrap_cash_cannot_create_orphan_cash(env):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(2)

    def opening():
        barrier.wait()
        return positions.bootstrap_commit({'ledger_start_at':'2026-08-01','opening_cash':10000,'positions':[]})

    def deposit():
        barrier.wait()
        try:
            return cash.create_cash_event({'event_type':'CASH_DEPOSIT','amount':100})
        except cash.CashEventBootstrapRequiredError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(opening), pool.submit(deposit)]
        results = [future.result(timeout=10) for future in futures]
    records = events.list_events(env/'trades.sqlite3')
    assert sum(r['event_type'] == 'ACCOUNT_OPENING' for r in records) == 1
    assert sum(r['event_type'] == 'CASH_DEPOSIT' for r in records) == int(results[1] is not None)


def test_later_void_of_correction_cannot_erase_historical_uncertainty(env):
    decision, trade = formal_seed(env)
    event = correction(trade['trade_id'], {'actual_price':20})
    with sqlite3.connect(env/'trades.sqlite3') as conn:
        conn.execute('UPDATE account_events SET created_at=?, voided_at=? WHERE event_id=?',
                     ('2026-08-20T00:00:00+00:00','2026-09-10T00:00:00+00:00',event['event']['event_id']))
    result = outcome.evaluate_outcome(decision['decision_id'], evaluation_as_of='2026-09-01T00:00:00.000000Z')
    assert result['actual_capital_outcome']['pnl'] is None
    assert 'HISTORICAL_ACTUAL_NOT_RECONSTRUCTIBLE' in result['reason_codes']


@pytest.mark.parametrize('patch', [{'actual_quantity':200}, {'fee':2}, {'other_cost':3}])
def test_all_accounting_corrections_fail_closed_and_void_restores_original(env, patch):
    buy, _ = seed(env)
    event = correction(buy['trade_id'], patch)['event']
    assert pa.compute_attribution()['totals'] is None
    with sqlite3.connect(env/'trades.sqlite3') as conn:
        conn.execute('UPDATE account_events SET voided_at=? WHERE event_id=?', ('2026-10-20T00:00:00+00:00',event['event_id']))
    assert pa.compute_attribution()['totals'] is not None


def test_live_api_unavailable_and_snapshot_conflict_is_structured(env):
    import performance_attribution_router
    buy, _ = seed(env)
    correction(buy['trade_id'], {'actual_price':20})
    app = FastAPI()
    app.include_router(performance_attribution_router.router)
    with TestClient(app) as client:
        live = client.get('/api/performance-attribution')
        frozen_response = client.post('/api/performance-attribution/snapshot', json={})
    assert live.status_code == 200
    assert live.json()['data']['totals'] is None
    assert frozen_response.status_code == 409
    assert frozen_response.json()['detail']['affected_trade_ids'] == [buy['trade_id']]
    assert pa.list_attribution_snapshots() == []


def test_legacy_cash_without_opening_is_diagnosed_not_rewritten(env):
    events.insert_event(env/'trades.sqlite3', {'event_id':'cev_legacy', 'event_type':'CASH_DEPOSIT',
                       'amount':100, 'provenance':'MANUAL', 'created_at':'2026-08-10T00:00:00+00:00'})
    before = events.list_events(env/'trades.sqlite3')
    result = positions.derive_positions()
    assert result['bootstrap_status'] == 'NOT_BOOTSTRAPPED'
    assert any('CASH_WITHOUT_ACCOUNT_OPENING' in item for item in result['data_limitations'])
    assert events.list_events(env/'trades.sqlite3') == before
