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

## 环境配置与 Runtime 端口

[后端配置示例](../backend/.env.example) 是说明，不是自动加载的配置文件。
在启动器或手动服务的父终端中设置环境变量；不要把真实 key 填进仓库示例。

Windows 启动器和 Linux 安装包启动器默认使用 Runtime `8911`。覆盖规则：

- 仅设 `VR_AGENT_RUNTIME_PORT`，或仅设带端口的 `VR_AGENT_RUNTIME_URL`；同时设置时必须一致
- 端口为 ASCII 十进制整数 `1024–65535`，排除后端 `8900` 和前端 `5899`
- URL 仅允许 `http`、`127.0.0.1` / `localhost` / `[::1]`、显式端口及可选末尾 `/`；不允许凭据、其他路径、query 或 fragment
- 启动器将结果统一为 `http://127.0.0.1:<port>`，同时传给后端与 Runtime；这不会开放远程监听

例如，在运行 Windows 启动器前设置 `$env:VR_AGENT_RUNTIME_PORT = "8912"`，
或在运行 Linux 安装包启动器前设置 `export VR_AGENT_RUNTIME_PORT=8912`。
这条自动同步规则不适用于上面的手动分终端命令：手动启动时，后端终端应设置
`VR_AGENT_RUNTIME_URL=http://127.0.0.1:8912`，Runtime 终端设置 `VR_AGENT_RUNTIME_PORT=8912`。
如需让脱敏报告核对声明值，后端终端也设置相同的 `VR_AGENT_RUNTIME_PORT`。
健康检查地址随端口调整。已有服务被复用时，仍需核对其实际版本与启动配置。

供应商配置与运行状态分开判断：

| 可选配置 | 实际边界 |
| --- | --- |
| `HITHINK_FINANCE_API_KEY` | 已有限定行情等客户端；认证、逐接口权限、证券范围和响应质量分别验证 |
| `TUSHARE_TOKEN` | 已有受限接口客户端与显式 ingestion；不会自动启用短线研究 transport 或定时采集 |
| `VR_SEC_CONTACT` | 本地英文姓名/邮箱设置，环境管理时页面只读；不是凭据，当前未接通 SEC transport |

不配置这些项不等于所有公开来源不可用；配置成功也不等于已经获得数据。
历史 `IWENCAI_API_KEY` / `IWENCAI_BASE_URL` / `VR_DATA_PROXY` 没有当前后端生产读取入口。
采用范围及待接通事项见 [选择性吸收证据索引](VIBE_ASTOCK_ADOPTION_PLAN.md)。

## 隔离启动准备：独立存储与暂停自动抓取

**只更换 `VR_DATA_DIR` / `VR_REPORTS_DIR` 不能隔离全部存储。** 复盘、短线历史及部分驾驶舱数据共用
`VIBE_RESEARCH_REVIEW_DB`：未显式设置时，Linux 使用 `$XDG_DATA_HOME/vibe-research/daily_reviews.sqlite3`
（未设置 XDG 时为 `~/.local/share/vibe-research/daily_reviews.sqlite3`），Windows 使用
`%LOCALAPPDATA%\VibeResearch\daily_reviews.sqlite3`（未设置时回退到用户目录的 `AppData/Local`）。
此默认位置不随 `VR_DATA_DIR` 改变。本步骤不修改默认路径、不迁移已有安装或复制真实历史数据。

从仓库根目录，用已安装项目依赖的 Python 先做不打开数据库、不导入应用、不联网的路径预检：

```bash
# Linux
backend/.venv/bin/python tools/acceptance/offline_acceptance.py --check-isolation
```

```powershell
# Windows / PowerShell 7：同一纯路径预检，不运行 Linux namespace 验收
backend\.venv\Scripts\python.exe tools/acceptance/offline_acceptance.py --check-isolation
```

该命令创建并清理一套临时环境，只返回脱敏的路径检查状态。`pass` 仅证明这套临时环境的路径解析，
不会修改当前终端，也不能替之后另开的普通启动终端背书。完整离线验收入口仍为
`tools/acceptance/offline_acceptance.py`（不带 `--check-isolation`）；没有 Linux user/network/PID namespaces 时必须停止，不静默降级。

定制验收复用 `tools/acceptance/offline_acceptance.py` 的 `isolated_env(root)`，不要复制 `os.environ`。
每个实例必须使用不同的全新临时根目录；该函数不继承原有凭据、代理、Python hooks 或数据库覆盖变量，并设置：

- `HOME` / `USERPROFILE`、XDG config/cache/data/state、`APPDATA` / `LOCALAPPDATA` 和临时目录；
- 独立的 `VR_DATA_DIR`、`VR_REPORTS_DIR`、**`VIBE_RESEARCH_REVIEW_DB`**；
- 独立的 `VR_FACT_LAKE_ROOT`、`VIBE_RESEARCH_RESEARCH_DATA_DIR`；
- `VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH=1` 与 `VIBE_NATIVE_INTEL_DISABLE_SCHEDULER=1`。

