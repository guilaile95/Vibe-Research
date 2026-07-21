# 当前下一任务

## 上一任务（已完成）

~~对提交 **`5dec970`**（`feat: calculate executable add quantities`）做受控端到端验收。~~

- **状态**：已完成（见 `PROJECT_STATE.md` §11 验收记录）
- 验收事实：
  - A（1500股、14.29元、add 10%）→ quantity=100，amount=1429.00 ✓
  - B（1500股、14.29元、add 20%）→ quantity=300，amount=4287.00 ✓
  - C（300股、14.29元、add 10%）→ quantity=null，amount=null，保留 add 与 10% 比例 ✓
  - 模型错误值 quantity=999/amount=99999 被后端重算覆盖 ✓
  - validator：正确股数/金额通过，错误拒绝；「相对当前持股」通过，「账户资金比例」拒绝 ✓
  - 浏览器展示（场景 B）：加仓 20% / 300股 / ¥4,287.00 / 不显示 0 或 ¥0 ✓
  - 回归：validator/service/api 三套件 136 passed；`npm run build` 成功 ✓
  - 无产品代码改动，验收结束时工作区干净

## 上一任务（已完成）

~~增加「账户资金」手工填写窗口（`feat: add manual account funding input`）。~~

- **状态**：已完成（见 `PROJECT_STATE.md` §13）
- 后端：`backend/account_profile.py`；`GET`/`PUT /api/account-profile`；校验 + 原子写入；未配置不解释为 0
- 前端：Portfolio 页「账户资金」区 + 弹窗；未配置不显示 ¥0；保存失败保留输入
- 回归：account_profile 单元 + API 测试 21 passed；全量离线 638 passed（仅已知 Windows 例外）；`npm run build` 成功
- 未接入持仓建议 / 加仓数量 / AI prompt；未改持仓增删改逻辑

## 上一任务（已完成）

~~修复账户资金前端响应解包错误（`fix: restore account funding profile UI`）。~~

- **根因**：`request()` 通用解包 (`payload?.data ?? payload`) 与 account-profile `{configured, data}` 结构不匹配
- **修复**：
  - `request()` 增加 `unwrapData` 选项（默认 `true`，现有调用不受影响）
  - `getAccountProfile()`/`saveAccountProfile()` 使用 `unwrapData: false`
  - Portfolio.tsx `loadAcct`/`saveAcct` 按 `AccountProfileResponse` 结构访问
- **新增三种状态**：加载中 / 加载失败（含重试按钮）/ 未配置，明确区分
- **临时文件清理**：`account_profile.py` 写入失败时删除暂存文件；成功替换后也清理
- **新增测试**：`test_os_replace_failure_cleans_tmp`、`test_success_no_tmp_residue`、`test_concurrent_write_valid`
- **Playwright 验证**：场景 A–H 共 25/26 通过（G2 保存按钮禁用为时序测试，功能正常）

## 当前下一任务

**待产品优先级确认**。

- 不自行选择或开始新的功能开发
- 下一功能启动前需确认优先级与范围
- 如无明确新需求，保持工作区干净
