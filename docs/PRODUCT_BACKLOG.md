# 产品候选池 (Product Backlog)

> **功能审计基线**：PR #35 Merge SHA `f5f420662e3246f56d371e6020efa4de725679e9`
> **候选池维护历史**：由 PR #34 引入；**实时稳定 HEAD**：`git rev-parse origin/feature/research-system-v01`
> **仅描述仓库内已实现能力边界与外部候选差距；不包含密钥、持仓内容或代理敏感配置**
> **维度拆分**：实现状态 ≠ 当前执行授权

---

## 0. 状态模型

### 0.1 实现状态（代码是否在稳定分支可用）

| 实现状态 | 含义 |
|----------|------|
| **已上线** | 功能已合并至稳定分支并可交付 |
| **部分实现** | 稳定分支有基础能力，仍缺关键增量 |
| **尚未实现** | 稳定分支无对应产品能力 |
| **本地实验** | 仅存在于本地 worktree / 未提交改动 |
| **已被稳定分支吸收** | 曾独立存在，内容已进入稳定分支 |
| **需要复核** | 备份/残留，价值未最终确认 |

### 0.2 当前执行授权（现在能否开发）

| 当前执行授权 | 含义 | 是否可开发 |
|--------------|------|-----------|
| **已授权** | 已获明确开发授权 | ✅ |
| **未授权** | 仅候选规划 | ❌ |
| **待用户决策** | 本地实验/备份，需用户决定去留 | ❌ 不得当授权任务推进 |

**当前已授权产品开发任务：无。**

历史上已上线的功能，不代表当前仍有开发授权。

### 0.3 已上线能力（P1 + P2 + 契约修复）

| 代号 | 名称 | 实现状态 | 合并记录 | 关键文件 |
|------|------|----------|----------|----------|
| P1-1/2 | 交易流水 (Trade Ledger) | 已上线 | PR #25 / `bd0214a` | `trade_ledger_*.py`, `Trades.tsx` |
| P1-3 | 决策反馈 (Decision Feedback) | 已上线 | PR #26/#27 / `dedf99b` | `decision_feedback_*.py`, `DecisionFeedback.tsx` |
| P2-1 | 决策依据层 (Decision Evidence) | 已上线 | **PR #28 / `fe954a78`** | `decision_trace_store.py`, `decision_evidence_*.py` |
| P2-2 | 信号账本 (Signal Ledger) | 已上线 | **PR #29 / `eecbf56`** | `signal_ledger_*.py`, `SignalLedger.tsx` |
| P2-3 | 账户资金执行策略 | 已上线 | PR #30 / `ecd101b` | `account_execution_policy.*`, `AccountPolicy.tsx` |
| P2-4A | 决策反馈分析 (Feedback Analytics) | 已上线 | PR #31 / `24117d6` | `decision_analytics_*.py`, `DecisionPerformance.tsx` |
| P2-4B | 收益归因 (Performance Attribution) | 已上线 | PR #32 / `06594c2` | `performance_attribution_*.py`, `PerformanceAttribution.tsx` |
| — | Scheduler 测试隔离修复 | 已上线 | PR #33 / `e857d43` | `test_scheduler_lifespan.py` |
| — | Decision Trace 生产契约修复 | 已上线 | **PR #35 / `f5f4206`** | `portfolio_advice_trace_adapter.py`, `signal_ledger_*`, `decision_evidence_service.py` |
| — | 数据健康中心 (Data Health) | 已上线 | PR #23 | `data_health_*.py`, `DataHealth.tsx` |
| — | 投资论文与证据 (Evidence Thesis) | 已上线 | 已合并 | `evidence_thesis_*.py`, `Thesis*.tsx` |
| — | 行业研究数据中心 | 已上线 | 已合并 | `sector_research_data.py`, `Sectors.tsx` |
| — | 每日复盘 SWR | 已上线 | 已合并 | `daily_review_*.py`, `DailyReview.tsx` |

