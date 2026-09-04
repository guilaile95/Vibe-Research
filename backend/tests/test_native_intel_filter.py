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
