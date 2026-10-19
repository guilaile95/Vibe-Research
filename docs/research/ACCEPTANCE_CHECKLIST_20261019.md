# 2026-10-19 有界验收清单

此清单区分离线工程证据与待授权的真实使用证据，不代表发布、部署或 Product Reality Day 1 已开始。
运行入口与结果状态见 [测试指南](../TESTING.md)。每次验收记录 exact commit、命令、环境、退出码和实际范围；旧结果不自动覆盖新源码。

## 离线工程门

- [ ] 离线 runner 的六个门分别取得结果，并检查 JSON 报告；失败或阻断不写成通过
- [ ] 前端完整单元测试与构建；明确 Node 版本，Linux 本地结果不替代 Windows / Node 22 CI
- [ ] 保存的研究历史只读展示原有记录、bundle 和引用；损坏与缺失输入失败关闭
- [ ] 合成流程在后端完全重启后仍可读取保存结果；浏览器存储与合成次日流程分别验证
- [ ] 独立审查当前差异，记录剩余缺陷；不把 mock、回环本地路由写成真实来源或真实模型验收

## 真实数据：四类案例均为 NOT_EVALUATED

1. A 股：核对证券身份、来源、时间与缺失字段
2. 港股：核对市场身份、币种、交易日和来源边界
3. 美股：核对市场身份、币种、时区和来源边界
4. 故意不可用来源 / 无效证券身份：确认明确失败或 UNKNOWN，且身份无效时在外部请求前截断

每类保存脱敏输入、观察时间、来源和预期/实际结果；不得用合成数据补记真实通过。

## 真实 AI：三个案例均为 NOT_EVALUATED

开始前确认真实目的地、模型、材料范围和金额预算，不记录密钥值。
以下是当前源码的请求与输出上限，不是金额承诺，也不是端到端统一耗时承诺：

| 案例 | 有界范围 | 源码依据 |
| --- | --- | --- |
| 单公司研究 | 最多 6 次请求；每次 90 秒、2500 requested output tokens、16000 UTF-8 输出字节；没有六阶段共享的总计 90 秒限制 | [company_research.py](../../backend/company_research.py)，`generate` 的逐阶段调用与输出长度检查 |
| 公司对比 | 1 次请求；模型阶段共享 90 秒、2500 requested output tokens、16000 UTF-8 输出字节；关闭清理另外受 0.5 秒限制且成功清理仍在共享期限内 | [company_comparison.py](../../backend/company_comparison.py)，`MODEL_SECONDS` / `MAX_OUTPUT_TOKENS` / `CLEANUP_SECONDS` 与模型循环 |
| 每日复盘 | 最多 1 次 dispatch；模型阶段 90 秒、2500 requested output tokens、12000 输出字符；上下文准备位于预算启动之前 | [chat.py](../../backend/chat.py) 的 `daily_review_task_budget` 与 [app.py](../../backend/app.py) 的流生成器 |

三个案例合计最多 8 次请求 / 20000 requested output tokens。输入 tokens、供应商计价及实际费用另行确认；这不是 monetary cap。逐案核对引用、身份、失败/取消行为、草稿边界和人工质量判断；模型连通不等于研究质量通过。

## 恢复与交付

复用 [本地备份与恢复](../LOCAL_BACKUP_AND_RECOVERY.md) 的静默备份、校验与恢复步骤；浏览器研究记录需要单独备份，凭据不进包。
运行与安装交付复用 [运行指南](../GETTING_STARTED.md) 和 [Linux 安装包指南](../LINUX_INSTALL.md)，不另建发布流程。
源码通过、稳定分支合并、运行服务切换与自然使用观察分别记录，未执行项保持 NOT_EVALUATED。
