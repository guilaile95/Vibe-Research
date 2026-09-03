# TrendRadar 功能对齐矩阵（Parity Matrix）

> 长期维护的工程基线：以 pinned upstream
> `sansan0/TrendRadar@8ee26026ba6c11dec41a95fb3895a7162876caa1`（v6.10.0）为参照，
> 逐项记录 Vibe-Research Native Intel 的对齐状态。
>
> 规则：
> - 每项只允许 `PARITY` / `SUPERSEDED_BY_VIBE` / `PLANNED_WAVE_N` / `ARCHITECTURE_ONLY`；
> - Vibe 实现为独立实现（Vibe-native），**不复制 TrendRadar GPL 代码**，不引入其
>   runtime / MCP / Docker / package 依赖；
> - 热榜数据来自第三方公开服务 NewsNow（`ourongxing/newsnow`，MIT 许可）的公共 HTTP API；
>   Vibe 直接调用该公开接口，行为契约（`status`/`items`/1-based 排名/HTTPS 域名校验）
>   经 2026-09-03 实测核验（cls-hot 13 条 / wallstreetcn-hot 10 条）。
> - 本文件是规划与状态文档，不是 Engineering Truth；实现以代码与测试为准。

## 上游参照事实（实测 / 读码核验）

| 事实 | 来源 |
| --- | --- |
| 热榜数据接口：`GET {NEWSNOW_BASE}/api/s?id={platform}&latest`，返回 `{status: success\|cache, items:[{id,title,url,mobileUrl,...}]}`，rank = items 的 1-based 序号 | `trendradar/crawler/fetcher.py`（行为研究）+ 2026-09-03 实测 |
| 11 个默认热榜平台 ID 与 expected_domain | `config/config.yaml`（platforms 块） |
| HTTPS + 域名白名单校验（防劫持），不匹配丢弃整平台 | `fetcher.py` 行为研究 |
| `status=cache` 与 `success` 都算成功 | `fetcher.py` 行为研究 |
| 掉榜 = 「抓取成功且历史上存在但当前列表缺失」；来源失败不得当掉榜 | 上游 README/存储语义 + 本项目独立推导 |

## Wave 1（本轮）范围

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| cls-hot（财联社热门） | **PARITY** | Vibe-native provider：`backend/native_intel_hotlist.py`；`source_type=hotlist`、`has_real_rank=true`、rank=1-based 真实排名 |
| wallstreetcn-hot（华尔街见闻） | **PARITY** | 同上 |
| Rank observation（真实排名观测） | **PARITY** | `intel_observations.rank`（仅 has_real_rank 来源写 rank；RSS 恒 NULL）；`intel_items.first_seen_at/last_seen_at/observation_count` |
| Rank history（排名轨迹读取） | **PARITY** | `GET /api/native-intel/items/{item_id}/rank-history` + `GET /api/native-intel/hotlist`（current/previous/delta 由观测推导，不落第二份 authority） |
| Off-list / 掉榜语义 | **PARITY** | 仅「来源本轮抓取成功 + 条目曾存在 + 当前榜单缺失」→ `OFF_LIST`；来源失败 → `UNKNOWN`；绝不写 rank=0/999 |
| Source enable / disable | **PARITY** | `intel_sources.enabled` + `PATCH /api/native-intel/sources/{id}`；禁用源不参与抓取 |
| Custom RSS（用户自建 RSS） | **PARITY** | `POST /api/native-intel/sources`（origin=user，DB 持久化，`news_sources.json` 不再是唯一真值） |
| RSS（系统策展源） | **PARITY** | 既有能力保持：`news_sources.json` 降级为系统 seed，首次初始化入 DB |
| 单源失败隔离 / PARTIAL 语义 | **PARITY** | 既有 `intel_source_runs` + `RUN_STATUS_PARTIAL` 保持；热榜失败不影响 RSS 与其他热榜 |
| A 股实体映射 | **PARITY**（Vibe 增强） | 热榜条目走既有 `intel_entity_terms` / `intel_item_entities` 映射；StockData / Watchlist context 自动可见（上游无此能力，SUPERSEDED_BY_VIBE 语义） |

## Wave 1B（下一批热榜平台，provider 表各加一行即可）

| 项目 | 状态 | 上游 platform id / expected_domain |
| --- | --- | --- |
| toutiao（今日头条） | PLANNED_WAVE_1B | `toutiao` / toutiao.com |
| baidu（百度热搜） | PLANNED_WAVE_1B | `baidu` / baidu.com |
| thepaper（澎湃新闻） | PLANNED_WAVE_1B | `thepaper` / thepaper.cn |
| bilibili-hot-search | PLANNED_WAVE_1B | `bilibili-hot-search` / bilibili.com |
| ifeng（凤凰网） | PLANNED_WAVE_1B | `ifeng` / ifeng.com |
| tieba（贴吧） | PLANNED_WAVE_1B | `tieba` / baidu.com |
| weibo（微博） | PLANNED_WAVE_1B | `weibo` / weibo.com |
| douyin（抖音） | PLANNED_WAVE_1B | `douyin` / douyin.com |
| zhihu（知乎） | PLANNED_WAVE_1B | `zhihu` / zhihu.com |

## Filtering

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 关键词过滤（本地 keyword） | SUPERSEDED_BY_VIBE | Vibe 已有本地实体词匹配（`intel_entity_terms`）+ 红线词过滤（`news_sources.json` redline_keywords，热榜标题同样适用）；无上游「关注关键词→报告」的配置面，本地映射是更强的等价物 |
| AI filter（LLM 相关性筛选） | PLANNED_WAVE_2 | 上游 `trendradar/ai/filter.py`；Vibe 侧下一 Wave 评估（须复用现有可插拔 AI 层，不引第二套 LLM） |
| AI interests（个人兴趣配置） | PLANNED_WAVE_2 | 上游 `config/ai_interests.txt` |
| AI tag update（标签自更新） | PLANNED_WAVE_2 | 上游 `config/ai_filter/update_tags_prompt.txt` |

