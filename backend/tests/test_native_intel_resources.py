"""Native Intel must release SQLite handles without waiting for garbage collection."""
import sqlite3

import pytest

import native_intel_store as store


@pytest.fixture
def tracked_connections(monkeypatch):
    original = sqlite3.connect
    connections = []

    def track(*args, **kwargs):
        conn = original(*args, **kwargs)
        connections.append(conn)  # Strong references make the regression deterministic.
        return conn

    monkeypatch.setattr(store.sqlite3, "connect", track)
    yield connections
    for conn in connections:
        conn.close()


def assert_closed(connections):
    assert connections
    for conn in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")


def test_store_operations_close_connections(tmp_path, tracked_connections):
    path = tmp_path / "native_intel.sqlite3"
    store.initialize_store(path)
    store.list_sources(path)
    store.count_items(path)
    assert_closed(tracked_connections)


@pytest.mark.parametrize("fail", [False, True])
def test_transaction_commit_or_rollback_and_close(tmp_path, tracked_connections, fail):
    path = tmp_path / "transaction.sqlite3"
    with store._connect(path) as conn:
        conn.execute("CREATE TABLE probe (value INTEGER)")
    try:
        with store._connect(path) as conn:
            conn.execute("INSERT INTO probe VALUES (1)")
            if fail:
                raise ValueError("injected failure")
    except ValueError:
        assert fail
    with store._connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM probe").fetchone()[0] == (0 if fail else 1)
    assert_closed(tracked_connections)


def test_setup_failure_closes_connection(tmp_path, monkeypatch, tracked_connections):
    original = store.sqlite3.connect

    class SetupFailure(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith("PRAGMA"):
                raise sqlite3.DatabaseError("injected setup failure")
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(store.sqlite3, "connect", lambda *a, **kw: original(*a, factory=SetupFailure, **kw))
    with pytest.raises(sqlite3.DatabaseError, match="injected"):
        with store._connect(tmp_path / "failure.sqlite3"):
            pytest.fail("must not yield a partially configured connection")
    assert_closed(tracked_connections)


def test_completed_operation_releases_wal_sidecars(tmp_path, tracked_connections):
    path = tmp_path / "native_intel.sqlite3"
    store.initialize_store(path)
    # No open connection remains to be collected during a subsequent backup.
    assert not path.with_name(path.name + "-wal").exists()
    assert not path.with_name(path.name + "-shm").exists()
    assert_closed(tracked_connections)
