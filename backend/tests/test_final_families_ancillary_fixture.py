"""Inherited browser fixtures match real empty services, not invented success."""
from datetime import datetime, timezone
import json
from pathlib import Path
import socket

import next_day_verification as journal
import short_term_seal_quality_service as seal


def test_fixed_ancillary_responses_match_empty_service_contracts(monkeypatch, tmp_path):
    fixture = json.loads((Path(__file__).parents[2] / "frontend/tests/fixtures/final-families-ancillary.json").read_text(encoding="utf-8"))
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path / "not-created"))
    monkeypatch.delenv("VR_FACT_LAKE_ROOT", raising=False)
    monkeypatch.setattr(journal, "_now", lambda: datetime(2026, 10, 8, 8, tzinfo=timezone.utc))
    # Explicitly unavailable synthetic calendar, not a statement about Oct 8.
    monkeypatch.setattr(journal.trade_calendar, "next_trade_date", lambda day: None)
    def forbidden(*args, **kwargs):
        raise AssertionError("network prohibited")
    for owner, name in ((socket.socket, "connect"), (socket.socket, "connect_ex"), (socket, "getaddrinfo"), (socket, "create_connection")):
        monkeypatch.setattr(owner, name, forbidden)
    assert journal.view("2026-10-08") == fixture["journal"]
    assert seal.query_seal_quality("2026-10-08") == fixture["seal"]
    assert not (tmp_path / "not-created").exists()
