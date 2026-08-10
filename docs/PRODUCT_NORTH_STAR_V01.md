# Vibe-Research North Star Product Spec v0.1

> 状态：**PRODUCT_DIRECTION_FROZEN_V0.1**
> 日期：2026-08-08
> 适用范围：产品方向、P0/P1/P2/P3 优先级与后续设计判断
> 说明：本文件记录用户在 2026-08-08 产品方向讨论中逐项确认的结论，作为后续会话恢复产品上下文的长期依据。它**不是代码实施授权**；当前授权仍以 `docs/NEXT_TASK.md` 为准。

---

## 1. 产品身份

Vibe-Research 定位为：

> **Single-user Personal Local Investment OS：面向个人、纯本地的 A 股投资研究与决策系统。**

核心使命不是预测股价，也不是每天推荐股票，而是：

> **围绕真实持仓与拟交易标的，降低买入、持有、卖出中的错误决策风险，同时改善长期收益。**

明确边界：

- 永久单用户、本地运行；不建设 SaaS、多租户、注册/订阅体系。
- 永远不连接券商，不读取券商账户，不下单、不撤单、不自动交易。
- 实际交易、持仓和账户变化由用户手工录入。
- 暂不购买 Tushare 等商业数据；零成本数据必须能够支撑基础产品成立。
- 不把产品做成实时行情终端；免费源不具备可靠实时能力时必须暴露 Freshness/Confidence。
- A 股个股是主产品对象；ETF 保留兼容，但暂不继续深化 ETF 专属分析体系。

---

## 2. 产品价值排序

投资价值链：

`发现机会 × 获得事实 × 做出判断 × 选择时点 × 控制错误 × 从结果学习`

当前优先级为：

1. **判断机会（核心引擎）**
2. **决策闭环（长期护城河）**
3. **发现机会（入口）**
4. **组合管理（资本配置落点）**
5. 高频/分钟级择时只作为辅助能力，不作为第一阶段核心。

P0 采用 **Capital-First**：越接近真实资金，越优先开发。

---

## 3. Strategy 与 Campaign

正式支持三个策略周期：

- `SHORT`：约 1–5 个交易日
- `SWING`：约 1 周–2 个月
- `MEDIUM`：约 2–12 个月

任何正式投资 Decision 必须属于：

`Security + Strategy + Campaign`

同一股票允许多个独立 Campaign，例如：

- MEDIUM 10% → HOLD
- SWING 4% → EXIT

股票层只提供 Aggregate View；真正的 BUY/HOLD/REDUCE/EXIT 属于具体 Campaign。

硬规则：

- 失败的 SHORT/SWING Campaign 不允许直接修改 Strategy 变成长线持有。
- 若逻辑改变，应结束旧 Campaign，再创建新 Campaign。
- Full Exit 后 Campaign 永久 `CLOSED`；重新进入必须创建新 Campaign，可通过 `RE-ENTRY / lineage` 关联旧 Campaign。
- 未持仓候选可以建立 `PRE-ENTRY Campaign`。

Campaign 生命周期：

`DRAFT → RESEARCHING → PRE-ENTRY → ACTIVE → REDUCING → CLOSED`

另有 `REJECTED / EXPIRED`。

---

## 4. Thesis

采用 **Structured Thesis Core + Free Notes**。

正式 Thesis 至少包括：

- Strategy
- Core Thesis
- 3–5 个 Key Drivers
- Catalyst / Realization Path
- Expected Horizon
- Invalidation Conditions
- Key Risks

AI 可以起草，但正式 Thesis 属于用户确认状态。

Original Thesis 一旦冻结，不允许事后回写成更有利的版本；新事实只产生 Thesis Delta：

- `STRENGTHENED`
- `STABLE`
- `WEAKENED`
- `DISPROVEN / INVALIDATED`
- `UNKNOWN`

---

## 5. 正式 Decision 输出

正式输出必须保留三层原始判断：

- **Asset View**：股票本身是否值得拥有
- **Trade View**：当前 Strategy / Horizon 下是否适合交易
- **Portfolio View**：对当前账户/组合意味着什么

再额外给一个：

- **Next Best Action**

正式动作词汇：

- `BUY NOW`
- `BUY SMALL`
- `SCALE IN`
- `WAIT`
- `HOLD`
- `WATCH TO REDUCE`
- `REDUCE`
- `EXIT`
- `AVOID`
- `RESEARCH MORE`

不得把 Asset/Trade/Portfolio 三层强行压缩成单一 BUY/SELL。

---

## 6. Risk Engine 与 Action Envelope

风险采用：

- **Hard Risk Gate**
- **Contextual Risk**

Hard Risk 只在严重程度高且证据门槛足够时成立，例如：

- 重大退市/交易资格风险
- 明显偿债/持续经营风险
- 高质量证据支持的重大财务真实性问题
- 足以破坏核心业务模式的监管风险
- Thesis 核心事实被证伪
- 关键数据完整性/可用性失效

Hard Risk 一旦成立，AI 无权覆盖；积极新增风险动作必须被阻断或收窄。

最终 Decision 采用：

