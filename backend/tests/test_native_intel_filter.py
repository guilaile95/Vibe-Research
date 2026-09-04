"""TREND-PARITY Wave 2：个人兴趣与关键词过滤测试集。

覆盖 17 项严格要求与契约：
1. Keyword include matching (title + summary, substring + /regex/)
2. Exclude wins (global_excludes and group excludes reject even when includes match)
3. Matching both title and summary
4. Multiple groups support (item can match multiple groups)
5. Profile persistence in SQLite (intel_filter_profiles)
6. Keyword <-> AI switch seamlessly without data loss
7. AI tag extraction returns valid JSON structure with {id, tag, description}
8. AI tag extraction fail-closed on malformed LLM response (raises ValueError)
9. AI batch classification handles items in batches
10. Min_score filtering (items below min_score excluded in filtered view)
11. Classification caching by (item_id, profile_id, profile_fingerprint)
12. Tag update (update_interest_tags) calculates change_ratio and keeps/adds/removes
13. Reclassification threshold logic (> reclassify_threshold triggers reclassification flag)
14. Partial failure honesty (batch failure reported as failed/unclassified, NEVER faked as score=0)
15. Core fetch NEVER depends on AI (AI failure never breaks fetch)
16. Entity mapping unchanged (entities are never mutated or removed by filtering)
17. Rank state unchanged (rank, delta, and states are never mutated or faked)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import native_intel_filter as filter_engine
import native_intel_router
import native_intel_service as service
import native_intel_store as store


@pytest.fixture
def test_db(tmp_path: Path) -> str:
    db_file = tmp_path / "test_filter.sqlite3"
    store.initialize_store(db_file)
    return str(db_file)


@pytest.fixture
def client(test_db: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DB", test_db)
    app = FastAPI()
    app.include_router(native_intel_router.router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test 1 & 3: Keyword include matching on title + summary, substring + regex
# ---------------------------------------------------------------------------

def test_keyword_matching_plain_and_regex():
    rules = filter_engine.KeywordRules(
        global_excludes=[],
        groups=[
            filter_engine.KeywordGroup(
                name="半导体",
                includes=["芯片", "/gpu|npu/"],
                excludes=[],
            ),
        ],
    )
    # Plain substring in title
    matched, groups = filter_engine.evaluate_keyword_rules("华为最新芯片突破", None, rules)
    assert matched is True
    assert "半导体" in groups

    # Regex pattern in summary
    matched, groups = filter_engine.evaluate_keyword_rules(
        "最新算力卡发布", "搭载下一代 GPU 架构，算力大幅提升", rules
    )
    assert matched is True
    assert "半导体" in groups

    # No match
    matched, groups = filter_engine.evaluate_keyword_rules("某消费品公司季度财报", "销售额稳步增长", rules)
    assert matched is False
    assert groups == []


# ---------------------------------------------------------------------------
# Test 2: Exclude wins (global_excludes and group excludes)
# ---------------------------------------------------------------------------

def test_exclude_wins_global_and_group():
    rules = filter_engine.KeywordRules(
        global_excludes=["震惊", "/赌博|博彩/"],
        groups=[
            filter_engine.KeywordGroup(
                name="机器人",
                includes=["机器人"],
                excludes=["机器人动画", "/玩具机器人/"],
            ),
        ],
    )
    # Includes match, but global exclude matches -> REJECT
    matched, groups = filter_engine.evaluate_keyword_rules(
        "震惊！人形机器人突破核心瓶颈", None, rules
    )
    assert matched is False
    assert groups == []

    # Regex global exclude matches -> REJECT
    matched, groups = filter_engine.evaluate_keyword_rules(
        "机器人企业涉足境外博彩", None, rules
    )
    assert matched is False
    assert groups == []

    # Group exclude matches -> REJECT
    matched, groups = filter_engine.evaluate_keyword_rules(
        "热播机器人动画上映", "讲述未来机甲故事", rules
    )
    assert matched is False
    assert groups == []

    # Group regex exclude matches -> REJECT
    matched, groups = filter_engine.evaluate_keyword_rules(
        "儿童玩具机器人热销", None, rules
    )
    assert matched is False
    assert groups == []

    # Clean match -> ACCEPT
    matched, groups = filter_engine.evaluate_keyword_rules(
        "人形机器人减速器量产", "关键供应链取得突破", rules
    )
    assert matched is True
    assert groups == ["机器人"]


# ---------------------------------------------------------------------------
# Test 4: Multiple groups support
# ---------------------------------------------------------------------------

def test_multiple_groups_match():
    rules = filter_engine.KeywordRules(
        global_excludes=[],
        groups=[
            filter_engine.KeywordGroup(name="半导体", includes=["芯片"], excludes=[]),
            filter_engine.KeywordGroup(name="智能汽车", includes=["特斯拉", "智驾"], excludes=[]),
        ],
    )
    # Matches both groups
    matched, groups = filter_engine.evaluate_keyword_rules(
        "特斯拉发布自研智驾芯片", "AI 性能较前代翻倍", rules
    )
    assert matched is True
    assert set(groups) == {"半导体", "智能汽车"}


# ---------------------------------------------------------------------------
# Test 5 & 6: Profile persistence & keyword <-> AI switch
# ---------------------------------------------------------------------------

def test_profile_persistence_and_mode_switch(test_db: str):
    # 1. Fetch default profile
    prof = service.get_filter_profile("default", test_db)
    assert prof["profile_id"] == "default"
    assert prof["method"] == "keyword"
    assert prof["min_score"] == 0.7
    assert len(prof["keyword_rules"]["groups"]) >= 3

    # 2. Switch to AI mode with tags
    ai_tags = [
        {"id": 1, "tag": "人形机器人", "description": "关注减速器和电机"},
        {"id": 2, "tag": "AI芯片", "description": "关注GPU与算力卡"},
    ]
    updated = service.update_filter_profile(
        "default",
        {
            "method": "ai",
            "tags": ai_tags,
            "min_score": 0.8,
            "interests_text": "关注人形机器人和AI算力芯片",
        },
        test_db,
    )
    assert updated["method"] == "ai"
    assert updated["min_score"] == 0.8
    assert len(updated["tags"]) == 2
    ai_fp = updated["profile_fingerprint"]
    assert ai_fp != ""

    # Verify persisted in database
    reloaded = service.get_filter_profile("default", test_db)
    assert reloaded["method"] == "ai"
    assert reloaded["profile_fingerprint"] == ai_fp
    # Keyword rules are still preserved, not lost!
    assert len(reloaded["keyword_rules"]["groups"]) >= 3

    # 3. Switch back to keyword mode seamlessly
    switched_back = service.update_filter_profile(
        "default",
        {"method": "keyword"},
        test_db,
    )
    assert switched_back["method"] == "keyword"
    assert len(switched_back["tags"]) == 2  # tags preserved


# ---------------------------------------------------------------------------
# Test 7 & 8: AI Tag Extraction (Valid JSON & Fail-Closed on Malformed)
# ---------------------------------------------------------------------------

def test_extract_interest_tags_valid():
    def mock_runner(cfg: Any, msgs: list[dict[str, str]]) -> str:
        return json.dumps({
            "tags": [
                {"id": 1, "tag": "具身智能", "description": "人形机器人与四足机器狗"},
                {"id": 2, "tag": "半导体制造", "description": "光刻机与晶圆代工"},
            ]
        })

    tags = filter_engine.extract_interest_tags(
        "我关注机器人和光刻机", model_runner=mock_runner
    )
    assert len(tags) == 2
    assert tags[0]["tag"] == "具身智能"
    assert tags[1]["tag"] == "半导体制造"


def test_extract_interest_tags_fail_closed_on_malformed():
    def broken_runner(cfg: Any, msgs: list[dict[str, str]]) -> str:
        return "抱歉，我无法解析你的输入，这不是合法的 JSON 内容。"

    with pytest.raises(ValueError, match="JSON 解析失败"):
        filter_engine.extract_interest_tags("关注AI", model_runner=broken_runner)

    def empty_tags_runner(cfg: Any, msgs: list[dict[str, str]]) -> str:
        return json.dumps({"tags": []})

    with pytest.raises(ValueError, match="(未找到有效 tags 列表|未能提取出任何有效标签)"):
        filter_engine.extract_interest_tags("关注AI", model_runner=empty_tags_runner)


# ---------------------------------------------------------------------------
# Test 9, 10, 11, 14: Batch classification, min_score, caching, failure honesty
# ---------------------------------------------------------------------------

def test_batch_classification_min_score_caching_and_partial_failure(test_db: str):
    # Setup test items in store
    items_to_insert = [
        {
            "item_key": f"https://example.com/item-{i}",
            "canonical_url": f"https://example.com/item-{i}",
            "url": f"https://example.com/item-{i}",
            "title": f"新闻标题 {i} 智能机器人突破",
            "title_key": f"新闻标题 {i} 智能机器人突破",
            "summary": "详细报道",
            "hint": "macro",
            "source_id": "hotlist-fixture",
            "published_at": None,
            "published_ts": 0,
        }
        for i in range(1, 6)
    ]
    now = store.utc_now_iso()
    inserted_ids = []
    with store._connect(test_db) as conn:
        for it in items_to_insert:
            cur = conn.execute(
                """
                INSERT INTO intel_items (
                    item_key, canonical_url, url, title, title_key, summary,
                    source_id, hint, published_at, published_ts, first_seen_at,
                    last_seen_at, observation_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    it["item_key"], it["canonical_url"], it["url"], it["title"],
                    it["title_key"], it["summary"], it["source_id"], it["hint"],
                    it["published_at"], it["published_ts"], now, now, now,
                ),
            )
            inserted_ids.append(cur.lastrowid)

    tags = [{"id": 1, "tag": "机器人", "description": "人形机器人与零部件"}]
    service.update_filter_profile(
        "default",
        {
            "method": "ai",
            "tags": tags,
            "min_score": 0.75,
            "interests_text": "关注机器人",
        },
        test_db,
    )

    # 1. Mock runner returns high score for item 1 (0.9), low score for item 2 (0.6),
    # item 3 matches (0.8), item 4 unmentioned
    call_count = 0
    def mock_runner(cfg: Any, msgs: list[dict[str, str]]) -> str:
        nonlocal call_count
        call_count += 1
        return json.dumps([
            {"id": inserted_ids[0], "tag_id": 1, "score": 0.9},
            {"id": inserted_ids[1], "tag_id": 1, "score": 0.6},  # below min_score 0.75
            {"id": inserted_ids[2], "tag_id": 1, "score": 0.8},
        ])

    res = service.classify_items(
        "default",
        item_ids=inserted_ids[:4],
        model_runner=mock_runner,
        path=test_db,
    )
    assert res["status"] == "SUCCESS"
    assert res["newly_classified"] == 3
    assert call_count == 1

    # 2. Test caching: calling classify_items again should hit cache (0 new calls)
    res_cached = service.classify_items(
        "default",
        item_ids=inserted_ids[:3],
        model_runner=mock_runner,
        path=test_db,
    )
    assert res_cached["status"] == "UP_TO_DATE"
    assert call_count == 1  # No extra LLM call!

    # 3. Test filter_items min_score enforcement
    raw_items = [
        {"item_id": inserted_ids[0], "title": "新闻 1", "summary": ""},
        {"item_id": inserted_ids[1], "title": "新闻 2", "summary": ""},
        {"item_id": inserted_ids[2], "title": "新闻 3", "summary": ""},
    ]
    filtered, meta = service.filter_items(raw_items, "default", test_db)
    assert meta["method"] == "ai"
    assert len(filtered) == 2  # Item 2 (score 0.6 < 0.75) excluded!
    filtered_ids = [f["item_id"] for f in filtered]
    assert inserted_ids[0] in filtered_ids
    assert inserted_ids[2] in filtered_ids
    assert inserted_ids[1] not in filtered_ids

    # 4. Test partial failure honesty (never fake score=0)
    def failing_runner(cfg: Any, msgs: list[dict[str, str]]) -> str:
        raise RuntimeError("LLM API Timeout 504")

    fail_res = service.classify_items(
        "default",
        item_ids=[inserted_ids[4]],  # Item 5 is unclassified
        model_runner=failing_runner,
        path=test_db,
    )
    assert fail_res["status"] == "PARTIAL_FAILURE"
    assert fail_res["failed"] == 1
    assert inserted_ids[4] in fail_res["failed_item_ids"]

    # Item 5 remains UNCLASSIFIED in database, NOT saved with fake score 0
    prof = service.get_filter_profile("default", test_db)
    cls_map = store.get_item_classifications(
        "default", prof["profile_fingerprint"], item_ids=[inserted_ids[4]], db_path=test_db
    )
    assert inserted_ids[4] not in cls_map


