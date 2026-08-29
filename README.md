# Vibe-Research

个人投资研究与决策辅助项目。

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

![每日复盘界面](docs/screenshots/daily-review.png)

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

## 当前主要功能

- 市场环境、每日复盘、历史快照与比较；
- A 股个股数据、全球指数及美股 / 港股子集；
- 板块研究、Native Intel、公告、研报与个人研报归档；
- 自选股、持仓、账户资金与执行约束；
- Thesis、Evidence、Decision Evidence 与 Signal Ledger；
- Trade Ledger、Decision Feedback、Decision Performance 与 Performance Attribution；
- Data Health、OpenAI-compatible API、本机 CLI 与 MCP 辅助入口。

当前恢复坐标见 [`docs/CURRENT_STAGE.md`](docs/CURRENT_STAGE.md)，架构与边界见
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。实时工程状态始终以 GitHub 的稳定分支、
Issues、PR 和 CI 为准；Draft PR 或研究分支不代表稳定版本。

## 数据与隐私

本项目采用本地优先的数据边界：

- 持仓、账户资金、交易与研究记录等保存在用户目录或 `VR_DATA_DIR`；
- 个人研报默认位于用户目录，可用 `VR_REPORTS_DIR` 单独指定；
- 部分前端配置、自选数据和模型配置保存在浏览器 `localStorage`；
- 模型密钥、真实持仓和本地数据库不应提交到 Git。

“本地优先”描述的是存储与运行边界，不表示所有功能都离线。市场数据接口与所配置的
AI 服务可能产生外部网络请求；使用前应自行确认相应服务的条款和数据处理方式。

## 运行方式

稳定分支当前验证的环境为：

- Linux / Ubuntu：CPython 3.11；
- Windows：PowerShell 7 + CPython 3.12.10；
- 前端 CI：Node.js 22。

### Windows 一键启动（推荐）

先安装 PowerShell 7、Python 3.12 和 Node.js 22。之后在仓库根目录双击：

```text
Start-Vibe.cmd
```

它只通过 `pwsh.exe` 运行，会自动：

1. 创建或复用 `backend\.venv`；
2. 按 Windows exact lock 同步后端依赖；
3. 按 `package-lock.json` 同步前端依赖；
4. 启动后端和前端；
5. 等待两个服务真实就绪；
6. 自动打开 `http://127.0.0.1:5899`。

首次安装依赖会比后续启动更久。保持启动窗口开启；按 `Ctrl+C` 会停止本次启动器创建的
服务。日志和依赖指纹保存在被 Git 忽略的 `.vibe-runtime/`。

也可以显式通过 PowerShell 7 运行：

```powershell
pwsh.exe -NoLogo -NoProfile -File .\start-vibe.ps1
```

强制重新核对依赖使用 `-Setup`；不自动打开浏览器使用 `-NoBrowser`。

Native Intel 在首次或陈旧启动时会在后台刷新。应用不再等待整轮网络抓取后才开放；
刷新完成前，资讯页面会诚实显示 `unavailable / stale / partial`，不会伪装成正常空数据。

### Linux

```bash
git clone https://github.com/guilaile95/Vibe-Research.git
cd Vibe-Research/backend
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-linux-py311.lock.txt
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8900
```

### Windows PowerShell 7（手动方式）

```powershell
git clone https://github.com/guilaile95/Vibe-Research.git
Set-Location Vibe-Research\backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev-windows-py312.lock.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8900
```

Windows authority lock 同时包含运行与开发测试依赖；项目没有单独维护 Windows
runtime-only lock。平台依赖合同见
[`docs/DEPENDENCY_REPRODUCIBILITY.md`](docs/DEPENDENCY_REPRODUCIBILITY.md)。

另开终端启动前端：

```powershell
Set-Location Vibe-Research\frontend
npm.cmd ci
npm.cmd run dev
```

默认访问地址为 `http://localhost:5899`，后端为 `http://127.0.0.1:8900`。
多数数据能力依赖公开网络接口，实际可用性会受来源状态、限流与网络环境影响。

## 项目结构

```text
Vibe-Research/
├── frontend/            React 19 + TypeScript + Vite
├── backend/             FastAPI、数据适配、研究与决策相关 API
├── a-stock-data/        A 股数据工具与说明
├── global-stock-data/   全球市场数据工具与说明
└── docs/                架构、状态、治理和研究记录
```

系统逻辑上，公开市场数据先经过适配与健康检查，再进入研究、证据、决策和反馈记录。
完整调用链以 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 为准。

## AI 配置

AI 功能是可选的。稳定版本包含：

- OpenAI-compatible API 配置；
- 调用本机已安装 CLI 的运行路径；
- `backend/mcp_server.py` 提供的 MCP 数据工具入口。

具体模型、CLI 和外部端点由使用者自行配置。模型密钥不应写入仓库；相关运行说明见
[`backend/README.md`](backend/README.md)。

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