`Deterministic Decision Policy → Action Envelope → AI Contextual Selection`

AI 可以在 Action Envelope 内有限选择，但不能突破确定性边界。

---

## 7. Risk Budget 与 Drawdown

### 7.1 单笔价格/逻辑 Backstop（v0.1，可校准）

- SHORT：7% 绝对损失 Backstop
- SWING：12%
- MEDIUM：20%

Backstop 不是默认机械止损；Thesis 失效、结构破坏、风险恶化可以更早触发高风险或 EXIT Review。

### 7.2 单笔账户 NAV 风险预算（v0.1，可配置）

- SHORT：0.75%
- SWING：1.00%
- MEDIUM：1.25%

基础仓位逻辑：

`Account NAV × Single-Trade Risk Budget ÷ Entry-to-Invalidation Distance = Risk Position Cap`

然后再经过 Opportunity Quality 与 Portfolio Adjustment，分别显示：

- Risk Allowed Cap
- Asset Optimal Position
- Portfolio Adjusted Position

### 7.3 账户回撤状态

以最近 NAV Peak 计算：

- `<10%`：NORMAL
- `>=10%`：CAUTION
- `>=18%`：HIGH RISK
- `>=25%`：DEFENSIVE
- `>=30%`：CRITICAL DRAWDOWN

账户回撤是 Portfolio 风险上下文，不得机械把 objectively good BUY 改成“不要买”。保留 Asset/Trade/Portfolio 三层原始结论。

---

## 8. Opportunity Engine

Opportunity Quality 的优先级（用户确认）：

`市场与板块环境 > 催化 > 基本面与产业逻辑 > 证据质量/置信度 > 赔率 > 技术结构`

即：`B > D > C > F > E > A`。

Strategy 依赖：

- SHORT：Market/Sector 有强裁决权；通常需要明确催化/资金驱动。
- SWING：Market/Sector 影响大但不是绝对否决；最好存在可识别催化窗口。
- MEDIUM：短期市场主要影响时点/仓位；基本面与产业逻辑是核心，不要求短期催化。

Opportunity Score 不得越过 Evidence Gate、Hard Risk Gate 或 Action Envelope。

---

## 9. Catalyst 与 Expectation

催化不是“利好/利空情绪分类”，而是 **Expectation Delta**：

`事件 → 事实确认 → Prior Expectation → Actual Outcome → Surprise → Price-in → Forward Expectation → Market/Sector Feedback → R/R`

“利好出尽”只是一种风险状态：当正面催化已被高度预期、价格提前充分上涨，而落地结果没有产生新的正向预期差时，兑现后的下行风险上升。

禁止：

- `重大利好 → BUY`
- `重大利好落地 → SELL`

### Prior Expectation（Q29）

Q29 **不冻结**，当前采用推荐的工作假设并在真实案例中校准：

1. Explicit Expectation
2. Professional Consensus
3. Implied Expectation（价格/估值/成交/相对强弱等）
4. Narrative Expectation

必须标记 `FACT / INFERENCE / UNKNOWN`；低置信度时允许明确 UNKNOWN，禁止 AI 编造“市场一致预期”。

---

## 10. Technical Analysis

技术分析定位为：

> **Market-Behavior Sensor，而不是 Truth Layer。**

优先级：

- Raw price/volume > derived indicators
- Multiple evidence > single indicator
- Relative strength > absolute return alone
- Multi-timeframe > single timeframe

MACD、KDJ、MA、单根 K 线等任何单一技术信号都无权直接产生 BUY/SELL。

输出建议：

- Technical State：STRONG / NEUTRAL / WEAK / BROKEN
- Technical Confidence：HIGH / MEDIUM / LOW

SHORT 的执行相关性更高；SWING 主要用于 timing gate；MEDIUM 仅用于时点/分批，不得单独否定长期 Thesis。

---

## 11. Evidence Engine

采用 **Claim-Specific Evidence Arbitration**：先判断 Claim 类型，再决定什么来源最有裁决权。

证据链：

`Source Record → Extracted Claim → Evidence Arbitration → Canonical Evidence`

证据状态必须区分：

- FACT
- INFERENCE
- UNKNOWN

Evidence Conflict：

- NONE
- MINOR
- MATERIAL
- CRITICAL

核心 Thesis 出现 CRITICAL 冲突时，允许 `Evidence Gate = BLOCKED`、`Next Best Action = RESEARCH MORE`。

Evidence 可以自动积累，但不能自动改写 Thesis 或 Formal Decision。

联网深度研究采用：

**Evidence-Gap Research + Research Budget**

先识别关键缺口，再定向寻找高质量来源；达到足够证据后停止，不做无边界搜索。

---

## 12. Confidence Stack

Confidence 不做单一黑箱分数，至少拆为：

- Data Quality
- Evidence Confidence
- Inference Confidence
- Decision Confidence

Decision Confidence 按 Strategy 动态组合，不做简单平均。

当前用户选择：即使短线数据质量不足，仍允许输出综合方向判断；但 LOW Confidence 必须收窄 Action Envelope，而不能把低质量数据包装成激进执行建议。

示例：