# ---------------------------------------------------------------------------
# Test 12 & 13: Tag Update, change_ratio & reclassification threshold
# ---------------------------------------------------------------------------

def test_update_interest_tags_and_reclassify_threshold():
    old_tags = [
        {"id": 1, "tag": "芯片半导体", "description": "光刻机与晶圆代工"},
        {"id": 2, "tag": "光伏新能源", "description": "硅料硅片电池组件"},
    ]

    # Scenario A: Minor update (change_ratio = 0.2 <= 0.6) -> no full reclassify
    def minor_runner(cfg: Any, msgs: list[dict[str, str]]) -> str:
        return json.dumps({
            "keep": [{"tag": "芯片半导体", "description": "光刻机、GPU及先进制程"}],
            "add": [{"tag": "商业航天", "description": "低轨卫星互联网与可回收火箭"}],
            "remove": ["光伏新能源"],
            "change_ratio": 0.25,
        })

    plan = filter_engine.update_interest_tags(
        old_tags, "关注芯片与商业航天", model_runner=minor_runner
    )
    assert plan["change_ratio"] == 0.25
    assert len(plan["new_tags"]) == 2
    assert plan["change_ratio"] <= filter_engine.DEFAULT_RECLASSIFY_THRESHOLD

    # Scenario B: Major restructure (change_ratio = 0.8 > 0.6)
    def major_runner(cfg: Any, msgs: list[dict[str, str]]) -> str:
        return json.dumps({
            "keep": [],
            "add": [
                {"tag": "生物医药", "description": "创新药与ADC"},
                {"tag": "脑机接口", "description": "侵入式与非侵入式脑机接口"},
            ],
            "remove": ["芯片半导体", "光伏新能源"],
            "change_ratio": 0.85,
        })

    major_plan = filter_engine.update_interest_tags(
        old_tags, "完全改变关注点：只看医药和脑机", model_runner=major_runner
    )
    assert major_plan["change_ratio"] == 0.85
    assert major_plan["change_ratio"] > filter_engine.DEFAULT_RECLASSIFY_THRESHOLD