**P2-1 / P2-2 说明**：
- 功能已完成并上线（PR #28 / PR #29）
- PR #35 已关闭权威建议契约错位、非法比例归档和身份字段补值问题
- 新生成的 Decision Evidence 与 Signal Ledger 使用权威结果契约
- **历史错误归档记录未回填**

### 0.4 本地目录与实验（非产品开发授权）

| 目录 | 实现状态 | 当前执行授权 | 说明 |
|------|----------|--------------|------|
| `Vibe-Research-visual-overhaul-20260729` | 本地实验 | 待用户决策 | 未提交 7 文件：`frontend/index.html`, `frontend/src/components/layout/Layout.tsx`, `frontend/src/components/ui/GlassCard.tsx`, `frontend/src/components/ui/PageHeader.tsx`, `frontend/src/index.css`, `frontend/src/router.tsx`, `frontend/tailwind.config.ts` |
| `Vibe-Research-data-health-design` | 需要复核 | 未授权 | worktree 已注销；本地仍含完整源码副本（111 .py / 205 .ts / 37 .tsx / 15 .md）；未确认可安全删除，继续保留等待独立审计 |
| `Vibe-Research-decision-feedback-hardening` | 需要复核 | 未授权 | 空目录残留；受 Windows 进程锁定；重启后重新确认为空再删除 |
| `Vibe-Research-decision-trace-contract` | 已被稳定分支吸收 | 未授权 | PR #35 已合并；worktree 与残留目录均已回收 |
| `Vibe-Research-trade-ledger-ui-git-backup-20260729-105111` | 需要复核 | 未授权 | Git 管理元数据/本地对象备份；价值未最终确认；**继续保留** |

### 0.5 候选池（未授权、仅规划）

即下方 BK-01 ~ BK-11。**当前已授权产品开发任务：无。**

---

## 1. 候选池明细

### BK-01 主动监控与告警推送

| 项 | 值 |
|----|-----|
| **授权状态** | 候选（未授权）|
| **当前实现** | 仅 1800s portfolio 时间戳 ticker + data_health 事件存储（只读观测）|
| **已实现组件** | `app.lifespan` 启动 `start_scheduler(1800)`；多个 `TTLCache` 限流；`data_health_event_store` 记录 success/partial/failure |
| **核心差距** | 无推送（邮件/webhook/浏览器）；无告警规则引擎（阈值/事件）；无周期信号扫描；无 watchlist 变更 diff |
| **依赖** | BK-02（筛选器产出候选池）、BK-04（技术触发）、`a-stock-data` 技能（实时行情）|
| **价值假设** | 用户无法盯盘时，系统主动发现突破/异动并推送，减少错过窗口风险 |

**MVP 范围（若授权）**：
1. 告警规则 CRUD（条件：估值百分位 / 价格 vs MA / 北向净流入 / 涨停）
2. 通知渠道抽象（至少一个：浏览器 Notification API 或 Webhook）
3. 告警历史 + 确认/去重/静默时段
4. 后台轮询调度（APScheduler/cron），不阻塞 FastAPI lifespan

**优先级建议**：中。依赖 BK-02/04 基础设施，单独价值有限。

---

### BK-02 基于信号的选股筛选器

| 项 | 值 |
|----|-----|
| **授权状态** | 候选（未授权）|
| **当前实现** | **无**。现有 `decision_cockpit_signals.py` 仅对候选池做 per-stock 评估，不返回筛选结果 |
| **已实现组件** | 三维信号评估（value/trend/short）+ 规则版本 + 置信度；候选池构建器（holdings + watchlist + sector reps + 连板）；signal_ledger 只读审计 API；广度/快照计算 |
| **核心差距** | 无 screener 端点/UI；无多条件筛选（AND/OR）；无保存预设；无全市场遍历；无按信号强度排序 |
| **依赖** | `astock.py`/`market.py` 全市场快照；`decision_cockpit_signals.py` 信号算法复用 |
| **价值假设** | 用户希望「找出当前满足 X 信号组合的所有 A 股」，而非仅看持仓候选 |

