# TrendRadar 功能对齐矩阵（Parity Matrix）

> 长期维护的工程基线：以 pinned upstream
> `sansan0/TrendRadar@8ee26026ba6c11dec41a95fb3895a7162876caa1`（v6.10.0）为参照，
> 逐项记录 Vibe-Research Native Intel 的对齐状态。
>
> 规划路线：全量对齐 TrendRadar 功能，统一划分为 7 个规划波次（Wave 1 ~ Wave 7）。
> 遵循 FULL_TRENDRADAR_FUNCTIONAL_PARITY 原则，完整枚举上游已核验的全部配置项与功能路径，
> 不做单方面裁减或遗漏；后续波次均明确标记为 `PLANNED_WAVE_X`，循序渐进落地。
>
> 规则：
> - 状态枚举：`PARITY`（已对齐并验证） / `PLANNED_WAVE_N`（规划波次中实现）；
> - Vibe 实现为独立实现（Vibe-native），**不复制 TrendRadar GPL 代码**，不引入其
>   runtime / MCP / Docker / package 依赖；
> - 热榜数据来自第三方公开服务 NewsNow（`ourongxing/newsnow`，MIT 许可）的公共 HTTP API；
>   Vibe 直接调用该公开接口，行为契约（`status`/`items`/1-based 排名/HTTPS 域名校验）
>   经 2026-09-03 实测核验（cls-hot 13 条 / wallstreetcn-hot 10 条）。
> - 本文件是规划与状态文档，不是 Engineering Truth；实现以代码与测试为准。

## 7 个波次总览（Full Parity Roadmap）

- **Wave 1（当前波次）**：原生热榜基础设施（热榜抓取、双榜支持、排名历史、离榜检测、资讯源管理、数据时效真实性、E2E）
- **Wave 2**：关键词与 AI 智能过滤体系对齐（标题+简介过滤、AI 相关性筛选、个人兴趣配置、标签自更新、黑白名单）
- **Wave 3**：完整热榜源覆盖对齐（扩展剩余 9 个平台源，全量对齐）
- **Wave 4**：聚合、报告与时间线对齐（三类报告模式、时间窗口预设、相似新闻聚类、生命周期与走势预测）
- **Wave 5**：AI 分析与国际化（多模型摘要、实体提取、多语言翻译、情感分析、Agent MCP 综合查询）
- **Wave 6**：多渠道通知与存储（9 类通知渠道推送、TXT/HTML 静态报告输出、S3 远端对象存储）
- **Wave 7**：可视化、部署与自托管（WebUI/大屏、Docker/1Panel 一键部署）

---

## 上游参照事实（实测 / 读码核验）

| 事实 | 来源 |
| --- | --- |
| 热榜数据接口：`GET {NEWSNOW_BASE}/api/s?id={platform}&latest`，返回 `{status: success\|cache, items:[{id,title,url,mobileUrl,...}]}`，rank = items 的 1-based 序号 | `trendradar/crawler/fetcher.py`（行为研究）+ 2026-09-03 实测 |
| 11 个默认热榜平台 ID 与 expected_domain | `config/config.yaml`（platforms 块） |
| HTTPS + 域名白名单校验（防劫持），不匹配丢弃整平台 | `fetcher.py` 行为研究 |
| `status=cache` 与 `success` 都算成功 | `fetcher.py` 行为研究 |
| 掉榜 = 「抓取成功且历史上存在但当前列表缺失」；来源失败不得当掉榜 | 上游 README/存储语义 + 本项目独立推导 |
| 过滤模式支持双轨：`filter.method = keyword \| ai` | `config/config.yaml`（filter 块） |
| 报告输出支持三模：`report.mode = daily \| current \| incremental` | `config/config.yaml`（report 块） |
| 个人兴趣配置与标签更新提示词 | `config/ai_interests.txt`、`config/ai_filter/update_tags_prompt.txt` |
| 时间调度编排预设 | `config/timeline.yaml` |

---