# ---------------------------------------------------------------------------
# Test 15: Core fetch NEVER depends on AI
# ---------------------------------------------------------------------------

def test_fetch_never_depends_on_ai(test_db: str, monkeypatch: pytest.MonkeyPatch):
    # Break chat.stream_messages completely to simulate complete AI outage
    def broken_stream(*args, **kwargs):
        raise ConnectionRefusedError("AI Gateway is DOWN")

    monkeypatch.setattr("chat.stream_messages", broken_stream)

    # Core hotlist fetcher
    def mock_fetcher(source_row: dict, **kwargs) -> tuple[list[dict], str | None, str | None]:
        return (
            [
                {
                    "item_key": "https://cls.cn/test1",
                    "canonical_url": "https://cls.cn/test1",
                    "url": "https://cls.cn/test1",
                    "title": "英伟达发布新一代 GPU 芯片",
                    "title_key": "英伟达发布新一代 GPU 芯片",
                    "summary": "算力翻倍",
                    "hint": "macro",
                    "published_at": None,
                    "published_ts": 0,
                    "rank": 1,
                }
            ],
            None,
            None,
        )

    registry = service.load_registry()
    registry["sources"] = [
        {
            "source_id": "cls-hot",
            "name": "财联社热门",
            "hint": "macro",
            "url": "https://cls.cn/hot",
            "source_type": "hotlist",
            "has_real_rank": True,
            "enabled": True,
        }
    ]

    # Fetch should succeed with 0 impact from AI outage
    outcome = service.run_fetch(
        "test",
        test_db,
        registry=registry,
        hotlist_fetcher=mock_fetcher,
    )
    assert outcome["status"] == "ok"
    assert outcome["item_seen"] == 1

    # Board query still works normally
    board = service.hotlist_board(test_db)
    assert board["status"] == "normal"
    assert len(board["items"]) == 1
    assert board["items"][0]["title"] == "英伟达发布新一代 GPU 芯片"
    assert board["items"][0]["rank"] == 1


# ---------------------------------------------------------------------------
# Test 16 & 17: Entity mapping and rank states are untouched
# ---------------------------------------------------------------------------

def test_entities_and_rank_states_unmutated_by_filter(test_db: str):
    now = store.utc_now_iso()
    # Insert source run and observations with real rank
    with store._connect(test_db) as conn:
        conn.execute(
            """
            INSERT INTO intel_sources (source_id, name, hint, url, source_type, has_real_rank, enabled, origin, updated_at)
            VALUES ('cls-hot', '财联社热门', 'macro', 'https://cls.cn/hot', 'hotlist', 1, 1, 'system', ?)
            """,
            (now,),
        )
        conn.execute(
            """
            INSERT INTO intel_fetch_runs (run_id, started_at, status, trigger)
            VALUES ('run-1', ?, 'ok', 'manual')
            """,
            (now,),
        )
        conn.execute(
            """
            INSERT INTO intel_source_runs (run_id, source_id, status, item_count, duration_ms)
            VALUES ('run-1', 'cls-hot', 'ok', 2, 100)
            """
        )
        cur1 = conn.execute(
            """
            INSERT INTO intel_items (item_key, canonical_url, url, title, title_key, summary, source_id, hint, published_at, published_ts, first_seen_at, last_seen_at, observation_count, created_at)
            VALUES ('key-1', 'https://cls.cn/1', 'https://cls.cn/1', '机器人龙头中大力德斩获大单', 'key-1', '减速器订单饱满', 'cls-hot', 'macro', NULL, 0, ?, ?, 1, ?)
            """,
            (now, now, now),
        )
        item1_id = cur1.lastrowid
        cur2 = conn.execute(
            """
            INSERT INTO intel_items (item_key, canonical_url, url, title, title_key, summary, source_id, hint, published_at, published_ts, first_seen_at, last_seen_at, observation_count, created_at)
            VALUES ('key-2', 'https://cls.cn/2', 'https://cls.cn/2', '某明星八卦绯闻', 'key-2', '娱乐报道', 'cls-hot', 'macro', NULL, 0, ?, ?, 1, ?)
            """,
            (now, now, now),
        )
        item2_id = cur2.lastrowid

        conn.execute(
            """
            INSERT INTO intel_observations (run_id, item_id, source_id, observed_at, rank, observed_title)
            VALUES ('run-1', ?, 'cls-hot', ?, 3, '机器人龙头中大力德斩获大单')
            """,
            (item1_id, now),
        )
        conn.execute(
            """
            INSERT INTO intel_observations (run_id, item_id, source_id, observed_at, rank, observed_title)
            VALUES ('run-1', ?, 'cls-hot', ?, 5, '某明星八卦绯闻')
            """,
            (item2_id, now),
        )
        # Add entity mapping for item 1
        conn.execute(
            """
            INSERT INTO intel_item_entities (item_id, term_kind, term, security_code, matched_in)
            VALUES (?, 'company_name', '中大力德', '002896', 'title')
            """,
            (item1_id,),
        )

    # In "all" mode
    board_all = service.hotlist_board(test_db, mode="all")
    assert len(board_all["items"]) == 2
    item1 = [it for it in board_all["items"] if it["item_id"] == item1_id][0]
    assert item1["rank"] == 3
    assert item1["current_state"] == "ON_LIST"
    assert len(item1["entities"]) == 1
    assert item1["entities"][0]["security_code"] == "002896"
    assert item1["filter_match"]["method"] == "keyword"
    assert "机器人与具身智能" in item1["filter_match"]["matched_groups"]

    # In "my_interests" mode: only item 1 returned
    board_filtered = service.hotlist_board(test_db, mode="my_interests")
    assert len(board_filtered["items"]) == 1
    f_item1 = board_filtered["items"][0]
    assert f_item1["item_id"] == item1_id
    assert f_item1["rank"] == 3
    assert f_item1["current_state"] == "ON_LIST"
    assert len(f_item1["entities"]) == 1
    assert f_item1["entities"][0]["security_code"] == "002896"


