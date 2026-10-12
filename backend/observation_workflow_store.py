"""Observation/task materializations in the existing facts database, not authorities.

GET copies a stable checkpoint into memory; it never opens a source SQLite
connection or creates WAL/SHM. Busy archives fail closed rather than read stale.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
import sqlite3
import threading

import short_term_fact_store as facts
from fact_lake_store import _ControlSnapshot, _is_link_or_reparse, FactLakeError

_initialization_lock = threading.Lock()
_preview_connection = ContextVar("observation_preview_connection", default=None)

TABLES = {
    'observation_slots': 'day TEXT, slot TEXT, payload TEXT NOT NULL, PRIMARY KEY(day,slot)',
    'observation_attempts': 'day TEXT, slot TEXT, attempt INTEGER, payload TEXT NOT NULL, PRIMARY KEY(day,slot,attempt)',
    'observation_watch': 'day TEXT, symbol TEXT, payload TEXT NOT NULL, PRIMARY KEY(day,symbol)',
    'observation_events': 'id TEXT PRIMARY KEY, day TEXT, payload TEXT NOT NULL',
    'observation_tasks': 'day TEXT, kind TEXT, payload TEXT NOT NULL, PRIMARY KEY(day,kind)',
    'observation_cursors': 'symbol TEXT PRIMARY KEY, since TEXT NOT NULL',
    'observation_notices': 'id TEXT PRIMARY KEY, day TEXT, payload TEXT NOT NULL',
}

class StoreError(RuntimeError):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))


@contextmanager
def write():
    preview = _preview_connection.get()
    if preview is not None:
        with preview:
            yield preview
        return
    path = facts.resolve_db_path()
    with _initialization_lock:
        if not path.exists():
            facts.init_db(path)
    conn = sqlite3.connect(path, timeout=10)
    try:
        conn.execute('BEGIN IMMEDIATE')
        for name, columns in TABLES.items():
            conn.execute(f'CREATE TABLE IF NOT EXISTS {name} ({columns})')
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def read():
    preview = _preview_connection.get()
    if preview is not None:
        yield preview
        return
    path = facts.resolve_db_path()
    conn = None
    try:
        if any(_is_link_or_reparse(part) for part in (path, *path.parents)):
            raise StoreError('观察归档路径不可用')
        snapshot = _ControlSnapshot(path) if path.exists() else None
        conn = snapshot.connect() if snapshot else sqlite3.connect(':memory:')
        conn.row_factory = None
        conn.execute('PRAGMA query_only=ON')
        if conn.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise StoreError('观察归档损坏')
        yield conn
        if snapshot:
            snapshot.assert_unchanged()
        elif path.exists() or _is_link_or_reparse(path):
            raise StoreError('观察归档读取期间发生变化')
    except (OSError, sqlite3.Error, ValueError, FactLakeError) as exc:
        raise StoreError('观察归档不可读取或正在变化') from exc
    finally:
        if conn:
            conn.close()


def rows(conn, table, where='', params=()):
    if table not in TABLES:
        raise ValueError('unknown observation table')
    kind = conn.execute('SELECT type FROM sqlite_schema WHERE name=?', (table,)).fetchone()
    if kind is None:
        return []
    if kind != ('table',):
        raise StoreError('观察归档结构无效')
    try:
        from observation_workflow_contract import validate_record
        keys = {'observation_slots': 'day,slot', 'observation_attempts': 'day,slot,attempt',
                'observation_watch': 'day,symbol', 'observation_events': 'id,day',
                'observation_tasks': 'day,kind', 'observation_notices': 'id,day'}
        def unique(pairs):
            out = {}
            for key, value in pairs:
                if key in out:
                    raise ValueError('duplicate JSON field')
                out[key] = value
            return out
        result = []
        for row in conn.execute(f'SELECT {keys[table]},payload FROM {table} {where}', params):
            if not isinstance(row[-1], str) or len(row[-1]) > 2_000_000:
                raise ValueError('oversized observation record')
            payload = json.loads(row[-1], object_pairs_hook=unique, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
            validate_record(table, row[:-1], payload)
            result.append(payload)
        return result
    except (sqlite3.Error, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise StoreError('观察归档记录无效') from exc


@contextmanager
def synthetic_database():
    """Per-request memory-only simulation; never substitutes the real root."""
    conn = sqlite3.connect(':memory:')
    for name, columns in TABLES.items():
        conn.execute(f'CREATE TABLE {name} ({columns})')
    token = _preview_connection.set(conn)
    try:
        yield
    finally:
        _preview_connection.reset(token)
        conn.close()
