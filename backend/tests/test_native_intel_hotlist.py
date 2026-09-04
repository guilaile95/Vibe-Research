"""TREND-PARITY Wave 1：热榜抓取 / 真实排名轨迹 / 掉榜与失败语义 / 来源管理。

测试只服务本轮验收（任务书 Test 1-10），不追覆盖率：
- 热榜来源走注入的 ``hotlist_fetcher``，RSS 走注入的 ``fetcher``，零网络；
- 掉榜 = 最近一次来源级 run 成功 + 条目曾存在 + 未出现在榜；
- 来源失败 = UNKNOWN，绝不当作掉榜；rank 永远不写 0 / 999。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    assert items[1]["rank"] == 2 and items[1]["item_key"].startswith("hotlist-fixture:title:")
    assert items[0]["published_at"] is None  # 绝不伪造发布时间

    # 未知平台 fail closed
    unknown = {**source, "url": hotlist.build_source_url("unsupported-platform-xyz")}
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


def test_cross_source_same_item_rank_isolation(tmp_path: Path) -> None:
    """A. P0 — 同一新闻在财联社与华尔街见闻同时出现，排名轨迹必须严格按平台隔离。

    Round 1: CLS rank=3, WSCN rank=10
    Round 2: CLS rank=1, WSCN rank=7
    证明：
    - CLS history = [3, 1], delta = +2
    - WSCN history = [10, 7], delta = +3
    - 同一 canonical_url 形成两个独立 hotlist item
    - CLS source_id 永远不会读取 WSCN rank，反之亦然。
    """
    path = tmp_path / "native-intel.sqlite3"
    cls_src = {
        "source_id": "hotlist-cls-hot",
        "name": "财联社热门",
        "hint": "macro",
        "url": hotlist.build_source_url("cls-hot"),
        "source_type": "hotlist",
        "has_real_rank": True,
    }
    wscn_src = {
        "source_id": "hotlist-wallstreetcn-hot",
        "name": "华尔街见闻",
        "hint": "macro",
        "url": hotlist.build_source_url("wallstreetcn-hot"),
        "source_type": "hotlist",
        "has_real_rank": True,
    }
    canonical_shared_url = "https://example.com/breaking-news-x"
    news_title = "新闻 X"

    class MultiSourceRoundFetcher:
        def __init__(self):
            self.round = 1

        def __call__(self, source, *, timeout, redline, **_kwargs):
            src_id = source["source_id"]
            if self.round == 1:
                rank = 3 if src_id == "hotlist-cls-hot" else 10
            else:
                rank = 1 if src_id == "hotlist-cls-hot" else 7
            return [
                {
                    "item_key": f"{src_id}:{canonical_shared_url}",
                    "canonical_url": canonical_shared_url,
                    "url": canonical_shared_url,
                    "title": news_title,
                    "title_key": news_title,
                    "summary": "",
                    "hint": "macro",
                    "published_at": None,
                    "published_ts": 0,
                    "rank": rank,
                }
            ], None, None

    fetcher = MultiSourceRoundFetcher()
    reg = {
        "sources": [cls_src, wscn_src],
        "registry_version": "multi-test",
        "redline": [],
        "recent_days": 7,
        "per_source": 6,
    }

    # Round 1
    fetcher.round = 1
    service.run_fetch(
        "test", str(path), registry=reg, sources_override=[cls_src, wscn_src], hotlist_fetcher=fetcher
    )
    board1 = service.hotlist_board(str(path))
    cls_item_1 = next(it for it in board1["items"] if it["source_id"] == "hotlist-cls-hot")
    wscn_item_1 = next(it for it in board1["items"] if it["source_id"] == "hotlist-wallstreetcn-hot")
    assert cls_item_1["item_id"] != wscn_item_1["item_id"]
    assert cls_item_1["canonical_url"] == wscn_item_1["canonical_url"] == canonical_shared_url
    assert cls_item_1["rank"] == 3
    assert wscn_item_1["rank"] == 10

    # Round 2
    fetcher.round = 2
    service.run_fetch(
        "test", str(path), registry=reg, sources_override=[cls_src, wscn_src], hotlist_fetcher=fetcher
    )

    # 验证 CLS
    cls_history = service.item_rank_history(cls_item_1["item_id"], str(path))
    assert cls_history is not None
    assert cls_history["source_id"] == "hotlist-cls-hot"
    assert [o["rank"] for o in cls_history["observations"]] == [3, 1]
    assert cls_history["current_rank"] == 1
    assert cls_history["previous_rank"] == 3
    assert cls_history["rank_delta"] == 2  # 3 - 1 = +2

    # 验证 WSCN
    wscn_history = service.item_rank_history(wscn_item_1["item_id"], str(path))
    assert wscn_history is not None
    assert wscn_history["source_id"] == "hotlist-wallstreetcn-hot"
    assert [o["rank"] for o in wscn_history["observations"]] == [10, 7]
    assert wscn_history["current_rank"] == 7
    assert wscn_history["previous_rank"] == 10
    assert wscn_history["rank_delta"] == 3  # 10 - 7 = +3

    # CLS 绝对不包含 WSCN 的排名点，反之亦然
    assert 10 not in [o["rank"] for o in cls_history["observations"]]
    assert 7 not in [o["rank"] for o in cls_history["observations"]]
    assert 3 not in [o["rank"] for o in wscn_history["observations"]]
    assert 1 not in [o["rank"] for o in wscn_history["observations"]]


def test_disabled_source_state_and_reenable(tmp_path: Path) -> None:
    """B. 停用来源显式降级为 DISABLED；重启用在完成新抓取前不得直接伪造 ON_LIST。"""
    path = tmp_path / "native-intel.sqlite3"
    fetcher = _RoundFetcher([[("新闻 A", 3)], [("新闻 A", 1)]])
    service.run_fetch(
        "test",
        str(path),
        registry=_registry(),
        sources_override=[_hot_source()],
        hotlist_fetcher=fetcher,
    )
    board = service.hotlist_board(str(path))
    item = _item_by_title(board, "新闻 A")
    assert item["current_state"] == store.ITEM_STATE_ON_LIST
    assert item["rank"] == 3

    # 停用来源
    service.update_source("hotlist-fixture", {"enabled": False}, str(path))
    state_disabled = store.get_item_rank_state(item["item_id"], path)
    assert state_disabled["current_state"] == store.ITEM_STATE_DISABLED
    # 保留末次真实排名供审计
    assert state_disabled["current_rank"] == 3
    assert state_disabled["current_state"] != store.ITEM_STATE_ON_LIST
    assert state_disabled["current_state"] != store.ITEM_STATE_OFF_LIST

    # 重新启用来源（尚未触发新抓取）
    service.update_source("hotlist-fixture", {"enabled": True}, str(path))
    state_re_enabled = store.get_item_rank_state(item["item_id"], path)
    # 不得直接根据旧 run 恢复成实时 ON_LIST，必须保持 UNKNOWN
    assert state_re_enabled["current_state"] == store.ITEM_STATE_UNKNOWN
    assert state_re_enabled["current_state"] != store.ITEM_STATE_ON_LIST

    # 执行新一轮抓取
    service.run_fetch(
        "test",
        str(path),
        registry=_registry(),
        sources_override=[_hot_source()],
        hotlist_fetcher=fetcher,
    )
    state_after_run = store.get_item_rank_state(item["item_id"], path)
    assert state_after_run["current_state"] == store.ITEM_STATE_ON_LIST
    assert state_after_run["current_rank"] == 1
    assert state_after_run["previous_rank"] == 3
    assert state_after_run["rank_delta"] == 2


def test_user_source_uuid_chinese_collision_soft_delete(tmp_path: Path) -> None:
    """E. 中文名称 source_id 不冲突 + 软删除保留历史 provenance。"""
    path = tmp_path / "native-intel.sqlite3"
    store.initialize_store(path)

    # 1. 创建两个中文名称 user RSS
    src_a = service.create_user_source(
        {"name": "半导体观察", "url": "https://example.test/semi.xml", "hint": "tech"},
        str(path),
    )
    src_b = service.create_user_source(
        {"name": "液冷情报", "url": "https://example.test/liquid.xml", "hint": "tech"},
        str(path),
    )

    # 2. source_id 解耦为 UUID，不冲突且不退化为 user-src
    assert src_a["source_id"].startswith("user-rss-")
    assert src_b["source_id"].startswith("user-rss-")
    assert src_a["source_id"] != src_b["source_id"]
    assert src_a["source_id"] != "user-src"
    assert src_b["source_id"] != "user-src"

    # 3. 在 A 下写入历史条目与观测
    store.start_run("run-a-1", "test", 1, path)
    item_id, is_new = store.upsert_observation(
        "run-a-1",
        src_a["source_id"],
        {
            "item_key": "https://example.test/semi/101",
            "canonical_url": "https://example.test/semi/101",
            "url": "https://example.test/semi/101",
            "title": "半导体最新动态",
            "title_key": "半导体最新动态",
            "summary": "半导体产业链技术突破。",
            "hint": "tech",
            "published_at": None,
            "published_ts": 0,
            "rank": None,
        },
        observed_at=store.utc_now_iso(),
        has_real_rank=False,
        db_path=path,
    )
    store.finish_run(
        "run-a-1",
        status=store.RUN_STATUS_OK,
        source_ok=1,
        source_failed=0,
        item_seen=1,
        item_new=1,
        db_path=path,
    )

    # 4. 删除 A
    deleted = service.delete_source(src_a["source_id"], str(path))
    assert deleted["source_id"] == src_a["source_id"]

    # 5. A 不再参与 fetch (enabled_only=True)
    fetch_sources = store.list_sources(path, enabled_only=True)
    assert src_a["source_id"] not in {s["source_id"] for s in fetch_sources}

    # 6. active source list 不再出现 A
    active_sources = service.sources_list(str(path))
    assert src_a["source_id"] not in {s["source_id"] for s in active_sources["sources"]}

    # 7. A 历史 item 仍能读取原 source_name / source_type provenance
    item_state = store.get_item_rank_state(item_id, path)
    assert item_state["source_name"] == "半导体观察"
    assert item_state["source_type"] == "rss"
    assert item_state["current_state"] == store.ITEM_STATE_DISABLED

    # 8. B 完全不受影响
    b_source = store.get_source(src_b["source_id"], path)
    assert b_source is not None
    assert b_source["name"] == "液冷情报"
    assert b_source["enabled"] == 1
    assert src_b["source_id"] in {s["source_id"] for s in service.sources_list(str(path))["sources"]}

    # 9. 系统源删除仍然 409
    service.sync_registry(str(path))
    try:
        service.delete_source("hotlist-cls-hot", str(path))
        raise AssertionError("系统源删除必须被阻止")
    except store.SystemSourceDeleteBlocked:
        pass


def test_stale_source_state_and_rank_honesty(tmp_path: Path) -> None:
    """过期数据诚实性验证：超过 STALE_AFTER_HOURS 的数据降级为 STALE，绝不伪装为当前 ON_LIST。

    1. 抓取时间超过 6 小时：get_item_rank_state 返回 current_state=STALE，保留末次已知 rank 供审计；
    2. hotlist_board 整体 status 同步反映为 stale；
    3. 新一轮成功抓取完成后，状态恢复为实时 ON_LIST，rank_delta 连续推导。
    """
    path = tmp_path / "intel_stale.sqlite3"
    cls_src = {
        "source_id": "hotlist-cls-hot",
        "name": "财联社热门",
        "hint": "macro",
        "url": "https://newsnow.busiyi.world/api/s?id=cls-hot&latest",
        "source_type": "hotlist",
        "has_real_rank": True,
        "origin": "system",
    }
    store.upsert_sources([cls_src], path)

    # 1. 模拟 7 小时前的过期抓取
    old_time = (datetime.now(timezone.utc) - timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.start_run("stale-run-1", "fixture", 1, path, started_at=old_time)
    item_id, is_new = store.upsert_observation(
        "stale-run-1",
        "hotlist-cls-hot",
        {
            "item_key": "hotlist-cls-hot:https://www.cls.cn/detail/999",
            "canonical_url": "https://www.cls.cn/detail/999",
            "url": "https://www.cls.cn/detail/999",
            "title": "早期宏观数据发布",
            "title_key": "早期宏观数据发布",
            "summary": "7 小时前的历史热点",
            "hint": "macro",
            "published_at": None,
            "published_ts": 0,
            "rank": 3,
        },
        observed_at=old_time,
        has_real_rank=True,
        db_path=path,
    )
    assert is_new is True
    store.record_source_run("stale-run-1", "hotlist-cls-hot", status=store.SOURCE_RUN_OK, item_count=1, db_path=path)
    store.finish_run("stale-run-1", status=store.RUN_STATUS_OK, source_ok=1, source_failed=0, item_seen=1, item_new=1, db_path=path)

    # 2. 读取单条状态：必须为 STALE，绝不得返回 ON_LIST
    stale_state = store.get_item_rank_state(item_id, path)
    assert stale_state["current_state"] == store.ITEM_STATE_STALE
    assert stale_state["current_state"] != store.ITEM_STATE_ON_LIST
    assert stale_state["current_state"] != store.ITEM_STATE_OFF_LIST
    # 历史末次 rank 保留供审计与展示
    assert stale_state["current_rank"] == 3

    # 3. 读取热榜看板：看板整体状态为 stale，条目 current_state 为 STALE
    board = service.hotlist_board(str(path))
    assert board["status"] == "stale"
    assert len(board["items"]) == 1
    assert board["items"][0]["current_state"] == "STALE"
    assert board["items"][0]["rank"] == 3

    # 4. 新一轮成功抓取完成（新鲜数据）
    fresh_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.start_run("fresh-run-2", "fixture", 1, path, started_at=fresh_time)
    store.upsert_observation(
        "fresh-run-2",
        "hotlist-cls-hot",
        {
            "item_key": "hotlist-cls-hot:https://www.cls.cn/detail/999",
            "canonical_url": "https://www.cls.cn/detail/999",
            "url": "https://www.cls.cn/detail/999",
            "title": "早期宏观数据发布",
            "title_key": "早期宏观数据发布",
            "summary": "7 小时前的历史热点",
            "hint": "macro",
            "published_at": None,
            "published_ts": 0,
            "rank": 1,
        },
        observed_at=fresh_time,
        has_real_rank=True,
        db_path=path,
    )
    store.record_source_run("fresh-run-2", "hotlist-cls-hot", status=store.SOURCE_RUN_OK, item_count=1, db_path=path)
    store.finish_run("fresh-run-2", status=store.RUN_STATUS_OK, source_ok=1, source_failed=0, item_seen=1, item_new=0, db_path=path)

    # 5. 重新读取：恢复为当前实时在榜 ON_LIST，delta 正常推导
    fresh_state = store.get_item_rank_state(item_id, path)
    assert fresh_state["current_state"] == store.ITEM_STATE_ON_LIST
    assert fresh_state["current_rank"] == 1
    assert fresh_state["previous_rank"] == 3
    assert fresh_state["rank_delta"] == 2

    fresh_board = service.hotlist_board(str(path))
    assert fresh_board["status"] == "normal"
    assert fresh_board["items"][0]["current_state"] == "ON_LIST"
    assert fresh_board["items"][0]["rank"] == 1


# ===========================================================================
# Wave 1B: 11 平台全量覆盖对齐测试集
# ===========================================================================

EXPECTED_11_PLATFORMS = [
    ("cls-hot", "财联社热门", "cls.cn"),
    ("wallstreetcn-hot", "华尔街见闻", "wallstreetcn.com"),
    ("toutiao", "今日头条", "toutiao.com"),
    ("baidu", "百度热搜", "baidu.com"),
    ("thepaper", "澎湃新闻", "thepaper.cn"),
    ("bilibili-hot-search", "Bilibili 热搜", "bilibili.com"),
    ("ifeng", "凤凰网", "ifeng.com"),
    ("tieba", "贴吧", "baidu.com"),
    ("weibo", "微博", "weibo.com"),
    ("douyin", "抖音", "douyin.com"),
    ("zhihu", "知乎", "zhihu.com"),
]


def test_system_registry_has_all_11_hotlists() -> None:
    """A. Registry Test: 断言系统默认共有 11 个 hotlist sources 并逐一核对元数据。"""
    reg = service.load_registry()
    hotlists = [s for s in reg["sources"] if s["source_type"] == "hotlist"]
    assert len(hotlists) == 11, f"Expected 11 hotlist sources, got {len(hotlists)}"

    by_platform = {
        hotlist.platform_of(s["url"]): s
        for s in hotlists
    }

    for platform, name, domain in EXPECTED_11_PLATFORMS:
        assert platform in by_platform, f"Platform {platform} missing from registry"
        src = by_platform[platform]
        assert src["source_id"] == f"hotlist-{platform}"
        assert src["name"] == name
        assert src["source_type"] == "hotlist"
        assert src["has_real_rank"] is True
        assert hotlist._PROVIDERS[platform] == domain
        assert src["url"] == hotlist.build_source_url(platform)


def test_all_11_providers_contract_fixtures(monkeypatch) -> None:
    """B. Provider Contract Fixtures: 对 11 个平台全部验证契约归一化、1-based 排名与 source-qualified item_key。"""
    for platform, name, domain in EXPECTED_11_PLATFORMS:
        source = {
            "source_id": f"hotlist-{platform}",
            "name": name,
            "url": hotlist.build_source_url(platform),
            "source_type": "hotlist",
            "has_real_rank": True,
        }
        monkeypatch.setattr(
            hotlist,
            "_http_get_json",
            lambda url, *, timeout, d=domain: {
                "status": "success",
                "items": [
                    {"title": f"{platform} 头条新闻", "url": f"https://www.{d}/item/1"},
                    {"title": f"{platform} 第二热点", "url": f"https://sub.{d}/item/2"},
                ],
            },
        )
        items, kind, detail = hotlist.fetch_hotlist_items(source, timeout=5, redline=[])
        assert kind is None, f"{platform} fetch failed: {kind} {detail}"
        assert len(items) == 2
        assert items[0]["rank"] == 1
        assert items[1]["rank"] == 2
        assert items[0]["item_key"].startswith(f"hotlist-{platform}:")
        assert items[1]["item_key"].startswith(f"hotlist-{platform}:")
        assert items[0]["published_at"] is None  # 绝不伪造发布时间
        assert items[1]["published_at"] is None


def test_all_11_providers_domain_fail_closed(monkeypatch) -> None:
    """C. Domain Fail-Closed: 11 个平台遭遇域名违例（如被篡改为劫持地址），必须整源报错，绝不写入 observation。"""
    for platform, name, domain in EXPECTED_11_PLATFORMS:
        source = {
            "source_id": f"hotlist-{platform}",
            "name": name,
            "url": hotlist.build_source_url(platform),
            "source_type": "hotlist",
            "has_real_rank": True,
        }
        monkeypatch.setattr(
            hotlist,
            "_http_get_json",
            lambda url, *, timeout: {
                "status": "success",
                "items": [
                    {"title": "可疑链接", "url": "https://evil.example.com/phishing"},
                ],
            },
        )
        items, kind, detail = hotlist.fetch_hotlist_items(source, timeout=5, redline=[])
        assert items == []
        assert kind == store.ERROR_KIND_HTTP
        assert detail == "HotlistDomainViolation"


def test_11_sources_mixed_run_isolation(tmp_path: Path) -> None:
    """D. 11-source mixed run: 模拟 10 个成功、1 个失败，整体为 PARTIAL，失败源 UNKNOWN，成功源不受影响。"""
    path = tmp_path / "native-intel.sqlite3"
    reg = service.load_registry()
    hotlists = [s for s in reg["sources"] if s["source_type"] == "hotlist"]
    assert len(hotlists) == 11

    # 模拟 fetcher：weibo 抛异常失败，其余 10 个成功返回 1 条数据
    def mock_fetcher(source, **kwargs):
        sid = source.get("source_id")
        if sid == "hotlist-weibo":
            return [], store.ERROR_KIND_NETWORK, "ConnectionResetError"
        platform = hotlist.platform_of(source.get("url"))
        domain = hotlist._PROVIDERS.get(platform, "example.com")
        return [
            {
                "source_id": sid,
                "item_key": f"{sid}:https://{domain}/item1",
                "title": f"{source.get('name')} 头条",
                "url": f"https://{domain}/item1",
                "canonical_url": f"https://{domain}/item1",
                "title_key": f"{source.get('name')} 头条",
                "summary": "",
                "hint": "macro",
                "published_at": None,
                "published_ts": 0,
                "rank": 1,
            }
        ], None, None

    result = service.run_fetch(
        "mixed-11-run",
        str(path),
        registry=reg,
        sources_override=hotlists,
        hotlist_fetcher=mock_fetcher,
    )

    assert result["status"] == store.RUN_STATUS_PARTIAL
    assert result["source_ok"] == 10
    assert result["source_failed"] == 1
    assert result["item_seen"] == 10

    board = service.hotlist_board(str(path))
    assert board["status"] == "partial"
    # 成功源条目均为 ON_LIST
    assert len(board["items"]) == 10
    for it in board["items"]:
        assert it["current_state"] == "ON_LIST"
        assert it["rank"] == 1
        assert it["source_id"] != "hotlist-weibo"


def test_disabled_persistence_across_sync_registry(tmp_path: Path) -> None:
    """E. Disabled persistence: 用户停用系统源（如 hotlist-weibo），sync_registry 绝不重新开启。"""
    path = tmp_path / "native-intel.sqlite3"
    reg = service.load_registry()
    hotlists = [s for s in reg["sources"] if s["source_type"] == "hotlist"]

    # 1. 首次入库
    store.upsert_sources(hotlists, path)
    weibo = store.get_source("hotlist-weibo", path)
    assert weibo is not None
    assert weibo["enabled"] == 1

    # 2. 用户手动停用
    store.update_source("hotlist-weibo", enabled=False, db_path=path)
    weibo_disabled = store.get_source("hotlist-weibo", path)
    assert weibo_disabled["enabled"] == 0

    # 3. 再次执行系统 sync_registry（通过 upsert_sources）
    store.upsert_sources(hotlists, path)
    weibo_after_sync = store.get_source("hotlist-weibo", path)
    # enabled 状态必须坚守为 0，不能被 seed 覆盖
    assert weibo_after_sync["enabled"] == 0

    # 4. 同时验证用户自建源 soft-deleted 也不受系统源同步影响
    custom_src = service.create_user_source(
        {"name": "我的自建源", "url": "https://custom.test/rss.xml", "hint": "macro"},
        str(path),
    )
    service.delete_source(custom_src["source_id"], str(path))
    assert store.get_source(custom_src["source_id"], path) is None
    deleted_src = store.get_source(custom_src["source_id"], path, include_deleted=True)
    assert deleted_src is not None
    assert deleted_src["deleted_at"] is not None

    store.upsert_sources(hotlists, path)
    assert store.get_source(custom_src["source_id"], path) is None
    deleted_again = store.get_source(custom_src["source_id"], path, include_deleted=True)
    assert deleted_again is not None
    assert deleted_again["deleted_at"] is not None


def test_cross_source_rank_isolation_three_new_platforms(tmp_path: Path) -> None:
    """F. Cross-source rank isolation: weibo, zhihu, baidu 共享同一条新闻 URL，必须生成 3 个独立 rank history。"""
    path = tmp_path / "native-intel.sqlite3"
    same_url = "https://news.example.com/major-breaking-event-2026"
    title = "重要科技突发事件全网热议"

    wb_src = {"source_id": "hotlist-weibo", "name": "微博", "hint": "macro", "url": hotlist.build_source_url("weibo"), "source_type": "hotlist", "has_real_rank": True}
    zh_src = {"source_id": "hotlist-zhihu", "name": "知乎", "hint": "macro", "url": hotlist.build_source_url("zhihu"), "source_type": "hotlist", "has_real_rank": True}
    bd_src = {"source_id": "hotlist-baidu", "name": "百度热搜", "hint": "macro", "url": hotlist.build_source_url("baidu"), "source_type": "hotlist", "has_real_rank": True}

    def make_item(src_id: str, rank: int) -> dict:
        return {
            "source_id": src_id,
            "item_key": f"{src_id}:{same_url}",
            "title": title,
            "url": same_url,
            "canonical_url": same_url,
            "title_key": title,
            "summary": "",
            "hint": "macro",
            "published_at": None,
            "published_ts": 0,
            "rank": rank,
        }

    test_reg = {
        "sources": [wb_src, zh_src, bd_src],
        "registry_version": "three-iso",
        "redline": [],
        "recent_days": 7,
        "per_source": 6,
    }

    # Round 1: weibo #2, zhihu #7, baidu #4
    r1_items = {
        "hotlist-weibo": [make_item("hotlist-weibo", 2)],
        "hotlist-zhihu": [make_item("hotlist-zhihu", 7)],
        "hotlist-baidu": [make_item("hotlist-baidu", 4)],
    }
    service.run_fetch(
        "iso-run-1",
        str(path),
        registry=test_reg,
        sources_override=[wb_src, zh_src, bd_src],
        hotlist_fetcher=lambda src, **kw: (r1_items[src["source_id"]], None, None),
    )

    # Round 2: weibo #1 (delta +1), zhihu #5 (delta +2), baidu #9 (delta -5)
    r2_items = {
        "hotlist-weibo": [make_item("hotlist-weibo", 1)],
        "hotlist-zhihu": [make_item("hotlist-zhihu", 5)],
        "hotlist-baidu": [make_item("hotlist-baidu", 9)],
    }
    service.run_fetch(
        "iso-run-2",
        str(path),
        registry=test_reg,
        sources_override=[wb_src, zh_src, bd_src],
        hotlist_fetcher=lambda src, **kw: (r2_items[src["source_id"]], None, None),
    )

    board = service.hotlist_board(str(path))
    assert len(board["items"]) == 3

    wb_item = next(it for it in board["items"] if it["source_id"] == "hotlist-weibo")
    zh_item = next(it for it in board["items"] if it["source_id"] == "hotlist-zhihu")
    bd_item = next(it for it in board["items"] if it["source_id"] == "hotlist-baidu")

    # 验证三个平台虽然 canonical_url 相同，但 item_id 完全独立
    assert len({wb_item["item_id"], zh_item["item_id"], bd_item["item_id"]}) == 3

    # 验证各平台排名轨迹完全隔离
    wb_hist = service.item_rank_history(wb_item["item_id"], str(path))
    assert [o["rank"] for o in wb_hist["observations"]] == [2, 1]
    assert wb_hist["current_rank"] == 1
    assert wb_hist["rank_delta"] == 1

    zh_hist = service.item_rank_history(zh_item["item_id"], str(path))
    assert [o["rank"] for o in zh_hist["observations"]] == [7, 5]
    assert zh_hist["current_rank"] == 5
    assert zh_hist["rank_delta"] == 2

    bd_hist = service.item_rank_history(bd_item["item_id"], str(path))
    assert [o["rank"] for o in bd_hist["observations"]] == [4, 9]
    assert bd_hist["current_rank"] == 9
    assert bd_hist["rank_delta"] == -5


def test_a_share_entity_mapping_shared_across_new_hotlists(tmp_path: Path, monkeypatch) -> None:
    """L. A 股实体映射验证：新增热榜条目自然进入统一 entity 映射 pipeline。"""
    path = tmp_path / "native-intel.sqlite3"
    _seed_entity_world(path, monkeypatch)

    wb_src = {"source_id": "hotlist-weibo", "name": "微博", "hint": "macro", "url": hotlist.build_source_url("weibo"), "source_type": "hotlist", "has_real_rank": True}

    item = {
        "source_id": "hotlist-weibo",
        "item_key": "hotlist-weibo:https://weibo.com/maotai-1",
        "title": "贵州茅台今日发布业绩超预期公告",
        "url": "https://weibo.com/maotai-1",
        "canonical_url": "https://weibo.com/maotai-1",
        "title_key": "贵州茅台今日发布业绩超预期公告",
        "summary": "茅台业绩大幅增长",
        "hint": "macro",
        "published_at": None,
        "published_ts": 0,
        "rank": 1,
    }

    test_reg = {
        "sources": [wb_src],
        "registry_version": "entity-test",
        "redline": [],
        "recent_days": 7,
        "per_source": 6,
    }
    service.run_fetch(
        "entity-run",
        str(path),
        registry=test_reg,
        sources_override=[wb_src],
        hotlist_fetcher=lambda src, **kw: ([item], None, None),
    )

    ctx = service.security_context("600519", str(path))
    titles = [row["title"] for row in ctx["observation"]["items"]]
    assert "贵州茅台今日发布业绩超预期公告" in titles
    matched = next(row for row in ctx["observation"]["items"] if row["title"] == "贵州茅台今日发布业绩超预期公告")
    assert matched["source_id"] == "hotlist-weibo"
    assert matched["rank"] == 1
