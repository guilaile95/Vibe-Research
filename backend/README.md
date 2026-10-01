# Vibe-Research Backend

市场数据查询、本地研究与决策/账户记录，以及可选 AI 层。包含受控写入与本地持久化，不能作为“全部只读、无状态”服务部署。权限与调用链见 [架构说明](../docs/ARCHITECTURE.md)。

## 安装

```bash
cd backend
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-linux-py311.lock.txt
```

> 上述为 Linux CPython 3.11 的锁定环境。Windows 请按 [根目录启动说明](../README.md#运行方式) 使用对应版本及锁文件。公开数据源可能限流、故障或变更，不保证安装后所有来源都可用。
> 一致预期 / 新闻 / 公告需 `akshare`，K线 / 财务需 `mootdx`；未装时对应端点返回 501 + 安装提示，不影响其余功能。

## 1. HTTP API（给网页前端 + 系统 AI）

```bash
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8900
```

| 端点 | 说明 | 依赖 |
|---|---|---|
| `GET /api/health` | 健康检查 | — |
| `GET /api/indices` | 大盘指数实时行情 | stdlib |
| `GET /api/quote?codes=600519,000858` | 实时行情（PE/PB/市值/涨跌停…） | stdlib |
| `GET /api/valuation?code=600519` | 完整估值（前向PE/PEG/消化年数） | requests+akshare |
| `GET /api/valuation/percentile?code=600519` | 估值历史分位（近5年·百度股市通） | akshare |
| `GET /api/financials?code=600519` | 财务关键指标（同花顺摘要，最新报告期，前端个股页用） | akshare |
| `GET /api/reports?code=600519` | 个股研报列表（含 PDF 链接） | requests |
| `GET /api/announcements?code=600519` | 近期公告（东财） | requests |
| `GET /api/news?code=600519` | 个股新闻 | akshare |
| `GET /api/kline?code=600519` | K线 | mootdx |
| `GET /api/finance?code=600519` | 季报财务快照（mootdx，前端未用 / 备用） | mootdx |
| **资金面·筹码·信号（v3.3）** | `/api/margin` · `/block-trade` · `/holders` · `/dividend` · `/fund-flow` · `/dragon-tiger` · `/lockup` · `/blocks` · `/hot-concepts` · `/investor-qa` · `/industry` | requests |
| `GET /api/market/overview` · `/api/radar` | 市场情绪+板块资金 · 资讯雷达 | akshare / stdlib |
| `POST /api/chat` | 系统 AI 对话（API 模式可使用受控工具；订阅模式能力不同） | 依所选接入方式 |
| `POST /api/ai/connection-test` | 手动固定合成请求、无工具、限时检测；不是模型质量评测 | httpx；[边界与费用](../docs/AI_CONNECTION_TEST.md) |

> 上表为主要端点；完整路由清单见 `app.py`。要更全量的 A 股数据（打板 / ETF期权 / 全市场行业排名等），用根目录 [`a-stock-data/`](../a-stock-data/SKILL.md) 工具箱。

`/api/chat` 请求体：
```json
{
  "messages": [{"role": "user", "content": "茅台估值贵不贵？"}],
  "context": "本页上下文（可空）",
  "llm": {"baseURL": "https://api.deepseek.com", "apiKey": "sk-…", "model": "deepseek-chat"}
}
```
`llm` 由前端随请求带上；此聊天请求本身不持久化 key。设置页的保存操作另会同步本机后台凭据，以支持已配置的定时功能；模型请求会将认证凭据发送给所选服务端，勿与“本地保存”混淆。

## 2. MCP Server（给 Claude Code / 高手 agent）

协议层不引入额外 MCP 框架，但仍需上面完整的后端 Python 环境。挂进 Claude Code：

```bash
claude mcp add vibe-research -- \
  "$(pwd)/.venv/bin/python" "$(pwd)/mcp_server.py"
```

工具清单由 `mcp_server.py` 从 `chat.TOOLS`（底层 `ai_tools.TOOLS`）动态生成，不再只有四个工具。通过 MCP 的 `tools/list` 查询当前注册清单。MCP 本身不调用模型；外部 agent 的模型费用及数据源额度由相应服务决定。

### 完整 A 股数据工具箱（随仓库自带）

仓库另带 [a-stock-data](../a-stock-data/SKILL.md) 的数据源工具说明；能力、依赖和限制以该目录当前文档为准，不以历史端点数量作保证。
- 要调哪个接口，直接看 [`a-stock-data/SKILL.md`](../a-stock-data/SKILL.md)——每个端点都有 copy-paste 即用的代码（内嵌全部调用逻辑，零第三方数据封装依赖，东财接口已内置限流防封）。
- 运行依赖：`pip install mootdx requests pandas stockstats`（自包含，v3.0 起已移除 akshare）。
- 仓库内置的是固定版本快照，可独立使用，无需额外下载。
- 分工：MCP 暴露已注册的受控查询工具；数据源目录提供额外研究接口说明。不要把外部 agent 的能力等同于本产品受限的 Codex 页面聊天。

