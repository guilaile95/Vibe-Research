"""No-network resource experiments using real spawned, deliberately stuck children."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
import multiprocessing
import os
from pathlib import Path
import threading
import time

import discovery_service as discovery
import public_data_budget as budget


def _local_stuck_child(path, operation, code):
    marker = Path(os.environ['DISCOVERY_LIFETIME_MARKERS']) / f'{code}-{os.getpid()}'
    marker.write_text(operation, encoding='utf-8')
    time.sleep(60)


def _local_result_child(path, operation, code):
    budget._write_result(path, {'rows': []})


def _all_slots_reusable(semaphore, expected):
    acquired = 0
    try:
        while semaphore.acquire(blocking=False):
            acquired += 1
        assert acquired == expected
    finally:
        for _ in range(acquired):
            semaphore.release()


def test_repeated_real_discovery_deadlines_reap_children_and_reuse_capacity(tmp_path, monkeypatch):
    original_run = budget.run
    monkeypatch.setenv('DISCOVERY_LIFETIME_MARKERS', str(tmp_path))
    monkeypatch.setattr(discovery, 'QUALIFICATION_TIMEOUT_SECONDS', 1.5)
    calls = []
    def local_only(operation, code=None, **kwargs):
        calls.append(operation)
        return original_run(operation, code, _target=_local_stuck_child, **kwargs)
    monkeypatch.setattr(budget, 'run', local_only)
    providers = replace(discovery.DEFAULT_PROVIDERS, native_intel=lambda _codes: {'status': 'normal'})
    before_children = {child.pid for child in multiprocessing.active_children()}
    codes = [f'600{index:03d}' for index in range(discovery.QUALIFICATION_LIMIT)]
    for _ in range(3):
        started = time.monotonic()
        results, _, summary = discovery._qualify(codes, providers, as_of=date(2026, 8, 28))
        assert time.monotonic() - started < 4.5
        assert summary['requested'] == len(codes)
        assert summary['timed_out'] > 0
        assert len(results) == len(codes)
        assert {child.pid for child in multiprocessing.active_children()} == before_children
        _all_slots_reusable(budget._SLOTS, budget.PUBLIC_DATA_WORKERS)
        _all_slots_reusable(discovery._QUALIFICATION_SLOTS,
                            discovery.QUALIFICATION_LIMIT + discovery.QUALIFICATION_WORKERS)
    assert list(tmp_path.iterdir()), 'the actual spawned children must have entered the hang'
    assert all(operation == 'discovery_financials' for operation in calls)
    # Idle executor threads are retained for reuse, not leaked per refresh.
    assert sum(t.name.startswith('discovery-stage3') for t in threading.enumerate()) <= discovery.QUALIFICATION_WORKERS
    assert original_run('discovery_announcements', '600001', timeout=3,
                        _target=_local_result_child) == {'rows': []}


def test_explicit_cancel_reaps_running_public_worker_before_return(tmp_path, monkeypatch):
    monkeypatch.setenv('DISCOVERY_LIFETIME_MARKERS', str(tmp_path))
    cancel = threading.Event()
    errors = []
    before = {child.pid for child in multiprocessing.active_children()}
    def run():
        try:
            budget.run('discovery_financials', '600001', timeout=10,
                       cancel_event=cancel, _target=_local_stuck_child)
        except budget.PublicDataUnavailable as error:
            errors.append(error.code)
    thread = threading.Thread(target=run, name='synthetic-discovery-cancel')
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not list(tmp_path.iterdir()) and time.monotonic() < deadline:
            time.sleep(.01)
        assert list(tmp_path.iterdir()), 'cancel only after the real child started'
        started = time.monotonic()
        cancel.set()
        thread.join(3)
        assert not thread.is_alive()
        assert time.monotonic() - started < 3
        assert errors == ['SOURCE_CANCELLED']
        assert {child.pid for child in multiprocessing.active_children()} == before
        _all_slots_reusable(budget._SLOTS, budget.PUBLIC_DATA_WORKERS)
    finally:
        cancel.set()
        thread.join(3)


def test_cancelled_before_admission_creates_no_child_or_capacity_loss():
    cancel = threading.Event()
    cancel.set()
    before = {child.pid for child in multiprocessing.active_children()}
    try:
        budget.run('discovery_financials', '600001', cancel_event=cancel,
                   _target=_local_stuck_child)
    except budget.PublicDataUnavailable as error:
        assert error.code == 'SOURCE_CANCELLED'
    else:
        raise AssertionError('pre-cancelled operation was admitted')
    assert {child.pid for child in multiprocessing.active_children()} == before
    _all_slots_reusable(budget._SLOTS, budget.PUBLIC_DATA_WORKERS)
