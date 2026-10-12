"""Windows path ctime=creation vs descriptor ctime=change, without weakening IDs."""
from types import SimpleNamespace
from pathlib import Path
import os
import json
import sys
import stat

import pytest
import short_term_fact_store as store
from test_cohort_identity import P, T, archived, isolated, tree


def metadata(value, **overrides):
    fields = {name: getattr(value, name) for name in
              ("st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")}
    fields["st_birthtime_ns"] = getattr(value, "st_birthtime_ns", value.st_ctime_ns)
    fields.update(overrides)
    return SimpleNamespace(**fields)


def emulate_windows(monkeypatch, path):
    """Expose the documented native API semantic difference, not alternate data."""
    original_stat, original_fstat = Path.stat, os.fstat
    birth = original_stat(path).st_ctime_ns
    def path_stat(self, *args, **kwargs):
        value = original_stat(self, *args, **kwargs)
        return metadata(value, st_ctime_ns=birth, st_birthtime_ns=birth) if self == path else value
    def descriptor_stat(fd):
        value = original_fstat(fd)
        return metadata(value, st_ctime_ns=birth + 123456700, st_birthtime_ns=birth)
    monkeypatch.setattr(store, "_WINDOWS_STAT_CTIME", True)
    monkeypatch.setattr(Path, "stat", path_stat)
    monkeypatch.setattr(os, "fstat", descriptor_stat)
    return path_stat, descriptor_stat


def test_stable_windows_metadata_old_tuple_rejects_new_reader_preserves_bytes(archived, monkeypatch):
    before = tree(archived.parent)
    emulate_windows(monkeypatch, archived)
    with archived.open("rb") as stream:
        path_identity = store._archive_stat_fingerprint(archived.stat())
        fd_identity = store._archive_stat_fingerprint(os.fstat(stream.fileno()))
    assert fd_identity[:5] != path_identity[:5]  # Exact old identity check fails.
    assert path_identity[:4] == fd_identity[:4]
    assert path_identity[5] == fd_identity[5]
    assert store._archive_descriptor_matches_path(path_identity, fd_identity)
    records = store.load_final_fact_records_readonly((P, T))
    assert set(records) == {P, T}
    assert store.load_final_fact_record(T)["envelope"]["trade_date"] == T
    assert tree(archived.parent) == before


@pytest.mark.parametrize("field", ["st_dev", "st_ino", "st_size", "st_mtime_ns", "st_birthtime_ns"])
def test_windows_cross_api_still_rejects_changed_identity(archived, monkeypatch, field):
    _, fstat = emulate_windows(monkeypatch, archived)
    monkeypatch.setattr(os, "fstat", lambda fd: metadata(fstat(fd), **{field: getattr(fstat(fd), field) + 1}))
    with pytest.raises(store.FactStoreBusyError): store.load_final_fact_records_readonly((P, T))


@pytest.mark.parametrize("call", [2, 3, 4])
@pytest.mark.parametrize("field", ["st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_birthtime_ns"])
def test_windows_descriptor_full_stability_before_after_and_second_open(archived, monkeypatch, call, field):
    _, fstat = emulate_windows(monkeypatch, archived)
    count = 0
    def changed(fd):
        nonlocal count
        count += 1
        value = fstat(fd)
        return metadata(value, **{field: getattr(value, field) + 1}) if count == call else value
    monkeypatch.setattr(os, "fstat", changed)
    with pytest.raises(store.FactStoreBusyError): store.load_final_fact_records_readonly((P, T))


@pytest.mark.parametrize("field", ["st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_birthtime_ns"])
def test_windows_path_full_fingerprint_drift_is_not_ignored(archived, monkeypatch, field):
    path_stat, descriptor_stat = emulate_windows(monkeypatch, archived)
    opened = False
    def marked_fstat(fd):
        nonlocal opened
        opened = True
        return descriptor_stat(fd)
    def changed(self, *args, **kwargs):
        value = path_stat(self, *args, **kwargs)
        if self == archived and opened:
            return metadata(value, **{field: getattr(value, field) + 1})
        return value
    monkeypatch.setattr(os, "fstat", marked_fstat)
    monkeypatch.setattr(Path, "stat", changed)
    with pytest.raises(store.FactStoreBusyError): store.load_final_fact_records_readonly((P, T))



def test_nonwindows_keeps_cross_api_ctime_exact(monkeypatch):
    monkeypatch.setattr(store, "_WINDOWS_STAT_CTIME", False)
    path = (1, 2, 3, 4, 5, 6)
    assert not store._archive_descriptor_matches_path(path, (1, 2, 3, 4, 7, 6))
    assert store._archive_descriptor_matches_path(path, path)


def test_older_windows_without_birthtime_does_not_silently_weaken_identity(monkeypatch):
    monkeypatch.setattr(store, "_WINDOWS_STAT_CTIME", True)
    assert not store._archive_descriptor_matches_path((1, 2, 3, 4, 5, None), (1, 2, 3, 4, 7, None))


@pytest.mark.parametrize("change", ["truncate", "grow", "replacement", "symlink"])
def test_real_file_change_between_bounded_reads_rejected(archived, monkeypatch, tmp_path, change):
    original_open = os.open
    original_bytes = archived.read_bytes()
    replacement = tmp_path / "replacement.sqlite3"
    replacement.write_bytes(original_bytes)
    calls = 0
    def altered(path, flags, *args, **kwargs):
        nonlocal calls
        if Path(path) == archived:
            calls += 1
            if calls == 2:
                if change == "truncate": archived.write_bytes(original_bytes[:-1])
                elif change == "grow": archived.write_bytes(original_bytes + b"x")
                elif change == "replacement": os.replace(replacement, archived)
                else:
                    archived.unlink(); archived.symlink_to(replacement)
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", altered)
    with pytest.raises(store.FactStoreError): store.load_final_fact_records_readonly((P, T))


def test_native_path_descriptor_compatibility_and_readonly_source(archived, capsys):
    """Runs natively on the Windows CI lane too; values aid any future failure."""
    before = tree(archived.parent)
    with archived.open("rb") as stream:
        path_identity = store._archive_stat_fingerprint(archived.stat())
        descriptor_identity = store._archive_stat_fingerprint(os.fstat(stream.fileno()))
    # Only this synthetic test file's numeric metadata; never a path or DB body.
    fields = ("device", "inode", "size", "mtime_ns", "ctime_ns", "birthtime_ns")
    with capsys.disabled():
        print("ARCHIVE_READER_NATIVE_STAT " + json.dumps({
            "platform": os.name, "python": list(sys.version_info[:3]),
            "path_stat": dict(zip(fields, path_identity)),
            "descriptor_stat": dict(zip(fields, descriptor_identity)),
        }, sort_keys=True))
    assert store._archive_descriptor_matches_path(path_identity, descriptor_identity), (path_identity, descriptor_identity)
    assert store.load_final_fact_record(T) is not None
    assert tree(archived.parent) == before