在同一环境启动任何可能写数据的子进程前，调用 `verify_isolated_env(root, env, repository)` 并要求
`status == "pass"`。它检查必需路径均在本实例根目录内，并调用生产代码的无副作用复盘DB与研究数据根解析器；
缺少显式复盘DB路径、路径越界或自动抓取开关未关闭时失败关闭。现有离线验收入口已在每个 gate 前执行此检查。
可复用方式（仍须为实际测试命令使用已有 namespace 包装，不要直接启动真实服务）：

```python
with tempfile.TemporaryDirectory(prefix="vibe-test-") as directory:
    root = Path(directory)
    env = isolated_env(root)
    checked = verify_isolated_env(root, env, repository=repository)
    if checked["status"] != "pass":
        raise RuntimeError("storage isolation not verified")
    result = run_owned(namespace_command(command), cwd=repository, env=env, timeout=120)
```

路径预检不是文件系统沙箱，也不检查任意第三方测试代码。它还只检查文件元数据：若存在旧版
`backend/.cache/portfolio.json`、`backend/.cache/myreports`，或 `.cache` 本身是符号链接，则在运行 gate 前停止，
不读取私有内容、不自动删除、复制或迁移。出现 `LEGACY_PRIVATE_INPUT_PRESENT` 时，优先选择不含这些数据的干净源码工作区；
若要继续使用原工作区，由用户自行确认备份与移出旧数据，工具不会自动清理。不要把真实持仓、账户、研报或 SQLite 文件作为测试输入。
需要复制数据库时须采用一致性备份，不能有 WAL 时只复制主文件。

两个 Native Intel 开关分别阻止启动抓取和定时抓取；只设一个不等于暂停全部自动抓取。
它们不是全局断网开关：行情页面、手动刷新、公开来源采集或模型操作仍可能外联。
普通后端启动也不是只读操作：本地服务可能初始化或恢复存储，持仓后台线程每 1,800 秒写入刷新时间戳，
上述开关不禁用该线程。严格离线测试须另用网络隔离；带真实生命周期的测试也须替换外部服务边界。
禁止让不同版本同时使用同一数据目录，不把路径检查、健康检查或合成验收记为真实用户使用记录。

## 手动归档一份公开 A 股报价

`backend/public_research_capture.py` 是独立命令，不挂接应用启动、页面 GET、定时任务或模型。
当前仅开放 `cn_quote_ref`：一只 A 股与上证基准来自同一次腾讯公开报价响应。
先选择独立、已显式初始化的 FactLake 绝对路径；命令不会创建归档，也不会从默认用户目录选择目标。

在后端依赖环境中，从 `backend/` 运行下列命令只查看计划，不读写归档或联网：

```sh
python -m public_research_capture --source cn_quote_ref --subject A:600000@YYYY-MM-DD --archive-root /absolute/isolated/fact-lake
```

将日期替换为实际研究截止日，检查来源、目标目录与预算后，显式追加 `--execute` 才会执行一次公开 GET，
保存原始响应及哈希，并通过已有归档读取器复验。当前报价不能回填为历史当时可得数据；
响应晚于截止日、缺字段或解析失败会保留其不可用/部分状态，不伪装为完整行情。
源服务条款与可用性仍需实际核对，不绕过访问限制、验证码或认证要求。

传输只使用由既有来源合同生成的固定 HTTPS 地址，拒绝重定向和压缩响应，不读取模型配置、
凭据、浏览器 Cookie 或环境代理；无自动重试。原始响应上限 2 MiB；每个 socket 阶段超时 5 秒，
在响应头和每个原始流块之间检查 20 秒已用时间预算，因此已开始的阻塞读取可再占用至多一个 socket 超时。
命令不会调用模型或写正式交易/决策；它会向选定归档写研究观测，因此不是只读操作。
HTTP 错误或无效原文可保留为不可用观测；传输拒绝/超限失败不伪造成功回执。

现有网页使用同一 `VR_FACT_LAKE_ROOT` 后可读取已归档观测，但本命令不会启动网页、切换运行服务或启用其他数据族。
严格离线测试使用注入的模拟 HTTP 响应及临时归档，不等于真实来源已验收。

## 检查启动结果

| 服务 | 本机地址 | 能证明什么 |
| --- | --- | --- |
| 网页 | `http://127.0.0.1:5899` | 前端可访问 |
| 后端健康 | `http://127.0.0.1:8900/api/health` | 后端进程可响应 |
| Agent Runtime 健康 | `http://127.0.0.1:8911/health` | Runtime 进程可响应；不代表已登录或真实模型可用 |

需要排查时，在设置 → 本机后端运行信息导出 [脱敏运行自检](RUNTIME_DIAGNOSTICS.md)。
此动作只读元数据，不测试网络、模型或登录；`NOT_EVALUATED` 不能解释为成功或失败。

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
| Ask AI 不可用 | 先看脱敏自检的 Runtime URL/端口声明；配置一致仍需分别验证实际服务、认证、模型与网络/额度 |
| 已填供应商 key 仍无数据 | 配置名存在不证明 key 有效；检查对应接口权限、来源日期/覆盖和失败状态，勿通过粘贴密钥排障 |
| 更新源码后仍见旧界面 | 核对实际运行版本；源码提交、前端产物和已运行进程可能不同 |

开发验证命令与证据边界见 [测试指南](TESTING.md)，长期限制见 [KNOWN_ISSUES](KNOWN_ISSUES.md)。运行指南不是安装、服务切换或功能验收回执。
