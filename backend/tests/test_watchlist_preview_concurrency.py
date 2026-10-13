"""Synthetic table-import authority races. No real user files or providers."""
from pathlib import Path
import pytest
import watchlist_store as store

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_CACHE_DIR", str(tmp_path))

def test_first_create_compare_and_save():
    assert store.save_watchlist(["600519"], expected_etag="NOT_CONFIGURED")["codes"] == ["600519"]

def test_first_create_race_preserves_other_writer():
    first = store.save_watchlist(["000858"])
    with pytest.raises(store.WatchlistVersionConflictError):
        store.save_watchlist(["600519"], expected_etag="NOT_CONFIGURED")
    assert store.get_watchlist_status()["etag"] == first["etag"]
    assert store.load_watchlist() == ["000858"]

def test_deleted_after_preview_is_not_empty_permission():
    saved = store.save_watchlist(["000858"])
    Path(store._watchlist_path()).unlink()  # Synthetic file within tmp_path.
    with pytest.raises(store.WatchlistVersionConflictError):
        store.save_watchlist(["000858", "600519"], expected_etag=saved["etag"])
    assert not Path(store._watchlist_path()).exists()

@pytest.mark.parametrize("etag", ["NOT_CONFIGURED", "old", "CORRUPTED"])
def test_corrupt_after_preview_is_never_overwritten(etag):
    path = Path(store._watchlist_path()); path.write_text("broken fixture")
    with pytest.raises(store.WatchlistVersionConflictError):
        store.save_watchlist(["600519"], expected_etag=etag)
    assert path.read_text() == "broken fixture"

def test_valid_version_saves_and_conflict_preserves_bytes():
    saved = store.save_watchlist(["000858"])
    new = store.save_watchlist(["000858", "600519"], expected_etag=saved["etag"])
    before = Path(store._watchlist_path()).read_bytes()
    with pytest.raises(store.WatchlistVersionConflictError):
        store.save_watchlist(["000858", "300750"], expected_etag=saved["etag"])
    assert Path(store._watchlist_path()).read_bytes() == before
    assert store.get_watchlist_status()["etag"] == new["etag"]
