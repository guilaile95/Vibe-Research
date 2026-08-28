"""Focused NATIVE-INTEL1 contracts: persistence, failures, and A-share mapping."""

from __future__ import annotations

from pathlib import Path

import astock
from fastapi import FastAPI
from fastapi.testclient import TestClient

import native_intel_router
import native_intel_service as service
import native_intel_store as store


def _source(source_id: str, name: str) -> dict:
    return {
        "source_id": source_id,
        "name": name,
        "hint": "a-share",
        "url": f"https://example.test/{source_id}.xml",
        "source_type": "rss",
        "has_real_rank": False,
    }


def _item(key: str, title: str, summary: str = "") -> dict:
    return {
        "item_key": key,
        "canonical_url": f"https://example.test/{key}",
        "url": f"https://example.test/{key}",
        "title": title,
        "title_key": title,
        "summary": summary,
        "hint": "a-share",
        "published_at": "2026-08-28T09:00:00+08:00",
        "published_ts": 1787878800,
        "rank": 1,
    }


def _seed_source(path: Path) -> None:
    store.upsert_sources([_source("official-rss", "Official RSS")], path)
    store.start_run("seed", "test", 1, path)


def _insert(path: Path, key: str, title: str, summary: str = "") -> int:
    item_id, _ = store.upsert_observation(
        "seed",
        "official-rss",
        _item(key, title, summary),
        observed_at="2026-08-28T01:00:00Z",
        has_real_rank=False,
        db_path=path,
    )
    return item_id


def test_fetch_isolates_failed_source_dedupes_and_never_invents_rss_rank(tmp_path: Path) -> None:
    path = tmp_path / "native-intel.sqlite3"
    sources = [_source("good", "Good"), _source("bad", "Bad")]
    registry = {
        "sources": sources,
        "registry_version": "test",
        "redline": [],
        "recent_days": 7,
        "per_source": 6,
    }

    def fetcher(source, **_kwargs):
        if source["source_id"] == "bad":
            return [], store.ERROR_KIND_NETWORK, "URLError"
        row = _item("one", "贵州茅台发布年度报告")
        return [row, dict(row)], None, None

    result = service.run_fetch(
        "test", str(path), registry=registry, sources_override=sources, fetcher=fetcher
    )
    state = store.export_state(path)

    assert result["status"] == store.RUN_STATUS_PARTIAL
    assert result["source_ok"] == 1
    assert result["source_failed"] == 1
    assert result["item_seen"] == 1
    assert len(state["items"]) == 1
    assert len(state["observations"]) == 1
    assert state["observations"][0]["rank"] is None
    assert service.data_status(str(path))["status"] == service.STATUS_PARTIAL
    trend = service.trending(str(path), window_hours=24, top_n=5)
    assert trend["status"] == service.STATUS_PARTIAL
    assert trend["items"][0]["title"] == "贵州茅台发布年度报告"