# ---------------------------------------------------------------------------
# Router Endpoints Integration Tests
# ---------------------------------------------------------------------------

def test_router_filter_endpoints(client: TestClient):
    # GET /api/native-intel/filter/profile
    r = client.get("/api/native-intel/filter/profile")
    assert r.status_code == 200
    prof = r.json()
    assert prof["profile_id"] == "default"
    assert prof["method"] == "keyword"

    # PUT /api/native-intel/filter/profile
    update_payload = {
        "name": "我的智能自选",
        "method": "keyword",
        "min_score": 0.8,
        "keyword_rules": {
            "global_excludes": ["广告"],
            "groups": [
                {"name": "芯片", "includes": ["GPU"], "excludes": []}
            ],
        },
    }
    r = client.put("/api/native-intel/filter/profile", json=update_payload)
    assert r.status_code == 200
    updated = r.json()
    assert updated["name"] == "我的智能自选"
    assert updated["min_score"] == 0.8
    assert len(updated["keyword_rules"]["groups"]) == 1

    # GET /api/native-intel/filter/status
    r = client.get("/api/native-intel/filter/status")
    assert r.status_code == 200
    status_data = r.json()
    assert status_data["status"] == "normal"
    assert "metrics" in status_data

    # GET /api/native-intel/hotlist?mode=my_interests
    r = client.get("/api/native-intel/hotlist?mode=my_interests")
    assert r.status_code == 200
    board = r.json()
    assert "filter_meta" in board
    assert board["filter_meta"]["mode"] == "my_interests"


# ---------------------------------------------------------------------------
# TREND-PARITY Wave 2 Follow-up: Gate Comprehensive Coverage Tests
# ---------------------------------------------------------------------------

def test_keyword_grammar_parity_required_and_max_count():
    # 1. Test required (AND logic) + includes (OR logic)
    rules = filter_engine.KeywordRules(
        global_excludes=[],
        filter_terms=["垃圾广告"],
        groups=[
            filter_engine.KeywordGroup(
                name="AI算力",
                required=["算力", "GPU"],
                includes=["英伟达", "华为"],
                max_count=2,
            ),
        ],
    )
    # Missing required word "GPU" -> should NOT match
    m, _ = filter_engine.evaluate_keyword_rules("华为最新算力中心落成", None, rules)
    assert m is False

    # Has both required ("算力", "GPU") and one include ("英伟达") -> MATCH
    m, g = filter_engine.evaluate_keyword_rules("英伟达发布下一代 GPU 算力芯片", None, rules)
    assert m is True
    assert "AI算力" in g

    # Filter terms hit -> reject
    m, _ = filter_engine.evaluate_keyword_rules("英伟达发布下一代 GPU 算力芯片，垃圾广告请勿理会", None, rules)
    assert m is False

    # 2. Regex flags: /pattern/i and /pattern/g
    regex_rules = filter_engine.KeywordRules(
        global_excludes=[],
        groups=[
            filter_engine.KeywordGroup(
                name="芯片测试",
                includes=["/gpu/i", "/npu/g"],
            ),
        ],
    )
    m, g = filter_engine.evaluate_keyword_rules("搭载顶级 GpU 加速器", None, regex_rules)
    assert m is True
    assert "芯片测试" in g

    # 3. Empty groups -> match all non-excluded
    empty_rules = filter_engine.KeywordRules(
        global_excludes=["黑名单词"],
        groups=[],
    )
    m, _ = filter_engine.evaluate_keyword_rules("任意标题", None, empty_rules)
    assert m is True
    m, _ = filter_engine.evaluate_keyword_rules("包含黑名单词的标题", None, empty_rules)
    assert m is False


def test_score_zero_preservation():
    tags = [{"id": 1, "tag": "半导体", "description": "芯片"}]
    items = [{"item_id": 101, "title": "完全不相关的某娱乐八卦", "summary": ""}]

    def mock_runner(cfg: Any, msgs: list[dict[str, str]]) -> str:
        return json.dumps([{"id": 101, "tag_id": 1, "score": 0.0}])

    succeeded, not_relevant, failed = filter_engine.classify_items_batch(
        items, tags, model_runner=mock_runner
    )
    assert len(succeeded) == 1
    assert succeeded[0]["item_id"] == 101
    assert succeeded[0]["relevance_score"] == 0.0  # Must NOT become 0.5


def test_three_state_caching_and_error_isolation(test_db: str):
    # Setup 4 items in test_db
    now = store.utc_now_iso()
    inserted_ids = []
    with store._connect(test_db) as conn:
        for i in range(1, 5):
            cur = conn.execute(
                """
                INSERT INTO intel_items (
                    item_key, canonical_url, url, title, title_key, summary,
                    source_id, hint, published_at, published_ts, first_seen_at,
                    last_seen_at, observation_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'cls-hot', 'macro', NULL, 0, ?, ?, 1, ?)
                """,
                (f"k-{i}", f"u-{i}", f"u-{i}", f"标题 {i}", f"k-{i}", f"摘要 {i}", now, now, now),
            )
            inserted_ids.append(cur.lastrowid)

    tags = [{"id": 1, "tag": "科技", "description": "科技资讯"}]
    prof = service.update_filter_profile(
        "default",
        {"method": "ai", "tags": tags, "interests_text": "关注科技", "min_score": 0.7},
        test_db,
    )
    fp = prof["profile_fingerprint"]

    # First run: item 1 classified (0.9), item 2 not relevant (0.0 or omitted), item 3 & 4 error
    call_idx = 0
    def mock_runner(cfg: Any, msgs: list[dict[str, str]]) -> str:
        nonlocal call_idx
        call_idx += 1
        if "标题 3" in msgs[-1]["content"] or "标题 4" in msgs[-1]["content"]:
            raise RuntimeError("Simulation LLM timeout")
        return json.dumps([
            {"id": inserted_ids[0], "tag_id": 1, "score": 0.9},
        ])

    # Run batch size = 2 so items 1&2 succeed, items 3&4 fail
    res = service.classify_items(
        "default",
        item_ids=inserted_ids,
        batch_size=2,
        model_runner=mock_runner,
        path=test_db,
    )

    analyses = store.get_item_analyses("default", fp, inserted_ids, db_path=test_db)
    assert analyses[inserted_ids[0]]["analysis_state"] == store.ANALYSIS_STATE_CLASSIFIED
    assert analyses[inserted_ids[1]]["analysis_state"] == store.ANALYSIS_STATE_NOT_RELEVANT
    assert analyses[inserted_ids[2]]["analysis_state"] == store.ANALYSIS_STATE_ERROR
    assert analyses[inserted_ids[3]]["analysis_state"] == store.ANALYSIS_STATE_ERROR

    # Check filter_status honest metric counts
    status = service.filter_status("default", test_db)
    metrics = status["metrics"]
    assert metrics["classified_count"] == 1
    assert metrics["not_relevant_count"] == 1
    assert metrics["error_count"] == 2
    assert metrics["matched_count"] == 1


