from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from fastapi.testclient import TestClient

import app as app_module
import discovery_service as discovery


NOW = datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc)


def _row(
    code: str,
    name: str,
    industry: str | None,
    *,
    change: float,
    amount: float,
    turnover: float,
    cap: float = 10_000_000_000,
    **extra,
) -> dict:
    return {
        "code": code,
        "name": name,
        "industry": industry,
        "price": 10.0,
        "change_pct": change,
        "amount": amount,
        "turnover_pct": turnover,
        "float_market_cap": cap,
        "pe_ttm": 20.0,
        "pb": 2.0,
        "listing_date": "2000-01-01",
        **extra,
    }


def _history(code: str, return_20d: float, return_60d: float) -> dict:
    return {
        "code": code,
        "latest_date": "2026-08-28",
        "return_20d": return_20d,
        "return_20d_status": "normal",
        "return_60d": return_60d,
        "return_60d_status": "normal",
    }


def _providers(
    rows: list[dict] | None = None,
    *,
    histories: list[dict] | None = None,
    financial_error: set[str] | None = None,
    announcement_error: set[str] | None = None,
    catalyst_codes: set[str] | None = None,
    intel_status: str = "normal",
    counters: dict[str, int] | None = None,
) -> discovery.DiscoveryProviders:
    rows = rows or [
        _row("600001", "短线样本", "科技", change=8, amount=1_000, turnover=20),
        _row("600002", "波段样本", "科技", change=-0.5, amount=900, turnover=5),
        _row("600003", "中线样本", "金融", change=1, amount=800, turnover=1),
        _row("000001", "市场样本一", "金融", change=-1, amount=100, turnover=0.5),
        _row("000002", "市场样本二", "消费", change=-2, amount=90, turnover=0.4),
        _row("300001", "市场样本三", "科技", change=0.5, amount=80, turnover=0.3),
    ]
    histories = histories or [
        _history("600001", -0.1, -0.2),
        _history("600002", 0.2, -0.1),
        _history("600003", -0.1, 0.3),
        _history("000001", -0.1, -0.1),
        _history("000002", -0.1, -0.1),
        _history("300001", -0.1, -0.1),
    ]
    financial_error = financial_error or set()
    announcement_error = announcement_error or set()
    catalyst_codes = catalyst_codes if catalyst_codes is not None else {"600001", "600002", "600003"}
    counters = counters if counters is not None else {}

    def financials(code: str) -> dict:
        counters["financials"] = counters.get("financials", 0) + 1
        if code in financial_error:
            raise RuntimeError("fixture unavailable")
        return {
            "period": "2026Q2",
            "revenue": 100,
            "net_profit": 10,
            "revenue_yoy": 12,
            "net_profit_yoy": 15,
            "data_quality": {"status": "normal"},
        }

    def announcements(code: str) -> list[dict]:
        counters["announcements"] = counters.get("announcements", 0) + 1
        if code in announcement_error:
            raise RuntimeError("fixture unavailable")
        return [{"title": f"{code} 正式公告", "date": "2026-08-29"}] if code in catalyst_codes else []

    def native(codes: list[str]) -> dict:
        return {
            "status": intel_status,
            "stats": {
                code: {
                    "mention_count": 1 if code in catalyst_codes else 0,
                    "source_count": 1 if code in catalyst_codes else 0,
                    "first_seen_at": "2026-08-29T01:00:00Z" if code in catalyst_codes else None,
                    "last_seen_at": "2026-08-29T01:00:00Z" if code in catalyst_codes else None,
                }
                for code in codes
            },
            "terms": [
                {"security_code": code, "term_kind": "concept", "term": "AI", "source_ref": "fixture"}
                for code in codes
                if code in catalyst_codes
            ],
            "reason_code": None if intel_status == "normal" else "FIXTURE_PARTIAL",
        }

    return discovery.DiscoveryProviders(
        market_snapshot=lambda: rows,
        full_market=lambda: {
            "status": "normal",
            "as_of": "2026-08-28",
            "fetched_at": "2026-08-28T07:00:00Z",
            "rows": histories,
            "provenance": {"artifact_sha256": "fixture-hash"},
        },
        financials=financials,
        announcements=announcements,
        native_intel=native,
    )