## Rank / Observation

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| current rank | **PARITY** | Wave 1 交付（仅真实 rank，不伪造） |
| rank timeline / history | **PARITY** | Wave 1 交付（observations 全量保留 + 读取 API） |
| first seen / last seen | **PARITY** | 既有 `intel_items.first_seen_at / last_seen_at` |
| frequency（出现次数） | **PARITY** | 既有 `observation_count` |
| new item（新上榜） | **PARITY** | Wave 1 交付（`is_new` + rank history 首点 = 当前点；UI「新上榜」筛选） |
| off-list semantics | **PARITY** | Wave 1 交付（成功 run 推导，见上） |

## Analytics

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| trending topics（关注趋势） | PARITY（Vibe 语义） | 既有 `GET /api/native-intel/trending`（跨来源出现次数 + 实体环比，无伪造排名）；Wave 1 起热榜条目附带真实 current/previous rank 与 delta |
| topic trend（单话题轨迹） | PLANNED_WAVE_3 | 读取侧可由 rank-history + 观测聚合实现，UI 未做 |
| lifecycle（话题生命周期） | PLANNED_WAVE_3 | — |
| viral detection（爆发检测） | PLANNED_WAVE_3 | 上游为启发式；Vibe 待定义诚实阈值语义 |
| prediction（预测） | PLANNED_WAVE_3 | 上游为启发式；须先满足 investment authority 边界审查 |
| platform comparison（平台对比） | PLANNED_WAVE_3 | 数据已具备（observations per source），无 UI |
| platform activity（平台活跃度） | PLANNED_WAVE_3 | 同上 |
| keyword co-occurrence | PLANNED_WAVE_3 | — |
| sentiment（情感） | PLANNED_WAVE_N | 依赖 AI 层；明确不做「热度→买卖」映射 |
| similar news（相似新闻） | PLANNED_WAVE_3 | 现有 title_key 归一是基础 |
| entity search（实体检索） | PARITY（Vibe 增强） | 既有 `intel_entity_terms` + StockData/Watchlist context；SUPERSEDED_BY_VIBE（上游 MCP 检索 < 本地结构化映射） |

## Reports

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| current report（当前快照） | SUPERSEDED_BY_VIBE | Intel 页 / MarketIntelPanel 即时渲染本地观测 |
| daily report（日报） | PLANNED_WAVE_3 | 上游输出 TXT/HTML；Vibe 候选形态是 DailyReview 面板扩展，不新建第二套 output |
| incremental report | PLANNED_WAVE_3 | — |
| keyword grouping | SUPERSEDED_BY_VIBE | 本地实体/赛道（hint）分组已覆盖核心诉求 |
| platform grouping | PLANNED_WAVE_2 | 热榜 UI 按来源筛选已是一部分 |
| standalone HTML | PLANNED_WAVE_N | 上游为静态站点发布场景；Vibe 是本地应用，除非 Owner 明确要求否则不排期 |
| AI analysis（AI 分析报告） | PLANNED_WAVE_2 | 须走 Vibe 可插拔 AI 层 |

## AI

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| AI filtering | PLANNED_WAVE_2 | 见 Filtering |
| AI analysis | PLANNED_WAVE_2 | — |
| AI translation | PLANNED_WAVE_N | 中文用户价值低，除非 Owner 明确要求 |

## Scheduler

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 周期抓取 | PARITY（Vibe 语义） | 既有 `native_intel_service.start_scheduler` + 启动补偿抓取；上游 timeline.yaml 的多时点编排不做 |
| timeline presets | ARCHITECTURE_ONLY | 上游按 GitHub Actions / cron 编排；Vibe 本地常驻调度器语义不同，保留架构说明 |

## Notifications

| 项目 | 状态 |
| --- | --- |
| Feishu / DingTalk / WeCom / Telegram / Email / ntfy / Bark / Slack / generic webhook | PLANNED_WAVE_N（全部：上游核心卖点之一，但本地单用户产品当前无推送场景；逐项保留在矩阵，禁止静默删除） |

## Storage / Output

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| SQLite | PARITY（Vibe 语义） | 单库 `native_intel.sqlite3`（sources/runs/items/observations/entities），纳入完整数据包备份 |
| TXT 输出 | PLANNED_WAVE_N | — |
| HTML 输出 | PLANNED_WAVE_N | — |
| remote S3-compatible storage | PLANNED_WAVE_N | Vibe 是本地优先产品；远端存储与隐私边界冲突，需 Owner 单独决策 |

## Agent / MCP capability

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| query / search / analytics | SUPERSEDED_BY_VIBE | Vibe 自有 MCP（`backend/mcp_server.py`）暴露数据工具；资讯读取面已可经 `/api/native-intel/*` 复用；不引入 TrendRadar MCP |
| status | PARITY | `GET /api/native-intel/status` |
| crawl（agent 触发抓取） | PLANNED_WAVE_2 | 现有 `POST /api/native-intel/refresh` 已是等价物，MCP 侧包装待做 |

## 明确不引入（架构红线）

- TrendRadar runtime / Docker / Python package / MCP / `fastmcp` / TrendRadar DB / 第二套 output/
- `trendradar_*` 模块命名（长期 owner 是 Vibe：`native_intel_*`）
- 任何「排名/热度 → 投资建议」映射（Native Intel 保持 observation_only）
