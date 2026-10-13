"""Owned SQLite connections close on success, early returns and rollback."""
import sqlite3

import pytest

import account_event_store as store


def event(event_id="synthetic_cash"):
    return {
        "event_id": event_id, "event_type": "CASH_DEPOSIT", "amount": 1,
        "provenance": "MANUAL", "created_at": "2026-09-30T00:00:00Z",
    }


@pytest.fixture
def connections(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.sqlite3"
    tracked = []
    for name in ("_connect", "_connect_readonly"):
        original = getattr(store, name)

        def track(db_path, connect=original):
            conn = connect(db_path)
            tracked.append(conn)
            return conn

        monkeypatch.setattr(store, name, track)
    yield path, tracked
    for conn in tracked:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")


@pytest.mark.parametrize("operation", ["get", "list", "count", "migrate", "insert", "bootstrap"])
def test_owned_connections_close_on_success(connections, operation):
    path, _ = connections
    store.insert_event(path, event())
    if operation == "get":
        assert store.get_event(path, "synthetic_cash")["amount"] == 1
    elif operation == "list":
        assert len(store.list_events(path)) == 1
    elif operation == "count":
        assert store.count_non_voided(path) == 1
    elif operation == "migrate":
        store.ensure_migrated(path)
    elif operation == "insert":
        store.insert_event(path, event("second"))
    else:
        store.atomic_bootstrap(path, event("opening"), [event("position")])


@pytest.mark.parametrize("read", [store.get_event, store.list_events, store.count_non_voided])
def test_missing_table_early_return_closes_connection(connections, read):
    path, _ = connections
    sqlite3.connect(path).close()
    read(path, "missing") if read is store.get_event else read(path)


def test_insert_error_rolls_back_and_closes(connections):
    path, _ = connections
    store.insert_event(path, event())
    with pytest.raises(store.AccountEventCorruptedError):
        store.insert_event(path, event())  # Duplicate primary key.
    assert store.count_non_voided(path) == 1


def test_bootstrap_error_rolls_back_whole_transaction_and_closes(connections):
    path, _ = connections
    with pytest.raises(store.AccountEventCorruptedError):
        store.atomic_bootstrap(path, event(), [event()])
    assert store.list_events(path) == []


def test_corrupt_read_closes_connection(connections, monkeypatch):
    path, _ = connections
    store.insert_event(path, event())
    monkeypatch.setattr(store, "_SELECT_LIST_BASE", "SELECT * FROM nonexistent")
    with pytest.raises(store.AccountEventCorruptedError):
        store.list_events(path)


@pytest.mark.parametrize("connect", [store._connect, store._connect_readonly])
def test_connection_setup_failure_closes_before_propagating(tmp_path, monkeypatch, connect):
    path = tmp_path / "synthetic.sqlite3"
    original = sqlite3.connect
    original(path).close()
    tracked = []

    class SetupFailure(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith("PRAGMA"):
                raise sqlite3.DatabaseError("injected setup failure")
            return super().execute(sql, *args, **kwargs)

    def failing_connect(*args, **kwargs):
        conn = original(*args, factory=SetupFailure, **kwargs)
        tracked.append(conn)
        return conn

    monkeypatch.setattr(store.sqlite3, "connect", failing_connect)
    with pytest.raises(sqlite3.DatabaseError, match="injected"):
        connect(path)
    assert len(tracked) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        tracked[0].execute("SELECT 1")
