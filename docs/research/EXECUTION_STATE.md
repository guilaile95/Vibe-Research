# BK-11 执行状态

> 每阶段只记录一行状态；瞬时执行细节不写入本文件。

| 字段 | 值 |
|------|----|
| stage | bk11-integration-pure-compute（七阶段纯计算链统一集成） |
| status | REVIEW_PENDING |
| branch | integration/bk11-pure-compute-v0.1 |
| base | ad844742e90d37e808c910c8af19246aaed0d331（stable feature/research-system-v01） |
| candidate head | 当前分支 HEAD（含本状态文件提交；推送后以 `git rev-parse` 为准） |
| accepted head | —（待独立审查 APPROVED） |
| changed files | 集成 91 笔链内提交（54 文件，全部来自已批准 BK-11 阶段）；本分支仅追加 EXECUTION_STATE.md 状态行 |
| tests | py_compile OK / BK-11 focused 1559 / backend offline 3336（11 deselected, 1 warning）/ 全链路 e2e 23 断言 |
| reviewer verdict | PENDING |
| remaining findings | — |
| Blocker 2 | OPEN |
| Blocker 3 | OPEN |
| Blocker 6 | PARTIALLY CLOSED |
| production integration | not authorized |
| next eligible stage | TBD（审查 APPROVED 后从候选池选择未阻塞阶段） |

## 历史阶段

- bk11-tushare-ingestion-v0.2：branch feat/bk11-tushare-ingestion-v0.2，
  base cd17fec2cc28d8dd9ea9b8e37df0cc6c394a0b18（PR #46 合并后稳定分支）。
  实现 Tushare production ingestion（client / facts adapter / daily-facts
  v0.2 / store 质量单调写入 / ingestion service / CLI）；结果
  IMPLEMENTED_OFFLINE / LIVE_SMOKE_BLOCKED_CREDENTIAL（TUSHARE_TOKEN
  未配置，未执行 live 探测与 live smoke）；离线测试 3473 passed；
  阻塞文案保持；独立审查结论以 PR 描述为准。
- bk11-production-ingestion-v0.1：branch feat/bk11-production-ingestion-v0.1，
  base 12593c340845a60b70c925bdceb7265b5710511d（PR #45 合并后稳定分支）。
  来源合同审计结果：路径 C BLOCKED —— suspended_count 无可信来源、
  breadth 无日期绑定、legal-zero 未证明、全 A 快照运输层不稳定；
  生产写入未实现，阻塞文案保持原状；审计见
  docs/research/BK11_PRODUCTION_INPUT_AUDIT_V01.md 与
  BK11_PRODUCTION_INGESTION_V01.md；独立审查结论以 PR 描述为准。
- bk11-daily-review-history-v0.1：branch feat/bk11-daily-review-history-v0.1，
  base 17c7f1dadd16a3ced2b73588fa9d5a987fa86520（PR #44 合并后稳定分支），
  只读历史 API + Data Health source + Daily Review 页面区块；生产快照写入
  按规则 C 记录为上游输入缺失阻塞；第一轮复审 CHANGES REQUIRED
  （P1=1 前端 envelope 层级、P2=1 无界 SQL 查询）已修复：store 新增有界
  list_recent_snapshots（SQL LIMIT）、service 改用 days+1 有界读取、前端
  对齐 facts.facts/ladder.metrics/gap.metrics 正式合同并真实展示梯队数组；
  独立审查结论以 PR 描述为准。
- bk11-slice-3e-snapshot-selector：branch feat/bk11-snapshot-selector-v0.1，
  base 56ea49b186ed9e3387e3c0c6fb38d6bffbdf0d82（3d accepted head），
  accepted head e9ac68fe1ebd4e0629e870498884d5a58b3132ce（独立复审
  APPROVED，P0=P1=P2=0；首轮 CHANGES REQUIRED P2=2：全序决胜/
  final 硬优先，已修正并复审通过）。
- bk11-slice-3d-fact-digest：branch feat/bk11-fact-digest-v0.1，base
  33e08b1464a377bc204813d3592b3c67c0cef9ab（3c accepted head），
  accepted head 56ea49b186ed9e3387e3c0c6fb38d6bffbdf0d82（独立审查
  APPROVED，P0=P1=P2=0）。
- bk11-slice-3c-fact-summary：branch feat/bk11-fact-summary-v0.1，base
  0c4a2763b36210ea9d14d8dc0c7ae1fc6d2ab254（3b accepted head），
  accepted head 33e08b1464a377bc204813d3592b3c67c0cef9ab（独立复审
  APPROVED，P0=P1=P2=0；首轮 CHANGES REQUIRED P2=3：int 严格性/
  会话时间序/混合状态文档，已修正并复审通过）。
- bk11-slice-3b-fact-compare：branch feat/bk11-fact-compare-v0.1，base
  1bfafeacae4cddfa76c97f8e448905b8e2b9f286（3a accepted head），
  accepted head 0c4a2763b36210ea9d14d8dc0c7ae1fc6d2ab254（独立复审
  APPROVED，P0=P1=P2=0；首轮 CHANGES REQUIRED P2=3：reason 顺序/
  引用泄漏/partial 形状，已修正并复审通过）。
- bk11-slice-3a-fact-store：branch feat/bk11-fact-store-v0.1，base
  0d45ca02f7d7e4cc0e81580d478065cf04caf529（2K accepted head），
  accepted head 1bfafeacae4cddfa76c97f8e448905b8e2b9f286（独立审查
  APPROVED，P0=P1=P2=0）。
- bk11-slice-2k-daily-facts：branch feat/bk11-daily-facts-v0.1，base
  414de9d90711d0419b1e52216e943afbb9cad219（2J accepted head），
  accepted head 0d45ca02f7d7e4cc0e81580d478065cf04caf529（独立复审
  APPROVED，P0=P1=P2=0；首轮 CHANGES REQUIRED P2=1 observed_at 空值，
  已修正并复审通过）。
- bk11-slice-2j-correction：branch feat/bk11-ladder-gap-v0.1，base
  226a40005edf97e74f44acdc7cc5408b5162bdfa，accepted head
  414de9d90711d0419b1e52216e943afbb9cad219（独立审查 APPROVED，
  P0=P1=P2=0）。
