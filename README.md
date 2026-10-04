# Vibe-Research

本地优先的个人投资研究与决策工作台：看市场、整理证据、记录判断、跟踪复盘。

[![CI](https://github.com/guilaile95/Vibe-Research/actions/workflows/ci.yml/badge.svg?branch=feature%2Fresearch-system-v01)](https://github.com/guilaile95/Vibe-Research/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> [!NOTE]
> 本仓库基于 [simonlin1212/Vibe-Research](https://github.com/simonlin1212/Vibe-Research)
> fork / 派生后继续开发。
>
> 原始项目、原始设计与初始实现请优先参阅上游仓库。当前 GitHub 仓库元数据
> 未保留 fork network 关联；本仓库主要用于个人持续开发、研究和实验。

Vibe-Research 整合公开市场数据、研究记录、持仓与账户信息、决策记录及可选的
AI 辅助能力。它不是自动交易、荐股或收益预测系统；最终判断与执行由使用者负责。

[开始运行](docs/GETTING_STARTED.md) · [文档导航](docs/README.md) · [进度与验证范围](docs/research/PROJECT_STATUS_20261002.md) · [已知限制](docs/KNOWN_ISSUES.md)

![每日复盘界面](docs/screenshots/daily-review.png)

*界面示例；截图不代表当前行情、完整功能验收或最新设计原型已落地。*

## 关于本仓库

当前稳定实现围绕以下流程组织信息：

```text
市场与数据
    ↓
研究、Thesis 与 Evidence
    ↓
信号和决策记录
    ↓
持仓、交易与执行约束
    ↓
结果、反馈与收益归因
```

AI 位于研究与决策工作流中，用于整理上下文和辅助推理，不替代事实核验，也不替代
个人决策。Data provides facts; evidence supports or weakens a thesis; AI organizes
reasoning; the user owns the final decision.

## 能做什么，如何判断是否适用

| 研究任务 | 已有入口 | 使用边界 |
| --- | --- | --- |
| 看市场与找线索 | 每日复盘、市场/板块、Discovery、Native Intel、自选 | 公开来源可能延迟、缺失或限流；先看时间和来源 |
| 研究一个对象 | 个股数据、候选研究、Evidence、Thesis、个人研报 | 摘录和引用帮助回查，不保证覆盖全文或后文更正 |
| 留下决策依据 | Campaign、确定性 Preview、Frozen Decision | 正式决定由用户明确确认，AI 输出只是草稿 |
| 跟踪执行与复盘 | 持仓、账户、手工交易归属、Outcome 与反馈 | 无券商或自动交易；账户事实需要用户维护 |
| 辅助整理材料 | 可选 API、Codex 订阅 Runtime、本机 CLI | 真实答案质量与成本需单独评估，配置成功不等于质量通过 |

研究留痕和决策边界是现有基础；行情可靠性、真实模型研究质量与长期使用价值仍待验收。
工程测试不代替真实行情、真实模型或用户自然任务观察。

## 版本与当前进度

公开稳定线为 [`feature/research-system-v01`](https://github.com/guilaile95/Vibe-Research/tree/feature/research-system-v01)。
截至 2026-10-02，可靠性与研究修复 #356–#360 仍为 Draft、未合并；本地组合源码已集成，运行服务未切换。
全功能矩阵正在补测，17 个离线 AI 案例已有准备，真实模型调用仍为 0（`NOT_EVALUATED`）；多页设计仍是原型。

后续公共修复、整合依赖与验收缺口见 [2026-10-04 公共集成记录](docs/research/PUBLIC_INTEGRATION_20261004.md)；[2026-10-02 状态快照](docs/research/PROJECT_STATUS_20261002.md)保留其历史身份。
接管任务读 [恢复坐标](docs/CURRENT_STAGE.md)；实时工程事实以 GitHub 分支、PR 和检查结果为准。

## 数据与隐私

本项目采用本地优先的数据边界：

- 持仓、账户资金、交易与研究记录等保存在用户目录或 `VR_DATA_DIR`；
- 个人研报默认位于用户目录，可用 `VR_REPORTS_DIR` 单独指定；
- 部分前端配置、自选数据和模型配置保存在浏览器 `localStorage`；
- 模型密钥、真实持仓和本地数据库不应提交到 Git。

“本地优先”描述的是存储与运行边界，不表示所有功能都离线。市场数据接口与所配置的
AI 服务可能产生外部网络请求；使用前应自行确认相应服务的条款和数据处理方式。

## 开始运行

Windows 需要 PowerShell 7、Python 3.12 和 Node.js 22.6+；新安装从稳定分支获取源码：

```powershell
git clone --branch feature/research-system-v01 --single-branch https://github.com/guilaile95/Vibe-Research.git
Set-Location Vibe-Research
pwsh.exe -NoLogo -NoProfile -File .\start-vibe.ps1
```

也可在仓库根目录双击 `Start-Vibe.cmd`。启动器安装或复用依赖，检查后端、Agent Runtime 与前端，打开 `http://127.0.0.1:5899`。
已有工作区先保留自己的编辑并核对版本。完整的 [Windows / Linux 手动运行、健康检查与 AI 配置](docs/GETTING_STARTED.md) 集中在运行指南；不要把源码更新视为服务已切换。

## 项目结构

```text
Vibe-Research/
├── frontend/            React 19 + TypeScript + Vite
├── backend/             FastAPI、数据适配、研究与决策相关 API
├── agent-runtime/       Codex 订阅 page-aware chat 运行时（Node，:8911）
├── a-stock-data/        A 股数据工具与说明
├── global-stock-data/   全球市场数据工具与说明
└── docs/                架构、状态、治理和研究记录
```

系统逻辑上，公开市场数据先经过适配与健康检查，再进入研究、证据、决策和反馈记录。
完整调用链以 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 为准。

## AI 配置

AI 功能是可选的。稳定版本包含：

- OpenAI-compatible API 配置；
- Codex 订阅接入：本机 Agent Runtime（`agent-runtime/` + `backend/agent_runtime.py`，:8911）
  提供的 page-aware Ask AI；
- MyReports 全文索引、摘录检索与提问，提供来源与页码引用入口；引用不等于全文结论已核实；
- 调用本机已安装 CLI 的运行路径；
- `backend/mcp_server.py` 提供的 MCP 数据工具入口。

Agent Runtime 的真实边界：它是页面上下文内的文本生成器（page-aware Ask AI），
不是 autonomous research / shell / web / MCP / formal decision agent——无 shell、无 web、
无本地磁盘直接访问、不接 Vibe MCP 工具、无插件与外部技能、无多智能体、不写 Formal authority；
输出一律为 `NON_AUTHORITATIVE_AI_DRAFT`。

具体模型、CLI 和外部端点由使用者自行配置。模型密钥不应写入仓库；配置与运行说明见
[运行指南](docs/GETTING_STARTED.md)，接口参考见 [后端说明](backend/README.md)。

## 项目状态

本仓库持续开发中，部分研究和实验分支不会进入稳定版本。恢复、已知限制和治理入口为：

- [`docs/CURRENT_STAGE.md`](docs/CURRENT_STAGE.md) — 当前恢复坐标；
- [`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md) — 已知限制；
- [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md) — 仓库治理；
- [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) — 历史快照提示，不是当前状态权威。

## 免责声明

本项目用于投资研究、数据整理和决策辅助，不构成投资建议、证券推荐或收益承诺。

## License & Attribution

本仓库基于
[simonlin1212/Vibe-Research](https://github.com/simonlin1212/Vibe-Research)
继续开发。原项目及相关代码版权声明按照仓库中的 MIT License 保留；本仓库同样按照
[MIT License](LICENSE) 发布。`LICENSE` 中的
`Copyright (c) 2026 simonlin1212` 保持不变。
