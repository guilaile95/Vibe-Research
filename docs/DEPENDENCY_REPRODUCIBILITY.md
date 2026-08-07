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