## Wave 1（已实现交付物）：原生热榜基础设施

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| cls-hot（财联社热门） | **PARITY** | Vibe-native provider：`backend/native_intel_hotlist.py`；`source_type=hotlist`、`has_real_rank=true`、rank=1-based 真实排名 |
| wallstreetcn-hot（华尔街见闻） | **PARITY** | 同上 |
| Rank observation（真实排名观测） | **PARITY** | `intel_observations.rank`（仅 has_real_rank 来源写 rank；RSS 恒 NULL）；`intel_items.first_seen_at/last_seen_at/observation_count` |
| Rank history（排名轨迹读取） | **PARITY** | `GET /api/native-intel/items/{item_id}/rank-history` + `GET /api/native-intel/hotlist`（current/previous/delta 由观测推导，不落第二份 authority） |
| Off-list / 掉榜语义 | **PARITY** | 仅「来源本轮抓取成功 + 条目曾存在 + 当前榜单缺失」→ `OFF_LIST`；来源失败 → `UNKNOWN`；绝不写 rank=0/999 |
| Source enable / disable | **PARITY** | `intel_sources.enabled` + `PATCH /api/native-intel/sources/{id}`；禁用源不参与抓取；条目推导为 `DISABLED` 并保留末次 rank |
| Custom RSS（用户自建 RSS） | **PARITY** | `POST /api/native-intel/sources`（origin=user，UUID source_id，DB 持久化，软删除保留 provenance） |
| RSS（系统策展源） | **PARITY** | 既有能力保持：`news_sources.json` 降级为系统 seed，首次初始化入 DB |
| 单源失败隔离 / PARTIAL 语义 | **PARITY** | 既有 `intel_source_runs` + `RUN_STATUS_PARTIAL` 保持；热榜失败不影响 RSS 与其他热榜 |
| 数据时效真实性（Stale / Freshness Truth） | **PARITY** | 超过 6 小时未成功抓取自动降级为 `STALE`，UI 显示过期警告条与非实时状态，保留末次 rank 供审计，绝不伪造当前在榜 |
| A 股实体映射 | **PARITY** | 热榜条目走既有 `intel_entity_terms` / `intel_item_entities` 映射；StockData / Watchlist context 自动可见 |
| E2E 测试验证 | **PARITY** | `tests/e2e/hotlist-parity.browser.mjs` 真浏览器 + 真后端 SQLite 持久化与过期诚实性验证，CI 自动化接入 |

---

## Wave 2：关键词与 AI 智能过滤体系对齐

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 过滤模式双轨支持（filter.method = keyword / ai） | PLANNED_WAVE_2 | 上游配置支持切换关键词过滤与 AI 过滤双轨模式 |
| 本地关键词过滤（Keyword filtering） | PLANNED_WAVE_2 | 基于本地规则引擎提供标题与简介的多字段关键词匹配 |
| AI 智能相关性筛选（AI intelligent filter） | PLANNED_WAVE_2 | 上游 `trendradar/ai/filter.py`；Vibe 复用既有可插拔 LLM 适配层进行资讯相关性智能打分与过滤 |
| 个人兴趣偏好配置（AI interests） | PLANNED_WAVE_2 | 上游 `config/ai_interests.txt`；支持用户定制关注的行业、赛道与主题兴趣描述 |
| 标签自更新机制（AI tag update） | PLANNED_WAVE_2 | 上游 `config/ai_filter/update_tags_prompt.txt`；根据热点演进自动提炼与迭代新标签 |
| 黑名单/白名单机制（Blacklist / Whitelist） | PLANNED_WAVE_2 | 支持精准包含与排除过滤规则 |
| 多模式匹配（Regex / Wildcard） | PLANNED_WAVE_2 | 支持正则表达式与通配符规则匹配 |
| 分类标签与来源分组（Platform grouping） | PLANNED_WAVE_2 | 支持按平台、板块和主题维度定制视图聚合与筛选 |

---

## Wave 3：完整热榜源覆盖对齐

| 项目 | 状态 | 上游 platform id / expected_domain |
| --- | --- | --- |
| toutiao（今日头条） | PLANNED_WAVE_3 | `toutiao` / toutiao.com |
| baidu（百度热搜） | PLANNED_WAVE_3 | `baidu` / baidu.com |
| thepaper（澎湃新闻） | PLANNED_WAVE_3 | `thepaper` / thepaper.cn |
| bilibili-hot-search | PLANNED_WAVE_3 | `bilibili-hot-search` / bilibili.com |
| ifeng（凤凰网） | PLANNED_WAVE_3 | `ifeng` / ifeng.com |
| tieba（贴吧） | PLANNED_WAVE_3 | `tieba` / baidu.com |
| weibo（微博） | PLANNED_WAVE_3 | `weibo` / weibo.com |
| douyin（抖音） | PLANNED_WAVE_3 | `douyin` / douyin.com |
| zhihu（知乎） | PLANNED_WAVE_3 | `zhihu` / zhihu.com |

---

