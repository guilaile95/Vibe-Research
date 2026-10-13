"""Local-draft imports fail closed instead of acknowledging truncated data."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.watchlist_store, "_CACHE_DIR", str(tmp_path))
    return TestClient(app_module.app)


@pytest.mark.parametrize("existing", [[], ["600000"]])
def test_oversized_import_returns_400_and_keeps_authoritative_snapshot(client, existing):
    saved = client.put("/api/watchlist", json={"codes": existing})
    assert saved.status_code == 200
    before = Path(app_module.watchlist_store._watchlist_path()).read_bytes()
    response = client.post("/api/watchlist/import-local", json={
        "codes": [f"{600000 + i:06d}" for i in range(51)],
        "expected_etag": saved.json()["data"]["etag"],
    })
    assert response.status_code == 400
    assert "51" in response.json()["detail"]
    assert Path(app_module.watchlist_store._watchlist_path()).read_bytes() == before
    assert client.get("/api/watchlist").json()["data"]["data"]["codes"] == existing


def test_duplicate_import_can_fill_limit_and_retry_without_duplicates(client):
    codes = [f"{600000 + i:06d}" for i in range(50)]
    first = client.post("/api/watchlist/import-local", json={"codes": codes + codes})
    assert first.status_code == 200
    result = first.json()["data"]
    assert result["codes"] == codes
    again = client.post("/api/watchlist/import-local", json={
        "codes": codes,
        "expected_etag": result["etag"],
    })
    assert again.status_code == 200
    assert again.json()["data"]["added"] == []
    assert again.json()["data"]["codes"] == codes
