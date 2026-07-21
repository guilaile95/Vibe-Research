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
- 账户资金：**仍未接入**持仓建议
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

## 当前下一任务

**待产品优先级确认**。

建议候选项（**勿自行开工**，需用户明确指定其一）：

1. 将账户资金及可用现金约束接入持仓建议动作与数量裁决（阶段二）——范围大，需单独设计
2. 其它产品需求

- 不自行选择或开始新的功能开发
- 下一功能启动前需确认优先级与范围
- 如无明确新需求，保持工作区干净