**MVP 范围（若授权）**：
1. Screener 端点：接收信号条件 JSON → 返回命中股票列表 + 信号标签
2. 全市场遍历（基于 `market.calculate_market_breadth` 的现有快照能力扩展）
3. 复合条件（AND/OR、阈值可调）
4. 保存预设 + 命中数 + 结果导出

**优先级建议**：高。是连接现有信号评估能力与「选股」需求的关键桥梁。

---

### BK-03 行业/板块/资金维度增强

| 项 | 值 |
|----|-----|
| **授权状态** | 切片 2 已授权并合并（PR #40，`feat/northbound-capital-flow-v1`）|
| **当前实现** | **BK-03 切片 1（板块代表公司主力资金流，PR #38）+ 切片 2（北向资金权威数据合同，PR #40）** |
| **已实现组件** | 行业/概念/区域排名（`board_ranking`）；个股 + 行业资金流（`stock_fund_flow_120d`、`_sectors`）；龙虎榜席位/机构净买；融资融券；大宗交易；股东户数变化；分红/解禁；行业动态数据面板 + 报告发现；**北向资金（沪股通/深股通）日级成交额、成交笔数、ETF 成交额、每日额度余额、按成交额活跃股（HKEX 官方日统计权威源，`GET /api/market/northbound`，Data Health 注册 `northbound_capital_flow`）** |
| **核心差距** | **无北向（沪股通/深港通）资金追踪**；无机构 vs 零售资金分解；无行业时序/轮动图；`SectorDetail.tsx` 无数据图表；行业覆盖有限（仅 PCB 真实可用，其余为关键词骨架）|
| **依赖** | `a-stock-data` 技能（北向资金数据源）；`astock.py` 扩展端点 |
| **价值假设** | 行业/资金维度已可用但缺失「北向资金」这一 A 股最关键资金视角，补充后形成完整资金面 |

**MVP 范围（若授权）**：
1. ~~北向资金数据接入~~ ✅ 已完成（PR #40，HKEX 官方日统计权威源，仅成交额/成交笔数/ETF 成交额/活跃股，净买入字段固定 None + limitation 说明）
2. 北向资金时序图 + 与股价叠加
3. `SectorDetail.tsx` 数据图表（行业资金流/相对强弱曲线）
4. 行业覆盖扩展（超过 PCB）

**真实性说明**：HKEX 官方北向日统计仅发布成交额，未发布买入/卖出拆分，净买入无法从权威源计算。东财北向净买额字段自 2024-08-19 起全部为 null，故本切片不接入净买入。界面与合同均如实标注「本数据源不提供北向净买入」。

**优先级建议**：高。已有坚实基础，补充北向资金即可闭环。

---

### BK-04 技术条件与价格触发

| 项 | 值 |
|----|-----|
| **授权状态** | 候选（未授权）|
| **当前实现** | **几乎为零**。仅 `decision_cockpit_signals.evaluate_trend` 内联 SMA20/60 + 量比 + 回撤 + 跳空检测 |
| **已实现组件** | 内联 SMA(20/60)；量比(5/20)；20 日涨幅；跳空检测（用于失效趋势信号，不作为指标暴露）|
| **核心差距** | 无指标模块；无 MACD/RSI/布林带/KDJ；无价格触发/突破检测；无 K 线形态识别；趋势信号内的 MA/量比逻辑不可复用 |
| **依赖** | `astock.py` kline 数据；BK-01（触发→告警通道）；BK-02（技术指标筛选）|
| **价值假设** | 用户需要「价格突破 N 日新高」「MACD 金叉」等技术触发，与现有估值/资金面互补 |

**MVP 范围（若授权）**：
1. 独立技术指标模块（MA/MACD/RSI/布林带/KDJ/量比），复用 `kline()` 数据
2. 指标 API 端点（按 code/period 返回时序值）
3. 价格触发规则（突破 N 日新高/新低、均线交叉）
4. KlineChart.tsx 叠加指标图层

**优先级建议**：中。依赖指标库基础，但与其他候选正交性强。

---

### BK-05 长期投资论文与观点漂移追踪

