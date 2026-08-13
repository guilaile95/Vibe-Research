# P0-SEC1 本地 API 访问边界 V0.1

## 1. 范围

本 Slice 只处理 **本地 API 访问边界**：loopback 绑定、浏览器跨源（CORS/Origin）、
Host 边界、可选 API Key 契约、health 公开面。

**不在本 Slice**（留给 SEC2/SEC3 或其它独立 Slice）：

- HTTP → 本机 AI CLI 特权边界（`--yolo` / `--auto`）＝ P0-SEC2；
- 模型 baseURL SSRF / redirect / DNS rebinding ＝ P0-SEC3；
- 前端 localStorage 存储 key（S-04）、研报上传配额（S-05）、异常反射（S-08）；
- 多用户 / 登录 / JWT / OAuth——Vibe-Research 是单用户本地系统，永不做账号体系。

## 2. 威胁模型

```
恶意网页 → 浏览器 → http://127.0.0.1:8900/api/*  → 读写私有投资数据
```

冻结：**127.0.0.1 不是鉴权机制**。任何能执行 JS 的网页（广告、恶意标签页）都可以
向 loopback 发起请求；浏览器同源策略只在 `Access-Control-Allow-Origin` 不允许时
阻止**读取**响应。因此默认必须满足：

1. CORS 默认只允许官方本地前端 Origin（`http://localhost:5899` / `http://127.0.0.1:5899`）；
2. 通配 `*` 与私有 API 的组合直接拒绝启动；
3. 非 loopback 绑定且未配置 `VR_API_KEY` → fail closed（禁止仅警告）。

## 3. 不变量（机械证明）

| # | 不变量 | 值 |
|---|---|---|
| 1 | DEFAULT_CORS_WILDCARD | NO |
| 2 | EVIL_ORIGIN_ALLOWED | NO |
| 2b | EVIL_ORIGIN_ROUTE_EXECUTION_BLOCKED | YES（服务端 Origin gate，403 于路由执行前） |
| 3 | PRIVATE_API_ANONYMOUS_NON_LOOPBACK | NO |
| 4 | NON_LOOPBACK_WITHOUT_AUTH | FAIL_CLOSED |
| 5 | HEALTH_PUBLIC | YES |
| 6 | HEALTH_PRIVATE_DATA | NO |
| 7 | CORS_PREFLIGHT | PASS |
| 8 | AUTH_TOKEN_REFLECTED | NO |
| 9 | FRONTEND_LOCAL_WORKFLOW | PRESERVED |

## 4. 配置语义

| 环境变量 | 语义 |
|---|---|
| `VR_ALLOW_ORIGINS` | 逗号分隔 `http(s)://host[:port]`。未设置 = 默认本地前端白名单；显式设置 = 严格解析，`*`/空值/畸形值 → 启动失败（fail closed，不回落 `*`）。同时作为服务端 Origin gate 的放行集合（非白名单且非 same-origin 的浏览器 Origin → 403）。 |
| `VR_API_KEY` | 设置后所有 `/api/*`（除 `/api/health`）要求 `Authorization: Bearer <key>`。错误响应 401，固定文案，不回显 token。 |
| `VR_HOST` | 可选，声明服务绑定地址。设置且为非 loopback 时，未配置 `VR_API_KEY` → 启动失败。未设置时以 uvicorn `--host` 实际绑定为准。 |
| `VR_TRUSTED_HOSTS` | 可选，逗号分隔纯主机名，扩展 Host 头白名单（默认 `localhost` / `127.0.0.1` / `[::1]`）。 |

## 5. 运行矩阵

| 场景 | 行为 |
|---|---|
| loopback + 无 key（默认） | 允许；仅白名单 Origin 能拿到 CORS 响应（本地前端正常工作） |
| loopback + key | 私有端点要求 key；`/api/health` 豁免 |
| `0.0.0.0` / LAN / 公网 + 无 key | 启动失败（`VR_HOST` 已声明时）；否则运行时全部请求 503（含 health） |
| 非 loopback + 有效 key | 允许（产品策略支持公网部署）；需同时配置 `VR_ALLOW_ORIGINS` 与 `VR_TRUSTED_HOSTS` |

## 6. 实现位置

- `backend/app.py`：
  - `_parse_origins` / `_ALLOWED_ORIGINS`：CORS 白名单（默认本地前端，严格解析）；
  - `lifespan`：`VR_HOST` 启动 fail-closed 校验；
  - `_LocalHostGate`：最小 Host 边界（未用 starlette `TrustedHostMiddleware`，
    因其对 `[::1]:port` 的 Host 头按冒号切分会得到 `[`，无法干净支持 IPv6 字面量）；
  - `_OriginGate`：服务端 Origin 边界——`/api/*` 上携带非白名单且非 same-origin
    Origin 的浏览器请求在路由执行前 403（固定文案，不反射）；缺 Origin（curl/脚本）
    或 same-origin（Origin == scheme://Host）放行；
  - `_NonLoopbackGuard`：运行时 bind 边界（读 `scope["server"]` 实际监听地址，
    与启动方式无关）；`testserver`（TestClient 进程内传输）视作 loopback 等价；
  - `_PUBLIC_API_PATHS = {"/api/health"}`：默认私有，只放行明确公开路径。
  - 中间件链：`NonLoopbackGuard → HostGate → OriginGate → API Key → CORS → Routes`。
- 测试：`backend/tests/test_local_api_security.py`（A–P，全部离线）。

## 7. 升级注意（行为变更）

- 默认 CORS 从 `*` 收紧为本地前端白名单：非本地前端（例如 `vite preview` 的其它端口、
  或独立部署的前端）必须显式设置 `VR_ALLOW_ORIGINS`；
- 非 loopback 部署现在必须同时配置 `VR_API_KEY`（否则拒启/503）与 `VR_TRUSTED_HOSTS`；
- `/api/health` 保持匿名可访问，但只返回固定 `{ok, service, version}`，
  任何私有数据出现在 health 即视为回归。
