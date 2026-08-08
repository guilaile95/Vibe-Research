# 项目当前状态

> 稳定分支：`feature/research-system-v01`
> 稳定 Head：`3e1ecfaf107b4b1741a9b7e7da90da3173752444`
> （Merge PR #54，2026-08-08）
> 当前任务与停止点：[`docs/NEXT_TASK.md`](NEXT_TASK.md)（唯一当前授权任务）
> 治理契约与门禁：[`docs/GOVERNANCE.md`](GOVERNANCE.md)
> 长期候选与依赖：[`docs/PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md)
> 工程执行规则：根目录 [`AGENTS.md`](../AGENTS.md)

本文件是**项目状态唯一权威**：只描述稳定分支已具备的能力、当前授权与总体状态；
不维护 Draft、worktree 存在性、锁定目录等瞬时状态（以 `git worktree list` 与
GitHub 现场为准）。其他文档链接引用本文件，不复制完整状态。

## 1. 系统形态

| 层级 | 当前实现 |
|---|---|
| 仓库 | Public；MIT License；default branch 为 `feature/research-system-v01` |
| 前端 | React 19 + TypeScript + Vite 6 + Tailwind；默认开发端口 `:5899` |
| 后端 | FastAPI + Uvicorn；默认端口 `:8900` |
| A 股数据 | `backend/astock.py` + 仓库内 `a-stock-data/`；公开数据源、受控缓存与降级 |
| 全球指数/美港股子集 | `backend/gstock.py` + `global-stock-data/` |
| 用户数据 | `VR_DATA_DIR` / 用户目录 / localStorage；持仓、账户资金、模型密钥不进 Git |
| 结构化存储 | 交易流水、决策反馈、决策依据、信号账本、收益归因等使用独立 SQLite 或用户目录文件 |

## 2. 已上线的决策闭环

当前稳定分支已形成以下链路：

1. 每日复盘与市场环境聚合；
2. 持仓与账户资金维护；
3. 结构化持仓建议与账户执行约束（含 P2-3 可用现金安全垫约束）；
4. 交易流水记录；
5. 决策反馈与采纳/结果统计；
6. Decision Evidence 与 Signal Ledger；
7. 收益归因与历史快照。

核心边界：

- 持仓建议使用固定七阶段校验管线，关键数据缺失时失败关闭；
- 账户资金未配置不解释为 0；执行阶段受可用现金安全垫约束
  （`portfolio_advice_cash_constraint.apply_available_cash_constraints`，P2-3），
  未配置/损坏时以 limitation 降级；
- 非法执行比例、缺失决策身份不得进入 Evidence/Signal/Outcome；
- 历史错误归档不自动回填、删除或改写；
- 展示路径可使用 stale-while-revalidate，建议生成路径不得使用不可接受的陈旧核心数据。

## 3. 研究与数据能力

- 板块研究工作台支持真实路由、研究栏目、研报发现与安全导入、代表公司动态数据；
- 个股数据覆盖行情、估值、财务、公告、研报、融资融券、大宗交易、股东户数、
  分红、龙虎榜、解禁、板块归属、个股资金流等；
- 数据健康中心展示来源状态、覆盖、陈旧性、错误摘要和是否阻断建议；
- 每日复盘包括市场宽度、情绪、板块排名、成交活跃度及历史比较；
- 技术指标模块已上线（PR #41）：MA/MACD/RSI/布林带/量比等展示层（无 KDJ）
  （`backend/technical_indicators.py` + `TechnicalIndicatorsCard`/`KlineChart`）；
  持仓建议上下文仍显式 `technical_indicators_available=false`，不编造技术位；
- 北向资金 HKEX 官方日统计权威源已上线（PR #40，`GET /api/market/northbound`）；
- shadow-mode 顶风险分析已上线（PR #42，只读观测）。
- Intel Daily Digest 已上线（PR #50，2026-08-07）：板块级日摘要持久化与 API
  （`backend/intel_digest_{store,service,router}.py`，`/api/intel-digests`）、
  前端生成/保存状态机（`intelDigestOrchestrator`/`intelDigestView` + Intel 页
  digest 面板）、来源时间戳完整性（不伪造 published_at）、material status
  （normal/partial/unavailable）、指纹去重、独立 SQLite（`intel_digest.sqlite3`）；
  CI 新增 `e2e-intel-digest-smoke` job。

### BK-11 状态

BK-11（短线市场事实层与复盘闭环）的生产接入、调度、回填与 Slice 4 继续
**暂停/归档**（Issue #48 原正文是 2026-08-06 的 PAUSED/ARCHIVED 历史快照；
Issue OPEN 本身不构成授权）。当前仅新授权 zero-cost source research 的恢复、
验证、独立复审与 Draft PR 发布；原研究分支保持 frozen evidence branch，研究成果
只能从当前稳定基线新建 recovery 分支迁移。该授权不包含生产 BaoStock ingestion。

## 4. 界面与工程治理

### 应用视觉系统

PR #36 已上线：统一字体、色彩、卡片与页面标题系统；桌面侧栏与移动抽屉共用
同一导航数据和 JSX；支持 Escape、焦点约束/返回、背景 `inert`、滚动锁、断点
切换与 reduced-motion；嵌套导航只保留一个 `aria-current="page"`；暗色/亮色、
多视口、横向溢出和关键交互已完成运行时验证。

### 工程治理

PR #37 已上线，`AGENTS.md` 为唯一规则正文；2026-08-07 起 `docs/GOVERNANCE.md`
为 Git/GitHub 治理契约唯一正文（文档权威链、CI 分级、分支保护策略、PR 恢复方案）。

Engineering Reliability B1/B2 已关闭：PR #52 将平台特定 exact dependency locks、
双平台 canonical lock check 与离线测试纳入稳定分支；PR #53 将当前 workflow 的
官方 Actions 更新为 `checkout@v7`、`setup-python@v6`、`setup-node@v6`。

2026-08-08 仓库转为 Public 后，稳定分支已启用最小 legacy Branch Protection：
禁止 force push 与删除，合并要求四项离线确定性 CI；管理员保留 emergency bypass。
精确配置与历史 Private/403 快照见 `docs/GOVERNANCE.md`。

## 5. 当前授权

- **当前已授权产品开发任务：无。**
- 当前授权任务为 BK-11 Zero-Cost Source Research Recovery & Publication v0.1，
  仅限 research closure / validation / independent review / Draft PR。
- BK-11 production ingestion / scheduler / backfill / Slice 4 仍未授权。
- PR #47（BK-11 Tushare ingestion v0.2）保持 Draft / OPEN，未授权处理。
- PR #43（Intel Daily Digest v0.1）已 CLOSED / 未合并，
  superseded by PR #50（recovery 已并入稳定分支）。

## 6. 本地环境边界

当前可访问用户 Windows 文件系统；所有 worktree 状态以现场
`git worktree list` / `git status` 核验为准。历史本地目录只有在完成现场核验后
才允许清理；远端开发不因此阻塞。本文件不维护瞬时目录状态。

## 7. 最近稳定合并

| PR | Merge SHA | 内容 |
|---|---|---|
| #54 | `3e1ecfaf107b4b1741a9b7e7da90da3173752444` | Post-B1/B2 authority state sync |
| #53 | `2316ba64e59797291253c84367457a53039297eb` | Actions modernization（B2 closed） |
| #52 | `fd7cdaa299fc61f9a527f4db2861f72335a3c709` | Python dependency reproducibility（B1 closed） |
| #50 | `1339f7aa6ecb97bb2a0612ca7a61e0995cf3ccdb` | Intel Daily Digest recovery（原 PR #43 有效功能迁入稳定） |
| #49 | `77a7ace25c3668d0ccd88be23d8db318416740dc` | 治理契约纳入稳定（GOV） |
| #46 | `cd17fec2cc28d8dd9ea9b8e37df0cc6c394a0b18` | BK-11 生产输入源审计（BLOCKED，冻结点） |
| #45 | `12593c340845a60b70c925bdceb7265b5710511d` | BK-11 历史集成进 Daily Review |
| #44 | `17c7f1dadd16a3ced2b73588fa9d5a987fa86520` | BK-11 纯计算链 |
| #42 | `6da75b9` | shadow-mode 顶风险分析 |
| #41 | `ad844742e90d37e808c910c8af19246aaed0d331` | 技术指标与价格触发 |
| #40 | `40d0dba` | 北向资金权威数据契约（BK-03 切片 2） |
| #39 | `12db498394e84d6104c805a16d50c0fa48ff61e9` | 状态收口文档（PR #38 后） |
| #38 | `838bd6cec40fd861bc286e8322e22298c7fd0ea6` | 板块代表公司主力资金流摘要 |
| #37 | `632117b348a8f27505c84e89c10d3df380b4e119` | DRY 与端到端交付治理 |
| #36 | `1d31e5639989220c7cb51d44954f8f4d940e9874` | 应用视觉系统与移动导航 |
| #35 | `f5f420662e3246f56d371e6020efa4de725679e9` | Decision Trace 权威契约修复 |
