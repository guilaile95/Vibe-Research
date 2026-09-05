# TrendRadar 功能对齐矩阵（Parity Matrix）

> 长期维护的工程基线：以 pinned upstream
> `sansan0/TrendRadar@8ee26026ba6c11dec41a95fb3895a7162876caa1`（v6.10.0）为参照，
> 逐项记录 Vibe-Research Native Intel 的对齐状态。
>
> 规划路线：全量对齐 TrendRadar 功能，严格遵照 Owner 批准的波次路线图推进。
> 遵循 FULL_TRENDRADAR_FUNCTIONAL_PARITY 原则，完整枚举上游已核验的全部配置项、抓取特性与功能路径，
> 杜绝单方面裁减、隐匿或提前宣称 PARITY；后续波次均实事求是标记为 `PLANNED_WAVE_X`。
>
> 规则：
> - 状态枚举：`PARITY`（已在代码中完整实现并获自动化测试验证） / `PLANNED_WAVE_N`（规划波次中实现）；
> - Vibe 实现为独立实现（Vibe-native），**不复制 TrendRadar GPL 代码**，不引入其
>   runtime / MCP / Docker / package 依赖；
> - 热榜数据来自第三方公开服务 NewsNow（`ourongxing/newsnow`，MIT 许可）的公共 HTTP API；
>   Vibe 直接调用该公开接口，行为契约（`status`/`items`/1-based 排名/HTTPS 域名校验）
>   经 2026-09-03 实测核验（cls-hot 13 条 / wallstreetcn-hot 10 条）。
> - 本文件是规划与状态文档，不是 Engineering Truth；实现以代码与测试为准。

## 全量对齐波次总览（Full Parity Roadmap）

- **Wave 1（已合并验证）**：原生热榜基础设施（热榜抓取、双榜支持、真实排名历史、掉榜与失败隔离语义、资讯源管理、数据时效 STALE 真实性、HTTP 状态 API、真浏览器 E2E）
- **Wave 1B（已合并验证）**：剩余 9 个热榜平台源覆盖对齐（扩展今日头条、百度、澎湃、B站、凤凰网、贴吧、微博、抖音、知乎，达到 11 个默认热榜平台全量覆盖，支持轻量动态来源下拉筛选与系统源启停）
- **Wave 2（已实现交付物）**：关键词与 AI 智能过滤双轨体系（标题+简介过滤、filter.method = keyword / ai、AI 智能相关性打分、个人兴趣偏好配置 ai_interests、标签自更新 update_tags_prompt、黑白名单、多模式正则/通配符匹配、分类标签与平台分组、真浏览器与真 SQLite E2E）
- **Wave 3（已实现交付物）**：抓取高级能力、新鲜度过滤与代理展示体系（RSS 全局与单源独立的 max_age_days 新鲜度过滤、Crawler / RSS HTTP 代理支持并脱敏防泄露、display.standalone 独立免过滤展示区保留热榜真实排名、展示区域开关与排序控制、全区域关闭诚实空态、真浏览器与真 SQLite E2E 验证）
- **Wave 4**：聚合、三模报告与时间线走势对齐（三类报告输出模式 report.mode = current / daily / incremental、用户可配置关键词报告分组聚合、timeline.yaml 调度预设与时间切片、相似新闻聚类、单话题位次走势图、话题全生命周期跟踪、爆发异动突发检测、趋势预测分析、平台活跃度横向对比、关键词共现分析）
- **Wave 5**：AI 深度分析、国际化与 Agent MCP 体系对齐（多模型智能摘要、实体提取、多语言热榜翻译、情感倾向分类、Agent MCP 综合查询工具、Agent 按需触发抓取工具、Agent MCP 系统状态工具）
- **Wave 6**：多渠道推送通知与格式存储（9 类通知渠道推送飞书/钉钉/企微/TG/邮件/Bark/ntfy/Slack/Webhook、TXT 本地快照报告输出、HTML 独立静态报告输出、S3 兼容远端对象存储归档）
- **Wave 7**：可视化大屏、自托管部署与全量对齐闭环审计（独立 WebUI/监控大屏 Wallboard、Docker Compose / 1Panel 容器化一键部署、FULL_TRENDRADAR_FUNCTIONAL_PARITY 终局能力闭环审计 Capability Closure Audit）

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
| RSS 新鲜度天数过滤（全局与单源） | `config/config.yaml`（rss.max_age_days / feeds[].max_age_days） |
| 网络代理配置支持（爬虫与 RSS） | `config/config.yaml`（crawler.proxy / rss.proxy） |
| 独立免过滤展示区与区域开关 | `config/config.yaml`（display.standalone / display.regions） |
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
| Custom RSS（用户自建 RSS） | **PARITY** | `POST /api/native-intel/sources`（origin=user，UUID source_id，DB 持久化，软删除保留历史 provenance） |
| RSS（系统策展源 seed） | **PARITY** | 既有能力保持：`news_sources.json` 降级为系统 seed，首次初始化入 DB |
| 单源失败隔离 / PARTIAL 语义 | **PARITY** | 既有 `intel_source_runs` + `RUN_STATUS_PARTIAL` 保持；热榜失败不影响 RSS 与其他热榜 |
| 数据时效真实性（Stale / Freshness Truth） | **PARITY** | 超过 6 小时未成功抓取自动降级为 `STALE`，UI 显示非实时警告条与警示徽章，保留末次 rank 供审计，绝不伪造当前在榜 |
| HTTP 系统与抓取状态接口（HTTP Status API） | **PARITY** | `GET /api/native-intel/status` 实时返回抓取运行状态、成功/失败来源数与数据平面健康度 |
| A 股实体映射 | **PARITY**（Vibe 增强） | 热榜条目走既有 `intel_entity_terms` / `intel_item_entities` 映射；StockData / Watchlist context 自动可见 |
| E2E 测试验证 | **PARITY** | `tests/e2e/hotlist-parity.browser.mjs` 真浏览器 + 真后端 SQLite 持久化与过期诚实性验证，CI 自动化接入 |

