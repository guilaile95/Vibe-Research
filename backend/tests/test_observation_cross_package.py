"""Acquired-path simulation in temporary raw receipts, never genuine market data.

Runs after P2/P3 integration. It deliberately sets fixture=False only inside the
fresh temporary archive to test the real admission branch without any provider.
"""
import json
import socket
from datetime import datetime, timezone

import pytest

archive = pytest.importorskip('shortline_research_archive')
C = pytest.importorskip('shortline_research_contract')
theme_capture = pytest.importorskip('short_term_theme_capture')
from fact_lake_store import initialize_fact_lake
import next_day_verification as verification
import verification_research_observation as research
import short_term_fact_store as facts
from test_short_term_fact_store import _envelope

DAYS = ['2026-07-27', '2026-07-28', '2026-07-29', '2026-07-30', '2026-07-31']
CODES = ['000001', '600001', '300001']


def seed_day(lake, day, *, current=False, height=2):
    rows = [{'c': '000001', 'lbc': height if current else 1, 'fbt': 93000, 'lbt': 143000, 'zbc': 1, 'fund': 1000}]
    if not current:
        rows.append({'c': '600001', 'lbc': 2, 'fbt': 93000, 'lbt': 143000, 'zbc': 1, 'fund': 1000})
    for kind, members in [('limit_up', rows), ('broken', [] if current else [{'c': '300001', 'lbc': 1, 'fbt': 93000, 'lbt': 143000, 'zbc': 1, 'fund': 1000}]), ('limit_down', [])]:
        metadata = {'kind': kind, 'trade_date': day, 'provider': 'eastmoney_push2ex', 'endpoint': C.ENDPOINTS[kind],
                    'captured_at': day+'T07:35:00Z', 'http_status': 200, 'fixture': False, 'page_index': 0, 'page_count': 1,
                    'batch_id': day+'-'+kind, 'request_shape': 'offline-acquired-branch-test', 'requested_codes': []}
        raw = C.canonical({'date': day.replace('-', ''), 'data': {'pool': members, 'tc': len(members), 'is_final': True, 'revision_id': 'offline-test'}}).encode()
        archive.persist_capture(lake, raw, metadata)
    for kind, fields, items in [
        ('daily_prices', ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'pre_close', 'trade_status', 'vol'],
         [['000001.SZ', day.replace('-', ''), 10.5, 11, 10, 11, 10, 'traded', 100], ['600001.SH', day.replace('-', ''), 10, 10, 9.3, 9.3, 10, 'traded', 100], ['300001.SZ', day.replace('-', ''), 10, 10, 10, 10, 10, 'traded', 100]]),
        ('daily_limits', ['ts_code', 'trade_date', 'up_limit', 'down_limit'],
         [[code+('.SH' if code.startswith('6') else '.SZ'), day.replace('-', ''), 11 if code != '300001' else 12, 9 if code != '300001' else 8] for code in CODES]),
    ]:
        metadata = {'kind': kind, 'trade_date': day, 'provider': 'tushare_pro', 'endpoint': C.ENDPOINTS[kind],
                    'captured_at': day+'T07:35:00Z', 'http_status': 200, 'fixture': False, 'page_index': 0, 'page_count': 1,
                    'batch_id': day+'-'+kind, 'request_shape': 'offline-acquired-branch-test', 'requested_codes': CODES}
        archive.persist_capture(lake, C.canonical({'code': 0, 'data': {'fields': fields, 'items': items}}).encode(), metadata)
    source_time = int(datetime.fromisoformat(day+'T09:30:00+08:00').timestamp())
    page = {'status_code': 0, 'data': {'page': {'total': len(rows)}, 'info': [
        {'code': row['c'], 'reason_type': '芯片+半导体', 'first_limit_up_time': source_time, 'reason_info': '离线合成测试'} for row in rows]}}
    theme_capture.store_ths_theme_capture(lake, [json.dumps(page).encode()], trade_date=day, captured_at=day+'T07:45:00Z', fixture=False)


def test_raw_archive_to_eight_condition_freeze_and_next_day(tmp_path, monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('outbound prohibited')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path/'personal'))
    monkeypatch.setenv('VR_FACT_LAKE_ROOT', str(tmp_path/'archive'))
    clock = [datetime.fromisoformat('2026-07-31T08:15:00+00:00')]
    class ServerClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz or timezone.utc)
    monkeypatch.setattr(archive, 'datetime', ServerClock)
    monkeypatch.setattr(verification, '_now', lambda: clock[0])
    lake = initialize_fact_lake(tmp_path/'archive')
    for day in DAYS:
        seed_day(lake, day, current=day == DAYS[-1])
    def final(day, count):
        at = day+'T07:10:00+00:00'
        env = _envelope(day, fetched_at=at, snapshot_at=at)
        env['sections']['facts'].update(trade_date=day, session='final', is_final=True, source_ids=['offline-test'], fetched_at=at, snapshot_at=at,
                                       facts={'limit_up_count': count, 'failed_board_rate': .25})
        monkeypatch.setattr(facts, '_utc_now', lambda: at)
        facts.save_daily_facts(env)
    final(DAYS[-1], 40)
    evidence = research.read_current(DAYS[-1], lambda: verification._stamp(clock[0]))
    assert evidence is not None
    assert evidence['values'] == {'highest_board': 2, 'promotion_1to2': 1, 'money_effect_median': pytest.approx(1.5),
                                  'deep_loss_count': 1, 'theme_concentration': 1, 'market_limit_down': 0}
    request = verification.SavePlan(revision=0, items=[verification.Condition(metric=metric, direction='up') for metric in verification.METRICS])
    saved = verification.replace_plan(DAYS[-1], request)
    assert len(saved['items']) == 8 and all(item['prior_value'] is not None for item in saved['items'])
    frozen = saved['items'][2]['prior_evidence']
    assert frozen['source_receipts_sha256'] == evidence['source_receipts_sha256']
    clock[0] = datetime.fromisoformat('2026-08-03T08:15:00+00:00')
    seed_day(lake, '2026-08-03', current=True, height=3)
    final('2026-08-03', 60)
    result = verification.view(DAYS[-1])
    indexed = {row['metric']: row for row in result['items']}
    assert indexed['highest_board']['current_value'] == 3 and indexed['highest_board']['verified'] is True
    assert indexed['highest_board']['prior_evidence'] == frozen
    assert indexed['theme_concentration']['current_value'] == 1
    assert indexed['promotion_1to2']['current_value'] is None and indexed['promotion_1to2']['verified'] is None
    assert result['summary']['unknown'] == 1