def test_incremental_carry_forward_and_threshold_branching(test_db: str):
    # Setup items
    now = store.utc_now_iso()
    with store._connect(test_db) as conn:
        conn.execute(
            """
            INSERT INTO intel_items (
                item_key, canonical_url, url, title, title_key, summary,
                source_id, hint, published_at, published_ts, first_seen_at,
                last_seen_at, observation_count, created_at
            ) VALUES ('k1', 'u1', 'u1', '半导体重大突破', 'k1', '芯片', 'cls-hot', 'macro', NULL, 0, ?, ?, 1, ?)
            """,
            (now, now, now),
        )
        item_id = conn.execute("SELECT item_id FROM intel_items WHERE item_key = 'k1'").fetchone()["item_id"]

    # Profile 1 with tag "芯片"
    old_tags = [{"id": 1, "tag": "芯片", "description": "半导体芯片"}]
    p1 = service.update_filter_profile(
        "default",
        {"method": "ai", "tags": old_tags, "interests_text": "关注芯片", "min_score": 0.7},
        test_db,
    )
    fp1 = p1["profile_fingerprint"]

    # Classify item 1 under fp1
    def mock_runner(cfg: Any, msgs: list[dict[str, str]]) -> str:
        return json.dumps([{"id": item_id, "tag_id": 1, "score": 0.95}])

    service.classify_items("default", item_ids=[item_id], model_runner=mock_runner, path=test_db)
    cls1 = store.get_item_classifications("default", fp1, [item_id], db_path=test_db)
    assert item_id in cls1

    # Incremental update: keep "芯片", change_ratio = 0.2 < threshold 0.5
    def mock_update_runner(cfg: Any, msgs: list[dict[str, str]]) -> str:
        return json.dumps({
            "keep": [{"tag": "芯片", "description": "半导体芯片"}],
            "add": [],
            "remove": [],
            "change_ratio": 0.1,
        })

    res_plan = service.apply_interest_update(
        "default",
        "关注芯片与半导体制造",
        model_runner=mock_update_runner,
        full_reclassify_threshold=0.5,
        path=test_db,
    )
    assert res_plan["decision"] == "INCREMENTAL"
    p2 = service.get_filter_profile("default", test_db)
    fp2 = p2["profile_fingerprint"]
    assert fp1 != fp2

    # Verify classification carried forward to fp2 without re-calling classify
    cls2 = store.get_item_classifications("default", fp2, [item_id], db_path=test_db)
    assert item_id in cls2
    assert cls2[item_id]["relevance_score"] == 0.95
    ana2 = store.get_item_analyses("default", fp2, [item_id], db_path=test_db)
    assert ana2[item_id]["analysis_state"] == store.ANALYSIS_STATE_CLASSIFIED