---

## Wave 1B（已实现交付物）：剩余 9 个热榜平台源覆盖对齐

| 项目 | 状态 | 上游 platform id / expected_domain | 说明 |
| --- | --- | --- | --- |
| toutiao（今日头条） | **PARITY** | `toutiao` / toutiao.com | Vibe-native provider，NewsNow 契约实测验证（30条），1-based 真实排名，域名防劫持校验通过 |
| baidu（百度热搜） | **PARITY** | `baidu` / baidu.com | Vibe-native provider，NewsNow 契约实测验证（30条），1-based 真实排名，域名防劫持校验通过 |
| thepaper（澎湃新闻） | **PARITY** | `thepaper` / thepaper.cn | Vibe-native provider，NewsNow 契约实测验证（20条），1-based 真实排名，域名防劫持校验通过 |
| bilibili-hot-search | **PARITY** | `bilibili-hot-search` / bilibili.com | Vibe-native provider，NewsNow 契约实测验证（30条），1-based 真实排名，域名防劫持校验通过 |
| ifeng（凤凰网） | **PARITY** | `ifeng` / ifeng.com | Vibe-native provider，NewsNow 契约实测验证（12条），1-based 真实排名，域名防劫持校验通过 |
| tieba（贴吧） | **PARITY** | `tieba` / baidu.com | Vibe-native provider，NewsNow 契约实测验证（30条），1-based 真实排名，域名防劫持校验通过 |
| weibo（微博） | **PARITY** | `weibo` / weibo.com | Vibe-native provider，NewsNow 契约实测验证（30条），1-based 真实排名，域名防劫持校验通过 |
| douyin（抖音） | **PARITY** | `douyin` / douyin.com | Vibe-native provider，NewsNow 契约实测验证（30条），1-based 真实排名，域名防劫持校验通过 |
| zhihu（知乎） | **PARITY** | `zhihu` / zhihu.com | Vibe-native provider，NewsNow 契约实测验证（20条），1-based 真实排名，域名防劫持校验通过 |
| 动态来源下拉筛选（Dynamic Source Filter） | **PARITY** | UI 交互能力 | 前端 `HotlistPanel` 与 `hotlistView` 升级为通用 `source:<source_id>` 动态下拉筛选，杜绝硬编码按钮 |
| 11 平台设置管理（Settings 11 Platforms） | **PARITY** | 来源管理能力 | 设置页完整呈现 11 个系统热榜源，支持用户独立启停，跨刷新持久化，系统源删除保护（409） |

---

