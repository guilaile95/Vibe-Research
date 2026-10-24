"""Offline regression evidence for Discovery snapshot and provider lifetimes."""
from __future__ import annotations

import copy
import csv
import multiprocessing
import os
import threading
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import discovery_service as discovery
import public_data_budget as budget
import research_data_plane as rdp


def _source(path: Path, close: int) -> Path:
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['code', 'trade_date', 'open', 'high', 'low', 'close', 'volume'])
        for code in ('000001', '000002'):
            writer.writerow([code, '2026-08-28', close, close + 1, close - 1, close, 100])
    return path


def test_rdp_active_manifest_replacement_cannot_mix_discovery_pages(tmp_path, monkeypatch):
    root = tmp_path / 'rdp'
    first = rdp.import_csv(_source(tmp_path / 'a.csv', 10), root=root)
    query = rdp.query_full_market
    calls = []
    pages = []

    def replace_active_after_first(**kwargs):
        calls.append(kwargs)
        result = query(root=root, **kwargs)
        pages.append(copy.deepcopy(result))
        if kwargs['offset'] == 0:
            rdp.import_csv(_source(tmp_path / 'b.csv', 100), root=root)
        return result

    monkeypatch.setattr(rdp, '_MAX_LIMIT', 1)
    monkeypatch.setattr(rdp, 'query_full_market', replace_active_after_first)
    result = discovery._default_full_market()
    assert [row['latest_close'] for row in result['rows']] == [10, 10]
    assert calls[1]['snapshot_id'] == first['snapshot_id']
    assert result['snapshot_id'] == first['snapshot_id']
    assert result['coverage'] == pages[0]['coverage']
    assert result['page_receipts'] == [page['replay_receipt'] for page in pages]
    assert 'replay_receipt' not in result, 'a first-page digest must not claim the aggregated rows'
    assert result['receipt_scope'] == 'PAGED_SOURCE_RESPONSES'
    assert result['next_offset'] is None and result['next_page'] is None
    assert result['returned_rows'] == result['total_rows'] == 2


def _page(offset: int) -> dict:
    return {
        'snapshot_id': 'a' * 64, 'status': 'normal', 'as_of': '2026-08-28',
        'provenance': {'artifact_sha256': 'b' * 64},
        'coverage': {'code_count': 2}, 'total_rows': 2, 'returned_rows': 1,
        'rows': [{'code': f'00000{offset + 1}', 'latest_date': '2026-08-28'}],
        'next_offset': 1 if offset == 0 else None,
        'next_page': {'snapshot_id': 'a' * 64, 'offset': 1} if offset == 0 else None,
        'replay_receipt': {'snapshot_id': 'a' * 64, 'artifact_sha256': 'b' * 64,
                           'query': 'query_full_market', 'parameters': {'offset': offset, 'limit': 1},
                           'result_sha256': str(offset) * 64},
    }


@pytest.mark.parametrize('change', [
    {'snapshot_id': 'c' * 64}, {'as_of': '2026-08-27'},
    {'rows': [{'code': '000001'}]}, {'total_rows': 3},
    {'coverage': {'code_count': 3}}, {'returned_rows': 0},
    {'replay_receipt': {'snapshot_id': 'c' * 64}},
])
def test_rdp_inconsistent_pages_fail_closed(change, monkeypatch):
    def query(**kwargs):
        page = _page(kwargs['offset'])
        if kwargs['offset']:
            page.update(change)
        return page
    monkeypatch.setattr(rdp, '_MAX_LIMIT', 1)
    monkeypatch.setattr(rdp, 'query_full_market', query)
    with pytest.raises(rdp.ResearchDataPlaneValidationError):
        discovery._default_full_market()


def test_discovery_rdp_dataset_preserves_snapshot_receipts_and_coverage(monkeypatch):
    monkeypatch.setattr(rdp, '_MAX_LIMIT', 1)
    monkeypatch.setattr(rdp, 'query_full_market', lambda **kw: _page(kw['offset']))
    envelope = discovery._default_full_market()
    providers = replace(discovery.DEFAULT_PROVIDERS, full_market=lambda: envelope)
    _, rows, dataset = discovery._full_market_rows(providers, '2026-08-28T07:00:00Z', '2026-08-28')
    assert len(rows) == 2
    assert dataset['snapshot_id'] == envelope['snapshot_id']
    assert dataset['page_receipts'] == envelope['page_receipts']
    assert dataset['source_coverage'] == envelope['coverage']


def _providers(financials, announcements):
    return replace(discovery.DEFAULT_PROVIDERS, financials=financials, announcements=announcements,
                   native_intel=lambda _codes: {'status': 'normal', 'stats': {}, 'terms': []})