`Trade View = BUY + Decision Confidence = LOW` 可以保留方向，但最多允许 `BUY SMALL / WAIT`，不得直接 `BUY NOW / SCALE IN`。

---

## 13. 数据路线

### 13.1 零付费原则

暂不购买 Tushare 等商业数据。Tushare 生产接口可以作为未来可选增强层，但不能成为基础产品成立的必要条件。

当前产品方向基于：

- BaoStock 等已验证零成本日频/历史能力
- 公开公告/财务/研究资料
- Best-Effort 公开行情/新闻来源
- 现有本地数据能力

必须区分：

- Supplier theoretical capability
- Repo integrated capability
- Actual permission
- Observed latency/reliability

不得宣称未实证的 1 分钟实时 SLA。

### 13.2 Field-Level Data Capability Registry

按字段/能力定义：

- Primary Source
- Allowed Fallback
- Semantic Contract
- Timestamp / Freshness
- Coverage
- Reliability
- Provenance

切源必须重新计算 Data Quality；语义不等价则明确 `UNAVAILABLE`，不得拼凑。

### 13.3 NAV

采用双层 NAV：

- **Official / Settled NAV**：可靠收盘数据，用于正式历史收益、Peak、Drawdown、Outcome、Calibration。
- **Estimated Intraday NAV**：Best-Effort 行情，仅用于盘中风险感知，必须暴露 Coverage/Freshness/Confidence。

---

## 14. Fundamental 与 Valuation

### 14.1 基本面

采用双层：

- Structural Quality
- Fundamental Trajectory

同时严格拆分：

- Actual Fundamental
- Forward Fundamental

链路：

`Prior Expectation → Actual Surprise → Forecast Revision → New Forward Expectation`

Earnings Quality 不建立重规则独立引擎；用户选择由 AI 基于结构化财务事实进行 Contextual Assessment。但重大审计/会计/监管问题仍受 Hard Risk Gate 约束。

### 14.2 Forward Earnings

采用 Forecast Hierarchy：

1. Company Guidance / explicit forward facts
2. Public Professional Forecasts
3. Vibe 显式业务模型
4. AI 辅助 Scenario
5. 信息不足则 UNKNOWN

禁止把 Vibe 自己的 Scenario Estimate 包装成“市场一致预期”。

### 14.3 Valuation

采用 **Valuation Model Router**：按商业模式、生命周期、行业属性选择 Primary + Cross-check 模型，禁止 valuation shopping。

估值输出采用：

- Bear Case
- Base Case
- Bull Case

并按 SHORT/SWING/MEDIUM 使用不同 Horizon。

场景概率使用区间而非伪精确数字；证据足够时计算 Expected Value Range，证据不足时允许 UNKNOWN。

v0.1 R/R Gate（可校准）：

- SHORT：>= 1.5 : 1
- SWING：>= 2.0 : 1
- MEDIUM：>= 2.5 : 1

---

## 15. Sell Engine

卖出决策独立于 BUY Engine，必须明确原因类别：

1. THESIS INVALIDATION
2. RISK EXIT
3. EXPECTATION / PRICE-IN
4. RISK-REWARD DETERIORATION
5. CATALYST FAILURE
6. PORTFOLIO REBALANCE
7. OPPORTUNITY COST
8. TECHNICAL EXECUTION

卖出结果不只 `SELL/HOLD`，至少允许：

- HOLD
- WATCH TO REDUCE
- REDUCE
- EXIT
- THESIS INVALIDATED

亏损本身不是卖出理由，盈利本身也不是继续持有理由。

---

## 16. Decision Challenge

每次重要 BUY/SELL 必须经过：

- 支持当前决定的最强证据
- 反对当前决定的最强证据
- Decision Pre-mortem：如果最终错了，最可能错在哪里
- 哪些新事实会使当前结论失效

采用 Two-Pass Thesis Review：

1. Blind Current-State Assessment：先不看 Original Thesis，独立判断当前事实。
2. Reveal Original Thesis：再逐条比较 SUPPORTED/WEAKENED/DISPROVEN/UNKNOWN。

减少既有观点锚定。

---

## 17. Decision State Machine / Validity

每个 Next Best Action 都必须定义：

- Maintain Conditions
- Upgrade Conditions
- Downgrade Conditions
- Invalidation Conditions

正式 Decision 由：

`Research → Decision Intent → Formal Analysis → Proposed Decision → User Commit → Frozen Decision Snapshot`

正式 Snapshot 具有 Validity Contract：

- Strategy Horizon
- Review By
- Key Assumptions
- Event Invalidation Conditions

状态：

- CURRENT
- AGING
- STALE
- EXPIRED
- INVALIDATED

旧正式 Decision 一旦失效，不能继续冒充当前建议。此时只显示：

- Historical Decision
- Interim State
- Risk/Gates/Action Envelope
- AI REVIEW RECOMMENDED

直到用户主动触发新的 AI 分析并 Commit 新 Decision。

每次更新正式 Decision 必须生成 Decision Delta：

- What Changed
- What Stayed Intact
- Decision Drivers
- Assumption Changes
- Delta Type：FACT / MODEL / HUMAN

