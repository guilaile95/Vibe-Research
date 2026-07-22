# 当前下一任务

## 上一任务（已完成）

~~对提交 **`5dec970`**（`feat: calculate executable add quantities`）做受控端到端验收。~~

- **状态**：已完成（见 `PROJECT_STATE.md` §11 验收记录）

## 上一任务（已完成）

~~增加「账户资金」手工填写窗口（`feat: add manual account funding input`）。~~

- **状态**：已完成（见 `PROJECT_STATE.md` §13）

## 上一任务（已完成）

~~修复账户资金前端响应解包与持久化 hardening（`88a1f83` / `f3d90af`）。~~

## 上一任务（已完成）

~~完善持仓手工维护：安全新增 / 精确编辑 / 删除确认（`9932601`）。~~

- **状态**：已完成并验收（见 `PROJECT_STATE.md` §15）
- 持仓支持：**新增**、**精确编辑**、**安全删除**
- `POST` 新增：同代码仍**加权合并**
- `PUT` 编辑：**精确替换**（不加权、不 upsert、不存在 404）
- 删除：确认弹窗 + 失败错误反馈；不写 closed
- 数量输入：**不再静默转换**
- 账户资金当时未参与持仓建议裁决；当前仅在 Validator 完成后追加只读指标
- 测试：`test_portfolio_edit_api.py` 23 passed；全量离线 667 passed（仅已知 Windows 例外）
- Playwright A–J：**53/53**；advice 请求数 0；真实数据 SHA 不变
- 功能提交：`9932601`

## 上一任务（已完成）

~~为持仓建议增加只读账户资金指标（`account_funding` 与 `account_metrics`）。~~

- **状态**：已完成并验收
- 仅增加只读账户资金指标；**尚未参与动作裁决**；可用现金约束留待下一阶段
- 动作 (action)、比例 (execution_size_pct_of_holding)、建议数量 (execution_quantity)、预计金额 (estimated_amount) 绝对保持不变
- Prompt 与 Validator 隔离，纯函数高精度 `Decimal(ROUND_HALF_UP)` 计算
- 离线专项测试 8 passed；全量离线 675 passed（仅已知 Windows 例外）

## 上一任务（已完成）

~~Vibe-Research 持仓建议架构收口——第一阶段（`refactor/portfolio-advice-architecture-v01`）。~~

- **状态**：已完成
- **核心变更**：
  1. Contracts 仅负责中立 Schema、枚举和交易单位
  2. Policy 负责全部投资比例、置信度和 partial 市场约束
  3. Validator 作为兼容 Facade，实际执行固定七阶段 Pipeline
  4. 将只读账户资金指标计算从 Service 拆分为独立纯函数模块 `portfolio_advice_account_metrics.py`
  5. 新建 Golden Tests (27 个场景快照)，锁定全部输出逻辑，保证重构过程行为不变
- **测试**：持仓建议专项 236 passed、1 warning、exit 0；全量离线 745 passed、1 failed、11 deselected、1 warning，唯一失败为 Windows `python3` 不可用导致 `fake 退出码 9009`
- **主要提交**：`9fa2428`、`70d2a71`、`67a1fc5`、`e3f44ef`、`0ee21aa`

## 当前下一任务

**待产品优先级确认**。

本轮持仓建议架构收口已补完：

- Contracts 已收敛为中立契约；Policy 已成为投资政策唯一代码来源
- Validator 已成为兼容 Facade；职责已拆为固定七阶段 Pipeline
- `portfolio-advice-v0.1`、Prompt 最终文本、动作/比例/数量/金额和 Legacy fallback 均未改变
- 账户资金仍只追加只读指标，不参与裁决
- Explainability、Evidence、Signal Ledger 尚未实现
- 全量离线唯一失败仍为 Windows 缺少 `python3` 导致 `fake 退出码 9009`

建议候选项（**勿自行开工**，需用户明确指定其一）：

1. 将账户资金及可用现金约束接入持仓建议动作与数量裁决（阶段二）——范围大，需单独设计
2. 其它产品需求

- 不自行选择或开始新的功能开发
- 下一功能启动前需确认优先级与范围
- 如无明确新需求，保持工作区干净