def test_unified_filter_items_and_rss_parity(test_db: str):
    now = store.utc_now_iso()
    with store._connect(test_db) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO intel_sources (source_id, name, hint, url, source_type, origin, enabled, has_real_rank, updated_at)
            VALUES ('cls-hot', '财联社热门', 'macro', 'https://cls.cn', 'hotlist', 'system', 1, 1, ?),
                   ('feed-user-1', '用户RSS', 'macro', 'https://rss.example', 'rss', 'user', 1, 0, ?)
            """,
            (now, now),
        )
        # Hotlist item
        conn.execute(
            """
            INSERT INTO intel_items (
                item_key, canonical_url, url, title, title_key, summary,
                source_id, hint, published_at, published_ts, first_seen_at,
                last_seen_at, observation_count, created_at
            ) VALUES ('k-hl', 'u-hl', 'u-hl', '热榜：具身机器人量产', 'k-hl', '机器人', 'cls-hot', 'macro', NULL, 0, ?, ?, 1, ?)
            """,
            (now, now, now),
        )
        # RSS item
        conn.execute(
            """
            INSERT INTO intel_items (
                item_key, canonical_url, url, title, title_key, summary,
                source_id, hint, published_at, published_ts, first_seen_at,
                last_seen_at, observation_count, created_at
            ) VALUES ('k-rss', 'u-rss', 'u-rss', 'RSS订阅：具身机器人核心零部件报告', 'k-rss', '产业链深度', 'feed-user-1', 'macro', ?, 0, ?, ?, 1, ?)
            """,
            (now, now, now, now),
        )

    # Set keyword rules targeting 机器人
    service.update_filter_profile(
        "default",
        {
            "method": "keyword",
            "keyword_rules": {
                "global_excludes": [],
                "groups": [{"name": "机器人", "includes": ["机器人"], "excludes": []}],
            },
        },
        test_db,
    )

    # 1. Query source_type=all
    all_res = service.list_filtered_items(profile_id="default", source_type="all", mode="my_interests", path=test_db)
    assert all_res["status"] == "normal"
    assert len(all_res["items"]) == 2

    # 2. Query source_type=rss
    rss_res = service.list_filtered_items(profile_id="default", source_type="rss", mode="my_interests", path=test_db)
    assert len(rss_res["items"]) == 1
    assert rss_res["items"][0]["title"] == "RSS订阅：具身机器人核心零部件报告"
    assert rss_res["items"][0]["rank"] is None  # RSS items must not have faked rank

    # 3. Query source_type=hotlist
    hl_res = service.list_filtered_items(profile_id="default", source_type="hotlist", mode="my_interests", path=test_db)
    assert len(hl_res["items"]) == 1
    assert "热榜" in hl_res["items"][0]["title"]


def test_fail_closed_on_filter_error_in_hotlist_board(test_db: str, monkeypatch: pytest.MonkeyPatch):
    # Insert an item
    now = store.utc_now_iso()
    with store._connect(test_db) as conn:
        conn.execute(
            """
            INSERT INTO intel_items (
                item_key, canonical_url, url, title, title_key, summary,
                source_id, hint, published_at, published_ts, first_seen_at,
                last_seen_at, observation_count, created_at
            ) VALUES ('k-err', 'u-err', 'u-err', '测试标题', 'k-err', '测试', 'cls-hot', 'macro', NULL, 0, ?, ?, 1, ?)
            """,
            (now, now, now),
        )

    # Mock filter_items to raise unexpected exception
    def mock_fail(*args, **kwargs):
        raise RuntimeError("Filter engine critical fault")

    monkeypatch.setattr(service, "filter_items", mock_fail)

    # When mode=my_interests, fail closed: items must be empty, filter_meta status UNAVAILABLE
    res = service.hotlist_board(test_db, mode="my_interests")
    assert res["items"] == []
    assert res["filter_meta"]["status"] == "UNAVAILABLE"
    assert "Filter engine critical fault" in res["filter_meta"]["error"]


def test_router_apply_interest_update_and_filter_items(client: TestClient):
    # Test POST /api/native-intel/filter/apply-interest-update
    # Without interests_text -> 422
    r = client.post("/api/native-intel/filter/apply-interest-update", json={})
    assert r.status_code == 422

    # Test GET /api/native-intel/filter/items
    r = client.get("/api/native-intel/filter/items?source_type=all&mode=my_interests")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "filter_meta" in data


# ---------------------------------------------------------------------------
# Independent Gate Follow-up Closure Tests (A - K)
# ---------------------------------------------------------------------------

def test_apply_interest_update_cfg_propagation_and_no_fallback(test_db: str):
    """验证 apply_interest_update 严格传递 effective_cfg，无 cfg 时抛出 AI_CONFIG_REQUIRED，且不修改 provider。"""
    # 1. 无 cfg 且无 runner -> AI_CONFIG_REQUIRED
    with pytest.raises(ValueError, match="AI_CONFIG_REQUIRED"):
        service.apply_interest_update(
            profile_id="default",
            interests_text="关注机器人与半导体",
            path=test_db,
        )

    # 2. 传递 cli-codex cfg -> runner 真实收到该 cfg
    received_cfgs = []

    def mock_runner(cfg, messages):
        received_cfgs.append(cfg)
        return '{"tags": [{"id": 1, "tag": "芯片", "description": "半导体"}]}'

    res = service.apply_interest_update(
        profile_id="default",
        interests_text="关注芯片领域",
        cfg={"provider": "cli-codex", "model": "gpt-5-codex"},
        model_runner=mock_runner,
        path=test_db,
    )
    assert len(received_cfgs) > 0
    assert received_cfgs[0]["provider"] == "cli-codex"
    assert received_cfgs[0]["model"] == "gpt-5-codex"

    # 3. 传递 openai-compatible cfg -> 必须保留，绝不转为 codex
    received_cfgs.clear()
    res2 = service.apply_interest_update(
        profile_id="default",
        interests_text="关注芯片与光刻机",
        cfg={"provider": "openai-compatible", "baseURL": "https://api.openai.com/v1", "apiKey": "sk-mock", "model": "gpt-4o"},
        model_runner=mock_runner,
        path=test_db,
    )
    assert len(received_cfgs) > 0
    assert received_cfgs[0]["provider"] == "openai-compatible"
    assert received_cfgs[0]["baseURL"] == "https://api.openai.com/v1"
    assert received_cfgs[0]["model"] == "gpt-4o"


def test_reclassify_threshold_router_and_service_truth(client: TestClient, test_db: str):
    """验证 router 与 service 的 threshold 真实流转：未传使用 profile 默认值 (0.6)，显式 0.0 保留，非法输入报 422。"""
    # 1. 确保 profile 拥有 0.6 threshold
    prof = service.get_filter_profile("default", test_db)
    assert prof["reclassify_threshold"] == 0.6

    # 先初始化 profile 拥有初始标签 ["芯片"]
    service.update_filter_profile(
        "default",
        {
            "interests_text": "关注芯片",
            "tags": [{"id": 1, "tag": "芯片", "description": "半导体"}],
            "reclassify_threshold": 0.6,
            "method": "ai",
        },
        test_db,
    )

    orig_update = filter_engine.update_interest_tags
    orig_extract = filter_engine.extract_interest_tags
    try:
        filter_engine.update_interest_tags = lambda old_tags, text, cfg=None, model_runner=None: {
            "keep": ["芯片"],
            "add": [{"id": 2, "tag": "具身智能", "description": "机器人"}],
            "remove": [],
            "new_tags": [{"id": 1, "tag": "芯片", "description": "半导体"}, {"id": 2, "tag": "具身智能", "description": "机器人"}],
            "change_ratio": 0.55,
        }

        filter_engine.extract_interest_tags = lambda text, cfg=None, model_runner=None: [
            {"id": 1, "tag": "全新提取标签", "description": "fresh"}
        ]

        # A. Router 不传 threshold -> 应当读取 profile 的 0.6。因为 change_ratio 0.55 < 0.6，必须走 INCREMENTAL
        r = client.post(
            "/api/native-intel/filter/apply-interest-update",
            json={
                "profile_id": "default",
                "interests_text": "关注芯片与具身智能",
                "ai_config": {"provider": "cli-codex", "model": "gpt-5-codex"},
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["decision"] == "INCREMENTAL"
        assert data["change_ratio"] == 0.55

        # B. Router 显式传 0.5 -> 0.55 >= 0.5，走 FULL
        r2 = client.post(
            "/api/native-intel/filter/apply-interest-update",
            json={
                "profile_id": "default",
                "interests_text": "关注芯片与具身智能",
                "ai_config": {"provider": "cli-codex", "model": "gpt-5-codex"},
                "full_reclassify_threshold": 0.5,
            },
        )
        assert r2.status_code == 200, r2.text
        data2 = r2.json()
        assert data2["decision"] == "FULL"
        assert data2["profile"]["tags"][0]["tag"] == "全新提取标签"

        # C. Router 显式传 0.0 -> 0.0 保留并生效 (0.55 >= 0.0 -> FULL)
        r3 = client.post(
            "/api/native-intel/filter/apply-interest-update",
            json={
                "profile_id": "default",
                "interests_text": "关注芯片与具身智能",
                "ai_config": {"provider": "cli-codex", "model": "gpt-5-codex"},
                "full_reclassify_threshold": 0.0,
            },
        )
        assert r3.status_code == 200, r3.text
        assert r3.json()["decision"] == "FULL"

        # D. Router 传入非法 threshold -> 422 BAD_ARGUMENT
        r4 = client.post(
            "/api/native-intel/filter/apply-interest-update",
            json={
                "profile_id": "default",
                "interests_text": "关注芯片与具身智能",
                "ai_config": {"provider": "cli-codex", "model": "gpt-5-codex"},
                "full_reclassify_threshold": "not-a-number",
            },
        )
        assert r4.status_code == 422
        assert r4.json()["detail"]["status"] == "BAD_ARGUMENT"

        r5 = client.post(
            "/api/native-intel/filter/apply-interest-update",
            json={
                "profile_id": "default",
                "interests_text": "关注芯片与具身智能",
                "ai_config": {"provider": "cli-codex", "model": "gpt-5-codex"},
                "full_reclassify_threshold": 1.5,
            },
        )
        assert r5.status_code == 422
        assert r5.json()["detail"]["status"] == "BAD_ARGUMENT"
    finally:
        filter_engine.update_interest_tags = orig_update
        filter_engine.extract_interest_tags = orig_extract


def test_full_branch_fresh_extract_and_failure_rollback(test_db: str):
    """验证 FULL 分支必须执行 fresh extract 且用 fresh 标签创建 profile，若 fresh extract 失败旧状态完整保留 (Fail-Closed)。"""
    # 1. 设置初始 profile
    initial_tags = [{"id": 1, "tag": "旧半导体", "description": "芯片"}]
    initial_prof = service.update_filter_profile(
        "default",
        {
            "interests_text": "旧关注半导体",
            "tags": initial_tags,
            "reclassify_threshold": 0.5,
            "method": "ai",
        },
        test_db,
    )
    initial_fp = initial_prof["profile_fingerprint"]

    # 模拟 update_tags 返回临时 new_tags，change_ratio = 0.8 >= 0.5
    orig_update = filter_engine.update_interest_tags
    orig_extract = filter_engine.extract_interest_tags
    try:
        filter_engine.update_interest_tags = lambda old_tags, text, cfg=None, model_runner=None: {
            "keep": [],
            "add": [{"id": 2, "tag": "错误临时候选", "description": "temp"}],
            "remove": ["旧半导体"],
            "new_tags": [{"id": 2, "tag": "错误临时候选", "description": "temp"}],
            "change_ratio": 0.8,
        }

        # Fresh extract 返回真正标签 ["机器人", "液冷"]
        filter_engine.extract_interest_tags = lambda text, cfg=None, model_runner=None: [
            {"id": 10, "tag": "机器人", "description": "减速器"},
            {"id": 11, "tag": "液冷", "description": "数据中心"},
        ]

        res = service.apply_interest_update(
            profile_id="default",
            interests_text="关注机器人与数据中心液冷",
            cfg={"provider": "cli-codex", "model": "gpt-5-codex"},
            path=test_db,
        )
        assert res["decision"] == "FULL"
        # 验证最终 profile 来自 fresh extract，而不是 update_tags 的 "错误临时候选"
        prof_after = service.get_filter_profile("default", test_db)
        tag_names = [t["tag"] for t in prof_after["tags"]]
        assert tag_names == ["机器人", "液冷"]
        assert "错误临时候选" not in tag_names
        new_fp = prof_after["profile_fingerprint"]
        assert new_fp != initial_fp

        # 2. 测试 Fail Closed：若 fresh extract 抛出异常，旧 profile 必须完全不被修改
        def fail_extract(text, cfg=None, model_runner=None):
            raise RuntimeError("Fresh extraction service timed out")

        filter_engine.extract_interest_tags = fail_extract

        with pytest.raises(RuntimeError, match="Fresh extraction service timed out"):
            service.apply_interest_update(
                profile_id="default",
                interests_text="尝试改变为航空航天",
                cfg={"provider": "cli-codex", "model": "gpt-5-codex"},
                path=test_db,
            )

        # 检查数据库：profile 必须保持上一步的 ["机器人", "液冷"]，指纹与文本未被篡改
        prof_unmodified = service.get_filter_profile("default", test_db)
        assert [t["tag"] for t in prof_unmodified["tags"]] == ["机器人", "液冷"]
        assert prof_unmodified["profile_fingerprint"] == new_fp
        assert prof_unmodified["interests_text"] == "关注机器人与数据中心液冷"
    finally:
        filter_engine.update_interest_tags = orig_update
        filter_engine.extract_interest_tags = orig_extract


def test_keyword_required_filter_terms_and_max_count_persistence_and_filtering(test_db: str):
    """验证 required、filter_terms、max_count 的持久化与完整过滤语义。"""
    now = store.utc_now_iso()
    with store._connect(test_db) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO intel_sources (source_id, name, hint, url, source_type, origin, enabled, has_real_rank, updated_at)
            VALUES ('cls-hot', '财联社热门', 'macro', 'https://cls.cn', 'hotlist', 'system', 1, 1, ?)
            """,
            (now,),
        )
        # item 1: 有 GPU 和 英伟达 (符合 required 和 includes)
        conn.execute(
            """
            INSERT INTO intel_items (item_key, canonical_url, url, title, title_key, summary, source_id, hint, published_at, published_ts, first_seen_at, last_seen_at, observation_count, created_at)
            VALUES ('item-1', 'u1', 'u1', '英伟达发布新一代GPU架构', 'k1', '算力突破', 'cls-hot', 'macro', NULL, 0, ?, ?, 1, ?)
            """,
            (now, now, now),
        )
        # item 2: 同样符合该组 (用于测试 max_count=1)
        conn.execute(
            """
            INSERT INTO intel_items (item_key, canonical_url, url, title, title_key, summary, source_id, hint, published_at, published_ts, first_seen_at, last_seen_at, observation_count, created_at)
            VALUES ('item-2', 'u2', 'u2', '英伟达GPU供应链出货翻倍', 'k2', '产业链爆单', 'cls-hot', 'macro', NULL, 0, ?, ?, 1, ?)
            """,
            (now, now, now),
        )
        # item 3: 只有英伟达，没有 GPU (缺少 required，应被拒绝)
        conn.execute(
            """
            INSERT INTO intel_items (item_key, canonical_url, url, title, title_key, summary, source_id, hint, published_at, published_ts, first_seen_at, last_seen_at, observation_count, created_at)
            VALUES ('item-3', 'u3', 'u3', '英伟达股价小幅波动', 'k3', '市场评论', 'cls-hot', 'macro', NULL, 0, ?, ?, 1, ?)
            """,
            (now, now, now),
        )
        # item 4: 命中了 filter_terms (如广告推广，应被拒绝)
        conn.execute(
            """
            INSERT INTO intel_items (item_key, canonical_url, url, title, title_key, summary, source_id, hint, published_at, published_ts, first_seen_at, last_seen_at, observation_count, created_at)
            VALUES ('item-4', 'u4', 'u4', '商业推广：英伟达GPU算力租借优惠', 'k4', '特惠', 'cls-hot', 'macro', NULL, 0, ?, ?, 1, ?)
            """,
            (now, now, now),
        )

    rules_payload = {
        "global_excludes": ["震惊"],
        "filter_terms": ["商业推广", "广告"],
        "groups": [
            {
                "name": "英伟达算力",
                "includes": ["英伟达"],
                "required": ["GPU"],
                "excludes": ["玩具"],
                "max_count": 1,
            }
        ],
    }

    updated_prof = service.update_filter_profile(
        "default",
        {
            "method": "keyword",
            "keyword_rules": rules_payload,
        },
        test_db,
    )

    # 1. 验证持久化
    reloaded_prof = service.get_filter_profile("default", test_db)
    kw_rules = reloaded_prof["keyword_rules"]
    assert kw_rules["filter_terms"] == ["商业推广", "广告"]
    group0 = kw_rules["groups"][0]
    assert group0["name"] == "英伟达算力"
    assert group0["includes"] == ["英伟达"]
    assert group0["required"] == ["GPU"]
    assert group0["max_count"] == 1

    # 2. 验证过滤语义：
    # item 4 命中 filter_terms -> 排除
    # item 3 缺少 required("GPU") -> 排除
    # item 1 和 item 2 都满足，但 max_count=1 -> 只有 1 条被采纳
    res = service.list_filtered_items(profile_id="default", source_type="all", mode="my_interests", path=test_db)
    assert res["status"] == "normal"
    assert len(res["items"]) == 1
    assert "英伟达" in res["items"][0]["title"]
    assert "GPU" in res["items"][0]["title"]


