# Chat 交接（可直接粘贴到新会话）

---

## 仓库与 Git

| 项 | 值 |
|----|-----|
| 仓库（origin） | https://github.com/guilaile95/Vibe-Research |
| 分支 | `feature/research-system-v01` |
| 当前 HEAD | 「feat: add manual account funding input」提交（待填精确哈希） |
| origin | `https://github.com/guilaile95/Vibe-Research.git` |
| upstream | `https://github.com/simonlin1212/Vibe-Research.git` |
| 跟踪 | `origin/feature/research-system-v01` |
| 工作区 | 文档提交前为干净；接手后请先 `git status` / `git rev-parse HEAD` 复核 |

> 说明：拼写为 **guilaile95**（非 guiliale95）。

## 协作方式

- 本地个人 AI 投研看板：**FastAPI** + **React/Vite**
- 持仓、模型 Key、复盘磁盘缓存在**用户目录 / localStorage**，不进 Git
- 业务改动优先有测试；`pytest -m "not live"`；前端 `npm run build`
- 禁止把密钥、代理订阅、真实持仓写入仓库或对话日志

## 请先阅读的文档（本仓库 `docs/`）

1. `docs/PROJECT_STATE.md` — 已完成能力与关键提交
2. `docs/ARCHITECTURE.md` — 复盘与持仓建议调用链
3. `docs/DECISIONS.md` — 设计决定
4. `docs/KNOWN_ISSUES.md` — 限制与已知测试例外
5. `docs/NEXT_TASK.md` — **当前下一任务**

## 已完成能力（摘要）

- 每日复盘结构化聚合 + **九维 AI** 分析契约
- `GET /api/daily-review`：**SWR**（内存 + 磁盘 latest + 后台 single-flight 刷新）
- normal 不被坏 partial 覆盖；刷新失败可保留旧 normal
- 全 A 快照：东财**直连**、分页、页级重试、失败不半截
- `POST /api/portfolio/advice`：fresh 复盘、breadth unavailable → **503 fail-closed**
- 固定动作与比例档位；**validator 为执行字段权威**
- add：后端计算 `execution_quantity` 与 `estimated_amount`（`5dec970`）— **已实现并完成受控端到端验收**（见 `PROJECT_STATE.md` §11）
- 前端复盘页 SWR 提示；持仓页结构化建议展示
- 账户资金手工填写：`GET`/`PUT /api/account-profile`；`account_profile.json`（独立于 `portfolio.json`）；未配置不解释为 0；Portfolio 页展示 + 弹窗编辑（本轮仅手工填写与展示，未接入持仓建议）

## 关键安全边界

- 持仓建议**禁止**使用 stale 磁盘复盘
- 不向客户端泄漏 ProxyError / 完整 URL / traceback
- 无账户总资产、可用现金、可靠可卖数量 → 限制文案 + 人工确认
- 无 K 线不得编造技术位；不做 T
- add 比例 = **相对当前持股**，不是账户仓位/资金比例

## 最近关键提交

- `8eb9225` nine-dimension daily review
- `2cf897c` persisted review while refreshing
- `cf535b8` preserve valid review on refresh failure
- `082e825` constrain portfolio advice execution rules
- `f2ae80c` stabilize A-share snapshot paging
- `5dec970` calculate executable add quantities  ← 当前功能 HEAD（文档撰写时）

## 当前下一任务

账户资金手工填写（`feat: add manual account funding input`）**已完成实现与测试**（见 `PROJECT_STATE.md` §13）。当前下一任务为**待产品优先级确认**（见 `docs/NEXT_TASK.md`）；新会话**不得重复已完成任务**，也不得自行启动新功能开发。

## 已知测试例外

```text
tests/test_fixes.py::test_run_cli_stream_timeout
```

Windows 缺少 `python3` 命令，退出码 9009。勿把新失败归入此项。

## 给新会话的强制要求

1. 先读上述 `docs/*`，并用 `git log` / 代码路径核对，**不要凭记忆扩写事实**。
2. 先 `git status`、`git rev-parse HEAD`、`git remote -v`。
3. **不要重复**已在文档与提交中标明完成的大功能，除非验收失败需修复。
4. 未经用户确认，**不扩大任务范围**、不 force push、不改无关模块。

---

我接下来会发送 Codex 的执行结果。请先审查结果与仓库事实是否一致，不要重复已经完成的任务，也不要在我确认前扩大任务范围。