| 项 | 值 |
|----|-----|
| **授权状态** | 候选（未授权）|
| **当前实现** | **已有实质实现**，全栈 CRUD + 修订 + 差异 + 证据链接 |
| **已实现组件** | 完整 CRUD 生命周期（create/read/update/soft-delete）；4 状态（active/weakened/invalidated/archived）；乐观锁并发控制（`expected_revision` → 409）；修订历史 + 字段级差异引擎；证据链接（support/oppose/neutral）+ 主体一致性校验；论文→交易单向链接（`thesis_ref`）；数据健康集成；多市场标的归一化 |
| **核心差距** | **无观点漂移检测**（论文 vs 股价走势分歧）；**无论文强度评分**（证据有 per-item confidence，无聚合论文强度）；论文→建议链接为单向（交易→论文，无反向）|
| **依赖** | `evidence_thesis_store.py`（现有）；`astock.py` 价格数据；`portfolio_advice_pipeline.py`（反向链接）|
| **价值假设** | 论文已可管理，但缺「漂移发现」——当标的走势与论文逻辑背离时主动提示 |

**MVP 范围（若授权）**：
1. 漂移指标计算（论文核心假设 vs 实际价格/财务趋势）
2. 论文强度分（证据置信度聚合 + 趋势）
3. 自动弱化信号（漂移超阈值 → 提示用户重评）
4. 论文→建议反向联动（建议生成时关联支持论文）

**优先级建议**：中。现有实现已覆盖 80% 需求，漂移检测是高价值增量。

---

### BK-06 AI 巴菲特方法论（价值/增长投资 AI 适配）

| 项 | 值 |
|----|-----|
| **授权状态** | 候选（未授权）|
| **当前实现** | **无**。现有 `portfolio_advice_prompt.py` 为战术持仓建议（短周期 add/hold/reduce/sell），非价值/增长筛选 |
| **已实现组件** | 高级组合建议管道（20+ 模块）；`chat.py` 五维投研框架（估值/资金面/财报质量/行业景气/事件催化）；`mcp_server.py` 通用工具暴露 |
| **核心差距** | 无巴菲特式筛选（ROE/护城河/管理层质量/长复利）；无价值/增长筛选 Prompt；无与 `a-stock-data` 技能的自动化数据对接 |
| **依赖** | `a-stock-data` 技能（财务三表/行业数据）；BK-02（筛选器承载）；BK-05（论文承载长期逻辑）|
| **价值假设** | 现有建议系统为短周期战术，缺乏「长期持有」视角；AI 巴菲特方法论补齐长仓筛选 |

**MVP 范围（若授权）**：
1. 巴菲特式筛选 Prompt/管道（ROE/毛利率/护城河评分/负债质量）
2. 与 `a-stock-data` 技能的财务数据自动对接
3. 长仓候选池（与现有短周期建议并列展示）
4. 论文→长仓候选绑定（BK-05 联动）

**优先级建议**：中低。概念清晰但实现链长，依赖外部技能对接。

---

### BK-07 免费股票数据库只读 Provider PoC

| 项 | 值 |
|----|-----|
| **授权状态** | 候选（未授权）|
| **当前实现** | **有，但为单体硬编码数据层**，非抽象化 Provider |
| **已实现组件** | 多源免费无 Key 数据（腾讯行情；东财报告/快照/广度/板块/资金流/龙虎榜/融资融券/大宗/公告/投资者关系；akshare 共识预测/新闻/个股信息/财务摘要/估值百分位；mootdx K 线/F10）；东财 host-pair fallback；序列化节流 + 抖动；瞬态网络错误分类；WAL 感知只读健康快照 |
| **核心差距** | **无 Provider 抽象层**；**无跨 Provider fallback chain**（仅 push2→push2delay）；Tushare/Baostock/yfinance 未接入；非架构化 PoC；无实时 `a-stock-data` 技能集成 |
| **依赖** | `astock.py`（现有）；`a-stock-data` 技能（上游 SKILL.md）|
| **价值假设** | 现有 `astock.py` 为静态硬编码移植，上游技能升级无法自动传播；Provider 抽象后可实现跨源冗余 |