def _all_queue_items(result: dict) -> list[dict]:
    return [item for strategy in discovery.STRATEGIES for item in result["queues"][strategy]]


def _assert_no_investment_output(value) -> None:
    forbidden = {"buy", "score", "expected_return", "target_position", "action"}
    if isinstance(value, dict):
        assert forbidden.isdisjoint({str(key).lower() for key in value})
        for nested in value.values():
            _assert_no_investment_output(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_investment_output(nested)


def test_normal_discovery_separates_strategy_queues_and_explains_research_priority():
    result = discovery.run_discovery(providers=_providers(), now=NOW)

    assert result["status"] == "partial"
    assert result["as_of"] == "2026-08-28"
    assert result["as_of"] != "2026-08-30"
    assert result["fetched_at"] == "2026-08-30T01:00:00Z"
    assert result["funnel"]["core_universe"] == 6
    assert {item["security_code"] for item in result["queues"]["SHORT"]} == {"600001"}
    assert {item["security_code"] for item in result["queues"]["SWING"]} == {"600002"}
    assert {item["security_code"] for item in result["queues"]["MEDIUM"]} == {"600003"}
    for item in _all_queue_items(result):
        assert item["reason_codes"]
        assert item["supporting_observations"]
        assert item["provenance_refs"]
        assert item["evidence_gate"] == "PARTIAL"
        assert item["research_priority"] != "HIGH"
        assert item["as_of"] == "2026-08-28"
        assert item["discovery_state"] == "QUEUED"
    _assert_no_investment_output(result)
    assert "campaign" not in json.dumps(result, ensure_ascii=False).lower()


def test_partial_sources_keep_truthful_unknowns_and_do_not_create_fake_high_priority():
    providers = _providers(
        histories=[],
        financial_error={"600002"},
        announcement_error={"600002"},
        catalyst_codes={"600001", "600003"},
        intel_status="partial",
    )
    providers = discovery.DiscoveryProviders(
        market_snapshot=providers.market_snapshot,
        full_market=lambda: {"status": "unavailable", "rows": []},
        financials=providers.financials,
        announcements=providers.announcements,
        native_intel=providers.native_intel,
    )

    result = discovery.run_discovery(providers=providers, now=NOW)

    assert result["status"] == "partial"
    assert next(item for item in result["datasets"] if item["dataset_id"] == "research_data_plane.full_market")["status"] == "unavailable"
    assert all(item["research_priority"] != "HIGH" for item in _all_queue_items(result))
    assert any(
        "RETURN_20D_UNKNOWN" in item.get("reason_codes", [])
        or "RETURN_20D_UNKNOWN" in item.get("uncertainties", [])
        for item in [*_all_queue_items(result), *result["excluded"]]
    )
    assert result["queues"]["SHORT"], "a usable stock must survive a sibling provider failure"


def test_market_snapshot_without_authoritative_trade_date_stays_partial(monkeypatch):
    monkeypatch.setattr(discovery, "observation_trade_date_at", lambda _fetched_at: None)

    result = discovery.run_discovery(providers=_providers(), now=NOW)

    market_dataset = next(
        item for item in result["datasets"]
        if item["dataset_id"] == "market.a_share_snapshot"
    )
    assert result["status"] == "partial"
    assert result["as_of"] is None
    assert result["market_context"]["status"] == "partial"
    assert market_dataset["status"] == "partial"
    assert market_dataset["as_of"] is None
    assert market_dataset["reason_code"] == "MARKET_TRADE_DATE_UNKNOWN"
    assert _all_queue_items(result)
    assert all(item["as_of"] is None for item in _all_queue_items(result))
    assert all(item["research_priority"] != "HIGH" for item in _all_queue_items(result))
    assert all("MARKET_TRADE_DATE_UNKNOWN" in item["uncertainties"] for item in _all_queue_items(result))
    assert all("HISTORICAL_ROW_STALE" not in item["uncertainties"] for item in _all_queue_items(result))


def test_restricted_universe_is_visible_but_uses_stricter_qualification():
    rows = [
        _row("600010", "*ST有线索", "科技", change=9, amount=1_000, turnover=25),
        _row("600011", "*ST无线索", "科技", change=8, amount=900, turnover=20),
        _row("600012", "上市初期", "科技", change=7, amount=800, turnover=18, listing_days=10),
        _row("000001", "普通样本", "金融", change=-1, amount=100, turnover=0.5),
        _row("000002", "普通样本二", "消费", change=-2, amount=90, turnover=0.4),
        _row("830001", "北交样本", "其他", change=10, amount=2_000, turnover=30),
    ]
    histories = [_history(code, 0.2, 0.2) for code in ("600010", "600011", "600012", "000001", "000002")]
    result = discovery.run_discovery(
        providers=_providers(rows, histories=histories, catalyst_codes={"600010", "600012"}),
        now=NOW,
    )

    queued = _all_queue_items(result)
    with_clue = [item for item in queued if item["security_code"] == "600010"]
    assert with_clue and all(item["research_priority"] == "LOW" for item in with_clue)
    assert all(item["restricted_universe"]["status"] == "RESTRICTED" for item in with_clue)
    assert not any(item["security_code"] == "600011" for item in queued)
    assert any(item.get("security_code") == "600011" for item in result["excluded"])
    assert any(item.get("security_code") == "830001" and "OUTSIDE_CORE_A_SHARE_UNIVERSE" in item["reason_codes"] for item in result["excluded"])


def test_strategy_divergence_is_not_collapsed_into_one_universal_result():
    result = discovery.run_discovery(providers=_providers(), now=NOW)
    assert "600001" in {item["security_code"] for item in result["queues"]["SHORT"]}
    assert "600001" not in {item["security_code"] for item in result["queues"]["MEDIUM"]}
    assert "600003" in {item["security_code"] for item in result["queues"]["MEDIUM"]}
    assert "600003" not in {item["security_code"] for item in result["queues"]["SHORT"]}


def test_synthetic_full_market_scan_bounds_expensive_qualification_calls():
    prefixes = ("600", "601", "603", "605", "000", "001", "002", "003", "300", "301", "688", "689")
    rows = []
    histories = []
    for index in range(5_200):
        code = f"{prefixes[index % len(prefixes)]}{index // len(prefixes):03d}"
        rows.append(_row(code, f"样本{index}", f"行业{index % 20}", change=(index % 10) + 1, amount=10_000 - index, turnover=(index % 30) + 1))
        histories.append(_history(code, 0.1, 0.1))
    counters: dict[str, int] = {}
    started = time.perf_counter()
    result = discovery.run_discovery(providers=_providers(rows, histories=histories, catalyst_codes=set(), counters=counters), now=NOW)
    elapsed = time.perf_counter() - started

    assert result["funnel"]["core_universe"] == 5_200
    assert counters["financials"] <= discovery.QUALIFICATION_LIMIT
    assert counters["announcements"] <= discovery.QUALIFICATION_LIMIT
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    for queue in result["queues"].values():
        keys = [(order[item["research_priority"]], item["security_code"]) for item in queue]
        assert keys == sorted(keys)
    assert elapsed < 2.0


def test_unmapped_intel_and_out_of_window_announcements_stay_unknown():
    base = _providers(catalyst_codes=set())
    providers = discovery.DiscoveryProviders(
        market_snapshot=base.market_snapshot,
        full_market=base.full_market,
        financials=base.financials,
        announcements=lambda _code: [
            {"title": "旧公告", "date": "2026-01-01"},
            {"title": "未来公告", "date": "2026-09-01"},
        ],
        native_intel=lambda _codes: {"status": "normal", "stats": {}, "terms": []},
    )

    result = discovery.run_discovery(providers=providers, now=NOW)

    assert _all_queue_items(result)
    for item in _all_queue_items(result):
        assert item["catalyst_status"] == "UNKNOWN"
        assert item["research_priority"] != "HIGH"
        assert "CATALYST_EVIDENCE_UNKNOWN" in item["uncertainties"]
        assert "NATIVE_INTEL_MAPPING_UNKNOWN" in item["uncertainties"]
        assert all(observation["code"] != "CATALYST_CLUE_AVAILABLE" for observation in item["supporting_observations"])


def test_stale_history_narrows_health_without_marking_security_restricted():
    histories = [
        {**_history("600001", 0.5, 0.5), "latest_date": "2026-08-01"},
        *[_history(code, 0.2, 0.2) for code in ("600002", "600003", "000001", "000002", "300001")],
    ]

    result = discovery.run_discovery(providers=_providers(histories=histories), now=NOW)
    item = next(
        item for item in result["queues"]["SHORT"]
        if item["security_code"] == "600001"
    )
    rdp_dataset = next(
        dataset for dataset in result["datasets"]
        if dataset["dataset_id"] == "research_data_plane.full_market"
    )

    assert item["restricted_universe"]["status"] == "CLEAR"
    assert "RDP_LATEST_DATE_BEHIND_MARKET" not in item["restricted_universe"]["reason_codes"]
    assert "HISTORICAL_ROW_STALE" in item["uncertainties"]
    assert "RDP_LATEST_DATE_BEHIND_MARKET" in item["uncertainties"]
    assert item["data_health"] == "partial"
    assert item["evidence_gate"] == "PARTIAL"
    assert item["research_priority"] != "HIGH"
    assert rdp_dataset["status"] == "partial"
    assert rdp_dataset["reason_code"] == "RDP_LATEST_DATE_BEHIND_MARKET"


def test_unproven_financial_period_cannot_contribute_fully_current_high_priority():
    base = _providers()
    providers = discovery.DiscoveryProviders(
        market_snapshot=base.market_snapshot,
        full_market=base.full_market,
        financials=lambda _code: {
            "period": "2022-12-31",
            "revenue": 100,
            "net_profit": 10,
            "data_quality": {"status": "normal"},
        },
        announcements=base.announcements,
        native_intel=base.native_intel,
    )

    result = discovery.run_discovery(providers=providers, now=NOW)
    item = next(item for item in result["queues"]["SHORT"] if item["security_code"] == "600001")
    financial_dataset = next(
        dataset for dataset in result["datasets"]
        if dataset["dataset_id"] == "financials.snapshot"
    )

    assert item["fundamental_status"] == "PARTIAL"
    assert item["evidence_gate"] == "PARTIAL"
    assert item["research_priority"] != "HIGH"
    assert item["data_health"] == "partial"
    assert "FUNDAMENTAL_FRESHNESS_UNKNOWN" in item["uncertainties"]
    assert discovery.FINANCIAL_FRESHNESS_REASON in item["reason_codes"]
    assert financial_dataset["status"] == "partial"
    assert financial_dataset["as_of"] is None
    assert financial_dataset["reason_code"] == discovery.FINANCIAL_FRESHNESS_REASON


def test_unknown_listing_age_stays_unknown_and_cannot_receive_high_priority():
    rows = [
        _row("600001", "上市日期未知", "科技", change=8, amount=1_000, turnover=20, listing_date=None),
        _row("600002", "波段样本", "科技", change=-0.5, amount=900, turnover=5),
        _row("600003", "中线样本", "金融", change=1, amount=800, turnover=1),
        _row("000001", "市场样本一", "金融", change=-1, amount=100, turnover=0.5),
        _row("000002", "市场样本二", "消费", change=-2, amount=90, turnover=0.4),
        _row("300001", "市场样本三", "科技", change=0.5, amount=80, turnover=0.3),
    ]

    result = discovery.run_discovery(providers=_providers(rows), now=NOW)
    item = next(item for item in result["queues"]["SHORT"] if item["security_code"] == "600001")

    assert item["restricted_universe"]["status"] == "UNKNOWN"
    assert item["research_priority"] != "HIGH"
    assert "LISTING_AGE_NOT_EVALUATED" in item["uncertainties"]


def test_empty_market_snapshot_fails_closed_without_running_expensive_providers():
    calls = {"count": 0}

    def unexpected(*_args):
        calls["count"] += 1
        raise AssertionError("must not be called")

    result = discovery.run_discovery(
        providers=discovery.DiscoveryProviders(
            market_snapshot=lambda: [],
            full_market=unexpected,
            financials=unexpected,
            announcements=unexpected,
            native_intel=unexpected,
        ),
        now=NOW,
    )

    assert result["status"] == "unavailable"
    assert result["queues"] == {strategy: [] for strategy in discovery.STRATEGIES}
    assert calls["count"] == 0


def test_stage3_timeout_returns_partial_without_blocking_other_queues(monkeypatch):
    base = _providers()

    def one_slow_financial(code: str) -> dict:
        if code == "600002":
            time.sleep(0.1)
        return base.financials(code)

    monkeypatch.setattr(discovery, "QUALIFICATION_TIMEOUT_SECONDS", 0.01)
    started = time.perf_counter()
    result = discovery.run_discovery(
        providers=discovery.DiscoveryProviders(
            market_snapshot=base.market_snapshot,
            full_market=base.full_market,
            financials=one_slow_financial,
            announcements=base.announcements,
            native_intel=base.native_intel,
        ),
        now=NOW,
    )

    assert time.perf_counter() - started < 0.3
    assert result["status"] == "partial"
    assert result["queues"]["SHORT"]
    assert result["queues"]["MEDIUM"]


def test_cache_serves_latest_snapshot_and_failed_refresh_returns_stale(monkeypatch):
    normal = discovery.run_discovery(providers=_providers(), now=NOW)
    unavailable = {
        **normal,
        "status": "unavailable",
        "fetched_at": "2026-08-30T04:00:00Z",
        "refresh_attempted_at": "2026-08-30T04:00:00Z",
        "queues": {strategy: [] for strategy in discovery.STRATEGIES},
    }
    results = iter((normal, unavailable))
    monkeypatch.setattr(discovery, "run_discovery", lambda: next(results))
    discovery.clear_cache()
    try:
        first = discovery.get_discovery(force_refresh=True)
        cached = discovery.get_discovery()
        stale = discovery.get_discovery(force_refresh=True)

        assert first["status"] == "partial"
        assert cached["cache"]["hit"] is True
        assert stale["status"] == "stale"
        assert stale["cache"]["refresh_failed"] is True
        assert stale["queues"] == normal["queues"]
        assert stale["fetched_at"] == normal["fetched_at"]
        assert stale["last_successful_at"] == normal["last_successful_at"]
        assert stale["refresh_attempted_at"] == unavailable["refresh_attempted_at"]
        assert stale["fetched_at"] != unavailable["fetched_at"]
    finally:
        discovery.clear_cache()


def test_discovery_api_uses_service_contract_without_formal_state_creation(monkeypatch):
    expected = discovery.run_discovery(providers=_providers(), now=NOW)
    monkeypatch.setattr(discovery, "get_discovery", lambda force_refresh=False: {**expected, "refresh_requested": force_refresh})
    client = TestClient(app_module.app)

    response = client.get("/api/screener/discovery", params={"refresh": "true"})

    assert response.status_code == 200
    assert response.json()["schema_version"] == discovery.SCHEMA_VERSION
    assert response.json()["refresh_requested"] is True
