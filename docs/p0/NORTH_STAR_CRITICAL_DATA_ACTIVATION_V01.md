# North-Star Critical Data Activation v0.1（P0-DS1，含 R1 + R2 correction）

## R2 Correction（semantic closure blockers 修复）

1. **Disclosures same-day look-ahead**：astock.announcements 保留 provider
   原始 notice_at 时间戳（transport 层不再丢时间）。可见性按 publish time
   <= as_of 精确证明（北京时间 naive → UTC，无任意 tolerance）：
   同日早于 as_of 可见、晚于 as_of 排除；date-only 且 == as_of 北京当日 →
   fail closed UNKNOWN（`disclosures:same-day-date-only-unprovable`，
   绝不猜已发布）。
2. **Real sector context**：industry identity alone 不再 USABLE。完整链路
   security → industry identity（individual_info）→ matching sector
   observation（get_overview 板块资金流精确匹配，不模糊猜）→ sector
   state/data + provenance + freshness（updated 北京日期 >= market fact
   date）。链任一环缺失 → UNKNOWN/STALE + 显式 blocker。
3. **Market/sector Data Health 连续性**：production market_sector wrapper
   按 success/partial/failure 更新 `sector_research` 健康事件。
4. **Data Health presentation closure**：status 筛选改 presentation-state
   语义（unavailable 排除 NOT_INITIALIZED；新增 not_initialized 筛选）；
   全部来源未初始化 → 全局 badge 中性「未初始化」（绝不红色）。

## R1 Correction（reviewer blockers 修复）

1. **Disclosures 时间语义**：FACT TIME（公告日，北京时间日历日）/ RETRIEVAL
   TIME（fetched_at，仅 provenance）/ EVALUATION TIME（as_of）明确分离。
   fetched_at 晚于 as_of 是正常网络耗时，绝不天然 NOT_EVALUATED；
   look-ahead 防护只针对 FACT TIME：公告日晚于 as_of 北京日的条目从判定
   排除（历史 as_of 无 look-ahead；全部未来 → EMPTY_BUT_VALID）。
2. **market_sector 不再 market-only USABLE**：市场上下文（广度信封）+
   security-relevant sector context（astock.individual_info 行业）必须同时
   positive-proof；sector 无法证明 → UNKNOWN + 显式 blocker
   `market-sector:blocker=SECURITY_SECTOR_CONTEXT_UNAVAILABLE`。
3. **Data Health observation continuity**：production wrapper 在业务
   observation boundary 更新既有 event store（announcements / financials
   success/partial/failure）；写入副作用绝不进入 pure evaluation core。
4. **Data Health 显示计数**：确认不可用排除 SOURCE_NOT_INITIALIZED；
   全部计数从真实 items 动态派生（无 hardcode 11/15）；not_initialized
   badge 与 aria-label 均中性。
5. **Real provider path**：production wrapper 测试仅替换 transport
   boundary（monkeypatch provider 函数），证明
   wrapper → parse → temporal → capability result → Data Health 全链连通。

## 定位

让 North Star P0 真实持仓决策链获得真实、可解释、带 freshness/provenance
的数据输入：Market/Sector、Disclosures、Financials 从「因为没有 adapter
而固定 NOT_EVALUATED」变为真实 capability 评估结果。Data Health 同时把
「未初始化/未检测」与「不可用」区分开。

## Capability 评估语义（DDA1 冻结，未修改）

| Capability | SHORT | SWING | MEDIUM | 数据路径 |
| --- | --- | --- | --- | --- |
| cap.security.price_reference | ✓ | ✓ | ✓ | Fact Lake `ds_tushare_daily`（既有 #116 adapter） |
| cap.context.market_sector | ✓ | ✓ | — | `market.get_market_breadth` 真实信封（既有） |
| cap.security.disclosures | ✓ | ✓ | ✓ | `astock.announcements` 东财公告（既有） |
| cap.security.financials | — | — | ✓ | `astock.financials` 同花顺财务摘要（既有） |

全部 REUSE > NEW：未新建 provider、未新建 Fact Lake dataset、未修改 DDA1。

### market_sector（`critical_data_market_sector_adapter.py`）

- retrieval time（fetched_at）绝不当作 market fact time（trade_date）；
- provider 显式 trade_date → 事实日期以 provider 为准
  （`date-basis=provider-trade_date`）；
