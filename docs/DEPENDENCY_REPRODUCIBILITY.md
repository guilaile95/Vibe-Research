# Python 依赖可复现性（Phase B1）

> 人类意图：`backend/requirements.txt` + `backend/requirements-dev.txt`（手写，
> 只表达 direct dependency 意图，可放宽）。
> 精确环境：`backend/requirements.lock.txt`（runtime 53 包）与
> `backend/requirements-dev.lock.txt`（runtime + dev 58 包，自包含单文件）。
> 编译器：`backend/requirements-tooling.txt`（`pip-tools==7.6.0`）。

## 权威与合同（Contract B — Canonical Lock + Compatibility Runtime）

- **LOCK_AUTHORITY = Ubuntu / CPython 3.11**（GitHub CI 环境）：权威 lock 须在
  CI 平台执行同一条 pip-compile 命令生成（自动纳入 Linux 专属包如 uvloop）。
- **WINDOWS / CPython 3.12 = COMPATIBILITY_TESTED / NOT_LOCK_AUTHORITY**：
  当前提交的 lock（Windows/3.11 编译）在 Windows 3.11/3.12 实测 exact 安装
  与测试全绿；对 Linux 存在一个软漂移点（uvloop 未 pin，pip 现场解析）——
  发布前应在 CI 平台重生成 lock 以升格 authority。
- 编译必须使用 **CPython 3.11**：3.12 编译会把 numpy 锁到 2.5.1（无 cp311
  wheel），导致 3.11 CI 无法安装。

## 再生成命令（backend/ 目录，Python 3.11 + pip-tools 7.6.0）

日常 regenerate（锁定当前版本，不升级）：

```text
pip-compile --no-emit-index-url -o requirements.lock.txt requirements.txt
pip-compile --no-emit-index-url -o requirements-dev.lock.txt requirements.txt requirements-dev.txt
```

主动升级（单独维护任务，与日常 regeneration 分离）：

```text
pip-compile --no-emit-index-url --upgrade -o requirements.lock.txt requirements.txt
pip-compile --no-emit-index-url --upgrade -o requirements-dev.lock.txt requirements.txt requirements-dev.txt
```

## 已知事实

- lock 文件**不手改**；顶部 header 记录 compiler 版本与来源。
- 当前提交形态**不带 hashes**：Windows 编译产物在 Linux 上 `--require-hashes`
  会因 uvloop extra 硬失败；带 hashes 版本须待权威平台（Linux CI）生成后启用
  （trade-off 已记录，不牺牲可用性）。
- pip-tools 7.6.0 与 pip 26.2.1 存在 API 不兼容（编译时用 pip 26.0.1）；
  安装端 pip 不受影响。

## Canonical Linux 生成结果（2026-08-08，CI authority 实测）

Ubuntu/CPython 3.11 authority 再生成与 Windows 候选 lock 的差异（已按
authority 输出 canonicalize 提交）：

| 包 | Windows lock | Ubuntu lock | 说明 |
|---|---|---|---|
| uvloop | 无 | `0.22.1`（无 marker） | Linux-only；Windows 无 wheel |
| akracer | 无 | `0.0.14` | Linux 侧 akshare JS 引擎（替代 mini-racer） |
| mini-racer | `0.14.1` | 无 | Windows 侧 akshare JS 引擎 |
| tzdata | `2026.3` | 无 | Windows-only（zoneinfo 数据） |
| colorama | `0.4.6` | 无 | Windows-only |

含义：single pip-tools lock **不能同时服务两个平台**（条件包 marker 在编译时
被求值剥离/丢弃）。Windows/3.12 对 canonical Ubuntu lock 的兼容性验证结果与
平台 lock 设计评估见 Phase B1 Publication 报告。

**2026-08-08 实测结论（决定性）**：

- Ubuntu/3.11 authority 侧**闭环成功**：canonicalize 后 CI 再生成零 diff
  （idempotency PASS）、7/7 jobs 全绿。
- Windows/3.12 全新环境安装 canonical lock **失败**：uvloop==0.22.1 无
  Windows wheel，pip 源码构建报 `RuntimeError: uvloop does not support
  Windows`（exit 1）。
- 按授权契约：**Contract B 不成立 → CHANGES REQUIRED**；P1 保持
  `PROVISIONALLY MITIGATED`，不关闭。
- 最小平台 lock 设计（待授权实施）：保留 `requirements-dev.lock.txt`
  （Linux authority，CI 验证）+ 新增 `requirements-dev.windows.lock.txt`
  （Windows 本机同编译器生成、提交、文档化再生成步骤；含 tzdata/
  mini-racer/colorama，不含 uvloop/akracer）；runtime lock 同理按平台各一
  （Windows runtime 由 windows dev lock 覆盖，共 3 个文件）。
