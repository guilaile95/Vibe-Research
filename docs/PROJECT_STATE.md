# 项目当前状态

> 文档基准：分支 `refactor/portfolio-advice-architecture-v01`；架构实现提交为 `0ee21aa`（当前 HEAD 以 `git rev-parse HEAD` 为准）
> 仅描述仓库内已实现能力；不包含密钥、持仓内容或代理敏感配置。

## 1. 技术栈与数据存储

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 | React 19 + TypeScript + Vite 6 + Tailwind | 默认开发端口 `:5899`（`frontend/vite.config.ts`） |
| 后端 | FastAPI + Uvicorn | 默认 `:8900`（`backend` + README） |
| A 股数据 | `backend/astock.py` + 仓库内 `a-stock-data/` | 东财等公开接口；`em_get` 固定直连 |
| 全球指数/美港股子集 | `backend/gstock.py` + `global-stock-data/` | 复用 `astock.em_get` |
| 持仓 | `backend/portfolio.py` | 默认 `~/.vibe-research/portfolio.json`（`VR_DATA_DIR` 可覆盖） |
| 复盘磁盘缓存 | `backend/daily_review_cache.py` | `daily_review_latest.json`（同上数据目录） |
| 复盘历史 | `review_store` / `review_history` | SQLite（如 Windows 下 `%LOCALAPPDATA%/VibeResearch/daily_reviews.sqlite3`） |
| 模型接入 | 前端 localStorage `vr-llm` + 后端 `chat` / `cli_runtime` | API 或本机 CLI 订阅；密钥不进仓库 |

版本线索：`frontend/package.json` 为 `0.1.3`；schema 如 `daily-review-v0.1`、`portfolio-advice-v0.1`。

## 2. 每日复盘九维结构

- **客观数据包**（`generate_daily_review`，schema `daily-review-v0.1`）主要包含：
  - `data_health.components`：indices / global_indices / breadth / emotion / turnover / industry_boards / concept_boards / region_boards
  - `market_environment`：indices、global_indices、breadth
  - `sector_rotation`：industry / concept / region + highlights
  - `short_term_emotion`
  - `capital_activity`
  - 顶层 `status`：`normal` | `partial` | `unavailable`
- **AI 分析输出**（`daily_review_ai_prompt.NINE_DIMENSION_HEADINGS`）固定九个二级标题：
  1. 市场整体
  2. 市场情绪与赚钱效应
  3. 涨停结构
  4. 主线题材
  5. 核心与高活跃个股
  6. 催化与公开信息
  7. 盘面本质与风险状态
  8. 明日观察点
  9. 复盘总结

## 3. GET `/api/daily-review`

- 定义：`backend/app.py` → `daily_review_snapshot`
- 调用：`daily_review.get_daily_review_for_display()`
- 响应：`{ "data": <复盘包>, "cache_meta"?: { source, stale, refreshing, saved_at, age_seconds, refresh_failed, refresh_error } }`
- `normal` / `partial` / `unavailable` 均为 HTTP 200；聚合逃逸异常 → 502
- **不接受** date/refresh 查询参数；不做历史日期查询
- 文档注释明确：持仓建议等业务走 `generate_daily_review` fresh 路径，不用本接口 stale 结果

相关：`POST /api/daily-review/analyze`（流式 AI 九维）、历史 save/list/compare 等路由。

## 4. Stale-while-revalidate

展示路径 `get_daily_review_for_display`：

1. 内存新鲜缓存 → 立即返回（`stale=false`）
2. 无内存但有磁盘「最近成功」包 → 返回旧结果（`stale=true`）并 **single-flight** 后台刷新
3. 皆无 → 同步 `generate_daily_review`

前端 `frontend/src/pages/DailyReview.tsx` 根据 `cache_meta.stale` 展示「当前显示上次成功结果，后台正在刷新」等提示并轮询。

## 5. 内存缓存与磁盘最近成功复盘

| 机制 | 位置 | 要点 |
|------|------|------|
| 进程内复盘缓存 | `daily_review._review_cache` | TTL **300s**；single-flight 聚合锁 |
| 子模块缓存 | `market._CACHE` 等 | 与复盘共用 TTL 量级 |
| 磁盘最近成功 | `daily_review_cache` → `daily_review_latest.json` | 重启后可 stale 展示 |
| SQLite 历史 | `review_store` / 显式 save API | 与运行时缓存分离，GET 展示不自动写库 |

仅高质量 `normal` / `partial` 写入内存与磁盘（见 `generate_daily_review` 文档字符串）。

## 6. normal / partial / unavailable 覆盖规则

