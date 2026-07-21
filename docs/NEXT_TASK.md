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

~~完善持仓手工维护：精确编辑 PUT、编辑窗口、删除确认、数量校验、失败可见。~~

- **状态**：已完成（见 `PROJECT_STATE.md` §15）
- 后端：`PUT /api/portfolio/holding` → `portfolio.update_holding`（精确替换，不加权，不存在 404）
- 前端：编辑弹窗、删除确认（代码/名称/数量 + 说明）、`validateShares` 拒绝静默转换
- 隔离：不动 `account_profile`；不自动 `POST /api/portfolio/advice`；DELETE 不写 closed
- 测试：`tests/test_portfolio_edit_api.py` 23 passed；全量离线 667 passed（仅已知 Windows 例外）
- 浏览器验收 A–J：**53/53** 通过；真实用户数据 SHA256 验收前后一致
- 未接入：账户资金 → 持仓建议；未改 advice / daily_review / astock

## 当前下一任务

**待产品优先级确认**。

建议候选项（**勿自行开工**，需用户明确指定其一）：

1. 将账户资金接入持仓建议（context / prompt / validator / add 金额约束）——范围大，需单独设计
2. 其它产品需求

- 不自行选择或开始新的功能开发
- 下一功能启动前需确认优先级与范围
- 如无明确新需求，保持工作区干净
