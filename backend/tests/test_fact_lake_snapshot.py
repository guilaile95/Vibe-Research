"""No source SQLite access, frozen control metadata, and portable file identity."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import os
import sqlite3

import pytest
import fact_lake_store as store
from test_short_term_seal_quality_service import archived, isolated, DAY
import short_term_seal_quality_service as service


def tree(root):
    result = {}
    for path in (root, *root.rglob('*')):
        value = path.lstat()
        result[str(path.relative_to(root))] = (
            value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns,
            value.st_ino, hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
        )
    return result


def wal(root):
    with sqlite3.connect(root / store.CONTROL_DB_FILENAME) as conn:
        assert conn.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
    conn.close()


def test_checkpointed_wal_real_seal_entire_tree_unchanged(archived, monkeypatch):
    root, _, _ = archived
    wal(root)
    before = tree(root)
    real_connect = sqlite3.connect
    def memory_only(database, *args, **kwargs):
        assert database == ':memory:'
        return real_connect(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', memory_only)
    lake = store.open_existing_fact_lake_snapshot(root)
    assert lake.readonly and lake.root == root
    assert service.query_seal_quality(DAY)['status'] == 'normal'
    lake.assert_unchanged()
    with pytest.raises(store.FactLakeReadOnlyError):
        lake._connect(readonly=False)
    assert tree(root) == before


@pytest.mark.parametrize('suffix', ['-wal', '-journal'])
def test_pending_sidecars_busy_without_changes(archived, suffix):
    root, _, _ = archived
    Path(str(root / store.CONTROL_DB_FILENAME) + suffix).write_bytes(b'pending')
    before = tree(root)
    with pytest.raises(store.FactLakeBusyError):
        store.open_existing_fact_lake_snapshot(root)
    assert service.query_seal_quality(DAY)['reason_codes'] == ['ARCHIVE_BUSY']
    assert tree(root) == before


@pytest.mark.parametrize('change', ['replace', 'truncate', 'grow', 'symlink'])
def test_source_change_between_reads_rejected(archived, monkeypatch, tmp_path, change):
    root, _, _ = archived
    db = root / store.CONTROL_DB_FILENAME
    original = os.open
    count = 0
    def changed(path, *args, **kwargs):
        nonlocal count
        if Path(path) == db:
            count += 1
            if count == 2:
                data = db.read_bytes()
                if change == 'replace':
                    replacement = root / 'replacement'
                    replacement.write_bytes(data)
                    replacement.replace(db)
                elif change == 'truncate': db.write_bytes(data[:100])
                elif change == 'grow': db.write_bytes(data + b'x')
                else:
                    outside = tmp_path / 'outside'
                    outside.write_bytes(data)
                    db.unlink()
                    try: db.symlink_to(outside)
                    except OSError: pytest.skip('symlink unavailable')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(os, 'open', changed)
    with pytest.raises(store.FactLakeError): store.open_existing_fact_lake_snapshot(root)


def test_final_assert_rejects_control_replacement(archived):
    root, _, _ = archived
    lake = store.open_existing_fact_lake_snapshot(root)
    db = root / store.CONTROL_DB_FILENAME
    replacement = root / 'replacement'
    replacement.write_bytes(db.read_bytes())
    replacement.replace(db)
    with pytest.raises(store.FactLakeBusyError): lake.assert_unchanged()


def test_frozen_connections_and_final_seal_assertion(archived, monkeypatch):
    root, _, _ = archived
    real = service.build_seal_quality_observation
    def mutate(*args, **kwargs):
        result = real(*args, **kwargs)
        db = root / store.CONTROL_DB_FILENAME
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE schema_meta SET value='fact_lake_control_v99'")
        return result
    monkeypatch.setattr(service, 'build_seal_quality_observation', mutate)
    assert service.query_seal_quality(DAY)['reason_codes'] == ['ARCHIVE_BUSY']


def test_schema_and_missing_fail_closed(tmp_path):
    missing = tmp_path / 'absent'
    with pytest.raises(store.FactLakeNotInitializedError): store.open_existing_fact_lake_snapshot(missing)
    assert not missing.exists()
    store.initialize_fact_lake(missing)
    with sqlite3.connect(missing / store.CONTROL_DB_FILENAME) as conn:
        conn.execute('CREATE TABLE unexpected(value)')
    before = tree(missing)
    with pytest.raises(store.FactLakeCorruptedError): store.open_existing_fact_lake_snapshot(missing)
    assert tree(missing) == before


def metadata(value, **overrides):
    fields = {name: getattr(value, name) for name in ('st_mode', 'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
    fields['st_birthtime_ns'] = getattr(value, 'st_birthtime_ns', value.st_ctime_ns)
    fields.update(overrides)
    return SimpleNamespace(**fields)


@pytest.mark.parametrize('drift', [None, 'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_birthtime_ns', 'st_ctime_ns'])
def test_windows_split_stat_semantics_and_descriptor_drift(archived, monkeypatch, drift):
    root, _, _ = archived
    db = root / store.CONTROL_DB_FILENAME
    path_stat, fd_stat = Path.stat, os.fstat
    birth = db.stat().st_ctime_ns
    count = 0
    def path_value(self, *args, **kwargs):
        value = path_stat(self, *args, **kwargs)
        return metadata(value, st_ctime_ns=birth, st_birthtime_ns=birth) if self == db else value
    def fd_value(fd):
        nonlocal count
        count += 1
        value = metadata(fd_stat(fd), st_ctime_ns=birth + 123456700, st_birthtime_ns=birth)
        return metadata(value, **{drift: getattr(value, drift) + 1}) if drift and count == 2 else value
    monkeypatch.setattr(store, '_SNAPSHOT_WINDOWS_CTIME', True)
    monkeypatch.setattr(Path, 'stat', path_value)
    monkeypatch.setattr(os, 'fstat', fd_value)
    if drift:
        with pytest.raises(store.FactLakeBusyError): store.open_existing_fact_lake_snapshot(root)
    else:
        lake = store.open_existing_fact_lake_snapshot(root)
        lake.assert_unchanged()
        assert service.query_seal_quality(DAY)['status'] == 'normal'


def test_real_active_wal_is_busy(archived):
    root, _, _ = archived
    db = root / store.CONTROL_DB_FILENAME
    conn = sqlite3.connect(db)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute("UPDATE schema_meta SET value='fact_lake_control_v99'")
        conn.commit()
        assert Path(str(db) + '-wal').stat().st_size > 0
        before = tree(root)
        with pytest.raises(store.FactLakeBusyError): store.open_existing_fact_lake_snapshot(root)
        assert tree(root) == before
    finally:
        conn.close()


@pytest.mark.parametrize('suffix', ['-wal', '-journal', '-shm'])
def test_sidecar_symlinks_rejected_without_modification(archived, tmp_path, suffix):
    root, _, _ = archived
    target = tmp_path / 'outside-sidecar'
    target.write_bytes(b'')
    link = Path(str(root / store.CONTROL_DB_FILENAME) + suffix)
    try: link.symlink_to(target)
    except OSError: pytest.skip('symlink unavailable')
    with pytest.raises(store.FactLakePathError): store.open_existing_fact_lake_snapshot(root)
    assert link.is_symlink() and target.read_bytes() == b''


def test_unknown_schema_no_source_sqlite_fallback(archived, monkeypatch):
    root, _, _ = archived
    with sqlite3.connect(root / store.CONTROL_DB_FILENAME) as conn:
        conn.execute("UPDATE schema_meta SET value='fact_lake_control_v99'")
    before = tree(root)
    def forbidden(*args, **kwargs): raise AssertionError('source SQLite forbidden')
    monkeypatch.setattr(store, '_connect_existing', forbidden)
    monkeypatch.setattr(store, '_connect_immutable', forbidden)
    with pytest.raises(store.FactLakeSchemaVersionError): store.open_existing_fact_lake_snapshot(root)
    assert tree(root) == before