## Wave 2（已实现交付物）：关键词与 AI 智能过滤双轨体系

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 过滤模式双轨支持（filter.method = keyword / ai） | **PARITY** | `backend/native_intel_filter.py` + `backend/native_intel_store.py`；支持本地关键词与 AI 语义双轨模式，独立配置持久化于 `intel_filter_profiles`，支持无缝热切换且配置不丢失 |
| 本地关键词过滤语法与 UI 映射（Keyword filtering parity） | **PARITY** (VIBE_NATIVE_SUPERSET) | `evaluate_keyword_rules()`；完整对齐上游 required（AND 必须词）、includes（OR 普通词）、excludes（排除词）、filter_terms（全局过滤词）、global_excludes（Exclude Wins 优先原则）及 max_count 组内条目上限；且上游仅对 title 过滤，Vibe 原生扩展对 title + summary 同时匹配（VIBE_NATIVE_SUPERSET）。前端 `Settings.tsx` 与 `FilterSettingsModal.tsx` 完整提供并映射 required（逗号分隔）、filter_terms、max_count、group.name 等表单交互与实时保存校验。 |
| AI 智能相关性筛选（AI intelligent filter） | **PARITY** | `classify_items_batch()`；复用既有统一 AI 适配层（Codex / OpenAI-compatible），批量相关性打分（min_score 阈值筛选），严格隔离不可信输入，失败诚实上报不造假；三态缓存（CLASSIFIED/NOT_RELEVANT/ERROR）精准隔离 |
| 个人兴趣偏好配置（AI interests） | **PARITY** | `extract_interest_tags()`；支持自然语言兴趣描述，结构化提取多标签并计算 profile fingerprint 保持确定性；统一 AI 密钥零落盘防泄露保护 |
| 标签增量更新与阈值分流（AI tag update & thresholding orchestration） | **PARITY** | `update_interest_tags()` 与 `apply_interest_update()`；对比新旧标签集计算 `change_ratio`；低于阈值增量继承（INCREMENTAL）且保留未增标签的 not_relevant 缓存；达到或超过阈值（支持 0.0 边界）执行 Fail-Closed fresh extract 并触发全量重跑（FULL）。前端通过 `applyNativeIntelInterestUpdate` 获得确定性决策与最新 fingerprint，再编排执行分类；UI 提供“增量对比更新”与“保存并执行 AI 分类”双按钮。 |
| 黑名单/白名单机制（Blacklist / Whitelist） | **PARITY** | 全局排除词 `global_excludes` + 分组包含/必须/排除规则，精确控制展示条目 |
| 匹配模式对齐（Regex / Substring / Wildcard Truth） | **PARITY** | 上游源码经严格核验确认无独立通配符 DSL（UPSTREAM_HAS_NO_STANDALONE_WILDCARD_DSL），其过滤语法完全由纯文本子串包含与 `/regex/` 正则构成；Vibe 完整实现纯文本子串包含与 `/regex/` 正则语法（支持修饰符并默认不区分大小写），达到上游语法完整等价与超集覆盖。 |
| 分类标签与来源分组（Platform grouping） | **PARITY** | 关键词分组与 AI 兴趣标签双轨打标，前端 `HotlistPanel` 动态渲染彩色徽章并支持 `mode=my_interests` 过滤视图与筛选设置弹窗；支持热榜与 RSS 全源过滤与诚实状态栏呈现 |
| E2E 测试验证 | **PARITY** | `tests/e2e/interest-filter.browser.mjs` 真浏览器 + 真后端 SQLite 持久化、模式切换、标签提取与设置同步验证，CI 自动化接入 |

---

