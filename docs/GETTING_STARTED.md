# 安装与运行

本指南对应公开稳定分支 `feature/research-system-v01`。Draft PR、本地集成源码与已启动服务可能处于不同版本，先确认自己要运行的版本。当前工程状态通过 [文档导航](README.md) 的 GitHub 入口核验；带日期的状态快照仅说明当时的证据。

## 环境与首次获取

| 部分 | 项目使用的环境 |
| --- | --- |
| Windows | PowerShell 7、CPython 3.12（authority lock 在 3.12.10 验证） |
| Linux | CPython 3.11，使用 Linux 专用 lock |
| 前端与 Agent Runtime | Node.js 22.6+；CI 使用 Node.js 22 |
| 获取源码 | Git；首次安装依赖需要网络 |

新安装执行：

```bash
git clone --branch feature/research-system-v01 --single-branch https://github.com/guilaile95/Vibe-Research.git
cd Vibe-Research
git branch --show-current
git rev-parse HEAD
```

已有工作区先查看 `git status --short`。保留自己的修改和本地数据，不用重置、清理或复制旧目录覆盖的方式“更新版本”。依赖选择见 [平台合同](DEPENDENCY_REPRODUCIBILITY.md)。

## Windows：一键启动

在仓库根目录双击 `Start-Vibe.cmd`，或运行：

```powershell
pwsh.exe -NoLogo -NoProfile -File .\start-vibe.ps1
```

启动器会创建或复用 `backend\.venv`，按 Windows lock 同步后端依赖，按两个 `package-lock.json` 同步前端和 Agent Runtime 依赖，然后检查并启动所需服务，打开 `http://127.0.0.1:5899`。

- `-Setup`：强制重新核对依赖。
- `-NoBrowser`：保持服务启动，但不自动打开浏览器。
- 保持启动窗口开启；按 `Ctrl+C` 停止本次启动器创建的服务。
- 日志及依赖指纹在被 Git 忽略的 `.vibe-runtime/`。首次安装通常较慢。

启动器可复用已响应的服务，所以启动成功不能单独证明服务正在运行刚更新的源码。可在应用设置的本机运行信息中核对版本；本指南本身不执行服务切换。

## 手动启动：每个服务各开一个终端

以下每个代码块都从**仓库根目录**开始。基础网页使用后端和前端；Codex 订阅 Ask AI 还需要 Agent Runtime。

### Linux

终端 1，后端：

```bash
cd backend
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-linux-py311.lock.txt
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8900
```

终端 2，前端：

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

终端 3，Codex 订阅 Ask AI 所需的 Runtime：

```bash
cd agent-runtime
npm ci
npm start
```

### Windows PowerShell 7

终端 1，后端：

```powershell
Set-Location backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev-windows-py312.lock.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8900
```

Windows 当前只维护 runtime + dev 合并 lock，没有单独的 runtime-only lock。

终端 2，前端：

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1
```

终端 3，Codex 订阅 Ask AI 所需的 Runtime：

```powershell
Set-Location agent-runtime
npm.cmd ci
npm.cmd start
```

Linux 用户目录打包、独立安装与前台生命周期管理见 [Linux 安装包指南](LINUX_INSTALL.md)。它与上述源码手动启动是不同路径，不代表云端部署已经验收。

## 检查启动结果

| 服务 | 本机地址 | 能证明什么 |
| --- | --- | --- |
| 网页 | `http://127.0.0.1:5899` | 前端可访问 |
| 后端健康 | `http://127.0.0.1:8900/api/health` | 后端进程可响应 |
| Agent Runtime 健康 | `http://127.0.0.1:8911/health` | Runtime 进程可响应；不代表已登录或真实模型可用 |

首次打开先看每日复盘和数据健康。Native Intel 可在后台刷新，完成前可能显示 `unavailable / stale / partial`。行情有内容、时间可核验、最新刷新成功是不同状态；服务健康不能代替来源可用性。

## 可选 AI 与个人数据

- OpenAI-compatible API：在应用模型配置中选择自己的端点、模型与凭据。示例提供方不是默认采用或质量认证。手动「测试当前配置」可能产生费用，且与保存独立；范围、限额和取消语义见 [AI 连接检测](AI_CONNECTION_TEST.md)。
- Codex 订阅：按应用登录入口完成用户登录，再检查 Runtime 状态。Runtime 只生成页面上下文内的草稿，不执行 shell、网页研究、交易或正式决策写入。
- 本机 CLI 是另一条接入路径，需已有相应工具与认证。外部模型可能计费；验证前明确提供方、模型、调用次数/预算与可发送的材料。
- 缺凭据时应说明缺口并向用户询问安全配置方式；不能把离线 fixture 的结果记成真实模型通过，也不应把密钥贴入公开 Issue、PR 或文档。

持仓、账户、交易和研究资料保存在用户目录或 `VR_DATA_DIR`；个人研报可由 `VR_REPORTS_DIR` 指定；部分浏览器设置在 `localStorage`。本地存储不等于全离线，市场请求和所配置的模型请求会访问外部服务。

## 常见问题

| 现象 | 先核对 |
| --- | --- |
| `pwsh.exe` 不存在 | 使用 PowerShell 7；系统自带 Windows PowerShell 5.1 不符合启动器要求 |
| 端口已占用或页面版本较旧 | 当前端口由哪个进程提供、设置页显示哪个源码目录/版本；不要直接结束未知进程 |
| 网页能打开但数据不可用 | 后端健康、数据来源状态、行情时间与刷新错误；不要把空、零、错误混为一类 |
| Ask AI 不可用 | Runtime 健康与认证、模型配置、网络/额度分别检查 |
| 更新源码后仍见旧界面 | 核对实际运行版本；源码提交、前端产物和已运行进程可能不同 |

开发验证命令与证据边界见 [测试指南](TESTING.md)，长期限制见 [KNOWN_ISSUES](KNOWN_ISSUES.md)。运行指南不是安装、服务切换或功能验收回执。