def test_stage_timeout_cancels_before_next_provider_phase(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    calls = []
    def financials(_code):
        entered.set()
        release.wait(2)
        completed.set()
        return {'revenue': 1, 'net_profit': 1}
    providers = _providers(financials, lambda code: calls.append(code) or [])
    monkeypatch.setattr(discovery, 'QUALIFICATION_TIMEOUT_SECONDS', .03)
    try:
        result, _, summary = discovery._qualify(['600001'], providers, as_of=date(2026, 8, 28))
        assert entered.is_set() and summary['timed_out'] == 1
        assert result['600001']['announcements']['status'] == 'ERROR'
    finally:
        release.set()
        assert completed.wait(2)
        time.sleep(.05)
    assert calls == [], 'a cancelled financial phase must never start announcements'


def test_timeout_preserves_finished_financial_clue(monkeypatch):
    release = threading.Event()
    entered = threading.Event()
    finished = threading.Event()
    def announcements(_code):
        entered.set()
        release.wait(2)
        finished.set()
        return []
    providers = _providers(lambda _code: {'revenue': 7, 'net_profit': 2, 'revenue_yoy': 7}, announcements)
    monkeypatch.setattr(discovery, 'QUALIFICATION_TIMEOUT_SECONDS', .03)
    try:
        result, _, summary = discovery._qualify(['600001'], providers, as_of=date(2026, 8, 28))
        assert entered.is_set() and summary['timed_out'] == 1
        assert result['600001']['fundamental']['status'] == 'PARTIAL'
        assert result['600001']['fundamental']['clue']['revenue_yoy'] == 7
        assert result['600001']['announcements']['status'] == 'ERROR'
    finally:
        release.set()
        assert finished.wait(2)


def test_repeated_timed_out_runs_share_a_bounded_worker_pool(monkeypatch):
    release = threading.Event()
    lock = threading.Lock()
    active = 0
    maximum = 0
    def financials(_code):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        release.wait(2)
        with lock:
            active -= 1
        return {}
    providers = _providers(financials, lambda _code: [])
    monkeypatch.setattr(discovery, 'QUALIFICATION_TIMEOUT_SECONDS', .01)
    try:
        for _ in range(discovery.QUALIFICATION_WORKERS + 3):
            discovery._qualify(['600001'], providers, as_of=date(2026, 8, 28))
        assert maximum <= discovery.QUALIFICATION_WORKERS
    finally:
        release.set()
        limit = time.monotonic() + 2
        while active and time.monotonic() < limit:
            time.sleep(.01)


def test_concurrent_manual_refreshes_do_not_start_duplicate_scan(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = []
    def scan():
        calls.append(True)
        entered.set()
        release.wait(2)
        return {'status': 'unavailable', 'fetched_at': '2026-08-28T00:00:00Z'}
    monkeypatch.setattr(discovery, 'run_discovery', scan)
    discovery.clear_cache()
    first = threading.Thread(target=lambda: discovery.get_discovery(force_refresh=True))
    first.start()
    try:
        assert entered.wait(1)
        second = discovery.get_discovery(force_refresh=True)
        assert calls == [True]
        assert second['status'] == 'unavailable'
        assert second['reason_code'] == 'DISCOVERY_REFRESH_IN_PROGRESS'
    finally:
        release.set()
        first.join(3)
        discovery.clear_cache()


def _stuck_discovery_financial(path, operation, code):
    """Run the real operation selector with a synthetic, never-network provider."""
    import astock
    def stuck(*_args, **_kwargs):
        Path(os.environ['DISCOVERY_SYNTHETIC_ENTERED']).write_text('entered', encoding='utf-8')
        time.sleep(60)
    astock.financials = stuck
    budget._child(path, operation, code)


def test_default_discovery_financial_deadline_kills_and_reaps_real_child(monkeypatch, tmp_path):
    before = {child.pid for child in multiprocessing.active_children()}
    original_run = budget.run
    calls = []
    def bounded(operation, code=None, **kwargs):
        calls.append(operation)
        return original_run(operation, code, _target=_stuck_discovery_financial, **kwargs)
    monkeypatch.setattr(budget, 'run', bounded)
    marker = tmp_path / 'entered'
    monkeypatch.setenv('DISCOVERY_SYNTHETIC_ENTERED', str(marker))
    monkeypatch.setattr(discovery, 'QUALIFICATION_TIMEOUT_SECONDS', 1)
    providers = replace(discovery.DEFAULT_PROVIDERS, native_intel=lambda _codes: {'status': 'normal'})
    started = time.monotonic()
    result, _, _ = discovery._qualify(['600001'], providers, as_of=date(2026, 8, 28))
    assert time.monotonic() - started < 3
    assert marker.read_text(encoding='utf-8') == 'entered'
    assert calls == ['discovery_financials']
    assert result['600001']['fundamental']['status'] == 'ERROR'
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_default_discovery_operations_keep_narrow_provider_contract(monkeypatch, tmp_path):
    import astock
    calls = []
    monkeypatch.setattr(astock, 'financials', lambda code, **kwargs: calls.append((code, kwargs)) or {'revenue': 1})
    monkeypatch.setattr(astock, 'announcements', lambda code, **kwargs: calls.append((code, kwargs)) or {'rows': [], 'source_coverage': {'window_complete': False}})
    financial_path, announcement_path = str(tmp_path / 'financial.json'), str(tmp_path / 'announcement.json')
    budget._child(financial_path, 'discovery_financials', '600001')
    budget._child(announcement_path, 'discovery_announcements', '600001')
    assert budget._read_result(financial_path)['revenue'] == 1
    assert budget._read_result(announcement_path)['source_coverage']['window_complete'] is False
    assert calls == [('600001', {'include_health': False}), ('600001', {'strict': True, 'with_coverage': True})]


def _stuck_discovery_announcements(path, operation, code):
    import astock
    astock.financials = lambda _code, **_kwargs: {'revenue': 7, 'net_profit': 2, 'revenue_yoy': 7}
    def stuck(*_args, **_kwargs):
        Path(os.environ['DISCOVERY_SYNTHETIC_ENTERED']).write_text('entered', encoding='utf-8')
        time.sleep(60)
    astock.announcements = stuck
    budget._child(path, operation, code)


def test_default_announcement_deadline_retains_financial_clue_and_reaps_child(monkeypatch, tmp_path):
    before = {child.pid for child in multiprocessing.active_children()}
    original_run = budget.run
    calls = []
    def bounded(operation, code=None, **kwargs):
        calls.append(operation)
        return original_run(operation, code, _target=_stuck_discovery_announcements, **kwargs)
    monkeypatch.setattr(budget, 'run', bounded)
    marker = tmp_path / 'entered'
    monkeypatch.setenv('DISCOVERY_SYNTHETIC_ENTERED', str(marker))
    monkeypatch.setattr(discovery, 'QUALIFICATION_TIMEOUT_SECONDS', 2)
    providers = replace(discovery.DEFAULT_PROVIDERS, native_intel=lambda _codes: {'status': 'normal'})
    started = time.monotonic()
    result, _, _ = discovery._qualify(['600001'], providers, as_of=date(2026, 8, 28))
    assert time.monotonic() - started < 4
    assert marker.read_text(encoding='utf-8') == 'entered'
    assert calls == ['discovery_financials', 'discovery_announcements']
    assert result['600001']['fundamental']['status'] == 'PARTIAL'
    assert result['600001']['fundamental']['clue']['revenue_yoy'] == 7
    assert result['600001']['announcements']['status'] == 'ERROR'
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_exhausted_global_admission_does_not_enqueue_work(monkeypatch):
    slots = threading.BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(discovery, '_QUALIFICATION_SLOTS', slots)
    def unexpected(_code):
        pytest.fail('admission failure must not start upstream work')
    try:
        result, _, summary = discovery._qualify(['600001'], _providers(unexpected, unexpected),
                                               as_of=date(2026, 8, 28))
        assert summary == {'completed': 0, 'timed_out': 0, 'requested': 1, 'busy': 1}
        assert result['600001']['fundamental']['reason_code'] == 'SOURCE_BUSY'
        assert result['600001']['announcements']['reason_code'] == 'SOURCE_BUSY'
    finally:
        slots.release()


def test_refresh_slot_is_released_after_unexpected_failure(monkeypatch):
    discovery.clear_cache()
    monkeypatch.setattr(discovery, 'run_discovery', lambda: (_ for _ in ()).throw(RuntimeError('synthetic')))
    with pytest.raises(RuntimeError, match='synthetic'):
        discovery.get_discovery(force_refresh=True)
    monkeypatch.setattr(discovery, 'run_discovery', lambda: {'status': 'unavailable'})
    assert discovery.get_discovery(force_refresh=True) == {'status': 'unavailable'}


def test_default_shortlist_does_not_self_exhaust_public_process_admission(monkeypatch):
    slots = threading.BoundedSemaphore(budget.PUBLIC_DATA_WORKERS)
    calls = []
    def bounded(operation, code=None, **_kwargs):
        if not slots.acquire(blocking=False):
            raise budget.PublicDataUnavailable('SOURCE_BUSY')
        try:
            calls.append((operation, code))
            time.sleep(.005)
            return {'revenue': 1, 'revenue_yoy': 1} if operation == 'discovery_financials' else {'rows': []}
        finally:
            slots.release()
    monkeypatch.setattr(budget, 'run', bounded)
    providers = replace(discovery.DEFAULT_PROVIDERS, native_intel=lambda _codes: {'status': 'normal'})
    codes = [f'600{index:03d}' for index in range(discovery.QUALIFICATION_LIMIT)]
    result, _, summary = discovery._qualify(codes, providers, as_of=date(2026, 8, 28))
    assert len(calls) == len(codes) * 2
    assert summary['busy'] == summary['timed_out'] == 0
    assert all(item['fundamental']['status'] == 'PARTIAL' for item in result.values())
    assert all(item['announcements']['status'] == 'UNKNOWN' for item in result.values())
