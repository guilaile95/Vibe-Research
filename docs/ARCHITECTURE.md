# 架构与调用链

> 依据当前代码路径描述；模块文件均位于 `backend/` 与 `frontend/src/`。

## 总览

```
frontend (Vite :5899)
    │  /api/* 代理 → 127.0.0.1:8900
    ▼
backend/app.py (FastAPI)
    ├── daily_review.*          复盘聚合 / 展示缓存
    ├── market.* / astock.*     市场与东财请求
    ├── portfolio.*             本地持仓读写
    ├── portfolio_advice_*      持仓建议编排 / 上下文 / 提示 / 校验
    ├── chat / cli_runtime      模型调用
    └── review_store / history  SQLite 显式历史（与运行时缓存分离）
```

---

## 链路一：每日复盘（展示）

```
DailyReview 前端
  frontend/src/pages/DailyReview.tsx
    │
    │ GET /api/daily-review
    ▼
app.daily_review_snapshot
    │
    ▼
daily_review.get_daily_review_for_display()
    │
    ├─(1) 内存命中且未过期（TTL 300s）
    │     → data + cache_meta(source=memory, stale=false, …)
    │
    ├─(2) 无内存，磁盘有可加载成功包（daily_review_cache.load_latest_review）
    │     → data(旧包) + cache_meta(source=persisted, stale=true)
    │     → single-flight 后台线程：generate_daily_review()
    │           → _build_daily_review → market / astock 聚合
    │           → sanitize → 内存 + 磁盘（高质量包）
    │     → 前端轮询 GET，直至 stale=false 或 refresh_failed
    │
    └─(3) 皆无
          → 同步 generate_daily_review()（live）
```

### 聚合内部（fresh）

```
generate_daily_review()
  → 缓存命中则 deepcopy 返回
  → 否则锁内 _build_daily_review()
       market.get_indices / breadth / emotion / boards / turnover / global …
  → daily_review_errors.sanitize_review_public_fields
  → 内存 _store_review + 磁盘 persist（规则见 PROJECT_STATE）
```

### 展示 vs 业务

| 用途 | 入口 | 是否允许 stale 磁盘包 |
|------|------|------------------------|
| 复盘页面展示 | `get_daily_review_for_display` | **允许** |
| 持仓建议 / 复盘 AI analyze 数据源 | `generate_daily_review` | **不允许**（只用 fresh 内存或实时聚合） |

`app.py` 与 `daily_review.py` 注释均写明：stale persisted review **只供复盘页面**；持仓建议 **只使用 fresh review**。

### 缓存与历史：两套机制

| 机制 | 模块 | 用途 |
|------|------|------|
| 运行时内存 + 磁盘 latest | `daily_review` + `daily_review_cache` | 加速展示与 SWR |
| SQLite 快照历史 | `review_store` + `review_history` + `/api/daily-review/history/*` | 用户**显式保存**后的浏览/对比；GET `/api/daily-review` **不写库** |

---

## 链路二：持仓操作建议

```
Portfolio 前端
  frontend/src/pages/Portfolio.tsx
    │ loadLlm()（localStorage vr-llm）
    │ POST /api/portfolio/advice  { user_request?, llm }
    ▼
app.portfolio_advice
    │
    ▼
portfolio_advice_service.generate_portfolio_advice(cfg, user_request)
    │
    ├─ portfolio.get_portfolio()          # 本地 JSON，不接受客户端注入
    ├─ 空持仓 → PortfolioAdviceUnavailableError → 409
    │
    ├─ daily_review.generate_daily_review()   # ★ fresh only
    ├─ breadth unavailable → MarketDataError → 503（不调模型）
    │
    ├─ portfolio_advice_context.build… + render JSON
    ├─ portfolio_advice_prompt.build_portfolio_advice_messages
    │     (策略常量从 portfolio_advice_contracts 导入/re-export)
    │
    ├─ model_runner / chat.stream_messages(use_tools=False)
    │     API 或 cli-*（cli_runtime）
    │
    ├─ 解析纯 JSON 对象
    │
    ├─ portfolio_advice_validator.validate_portfolio_advice
    │     ★ 最终裁决：动作、比例档位、execution_quantity、estimated_amount、
    │       条件数字可追溯、文字股数/金额一致性、账户比例话术等
    │     (从 portfolio_advice_contracts 读取策略规则，断开 prompt 依赖)
    │
    └─ portfolio_advice_account_metrics.attach_account_funding_metrics
          ★ 装配只读账户资金指标（account_funding 与 account_metrics）
            高精度 Decimal(ROUND_HALF_UP) 计算；尚未参与动作与比例裁决；未配置/损坏安全降级
    │
    ▼
{ "data": <权威结果 portfolio-advice-v0.1> }
    │
    ▼
结构化 UI（HoldingAdviceCard / AccountFundingCard 等）
```

### 权威边界

- **模型**：决定是否 add/hold/… 及允许的比例档位等语义建议；结构字段中的数量/金额 **不可信**。
- **validator**：`execution_size_pct_of_holding` / `execution_quantity` / `estimated_amount` 等执行字段以**后端重算与校验结果**为准。
- **事实字段**（shares、现价、盈亏、权重等）：来自持仓上下文重算，覆盖模型抄写。

### 错误码摘要

| 条件 | HTTP |
|------|------|
| 无持仓 | 409 |
| 市场核心数据（如 breadth unavailable） | 503 |
| 模型调用失败 / 输出无效 | 502 |
| 请求参数非法 | 400 |
| 其它未预期 | 500 |

---

## 数据平面（东财）

```
market / daily_review
  → astock.em_get（串行限流、trust_env=False、固定直连）
  → a_share_snapshot 分页 + 页级重试
  → 失败不返回半截列表
```

本地环境可另配 Clash Party 等对国内金融域名 DIRECT；**应用层仍以代码直连为准**，不把代理配置写入仓库。

---

## 链路三：持仓手工维护（CRUD）

```
Portfolio 前端  frontend/src/pages/Portfolio.tsx
    │
    ├─ GET    /api/portfolio              → pf.get_portfolio（行情叠加盈亏）
    ├─ POST   /api/portfolio/holding      → pf.add_holding（同代码加权合并）
    ├─ PUT    /api/portfolio/holding      → pf.update_holding（精确替换；不存在 404）
    ├─ DELETE /api/portfolio/holding      → pf.remove_holding（仅移除，不写 closed）
    ├─ POST   /api/portfolio/close        → pf.close_position（清仓记录，独立）
    └─ GET/PUT /api/account-profile       → account_profile（独立 JSON，不经 portfolio）
```

### 存储隔离

| 文件 | 模块 | 内容 |
|------|------|------|
| `portfolio.json` | `portfolio.py` | holdings + closed + last_refresh |
| `account_profile.json` | `account_profile.py` | total_assets / available_cash / updated_at |

两者默认同目录 `~/.vibe-research/`（`VR_DATA_DIR` 可覆盖），**互不写入**。持仓增删改**不**调用 `POST /api/portfolio/advice`。
