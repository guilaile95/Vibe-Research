# 已知问题与限制

## 性能与网络

| 项 | 说明 |
|----|------|
| 全 A 冷抓耗时 | 约 **80–110 秒**（环境与网络相关）；热缓存命中则远短于冷路径 |
| RemoteDisconnected | 东财分页仍可能偶发；`_em_get_page_with_retries` 做**页级重试**，不应整表从第 1 页重跑 |
| ProxyError | 代码层固定直连后应显著减少；若本机代理劫持仍异常，需检查环境 |
| 模型耗时 | CLI/API 调用波动大（数十秒至数分钟），与供应商与负载有关 |

## 产品与数据能力缺口

| 项 | 说明 |
|----|------|
| 账户总资产 / 可用现金 | 可手工维护（`account_profile`）；已接入 P2-3 可用现金安全垫约束（`apply_available_cash_constraints`，未配置/损坏时 limitation 降级）；add 数量以持股比例为基础，再受现金与整手约束 |
| 可靠可卖数量 | 未接入；reduce/sell 数量为理论值，执行前需人工确认 |
| 完整历史 K 线 / 技术指标 | 技术指标模块已上线（PR #41，展示层）；持仓建议上下文仍显式 `technical_indicators_available=false`，禁止编造技术位 |
| 可靠公告 / 新闻 / 机构催化链 | 持仓建议第一版不依赖，禁止编造催化 |
| estimated_amount | 静态估算：数量 × 现价；**不含**手续费、滑点、成交偏差 |
| 真实模型动作 | 模型可能返回 hold/reduce 等，**不一定**给 add；add 行为以确定性单测与受控 fixture 验收为主 |

## 架构限制

| 项 | 说明 |
|----|------|
| 内存缓存不跨进程 | 多 uvicorn worker 或重启后各自缓存；磁盘 latest 可跨重启展示 |
| SQLite 历史 vs 运行时缓存 | 两套机制；勿假设 GET 复盘会自动写历史库 |

## 已知测试例外（Windows）

```text
tests/test_fixes.py::test_run_cli_stream_timeout
```

- **现象**：断言期望超时类文案，实际可能得到与 `python3` 命令相关的失败信息。
- **原因**：Windows 环境常缺少 `python3` 可执行名，子进程退出码 **9009**（命令未找到）。
- **处理**：视为环境已知问题；**不得**把其它失败归入此项。

其余 `pytest -m "not live"` 应以当前分支绿测为准；测试数量以 CI 与本地实测为准（2026-08-06 稳定 head CI 全绿），不在本文档维护具体数字。

## 持仓维护 UX 注意

| 项 | 说明 |
|----|------|
| POST vs PUT | 同代码 POST=加权加仓；精确改数/改成本必须用 PUT 编辑，不可当 upsert |
| 数量零股 | PUT 允许非 100 股整数倍；不强制整手 |
| 删除 vs 清仓 | 删除只去 holdings；清仓走独立 close API 写 closed |

## 安全与隐私（运行时，不进仓）

以下位于用户目录或本机配置，**不应提交到 Git**：

- `~/.vibe-research/portfolio.json`、`daily_review_latest.json`、`account_profile.json`
- SQLite 历史库
- 前端 localStorage 中的 API Key / 模型配置
- 本机 Clash/代理订阅与密码

## 已接受的非阻断问题（P2）

| 项 | 说明 |
|----|------|
| Intel Digest saving 请求无显式 timeout | 后端进程挂起时 UI 可能停留在"保存中"；不导致数据库数据损坏；reload 可恢复；当前 P2；后续候选修复，不是当前授权任务 |
| thesis E2E 偶发失败（intermittent） | 2026-08-07 首次 stable merge run（run `31200057732`）失败于 "Updated evidence text not visible"（UI 更新可见性时序断言，`evidence-thesis-real.browser.mjs:255`）；**同一 exact Head 复跑成功**（CONFIRMED_INTERMITTENT_E2E_FAILURE）；不代表 thesis 产品功能故障；当前 P2；后续稳定性加固候选，本轮不修 |
