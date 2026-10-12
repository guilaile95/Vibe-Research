"""Bounded committed-only public receipt enumeration, temporary files only."""
from datetime import datetime, timezone
import hashlib

import pytest
from data_contracts import ProviderObservation, FetchSemantics, HistoryMode, QualityStatus
from fact_lake_store import initialize_fact_lake


def receipt(lake, name, day, dataset="research_test"):
    raw = b'{"synthetic":true}'
    obs = ProviderObservation(observation_id=name, dataset_id=dataset, provider_id="synthetic",
        provider_endpoint="fixture", provider_symbol="all", request_fingerprint="fixture",
        source_payload_hash="sha256:" + hashlib.sha256(raw).hexdigest(), normalizer_version="fixture.v1",
        payload={"fixture": True}, fetch_semantics=FetchSemantics.BY_DATE, history_mode=HistoryMode.BY_DATE,
        fetched_at=day + "T08:00:00Z", trade_date=day, quality_status=QualityStatus.VALID)
    return lake.store_observation(obs, raw, "application/json")


def test_listing_bounds_order_and_scope(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    receipt(lake, "b", "2026-07-30")
    receipt(lake, "a", "2026-07-29")
    receipt(lake, "other", "2026-07-29", "different")
    kwargs = dict(dataset_id="research_test", start_trade_date="2026-07-29", end_trade_date="2026-07-30")
    assert [v.observation.observation_id for v in lake.list_observations(**kwargs)] == ["a", "b"]
    assert len(lake.list_observations(**kwargs, limit=1)) == 1
    assert lake.list_observations(dataset_id="missing", start_trade_date="2026-07-29", end_trade_date="2026-07-30") == ()
    for invalid in (True, 0, 10001):
        with pytest.raises(ValueError):
            lake.list_observations(**kwargs, limit=invalid)
    with pytest.raises(ValueError):
        lake.list_observations(dataset_id="research_test", start_trade_date="2024-01-01", end_trade_date="2026-07-30")
    stored = lake.get_observation("a")
    (lake.root / stored.blob_relpath).write_bytes(b"corrupted")
    with pytest.raises(Exception):
        lake.list_observations(**kwargs)