**MVP 范围（若授权）**：
1. Provider 抽象接口（`DataProvider` Protocol）
2. 跨 Provider fallback chain（腾讯 → akshare → mootdx 按数据类型）
3. Provider 注册表 + 健康模型 per source
4. 与 `a-stock-data` 技能的动态对接（替代静态移植）

**优先级建议**：中。架构改进，对用户透明但影响长期可维护性。

---

### BK-08 视觉重构决策

| 项 | 值 |
|----|-----|
| **实现状态** | 部分实现（稳定分支已有成熟设计系统）+ 本地实验（visual-overhaul 未提交 7 文件）|
| **当前执行授权** | 待用户决策（本地实验）/ 未授权（产品增量）|
| **已实现组件** | Tailwind CSS 3.4 + 完整 HSL CSS 变量 token 体系（浅色/深色）；暗色模式默认 + 切换 + localStorage 持久化；共享 Layout + GlassCard + PageHeader + `cn()` 工具；Lucide React 图标（单一来源）；Inter + JetBrains Mono 字体；玻璃暖橙美学（径向渐变环境背景 + 毛玻璃 + 发光阴影）|
| **核心差距** | **无障碍（a11y）体系**（仅 3 文件 aria-* 属性，非系统化）；无 focus-visible 样式；无 skip links；无屏幕阅读器模式；无设计 token 文档 |
| **依赖** | 前端 worktree `Vibe-Research-visual-overhaul-20260729`（含未提交 7 文件，非已授权开发）|
| **价值假设** | 视觉体系已建立，重构决策应聚焦 a11y 系统化 + 设计 token 文档化，而非「换皮」 |

**MVP 范围（若授权）**：
1. a11y 审计（focus-visible / skip links / ARIA patterns）
2. 设计 token 文档（`docs/DESIGN.md`）
3. 视觉回归测试（Playwright 截图门控）

**优先级建议**：中低。视觉体系已成熟，a11y 为合规需求，非功能性产品增量。

---

### BK-09 数据健康设计审计

| 项 | 值 |
|----|-----|
| **授权状态** | 候选（未授权，但已实现生产级功能）|
| **当前实现** | **完整实现且为生产级** |
| **已实现组件** | 数据新鲜度/过时追踪（域感知：A 股盘间 300s 阈值 + 交易日 + 午休/收盘后边缘案例）；11 个注册源 + 专用 `DataHealthAdapter` Protocol；三态质量评分（normal/partial/unavailable）+ 完整错误分类（11 错误码 + 4 业务码）；原子写入事件存储（JSON + 模式版本化 + 严格字段验证）；前端总览 + 建议可用性闸门卡片 + 过时/问题列表 + 11 源卡片网格 + 单源详情面板 |
| **核心差距** | **无实时告警/推送**（按需只读）；**无历史趋势**（点状态，无时序健康图）；**无自动修复**（降级源仅暴露不重试）；预期 `data_health_store.py` 文件名不存在（实际为 `data_health_event_store.py`）|
| **依赖** | BK-01（健康事件 → 告警通道）；现有 `data_health_*.py` |
| **价值假设** | 数据健康监控已完整，缺口在「主动通知」与「趋势洞察」，非基础能力 |

**MVP 范围（若授权）**：
1. 健康事件订阅 → 告警推送（复用 BK-01 通道）
2. 健康历史时序图（事件 store → 趋势可视化）
3. 降级源自动重试（修复回路）

**优先级建议**：中。基础能力完整，增量需与 BK-01 联动。

---

### BK-10 剩余工程治理

| 项 | 值 |
|----|-----|
| **授权状态** | 候选（未授权，工程类非产品）|
| **当前实现** | **部分实现**：强测试覆盖 + CI/CD；工具链/文档不均 |
| **已实现组件** | CI 流水线（7 jobs：backend/frontend/e2e-smoke/e2e-thesis/e2e-data-health/whitespace）；79 后端测试 + 32 前端单测 + 11 Playwright E2E；严格 TS 配置；4 核心文档（ARCHITECTURE/DECISIONS/KNOWN_ISSUES/NEXT_TASK）；数据健康模式版本化 + 论文库 WAL 感知只读健康快照 |
| **核心差距** | **无 lint/format/coverage 工具**（最大治理缺口：无 eslint/prettier/ruff/mypy/black）；无 pre-commit hooks；无数据库迁移框架（Alembic）；无依赖更新 bot；无 mypy/pyright CI 门控 |
| **依赖** | 无外部依赖；全部为内部工程配置 |
| **价值假设** | 测试覆盖已高，但代码风格/类型安全无自动化保障；随团队扩张，治理债务将累积 |