---

## 18. AI 权限与调用方式

采用 **Deterministic-First + User-Triggered AI**。

系统可以自动发现 `AI REVIEW RECOMMENDED`，但不会自动调用 AI。

正式深度分析由用户主动触发。

AI 角色：

- 推理层
- 对抗性审查层
- 解释层

AI 不是事实数据库；聊天内容不能自动成为 Canonical Fact。

AI 可以提出 Thesis/Decision 修改 Proposal，但正式 Thesis、Strategy、Decision 等用户拥有状态必须用户确认。

### Adaptive Adversarial Review

默认单模型结构化分析；重大决策、MATERIAL/CRITICAL Evidence Conflict、低置信度、Action Envelope 边界附近或用户主动要求时，再启动第二 AI 独立 Reviewer。

不做模型多数投票；无法消解的模型分歧应降低 Inference/Decision Confidence 并收窄 Action Envelope。

### Formal Model Identity

正式分析必须记录：

- Provider
- Model Identifier
- Prompt Version
- Analysis Policy Version

模型变化属于 MODEL DELTA；新模型可先 Shadow 验证。

隐私最小披露方案当前 `DEFERRED`；现阶段不为隐私数据最小化增加产品复杂度。

---

## 19. Portfolio / Capital Allocation

Portfolio Engine 保留：

- Security Exposure
- Sector / Industry Exposure
- Theme / Thesis Exposure
- Factor / Macro Exposure

集中度主要影响 Portfolio View、Position Sizing 与 Action Envelope，不得偷偷改写 Asset View。

建立 **Marginal Capital Allocation Engine**：比较下一单位风险资本放在新机会、现有持仓、加仓、现金中的未来风险调整后价值。

换仓采用 **Replacement Hurdle + NO-TRADE ZONE**：候选机会只有在扣除交易摩擦、不确定性与组合影响后仍显著优于现有持仓，才建议换仓。

---

## 20. Manual Account Ledger

Vibe 永远不连接券商。

实际交易全部手工维护，采用 Event Ledger：

- TRADE_BUY
- TRADE_SELL
- CASH_DEPOSIT
- CASH_WITHDRAWAL
- DIVIDEND
- FEE
- TAX
- CORPORATE_ACTION
- CORRECTION

真实持仓从事件账本推导，不允许静默覆盖历史。

每笔实际交易必须显式归属 Campaign；无法确定时进入 `UNALLOCATED / RECONCILIATION REQUIRED`，系统不猜 FIFO、不用 AI 推断。

没有预先 Campaign 的真实交易必须允许记录，但标记：

- `Trade Origin = UNPLANNED`
- `Pre-trade Thesis = NONE`
- `Pre-trade Decision Snapshot = NONE`

事后可创建 Campaign，但必须标记 `POST-ENTRY`，禁止伪造成事前 Thesis。

### Legacy Bootstrap

Vibe 上线前已有持仓：

- `Origin = PRE-VIBE / LEGACY`
- Historical Pre-trade Thesis = UNKNOWN
- Historical Decision = UNKNOWN

从 Vibe 接管日建立 Current Thesis 和新的正式 Decision，只评价接管后的 Decision Quality。

首次账本采用：

- `ACCOUNT_OPENING`
- `LEGACY_POSITION_OPENING`

不把当前平均成本伪造成一笔历史 BUY。

---

## 21. Outcome / Learning

所有正式 Decision Snapshot 都进入 Outcome Evaluation，即使用户没有实际交易。

同时保留：

### Actual Capital Outcome

- Realized/Unrealized P&L
- MAE / MFE
- Drawdown
- Actual Position / Execution

### Decision Counterfactual Outcome

评价：

- Correct Wait
- Missed Opportunity / False Negative
- Correct Avoidance
- False Positive
- Premature Exit
- Late Exit

Process Evaluation 至少包括：

- Thesis Accuracy
- Catalyst Accuracy
- Scenario Calibration
- Risk Detection
- Action Quality
- Position Quality

不允许简单使用“赚钱=好决策、亏钱=坏决策”。

复盘采用 **Hindsight-Controlled Two-Pass Evaluation**：

1. Decision-Time Replay：只用当时可获得的信息，先评价过程。
2. Outcome Reveal：再揭示未来价格、财报、Catalyst 和市场结果，进行归因。

Evidence 至少区分 Event Time 与 Published/Known Time，防止未来信息泄漏。

---

## 22. Behavioral Risk

建立 **Evidence-Based Behavioral Risk Engine**，但只根据可审计交易行为，不做人格式心理诊断。

可识别：

- UNPLANNED trades
- oversizing
- chase-after-runup
- premature exit
- late exit
- frequent replacement
- Thesis Drift attempts
- Decision → Execution deviation

Behavioral Evidence 必须分级：

`OBSERVATION → EMERGING → ESTABLISHED`

只有 Established、样本量/效果大小/跨时间稳定性足够时，才允许影响 Action Envelope。

采用 **Bounded Behavioral Overlay**：行为风险可以有限收窄动作、仓位和执行节奏，增加 Decision Challenge，但不能单独改写 Asset View 或形成 Hard Block。

