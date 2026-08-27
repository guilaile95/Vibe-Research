# TREND-RADAR1 TR1-P0 Qualification Record

任务：#230 TR1-P0（Parent #228）——Pin & Qualify TrendRadar Sidecar + Gateway Contract
认证执行日：2026-08-27。记录者为 Vibe 实现分支本身；本文档是 verdict matrix 的现场证据汇总。

---

## 0. 结论速览

verdict matrix 全项 PASS 或显式 BLOCKED_WITH_EVIDENCE；本环境无 Docker daemon，
镜像 runtime 类证明按决策树降级为「pinned 源码隔离运行时」实测 + registry API
digest 记录，全部如实标注方法，无任何伪造的 LIVE 声明。

```text
UPSTREAM_SOURCE_PIN = PASS              master@8ee26026 现场复核未漂移
DOCKER_IMAGE_DIGEST     = PASS*         *registry API 解析（无本地 daemon）
CORE_LOCAL_RUNTIME      = PASS*         *pinned 源码隔离 venv 实测爬取落库
MCP_LOCAL_RUNTIME       = PASS*         *同上，HTTP transport loopback 实测
MCP_LOOPBACK_BOUNDARY   = PASS          显式 host=127.0.0.1:3777 运行+网关强制回环
REPORT_LOOPBACK_BOUNDARY= BLOCKED_WITH_EVIDENCE   本机无 Docker/未起 report 服务；
                                          官方 compose 模板即 127.0.0.1 绑定（源码事实）
MCP_TOOL_DISCOVERY      = PASS          27 tools（与上游自报数量一致）
MCP_RESOURCE_DISCOVERY  = PASS          4 resources
MCP_CLIENT_DEPENDENCY   = QUALIFIED     官方 mcp==1.16.0 隔离锁（fastmcp-slim 无同代版本已留证）
MCP_TIMEOUT_FAILURE     = PASS          asyncio.wait_for 总 deadline + 取消语义（离线可复现）
RAW_HOTLIST_READ        = PASS          MCP get_latest_news 真实内容 + 只读 SQLite 全量观察
RSS_READ                = PASS          hnrss.org 真实抓取 20 条 → output/rss/*.db 可读
SQLITE_READ_ONLY        = PASS          URI mode=ro + PRAGMA query_only
SQLITE_ZERO_MUTATION    = PASS          目录文件集 + 单字节 sha256 + mtime_ns 打开前后不变
RANK_TIMELINE_READ      = PASS          rank_history 全行（含 rank=0 脱榜语义显式建模）
SOURCE_CRAWL_STATUS_READ= PASS          crawl_source_status × crawl_records / rss_crawl_status
SCHEMA_DRIFT_FAIL_CLOSED= PASS          缺列/缺表 → CONTRACT_MISMATCH（测试矩阵覆盖）
AI_DISABLED_SEMANTICS   = PASS          无任何 key 配置时全链路 healthy-degraded
NOTIFICATION_DISABLED_SEMANTICS = PASS  总开关 False + 空 channels，全程零外发
NO_REAL_NOTIFICATION_SENT = PASS        自动化全过程无真实通知（含 MCP send_notification
                                          工具存在于 inventory 但 Vibe allow-list 恒空集）
NEWSNOW_PROVENANCE      = PASS          默认公共 NewsNow endpoint（DataFetcher.DEFAULT_API_URL），
                                          未做生产自托管依赖
CUSTOM_NEWSNOW_ENDPOINT_CONTRACT = PASS DataFetcher(api_url=...) 参数化端点（源码事实）+
                                          fetch_data 状态 success/cache 双态契约实测
GPL_BOUNDARY            = PASS          见 §5
AUTHORITY_BOUNDARY      = PASS          所有输出 observation-only 标注；allow-list P0=∅
SECRET_SCAN             = PASS          新增文件零凭据（见 §6）
CRITICAL = 0 ; HIGH = 0
```

---

## 1. 上游 pin（UPSTREAM_SOURCE_PIN）

| 事实 | 值 | 取证方式 |
| --- | --- | --- |
| repo | `sansan0/TrendRadar` | GitHub API |
| source_commit | `8ee26026ba6c11dec41a95fb3895a7162876caa1` | commits/master 复核（2026-07-17T13:53:35Z），与本 issue 记载一致、未漂移 |
| core version | `6.10.0`（version 文件 + pyproject） | contents API |
| mcp version | `4.1.0`（version_mcp 文件） | contents API |
| license | GPL-3.0 | license API |
| python 要求 | `requires-python >=3.12` | pyproject.toml |
| server framework | `fastmcp==2.12.5` | pyproject.toml dependencies |

## 2. 镜像不可变身份（DOCKER_IMAGE_DIGEST）

本机无 Docker daemon（`docker: command not found`，Program Files/LOCALAPPDATA 均无安装痕迹，
podman 同样不存在）。按问题预设走证据降级：用 Docker Hub registry HTTP API 匿名解析
（取证日 2026-08-27，认证脚本可直接重放）：

