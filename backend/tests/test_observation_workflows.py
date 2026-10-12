"""Synthetic software acceptance. All outbound network calls are forbidden."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import socket
import sqlite3
import sys
from types import SimpleNamespace

from fastapi import FastAPI
import httpx
import pytest

import next_day_verification as verification
import observation_workflow_store as store
import observation_workflows as obs
import observation_reminders as reminders
import observation_workflows_router as router
from observation_workflow_preview import preview
import verification_research_observation as research

DAY = '2026-07-31'
GROUPS = {'watchlist': ['sh600000'], 'holdings': ['sh600000']}

@pytest.fixture(autouse=True)
def guarded(monkeypatch, tmp_path):
    loop = asyncio.new_event_loop()
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('VR_FACT_LAKE_ROOT', raising=False)
    clock = [obs.instant(DAY+'T01:25:00Z')]
    monkeypatch.setattr(obs, '_now', lambda: clock[0])
    monkeypatch.setattr(verification, '_now', lambda: clock[0])
    def deny(*args, **kwargs):
        raise AssertionError('outbound network prohibited')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)
    app = FastAPI()
    app.include_router(router.router)
    async def call(method, path, body):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            return await client.request(method, path, json=body)
    yield clock, lambda method, path, body=None: loop.run_until_complete(call(method, path, body))
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.run_until_complete(loop.shutdown_default_executor())
    loop.close()


def quote(clock, price=10, **extra):
    return [{'symbol': 'sh600000', 'price': price, 'open_price': 10.4, 'previous_close': 10,
             'provider_at': obs.stamp(clock[0]), 'source_id': 'SYNTHETIC', 'is_limit_up': False, **extra}]


def snapshot_files(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}


def test_get_empty_and_preview_never_create_files(guarded, tmp_path, monkeypatch):
    clock, call = guarded
    assert call('GET', '/api/observation-workflows/'+DAY).status_code == 200
    assert list(tmp_path.iterdir()) == []
    # Preview uses the request-scoped synthetic clock, not the test global clock.
    monkeypatch.setattr(obs, '_now', lambda: obs._preview_clock.get() or clock[0])
    result = call('GET', '/api/observation-workflows/preview')
    assert result.status_code == 200, result.text
    body = result.json()['data']
    assert body['synthetic'] is True
    assert [s['state'] for s in body['slots']] == ['SAVED']*6
    assert len(body['events']) == 1
    assert next(t for t in body['tasks'] if t['kind'] == 'watch_changes')['status'] == 'COMPLETE'
    assert list(tmp_path.iterdir()) == []


def test_slot_auction_open_and_six_immutable_keys(guarded, tmp_path):
    clock, _ = guarded
    for slot in obs.SLOTS:
        clock[0] = obs.window(DAY, slot)[0]
        result = obs.capture_slot(DAY, slot, GROUPS, lambda _: quote(clock))
        assert result['status'] == 'SAVED'
        assert result['cohort']['expected'] == 1
        assert result['cohorts']['holdings']['samples'] == 1
        assert result['rows'][0]['price'] == (10.4 if slot == '09:25' else 10)
        assert obs.capture_slot(DAY, slot, GROUPS, lambda _: (_ for _ in ()).throw(AssertionError('duplicate fetch'))) == result
    before = snapshot_files(tmp_path)
    assert len([s for s in obs.view(DAY)['slots'] if s['state'] == 'SAVED']) == 6
    assert snapshot_files(tmp_path) == before


@pytest.mark.parametrize('at', ['2026-07-31T01:24:59.999999Z', '2026-07-31T01:29:00Z', '2026-08-03T01:25:00Z'])
def test_slot_rejects_outside_exact_window_before_write(guarded, tmp_path, at):
    guarded[0][0] = obs.instant(at)
    with pytest.raises(obs.ObservationError):
        obs.capture_slot(DAY, '09:25', GROUPS, lambda _: [])
    assert list(tmp_path.iterdir()) == []


def test_failed_partial_retry_does_not_consume_success_slot(guarded):
    clock, _ = guarded
    first = obs.capture_slot(DAY, '09:25', GROUPS, lambda _: quote(clock, open_price=None))
    assert first['status'] == 'PARTIAL'
    assert first['cohort']['median_pct'] is None
    assert obs.view(DAY)['slots'][0]['observation'] is None
    with pytest.raises(obs.ObservationError, match='30'):
        obs.capture_slot(DAY, '09:25', GROUPS, lambda _: [])
    clock[0] = obs.instant(DAY+'T01:25:30Z')
    assert obs.capture_slot(DAY, '09:25', GROUPS, lambda _: quote(clock))['status'] == 'SAVED'
    assert len(obs.view(DAY)['slots'][0]['attempts']) == 2


def test_capture_crosses_cutoff_and_clock_rollback(guarded):
    clock, _ = guarded
    def fetch(_):
        clock[0] = obs.instant(DAY+'T01:29:00Z')
        return quote(clock)
    assert obs.capture_slot(DAY, '09:25', GROUPS, fetch)['status'] == 'FAILED'
    assert obs.view(DAY)['slots'][0]['state'] == 'MISSING'
    clock[0] = obs.instant(DAY+'T01:25:40Z')
    with pytest.raises(obs.ObservationError):
        obs.capture_slot(DAY, '09:25', GROUPS, lambda _: quote(clock))


def test_retries_exhausted(guarded):
    clock, _ = guarded
    for seconds in (0, 30, 60):
        clock[0] = obs.instant(f'{DAY}T01:2{5+seconds//60}:{seconds%60:02d}Z')
        assert obs.capture_slot(DAY, '09:25', GROUPS, lambda _: [])['status'] == 'PARTIAL'
    assert obs.view(DAY)['slots'][0]['state'] == 'RETRIES_EXHAUSTED'
    clock[0] = obs.instant(DAY+'T01:27:00Z')
    with pytest.raises(obs.ObservationError, match='用尽'):
        obs.capture_slot(DAY, '09:25', GROUPS, lambda _: quote(clock))


def test_two_threads_fetch_slot_once(guarded):
    clock, _ = guarded
    called = []
    def fetch(_):
        called.append(1)
        return quote(clock)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(obs.capture_slot, DAY, '09:25', GROUPS, fetch) for _ in range(2)]
        results = [future.result() for future in futures]
    assert results[0] == results[1]
    assert len(called) == 1


def test_quote_time_unknown_stale_future_and_session(guarded):
    clock, _ = guarded
    for at in (None, '2026-07-30T01:25:00Z', DAY+'T01:25:01Z'):
        rows, missing = obs.qualify_quotes(quote(clock, provider_at=at), obs.watch_universe(GROUPS), clock[0])
        assert rows == [] and 'sh600000' in missing
    with pytest.raises(obs.ObservationError):
        obs.record_watch_quotes(GROUPS, quote(clock))


def test_watch_first_frame_move_cooldown_and_restart(guarded):
    clock, _ = guarded
    clock[0] = obs.instant(DAY+'T02:00:00Z')
    assert obs.record_watch_quotes(GROUPS, quote(clock))['events'] == []
    clock[0] = obs.instant(DAY+'T02:01:00Z')
    found = obs.record_watch_quotes(GROUPS, quote(clock, 10.2))['events']
    assert len(found) == 1 and found[0]['kind'] == 'RAPID_UP'
    assert obs.record_watch_quotes(GROUPS, quote(clock, 10.2))['events'] == []
    clock[0] = obs.instant(DAY+'T02:02:00Z')
    assert obs.record_watch_quotes(GROUPS, quote(clock, 10.4))['events'] == []
    # State is database-owned, not an in-memory/tab counter.
    with store.read() as conn:
        assert len(store.rows(conn, 'observation_events')) == 1
    clock[0] = obs.instant(DAY+'T05:00:00Z')
    assert obs.record_watch_quotes(GROUPS, quote(clock, 11))['events'] == []


def test_limit_transitions_first_frame_unknown_not_false(guarded):
    clock, _ = guarded
    clock[0] = obs.instant(DAY+'T02:00:00Z')
    assert obs.record_watch_quotes(GROUPS, quote(clock, is_limit_up=None))['events'] == []
    clock[0] = obs.instant(DAY+'T02:00:10Z')
    assert obs.record_watch_quotes(GROUPS, quote(clock, is_limit_up=True))['events'] == []
    clock[0] = obs.instant(DAY+'T02:00:20Z')
    assert obs.record_watch_quotes(GROUPS, quote(clock, is_limit_up=False))['events'][0]['kind'] == 'OPENED'


def test_holiday_calendar_failure_and_http_no_clock_injection(guarded, monkeypatch):
    clock, call = guarded
    clock[0] = obs.instant('2026-10-01T01:25:00Z')
    with pytest.raises(obs.ObservationError):
        obs.capture_slot('2026-10-01', '09:25', GROUPS, lambda _: [])
    monkeypatch.setattr(obs.trade_calendar, '_load_calendar', lambda: None)
    assert obs.view(DAY)['calendar_state'] == 'CALENDAR_UNKNOWN'
    assert call('GET', '/api/observation-workflows/'+DAY+'?observed_at=anything').status_code == 422
    assert call('POST', f'/api/observation-workflows/{DAY}/tasks/premarket/run', {'now': 'anything'}).status_code == 422


def batch(clock, code, since, **extra):
    return {'status': 'COMPLETE', 'since': since, 'through': obs.stamp(clock[0]), 'has_more': False,
            'items': [{'id': 'fixture-id', 'symbol': code, 'published_at': DAY+'T08:00:00Z', 'title': '合成公告', 'source_id': 'synthetic'}], **extra}


def test_per_symbol_failure_does_not_advance_cursor(guarded):
    clock, _ = guarded
    clock[0] = obs.instant(DAY+'T08:15:00Z')
    def fetch(code, since):
        return batch(clock, code, since, has_more=code == 'sz000001')
    task = reminders.run_task(DAY, 'watch_changes', fetch, ['sh600000', 'sz000001'])
    assert task['status'] == 'PARTIAL'
    assert task['output']['missing'] == ['sz000001']
    with store.read() as conn:
        assert conn.execute('SELECT symbol FROM observation_cursors').fetchall() == [('sh600000',)]
        assert len(store.rows(conn, 'observation_notices')) == 1


def test_cursor_rolls_back_entire_invalid_batch(guarded):
    clock, _ = guarded
    clock[0] = obs.instant(DAY+'T08:15:00Z')
    def fetch(code, since):
        value = batch(clock, code, since)
        value['items'] *= 2
        return value
    task = reminders.run_task(DAY, 'watch_changes', fetch, ['sh600000'])
    assert task['status'] == 'PARTIAL'
    with store.read() as conn:
        assert conn.execute('SELECT * FROM observation_cursors').fetchall() == []
        assert store.rows(conn, 'observation_notices') == []


def test_premarket_after_1130_rejected_and_crossing_rolls_back(guarded):
    clock, _ = guarded
    clock[0] = obs.instant(DAY+'T03:29:59Z')
    def fetch():
        clock[0] = obs.instant(DAY+'T03:30:00Z')
        return {}
    task = reminders.run_task(DAY, 'premarket', fetch)
    assert task['status'] == 'FAILED'
    with pytest.raises(obs.ObservationError):
        reminders.run_task(DAY, 'premarket', fetch)


def test_acknowledge_does_not_complete_partial_task(guarded):
    clock, call = guarded
    clock[0] = obs.instant(DAY+'T08:15:00Z')
    response = call('POST', f'/api/observation-workflows/{DAY}/tasks/watch_changes/run', {})
    assert response.status_code == 200
    response = call('POST', f'/api/observation-workflows/{DAY}/tasks/watch_changes/acknowledge', {})
    assert response.json()['data']['acknowledged'] is True
    assert response.json()['data']['status'] == 'PARTIAL'


def test_due_next_trade_day_keeps_missing_unknown(guarded):
    clock, _ = guarded
    clock[0] = obs.instant(DAY+'T08:00:00Z')
    verification.replace_plan(DAY, verification.SavePlan(revision=0, items=[verification.Condition(metric='limit_up_count', direction='up')]))
    clock[0] = obs.instant('2026-08-03T08:29:59Z')
    assert obs.due_verifications() == []
    clock[0] = obs.instant('2026-08-04T01:00:00Z')
    due = obs.due_verifications()[0]
    assert due['target_date'] == '2026-08-03' and due['due_at'].startswith('2026-08-03T08:30:00')
    assert due['state'] == 'DUE_UNRESOLVED'
    assert due['items'][0]['verified'] is None


def fake_research(day, value=3, fixture=False):
    return {'schema_version': 'shortline-research.v1', 'trade_date': day, 'previous_trade_date': '2026-07-30', 'fixture': fixture,
            'selection_mode': 'CURRENT_STORED_POSTHOC', 'point_in_time_claim': 'NONE', 'status': 'partial',
            'projection': {'daily': {'highest_board': value}, 'cohort': {'groups': {}, 'promotion': []}},
            'evidence': [{'trade_date': day, 'kind': 'limit_up', 'complete': True, 'status': 'normal', 'receipts': [{'observation_id': 'synthetic-receipt', 'raw_payload_hash': 'sha256:'+'a'*64,
                          'source_ids': ['eastmoney_push2ex:getTopicZTPool'], 'normalizer_version': 'shortline-captured-providers.v1', 'captured_at': day+'T07:10:00Z', 'locally_received_at': day+'T07:11:00Z', 'committed_at': None}]}]}


def test_eight_conditions_freeze_versioned_research_not_fake_stored_time(guarded, monkeypatch):
    clock, _ = guarded
    clock[0] = obs.instant(DAY+'T08:00:00Z')
    current = [3]
    monkeypatch.setitem(sys.modules, 'shortline_research_service', SimpleNamespace(query_shortline_research=lambda day: fake_research(day, current[0])))
    saved = verification.replace_plan(DAY, verification.SavePlan(revision=0, items=[verification.Condition(metric='highest_board', direction='up')]))
    item = saved['items'][0]
    assert len(saved['metrics']) == 8 and item['prior_value'] == 3
    assert item['baseline']['rate'] is None and item['baseline']['samples'] == 0
    assert item['prior_evidence']['schema_version'] == research.VERSION
    assert 'stored_at' not in item['prior_evidence']
    current[0] = 9
    assert verification.view(DAY)['items'][0]['prior_value'] == 3
    clock[0] = obs.instant('2026-08-03T08:00:00Z')
    result = verification.view(DAY)['items'][0]
    assert result['current_value'] == 9 and result['verified'] is True
    with pytest.raises(verification.VerificationError):
        verification.replace_plan(DAY, verification.SavePlan(revision=1, items=[]))


def test_research_fixtures_future_receipts_and_digest_corruption_rejected(guarded, monkeypatch):
    clock, _ = guarded
    clock[0] = obs.instant(DAY+'T08:00:00Z')
    monkeypatch.setitem(sys.modules, 'shortline_research_service', SimpleNamespace(query_shortline_research=lambda day: fake_research(day, fixture=True)))
    assert research.read_current(DAY, lambda: obs.stamp(clock[0])) is None
    source = fake_research(DAY)
    source['evidence'][0]['receipts'][0]['captured_at'] = DAY+'T09:00:00Z'
    monkeypatch.setitem(sys.modules, 'shortline_research_service', SimpleNamespace(query_shortline_research=lambda day: source))
    assert research.read_current(DAY, lambda: obs.stamp(clock[0])) is None


def test_existing_tencent_quote_adapter_uses_open_timestamp_and_yuan(guarded):
    from observation_producer_adapters import tencent_quote_rows, capture_using_existing_quote_port
    clock, _ = guarded
    provider = {'600000': {'price': 10, 'open': 10.5, 'last_close': 10, 'data_time': DAY+'T09:25:00+08:00',
                           'trade_date': DAY, 'limit_up': None, 'amount_wan': 5}}
    row = tencent_quote_rows(provider)[0]
    assert row['provider_at'].startswith(DAY+'T01:25:00') and row['turnover_yuan'] == 50000
    assert row['is_limit_up'] is None
    result = capture_using_existing_quote_port(DAY, '09:25', GROUPS, lambda codes: provider)
    assert result['rows'][0]['price'] == 10.5
    assert result['rows'][0]['pct'] == pytest.approx(5)


def test_raw_announcement_adapter_requires_complete_timestamped_page(guarded):
    from observation_producer_adapters import eastmoney_announcement_page
    clock, _ = guarded
    clock[0] = obs.instant(DAY+'T08:15:00Z')
    raw = {'data': {'total_hits': 1, 'list': [{'art_code': 'id-1', 'title': '合成公告',
            'codes': [{'stock_code': '600000'}], 'notice_date': DAY+' 16:00:00'}]}}
    value = eastmoney_announcement_page(raw, 'sh600000', None, obs.stamp(clock[0]))
    assert value['items'][0]['published_at'].startswith(DAY+'T08:00:00')
    with store.write() as conn:
        assert reminders.announcement_batch(conn, DAY, 'sh600000', value, clock[0])['status'] == 'COMPLETE'
    raw['data']['total_hits'] = 51
    assert eastmoney_announcement_page(raw, 'sh600000', None, obs.stamp(clock[0]))['status'] == 'NOT_CHECKED'
    raw['data']['total_hits'] = 1
    raw['data']['list'][0]['notice_date'] = DAY
    with pytest.raises(obs.ObservationError, match='只有日期'):
        eastmoney_announcement_page(raw, 'sh600000', None, obs.stamp(clock[0]))


def test_ratio_overflow_and_nonfinite_median_fail_closed(guarded):
    clock, _ = guarded
    rows, missing = obs.qualify_quotes(quote(clock, 1.0, previous_close=5e-324), obs.watch_universe(GROUPS), clock[0])
    assert rows == [] and missing == {'sh600000': 'DERIVED_RETURN_OUT_OF_RANGE'}
    with pytest.raises(obs.ObservationError):
        obs.cohort_stats([{'pct': float('inf')}], 1)
    clock[0] = obs.instant(DAY+'T02:00:00Z')
    assert obs.record_watch_quotes(GROUPS, quote(clock, 5e-324, previous_close=5e-324))['events'] == []
    clock[0] = obs.instant(DAY+'T02:01:00Z')
    result = obs.record_watch_quotes(GROUPS, quote(clock, 1.0, previous_close=5e-324))
    assert result['events'] == [] and result['missing']['sh600000'] == 'DERIVED_RETURN_OUT_OF_RANGE'


def test_stored_slot_identity_tamper_is_not_projected(guarded):
    clock, _ = guarded
    value = obs.capture_slot(DAY, '09:25', GROUPS, lambda _: quote(clock))
    value['trade_date'] = '2026-07-30'
    with store.write() as conn:
        conn.execute('UPDATE observation_slots SET payload=?', (store.encode(value),))
    with pytest.raises(store.StoreError):
        obs.view(DAY)


def test_read_fails_if_source_deleted_or_sidecar_is_dangling_link(guarded, tmp_path):
    clock, _ = guarded
    obs.capture_slot(DAY, '09:25', GROUPS, lambda _: quote(clock))
    path = store.facts.resolve_db_path()
    side = path.with_name(path.name+'-journal')
    try:
        side.symlink_to(tmp_path/'missing-target')
    except OSError:
        pytest.skip('symlink creation requires platform privilege')
    with pytest.raises(store.StoreError):
        obs.view(DAY)
    side.unlink()
    with pytest.raises(store.StoreError):
        with store.read():
            path.unlink()


def test_read_reuses_accepted_windows_snapshot_helper(guarded, monkeypatch):
    import fact_lake_store
    clock, _ = guarded
    obs.capture_slot(DAY, '09:25', GROUPS, lambda _: quote(clock))
    original = fact_lake_store._snapshot_descriptor_matches
    calls = []
    def check(left, right):
        calls.append(1)
        return original(left, right)
    monkeypatch.setattr(fact_lake_store, '_snapshot_descriptor_matches', check)
    assert obs.view(DAY)['slots'][0]['state'] == 'SAVED'
    assert len(calls) >= 3


@pytest.mark.parametrize('field,bad', [('observation_id', ''), ('raw_payload_hash', 'sha256:fake'), ('captured_at', '2027-01-01T00:00:00Z'), ('source_ids', ['untrusted']), ('normalizer_version', 'unknown')])
def test_recomputed_digest_cannot_hide_invalid_stored_research_receipts(guarded, monkeypatch, field, bad):
    import hashlib
    clock, _ = guarded
    clock[0] = obs.instant(DAY+'T08:00:00Z')
    monkeypatch.setitem(sys.modules, 'shortline_research_service', SimpleNamespace(query_shortline_research=lambda day: fake_research(day)))
    verification.replace_plan(DAY, verification.SavePlan(revision=0, items=[verification.Condition(metric='highest_board', direction='up')]))
    with sqlite3.connect(verification.journal_path()) as conn:
        payload = json.loads(conn.execute('SELECT payload FROM plans').fetchone()[0])
        evidence = payload[0]['prior_evidence']
        evidence['source_receipts'][0]['receipts'][0][field] = bad
        raw = json.dumps(evidence['source_receipts'], sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        evidence['source_receipts_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
        conn.execute('UPDATE plans SET payload=?', (json.dumps(payload),))
    with pytest.raises(verification.JournalError):
        verification.view(DAY)


def test_empty_or_future_premarket_rows_cannot_be_complete(guarded):
    clock, _ = guarded
    clock[0] = obs.instant(DAY+'T01:05:00Z')
    def source(row):
        return {key: {'trade_date': DAY, 'status': 'COMPLETE', 'complete': True, 'source_total': 1, 'source_id': 'synthetic', 'captured_at': obs.stamp(clock[0]), 'rows': [row]} for key in reminders.PREMARKET_SECTIONS}
    assert reminders.premarket(DAY, source({}))['status'] == 'PARTIAL'
    assert reminders.premarket(DAY, source({'title': 'future', 'value': 1, 'unit': '%', 'published_at': DAY+'T09:00:00Z'}))['status'] == 'PARTIAL'
    clock[0] = obs.instant(DAY+'T07:40:00Z')
    result = reminders.run_task(DAY, 'close_digest', lambda: {'trade_date': DAY, 'status': 'COMPLETE'})
    assert result['status'] == 'FAILED'


def test_due_projection_has_explicit_work_budget(guarded, monkeypatch):
    clock, _ = guarded
    clock[0] = obs.instant('2026-10-12T09:00:00Z')
    days = obs.trade_calendar._load_calendar()[-200:-170]
    plans = {day: {'revision': 1, 'items': [{'metric': 'limit_up_count'}]} for day in days}
    # Use dates definitely before the simulated clock.
    days = [d for d in obs.trade_calendar._load_calendar() if '2026-06-01' <= d <= '2026-07-31'][:30]
    plans = {day: {'revision': 1, 'items': [{'metric': 'limit_up_count'}]} for day in days}
    monkeypatch.setattr(verification, '_read_plans', lambda _: plans)
    called = []
    monkeypatch.setattr(verification, '_results', lambda day, plan, now: called.append(day) or [])
    result = obs.due_projection()
    assert len(called) == 20 and result['coverage']['eligible_plans'] == 30 and result['coverage']['has_more'] is True
    assert called == sorted(days, reverse=True)[:20]


def test_goldens_equal_preview_and_read_routes(guarded, monkeypatch):
    from pathlib import Path
    clock, _ = guarded
    monkeypatch.setattr(obs, '_now', lambda: obs._preview_clock.get() or clock[0])
    root = Path(__file__).parents[2]/'frontend/tests/fixtures'
    assert preview() == json.loads((root/'observation-workflows-preview.json').read_text(encoding="utf-8"))
    clock[0] = obs.instant('2026-08-03T00:00:00Z')
    for day, expected in json.loads((root/'observation-workflows-empty.json').read_text(encoding="utf-8")).items():
        assert obs.view(day) == expected


def test_irrelevant_preclose_source_keeps_valid_highest_board(guarded, monkeypatch):
    clock, _ = guarded
    clock[0] = obs.instant(DAY+'T08:00:00Z')
    source = fake_research(DAY)
    invalid = json.loads(json.dumps(source['evidence'][0]))
    invalid['kind'] = 'daily_prices'
    invalid['receipts'][0].update(observation_id='other-receipt', source_ids=['tushare_pro:daily'], captured_at=DAY+'T06:00:00Z')
    source['evidence'].append(invalid)
    monkeypatch.setitem(sys.modules, 'shortline_research_service', SimpleNamespace(query_shortline_research=lambda day: source))
    value = research.read_current(DAY, lambda: obs.stamp(clock[0]))
    assert value['values']['highest_board'] == 3
    assert len(value['source_receipts'][0]['receipts']) == 1
    assert value['values']['money_effect_median'] is None


def test_nonnull_reading_requires_exact_day_dependency_even_with_valid_digest(guarded, monkeypatch):
    import hashlib
    clock, _ = guarded
    clock[0] = obs.instant(DAY+'T08:00:00Z')
    monkeypatch.setitem(sys.modules, 'shortline_research_service', SimpleNamespace(query_shortline_research=lambda day: fake_research(day)))
    original = research.read_current(DAY, lambda: obs.stamp(clock[0]))
    for alter in ('old_date', 'promotion_without_cohort', 'theme_without_tags'):
        evidence = json.loads(json.dumps(original))
        source = evidence['source_receipts'][0]
        if alter == 'old_date':
            source['receipts'][0]['trade_date'] = '2025-01-01'
        elif alter == 'promotion_without_cohort':
            source['values']['promotion_1to2'] = 1
            evidence['values']['promotion_1to2'] = 1
        else:
            source.update(source='theme_research', schema_version='short-term-theme-research-archive-v1', values={'theme_concentration': 1})
            evidence['values'] = dict.fromkeys(research.KEYS); evidence['values']['theme_concentration'] = 1
        encoded = json.dumps(evidence['source_receipts'], sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        evidence['source_receipts_sha256'] = hashlib.sha256(encoded.encode()).hexdigest()
        assert not research.validate(evidence, DAY, obs.stamp(clock[0]), verification._value), alter
