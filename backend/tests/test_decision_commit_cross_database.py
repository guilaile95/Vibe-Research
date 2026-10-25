"""Controlled Campaign/Frozen Decision interleaving on separate real SQLite files."""
from __future__ import annotations

from dataclasses import replace
import threading

import pytest

from decision_clock_fixtures import historical_decision_server_clock as _historical_decision_server_clock  # noqa: F401
import campaign_service
import campaign_store
import decision_commit_runtime as runtime
import frozen_decision_service
import frozen_decision_store
from test_decision_commit_runtime import AS_OF, CAMPAIGN_ID, _draft, _ports, _thesis


def _real_campaign_ports(tmp_path, monkeypatch):
    monkeypatch.setenv('VIBE_RESEARCH_CAMPAIGN_DB', str(tmp_path / 'campaigns.sqlite3'))
    frozen_path = tmp_path / 'frozen.sqlite3'
    monkeypatch.setattr(frozen_decision_service, '_resolve_db_path', lambda _path: frozen_path)
    campaign_store.create_campaign(campaign_id=CAMPAIGN_ID, security_code='600519',
                                  strategy='SWING', status='ACTIVE', created_at=AS_OF)
    ports, _ = _ports(_thesis())
    return replace(ports, campaign_reader=campaign_service.get_campaign,
                   frozen_reader=frozen_decision_service.list_decisions,
                   decision_reader=frozen_decision_service.get_decision,
                   freeze_writer_with_pre_write_validation=runtime._production_freeze_writer_with_pre_write_validation)


def test_campaign_cannot_close_between_final_validation_and_frozen_insert(tmp_path, monkeypatch):
    ports = _real_campaign_ports(tmp_path, monkeypatch)
    preview = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    at_insert = threading.Event()
    transition_started = threading.Event()
    transition_finished = threading.Event()
    errors = []
    statuses_at_insert = []
    original_write = frozen_decision_store.write_frozen_decision
    original_open = campaign_store._open_write_connection

    def observed_open():
        if threading.current_thread().name == 'controlled-campaign-close':
            transition_started.set()
        return original_open()

    def close_campaign():
        try:
            assert at_insert.wait(2)
            campaign_service.transition_campaign(CAMPAIGN_ID, 'ACTIVE', 'CLOSED')
        except BaseException as error:
            errors.append(error)
        finally:
            transition_finished.set()

    def pause_before_insert(path, frozen):
        at_insert.set()
        assert transition_started.wait(2)
        # Without a Campaign write guard, the separate real transaction completes
        # in this gap. With the guard it waits until the Frozen insert commits.
        transition_finished.wait(.25)
        statuses_at_insert.append(campaign_service.get_campaign(CAMPAIGN_ID)['status'])
        return original_write(path, frozen)

    monkeypatch.setattr(campaign_store, '_open_write_connection', observed_open)
    monkeypatch.setattr(frozen_decision_store, 'write_frozen_decision', pause_before_insert)
    thread = threading.Thread(target=close_campaign, name='controlled-campaign-close')
    thread.start()
    try:
        result = runtime.commit_decision_proposal(CAMPAIGN_ID, {
            **_draft(), 'as_of': AS_OF, 'user_confirmed': True,
            'expected_proposal_fingerprint': preview['proposal_fingerprint'],
        }, ports=ports)
    finally:
        at_insert.set()
        thread.join(5)
    assert not thread.is_alive()
    assert errors == []
    assert statuses_at_insert == ['ACTIVE']
    assert campaign_service.get_campaign(CAMPAIGN_ID)['status'] == 'CLOSED'
    assert frozen_decision_service.get_decision(result['committed']['decision_id']) == result['committed']


def _commit(ports, preview):
    return runtime.commit_decision_proposal(CAMPAIGN_ID, {
        **_draft(), 'as_of': AS_OF, 'user_confirmed': True,
        'expected_proposal_fingerprint': preview['proposal_fingerprint'],
    }, ports=ports)


def test_terminal_transition_wins_before_reservation_and_no_decision_is_written(tmp_path, monkeypatch):
    ports = _real_campaign_ports(tmp_path, monkeypatch)
    preview = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    original_writer = ports.freeze_writer_with_pre_write_validation

    def transition_before_guard(payload, **kwargs):
        campaign_service.transition_campaign(CAMPAIGN_ID, 'ACTIVE', 'CLOSED')
        return original_writer(payload, **kwargs)

    ports = replace(ports, freeze_writer_with_pre_write_validation=transition_before_guard)
    with pytest.raises(runtime.TerminalCampaignDecisionConflictError):
        _commit(ports, preview)
    assert frozen_decision_service.list_decisions() == []
    assert campaign_service.get_campaign(CAMPAIGN_ID)['status'] == 'CLOSED'
    assert len(campaign_service.list_campaign_transitions(CAMPAIGN_ID)) == 1