```text
wantcat/trendradar:6.10.0     tag manifest-list digest =
  sha256:de396d242c105d697c2765f5341ca71a45d9bcefe934d1d32b511eeae2f0d0be
    linux/amd64 sha256:c7dc319df6e7929581418a6d1ea132019c2664f53c3d82183f09b5c511111a6b
    linux/arm64 sha256:d65d5d3a265f74508f2f072a6ad2b6713ab3b2adf88d7bf54595c679feb45c28
wantcat/trendradar-mcp:4.1.0  tag manifest-list digest =
  sha256:92eabda020223f94a3e0a65aa9bc9b83fb25ebc10b31bd0fad097fd2260ed1dc
    linux/amd64 sha256:1a1717daedb44a74414512e11ee8de865daffa984d00cb5d689d9a8f868cd5a8
    linux/arm64 sha256:d0a10037ec09a14ad3b4235d920d4bc59fe4a0a6797f4812b17be042a3221e4e
```

`ops/trendradar/compose.qualify.yml` 已用 tag+manifest-list digest 钉定；
将来在有 daemon 的机器上 `docker pull` 后 RepoDigest 应与之吻合，差异即重新认证触发条件。

## 3. 运行时资格认证（CORE/MCP，pinned 源码方式）

**方法声明**：因无 Docker，采用 pinned commit 源码 + 隔离 venv（py3.12.10）在
仓库外 `%TEMP%/tr-qualify` 实测；所有结论针对 pinned source identity，
不声明 Docker runtime 行为。

### 3.1 Core 爬取与 SQLite 落库

- `ENABLE_NOTIFICATION=False` 主开关强制；模板渠道本来就全空。
- 真实公共 NewsNow 数据：toutiao/baidu/wallstreetcn-hot/thepaper 四平台
  （success 4 / failed 0），新增 90 条 → `output/news/2026-08-27.db`（200,704 字节，
  sha256 f630fe744bc5c5234859e4ae988b15faf7097c7631a3bde78d2e43bb948e02c3）。
- 实产 DB schema 与 pinned DDL（schema.sql/rss_schema.sql/ai_filter_schema.sql）
  逐表逐列一致，仅多 sqlite_sequence（SQLite 内部表）。

### 3.2 MCP HTTP（loopback）

- 启动：`run_server(project_root='.', transport='http', host='127.0.0.1', port=3777)`，
  端点 `/mcp`。
- tools/list：**27 tools**，名称全集已留存于工作单日志（aggregate_news … trigger_crawl）。
- resources：**4 个**：config://platforms, config://rss-feeds, data://available-dates,
  config://keywords。
- 良性调用：`list_available_dates`（返回本地可用日期含 2026-08-27）、
  `get_latest_news(limit=2)`（真实热点内容返回）。
- 错参被服务端 pydantic 校验拒绝（错误路径真实验证过一次，即 probe 第一版
  get_latest_news 参数名不匹配 → ToolError）。
- **send_notification 与 trigger_crawl 存在于服务端工具面**；Vibe 网关侧
  `ALLOWED_TOOL_NAMES = frozenset()` 在 Phase 0 使其永不可达（离线断言 + live 断言双保险）。

### 3.3 RSS 通道

- feed=hnrss.org frontpage 真实抓取成功（20 条入库）→ `output/rss/2026-08-27.db`
  存在且 schema 符合 rss_schema.sql；ruanyifeng feed 配置为 enabled=false 正确跳过。

### 3.4 AI / notification 关闭语义

无任何 AI key / webhook 配置下：core 爬取正常、storage 正常、MCP 数据查询正常 ——
healthy-degraded 成立；全程未发送任何真实通知。

## 4. Vibe 网关集成（production code path 实测）

配置 `VIBE_TRENDRADAR_MCP_URL=http://127.0.0.1:3777/mcp` 后，以 isolated lock 安装的
客户端 venv 直接驱动 `backend/trendradar_gateway.py` 生产代码：

```text
status_snapshot() -> OK; server={trendradar-news, version 1.16.0, protocol 2025-06-18}
tool_inventory() -> OK; 27 tools （连续两次独立生命周期均 OK）
非回环 URL http://10.9.8.7:3333/mcp -> CONFIG_ERROR("loopback-only; refusing...")
宕机端口 -> UNAVAILABLE（TaskGroup 连接失败收敛）
超时类 -> TIMEOUT（asyncio.wait_for 总 deadline 强制）
```

实现期间由 live 冒烟暴露并当场修复的两处缺陷（回归都已在离线矩阵固化）：
1. ClientSession 不自动发 initialize → 第二次连接 400（已把 initialize 收进 `_run`）；
2. 非法 URL 被错标 DISABLED → 已改为 CONFIG_ERROR fail-closed 分支优先。

## 5. MCP_CLIENT_DEPENDENCY 选型（Qualification 流程证据）

按问题预设顺序执行：

