# Native Intel Wave 5 Behavior Contract

Reference: [TrendRadar v6.10.0, pinned commit 8ee26026ba6c11dec41a95fb3895a7162876caa1](https://github.com/sansan0/TrendRadar/tree/8ee26026ba6c11dec41a95fb3895a7162876caa1).
Audited files:
- `trendradar/ai/analyzer.py`
- `trendradar/ai/client.py`
- `trendradar/ai/translator.py`
- `trendradar/ai/prompt_loader.py`
- `config/config.yaml`
- `config/ai_analysis_prompt.txt`
- `config/ai_translation_prompt.txt`
- `README-MCP-FAQ.md`
- `mcp_server/server.py`
- `mcp_server/tools/*.py`

---

## 1. Pinned AI Analyzer Output Structure

The pinned AI Analyzer produces a structured object with 6 primary sections and associated execution metadata:

```json
{
  "core_trends": "核心热点态势（提炼共性与宏观微观逻辑，200字以内）",
  "sentiment_controversy": "舆论风向与争议（情绪光谱与核心矛盾，100字以内）",
  "signals": "异动与弱信号（跨平台共振/温差、排名急升/衰退/回榜，150字以内）",
  "rss_insights": "RSS深度洞察（认知纠偏、硬核专业增量，100字以内；无RSS时填暂无）",
  "outlook_strategy": "研判与策略建议（分角色预测推演：1. 投资者 2. 品牌方 3. 公众）",
  "standalone_summaries": {
    "源名称": "每源100字以内概括，包含整体动向与前5板块未覆盖的独有内容"
  }
}
```

Vibe Native Mapping:
- Retains these 6 core sections with clean Chinese labeling:
  - 核心热点与态势 (`core_trends`)
  - 舆情风向与争议 (`sentiment_controversy`)
  - 异动与弱信号 (`signals`)
  - RSS 深度洞察 (`rss_insights`)
  - 研判与观察建议 (`outlook_strategy`, explicitly watermarked as `NON_AUTHORITATIVE_AI_DRAFT`)
  - 重点独立来源概括 (`standalone_summaries`)
- Explicit disclaimer: "AI 生成草稿，不是正式投资决策". Strictly prohibited from generating trade orders, formal thesis, or modifying position/account authorities.

---

## 2. AI Analysis Parameter Semantics

- `max_news` (`MAX_NEWS_FOR_ANALYSIS`, default 50):
  - In pinned upstream, caps the total hotlist and RSS lines formatted into the prompt.
  - In Vibe, selection is strictly deterministic based on Wave 4 report ordering (`ordering_score` descending for hotlist, newest publication for RSS), avoiding random or physical SQLite row ID ordering.
  - Honest metadata returned: `total_news`, `analyzed_news`, `max_news_limit`, `hotlist_count`, `hotlist_analyzed`, `rss_count`, `rss_analyzed`, `standalone_analyzed`.
- `include_rss` (`INCLUDE_RSS`, default true):
  - When enabled and RSS stats are present, RSS items are included up to remaining `max_news` budget.
  - When disabled, RSS prompt block is omitted and `rss_insights` output is forcibly cleared.
- `include_standalone` (`INCLUDE_STANDALONE`, default false):
  - When enabled and standalone data exists, formats separate `### [源名称]` sections and asks AI to fill `standalone_summaries`.
  - When disabled, standalone summaries are empty dictionary.
- `include_rank_timeline` (`INCLUDE_RANK_TIMELINE`, default false):
  - If true, appends rank trajectory string `1(09:30)→2(10:00)→...` to each item.
- `language` (`LANGUAGE`, default "Chinese"):
  - Passed to prompt `{language}` placeholder.
- `report_mode` (`CURRENT`, `DAILY`, `INCREMENTAL`):
  - `CURRENT`: Analyzes current hotlist/RSS snapshot.
  - `DAILY`: Analyzes day-aggregated items and trajectories.
  - `INCREMENTAL`: Analyzes new unobserved items since last cursor. In Vibe, AI analysis runs strictly in read-only preview mode and NEVER advances the report baseline cursor. Cursor advance is reserved for explicit user or scheduled report execution.

---

## 3. JSON Output Parsing, Repair, and Honesty

- Upstream parsing steps:
  1. Strip markdown code fence blocks (```json ... ``` or ``` ... ```).
  2. Parse with `json.loads`.
  3. If decode fails, attempt local repair via `json_repair`.
  4. If local repair fails, execute ONE remote repair attempt (`_retry_fix_json`) with lightweight repair prompt asking the LLM to fix escaping, commas, quotes.
- Failure semantics:
  - Upstream falls back to raw text into `core_trends` if repair fails.
  - In Vibe: If remote repair fails, the status is honestly marked as `ERROR` or `PARTIAL`. Vibe NEVER treats malformed raw text as a successful structured analysis.

---

## 4. Pinned Translation Behavior

- Single Translation: Translates given text to `target_language`. If text is empty or whitespace, returns original text marked success without calling LLM.
- Batch Translation (`translate_batch`):
  - Uses indexed format:
    ```
    [1] Text A
    [2] Text B
    [3] Text C
    ```
  - Parses response using regex / bracket inspection matching `[idx]`.
  - Exact index-based reconstruction (`idx_to_text[idx]`):
    If input has 3 items and AI returns only `[1]` and `[3]`, item 2 receives empty string, which is then safely filled with original text `Text B`. Position 3 is NOT shifted to position 2.
- Data Authority:
  - Translations are stored as derived `intel_ai_artifacts`.
  - Never mutates `intel_items.title` or `intel_items.summary`. Original text remains authoritative truth.
- Scope: Configurable for hotlist, rss, standalone. Excludes non-human text (URLs, ranks, timestamps, IDs).

---

## 5. Sentiment & Controversy Analysis

- Upstream analysis:
  - In `AIAnalyzer`: Narrative text under section `sentiment_controversy` analyzing public opinion spectrum and core conflicts.
  - In `mcp_server/tools/analytics.py`: `analyze_sentiment` tool generates an AI prompt for sentiment analysis rather than calculating a raw score.
- Vibe Wave 5 Parity:
  - Macro level: Provides `sentiment_controversy` in AI deep analysis reports.
  - Item / Topic level: Provides structured classification:
    `sentiment`: `positive` | `negative` | `neutral` | `controversial` | `uncertain`
    `controversy`: bool
    `confidence`: float (0.0 ~ 1.0)
    `reasoning`: str
  - Ambiguous cases return `uncertain` or `neutral` (no forced polarization).
  - Explicit rule: Sentiment is an observation annotation, NEVER a stock price forecast, trade signal, or automatic thesis.

---

## 6. Entity & Concept Extraction

- Upstream types: In `mcp_server/tools/analytics.py` and `search_tools.py`, entity search supports `person`, `location`, `organization`.
- Vibe Financial Domain Superset:
  - Supports A-share domain entities: `company`, `industry`, `concept`, plus general `person`, `organization`, `location`.
  - Schema per entity: `type`, `name`, `evidence`, `confidence`, `resolved_security_code`.
- Authority Separation:
  - AI extraction results are non-authoritative annotations stored in `intel_ai_artifacts`.
  - AI NEVER directly writes to `intel_entity_terms` or `intel_security_directory`.
  - Exact deterministic resolution to security codes occurs only via strict match against existing registered tickers/names/aliases.

---

## 7. Pinned MCP Tool Surface Audit

TrendRadar pinned commit exposes 27 FastMCP tools across several categories:

| Pinned MCP Tool | Category | In/Out Scope for Wave 5 | Vibe-Native Equivalent |
|---|---|---|---|
| `get_latest_news` | Query | In Scope | `query_intel(mode="current", ...)` |
| `get_trending_topics` | Query/Trend | In Scope | `analyze_intel_trend(topic=None)` |
| `get_latest_rss` | Query | In Scope | `query_intel(mode="current", source_type="rss")` |
| `search_rss` | Search | In Scope | `search_intel(query=..., source_type="rss")` |
| `get_rss_feeds_status` | Status | In Scope | `get_intel_status()` |
| `get_news_by_date` | Query | In Scope | `query_intel(mode="daily", date=...)` |
| `analyze_topic_trend` | Analytics | In Scope | `analyze_intel_trend(topic=...)` |
| `analyze_data_insights` | Analytics | In Scope | `analyze_intel_trend(insight_type=...)` |
| `analyze_sentiment` | Analytics | In Scope | `analyze_intel_sentiment(topic=...)` |
| `find_related_news` | Analytics | In Scope | `analyze_intel_trend(similar_to=...)` |
| `generate_summary_report`| Report | In Scope | `query_intel(mode="report", ...)` |
| `aggregate_news` | Query | In Scope | `query_intel(mode="aggregate", ...)` |
| `compare_periods` | Analytics | In Scope | `analyze_intel_trend(compare_period=...)` |
| `search_news` | Search | In Scope | `search_intel(query=...)` |
| `get_current_config` | Config/Status | In Scope | `get_intel_status()` |
| `get_system_status` | System/Status | In Scope | `get_intel_status()` |
| `check_version` | System/Status | In Scope | `get_intel_status()` |
| `trigger_crawl` | Trigger | In Scope | `trigger_intel_refresh()` |
| `sync_from_remote` | Storage | Out of Scope (Wave 6/7) | N/A (Local SQLite authority) |
| `get_storage_status` | Storage | In Scope | `get_intel_status()` |
| `list_available_dates` | Storage/Query | In Scope | `query_intel(mode="dates")` |
| `read_article` | Crawler | Out of Scope | N/A (Forbidden broad web fetch) |
| `read_articles_batch` | Crawler | Out of Scope | N/A (Forbidden broad web fetch) |
| `resolve_date_range` | Util | In Scope | `resolve_intel_date_range(expression)` |
| `get_channel_format_guide`| Notification | Out of Scope (Wave 6) | N/A |
| `get_notification_channels`| Notification | Out of Scope (Wave 6) | N/A |
| `send_notification` | Notification | Out of Scope (Wave 6) | N/A |

### Tool Execution & Security Boundaries
- Read-only tools query existing `native_intel_store.py` / `native_intel_service.py` functions without raw SQL injection.
- `trigger_intel_refresh` invokes native `run_fetch` and returns honest counts (`run_id`, `status`, `source_ok`, `source_failed`, `item_seen`, `item_new`).
- External Agent tool surface is hosted via Vibe HTTP API and Python service adapter.
- Internal page-aware Codex agent runtime (`agent-runtime/src/runtime.mjs`) continues to enforce `mcp_tool_call = TOOL_SURFACE_VIOLATION`.

---

## 8. Superseded Capabilities vs New Additions

### Superseded by Vibe:
1. Unified SQLite single authority (`native_intel.sqlite3`) with WAL and foreign keys vs plain JSON/TXT daily file dumps.
2. Wave 2 multi-field keyword/regex filtering, exclude-wins priority, and AI interest classification with dynamic fingerprinting.
3. Wave 3 fine-grained RSS display controls, per-source max age, global/per-feed freshness override, proxy support, and standalone display.
4. Wave 4 deterministic 3-mode reporting (`CURRENT`, `DAILY`, `INCREMENTAL`), cross-platform co-occurrence, platform coverage, velocity metrics, and observation/formal separation.
5. Isolated dual-provider AI routing (`cli-codex` subscription vs `api-compatible`) with zero auto-fallback leakage.

### Wave 5 Additions:
1. `backend/native_intel_ai.py`:
   - AI Deep Analysis with 6 core sections and honest input budget cap.
   - AI Translation with index-preserving batch protocol and missing index protection.
   - AI Entity & Concept Extraction with deterministic A-share code resolution.
   - AI Sentiment & Controversy Classification.
   - SHA-256 fingerprint-based caching for all AI artifacts.
2. `backend/native_intel_agent_tools.py`:
   - Vibe-native Agent Tool surface (`query_intel`, `search_intel`, `analyze_intel_trend`, `get_intel_status`, `trigger_intel_refresh`).
3. Database & Timeline:
   - `intel_ai_artifacts` table in `native_intel.sqlite3`.
   - Timeline AI fields migration (`ai_analysis_enabled`, `ai_analysis_mode`) with failure isolation.
4. Frontend:
   - Activated `ai_analysis` display region in `Settings.tsx` and `HotlistPanel.tsx`.
   - Item action buttons for Translate, Extract Entities, and Sentiment with non-destructive display.