def test_failed_frozen_write_releases_campaign_reservation_without_mutation(tmp_path, monkeypatch):
    ports = _real_campaign_ports(tmp_path, monkeypatch)
    preview = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    before = campaign_service.get_campaign(CAMPAIGN_ID)
    monkeypatch.setattr(frozen_decision_store, 'write_frozen_decision',
                        lambda *_args: (_ for _ in ()).throw(RuntimeError('synthetic write failure')))
    with pytest.raises(RuntimeError, match='synthetic write failure'):
        _commit(ports, preview)
    assert campaign_service.get_campaign(CAMPAIGN_ID) == before
    assert campaign_service.list_campaign_transitions(CAMPAIGN_ID) == []
    assert frozen_decision_service.list_decisions() == []
    campaign_service.transition_campaign(CAMPAIGN_ID, 'ACTIVE', 'CLOSED')
    assert campaign_service.get_campaign(CAMPAIGN_ID)['status'] == 'CLOSED'


def test_existing_frozen_replay_after_close_does_not_require_new_write_reservation(tmp_path, monkeypatch):
    ports = _real_campaign_ports(tmp_path, monkeypatch)
    preview = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    first = _commit(ports, preview)
    campaign_service.transition_campaign(CAMPAIGN_ID, 'ACTIVE', 'CLOSED')
    monkeypatch.setattr(campaign_store, 'hold_campaign_state',
                        lambda *_args: pytest.fail('idempotent replay must not enter write admission'))
    second = _commit(ports, preview)
    assert second['idempotent'] is True
    assert second['committed'] == first['committed']
    assert len(frozen_decision_service.list_decisions()) == 1


def test_busy_campaign_database_fails_without_frozen_write(tmp_path, monkeypatch):
    import sqlite3
    import time
    ports = _real_campaign_ports(tmp_path, monkeypatch)
    preview = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    blocker = sqlite3.connect(str(tmp_path / 'campaigns.sqlite3'), isolation_level=None)
    blocker.execute('BEGIN IMMEDIATE')
    connect = sqlite3.connect

    def short_timeout(*args, **kwargs):
        # Exercise SQLite's actual busy-timeout failure without adding 10s to CI.
        kwargs['timeout'] = .03
        return connect(*args, **kwargs)

    monkeypatch.setattr(campaign_store.sqlite3, 'connect', short_timeout)
    started = time.monotonic()
    try:
        with pytest.raises(runtime.DecisionCommitRuntimeError, match='could not be reserved'):
            _commit(ports, preview)
    finally:
        blocker.rollback()
        blocker.close()
    assert time.monotonic() - started < 1
    assert frozen_decision_service.list_decisions() == []
    assert campaign_service.get_campaign(CAMPAIGN_ID)['status'] == 'ACTIVE'


def _try_external_campaign_transition(campaign_path, campaign_id, result_path):
    """A separate interpreter cannot bypass the SQLite reservation."""
    import json
    import os
    from pathlib import Path
    os.environ['VIBE_RESEARCH_CAMPAIGN_DB'] = campaign_path
    import campaign_store as store
    connect = store.sqlite3.connect
    def short_timeout(*args, **kwargs):
        kwargs['timeout'] = .05
        return connect(*args, **kwargs)
    store.sqlite3.connect = short_timeout
    import campaign_service as service
    try:
        service.transition_campaign(campaign_id, 'ACTIVE', 'CLOSED')
        result = {'transition': 'completed'}
    except service.CampaignServiceError:
        result = {'transition': 'blocked'}
    Path(result_path).write_text(json.dumps(result), encoding='utf-8')


def test_campaign_reservation_blocks_other_process_and_is_reusable(tmp_path, monkeypatch):
    import json
    import multiprocessing
    _real_campaign_ports(tmp_path, monkeypatch)
    result_path = tmp_path / 'child-result.json'
    child = multiprocessing.get_context('spawn').Process(
        target=_try_external_campaign_transition,
        args=(str(tmp_path / 'campaigns.sqlite3'), CAMPAIGN_ID, str(result_path)),
    )
    with campaign_store.hold_campaign_state(CAMPAIGN_ID) as held:
        assert held['status'] == 'ACTIVE'
        child.start()
        child.join(5)
        try:
            assert not child.is_alive()
            assert child.exitcode == 0
            assert json.loads(result_path.read_text(encoding='utf-8')) == {'transition': 'blocked'}
        finally:
            if child.is_alive():
                child.kill()
                child.join(2)
            child.close()
    campaign_service.transition_campaign(CAMPAIGN_ID, 'ACTIVE', 'CLOSED')
    assert campaign_service.get_campaign(CAMPAIGN_ID)['status'] == 'CLOSED'