## Wave 3（已实现交付物）：抓取高级能力、新鲜度过滤与代理展示体系

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| RSS 全局新鲜度过滤（Global max_age_days） | **PARITY** | `backend/native_intel_freshness.py` + `backend/native_intel_store.py`；按发布时间过滤陈旧历史 RSS，未标注时间条目保留（PUBLISHED_AT_UNKNOWN），非破坏性保留 SQLite 原始数据，前端与设置页完整可配置并实时生效 |
| RSS 单源独立新鲜度过滤（Per-feed max_age_days） | **PARITY** | `intel_sources.max_age_days`；支持单源覆盖全局（NULL 继承全局，0 禁用新鲜度过滤，正整数指定天数），前端来源列表提供独立下拉/输入，跨刷新持久化 |
| 爬虫与抓取代理支持（Crawler / RSS Proxy） | **PARITY** | `backend/native_intel_hotlist.py` + `backend/native_intel_service.py`；支持配置热榜爬虫与 RSS 抓取代理通道（HTTP/HTTPS），RSS 代理支持自动回退爬虫代理，密码严格脱敏防泄露，来源失败严格隔离 |
| 独立免过滤展示区（display.standalone） | **PARITY** | `GET /api/native-intel/standalone`；支持配置独立重点来源，绕过关键词与 AI 个人兴趣过滤，热榜条目保留真实位次与轨迹，RSS 条目遵循时效过滤 |
| 展示区域控制与顺序（Display region ordering & toggle） | **PARITY** | `GET/PUT /api/native-intel/config`；支持 hotlist、rss、standalone 区域独立启停，按 `region_order` 自定义上下顺序，全部关闭时显示诚实空态组件 `all-regions-disabled-empty` |
| E2E 测试验证 | **PARITY** | `tests/e2e/wave3-display-controls.browser.mjs` 真浏览器 + 真后端 SQLite 持久化、时效切换、免过滤独立区、区域动态排序与全关空态验证，CI 自动化接入 |

---

## Wave 4：聚合、三模报告与时间线走势对齐

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 当前快照报告模式（report.mode = current） | **PARITY** | 原生 CURRENT 最新来源列表；GET 预览 / POST 生成；`/intel` 报告页展示分组结果，不提前实现 Wave 6 推送与导出 |
| 每日汇总日报模式（report.mode = daily） | **PARITY** | Asia/Shanghai 零点（含）至当前观测时刻的当天汇总；包含早先列表，沿用 Wave 3 RSS freshness；不修改 DailyReview |
| 增量变化报告模式（report.mode = incremental） | **PARITY**（明确扩展） | 同一 SQLite 中持久 cursor；成功才推进。新 source/item、标题/发布时间/真实位次变化；重复观察不当新增。上游仅新标题/URL；Vibe 的有效变化是显式 deterministic 扩展 |
| 用户关键词报告分组（Keyword grouping in reports） | **PARITY** | 复用 Wave 2 唯一规则；关键词/平台/来源分组、第一命中组、组级上限优先、位置/计数排序；RSS 发布时间排序且 rank 恒 NULL |
| 时间窗口预设（Timeline presets） | **PARITY** | always_on / morning_evening / office_hours / night_owl / custom；半开区间、跨午夜、非法重叠 422；现有 fetch loop 执行报告机会，once/config 可恢复，无第二 daemon |
| 相似新闻（Similar news） | **PARITY** | 真实算法是标题 SequenceMatcher ratio，阈值 0.6，排除相同标题；不是事件识别或语义聚类模型 |
| 关注度趋势（Trending topics） | **PARITY** | 既有 `GET /api/native-intel/trending` 跨源频次与实体环比统计 |
| 日桶话题趋势（Topic daily trend） | **PARITY** | 每来源/每日不同标题计数，来源数/平台数/环比；明确 RAW_HISTORY 或 CURRENT_ELIGIBLE，缺采集不冒充零 |
| 单话题位次轨迹走势（Topic rank timeline） | **PARITY** | 单 source/item 的真实 observation rank 折线与时间卡片；微博/百度分开，不生成综合排名，RSS 不入排名 |
| 话题生命周期跟踪（Topic lifecycle） | **PARITY** | pinned 的前3/后3日与峰值简单规则：上升期/衰退期/爆发期/稳定期；不是正式状态机，返回实际输入和依据 |
| 爆发突发热点检测（Viral detection） | **PARITY** | 今日/昨日 >=3；零基线至少5。是每日条数阈值，不是原规划中未经证实的多维模型 |
| 趋势预测分析（Trend prediction） | **PARITY** | 近期已出现日桶末次增长严格 >30%，规则强度0.6/0.7/0.9，默认>=0.7；UI 明确“趋势推断（规则）”，不是概率或 AI |
| 14 天分析（14_DAY_ANALYTICS） | **PARITY** | 14 天 + 前 14 天比较；5,000 行分批聚合，432,000 条历史回归核对精确聚合，不再因 raw rows >100k 拒绝 |
| 30 天分析（30_DAY_ANALYTICS） | **PARITY** | 30 天 + 前 30 天比较；同一 SQLite 分批聚合；统计不截断，仅轨迹返回最近 10,000 点并显式标注，附精确总数 |
| 平台活跃度与横向对比（Platform comparison & activity） | **PARITY**（原生差异见契约） | Hotlist 逐来源 + RSS 逐来源 + RSS 分组汇总行；汇总行不能与单源行再次求和。日去重数/话题命中/首次观测数/真实排名观察/前窗变化，RSS 无排名；source-run 计数替代文件名更新频率 |
| 关键词组共现（Keyword co-occurrence） | **PARITY**（Owner 指定差异） | 按 Native Intel item identity 同时命中 Wave 2 Group A/B 计一次；热榜身份包含来源，同一故事跨平台可能分别计数，不声称故事级跨来源去重。附样本，不推断因果 |
| 新出现区域（new_items） | **PARITY** | 现有 display config 正式启用 slot；NEW_ON_LIST（每平台）与 NEWLY_OBSERVED（首次本地 RSS，非刚发布）独立 badge；沿用 scope/freshness/组上限 |

