"""数据健康 API 测试。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import data_health_event_store as store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VR_REPORTS_DIR", str(tmp_path / "myreports"))
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(tmp_path / "evidence_thesis.db"))
    import newsradar
    monkeypatch.setattr(newsradar, "CACHE_FILE", str(tmp_path / "radar.json"))
    monkeypatch.setattr(newsradar, "CACHE_DIR", str(tmp_path))
    import portfolio as pf
    monkeypatch.setattr(pf, "PF_FILE", str(tmp_path / "portfolio.json"))
    monkeypatch.setattr(pf, "CACHE_DIR", str(tmp_path))
    import watchlist_store as wl
    monkeypatch.setattr(wl, "_CACHE_DIR", str(tmp_path))
    import myreports
    monkeypatch.setattr(myreports, "REPORTS_DIR", tmp_path / "myreports")
    import data_health_adapters as adapters
    adapters.reset_adapters_for_tests()
    import app as app_mod
    return TestClient(app_mod.app), tmp_path


def test_all_not_initialized(client):
    c, root = client
    before = list(root.rglob("*"))
    r = c.get("/api/data-health")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["overall_status"] == "unavailable"
    assert body["summary"]["normal"] + body["summary"]["partial"] + body["summary"]["unavailable"] == 11
    assert body["summary"]["not_initialized"] == 11
    assert body["blocks_advice"] is False
    assert len(body["items"]) == 11
    after = list(root.rglob("*"))
    assert before == after
    assert not (root / "data_health_events.json").exists()


def test_gate_blocked_and_stale_partial(client):
    c, root = client
    frozen = datetime.now(timezone.utc) - timedelta(seconds=400)
    store.record_gate_blocked("HOLDING_QUOTES_UNAVAILABLE", now=frozen)
    store.record_partial("quotes", now=frozen)
    store.record_success("announcements", now=datetime.now(timezone.utc))

    r = c.get("/api/data-health")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["blocks_advice"] is True
    assert body["block_reasons"]
    assert body["block_reasons"][0]["error_code"] == "HOLDING_QUOTES_UNAVAILABLE"
    by = {it["source_id"]: it for it in body["items"]}
    assert by["portfolio_advice_gate"]["status"] == "normal"
    assert by["portfolio_advice_gate"]["blocks_advice"] is True
    assert by["portfolio_advice_gate"]["is_stale"] is True
    assert by["quotes"]["status"] == "partial"
    # overall should be partial (partial/stale present)
    assert body["overall_status"] == "partial"


def test_gate_allowed(client):
    c, _ = client
    store.record_gate_allowed()
    r = c.get("/api/data-health")
    body = r.json()["data"]
    gate = next(it for it in body["items"] if it["source_id"] == "portfolio_advice_gate")
    assert gate["status"] == "normal"
    assert gate["blocks_advice"] is False
    assert body["blocks_advice"] is False


def test_gate_runtime_failure(client):
    c, _ = client
    store.record_gate_failure("SOURCE_TIMEOUT")
    r = c.get("/api/data-health")
    gate = next(it for it in r.json()["data"]["items"] if it["source_id"] == "portfolio_advice_gate")
    assert gate["status"] == "unavailable"
    assert gate["blocks_advice"] is False


def test_filter_does_not_change_overall_or_gate(client):
    c, _ = client
    store.record_gate_blocked("NO_HOLDINGS")
    store.record_success("quotes")
    full = c.get("/api/data-health").json()["data"]
    filtered = c.get("/api/data-health", params={"status": "normal"}).json()["data"]
    assert filtered["overall_status"] == full["overall_status"]
    assert filtered["blocks_advice"] == full["blocks_advice"]
    assert filtered["summary"] == full["summary"]
    assert filtered["block_reasons"] == full["block_reasons"]
    assert len(filtered["items"]) < len(full["items"]) or len(filtered["items"]) <= 11


def test_unknown_source_404(client):
    c, _ = client
    r = c.get("/api/data-health/not-a-source")
    assert r.status_code == 404


def test_invalid_filters_422(client):
    c, _ = client
    assert c.get("/api/data-health", params={"status": "bad"}).status_code == 422
    assert c.get("/api/data-health", params={"module": "不存在的模块"}).status_code == 422
    assert c.get("/api/data-health", params={"is_stale": "maybe"}).status_code == 422
    assert c.get("/api/data-health", params={"blocks_advice": "yes"}).status_code == 422
    # comma module
    assert c.get("/api/data-health?module=a,b").status_code == 422
    # duplicate module
    assert c.get("/api/data-health?module=每日复盘&module=持仓建议").status_code == 422


def test_source_detail(client):
    c, _ = client
    r = c.get("/api/data-health/quotes")
    assert r.status_code == 200
    data = r.json()["data"]
    assert "record" in data
    assert "calculation" in data
    assert "related_pages" in data
    assert data["record"]["source_id"] == "quotes"
    # disclaimer for request-scoped
    calc = data["calculation"]
    assert "disclaimer" in calc or "最近一次" in json.dumps(calc, ensure_ascii=False)


def test_no_sensitive_leak(client):
    c, root = client
    # corrupt events
    p = root / "data_health_events.json"
    p.write_text('{"broken": true, "path": "C:\\\\secret\\\\key"}', encoding="utf-8")
    r = c.get("/api/data-health")
    text = r.text
    assert "Traceback" not in text
    assert "sqlite3" not in text
    assert "secret" not in text
    assert str(root) not in text
    assert "C:\\" not in text


def test_framework_error_500(client, monkeypatch):
    c, _ = client
    import data_health_adapters as adapters

    def boom(**kwargs):
        raise RuntimeError("registry broken")

    monkeypatch.setattr(adapters, "get_health_overview", boom)
    r = c.get("/api/data-health")
    assert r.status_code == 500
    assert r.json()["detail"] == "数据健康服务暂不可用"
    assert "registry broken" not in r.text


def test_module_filter_exact(client):
    c, _ = client
    r = c.get("/api/data-health", params={"module": "个股行情"})
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert all(it["module"] == "个股行情" for it in items)


def test_get_does_not_create_event_file(client):
    c, root = client
    c.get("/api/data-health")
    c.get("/api/data-health/daily_review")
    assert not (root / "data_health_events.json").exists()
