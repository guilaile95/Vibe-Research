# Vibe-Astock 选择性吸收决策

> 历史决策：下文原结论及 2026-08-07 的暂停记录只描述当时基线与授权。
> 不应据此推断后续实现仍全部暂停，也不构成恢复实施的授权。
> 当前工程状态先按 [文档导航](README.md) 核对 live GitHub；后续采用范围见本页末尾的原始证据入口。

参考仓库：

```text
simonlin1212/vibe-astock
```

调研基线：

```text
f4030751b612acb2a017135345005b7befb919e9
```

## 结论

有条件采纳；禁止整体合仓。

BK-11「短线市场事实层与复盘闭环」已纳入 `docs/PRODUCT_BACKLOG.md` 路线图，**当前未授权实施**。任何切片都必须单独授权；Slice 0 未给出 Go 结论前，不得进入产品实现。

（2026-08-07 更新：BK-11 已暂停/归档，Issue #48 PAUSED/ARCHIVED；恢复实施需新的明确授权）

## 技术判断

- Python / FastAPI / React / TypeScript / Vite / Tailwind 基本兼容；
- LangGraph / LangChain 属新增运行时，不进入 MVP；
- 可复用的是业务指标口径与短线复盘闭环思想，不是其仓库骨架。

## 架构判断

- 业务指标有互补价值：市场宽度、涨跌停、炸板、连板梯队、晋级率、封板质量、亏钱效应、题材结构等；
- 冲突点包括：`vr/` 目录、`server.py`、动态路由注入、内存任务状态、独立 JSON 存储、第二套前端/鉴权/CORS、MiMo 专用配置；
- 所有接入层必须按当前 Vibe-Research 架构重新实现，不得复制第二套运行时。

## 性能边界

- 同一交易日共享原始数据快照；
- 指标使用纯函数；
- 按 `source + trade_date` 缓存；
- LLM 不进入实时数据主路径。

## 维护边界

- 不复制第二套存储、路由、前端、鉴权、任务模型和 AI schema；
- 不把短线事实层做成与 Daily Review / Data Health / Decision Evidence 平行的孤岛；
- T+1 验证条件映射到现有 Decision Evidence / Feedback / Analytics，不新建反馈存储。

## 最终策略

- 采纳业务思想和指标口径；
- 接入层全部按 Vibe-Research 现有架构重写；
- Slice 0 只做可行性审计；
- Slice 1–4 先交付硬指标与可复核事实；
- Slice 5 的 AI 叙述仅为可选增强，且不得重新计算核心数字。


## 后续采用证据入口

以下按证据类型导航，不复制各任务的完成清单或把历史报告升级为实时状态。
每篇记录的日期、基线、来源与验证范围仍适用；当前代码、合并及部署状态分别核验。

| 分类 | 范围与原始证据 |
| --- | --- |
| 已采用的软件合同 | [2026-10-12 短线研究](research/SHORTLINE_RESEARCH_ADOPTION_20261012.md)：共享原始回执、日期/覆盖约束、归档回放和研究视图；[封板质量](research/ASTOCK_SEAL_QUALITY_ADOPTION_20261012.md) 与 [题材研究](research/THEME_RESEARCH_ADOPTION_20261012.md)：只读研究计算与归档输入合同 |
| 已采用的工作流与设置 | [六阶段公司研究](research/COMPANY_RESEARCH_WORKFLOW_20261012.md)：固定输入、显式模型预算和非权威草稿；[设置与平台](research/SETTINGS_PLATFORM_ADOPTION_20261012.md)：本地 SEC 联系设置、手动发布检查与既有平台合同 |
| 未接通或未启用的范围 | 短线/题材真实 transport、生产收盘调度和真实历史样本积累，按上述各篇的剩余验收段落判断；SEC 设置没有 SEC transport，手动发布检查没有下载安装/升级功能。不能从客户端、适配器或环境变量的存在推断这些能力已启用 |
| 尚需独立验证的范围 | 真实供应商权限与数据完整性、真实模型质量/数值语义、原生平台安装及真实用户使用；离线 fixture、CI、配置检查和服务健康不能互相替代。公司研究仍明确保留 `numeric_claim_verification=NOT_EVALUATED` |

上述采用继续遵守本页的单一运行时、共享存储、既有 authority 和覆盖率边界。
部署配置见 [运行指南](GETTING_STARTED.md)，只读检查见 [脱敏运行自检](RUNTIME_DIAGNOSTICS.md)。
