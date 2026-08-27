# TREND-RADAR1 sidecar 运行资产（Vibe-owned）

TrendRadar 是独立 GPL-3.0 项目，只以**本地 sidecar** 形式运行，
其源码与镜像一律**不进本仓库**。本目录只放 Vibe 自己的运维/认证产物。

- `README.md`：本文件——定位、边界、如何起一个本地 sidecar。
- `compose.qualify.yml`：资格认证用 compose 骨架（引用官方镜像 + digest）。
- `QUALIFICATION.md`：TR1-P0 verdict matrix 与全部实测证据。

## 边界（必须保持）

1. 不 vendor / import / 复制 TrendRadar 源码或配置正文；只能以
   事实性互操作信息（schema 常量、端点路径、镜像 digest）记录。
2. 默认 loopback-only：MCP `/mcp` 与报告服务只绑 `127.0.0.1`；
   远程暴露需单独 Owner 授权 + 独立威胁模型。
3. secrets（AI key / webhook / SMTP / S3）只在本地 runtime 目录/env，
   永不写入 Git、日志、测试快照。
4. Vibe 侧消费只能走两条已认证通道：
   - MCP 官方客户端（`backend/trendradar_gateway.py`，isolated 锁安装）；
   - 只读 SQLite 观察（`backend/trendradar_observation_adapter.py`）。
   二者输出的都是 **observation-only** 数据，不是 Canonical Fact /
   Thesis / Decision / Holding authority。

## 快速起步（官方镜像，需本机 Docker）

```bash
# 在 Vibe 外准备 runtime 目录
mkdir -p ~/tr-runtime/output ~/tr-runtime/config   # 配置自行按上游文档放置

# 以 digest 钉定启动（见 compose.qualify.yml）
docker compose -f ops/trendradar/compose.qualify.yml up -d
```

无 Docker 的机器（如当前认证环境）：按 pinned commit 用隔离 venv 从源码
运行同样成立——`requires-python>=3.12`，入口：

```bash
python -m trendradar                          # core 爬取/调度
python -c "from mcp_server.server import run_server; run_server(project_root='.', transport='http', host='127.0.0.1', port=3777)"
```

Vibe 后端消费侧环境变量（默认全关，显式打开才生效）：

| env | 含义 |
| --- | --- |
| `VIBE_TRENDRADAR_MCP_URL` | sidecar MCP 地址；仅接受回环 http(s)，未设=DISABLED |
| `VIBE_TRENDRADAR_TIMEOUT_SECONDS` | 单次调用总 deadline（默认 15s，>300 拒收） |
| `VIBE_TRENDRADAR_OUTPUT_ROOT` | 观察适配器允许读取的 TrendRadar output 根目录 |