- 核心组件：`indices`、`breadth`、`emotion`、`industry_boards`、`concept_boards`
- 可选组件：`global_indices`、`turnover`、`region_boards`
- **关键组件 unavailable 的 partial / 整体 unavailable 不覆盖已有 normal**（`cf535b8` 及相关 persist 逻辑）
- 刷新失败：展示路径可保留旧 normal，并置 `refresh_failed`（不泄漏底层网络栈）

## 7. 全 A 分页、直连、页级重试与完整性

- `astock.a_share_snapshot`：东财 clist 分页；失败 **整页失败则整体抛错**，不返回已抓部分列表
- `em_get`：**固定直连**，`trust_env=False`，不读系统/环境代理
- `_em_get_page_with_retries`：同一页内有限重试瞬时网络错误；不回退从第 1 页重跑
- 提交 `f2ae80c`：`fix: stabilize A-share snapshot paging requests`
- 验收量级：成功时约 5500–5900 只；冷抓约 80–110 秒（环境相关）

## 8. POST `/api/portfolio/advice`

- 定义：`app.portfolio_advice`
- 链路：`get_portfolio` → `generate_daily_review`（**fresh**）→ context → prompt → 模型 → `validate_portfolio_advice`
- 请求：`user_request?` + `llm`（`LLMConfig`）；**禁止**客户端注入 portfolio/context/messages
- 状态码：空持仓 409；广度不可用等市场核心数据 503；模型/输出无效 502；参数 400；其它 500
- 不写持仓文件、不写复盘历史

## 9. breadth unavailable 时 503 fail-closed

- `portfolio_advice_service`：`_market_breadth_unavailable` 为真时抛 `PortfolioAdviceMarketDataError`
- API 映射 **503** + 安全文案，**不调用模型**（见 `test_portfolio_advice_market_guard`）

## 10. 持仓建议动作、比例档位与 validator

- 动作：`add` / `hold` / `reduce` / `sell` / `watch` / `avoid`（`portfolio_advice_prompt.ACTIONS`）
- 账户层：`hold` / `reduce_risk` / `selective_add` / `defensive`
- 比例字段：`execution_size_pct_of_holding`（相对**当前该股持股数量**）
  - add：10 或 20
  - reduce：10 / 20 / 30
  - sell：固定 100
  - hold/watch/avoid：null
- 置信度上限：low≤10，medium≤20，high≤30；partial 市场时 add 最多 10、reduce 最多 20
- 条件数字可追溯；禁止无来源阈值、市场冲击类模板话术、reduce/sell 失效条件与风险控制冲突
- 第一版 **不做 T**（无 `t_trade`）

## 11. add 数量与预计金额

- 提交 `5dec970`：`feat: calculate executable add quantities`
- 后端重算（覆盖模型结构字段）：
  - `raw = shares × pct / 100`
  - `execution_quantity = floor(raw / 100) × 100`；不足 100 股 → null
  - `estimated_amount = quantity × current_price`（`Decimal`，分位四舍五入）
- 示例：1500 股、14.29 元、add 10% → 100 股、1429.00；add 20% → 300 股、4287.00
- 文字中的建议买入股数/投入金额须与后端一致；禁止账户资金/总资产比例语义

### 受控端到端验收（已完成，`82b2096` 之后）

| 场景 | 输入 | 结果 |
|------|------|------|
| A | 持股 1500，现价 14.29，add 10% | `execution_quantity=100`，`estimated_amount=1429.00` ✓ |
| B | 持股 1500，现价 14.29，add 20% | `execution_quantity=300`，`estimated_amount=4287.00` ✓ |
| C | 持股 300，现价 14.29，add 10% | `execution_quantity=null`，`estimated_amount=null`，保留 add 与 10% 比例，含不足 100 股限制文案 ✓ |
| 覆盖 | 模型返回 quantity=999、amount=99999 | 后端重算覆盖为正确值 ✓ |

validator 验证：正确股数/金额通过，错误股数/金额拒绝，「相对当前持股」通过，「使用账户资金比例」拒绝。

浏览器受控展示验证（场景 B）：相对当前持股加仓 20%；建议买入 300 股；预计所需金额约 ¥4,287.00；不显示 0 股或 ¥0。

回归：validator/service/api 三套件 **136 passed**；`npm run build` 成功。无产品代码改动，验收结束时工作区干净。

## 12. 前端展示

| 页面 | 文件 | 要点 |
|------|------|------|
| 每日复盘 | `frontend/src/pages/DailyReview.tsx` | SWR 提示、`cache_meta`、九维 AI 流式分析入口 |
| 持仓 | `frontend/src/pages/Portfolio.tsx` | 本地持仓 +「生成持仓操作建议」 + 账户资金 |
| API 类型 | `frontend/src/lib/api.ts` | `PortfolioAdviceHoldingAdvice` 含 `execution_quantity`、`estimated_amount` 等；`AccountProfileData` 含 `total_assets`、`available_cash`、`updated_at` |