def test_different_campaign_writer_is_serialized_not_dropped(tmp_path, monkeypatch):
    _real_campaign_ports(tmp_path, monkeypatch)
    other_id = 'campaign_' + 'd' * 32
    campaign_store.create_campaign(campaign_id=other_id, security_code='000001',
                                  strategy='SWING', status='ACTIVE', created_at=AS_OF)
    started = threading.Event()
    finished = threading.Event()
    errors = []
    original_open = campaign_store._open_write_connection
    def observed_open():
        if threading.current_thread().name == 'other-campaign':
            started.set()
        return original_open()
    monkeypatch.setattr(campaign_store, '_open_write_connection', observed_open)
    def close_other():
        try:
            campaign_service.transition_campaign(other_id, 'ACTIVE', 'CLOSED')
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()
    thread = threading.Thread(target=close_other, name='other-campaign')
    try:
        with campaign_store.hold_campaign_state(CAMPAIGN_ID):
            thread.start()
            assert started.wait(2)
            assert not finished.wait(.1)
            assert campaign_service.get_campaign(other_id)['status'] == 'ACTIVE'
    finally:
        thread.join(5)
    assert not thread.is_alive() and not errors
    assert campaign_service.get_campaign(CAMPAIGN_ID)['status'] == 'ACTIVE'
    assert campaign_service.get_campaign(other_id)['status'] == 'CLOSED'


def test_actual_frozen_insert_abort_rolls_back_and_releases_campaign_guard(tmp_path, monkeypatch):
    import sqlite3
    ports = _real_campaign_ports(tmp_path, monkeypatch)
    preview = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    before = campaign_service.get_campaign(CAMPAIGN_ID)
    original_open = frozen_decision_store._open_for_write

    def fail_insert_connection(path):
        connection = original_open(path)
        # Session-local fault after production schema validation, not a mutation
        # of the authoritative schema or a bypass of its trigger prohibition.
        connection.execute("CREATE TEMP TRIGGER reject_test_insert BEFORE INSERT ON frozen_decisions BEGIN SELECT RAISE(ABORT, 'synthetic'); END")
        return connection

    monkeypatch.setattr(frozen_decision_store, '_open_for_write', fail_insert_connection)
    with pytest.raises(frozen_decision_store.FrozenDecisionCorruptedError):
        _commit(ports, preview)
    assert frozen_decision_service.list_decisions() == []
    assert campaign_service.get_campaign(CAMPAIGN_ID) == before
    assert campaign_service.list_campaign_transitions(CAMPAIGN_ID) == []
    monkeypatch.setattr(frozen_decision_store, '_open_for_write', original_open)
    result = _commit(ports, preview)
    assert result['idempotent'] is False
    campaign_service.transition_campaign(CAMPAIGN_ID, 'ACTIVE', 'CLOSED')


def test_campaign_and_frozen_database_alias_fails_closed_before_reservation(tmp_path, monkeypatch):
    ports = _real_campaign_ports(tmp_path, monkeypatch)
    before = campaign_service.get_campaign(CAMPAIGN_ID)
    monkeypatch.setattr(frozen_decision_service, '_resolve_db_path',
                        lambda _path: tmp_path / 'campaigns.sqlite3')
    with pytest.raises(frozen_decision_store.FrozenDecisionSchemaVersionError):
        runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    assert campaign_service.get_campaign(CAMPAIGN_ID) == before
    assert campaign_service.list_campaign_transitions(CAMPAIGN_ID) == []