实际操作超出正式 Decision/Action Envelope 时创建 `OVERRIDE EVENT`。Override 不等于用户错误；后续 Outcome 用于判断模型问题还是执行偏差。

---

## 23. Calibration / Model Governance

参数不能因几笔近期交易自动漂移。

正式流程：

`Calibration Proposal → Frozen Candidate → Shadow Mode → Future Outcome → Promotion Review → User Confirmation`

任何 Frozen Decision 应保留：

- Risk Policy Version
- Opportunity Policy Version
- Decision Policy Version
- Behavior Model Version
- Prompt / Analysis Policy Version
- Model Provider / Identifier

不允许静默修改旧 Decision 的解释基础。

---

## 24. Universe

当前以 A 股个股为主。

### Core Universe

- 沪市主板
- 深市主板
- 创业板
- 科创板

### Restricted Universe

- ST / *ST
- 明确重大退市风险
- 上市初期新股
- 长期停牌/异常交易状态
- 其他特殊风险状态

Restricted 股票可以研究和管理已有持仓，但新增风险资本需要更严格的 Risk/Evidence/Action Envelope。

### Deferred

- 北交所
- ETF 专属 Decision Engine / Look-through 深度设计
- 港股、美股等正式交易 Universe

全球资产可作为 Market/Industry Context，不作为当前正式交易对象。

---

## 25. 首页与运行模式

首页顺序由用户确认：

1. **整体市场总览**：Market Regime / Sector Regime / Breadth / Risk Appetite
2. **持仓 Decision Inbox**：哪些持仓需要在下一个可交易时点前重新评估
3. **单股深度分析**

Decision Inbox 的优先级按：

`Risk Severity × Capital Relevance × Decision Urgency × Confidence`

没有重要事项时，允许明确显示“无需操作/无关键决策”，不为证明系统有用而制造交易。

### 运行模式（Q59）

当前暂定：`A / PROVISIONAL`

- 只有打开 Vibe 时运行刷新与监控。
- 不宣称后台 24/7 保护。
- Local Background Agent 暂不开发，未来可因实际使用反馈重新评估。

### Startup Refresh

采用分阶段刷新：

- 页面立即显示带时间戳的上次 Snapshot，旧判断标记 STALE/历史。
- 优先刷新：持仓、Active Candidates、Market/Sector、Hard Risk、重大事件。
- 尽快重建 Decision Inbox。
- 然后再处理 Discovery、普通 Watchlist、深度 Evidence、Outcome 等重任务。

关键刷新完成前，旧 BUY/SELL 不得冒充 Current Decision。

---

## 26. P0 / P1 / P2 / P3 路线

### P0 — 持仓全周期决策闭环（当前产品优先级）

P0 只解决：

> **从当前信息看，我现在持有的股票中，哪些需要在下一个可交易时点前重新判断？为什么？**

盘中、盘后、周末采用不同信息重点：

- 盘中：风险变化 / Decision Transition
- 盘后：当日事实与 Evidence 更新
- 周末：Thesis Review / 下周准备

P0 主流程：

`市场总览 → 持仓 Decision Inbox → Campaign/Current Thesis → Evidence/Risk → Sell Engine → Asset/Trade/Portfolio → Next Best Action → Frozen Decision → 手工实际交易 → 基础 Outcome`

P0 **不要求**候选股买入分析或全市场 Discovery。

#### P0 验收

必须同时满足：

**体验验收**：用户愿意真实地在交易日/盘后/周末使用 Vibe 检查持仓。

**决策质量验收**：对真实持仓能够稳定回答：

- 当前市场环境如何
- 哪只持仓最值得优先处理
- 为什么
- HOLD / REDUCE / EXIT 的依据
- 支持证据与反方证据
- 什么条件会改变当前判断

页面能跑不等于 P0 验收通过。

### P1 — 候选股买入决策

`输入股票 → Evidence-Gap Research → Fundamental/Catalyst/Expectation → Scenario Valuation → R/R → Risk → Decision Challenge → BUY/WAIT/AVOID → PRE-ENTRY Campaign`

### P2 — 全市场机会发现

采用 Multi-Stage Discovery Funnel：

`全市场低成本扫描 → Sector/Theme → Catalyst/Fundamental → Evidence Gate → Opportunity Engine → Strategy-specific Opportunity Queues → Research Priority`

Discovery 只负责发现值得研究的东西，不直接产生 BUY。

SHORT / SWING / MEDIUM Opportunity Queue 分开；跨策略不做虚假的统一机会总分。

### P3 — 长期学习与模型治理

真实 Decision 样本足够后再深化：

- Behavioral Risk
- Counterfactual Audit
- Advanced Outcome Evaluation
- Shadow Policies / Calibration
- Model Governance

---

## 27. 明确 Deferred / Non-goals

当前不优先或明确不做：

