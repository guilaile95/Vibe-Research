# 项目状态与验证范围 · 2026-10-02

这是带日期的交付快照，便于理解版本和证据，不是实时任务数据库。最新事实以 [稳定分支](https://github.com/guilaile95/Vibe-Research/tree/feature/research-system-v01)、各 PR、CI 和用户明确授权为准。返回 [文档导航](../README.md)。

## 三个版本面分别核验

| 对象 | 本次核验结果 | 不代表什么 |
| --- | --- | --- |
| 远端稳定分支 | `feature/research-system-v01`，`aab09365f5bb18699268aafe7ff333e84c71c87d` | 不包含尚未合并的 Draft 修复 |
| 本地集成源码 | 已组合可靠性基线、三批修复及保留的本地编辑；集成树 `13c1defc6e1b3821c49e9dfd7378772694b0c10f` 已核验 | 本地私有集成不是公开下载版本，也不等于 stable 已合并 |
| 正在运行的服务 | 本次文档任务及前一轮源码集成均未切换服务 | 不能仅据源码 SHA 宣称用户运行的是新版 |

本地私有恢复记录及提交只保存在本地；公开文档分支从已公开 stable 建立，不携带这些提交或用户未跟踪文件。

## 可审阅的交付

以下五个 PR 在本次回读时均为 **Open / Draft / unmerged**。短 SHA 只用于阅读，链接固定到完整提交；合并关系仍以 PR 页面为准。

| PR | 已核验 HEAD | 范围与证据入口 |
| --- | --- | --- |
| [#356](https://github.com/guilaile95/Vibe-Research/pull/356) | [`15804a72`](https://github.com/guilaile95/Vibe-Research/commit/15804a72a2d6da69e8f40048003ad58f8a58909b) | 数据与持久化可靠性基线；[完整评估](https://github.com/guilaile95/Vibe-Research/pull/356#issuecomment-5955194753) |
| [#357](https://github.com/guilaile95/Vibe-Research/pull/357) | [`7556c893`](https://github.com/guilaile95/Vibe-Research/commit/7556c893d978d8dcb0ba72621134554dbfd3cda2) | 独立桌面交付历史；当前不推进下载打包或安装器验收 |
| [#358](https://github.com/guilaile95/Vibe-Research/pull/358) | [`92abc3fb`](https://github.com/guilaile95/Vibe-Research/commit/92abc3fbebee593cc1b675bdce5d8ba9ee2a850b) | qfq 来源与口径、财务零值、持仓建议取消保存；[CI 11 项](https://github.com/guilaile95/Vibe-Research/actions/runs/37028167769) + [启动检查 1 项](https://github.com/guilaile95/Vibe-Research/actions/runs/37028167772) 成功 |
| [#359](https://github.com/guilaile95/Vibe-Research/pull/359) | [`61bb2a68`](https://github.com/guilaile95/Vibe-Research/commit/61bb2a6821fdee59f17868fa4842a75e5ebeffce) | 完整分页证据覆盖、证券导航、未保存表单；[11/11 CI](https://github.com/guilaile95/Vibe-Research/actions/runs/37033526554) 成功 |
| [#360](https://github.com/guilaile95/Vibe-Research/pull/360) | [`ddc9fa05`](https://github.com/guilaile95/Vibe-Research/commit/ddc9fa050ccee43c5af04bc7b8ac3fd543a19660) | 拒绝变更来源的旧索引、披露摘录范围；[11/11 CI](https://github.com/guilaile95/Vibe-Research/actions/runs/37034739774) 成功 |

#358 基于 #356；#359 与 #360 分别基于 #358，不能把它们误读为已按序合并到 stable。#357 是单独的桌面分支。

## 已有能力与仍缺的证据

| 能力 / 工作 | 当前证据 | 验证边界与下一步 |
| --- | --- | --- |
| 研究留痕与正式决策链 | Evidence、Thesis、Frozen Decision、手工交易归属和 Outcome 已有实现及工程测试 | 用户长期价值仍未验收；按真实任务观察，不能制造交易或样本 |
| 本地组合源码 | 已有 843/843 前端测试、构建、导航与表单浏览器验证、93 项报告/API 回归 | 测试子集有重叠，不能相加为覆盖率；不证明所有功能均通过 |
| 全功能补测 | 正在基于最终集成快照补完整功能矩阵 | 先前 26 状态 / 120 循环只是有限合成检查；待提交逐项通过、失败、阻断与未测列表 |
| AI 答案质量 | 17 个离线案例准备完成；真实模型调用 0、真实模型计分 0，`NOT_EVALUATED` | 正在确认提供方、模型、安全凭据与有界预算；不能默认某家服务已采用，缺凭据需询问而非跳过 |
| 行情可靠性 | 数据口径与降级已有修复及隔离验证 | 真实来源的完整性、新鲜度、持续可用性仍待验收；绿 CI 不证明真实行情可用 |
| 多页面视觉优化 | 原型正在扩展 | 原型不是已落地产品 UI；进入实现需对应任务范围与验收 |

报告检索以摘录提供证据。#360 可拒绝已变更来源的旧索引，并在 API / 模型上下文披露 `EXCERPTS_ONLY` 与截断；它**不保证捕获长文后段更正**，当前 UI 仍为既有通用摘录说明。PDF/OCR 忠实度和真实模型结论质量需要单独评价。

取消保存以应用已观察取消事件、且对应事务尚未提交为边界；不会撤销已提交结果，也不证明远端模型停止计算或退回费用。

## 后续顺序与维护

1. 收齐最终集成快照的功能矩阵，区分缺陷、环境阻断和未测能力。
2. 明确真实模型提供方与预算后执行已准备案例，回读引用与答案；保持离线和真实评分分开。
3. 用真实刷新记录验收行情来源、时间和覆盖，再评价研究到复盘的实际使用价值。
4. 原型设计单独审阅；桌面打包暂不推进。以上记录不是自动开发、合并或服务切换授权。

工程恢复见 [CURRENT_STAGE](../CURRENT_STAGE.md) 与 [#203](https://github.com/guilaile95/Vibe-Research/issues/203)；正式观察见 [#162](https://github.com/guilaile95/Vibe-Research/issues/162)。此次读取的 #162 最新评论仍为等待第一次真实会话，Day 1 未开始；旧正文与评论措辞不一致时，按时间和用户明确决定核对，不从测试推导激活。
