"""TREND-PARITY Wave 1：热榜抓取 / 真实排名轨迹 / 掉榜与失败语义 / 来源管理。

测试只服务本轮验收（任务书 Test 1-10），不追覆盖率：
- 热榜来源走注入的 ``hotlist_fetcher``，RSS 走注入的 ``fetcher``，零网络；
- 掉榜 = 最近一次来源级 run 成功 + 条目曾存在 + 未出现在榜；
- 来源失败 = UNKNOWN，绝不当作掉榜；rank 永远不写 0 / 999。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import astock
import native_intel_hotlist as hotlist
import native_intel_router
import native_intel_service as service
import native_intel_store as store


def _hot_source() -> dict:
    return {
        "source_id": "hotlist-fixture",
        "name": "Fixture 热榜",
        "hint": "macro",
        "url": hotlist.build_source_url("cls-hot"),
        "source_type": "hotlist",
        "has_real_rank": True,
    }


def _rss_source() -> dict:
    return {
        "source_id": "macro-fixture-rss",
        "name": "Fixture RSS",
        "hint": "macro",
        "url": "https://example.test/fixture.xml",
        "source_type": "rss",
        "has_real_rank": False,
    }


def _hot_item(title: str, rank: int) -> dict:
    return {
        "item_key": f"https://cls.cn/subject/{title}",
        "canonical_url": f"https://cls.cn/subject/{title}",
        "url": f"https://cls.cn/subject/{title}",
        "title": title,
        "title_key": title,
        "summary": "",
        "hint": "macro",
        "published_at": None,
        "published_ts": 0,
        "rank": rank,
    }


def _registry() -> dict:
    return {
        "sources": [_hot_source(), _rss_source()],
        "registry_version": "tp1",
        "redline": [],
        "recent_days": 7,
        "per_source": 6,
    }


class _RoundFetcher:
    """按轮次返回榜单；轮次表耗尽或标记失败时返回结构化失败。"""

    def __init__(self, rounds: list[list[tuple[str, int]] | None]):
        self.rounds = list(rounds)

    def __call__(self, source, *, timeout, redline, **_kwargs):
        if not self.rounds:
            raise AssertionError("round 表耗尽")
        board = self.rounds.pop(0)
        if board is None:
            return [], store.ERROR_KIND_NETWORK, "URLError"
        return [_hot_item(title, rank) for title, rank in board], None, None


def _run_round(path: Path, fetcher) -> dict:
    return service.run_fetch(
        "test",
        str(path),
        registry=_registry(),
        sources_override=[_hot_source()],
        hotlist_fetcher=fetcher,
    )


def _board_titles(board: dict, state: str | None = None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in board["items"]:
        if state is None or item["current_state"] == state:
            out[item["title"]] = item
    return out


def _item_by_title(board: dict, title: str) -> dict:
    for item in board["items"]:
        if item["title"] == title:
            return item
    raise AssertionError(f"item {title!r} not in board")


# ---------------------------------------------------------------------------
# Test 1-4：首次上榜 / 排名变化 / 掉榜 / 来源失败
# ---------------------------------------------------------------------------


def test_rank_lifecycle_first_change_offlist_then_unknown(tmp_path: Path) -> None:
    path = tmp_path / "native-intel.sqlite3"
    fetcher = _RoundFetcher(
        [
            [("A", 3), ("B", 8)],  # round 1
            [("A", 1), ("B", 12)],  # round 2
            [("A", 2)],  # round 3：B 掉榜（抓取成功）
            None,  # round 4：来源失败
        ]
    )

    # Test 1 — 首次上榜：history = [3] / [8]
    _run_round(path, fetcher)
    board = service.hotlist_board(str(path))
    a = _item_by_title(board, "A")
    b = _item_by_title(board, "B")
    assert a["rank"] == 3 and b["rank"] == 8
    assert a["current_state"] == store.ITEM_STATE_ON_LIST
    ha = service.item_rank_history(a["item_id"], str(path))
    hb = service.item_rank_history(b["item_id"], str(path))
    assert [o["rank"] for o in ha["observations"]] == [3]
    assert [o["rank"] for o in hb["observations"]] == [8]
    assert a["rank_delta"] is None and b["rank_delta"] is None

    # Test 2 — 排名变化：A 3→1（+2），B 8→12（-4）；底层仍保存 3→1
    _run_round(path, fetcher)
    board = service.hotlist_board(str(path))
    a = _item_by_title(board, "A")
    b = _item_by_title(board, "B")
    assert a["rank"] == 1 and a["previous_rank"] == 3 and a["rank_delta"] == 2
    assert b["rank"] == 12 and b["previous_rank"] == 8 and b["rank_delta"] == -4
    ha = service.item_rank_history(a["item_id"], str(path))
    assert [o["rank"] for o in ha["observations"]] == [3, 1]

    # Test 3 — 掉榜：第三轮抓取成功但 B 未出现 → OFF_LIST，rank 保留 12，不是 0
    _run_round(path, fetcher)
    board = service.hotlist_board(str(path))
    a = _item_by_title(board, "A")
    b = _item_by_title(board, "B")
    assert a["current_state"] == store.ITEM_STATE_ON_LIST and a["rank"] == 2
    assert b["current_state"] == store.ITEM_STATE_OFF_LIST
    assert b["rank"] == 12  # 最后真实排名，不伪造
    hb = service.item_rank_history(b["item_id"], str(path))
    assert [o["rank"] for o in hb["observations"]] == [8, 12]

    # Test 4 — 来源失败：B 是 UNKNOWN（不是 OFF_LIST），A 同样 UNKNOWN
    outcome = _run_round(path, fetcher)
    assert outcome["status"] == store.RUN_STATUS_FAILED
    board = service.hotlist_board(str(path))
    assert board["status"] == service.STATUS_UNAVAILABLE or board["items"]
    a = _item_by_title(board, "A")
    b = _item_by_title(board, "B")
    assert a["current_state"] == store.ITEM_STATE_UNKNOWN
    assert b["current_state"] == store.ITEM_STATE_UNKNOWN
    assert b["rank"] == 12  # 保留最后真实排名
    # 来源 run 记录为 failed，绝不混入「成功但掉榜」
    last_run = store.latest_source_run("hotlist-fixture", str(path))
    assert last_run["status"] == store.SOURCE_RUN_FAILED


# ---------------------------------------------------------------------------
# Test 5 — RSS 不受热榜逻辑污染：rank 恒 NULL
# ---------------------------------------------------------------------------


def test_rss_items_keep_null_rank(tmp_path: Path) -> None:
    path = tmp_path / "native-intel.sqlite3"
    fetcher = _RoundFetcher([[("A", 3)]])

    def rss_fetcher(source, **_kwargs):
        row = {
            "item_key": "https://example.test/rss-1",
            "canonical_url": "https://example.test/rss-1",
            "url": "https://example.test/rss-1",
            "title": "RSS 新闻一",
            "title_key": "RSS 新闻一",
            "summary": "",
            "hint": "macro",
            "published_at": None,
            "published_ts": 0,
            "rank": None,
        }
        return [row], None, None

    service.run_fetch(
        "test",
        str(path),
        registry=_registry(),
        sources_override=[_hot_source(), _rss_source()],
        hotlist_fetcher=fetcher,
        fetcher=rss_fetcher,
    )
    # 热榜板面只含 hotlist 来源；RSS 条目从统一 items 查询读取
    board = service.hotlist_board(str(path))
    assert all(r["source_type"] == "hotlist" for r in board["items"])
    rows, _ = store.query_items(str(path))
    rss_rows = [r for r in rows if r["source_type"] == "rss"]
    assert len(rss_rows) == 1
    assert rss_rows[0]["rank"] is None
    assert rss_rows[0]["has_real_rank"] is False
    hot = _item_by_title(board, "A")
    assert hot["rank"] == 3
    # rank-history API 对 RSS 条目：无排名语义
    h = service.item_rank_history(int(rss_rows[0]["item_id"]), str(path))
    assert h["current_state"] == store.ITEM_STATE_NO_RANK_SEMANTICS
    assert h["observations"] == []


# ---------------------------------------------------------------------------
# Test 6/7/8 — 来源注册表：用户 RSS 持久化 / 系统源启停 / 删除权限
# ---------------------------------------------------------------------------


def test_user_rss_persists_across_reads(tmp_path: Path) -> None:
    path = tmp_path / "native-intel.sqlite3"
    store.initialize_store(path)
    seed_file_before = Path(service.SOURCES_FILE).read_bytes()
    created = service.create_user_source(
        {"name": "我的 RSS", "url": "https://example.test/feed.xml", "enabled": True},
        str(path),
    )
    assert created["origin"] == "user"
    assert created["source_type"] == "rss"
    assert created["has_real_rank"] is False
    # 新进程等价：全新连接从磁盘读回（store 每次调用均新开连接）
    again = store.get_source(created["source_id"], path)
    assert again is not None and again["origin"] == "user"
    listing = service.sources_list(str(path))
    ids = {s["source_id"] for s in listing["sources"]}
    assert created["source_id"] in ids
    # news_sources.json 保持不变（配置不回退到代码文件）
    assert Path(service.SOURCES_FILE).read_bytes() == seed_file_before


def test_system_source_toggle_gates_fetch(tmp_path: Path) -> None:
    path = tmp_path / "native-intel.sqlite3"
    fetcher = _RoundFetcher([[("A", 3)], [("A", 1)]])

    def rss_stub(source, **_kwargs):
        return [], None, None

    # 首轮抓取：fixture 源入库（upsert 默认 origin=system）
    service.run_fetch(
        "test",
        str(path),
        registry=_registry(),
        sources_override=[_hot_source(), _rss_source()],
        hotlist_fetcher=fetcher,
        fetcher=rss_stub,
    )
    assert store.get_source("hotlist-fixture", str(path))["origin"] == "system"

    # 停用 → 抓取清单不含该源（热榜 fetcher 不被调用）
    service.update_source("hotlist-fixture", {"enabled": False}, str(path))
    called: list[str] = []

    def spy_hotlist(source, *, timeout, redline, **_kwargs):
        called.append(source["source_id"])
        return [], None, None

    outcome = service.run_fetch(
        "test", str(path), registry=_registry(), hotlist_fetcher=spy_hotlist, fetcher=rss_stub
    )
    assert called == []
    assert outcome["source_total"] == 1  # 仅剩 RSS 源

    # 恢复启用 → 重新抓取
    service.update_source("hotlist-fixture", {"enabled": True}, str(path))
    outcome = service.run_fetch(
        "test", str(path), registry=_registry(), hotlist_fetcher=fetcher, fetcher=rss_stub
    )
    assert outcome["item_seen"] == 1
    board = service.hotlist_board(str(path))
    assert _item_by_title(board, "A")["rank"] == 1


def test_user_source_deletable_system_source_blocked(tmp_path: Path) -> None:
    path = tmp_path / "native-intel.sqlite3"
    store.initialize_store(path)
    created = service.create_user_source(
        {"name": "临时 RSS", "url": "https://example.test/tmp.xml"}, str(path)
    )
    deleted = service.delete_source(created["source_id"], str(path))
    assert deleted["source_id"] == created["source_id"]
    assert store.get_source(created["source_id"], path) is None

    service.sync_registry(str(path))
    try:
        service.delete_source("hotlist-cls-hot", str(path))
        raise AssertionError("system source delete must be blocked")
    except store.SystemSourceDeleteBlocked:
        pass
    assert store.get_source("hotlist-cls-hot", path) is not None


# ---------------------------------------------------------------------------
# Test 9/10 — StockData / Watchlist 自动受益（同一 entity mapping / context 链）
# ---------------------------------------------------------------------------


def _seed_entity_world(path: Path, monkeypatch) -> None:
    store.upsert_security_directory(
        [{"code": "600519", "name": "贵州茅台", "industry": "白酒"}], path
    )
    store.set_meta("directory_synced_at", service.utc_now_iso(), path)
    monkeypatch.setattr(astock, "individual_info", lambda _code: {})
    monkeypatch.setattr(astock, "concept_blocks", lambda _code, strict=True: {"boards": []})
    monkeypatch.setattr(astock, "hot_concepts", lambda _code, strict=True: [])
    service.ensure_security_terms("600519", str(path), force=True)


def test_hotlist_item_reaches_security_context(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "native-intel.sqlite3"
    _seed_entity_world(path, monkeypatch)
    fetcher = _RoundFetcher([[("贵州茅台获大额买入", 3)]])
    result = service.run_fetch(
        "test",
        str(path),
        registry=_registry(),
        sources_override=[_hot_source()],
        hotlist_fetcher=fetcher,
    )
    assert result["item_new"] == 1
    context = service.security_context("600519", str(path))
    titles = [row["title"] for row in context["observation"]["items"]]
    assert "贵州茅台获大额买入" in titles
    # 热榜条目带真实排名进入 context
    matched = [row for row in context["observation"]["items"] if row["title"] == "贵州茅台获大额买入"][0]
    assert matched["rank"] == 3


def test_hotlist_item_reaches_watchlist_context(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "native-intel.sqlite3"
    _seed_entity_world(path, monkeypatch)
    fetcher = _RoundFetcher([[("贵州茅台股东大会召开", 5)]])
    service.run_fetch(
        "test",
        str(path),
        registry=_registry(),
        sources_override=[_hot_source()],
        hotlist_fetcher=fetcher,
    )
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DB", str(path))
    import watchlist_store

    monkeypatch.setattr(
        watchlist_store,
        "get_watchlist_status",
        lambda: {"status": "valid", "data": {"codes": ["600519"]}},
    )
    context = service.watchlist_context(str(path))
    securities = {s["code"]: s for s in context["securities"]}
    assert "600519" in securities
    titles = [row["title"] for row in securities["600519"]["items"]]
    assert "贵州茅台股东大会召开" in titles


# ---------------------------------------------------------------------------
# provider 单元行为：contract 校验 / 域名白名单 / 红线过滤 / published_at 不伪造
# ---------------------------------------------------------------------------


def test_hotlist_provider_unit_behaviour(monkeypatch) -> None:
    source = _hot_source()

    def fake_http(url: str, *, timeout: int) -> dict:
        assert "id=cls-hot" in url
        return {
            "status": "success",
            "items": [
                {"title": "正常头条", "url": "https://www.cls.cn/detail/1"},
                {"title": "比特币暴涨", "url": "https://www.cls.cn/detail/2"},  # 红线词
                {"title": "第二头条", "url": "http://www.cls.cn/detail/3"},  # 非 HTTPS
                {"title": "外站劫持", "url": "https://evil.example.com/x"},  # 域名违例
            ],
        }

    monkeypatch.setattr(hotlist, "_http_get_json", fake_http)
    items, kind, detail = hotlist.fetch_hotlist_items(
        source, timeout=5, redline=["比特币"]
    )
    # 域名违例 → 整平台丢弃（源失败语义，不当空榜）
    assert items == [] and kind == store.ERROR_KIND_HTTP and detail == "HotlistDomainViolation"

    monkeypatch.setattr(
        hotlist,
        "_http_get_json",
        lambda url, *, timeout: {
            "status": "cache",
            "items": [
                {"title": "正常头条", "url": "https://www.cls.cn/detail/1"},
                {"title": "异常：无链接条目"},
            ],
        },
    )
    items, kind, detail = hotlist.fetch_hotlist_items(source, timeout=5, redline=[])
    assert kind is None
    # 无 URL 条目保留（rank 是热榜的核心事实），item_key 回退标题归一
    assert len(items) == 2
    assert items[0]["rank"] == 1 and items[0]["url"]
    assert items[1]["rank"] == 2 and items[1]["item_key"].startswith("title:")
    assert items[0]["published_at"] is None  # 绝不伪造发布时间

    # 未知平台 fail closed
    unknown = {**source, "url": hotlist.build_source_url("weibo")}
    items, kind, detail = hotlist.fetch_hotlist_items(unknown, timeout=5, redline=[])
    assert items == [] and kind == store.ERROR_KIND_PARSE

    # status 异常拒绝
    monkeypatch.setattr(
        hotlist, "_http_get_json", lambda url, *, timeout: {"status": "weird", "items": []}
    )
    items, kind, detail = hotlist.fetch_hotlist_items(source, timeout=5, redline=[])
    assert items == [] and kind == store.ERROR_KIND_PARSE and detail == "HotlistStatusRejected"


def test_rank_history_api_routes(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "native-intel.sqlite3"
    fetcher = _RoundFetcher([[("A", 3), ("B", 8)], [("A", 1)]])
    service.run_fetch(
        "test",
        str(path),
        registry=_registry(),
        sources_override=[_hot_source()],
        hotlist_fetcher=fetcher,
    )
    service.run_fetch(
        "test",
        str(path),
        registry=_registry(),
        sources_override=[_hot_source()],
        hotlist_fetcher=fetcher,
    )
    board = service.hotlist_board(str(path))
    app = FastAPI()
    app.include_router(native_intel_router.router)
    client = TestClient(app)
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DB", str(path))

    a = _item_by_title(board, "A")
    resp = client.get(f"/api/native-intel/items/{a['item_id']}/rank-history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_state"] == "ON_LIST"
    assert body["rank_delta"] == 2
    assert [o["rank"] for o in body["observations"]] == [3, 1]

    # 不存在的条目 404
    assert client.get("/api/native-intel/items/999999/rank-history").status_code == 404
    # 来源管理 API：列表 + 系统源删除 409
    sources = client.get("/api/native-intel/sources").json()
    assert any(s["origin"] == "user" or s["origin"] == "system" for s in sources["sources"])
    resp = client.delete("/api/native-intel/sources/hotlist-fixture")
    assert resp.status_code == 409
    assert resp.json()["detail"]["status"] == "SYSTEM_SOURCE_DELETE_BLOCKED"
    # POST 非法输入 422
    assert client.post("/api/native-intel/sources", json={"name": "", "url": "x"}).status_code == 422
    ok = client.post(
        "/api/native-intel/sources",
        json={"name": "API RSS", "url": "https://example.test/api.xml"},
    )
    assert ok.status_code == 200
    assert ok.json()["data"]["origin"] == "user"
    dup = client.post(
        "/api/native-intel/sources",
        json={"name": "API RSS", "url": "https://example.test/api.xml"},
    )
    assert dup.status_code == 409
