"""Both consumers must read one immutable generation, including default 1000 paging."""
import csv
from datetime import date, timedelta
import pytest
import research_data_plane as rdp
import stock_relative_context as stock
import sector_industry_context as sector


def envelope(**changes):
    return {"status": "normal", "snapshot_id": "a" * 64, "as_of": "2026-03-02", "latest_date": "2026-03-02", "dataset_id": rdp.DATASET_ID, "provider_id": rdp.PROVIDER_ID, "adjustment": rdp.ADJUSTMENT, "provenance": {"source_name": "fixture"}, "rows": [], "next_offset": None, **changes}


@pytest.mark.parametrize("consumer", [stock._read_full_market, sector._read_rdp_rows])
@pytest.mark.parametrize("field,value", [("snapshot_id", "b" * 64), ("as_of", "2026-03-01"), ("latest_date", "2026-03-01"), ("dataset_id", "other"), ("provider_id", "other"), ("adjustment", "ADJUSTED"), ("provenance", {"source_name": "other"})])
def test_changed_page_identity_is_rejected(consumer, field, value):
    def read(**kw):
        if kw["offset"] == 0:
            assert "snapshot_id" not in kw
            return envelope(next_offset=1)
        assert kw["snapshot_id"] == "a" * 64
        return envelope(**{field: value})
    with pytest.raises((stock._RdpUnavailable, sector._RdpUnavailable), match="pagination_identity_changed|invalid_page_provenance|inconsistent_page_date"):
        consumer(read)


@pytest.mark.parametrize("consumer", [stock._read_full_market, sector._read_rdp_rows])
@pytest.mark.parametrize("changes", [{"snapshot_id": None}, {"provenance": {}}, {"next_offset": True}, {"next_offset": "1"}, {"next_offset": 0}])
def test_missing_identity_or_invalid_paging_fails_closed(consumer, changes):
    with pytest.raises((stock._RdpUnavailable, sector._RdpUnavailable)):
        consumer(lambda **kw: envelope(**changes))


@pytest.mark.parametrize("count,page_size", [(3, 2), (1001, 1000)])
def test_real_rdp_rotation_pins_both_consumers(tmp_path, monkeypatch, count, page_size):
    codes = [f"{i:06d}" for i in range(1, count + 1)]
    def make(name, last):
        path = tmp_path / f"{name}.csv"
        with path.open("w") as handle:
            writer = csv.writer(handle)
            writer.writerow(["code", "trade_date", "open", "high", "low", "close", "volume"])
            for code in codes:
                for day in range(61):
                    price = last if day == 60 else 10
                    writer.writerow([code, (date(2026, 1, 1) + timedelta(days=day)).isoformat(), price, price, price, price, 100])
        return path
    first, second = make("a", 11), make("b", 20)
    root = tmp_path / "rdp"
    monkeypatch.setattr(stock, "_RDP_PAGE_SIZE", page_size)
    monkeypatch.setattr(sector, "_RDP_PAGE_SIZE", page_size)
    for consumer in ("stock", "sector"):
        rdp.import_csv(first, root=root)
        reads = []
        def read(**kwargs):
            result = rdp.query_full_market(root=root, **kwargs)
            reads.append((kwargs, result["snapshot_id"]))
            if kwargs["offset"] == 0:
                rdp.import_csv(second, root=root)
            return result
        if consumer == "stock":
            result = stock.build_stock_relative_context(codes[-1], rdp_reader=read, snapshot_reader=lambda: [{"code": c, "industry": "Synthetic"} for c in codes])
            assert result["status"] == "normal"
            assert result["periods"]["5D"]["vs_market_pct_points"] == pytest.approx(0)
        else:
            rows, _, _ = sector._read_rdp_rows(read)
            assert len(rows) == count
            assert all(row["return_5d"] == pytest.approx(0.1) for row in rows.values())
        assert len(reads) == 2
        assert len({snapshot for _, snapshot in reads}) == 1
        assert reads[1][0]["snapshot_id"] == reads[0][1]


@pytest.mark.parametrize("consumer", [stock._read_full_market, sector._read_rdp_rows])
def test_disappearing_pinned_snapshot_is_unavailable(consumer):
    def read(**kwargs):
        if kwargs["offset"] == 0:
            return envelope(next_offset=1)
        assert kwargs["snapshot_id"] == "a" * 64
        return {"status": "unavailable", "reason": "snapshot_missing"}
    with pytest.raises((stock._RdpUnavailable, sector._RdpUnavailable), match="unavailable"):
        consumer(read)