- 付费 Tushare / 商业实时数据
- 券商连接、账户读取、下单、自动交易
- SaaS / 多用户 / 云账户体系
- 后台常驻监控（Q59 暂定 A）
- 全市场分钟级实时监控
- ETF 专属复杂分析与 Look-through
- 北交所正式支持
- 管理层 Guidance 历史可靠度评分（LOW PRIORITY / DEFERRED）
- 隐私最小披露 Context Builder（DEFERRED）
- 以技术指标为核心的选股/交易系统
- AI 自动调用、AI 自动修改正式 Thesis/Decision

---

## 28. 仍未冻结 / 需要真实数据再校准的项目

以下不是永久参数：

- Q29 Prior Expectation Stack 的结构/权重
- R/R Gate：1.5 / 2.0 / 2.5
- 单笔 NAV 风险预算：0.75% / 1.00% / 1.25%
- SHORT/SWING/MEDIUM 价格 Backstop：7% / 12% / 20%
- Scenario Probability 区间生成方法
- Opportunity Quality 的具体数值权重
- Action Envelope 的数值门槛
- Behavioral Evidence 晋级门槛
- Decision TTL / Review By 的具体策略参数
- 免费数据源的实际 Freshness/SLA

这些必须通过 Frozen Decision Ledger、真实 Outcome、Shadow Mode 逐步校准，不得凭短期表现随意修改。

---

## 29. 授权边界

本文件的合并只代表：

> **产品方向已被记录并可作为后续设计/开发拆解依据。**

它**不自动授权**：

- P0 代码实施
- 新 PR Ready / Merge
- PR #59 Ready / Merge
- 生产数据接入
- Scheduler / Background Agent
- 券商、付费 API、自动交易
- 任何未在 `docs/NEXT_TASK.md` 明确授权的开发工作

后续实施仍必须由用户明确授权，再更新 `docs/NEXT_TASK.md`。

---

## 30. Data Governance Foundation — 2026-08-10 Priority Addendum

> 状态：**USER_CONFIRMED_NEXT_PRIORITY**
>
> 触发条件：当前正在收尾的 **Phase 2 Formal Thesis + S2D-M Migration / QA closure** 完成后优先进入本阶段；在此之前不抢占现有 Codex / Zcode / DeepSeek 工作。
>
> 本节记录产品与架构优先级，不改变第 29 节的治理原则：不得据此自行 Ready / Merge、迁移真实用户数据库、激活 stable schema 或越过 `docs/NEXT_TASK.md` 的明确实施边界。

### 30.1 从 Source-oriented 升级为 Dataset / Fact-oriented Data Governance

现有 `Field-Level Data Capability Registry` 继续保留，但数据层应进一步形成统一的 **Dataset / Fact Source Contract**。

标准链路：

`Provider → Raw Observation → Normalization → Canonical Fact → Temporal Semantics → Provenance → Data Health → Cross-source Reconciliation → Evidence / Thesis / Decision`

核心原则：

- Provider 返回值只是 **Observation**，不是自动成立的 Canonical Fact。
- Source Routing 必须按 **Dataset** 定义，而不是简单“Provider A 挂了就切 Provider B”。
- 每个 Dataset 明确 `canonical / verifier / fallback / historical_backfill` 角色；只有语义等价的源才允许自动 fallback。
- 语义不等价、历史范围不同、复权口径不同或时间含义不明时必须 fail closed，而不是拼凑成一个看似完整的结果。
- 现有 `DataHealthRecord` 继续负责“来源/模块当前是否健康”；本阶段新增的是“这条事实能否在某个时间点被合法使用”的 temporal/provenance contract，不重复建设 Data Health。

### 30.2 Temporal Semantics / PIT / Revision Contract

Dataset 至少要显式描述：

- `fetch_semantics`: `by_date | snapshot`
- `history_mode`: `by_date | snapshot_with_backfill | snapshot_only`
- `primary_source`
- `verifier_source`
- `fallback_source`
- `backfill_source`
- `history_floor_date`
- `history_horizon`
- `source_retired_date`
- `max_staleness`
- `point_in_time / as_of`
- revision / restatement semantics
- adjustment semantics
- historical-universe / survivorship-bias handling

Observation / Fact 在适用时应区分：

- `effective_at`
- `published_at`
- `observed_at`
- `fetched_at`
- `trade_date`
- `report_period`
- provider / endpoint / provider symbol
- source payload hash / data version
- normalizer version
- quality status / reason codes

不知道的时间或语义必须保持 `NULL / UNKNOWN`，不得由抓取时间、当前日期或其它近似字段伪造。

### 30.3 Local Research Fact Lake

建立 Vibe-Research 自己的 **Local Research Fact Lake**，目标不是复制一个通用行情平台，而是让正式投资判断具备可复查、可重放、可冻结的本地事实基础。

第一阶段优先保存长期价值高、需要 PIT / revision / provenance 的数据：

- Financial Statements / Financial Indicators
- Valuation Snapshot History（从接入日起自行积累）
- Corporate Actions / Adjustment Events
- Historical Instrument Universe / Listing / Delisting
- Index / Industry Membership
- Concept Membership Snapshot History
- Fund Holdings / Institutional Evidence
- Share Structure / Shareholder Data
- Raw Observation Metadata / Provenance

存储倾向：