**MVP 范围（若授权）**：
1. Lint + Format 工具链（ruff + mypy 或 pyright）
2. pre-commit hooks
3. 覆盖率工具 + CI 门控
4. 依赖更新 bot（Dependabot/Renovate）

**优先级建议**：低（工程类）。不直接产出产品价值，但长期影响可维护性。

---

### BK-11 短线市场事实层与复盘闭环

| 项 | 值 |
|----|-----|
| **授权状态** | 候选（已纳入路线图，当前未授权实施）|
| **当前实现** | **部分基础、尚未形成短线事实层**。当前项目已有市场宽度、每日复盘、板块研究、技术指标、Data Health、Decision Evidence、Decision Feedback 等基础能力，但没有系统化的涨跌停/炸板/连板梯队/晋级率/封板质量/亏钱效应/题材结构短线事实层。 |
| **已实现组件** | 市场宽度与每日复盘骨架；Data Health 来源状态；Decision Evidence / Feedback / Analytics 闭环；板块研究与技术指标事实展示 |
| **核心差距** | 缺少可复核的短线市场事实指标合同、交易日/场次语义、Preflight 充分性检查、T+1 验证映射，以及与现有复盘/证据链路的统一接入 |
| **依赖** | 硬依赖：现有 Data Health、Daily Review、Decision Evidence/Feedback 能力；可选增强：BK-07 Provider 抽象。**BK-07 不是硬阻塞**，Slice 0–3 可先基于现有受控数据源推进。 |
| **价值假设** | 通过可复核的短线市场事实指标增强每日复盘，形成“事实计算 → 数据充分性检查 → 展示 → T+1 验证”的闭环，而不是依赖 LLM 直接生成行情数字。 |
| **优先级建议** | **中高**。优先于 BK-05、BK-06；但**不插队**当前已授权或已进入复审的任务。 |

**采纳边界（可吸收）**：

```text
市场宽度
涨停/跌停数量
炸板率
封板质量
连板梯队
晋级率
连板溢价
亏钱效应
题材结构
交易场次语义
Preflight 数据充分性检查
normal/partial/unavailable 降级
T+1 验证条件
硬指标与 AI 叙述分离
```

**不采纳边界（禁止整体合仓）**：

```text
整体复制 vibe-astock 仓库
复制其 vr/ 目录
复制 server.py
sys.path 动态路由注入
独立 JSON 存储体系
全局字典 + 线程的任务状态模型
MiMo 专用配置体系
另一套前端
另一套聊天/鉴权/CORS
LangGraph 作为项目核心运行时
串行五分析师作为 MVP
```

**接入原则**：

```text
所有接入层按当前 Vibe-Research 架构重新实现。
```

**切片规划**：

1. **Slice 0：数据与口径可行性**（仅审计）  
   审计数据源可用性、字段口径、交易日与盘中/收盘语义、数据许可和展示边界、缓存策略、Data Health 映射。  
   交付：字段合同、来源分级、limitations、可离线 fixture、Go / No-Go 结论。  
   **不得在 Slice 0 直接实现完整页面。**

2. **Slice 1：市场宽度与涨跌停事实**  
   上涨/下跌家数、涨停/跌停数量、炸板数量与炸板率、封板率或封板质量的最小事实指标。  
   要求：纯计算、无 LLM、统一 envelope、接入 Data Health、固定 fixture 测试。

3. **Slice 2：短线结构指标**  
   连板梯队、晋级率、连板溢价、梯队断层、亏钱效应、题材结构。  
   每个指标必须记录分子、分母、样本范围、交易日、缺失语义。

