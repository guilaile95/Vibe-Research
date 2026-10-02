# Vibe-Research Backend

市场数据查询、本地研究与决策/账户记录，以及可选 AI 层。后端包含受控写入和本地持久化；部署与调用前请了解[架构与数据边界](../docs/ARCHITECTURE.md)。

## 安装

按[入门运行指南](../docs/GETTING_STARTED.md)选择平台、Python 版本与对应精确锁文件，并启动所需服务。依赖合同见[依赖可复现性](../docs/DEPENDENCY_REPRODUCIBILITY.md)。

公开数据源可能限流、故障或变更；安装成功不代表所有来源均可用。下表中的依赖说明用于理解接口，不替代完整锁定环境。

## 1. HTTP API（给网页前端 + 系统 AI）

Linux 完成安装后，在 `backend/` 目录启动后端；其他平台命令见入门指南：

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

> 上表是部分接口参考，不是完整 API 清单；当前路由、参数和数据来源以 [`app.py`](app.py) 及其注册的 router 模块为准。额外 A 股研究接口见根目录 [`a-stock-data/`](../a-stock-data/SKILL.md) 工具说明。

`/api/chat` 请求体：
```json
{
  "messages": [{"role": "user", "content": "茅台估值贵不贵？"}],
  "context": "本页上下文（可空）",
  "llm": {"baseURL": "https://api.deepseek.com", "apiKey": "sk-…", "model": "deepseek-chat"}
}
```
`llm` 由前端随请求带上；此聊天请求本身不持久化 key。设置页保存操作另会将模型配置与凭据同步到本机后台，供已配置的定时功能使用。模型请求会将认证凭据和所需上下文发送给选定服务端。

## 2. MCP Server（给 Claude Code / 高手 agent）

协议层未引入额外 MCP 框架，但仍需完整的后端 Python 环境。在 `backend/` 目录将其挂进已安装的 Claude Code：

```bash
claude mcp add vibe-research -- \
  "$(pwd)/.venv/bin/python" "$(pwd)/mcp_server.py"
```

工具清单由 [`mcp_server.py`](mcp_server.py) 从 `chat.TOOLS`（底层 `ai_tools.TOOLS`）动态生成，可通过 MCP 的 `tools/list` 查询。MCP 本身不调用模型；外部 agent 的认证、模型费用和数据源额度由相应服务决定。

### A 股数据工具箱（随仓库自带）

仓库带有 [`a-stock-data/`](../a-stock-data/SKILL.md) 数据工具与示例快照。能力、依赖和来源限制以该目录当前文档为准，不以历史端点数量保证覆盖或可用性。

- 按具体接口说明准备依赖；请求限流措施不保证第三方来源始终可达。
- MCP 暴露已注册的受控工具；数据源目录提供额外研究接口说明。
- 外部 agent 的工具能力与本产品受限的 Codex 页面聊天不同，不能相互推定。

