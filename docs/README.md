# 文档导航

从 [项目首页](../README.md) 了解用途，再按当前任务选择入口。

| 我要做什么 | 入口 | 内容边界 |
| --- | --- | --- |
| 安装、启动、检查本机服务 | [运行指南](GETTING_STARTED.md) | Windows / Linux、三个服务、AI 配置与常见问题 |
| 了解当前进度和验证缺口 | [恢复坐标](CURRENT_STAGE.md) / 下文 GitHub 入口 | 回读当前 PR 与 exact-head CI；历史快照不充当实时状态 |
| 运行本地工程验证 | [测试指南](TESTING.md) | 离线测试、构建、隔离浏览器用例与验证边界 |
| 检测当前 API 配置 | [AI 连接检测](AI_CONNECTION_TEST.md) | 手动合成请求、费用与取消；不评价回答质量 |
| 制作 Linux 用户目录安装包 | [Linux 打包与运行](LINUX_INSTALL.md) | 独立安装/生命周期路径；不等于云端部署验收 |
| 接管工程任务 | [恢复坐标](CURRENT_STAGE.md) → [AGENTS.md](../AGENTS.md) | 当前授权、实际 Git 状态和协作边界 |
| 理解数据与研究调用链 | [架构](ARCHITECTURE.md) / [后端参考](../backend/README.md) | 实现入口；具体行为以当前源码为准 |
| 判断适用范围 | [已知限制](KNOWN_ISSUES.md) | 数据、模型、手工账户事实和真实使用边界 |
| 修改环境或依赖 | [依赖可复现性](DEPENDENCY_REPRODUCIBILITY.md) | 平台 lock 和版本合同 |
| 理解治理和产品方向 | [治理入口](GOVERNANCE.md) / [产品北极星](PRODUCT_NORTH_STAR_V01.md) | 权威来源和长期意图；不自动授权新任务 |

## 按研究任务阅读

1. **看市场、找线索**：从应用的每日复盘、资讯和发现入口开始，先看时间、来源与缺失状态。
2. **研究一个对象**：进入候选研究或个股数据，保存需要的 Evidence 和 Thesis，回到原始材料核对结论。
3. **留下决策依据**：用户明确确认后形成 Frozen Decision；实际成交或 no-trade 与后续 Outcome 分开记录。
4. **评价工具是否有用**：按 [Product Reality #162](https://github.com/guilaile95/Vibe-Research/issues/162) 记录真实任务，不能把测试或演示计为观察日。

## GitHub 与 Notion 的分工

- [稳定分支](https://github.com/guilaile95/Vibe-Research/tree/feature/research-system-v01)、[PR](https://github.com/guilaile95/Vibe-Research/pulls) 和 [CI](https://github.com/guilaile95/Vibe-Research/actions) 记录代码与验证事实；[工程授权 #203](https://github.com/guilaile95/Vibe-Research/issues/203) 与用户最新明确指令界定执行范围。
- [Notion 项目主页](https://app.notion.com/p/3be55152dfe881fd8552e356a79c7cf6) 与 [详细文档](https://app.notion.com/p/3e355152dfe881ee9effcfa720040127) 保留长期产品判断、评估和历史，访问需要对应工作区权限。
- 本地源码、远端稳定分支和正在运行的服务分别核验；其中一个更新不证明另外两个已更新。

## 历史资料

`research/` 下的评估、实验、执行记录按各自日期、基线和数据范围阅读。
[2026-10-04 公共集成记录](research/PUBLIC_INTEGRATION_20261004.md) 与
[2026-10-02 状态快照](research/PROJECT_STATUS_20261002.md) 保留历史身份。
[PROJECT_STATE](PROJECT_STATE.md)、[NEXT_TASK](NEXT_TASK.md) 和 [BK-11 执行记录](research/EXECUTION_STATE.md) 是历史入口，不作为当前任务队列。
新增结论优先链接原有证据，不复制整套日志；项目代理规则只在根 [AGENTS.md](../AGENTS.md) 维护。

- [K-line research linkage](KLINE_RESEARCH_LINKAGE.md): bounded event/evidence overlay and identity/date limits
- [Public stack and rollback](research/PUBLIC_STACK_ROLLBACK_20261004.md): dated ancestry and reversible integration gates

- [PA1 view ownership](PA1_VIEW_OWNERSHIP.md): asynchronous result identity and confirmed snapshot-write handling

- [Trade-list read ownership](TRADE_LIST_READ_OWNERSHIP.md): applied-filter identity and stale-response protection

- [RDP snapshot replay](research/RDP_SNAPSHOT_REPLAY_20261009.md): reopen an imported research generation, retain receipts, and run the offline two-generation example
