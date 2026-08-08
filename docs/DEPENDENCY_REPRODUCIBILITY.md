# Python 依赖可复现性（Phase B1，平台特定 authority lock）

> 人类意图：`backend/requirements.txt` + `backend/requirements-dev.txt`（手写，
> 只表达 direct dependency 意图，可放宽）。
> 精确环境：以下 `*-lock.txt` 为**生成的 authority 产物**（不手改，顶部 header
> 记录 compiler 与来源；lint 规则：每个包必须 `==` exact pin）。

## 平台合同（CONTRACT D：PLATFORM-SPECIFIC AUTHORITATIVE LOCKS）

| 环境 | authority | 角色 | 安装命令 |
|---|---|---|---|
| Linux | Ubuntu / CPython 3.11（GitHub Actions） | CI + canonical runtime/test | `pip install -r backend/requirements-dev-linux-py311.lock.txt` |
| Windows | Windows / CPython 3.12.10 | canonical local development/test | `pip install -r backend/requirements-dev-windows-py312.lock.txt` |

- 两个平台都是 **EXACT REPRODUCIBLE**（各自 authority 生成与验证）。
- 已实证：single cross-platform lock **不可行**（uvloop 无 Windows wheel、
  tzdata/mini-racer/colorama 为 Windows-only、akracer 为 Linux-only；
  pip-tools 编译时按当前平台求值 marker）。Windows 不是 production
  deployment target，故**不设** Windows runtime-only 第四份 lock（DRY）。
- Windows 不再描述为"compatibility-tested against Linux lock"（已被实证否定）。

## Lock 文件（backend/）

| 文件 | 内容 | authority |
|---|---|---|
| `requirements-linux-py311.lock.txt` | Linux runtime closure（53 包） | Ubuntu/3.11 |
| `requirements-dev-linux-py311.lock.txt` | Linux runtime+dev 完整 closure（58 包） | Ubuntu/3.11 |
| `requirements-dev-windows-py312.lock.txt` | Windows runtime+dev 完整 closure（59 个 == pin，含 `uvicorn[standard]`） | Windows/3.12.10 |

## 编译器（LOCK_COMPILER，两平台相同）

`backend/requirements-tooling.txt`：`pip==26.0.1` + `pip-tools==7.6.0`
（已实测 Windows/3.12.10 与 Linux/3.11 均可正常 compile；pip 26.2.1 与
pip-tools 7.6.0 API 不兼容，编译环境必须 26.0.1）。

## 再生成命令（backend/ 目录，各平台 authority 环境）

Linux（Ubuntu/3.11）：

```text
pip install -r requirements-tooling.txt
pip-compile --no-emit-index-url --output-file=requirements-linux-py311.lock.txt requirements.txt
pip-compile --no-emit-index-url --output-file=requirements-dev-linux-py311.lock.txt requirements.txt requirements-dev.txt
```

Windows（Windows/3.12.10）：

```text
pip install -r requirements-tooling.txt
pip-compile --no-emit-index-url --output-file=requirements-dev-windows-py312.lock.txt requirements.txt requirements-dev.txt
```

主动升级：上述命令加 `--upgrade`（单独维护任务，与日常 regeneration 分离）。
CI 通过 "Canonical Python lock check"（Linux）与 "Python Windows lock check"
（Windows）分别验证两平台再生成零 diff。

## 已知事实

- hashes：NON-BLOCKING；未来若启用必须**各平台分别研究**，不得用一份
  hashes lock 强行统一两平台。
- pip-compile 无跨平台编译参数（7.6.0 实测）：Linux lock 只能 Linux 生成，
  Windows lock 只能 Windows 生成（CI 双 authority 分别验证）。