4. **Slice 3：历史与页面**  
   交易日快照、历史比较、Daily Review 或独立短线复盘区域，以及来源/抓取时间/状态/limitations。  
   不复制 Vibe-Astock 页面。

5. **Slice 4：T+1 验证闭环**  
   将昨日判断或验证条件映射到现有 Decision Evidence / Decision Feedback / Decision Analytics。  
   不得建立第二套反馈存储。

6. **Slice 5：可选 AI 叙述**  
   进入条件：Slice 1–4 稳定、硬指标合同通过、已有评测证明 AI 叙述有增益。  
   MVP 只允许：一次结构化 LLM 调用、读取已提交指标快照、不得重新计算核心数字、失败不影响硬指标页面。  
   LangGraph 和五 Agent 只能作为未来实验，不属于 BK-11 MVP。

**执行顺序（相对当前路线）**：

```text
1. 当前 KDJ 复审完成并关闭 BK-04
2. 现有 PR #43 / BK-02 / BK-03 依赖链完成收口
3. BK-01 前置依赖完成最小收口
4. BK-11 Slice 0 可行性审计
5. 只有 Slice 0 Go 后才授权 Slice 1
```

**决策文档**：见 [`docs/VIBE_ASTOCK_ADOPTION_PLAN.md`](VIBE_ASTOCK_ADOPTION_PLAN.md)。

---

## 2. 候选依赖图

```
BK-04 (技术指标) ──┬──▶ BK-02 (信号筛选) ──▶ BK-01 (监控告警)
                   │         │                      ▲
                   │         ▼                      │
                   └──▶ BK-03 (资金维度) ────────────┘
                                  ▲
                                  │
BK-07 (Provider 抽象) ──▶ astock.py ──▶ BK-03/BK-04 数据源
          │
          │ 可选增强（非硬阻塞）
          ▼
BK-11 Slice 0–3 (短线市场事实层)
          │
          ├──▶ Decision Evidence / Feedback（Slice 4）
          └──▶ 可选 AI 叙述（Slice 5）

BK-05 (投资论文) ◀── BK-06 (巴菲特方法论)
        │
        ▼
BK-01 (告警：论文漂移)

BK-09 (数据健康) ──▶ BK-01 (告警通道)
BK-10 (工程治理) ──▶ 全部候选（基础设施）
BK-08 (视觉) ──▶ 全部前端候选
```

### 2.1 关键依赖对

| 被依赖方 | 依赖方 | 关系 |
|----------|--------|------|
| BK-04 指标库 | BK-02 筛选器、BK-01 告警 | 指标是筛选/告警的原子条件 |
| BK-02 筛选器 | BK-01 监控 | 筛选器产出候选池供监控轮询 |
| BK-07 Provider 抽象 | BK-03/BK-04 数据源 | 抽象层替代 `astock.py` 硬编码 |
| BK-07 Provider 抽象 | BK-11 短线事实层 | 可选增强，不是 Slice 0–3 硬阻塞 |
| BK-01 告警通道 | BK-03/05/09 事件 | 告警是健康/资金/论文事件的统一出口 |
| Data Health / Decision Evidence·Feedback | BK-11 Slice 1–4 | 短线事实状态与 T+1 验证复用现有闭环 |
| BK-10 工程治理 | 全部候选 | lint/format/coverage 是开发前置 |
| BK-08 视觉 | 全部前端候选 | a11y/token 是前端一致性基础 |

---

## 3. 推荐开发顺序（若获授权）

> **注意**：以下为产品优先级建议，**不构成开发授权**。实际开发需逐项单独授权。