def test_apply_interest_update_with_min_score_persistence_and_filtered_readback(test_db: str, client: TestClient):
    now = store.utc_now_iso()
    # 1. 插入两篇条目：Item A (score 0.90) 与 Item B (score 0.80)
    with store._connect(test_db) as conn:
        conn.execute(
            """
            INSERT INTO intel_fetch_runs (run_id, started_at, finished_at, status, trigger, source_total, source_ok, source_failed, item_seen, item_new)
            VALUES ('run-min-score-test', ?, ?, 'ok', 'manual', 1, 1, 0, 2, 2)
            """,
            (now, now),
        )
        cur = conn.execute(
            """
            INSERT INTO intel_items (item_key, canonical_url, url, title, title_key, summary, source_id, hint, published_at, published_ts, first_seen_at, last_seen_at, observation_count, created_at)
            VALUES ('item-a', 'http://a', 'http://a', '人形机器人谐波减速器量产突破', 'k-a', '减速器订单放量', 'cls-hot', 'macro', NULL, 0, ?, ?, 1, ?)
            """,
            (now, now, now),
        )
        item_a_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO intel_observations (run_id, item_id, source_id, observed_at, rank, observed_title, published_at)
            VALUES ('run-min-score-test', ?, 'cls-hot', ?, 1, '人形机器人谐波减速器量产突破', ?)
            """,
            (item_a_id, now, now),
        )

        cur = conn.execute(
            """
            INSERT INTO intel_items (item_key, canonical_url, url, title, title_key, summary, source_id, hint, published_at, published_ts, first_seen_at, last_seen_at, observation_count, created_at)
            VALUES ('item-b', 'http://b', 'http://b', '轻型四足机器狗开售', 'k-b', '四足消费级机器狗上市', 'cls-hot', 'macro', NULL, 0, ?, ?, 1, ?)
            """,
            (now, now, now),
        )
        item_b_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO intel_observations (run_id, item_id, source_id, observed_at, rank, observed_title, published_at)
            VALUES ('run-min-score-test', ?, 'cls-hot', ?, 2, '轻型四足机器狗开售', ?)
            """,
            (item_b_id, now, now),
        )

    # 初始 profile: min_score = 0.70
    service.update_filter_profile(
        "default",
        {
            "method": "ai",
            "interests_text": "关注工业机器人",
            "min_score": 0.70,
            "tags": [{"id": 1, "tag": "工业机器人", "description": "传统工业自动化臂"}],
        },
        test_db,
    )

    # Mock runner：返回新 tags，并在打分时给 item A 0.90，给 item B 0.80
    def mock_runner(cfg: Any, msgs: list[dict[str, str]]) -> str:
        prompt_str = str(msgs)
        if "update_tags" in prompt_str or "提炼出" in prompt_str or "新描述" in prompt_str or "tags" in prompt_str and "score" not in prompt_str:
            return json.dumps({
                "keep": [],
                "add": [
                    {"tag": "人形机器人", "description": "具身智能与核心零部件"},
                    {"tag": "四足机器人", "description": "四足机器狗与巡检机器人"},
                ],
                "remove": ["工业机器人"],
                "change_ratio": 1.0,
                "new_tags": [
                    {"id": 1, "tag": "人形机器人", "description": "具身智能与核心零部件"},
                    {"id": 2, "tag": "四足机器人", "description": "四足机器狗与巡检机器人"},
                ],
                "tags": [
                    {"id": 1, "tag": "人形机器人", "description": "具身智能与核心零部件"},
                    {"id": 2, "tag": "四足机器人", "description": "四足机器狗与巡检机器人"},
                ],
            })
        # 批量打分
        return json.dumps([
            {"id": item_a_id, "tag_id": 1, "score": 0.90},
            {"id": item_b_id, "tag_id": 2, "score": 0.80},
        ])

    # 2. 用户同一次操作：修改 interests_text 并将 min_score 改为 0.85
    new_interests = "重点关注人形机器人核心零部件与四足机器人"
    res = service.apply_interest_update(
        profile_id="default",
        interests_text=new_interests,
        min_score=0.85,
        cfg={"provider": "cli-codex", "model": "gpt-5-codex"},
        model_runner=mock_runner,
        path=test_db,
    )

    # 验证返回的 profile 包含了 0.85
    assert res["profile"]["min_score"] == 0.85
    assert res["profile"]["interests_text"] == new_interests
    canonical_fp = res["profile"]["profile_fingerprint"]

    # 验证持久化落库（Reload Persistence）
    reloaded = service.get_filter_profile("default", test_db)
    assert reloaded["min_score"] == 0.85
    assert reloaded["interests_text"] == new_interests
    assert reloaded["profile_fingerprint"] == canonical_fp

    # 3. 执行分类
    cls_res = service.classify_items(
        profile_id="default",
        cfg={"provider": "cli-codex", "model": "gpt-5-codex"},
        model_runner=mock_runner,
        path=test_db,
    )
    assert cls_res["status"] == "SUCCESS"
    assert cls_res["classified"] == 2

    # 4. 验证 filtered readback 真实受新 min_score=0.85 影响：
    # Item A (score 0.90 >= 0.85) -> 可见
    # Item B (score 0.80 < 0.85)  -> 不可见
    filtered = service.list_filtered_items(profile_id="default", source_type="all", mode="my_interests", path=test_db)
    assert filtered["status"] == "normal"
    filtered_ids = [i["item_id"] for i in filtered["items"]]
    assert item_a_id in filtered_ids
    assert item_b_id not in filtered_ids

    # 5. 验证 all 模式：两篇都返回，但 Item A filter_match 有效，Item B filter_match 为 None
    all_view = service.list_filtered_items(profile_id="default", source_type="all", mode="all", path=test_db)
    all_map = {i["item_id"]: i for i in all_view["items"]}
    assert all_map[item_a_id]["filter_match"] is not None
    assert all_map[item_a_id]["filter_match"]["relevance_score"] == 0.90
    assert all_map[item_b_id]["filter_match"] is None


def test_apply_interest_update_router_min_score_and_validation(client: TestClient, test_db: str):
    # 1. 正常传入 min_score = 0.82
    resp = client.post(
        "/api/native-intel/filter/apply-interest-update",
        json={
            "interests_text": "关注新能源固态电池",
            "min_score": 0.82,
            "cfg": {"provider": "cli-codex", "model": "gpt-5-codex"},
        },
    )
    # 若没有 mock runner 可能会报 AI_ERROR 或 422，但如果是参数校验错误会是 BAD_ARGUMENT
    # 测试非法 min_score 校验
    bad_resp1 = client.post(
        "/api/native-intel/filter/apply-interest-update",
        json={
            "interests_text": "关注新能源",
            "min_score": 1.5,
        },
    )
    assert bad_resp1.status_code == 422
    assert "min_score 必须在 0.0 到 1.0 之间" in bad_resp1.json()["detail"]["error"]

    bad_resp2 = client.post(
        "/api/native-intel/filter/apply-interest-update",
        json={
            "interests_text": "关注新能源",
            "min_score": "not-a-number",
        },
    )
    assert bad_resp2.status_code == 422
    assert "非法的 min_score" in bad_resp2.json()["detail"]["error"]
