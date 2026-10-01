"""Atomic watchlist persistence, including recovery from older interrupted saves."""
import importlib.util
from pathlib import Path

import pytest

import watchlist_store as store


@pytest.fixture(autouse=True)
def isolated_watchlist(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_CACHE_DIR", str(tmp_path))


def restart_store():
    # Fresh module state, without reloading the shared module used by other tests.
    spec = importlib.util.spec_from_file_location("restarted_watchlist", store.__file__)
    restarted = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(restarted)
    restarted._CACHE_DIR = store._CACHE_DIR
    return restarted


def test_failed_final_replace_preserves_live_snapshot_and_merge(monkeypatch):
    original = store.save_watchlist(["600001"])
    path = Path(store._watchlist_path())
    before = path.read_bytes()
    replace = store.os.replace

    def fail_final(src, dst):
        if str(dst) == str(path):
            raise OSError("injected publish failure")
        replace(src, dst)

    with monkeypatch.context() as patch:
        patch.setattr(store.os, "replace", fail_final)
        with pytest.raises(OSError):
            store.save_watchlist(["600002"], expected_etag=original["etag"])
    assert path.read_bytes() == before
    assert Path(str(path) + ".bak").read_bytes() == before
    assert not list(path.parent.glob("*.tmp.*"))
    restarted = restart_store()
    assert restarted.get_watchlist_status()["etag"] == original["etag"]
    assert restarted.merge_watchlist(["600003"])["codes"] == ["600001", "600003"]


def test_legacy_missing_live_recovers_backup_without_consuming_it():
    original = store.save_watchlist(["600001"])
    path = Path(store._watchlist_path())
    backup = Path(str(path) + ".bak")
    path.rename(backup)  # Interrupted old implementation, synthetic fixture only.
    before = backup.read_bytes()
    restarted = restart_store()
    assert restarted.get_watchlist_status()["etag"] == original["etag"]
    assert restarted.load_watchlist() == ["600001"]
    assert not path.exists()
    with pytest.raises(restarted.WatchlistVersionConflictError):
        restarted.merge_watchlist(["600002"], expected_etag="stale")
    assert backup.read_bytes() == before
    result = restarted.merge_watchlist(["600003"], expected_etag=original["etag"])
    assert result["codes"] == ["600001", "600003"]
    assert backup.read_bytes() == before
    assert restarted.load_watchlist() == result["codes"]


def test_missing_live_with_corrupt_backup_is_not_unconfigured():
    backup = Path(store._watchlist_path() + ".bak")
    backup.write_text("{invalid", encoding="utf-8")
    assert restart_store().get_watchlist_status()["status"] == "corrupted"
    assert backup.read_text() == "{invalid"


def test_corrupt_live_does_not_silently_fall_back_to_stale_backup():
    store.save_watchlist(["600001"])
    store.save_watchlist(["600002"])
    Path(store._watchlist_path()).write_text("{invalid", encoding="utf-8")
    assert store.get_watchlist_status()["status"] == "corrupted"


def test_backup_failure_preserves_both_snapshots(monkeypatch):
    store.save_watchlist(["600001"])
    store.save_watchlist(["600002"])
    path = Path(store._watchlist_path())
    before = path.read_bytes()
    backup = Path(str(path) + ".bak")
    backup_before = backup.read_bytes()

    def partial_copy(src, dst):
        Path(dst).write_bytes(b"partial")
        raise OSError("injected backup failure")

    monkeypatch.setattr(store.shutil, "copyfile", partial_copy)
    with pytest.raises(OSError):
        store.save_watchlist(["600003"])
    assert path.read_bytes() == before
    assert backup.read_bytes() == backup_before
    assert not list(path.parent.glob("*.tmp.*"))