Wave 4 行为证据：[独立输入输出契约](NATIVE_INTEL_WAVE4_CONTRACT.md)；
`backend/tests/test_native_intel_reporting.py` 的真实 SQLite 定向回归；
包括 432,000 条历史下 CURRENT/DAILY/INCREMENTAL 与 14/30 天精确聚合、失败来源日报真值、重新启用边界；
`frontend/tests/e2e/wave4-report-analytics.browser.mjs` 的 Chromium → FastAPI → 隔离 SQLite 六场景，
加入既有 Intel digest CI job。PARITY 是这里列明的已实现并自动验证行为，不替代项目经理 Independent Gate；
与 pinned 的差异及计算上限均以契约为准。

---

## Wave 5：AI 深度分析、国际化与 Agent MCP 体系对齐

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 多模型智能摘要（AI Summarization） | PLANNED_WAVE_5 | 走 Vibe 可插拔 AI 适配层（支持 DeepSeek、Doubao、OpenAI 等） |
| AI 实体与概念提取（AI Entity Extraction） | PLANNED_WAVE_5 | 自动抽取非结构化资讯中的实体、企业与概念词 |
| 多语言热榜翻译（AI Translation） | PLANNED_WAVE_5 | 国际资讯与跨语言热榜双向翻译 |
| 情感倾向分类（Sentiment Analysis） | PLANNED_WAVE_5 | 资讯情绪倾向分类（仅客观事实标注，保持 observation-only 边界） |
| 实体检索与关联分析（Entity search） | **PARITY** | 既有 `intel_entity_terms` + StockData/Watchlist 结构化联动已覆盖 |
| Agent MCP 综合查询接口（MCP Query & Search） | PLANNED_WAVE_5 | 通过 Vibe MCP 向外部 Agent 暴露热榜位次、轨迹与实体分析工具 |
| Agent 按需触发抓取（MCP Crawl Trigger） | PLANNED_WAVE_5 | 将现有 `POST /api/native-intel/refresh` 包装为 Agent MCP 工具暴露 |
| Agent MCP 系统状态工具（MCP Status Tool） | PLANNED_WAVE_5 | 向外部 Agent 暴露 Native Intel 运行状态与健康度查询 MCP 工具（区别于已有的 HTTP API） |

---

## Wave 6：多渠道推送通知与格式存储

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

## Wave 7：可视化大屏、自托管部署与全量对齐闭环审计

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 独立 WebUI / 监控大屏（Dashboard & Wallboard） | PLANNED_WAVE_7 | 跨终端热点全景大屏与监控展示看板 |
| 一键部署模板（Docker Compose / 1Panel） | PLANNED_WAVE_7 | 容器化一键部署编排与 1Panel 应用商店集成 |
| 终局能力闭环审计（Capability Closure Audit） | PLANNED_WAVE_7 | 针对全部上游特性的全量实测与工程闭环核验（FULL_PARITY 终局验收） |

---

## 架构红线（约束原则）

- 不复制 TrendRadar GPL 源码，不引入其 runtime / Docker / package 作为依赖；
- 模块由 Vibe 独立实现与维护（`native_intel_*`），不引入 `trendradar_*` 模块命名；
- 任何「排名/热度」严格遵循 `observation_only`，不得未经决策层伪造为买卖权威建议；
- 跨平台数据必须按平台隔离排名轨迹，不得相互污染真实平台序号。