## Wave 4：聚合、报告与时间线对齐

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 当前快照报告（report.mode = current） | **PARITY** | Vibe Intel 资讯页 / MarketIntelPanel 即时渲染本地观测事实 |
| 每日汇总日报（report.mode = daily） | PLANNED_WAVE_4 | 上游定时日报生成模式；Vibe 规划与 DailyReview 面板深度整合 |
| 增量变化报告（report.mode = incremental） | PLANNED_WAVE_4 | 上游两抓取窗口间新上榜与异动增量对比报告 |
| 关键词与赛道分组（Keyword grouping） | **PARITY** | Vibe 本地实体词与赛道 hint 映射已实现结构化分组 |
| 时间窗口预设（Timeline presets） | PLANNED_WAVE_4 | 上游 `config/timeline.yaml` 编排预设与时间切片分析 |
| 多源归一化与相似新闻聚类（Similar news clustering） | PLANNED_WAVE_4 | 跨平台相同事件识别与聚类关联（按平台严格隔离原始 rank） |
| 关注度趋势（Trending topics） | **PARITY** | 既有 `GET /api/native-intel/trending` 跨源频次与实体环比统计 |
| 单话题位次轨迹走势（Topic trend） | PLANNED_WAVE_4 | 基于 rank-history 观测推导单话题在各榜单上的位次演变走势图 |
| 话题生命周期跟踪（Topic lifecycle） | PLANNED_WAVE_4 | 单话题自首见、爆发、衰退至掉榜的全生命周期状态机 |
| 爆发突发热点检测（Viral detection） | PLANNED_WAVE_4 | 基于排名跃升速率与多源共振的多维度异动突发检测算法 |
| 趋势预测分析（Trend prediction） | PLANNED_WAVE_4 | 话题热度延续性评估（严格保持 observation-only，不伪造投资权威） |
| 平台活跃度与横向对比（Platform comparison & activity） | PLANNED_WAVE_4 | 跨平台热点分发节奏、活跃度与覆盖度横向对比面板 |
| 关键词共现分析（Keyword co-occurrence） | PLANNED_WAVE_4 | 热点事件关联关键词与概念网络分析 |

---

## Wave 5：AI 分析与国际化

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 多模型智能摘要（AI Summarization） | PLANNED_WAVE_5 | 走 Vibe 可插拔 AI 适配层（支持 DeepSeek、Doubao、OpenAI 等） |
| AI 实体与概念提取（AI Entity Extraction） | PLANNED_WAVE_5 | 自动抽取非结构化资讯中的实体、企业与概念词 |
| 多语言热榜翻译（AI Translation） | PLANNED_WAVE_5 | 国际资讯与跨语言热榜双向翻译 |
| 情感倾向分类（Sentiment Analysis） | PLANNED_WAVE_5 | 资讯情绪倾向分类（仅客观事实标注，保持 observation-only 边界） |
| 实体检索与关联分析（Entity search） | **PARITY** | 既有 `intel_entity_terms` + StockData/Watchlist 结构化联动已覆盖 |
| Agent MCP 综合查询接口（MCP Query & Search） | PLANNED_WAVE_5 | 通过 Vibe MCP 向外部 Agent 暴露热榜位次、轨迹与实体分析工具 |
| Agent 按需触发抓取（MCP Crawl Trigger） | PLANNED_WAVE_5 | 现有 `POST /api/native-intel/refresh` 包装为 Agent MCP 工具 |
| 系统状态查询（MCP Status） | **PARITY** | 现有 `GET /api/native-intel/status` 提供抓取运行状态查询 |

---

## Wave 6：多渠道通知与存储

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 飞书机器人通知（Feishu Webhook） | PLANNED_WAVE_6 | 支持富文本消息卡片与告警推送 |
| 钉钉机器人通知（DingTalk Webhook） | PLANNED_WAVE_6 | 支持 Markdown 群机器人推送 |
| 企业微信通知（WeCom Webhook） | PLANNED_WAVE_6 | 支持图文卡片与即时推送 |
| Telegram 机器人通知（Telegram Bot） | PLANNED_WAVE_6 | 支持频道与群组自动化推送 |
| 邮件通知（Email / SMTP） | PLANNED_WAVE_6 | 支持 HTML 格式定时汇总与即时邮件投递 |
| Bark 移动端通知 | PLANNED_WAVE_6 | iOS 端即时轻量推送 |
| ntfy 通知 | PLANNED_WAVE_6 | 开源跨平台推送通知 |
| Slack 通知 | PLANNED_WAVE_6 | 工作区频道集成推送 |
| 通用 Webhook（Generic Webhook） | PLANNED_WAVE_6 | 自定义 HTTP POST JSON 数据投递 |
| TXT 本地报告输出 | PLANNED_WAVE_6 | 纯文本快照生成与本地离线导出 |
| HTML 独立静态报告输出 | PLANNED_WAVE_6 | 独立渲染的 HTML 报告文件导出 |
| 远端 S3 兼容对象存储归档 | PLANNED_WAVE_6 | 支持 MinIO / AWS S3 等对象存储热榜快照同步归档 |

---

## Wave 7：可视化、部署与自托管

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 独立 WebUI / 监控大屏（Dashboard & Wallboard） | PLANNED_WAVE_7 | 跨终端热点全景大屏与监控展示看板 |
| 一键部署模板（Docker Compose / 1Panel） | PLANNED_WAVE_7 | 容器化一键部署编排与 1Panel 应用商店集成 |

---

## 架构红线（约束原则）

- 不复制 TrendRadar GPL 源码，不引入其 runtime / Docker / package 作为依赖；
- 模块由 Vibe 独立实现与维护（`native_intel_*`），不引入 `trendradar_*` 模块命名；
- 任何「排名/热度」严格遵循 `observation_only`，不得未经决策层伪造为买卖权威建议；
- 跨平台数据必须按平台隔离排名轨迹，不得相互污染真实平台序号。
