"""Explicit synthetic manual notes, never official evidence or live ingestion."""
from copy import deepcopy
import uuid
import socket
import asyncio
import httpx
from fastapi import FastAPI
from shortline_research_router import router
import pytest
from fact_lake_store import initialize_fact_lake, open_existing_fact_lake_snapshot, FactLakeObservationConflictError
from shortline_regime_annotations import save_regime_annotation, read_regime_annotations, validate_entry


@pytest.fixture(autouse=True)
def no_outbound(monkeypatch, tmp_path):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path / "private"))
    loop = asyncio.new_event_loop()
    def forbidden(*args, **kwargs):
        raise AssertionError("outbound I/O forbidden")
    for owner, key in ((socket, "create_connection"), (socket, "getaddrinfo"), (socket.socket, "connect"), (socket.socket, "connect_ex")):
        monkeypatch.setattr(owner, key, forbidden)
    try:
        yield loop
    finally:
        loop.close()


def entry():
    return {"effective_date": "2026-12-01", "announcement_date": "2026-10-12", "title": "Synthetic planned rule note",
            "note": "Synthetic user claim, not an official event", "source_url": "https://example.com/research-note",
            "idempotency_key": str(uuid.uuid4())}


def test_explicit_save_idempotent_and_immutable(tmp_path, monkeypatch):
    root = tmp_path / "lake"; initialize_fact_lake(root); monkeypatch.setenv("VR_FACT_LAKE_ROOT", str(root))
    value = entry(); first = save_regime_annotation(value); second = save_regime_annotation(value)
    assert first["created"] is True and second["created"] is False
    assert first["id"] == second["id"] and first["created_at"] == second["created_at"]
    value["title"] = "changed"
    with pytest.raises(FactLakeObservationConflictError): save_regime_annotation(value)
    lake = open_existing_fact_lake_snapshot(root)
    result = read_regime_annotations(lake, "2026-10-12"); lake.assert_unchanged()
    assert len(result["events"]) == 1 and result["events"][0]["upcoming"]
    assert result["events"][0]["title"] == "Synthetic planned rule note"
    assert result["authority"] == "USER_AUTHORED_UNVERIFIED"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///tmp/x", "data:text/plain,x", "https://user:secret@example.com/", "https://example.com:abc/", "https://example.com/a\nb"])
def test_unsafe_source_url_rejected(url):
    value = entry(); value["source_url"] = url
    with pytest.raises(ValueError): validate_entry(value)


def test_date_bounds_and_no_automatic_archive_initialization(tmp_path, monkeypatch):
    value = entry(); value["effective_date"] = "2026-02-30"
    with pytest.raises(ValueError): validate_entry(value)
    root = tmp_path / "not-created"; monkeypatch.setenv("VR_FACT_LAKE_ROOT", str(root))
    with pytest.raises(Exception): save_regime_annotation(entry())
    assert not root.exists()


def test_explicit_http_save_and_bounded_body(tmp_path, monkeypatch, no_outbound):
    root = tmp_path / "lake"; initialize_fact_lake(root); monkeypatch.setenv("VR_FACT_LAKE_ROOT", str(root))
    app = FastAPI(); app.include_router(router)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            value = entry()
            first = await client.post("/api/market/shortline-research/regime-events", json=value)
            second = await client.post("/api/market/shortline-research/regime-events", json=value)
            assert first.status_code == second.status_code == 200
            assert first.json()["data"]["id"] == second.json()["data"]["id"]
            assert second.json()["data"]["created"] is False
            assert (await client.post("/api/market/shortline-research/regime-events?root=/tmp/x", json=value)).status_code == 422
            assert (await client.post("/api/market/shortline-research/regime-events", content=b"x" * 10001)).status_code == 413
    no_outbound.run_until_complete(run())