- Raw immutable payload：JSON / Parquet
- Normalized facts：Parquet
- Analytical query：DuckDB
- Operational metadata / watermark / registry：SQLite

第一阶段**不要求**把所有实时行情、分钟线、tick、全部新闻都搬入 Lake；只为能明显提升 Thesis / Decision 可复现性的 Dataset 建湖。

### 30.4 External Project / Provider Positioning

当前候选的架构定位：

- **rootSunc/ashare-lake**：作为 DatasetSpec、PIT、history_mode、provenance、historical universe、source routing 的架构 benchmark；默认不直接成为 Vibe-Research production dependency。
- **HiThink-Tech/Financial-API**：作为补盲区、cross-source verifier 与 bulk ingestion 候选；在 LIVE_SMOKE 与数据契约验证通过前，不替换现有 Tushare / Eastmoney 已批准主事实链。
- **FTShare**：当前仅进入 LIVE_SMOKE / capability discovery；SLA、来源 provenance、历史/修订语义和条款明确前，不升级为 canonical production source。
- **QuoteMux**：不作为当前 production dependency；其 aggregation / fallback / health 思路可作为参考，但 Vibe-Research 应维护更严格的 Dataset-level contract。
- **free-stockdb**：可参考本地镜像、manifest、checksum 与查询引擎工程，但 mirror 完整性不能替代事实 provenance，因此不作为 canonical fact source。
- **TickDB**：当前产品阶段不接；只有未来明确进入实时/日内执行与高频数据需求时重新评估。

### 30.5 当前阶段完成后的执行顺序

在 **Phase 2 Formal Thesis + S2D-M Migration / QA closure** 完成后，优先顺序冻结为：

1. **DS-A1 — Canonical Data Source Contract v0.1**  
   先定义 DatasetSpec / ObservationEnvelope / TemporalSemantics / ProvenanceEnvelope / SourceRoutePolicy / ReconciliationPolicy；不先接新生产源。

2. **DS-H1 — HiThink LIVE_SMOKE v0.1**  
   独立验证认证/权限、rate limit、历史深度、分页、空值、财报 revision、report-date、复权、THS 板块/成分、基金、涨停与 market dumps；输出 machine-readable capability matrix。

3. **DS-L1 — Local Fact Lake PoC v0.1**  
   首批只选择少量高价值 Dataset，证明 `immutable raw observation → normalize → provenance → repeat ingest → revision detection → as_of query → DuckDB read`；仅使用隔离本地测试数据，不迁移真实用户数据库。

4. **DS-A2 — ashare-lake Semantic Gap Review**  
   将其 DatasetSpec / temporal / provenance 设计逐项与 Vibe contract 比较，明确 `COPY CONCEPT / ADAPT / REJECT / NOT APPLICABLE`，避免无边界复制整个项目。

### 30.6 Roadmap Gate

用户确认的路线顺序为：

`当前 Phase 2 / Migration closure → Data Governance Foundation (DS-A1/H1/L1/A2) → 再评估后续 Phase 3+`

因此，在当前阶段正式关闭后，**Data Governance Foundation 是下一优先工作，不应默认直接跳到 Phase 3 Campaign Trade Attribution**。

该优先级是 North Star 级产品决定；具体 executor 分工、分支、文件范围和验收合同仍应在届时同步到 `docs/NEXT_TASK.md` 后执行。

### 30.7 Verified Anti-Rewheel Reuse Registry — ARW-A1 (2026-08-10)

> 状态：**ARW_A1_INDEPENDENT_REVIEW = APPROVE_WITH_CURRENT_STATE_CORRECTION**
>
> 本节记录对高影响开源复用主张的已验证结论。上游结论必须绑定精确 repository / commit / LICENSE；“当前 Vibe 能力”判断也必须绑定明确 branch / SHA。研究结果是架构输入，不是代码替换或实施授权。

经独立复核后的复用定位：