| 顺序 | 代号 | 理由 |
|------|------|------|
| 1 | **BK-03 资金维度增强** | 已有实质实现，补充北向资金即可闭环；价值最直接 |
| 2 | **BK-02 信号筛选器** | 复用现有信号评估算法；是 BK-01 的前置 |
| 3 | **BK-04 技术指标** | 基础设施模块；BK-02/01 依赖其原子条件 |
| 4 | **BK-01 监控告警** | 依赖 BK-02 筛选器 + BK-04 触发条件 |
| 5 | **BK-11 短线市场事实层与复盘闭环** | 中高优先级；在既有复审/依赖链收口后，优先于 BK-05/06 启动 Slice 0 |
| 6 | **BK-05 论文漂移** | 已有实质实现；漂移检测为高价值增量 |
| 7 | **BK-09 数据健康增强** | 需与 BK-01 联动 |
| 8 | **BK-06 巴菲特方法论** | 概念清晰但实现链长；依赖外部技能对接 |
| 9 | **BK-07 Provider 抽象** | 架构改进，用户透明；可增强 BK-11 但不阻塞 |
| 10 | **BK-08 视觉 a11y** | 视觉体系已成熟；a11y 为合规需求 |
| 11 | **BK-10 工程治理** | 工程类非产品；长期可维护性 |

---

## 4. 文档交叉引用规则

| 文档 | 职责 | 何时更新 |
|------|------|----------|
| `docs/PRODUCT_BACKLOG.md` | 本文档 — 候选池边界、授权状态、依赖关系 | 候选授权/完成/新增时 |
| `docs/NEXT_TASK.md` | 当前已授权任务（无候选） | 授权变更时 |
| `docs/CHAT_HANDOFF.md` | 交接摘要 + 安全边界 | 架构/边界变更时 |
| `docs/PROJECT_STATE.md` | 已实现能力清单 | 功能合并至稳定分支时 |
| `docs/ARCHITECTURE.md` | 调用链 + 数据流 | 架构变更时 |
| `docs/DECISIONS.md` | 设计决定 | 新设计决定时 |
| `docs/KNOWN_ISSUES.md` | 已知限制 + 测试例外 | 发现/修复限制时 |

---

## 5. 决策记录

| 日期 | 决策 | 理由 |
|------|------|------|
| 2026-07-30 | 建立 PRODUCT_BACKLOG.md | 区分「当前已授权任务：无」与「长期产品候选池」，避免误将候选当任务开发 |
| 2026-07-30 | BK-03/05/09 标记「已有实质实现」 | 审计发现这三个候选并非从零开始，而是已有生产级基础，仅缺增量 |
| 2026-07-30 | BK-08 标记「已有成熟设计系统」 | 视觉 overhaul 需求非「换皮」而是 a11y 系统化 |
| 2026-07-30 | 候选开发需逐项单独授权 | 防止范围蔓延；每个 BK 应独立评审成本/收益 |
| 2026-07-30 | 拆分实现状态与当前执行授权 | 避免把已上线/有 worktree 误读为当前开发授权 |
| 2026-07-30 | 修正 P2-1/P2-2 Merge SHA | P2-1=`fe954a78`(PR #28)；P2-2=`eecbf56`(PR #29) |
| 2026-07-30 | 记录 PR #35 契约修复 | Merge `f5f4206`；历史归档不回填 |
| 2026-08-01 | 登记 BK-11 短线市场事实层与复盘闭环 | 有条件吸收 vibe-astock 业务思想；禁止整体合仓；当前未授权实施 |

---

## 6. 不做列表（明确排除）

以下事项**不在产品候选池内**，且**未获授权**：

- ❌ 自动交易 / 算法交易执行
- ❌ 收益率计算与建议准确率统计（安全边界禁止）
- ❌ 模型训练 / 微调
- ❌ 自动归权（安全边界禁止）
- ❌ 综合评分 / 权重（禁止虚构无来源权重）
- ❌ T+0 短线交易（安全边界禁止做 T）
- ❌ 修改 portfolio.json / 写复盘历史（安全边界禁止）
- ❌ 账户资产网络泄漏
- ❌ 整体复制 vibe-astock 仓库 / `vr/` / `server.py` / 动态路由注入
- ❌ 为 BK-11 新建第二套存储、任务状态模型、前端或鉴权体系
- ❌ 将 LangGraph / 串行五分析师作为 BK-11 MVP 核心运行时
- ❌ 精确抄底逃顶信号
- ❌ 高杠杆投机建议
