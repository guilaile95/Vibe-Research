# TrendRadar 功能对齐矩阵（Parity Matrix）

> 长期维护的工程基线：以 pinned upstream
> `sansan0/TrendRadar@8ee26026ba6c11dec41a95fb3895a7162876caa1`（v6.10.0）为参照，
> 逐项记录 Vibe-Research Native Intel 的对齐状态。
>
> 规划路线：全量对齐 TrendRadar 功能，统一划分为 7 个规划波次（Wave 1 ~ Wave 7）。
> 不设单方面判定“不重要”或“跳过”的状态，后续波次均标记为 `PLANNED_WAVE_X`，循序渐进落地。
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

- **Wave 1（当前波次）**：原生热榜基础设施（热榜抓取、双榜支持、排名历史、离榜检测、资讯源管理、E2E）
- **Wave 2**：关键词过滤与分类体系对齐（标题+简介过滤、黑白名单、多模式匹配）
- **Wave 3**：完整热榜源覆盖对齐（扩展剩余 9 个平台源，全量对齐）
- **Wave 4**：聚合与时间线对齐（时间窗口预设、多源归一化、聚类分析）
- **Wave 5**：AI 分析与国际化（多模型摘要、实体提取、多语言翻译、情感分析、Agent MCP 分析）
- **Wave 6**：多渠道通知与存储（Bark/飞书/钉钉/TG/邮件通知、TXT/HTML/S3 远端存储）
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

---

## Wave 1（已实现交付物）：原生热榜基础设施

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| cls-hot（财联社热门） | **PARITY** | Vibe-native provider：`backend/native_intel_hotlist.py`；`source_type=hotlist`、`has_real_rank=true`、rank=1-based 真实排名 |
| wallstreetcn-hot（华尔街见闻） | **PARITY** | 同上 |
| Rank observation（真实排名观测） | **PARITY** | `intel_observations.rank`（仅 has_real_rank 来源写 rank；RSS 恒 NULL）；`intel_items.first_seen_at/last_seen_at/observation_count` |
| Rank history（排名轨迹读取） | **PARITY** | `GET /api/native-intel/items/{item_id}/rank-history` + `GET /api/native-intel/hotlist`（current/previous/delta 由观测推导，不落第二份 authority） |
| Off-list / 掉榜语义 | **PARITY** | 仅「来源本轮抓取成功 + 条目曾存在 + 当前榜单缺失」→ `OFF_LIST`；来源失败 → `UNKNOWN`；绝不写 rank=0/999 |
| Source enable / disable | **PARITY** | `intel_sources.enabled` + `PATCH /api/native-intel/sources/{id}`；禁用源不参与抓取；状态返回 `DISABLED` |
| Custom RSS（用户自建 RSS） | **PARITY** | `POST /api/native-intel/sources`（origin=user，UUID source_id，DB 持久化，软删除支持） |
| RSS（系统策展源） | **PARITY** | 既有能力保持：`news_sources.json` 降级为系统 seed，首次初始化入 DB |
| 单源失败隔离 / PARTIAL 语义 | **PARITY** | 既有 `intel_source_runs` + `RUN_STATUS_PARTIAL` 保持；热榜失败不影响 RSS 与其他热榜 |
| A 股实体映射 | **PARITY** | 热榜条目走既有 `intel_entity_terms` / `intel_item_entities` 映射；StockData / Watchlist context 自动可见 |
| E2E 测试验证 | **PARITY** | `tests/e2e/hotlist-parity.browser.mjs` 真浏览器 + 真后端 SQLite 持久化验证，CI 自动化接入 |

---

## Wave 2：关键词过滤与分类体系对齐

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 标题+简介过滤（Keyword filtering） | PLANNED_WAVE_2 | 上游关键词过滤配置；Vibe 将基于本地规则引擎提供标题与简介的多字段关键词匹配 |
| 黑名单/白名单机制（Blacklist / Whitelist） | PLANNED_WAVE_2 | 支持精准包含与排除过滤 |
| 多模式匹配（Regex / Wildcard） | PLANNED_WAVE_2 | 支持正则与通配符规则匹配 |
| 分类标签与来源分组（Platform grouping） | PLANNED_WAVE_2 | 支持按平台和主题维度定制视图聚合 |

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

## Wave 4：聚合与时间线对齐

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 时间窗口预设（Timeline presets） | PLANNED_WAVE_4 | 上游 timeline 抓取时点与时间切片预设 |
| 多源归一化与相似新闻聚合（Similar news clustering） | PLANNED_WAVE_4 | 跨平台相同事件识别与聚类关联（不污染各平台原始 rank） |
| 话题生命周期（Topic lifecycle） | PLANNED_WAVE_4 | 单话题自上榜至离榜全周期跟踪 |
| 爆发检测（Viral detection） | PLANNED_WAVE_4 | 排名跃升与多源共振突发检测 |
| 平台活跃度对比（Platform activity comparison） | PLANNED_WAVE_4 | 跨平台热点分发节奏与覆盖率对比 |

---

## Wave 5：AI 分析与国际化

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 多模型智能摘要（AI Summarization） | PLANNED_WAVE_5 | 走 Vibe 可插拔 AI 适配层（支持 DeepSeek、Doubao、OpenAI 等） |
| 实体提取（AI Entity Extraction） | PLANNED_WAVE_5 | 自动抽取事件关联实体与概念 |
| 多语言翻译（AI Translation） | PLANNED_WAVE_5 | 国际资讯与多语言热榜翻译 |
| 情感分析（Sentiment Analysis） | PLANNED_WAVE_5 | 资讯情绪倾向分类（仅客观事实标注，保持 observation-only 边界） |
| Agent MCP 分析能力（Agent MCP Analytics） | PLANNED_WAVE_5 | 通过 MCP 对外暴露热榜分析与多源综合查询接口 |

---

## Wave 6：多渠道通知与存储

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 飞书机器人通知（Feishu Webhook） | PLANNED_WAVE_6 | 支持消息卡片与告警推送 |
| 钉钉机器人通知（DingTalk Webhook） | PLANNED_WAVE_6 | 支持群机器人推送 |
| 企业微信通知（WeCom Webhook） | PLANNED_WAVE_6 | 支持图文推送 |
| Telegram 通知（Telegram Bot） | PLANNED_WAVE_6 | 支持频道与群组推送 |
| 邮件通知（Email / SMTP） | PLANNED_WAVE_6 | 支持定时汇总与即时邮件 |
| Bark / ntfy / Slack / Generic Webhook | PLANNED_WAVE_6 | 移动端与开发者通用推送 |
| 多格式本地存储（TXT / HTML 报告输出） | PLANNED_WAVE_6 | 支持快照生成与离线导出 |
| 远端存储集成（Remote S3-compatible storage） | PLANNED_WAVE_6 | 支持远端对象存储归档 |

---

## Wave 7：可视化、部署与自托管

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 独立 WebUI / 监控大屏（Dashboard & Wallboard） | PLANNED_WAVE_7 | 跨终端热点全景大屏与监控面板 |
| 一键部署模板（Docker Compose / 1Panel） | PLANNED_WAVE_7 | 容器化一键部署与自托管配置 |

---

## 架构红线（约束原则）

- 不复制 TrendRadar GPL 源码，不引入其 runtime / Docker / package 作为依赖；
- 模块由 Vibe 独立实现与维护（`native_intel_*`），不引入 `trendradar_*` 模块命名；
- 任何「排名/热度」严格遵循 `observation_only`，不得未经决策层伪造为买卖权威建议；
- 跨平台数据必须按平台隔离排名轨迹，不得相互污染真实平台序号。