- **pyeventsourcing/eventsourcing @ `099c92d` / BSD-3-Clause**：`SQLiteConnectionPool._create_connection()` 会先读取 `PRAGMA journal_mode`，但在非 WAL 库上仍执行 `PRAGMA journal_mode=WAL`。该模式不能满足 Vibe 的“schema/version 拒绝前零写入”契约，且上游不提供 Vibe 所需的 exact schema-version fail-closed gate。当前复用结论：`REJECT`，不得用于替换 S2D-M normal-open/version gate。
- **simonw/sqlite-utils @ `6a45683` / Apache-2.0**：`_sqlite_migrations`、`migration_set + name` 唯一记账、read-only `pending()/applied()`、单迁移事务与 `stop_before` 均具有未来参考价值；但它不等价于 Vibe 的 schema-version / downgrade protection / zero-write open contract。当前复用结论：`DEFER / ADAPT_CONCEPT`，适合作为未来 v2→v3→v4 多版本治理参考，不改写当前已验收显式迁移链。
- **youngseongshin/thesis-investment-os @ `9d50ecf` / MIT**：Evidence / Thesis 的 Python dataclass 虽为 `frozen=True`，但持久层包含 `INSERT OR REPLACE` 等可变写入模型，不能替代 Vibe 的 Formal Thesis immutable original / revision / canonical delta / frozen evidence 不变量。当前复用结论：Thesis/Evidence 持久模型 `REJECT`；其中 `process_score / result_score / outcome_confidence`、failure-mode 与 Prediction/Outcome calibration 思路可作为未来 `ADAPT_CONCEPT` 候选。
- **muye1202/VerumTrade @ `ffd5866` / Apache-2.0**：`EvidenceLedgerItem`、accepted/downgraded/rejected admissibility、`reasoning_trace`、`decision_diff` 已验证存在；其价值主要在 Evidence Arbitration 与 plan→final decision-diff 语义。上游没有 Vibe 要求的 Frozen/immutable Decision 持久账本。当前复用结论：`ADAPT_CONCEPT`，未来可用于 Decision Challenge / Frozen Decision Audit / Evidence Arbitration 设计，不直接复制其决策存储模型。
- **TauricResearch/TradingAgents @ `a33fd4c` / Apache-2.0**：decision log 不是纯 append-only；pending decision 的 outcome/reflection 会原位替换并通过临时文件重写，且允许 rotation 清理。当前复用结论：持久化模型 `REJECT`，不得替代 Vibe 的“Frozen Decision 不变 + Outcome 独立追加”方向。
- **virattt/ai-hedge-fund @ `eff8a73` / MIT**：`ClampEvent` 风控审计、`abstain != neutral`、PromptCache 每决策保存 exact prompt/response 三项已验证。Vibe 已有更保守的确定性执行限制，因此不照搬 clamp 行为；`ClampEvent` audit-event 形态、abstain 聚合语义、prompt replay/audit 可作为未来 `ADAPT_CONCEPT` 候选。

#### 30.7.1 Anti-Rewheel Hard Rules

后续任何“避免重复造轮子”提案都必须遵守：

1. **Exact-head evidence first**：必须记录上游 repository、verified commit、LICENSE、exact file / symbol；README 或二手调研不能单独作为实施依据。
2. **Do not regress Vibe invariants**：外部实现如果弱于 Vibe 已冻结不变量，只能 `REJECT` 或抽取局部概念，不得以“减少代码量”为由降级审计性。
3. **No mid-flight subsystem replacement**：已经有独立 QA contract 和全绿验收的 subsystem，不因发现新库就中途换实现；除非新证据证明替换方案完整满足现有 contract 且用户单独授权重开。
4. **Concept reuse before dependency reuse**：优先采用 `ADAPT_CONCEPT`，只有在许可证、语义、维护风险、测试合同与产品边界都匹配时才讨论 `COPY_CODE` 或 runtime dependency。
5. **Mutable upstream is not an immutable ledger**：living-object Thesis、原位 outcome 回填、`INSERT OR REPLACE` 等模式不得用于替换 Formal Thesis / Frozen Decision / append-only Outcome 的审计不变量。
6. **Research must pin Vibe state too**：对“Vibe 当前是否已有该能力/缺陷”的判断必须写明 Vibe branch + exact SHA，禁止用未标明版本的本地工作区状态覆盖已验收 branch 结论。

#### 30.7.2 S2D-M Current-State Correction

ARW-A1 研究读取到的 protected stable `feature/research-system-v01@1be2ecba...` 仍包含旧 `initialize_store → WAL → schema validation` 路径，这是因为已验收实现尚未合并到 stable；该 stable 落后状态**不能被解释为 S2D-M blocker 重新出现**。

当前正式治理结论冻结为：

- `PR #76 / S2D-M-R1 @ 306f973` 已将 existing DB normal-open 改为 immutable read-only exact schema-version gate，只有通过门禁后才进入 writable/WAL 路径。
- `PR #77 / QA3-R2 @ 4b9aabf` 已对 `NORMAL_OPEN_ZERO_MUTATION`、reserved scratch、migration→Formal bridge、backup immutability、rollback 等合同完成最终全绿验证。
- 因此：`NORMAL_OPEN_ZERO_MUTATION = CLOSED`，`S2D_M_PRODUCTION_SAFETY = CLOSED`，`S2D_M_MIGRATION_QA = CLOSED`。
- 不得仅因 stable 尚未合并这些 Draft PR，就创建第二套重复修复或重新打开同一 blocker；只有未来 exact-head regression 证据才能重开。

#### 30.7.3 Post-Phase2 Reuse Candidate Pool

当前进入未来候选池、但**未授权实施**的概念：

- sqlite-utils：migration ledger / migration-set governance / read-only pending / stop-before。
- thesis-investment-os：process quality 与 result quality 分离、failure-mode、Prediction/Outcome calibration。
- VerumTrade：Evidence admissibility arbitration、accepted/downgraded/rejected + reason、decision-diff。
- ai-hedge-fund：ClampEvent-style audit event、abstain semantics、prompt/response replay cache。

以上候选不得改变当前 Data Governance 执行顺序：`DS-A1 → DS-H1 → DS-L1 → DS-A2`。是否进入产品实现，必须在对应未来 slice 中重新对照 Vibe contract、写入 `docs/NEXT_TASK.md` 并获得明确授权。