def test_realistic_a_share_terms_map_code_company_industry_and_concept_without_fuzzy_aliases(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "native-intel.sqlite3"
    store.upsert_security_directory(
        [
            {"code": "600519", "name": "贵州茅台", "industry": "白酒"},
            {"code": "000858", "name": "五粮液", "industry": "白酒"},
            {"code": "300750", "name": "宁德时代", "industry": "电池"},
        ],
        path,
    )
    store.set_meta("directory_synced_at", service.utc_now_iso(), path)
    monkeypatch.setattr(astock, "individual_info", lambda _code: {})
    monkeypatch.setattr(
        astock,
        "concept_blocks",
        lambda code, strict=True: {
            "boards": [{"name": "白酒概念" if code in {"600519", "000858"} else "固态电池"}]
        },
    )
    monkeypatch.setattr(astock, "hot_concepts", lambda _code, strict=True: [])

    for code in ("600519", "000858", "300750"):
        result = service.ensure_security_terms(code, str(path), force=True)
        assert result["errors"] == []

    _seed_source(path)
    ids = [
        _insert(path, "maotai", "贵州茅台发布年度报告"),
        _insert(path, "baijiu", "白酒行业景气度回升"),
        _insert(path, "battery", "固态电池产业化进展加速"),
        _insert(path, "unrelated", "贵州旅游市场迎来旺季"),
    ]
    service.link_entities_for_items(ids, str(path))

    maotai = {row["title"] for row in store.query_items_by_security("600519", path)}
    wuliangye = {row["title"] for row in store.query_items_by_security("000858", path)}
    catl = {row["title"] for row in store.query_items_by_security("300750", path)}

    assert "贵州茅台发布年度报告" in maotai
    assert "白酒行业景气度回升" in maotai
    assert "白酒行业景气度回升" in wuliangye
    assert "贵州茅台发布年度报告" not in wuliangye
    assert "固态电池产业化进展加速" in catl
    assert "贵州旅游市场迎来旺季" not in maotai
    assert service._normalize_security_name("五 粮 液") == "五粮液"


def test_ascii_concept_and_security_code_require_real_boundaries() -> None:
    terms = [
        {"term": "AI", "term_kind": store.TERM_CONCEPT, "security_code": "300750"},
        {"term": "600519", "term_kind": store.TERM_SECURITY_CODE, "security_code": "600519"},
    ]

    assert service._match_terms("AI 算力需求增长", terms)[0]["term"] == "AI"
    assert service._match_terms("CHAIRMAN published results", terms) == []
    assert service._match_terms("代码600519发布公告", terms)[0]["term"] == "600519"
    assert service._match_terms("金额16005190元", terms) == []


def test_security_profile_uses_existing_delayed_source_for_real_sample(monkeypatch) -> None:
    calls: list[str] = []

    class Response:
        @staticmethod
        def json():
            return {"data": {"f57": "600519", "f58": "贵州茅台", "f127": "白酒Ⅱ"}}

    def fake_get(url, **_kwargs):
        calls.append(url)
        if "push2.eastmoney.com" in url:
            raise ConnectionError("primary unavailable")
        return Response()

    monkeypatch.setattr(astock, "em_get", fake_get)

    assert astock.security_profile("600519", strict=True) == {
        "code": "600519",
        "name": "贵州茅台",
        "industry": "白酒Ⅱ",
    }
    assert len(calls) == 2


def test_unresolved_security_fails_closed_to_exact_code(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "native-intel.sqlite3"
    monkeypatch.setattr(
        service,
        "_refresh_security_profile",
        lambda _code, _path: {"status": service.STATUS_UNAVAILABLE, "error": "A 股证券资料暂不可用"},
    )
    monkeypatch.setattr(service, "resolve_security_name", lambda _code, _path: (None, "unresolved"))
    monkeypatch.setattr(
        service,
        "_astock_terms",
        lambda _code, _path: ([], [{"source": "astock", "error": "数据源暂不可用"}]),
    )

    result = service.ensure_security_terms("601318", str(path), force=True)
    terms = store.list_entity_terms(path, security_code="601318")

    assert result["errors"]
    assert [(term["term"], term["term_kind"]) for term in terms] == [
        ("601318", store.TERM_SECURITY_CODE)
    ]
    assert service._match_terms("中国平安发布公告", terms) == []


def test_interrupted_run_is_failed_on_restart_without_losing_items(tmp_path: Path) -> None:
    path = tmp_path / "native-intel.sqlite3"
    _seed_source(path)
    _insert(path, "persisted", "宁德时代供应链更新")

    assert store.recover_stale_runs(path) == 1
    assert store.get_run("seed", path)["status"] == store.RUN_STATUS_FAILED
    assert store.count_items(path) == 1
    assert service.data_status(str(path))["status"] == service.STATUS_STALE


def test_native_intel_router_source_to_sink(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "native-intel.sqlite3"
    sources = [_source("good", "Good"), _source("bad", "Bad")]
    registry = {
        "sources": sources,
        "registry_version": "test",
        "redline": [],
        "recent_days": 7,
        "per_source": 6,
    }

    def fetcher(source, **_kwargs):
        if source["source_id"] == "bad":
            return [], store.ERROR_KIND_NETWORK, "URLError"
        return [_item("router", "贵州茅台白酒行业资讯")], None, None

    service.run_fetch(
        "test", str(path), registry=registry, sources_override=sources, fetcher=fetcher
    )
    store.upsert_security_directory(
        [{"code": "600519", "name": "贵州茅台", "industry": "白酒"}], path
    )
    store.replace_entity_terms(
        "600519",
        [
            {"term": "贵州茅台", "term_kind": store.TERM_COMPANY_NAME, "source_ref": "fixture"},
            {"term": "白酒", "term_kind": store.TERM_INDUSTRY, "source_ref": "fixture"},
        ],
        path,
    )
    rows, _ = store.query_items(path)
    service.link_entities_for_items([int(rows[0]["item_id"])], str(path))

    monkeypatch.setenv("VIBE_NATIVE_INTEL_DB", str(path))
    monkeypatch.setattr(
        service,
        "_refresh_security_profile",
        lambda _code, _path: {"status": service.STATUS_NORMAL, "error": None},
    )
    import watchlist_store

    monkeypatch.setattr(
        watchlist_store,
        "get_watchlist_status",
        lambda: {"status": "valid", "data": {"codes": ["600519"]}},
    )
    app = FastAPI()
    app.include_router(native_intel_router.router)
    client = TestClient(app)

    assert client.get("/api/native-intel/status").json()["status"] == "partial"
    assert client.get("/api/native-intel/items").json()["items"][0]["title"] == "贵州茅台白酒行业资讯"
    assert client.get("/api/native-intel/trending").json()["status"] == "partial"
    security = client.get("/api/native-intel/security-context/600519").json()
    assert security["status"] == "partial"
    assert security["observation"]["item_count"] == 1
    watchlist = client.get("/api/native-intel/watchlist-context").json()
    assert watchlist["status"] == "partial"
    assert watchlist["securities"][0]["code"] == "600519"
    assert client.get("/api/native-intel/security-context/not-a-code").status_code == 422
    assert any(
        getattr(route, "path", None) == "/api/native-intel/refresh"
        and "POST" in getattr(route, "methods", set())
        for route in native_intel_router.router.routes
    )