def _concurrent_decision_child(campaign_path, frozen_path, preview, ready, gate, result_path):
    import json
    import os
    from pathlib import Path
    os.environ['VIBE_RESEARCH_CAMPAIGN_DB'] = campaign_path
    frozen_decision_service._resolve_db_path = lambda _path: Path(frozen_path)
    frozen_decision_service._utc_now_iso = lambda: AS_OF
    runtime.utc_now_iso = lambda: AS_OF
    ports, _ = _ports(_thesis())
    def gated_write(payload, **kwargs):
        Path(ready).write_text('ready', encoding='utf-8')
        deadline = __import__('time').monotonic() + 5
        while not Path(gate).exists():
            if __import__('time').monotonic() >= deadline:
                raise RuntimeError('test gate timeout')
            __import__('time').sleep(.005)
        return runtime._production_freeze_writer_with_pre_write_validation(payload, **kwargs)
    ports = replace(ports, campaign_reader=campaign_service.get_campaign,
                    frozen_reader=frozen_decision_service.list_decisions,
                    decision_reader=frozen_decision_service.get_decision,
                    freeze_writer_with_pre_write_validation=gated_write)
    try:
        value = _commit(ports, preview)
        result = {'status': 'ok', 'id': value['committed']['decision_id']}
    except runtime.ProposalStaleError:
        result = {'status': 'retry'}
    except BaseException as error:
        result = {'status': 'error', 'type': type(error).__name__}
    Path(result_path).write_text(json.dumps(result), encoding='utf-8')


def test_two_processes_same_proposal_append_once_and_loser_can_exact_replay(tmp_path, monkeypatch):
    import json
    import multiprocessing
    import time
    ports = _real_campaign_ports(tmp_path, monkeypatch)
    preview = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    gate = tmp_path / 'go'
    children = []
    for index in range(2):
        children.append(multiprocessing.get_context('spawn').Process(
            target=_concurrent_decision_child,
            args=(str(tmp_path / 'campaigns.sqlite3'), str(tmp_path / 'frozen.sqlite3'),
                  preview, str(tmp_path / f'ready-{index}'), str(gate), str(tmp_path / f'result-{index}')),
        ))
    try:
        for child in children:
            child.start()
        deadline = time.monotonic() + 5
        while not all((tmp_path / f'ready-{i}').exists() for i in range(2)):
            assert time.monotonic() < deadline
            time.sleep(.01)
        gate.write_text('go', encoding='utf-8')
        for child in children:
            child.join(5)
            assert not child.is_alive() and child.exitcode == 0
        results = [json.loads((tmp_path / f'result-{i}').read_text(encoding='utf-8')) for i in range(2)]
        assert sorted(result['status'] for result in results) == ['ok', 'retry']
        decisions = frozen_decision_service.list_decisions()
        assert len(decisions) == 1
        replay = _commit(ports, preview)
        assert replay['idempotent'] is True
        assert replay['committed'] == decisions[0]
    finally:
        gate.write_text('go', encoding='utf-8')
        for child in children:
            if child.is_alive():
                child.kill()
                child.join(2)
            child.close()


def test_postcommit_readback_failure_preserves_one_row_and_exact_replay(tmp_path, monkeypatch):
    ports = _real_campaign_ports(tmp_path, monkeypatch)
    preview = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    original = frozen_decision_store._row_to_snapshot
    monkeypatch.setattr(frozen_decision_store, '_row_to_snapshot',
                        lambda *_args: (_ for _ in ()).throw(RuntimeError('after-commit fixture fault')))
    with pytest.raises(RuntimeError, match='after-commit fixture fault'):
        _commit(ports, preview)
    monkeypatch.setattr(frozen_decision_store, '_row_to_snapshot', original)
    records = frozen_decision_service.list_decisions()
    assert len(records) == 1
    campaign_service.transition_campaign(CAMPAIGN_ID, 'ACTIVE', 'CLOSED')
    replay = _commit(ports, preview)
    assert replay['idempotent'] is True
    assert replay['committed'] == records[0]
    assert len(frozen_decision_service.list_decisions()) == 1


def test_busy_after_schema_check_is_mapped_and_releases_connection(tmp_path, monkeypatch):
    import sqlite3
    ports = _real_campaign_ports(tmp_path, monkeypatch)
    preview = runtime.preview_decision_proposal(CAMPAIGN_ID, _draft(), ports=ports, as_of=AS_OF)
    connect = sqlite3.connect
    blocker = connect(str(tmp_path / 'campaigns.sqlite3'), isolation_level=None)
    original_open = campaign_store._open_write_connection
    def block_after_schema_check():
        connection = original_open()
        connection.execute('PRAGMA busy_timeout = 30')
        blocker.execute('BEGIN IMMEDIATE')
        return connection
    monkeypatch.setattr(campaign_store, '_open_write_connection', block_after_schema_check)
    try:
        with pytest.raises(runtime.DecisionCommitRuntimeError, match='could not be reserved'):
            _commit(ports, preview)
    finally:
        blocker.rollback()
        blocker.close()
    assert frozen_decision_service.list_decisions() == []
    monkeypatch.setattr(campaign_store, '_open_write_connection', original_open)
    assert _commit(ports, preview)['idempotent'] is False
