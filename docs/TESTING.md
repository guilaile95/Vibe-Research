# 本地验证与证据边界

命令以当前检出的源码为准，不把 Draft 或本地组合结果写成稳定版验收。
先读根 [AGENTS.md](../AGENTS.md)，记录 `git rev-parse HEAD` 和
`git status --short`，确认没有把用户修改、真实数据或密钥带入测试。
环境与安装见 [运行指南](GETTING_STARTED.md)，平台 lock 见
[依赖合同](DEPENDENCY_REPRODUCIBILITY.md)。

## 基础检查

前端（从仓库根目录开始，Node.js 22.6+）：

```sh
cd frontend
npm ci
npm run build
npm test
```

`build` 包含 TypeScript 检查与 Vite 构建；`npm test` 是 Node 单元测试，
不是浏览器测试。项目没有统一的 `npm run lint` 或根目录 `npm test` 入口。

Agent Runtime（另一个终端，从仓库根目录开始）：

```sh
cd agent-runtime
npm ci
npm test
```

这不需要先启动生产 Runtime，也不证明 Codex 已登录或真实模型回答质量通过。

Linux 后端（从仓库根目录开始，使用开发 lock）：

```sh
cd backend
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev-linux-py311.lock.txt
TEST_ROOT=$(mktemp -d)
VR_DATA_DIR="$TEST_ROOT/data" \
VR_REPORTS_DIR="$TEST_ROOT/reports" \
VIBE_RESEARCH_REVIEW_DB="$TEST_ROOT/review.db" \
  .venv/bin/python -m pytest -m "not live"
```

上面的数据目录是新的测试目录；不要换成真实 `VR_DATA_DIR`、研报目录或数据库。
测试结束后先检查输出再按需清理自己的临时目录，勿清理未知目录。
Windows 使用 Python 3.12 与 `requirements-dev-windows-py312.lock.txt`，
为同样三个环境变量指定新的临时路径，再用虚拟环境 Python 执行
`-m pytest -m "not live"`。Linux 通过不能代替 Windows 文件名/依赖合同验证。

## 浏览器验证

已有脚本集中在 [frontend/package.json](../frontend/package.json) 的
`test:e2e:*` 项。先构建前端；测试一般读取 `frontend/dist`，旧构建可能测到旧界面。
安装与当前 lock 匹配的浏览器：

```sh
cd frontend
npx playwright install chromium
```

若缺少系统依赖，应在允许安装的环境准备它们；不要自行提升权限或修改受限机器。
CI 的 [浏览器准备步骤](../.github/actions/setup-playwright/action.yml) 使用
`--with-deps`，不意味着本机任务自动获得相同系统修改权限。

选用与改动对应的脚本，不直接绕开 npm 入口执行 `.browser.mjs`：入口会加载
`tests/e2e/runtime-env.mjs`，默认关闭测试进程的 Native Intel 启动刷新。
这只控制该项刷新，不是通用网络隔离保证。运行前读选定 harness 的端口、
Python、临时数据和网络限制，勿把已有运行服务或真实用户配置当作测试 fixture。

以下是当前有界回归入口，均需从 `frontend/` 运行：

| 范围 | 命令 |
| --- | --- |
| Intel / 数据健康恢复 | `npm run test:e2e:intel-health-recovery` |
| 导航与浏览器存储 | `npm run test:e2e:nav-storage` |
| AI / 设置存储与配置检测 | `npm run test:e2e:ai-settings-storage` |
| 行情与手工交易记录 | `npm run test:e2e:market-ledger` |
| 辩论、移动复盘、上传/历史/日历原始问题族 | `npm run test:e2e:final-families` |

最后一项会启动隔离的 Python 后端；Linux 可在上述虚拟环境已准备后运行：

```sh
PYTHON="$(cd ../backend && pwd)/.venv/bin/python" npm run test:e2e:final-families
```

这些脚本名描述覆盖范围，不能据此推定全部功能已通过。其他真实路由测试的
`PYTHON` / `VR_TEST_PYTHON` 等配置以各自脚本和
[CI workflow](../.github/workflows/ci.yml) 为准。

Linux 打包的无服务生命周期测试另见 [安装包指南](LINUX_INSTALL.md)。

## 如何记录结果

- 记录 exact commit、工作区差异、命令、环境、退出状态与实际覆盖场景
- 分开记录通过、失败、跳过、未运行、环境阻断；只跑部分命令不能写成全套 CI 通过
- 保留必要的合成截图/断言；分享前检查日志、路径和输出，剔除私人资料与凭据
- Mock 请求、真实本地路由、真实市场来源、真实模型、自然使用观察是不同证据
- 连接检测只证明一次有界调用完成；真实模型质量仍需独立、已授权的材料与费用范围
- 源码验证不重启既有服务，不证明稳定合并、部署或 Product Reality Day 1 已开始

文档-only 改动可检查相对链接、命令对应的脚本/lock、冲突标记、
`git diff --check` 与非文档树一致性。没有运行的安装、应用、浏览器和模型验证
应明确标注未运行，不用静态核对代替。