1. 首选 `fastmcp-slim==2.12.5`（与服务端 fastmcp 同版本）：PyPI 实证 **fastmcp-slim
   只发布 3.x 线**（releases: 3.3.0…3.4.7，无任何 2.x）→
   `pip._internal.exceptions.DistributionNotFound: No matching distribution found for
   fastmcp-slim==2.12.5`（Windows py312 与 Linux py311 两边 pip-tools 编译同样失败，
   2026-08-27 现场留痕）。协议代际也不匹配：服务器家族实证绑定官方 `mcp==1.16.0`。
2. 按预设 fallback 评估官方 MCP Python SDK：
   - license MIT ✓；supported Python ✓（requires-python>=3.10）；server 传输 Streamable HTTP ✓；
   - 与服务端的兼容性直接来自认证 venv 的事实组合（server fastmcp 2.12.5 + mcp 1.16.0，
     live 握手协议版本 2025-06-18）；client 固定 pin 同代 `mcp==1.16.0`；
   - **依赖冲突发现**：`mcp>=1.x 全线 requires httpx>=0.27`（PyPI metadata 全版本核对），
     而 Vibe 主依赖树 mootdx 全版本线钉死 `httpx<0.24~<0.26` → 单环境解析
     `ResolutionImpossible`（完整冲突链已留痕）。
3. 最终形态：**isolated dependency tree**
   `backend/requirements-trendradar.txt`（pin `mcp==1.16.0`）+ 双平台独立锁
   （linux-py311 / windows-py312）+ CI 两个 job 各加「编译一致性 + 安装 + import 冒烟」步骤。
   运行端遵循本仓库既有重数据源约定（akshare/mootdx 同款模式）：未安装该锁时网关
   一切调用返回显式 `UNAVAILABLE(client-missing)` envelope，不影响其余功能；
   gateway 全部离线测试走 fake transport，不依赖该包存在。

结论：**QUALIFIED**（官方 mcp SDK、isolated lock、双平台 CI 校验、缺装行为显式降级）。

## 6. GPL 边界证明（GPL_BOUNDARY）

- 本任务 diff 中不存在 TrendRadar Python/YAML/markdown 正文拷贝；
  `ops/trendradar/compose.qualify.yml` 仅含镜像 digest 引用与环境变量骨架；
  schema 契约以"列名常量集合"形式表达（facts per §"minimal factual interoperability"），
  SQL 全部为 Vibe 自写最小 SELECT。
- 无 in-process import：TrendRadar 代码只运行在其自有进程/容器/venv；
  Vibe 进程只经由官方 mcp 客户端与其对话（network process boundary）。
- 新增第三方依赖唯一官方 `mcp==1.16.0`，MIT License ✓（httpx/anyio/httpcore 等
  传递依赖 BSD/Apache/MIT 族，均在独立树内）。
- 自动核查（PR Gate 可重放，实测输出 `UPSTREAM_BODY_MARKERS_ADDED=0` + 空导入清单）：

```bash
# 1) 新增行中不允许出现上游标志性正文/上游私有模块引用
git diff <BASE> -- backend ops | grep -E "^\+" \
  | grep -cE "TrendRadar 数据库表结构|from trendradar\.(core|crawler|storage|ai|report|notification|utils)|import trendradar\b"
#   预期 0

# 2) 不允许 import 上游包或其子模块
grep -rnE "^import trendradar$|^from (trendradar|mcp_server\.(services|tools))\b" backend --include="*.py"
#   预期无输出。注：backend/mcp_server.py 是 Vibe 自己更早已有的 stdio MCP server，
#   与上游目录仅同名，tests/test_mcp_stdio_encoding.py 等引用的是 Vibe 自有模块。
```

补充事实：Vibe 对自身 mcp_server 的既有引用早于本任务，属同名词碰撞而非上游导入；
已在新代码命名层面避开歧义（网关模块前缀 `trendradar_gateway`）。

## 7. Secret scan（SECRET_SCAN）

新增/修改文件（backend/{trendradar_gateway,trendradar_observation_adapter,
trendradar_router}.py、requirements*.txt、tests/test_trendradar_*.py、
ops/trendradar/*、ci.yml 片段）人工+grep 复核：无 token/webhook/password/S3 key/
AI key 形态字符串；compose 内 env 只是占位符变量名。

## 8. AUTHORITY_BOUNDARY 陈述

三个 production 模块的每个 envelope 都携带
`usage_boundary: observation_only_not_an_investment_authority`
（adapter）或等价 provenance 结构（gateway）。P0 未向 Evidence/Thesis/Decision/
Trade/Holding 写入任何字段，也建立不了此类写入（无入口）。未来任何 Intel 卡片只能
作为 observation 展示层消费这两个只读通道。

## 9. 遗留与后续（非 blocker）

- REPORT_LOOPBACK_BOUNDARY 与官方镜像 runtime 类证据：待有 Docker 的机器跑
  `compose.qualify.yml` 并补 pull-digest 复核（当前源码侧同类语义已验）。
- NewsNow 生产级自托管不在本 keeper 范围（endpoint 参数化契约已验）。