add 卡片文案：相对当前持股加仓；建议买入数量；预计所需金额（约 ¥…）；执行前确认可用资金。null 时不展示 0 股 / ¥0。

## 13. 账户资金（手工填写）

- 模块：`backend/account_profile.py`；存储：`~/.vibe-research/account_profile.json`（`VR_DATA_DIR` 可覆盖）
- 独立于 `portfolio.json`，不重复保存持仓数量或成本价
- 字段：`total_assets`、`available_cash`、`updated_at`（后端生成，拒绝客户端提交）
- 校验：`total_assets > 0`；`available_cash >= 0`；`available_cash <= total_assets`；拒绝 NaN/Infinity/字符串/布尔值/未知字段；金额保留两位小数
- 原子写入（临时文件 + `os.replace`）；UTF-8
- API：`GET /api/account-profile`（未配置 → `{ configured: false, data: null }`）、`PUT /api/account-profile`（后端校验 + 生成 `updated_at`）
- 前端：Portfolio 页「账户资金」区；未配置显示「尚未配置账户资金」+「填写账户资金」按钮；已配置显示总资产/可用现金/更新时间 +「编辑」按钮；弹窗与持仓编辑风格一致；可用现金大于总资产时禁止保存；保存失败保留输入；未配置不显示 ¥0
- 账户资金手工维护本身不参与 AI Prompt、动作裁决、账户仓位计算或加仓数量限制；持仓建议完成 Validator 后仅追加 `account_funding` / `account_metrics` 只读指标
- **已知 BUG**（`fe54b8f`）：前端的 `request()` 通用解包 (`payload?.data ?? payload`) 导致 `getAccountProfile()` 返回内层数据而非 `{configured, data}` 包装，UI 永远显示「尚未配置账户资金」。已修复于 `fix: restore account funding profile UI`（见第 14 节）。
  - `request()` 增加 `unwrapData` 选项（默认 `true`），account-profile 使用 `unwrapData: false`
  - `loadAcct`/`saveAcct` 正确按 `AccountProfileResponse` 处理响应
  - 新增加载中 / 加载失败（含重试按钮）/ 未配置三种状态
  - `account_profile.py`：写入失败时清理临时文件；新增并发、残留临时文件测试

## 14. 账户资金后续修复提交

| 短哈希 | 说明 |
|--------|------|
| `88a1f83` | fix: restore account funding profile UI（`unwrapData`） |
| `f3d90af` | fix: harden account funding persistence and submit state |

## 15. 持仓安全新增 / 精确编辑 / 删除（已验收）

**功能提交**：`9932601` — `feat: add portfolio holding exact edit and delete confirm`
（验收后文档刷新见后续 `docs:` 提交；当前能力以该功能提交与代码为准。）
### 能力摘要

| 能力 | 行为 |
|------|------|
| 新增 | `POST /api/portfolio/holding`：新代码新增；**同代码仍加权合并**成本 |
| 精确编辑 | `PUT /api/portfolio/holding`：**精确替换** shares/cost；不加权；不 upsert |
| 安全删除 | 前端确认弹窗 + 失败可见错误；`DELETE` 只移 holdings，**不写** closed |
| 数量输入 | 保留原始字符串；**不再**静默把 `-100` 变成 `100` |
| 账户资金 | 只读指标已接入持仓建议结果 (`account_funding` & `account_metrics`)；**尚未参与动作裁决**；可用现金约束留待下一阶段 |

### 后端

- `portfolio.update_holding(code, shares, cost)`：精确覆盖；code 不存在 → `ValueError` → HTTP **404**
- `HoldingUpdate`：`extra=forbid`；shares 严格 **int**；拒绝 bool / 字符串 / 小数
- shares：必须 `> 0` 正整数；**不要求** 100 股整手
- cost：有限数值（拒 bool/字符串/NaN/Infinity）；**允许负值**（既有语义）
- 失败不写 `portfolio.json`；不改 `account_profile.json`；不调 advice
- 持仓建议只读账户资金指标：在 `validator` 返回权威结果后纯函数装配 `account_funding` 与 `account_metrics`，不触碰模型 Prompt、上下文与 validator。高精度 `Decimal(ROUND_HALF_UP)` 计算。未配置/损坏安全降级。

### 前端（`Portfolio.tsx` + `api.updateHolding`）

- 编辑：代码只读预填；保存一次 PUT；取消不请求；失败弹窗不关、输入保留、列表旧值不变
- 删除：确认展示名称/代码、数量、「删除只移除当前持仓记录」；取消不 DELETE；失败不静默
- `validateShares`：空/0/负/小数/非数字均拒绝且不发请求
- 持仓建议：增加“账户资金参考”区展示只读指标，单票卡片展示占账户总资产比例。

