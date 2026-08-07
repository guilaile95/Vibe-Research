# Vibe-Astock 选择性吸收决策

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