- provider 未提供 trade_date → 以真实 observation timestamp（fetched_at）
  + 权威交易日历归属 MARKET OBSERVATION DATE
  （`date-basis=observation-time`）；盘中/收盘后属当日 session，
  周末/节假日属最近交易日；caller as_of 绝不创造 provider 没有提供的
  fact date；
- NO LOOKAHEAD：market fact date 晚于 as_of → NOT_EVALUATED（live 快照
  不得重标为 historical date）；
- envelope status=partial → UNKNOWN（数据不足不伪造 USABLE）；
- provider 异常 → ERROR；不凭空产生 market regime。

### disclosures（`critical_data_disclosures_adapter.py`）

- EMPTY_BUT_VALID：查询成功且无公告 = 有效空事实，USABLE + 显式标记，
  绝不视为 provider failure；
- 有公告 → USABLE + count / latest_notice_date / fetched_at / source；
- fetched_at 缺失/非法 → UNKNOWN（无法证明 freshness）；
- fetched_at 晚于 as_of → NOT_EVALUATED；provider 异常 → ERROR。

### financials（`critical_data_financials_adapter.py`）

- 复用既有真实财务读取路径做 retrieval probe；dataset 语义对齐
  `ds_financial_indicator`（REPORT_PERIOD / RESTATABLE）常量声明；
- 禁止 local latest == authoritative latest：provider 的「最新报告期」
  只是 provider-claimed，不构成 applicability authority；
- DI2 尚无 required report period applicability authority →
  retrieval 成功也只能 NOT_EVALUATED，且 blocker 显式为
  `financials:blocker=REPORT_PERIOD_APPLICABILITY_NOT_RESOLVED`
  （经 authority_refs 承载 —— CCD dependency_results 为 exact-shape
  契约，不可扩字段）；
- provider 异常 → ERROR；无数据 → UNKNOWN。

## Decision Inbox Integration

`decision_inbox_runtime_assembler` 移除「无 adapter → 固定 NOT_EVALUATED」
占位，改为 per-capability 真实 evaluator 分发。NOT_EVALUATED 仍是合法结果
（数据缺失 / applicability 未解决 / 未到评估时点），绝不为了灯变绿强制
USABLE。测试注入确定性 fake，不发网络请求。

## Data Health 语义修正（展示层）

- backend 三态 contract（normal/partial/unavailable）保持不变；
- 前端 presentation 层新增 `presentationState`：
  `SOURCE_NOT_INITIALIZED` → `not_initialized`（中性展示，绝不红色「不可用」）；
- Freshness 独立显示：`freshnessState` → FRESH / STALE / UNKNOWN；
- 「尚未初始化」独立于质量三态计数（不再是「不可用子集」）；
- `isProblemSource` 排除未初始化（未检测 ≠ 问题）。

## Hard Risk Data Inputs（盘点结论，非 Hard Risk 引擎设计）

HARD_RISK_INPUT_COVERAGE = **PARTIAL**

| 输入 | 现状 | 覆盖 |
| --- | --- | --- |
| 重大公告 | disclosures capability 真实 evaluator（本 Slice 打通） | READY |
| 财务异常 | financials capability retrieval 打通；report-period applicability authority 缺失（显式 blocker） | PARTIAL |
| 交易资格/特殊状态 | 仅有零散信号（astock 字段 / limit_up pool / BK-11 facts），无正式 authority | PARTIAL |
| 核心数据完整性 | Data Health 权威（既有） | READY |

本 Slice 不重新设计 Hard Risk Engine，不直接让 AI 生成 Hard Risk authority。

## 验证

- backend：三个 adapter 专项测试（全状态分支 + 输入校验 + refs）+
  assembler dispatch + Real Observation（真实形状 600519 全链，
  §11 A–G 接受矩阵）+ 609 relevant regression；
- frontend：dataHealthView presentation/freshness 契约测试 + 全量 +
  typecheck/build；
- EXACT_HEAD_CI 覆盖 backend 全量 + frontend + Playwright。

## 非目标

BK-11、我的研报、北向资金增强、新 Discovery、SEC3、新 design system、
手机端、新商业数据源、Tushare 付费依赖、自动交易、后台 scheduler。
本任务只服务 North-Star P0。