### 验收

- 专项：`tests/test_portfolio_edit_api.py` **23 passed**，`tests/test_portfolio_advice_account_metrics.py` **8 passed**
- 全量离线：`pytest -m "not live"` → **675 passed**，1 failed（已知 Windows `test_run_cli_stream_timeout`）
- 前端：`npm run build` 成功
- **未做**：账户资金参与动作/比例裁决；可用现金约束（留待下一阶段）

## 16. 最近关键提交（须与 `git log` 一致）

| 短哈希 | 说明 |
|--------|------|
| `9932601` | feat: add portfolio holding exact edit and delete confirm |
| `e3f44ef` | refactor: separate portfolio advice policy from contracts |
| `0ee21aa` | refactor: split portfolio advice validator pipeline |
| `f3d90af` | fix: harden account funding persistence and submit state |
| `88a1f83` | fix: restore account funding profile UI |
| `fe54b8f` | feat: add manual account funding input |
| `5dec970` | feat: calculate executable add quantities |
| `f2ae80c` | fix: stabilize A-share snapshot paging requests |
| `082e825` | fix: constrain portfolio advice execution rules |
| `cf535b8` | fix: preserve valid review on refresh failure |
| `2cf897c` | perf: serve persisted daily review while refreshing |
| `8eb9225` | feat: upgrade daily review to nine-dimension analysis |

接手后请以 `git log --oneline -15` 与 `git rev-parse HEAD` 刷新本节。

## 远程协作

- origin：`https://github.com/guilaile95/Vibe-Research.git`
- 交付分支：`origin/refactor/portfolio-advice-architecture-v01`

## 17. 持仓建议架构收口（refactor）

分支：refactor/portfolio-advice-architecture-v01（从 feature/research-system-v01 分出）

本轮为纯架构重构，不改变任何产品行为、API 结构或 Prompt 文本。

### 变更内容

- `portfolio_advice_contracts.py`：只保留 Schema、动作/置信度枚举和交易单位等中立契约
- `portfolio_advice_policy.py`：投资比例、confidence cap 和 partial 市场限制的唯一代码来源（`portfolio-policy-v0.1`）
- `portfolio_advice_prompt.py`：继续 re-export Contracts 中的 `SCHEMA_VERSION`、`ACTIONS`、`ACCOUNT_ACTIONS`，并暴露同一 `POLICY` 对象；最终 Prompt 文本未改变
- `portfolio_advice_validator.py`：成为兼容 Facade，继续导出原校验入口、错误类型和执行计算函数
- Validator 实现拆为 `schema` → `compat` → `fact_reconciler` → `policy_audit` → `execution` → `narrative_audit` → `pipeline` 最终装配
- 新建 portfolio_advice_account_metrics.py：将账户指标计算从 Service 迁移至独立模块
- 修改 portfolio_advice_service.py：纯编排，删除已迁出的实现体
- 新建 tests/fixtures/portfolio_advice/ + test_portfolio_advice_golden.py：27 个行为快照 + Golden Test 套件
- 新建 `test_portfolio_advice_architecture.py`：Policy 唯一来源、Facade 兼容与 Pipeline 顺序测试

兼容行为仍保留：模型遗漏持仓 → `watch`；非法账户动作 → `hold`。这是 `portfolio-advice-v0.1` 的 Legacy fallback，不是新增投资判断。

账户资金继续只在 Validator 返回后由 `portfolio_advice_account_metrics` 装配，不进入 Prompt、Context、Policy、Pipeline 或模型输入，也不约束动作和数量。

### 验收

- 持仓建议专项：236 passed，1 warning，exit code 0
- 分项收集：架构 7、Golden 27、Contracts/Policy 36、Account Metrics 8、Service 42、Validator 66、Prompt 22、API 28（合计 236）
- 全量离线：745 passed，1 failed，11 deselected，1 warning，exit code 1
- 唯一失败仍为 `test_run_cli_stream_timeout`：Windows 缺少 `python3`，实际 `fake 退出码 9009`
- 前端 `npm run build`：passed，exit code 0；仅既有空 `vendor-charts` 和 >500kB 警告
- 浏览器隔离回归：真实页面请求 + 临时响应桩覆盖 add/hold/reduce/sell/watch/avoid、partial 行情、账户已配置/未配置/损坏；Console 无 warn/error。核心 Pipeline 行为由 27 个 Golden 与 93 个 Validator 测试真实执行覆盖

本轮未实现 Explainability、Evidence Layer 或 Signal Ledger；未改变 API Schema、Prompt 最终文本或任何投资政策。
