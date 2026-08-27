"""TrendRadar sidecar gateway（TR1-P0）。

Vibe-owned 独立进程边界：通过 MCP Streamable HTTP 访问本地 loopback 运行的
TrendRadar sidecar（官方镜像或 pin 源码运行，见 ops/trendradar/）。本模块是
Vibe 内唯一允许发起该访问的入口：

- 显式启用：默认 DISABLED；仅当 VIBE_TRENDRADAR_MCP_URL 配置为回环地址时 READY；
- loopback-only URL 强制（非回环即 CONFIG_ERROR fail-closed）；
- strict allow-list tool 调用包装（无"任意 JSON 调任意工具"的公开面）；
- 归一化 envelope + 显式 failure classes；
- provenance 固定携带上游身份与检索时间。

上游不是 Vibe authority：输出只能是 observation 输入，永不直接成为
Fact/Thesis/Decision/Holding 权威（authority boundary 由调用方保证，
本模块在 provenance 里显式声明 observation-only）。
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

GATEWAY_AUTHORITY_REF = "vibe:trendradar_gateway:v0.1"

# 已认证的上游不可变身份（ops/trendradar/QUALIFICATION.md 为记录权威）
UPSTREAM_REPO = "sansan0/TrendRadar"
UPSTREAM_SOURCE_COMMIT = "8ee26026ba6c11dec41a95fb3895a7162876caa1"
UPSTREAM_CORE_VERSION = "6.10.0"
UPSTREAM_MCP_VERSION = "4.1.0"
UPSTREAM_LICENSE = "GPL-3.0"
CORE_IMAGE_TAG_DIGEST = (
    "wantcat/trendradar:6.10.0@sha256:"
    "de396d242c105d697c2765f5341ca71a45d9bcefe934d1d32b511eeae2f0d0be"
)
MCP_IMAGE_TAG_DIGEST = (
    "wantcat/trendradar-mcp:4.1.0@sha256:"
    "92eabda020223f94a3e0a65aa9bc9b83fb25ebc10b31bd0fad097fd2260ed1dc"
)
CORE_IMAGE_AMD64_DIGEST = (
    "sha256:c7dc319df6e7929581418a6d1ea132019c2664f53c3d82183f09b5c511111a6b"
)
MCP_IMAGE_AMD64_DIGEST = (
    "sha256:1a1717daedb44a74414512e11ee8de865daffa984d00cb5d689d9a8f868cd5a8"
)

MCP_URL_ENV = "VIBE_TRENDRADAR_MCP_URL"
TIMEOUT_ENV = "VIBE_TRENDRADAR_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 15.0

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# status / failure classes（超出此集合的内部状态不得外泄）
STATUS_OK = "OK"
STATUS_DISABLED = "DISABLED"
STATUS_CONFIG_ERROR = "CONFIG_ERROR"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
STATUS_UPSTREAM_ERROR = "UPSTREAM_ERROR"
STATUS_BAD_ARGUMENT = "BAD_ARGUMENT"

ENVELOPE_STATUSES = frozenset(
    {
        STATUS_OK,
        STATUS_DISABLED,
        STATUS_CONFIG_ERROR,
        STATUS_UNAVAILABLE,
        STATUS_TIMEOUT,
        STATUS_CONTRACT_MISMATCH,
        STATUS_UPSTREAM_ERROR,
        STATUS_BAD_ARGUMENT,
    }
)


def utc_now_iso() -> str:
    """canonical UTC ISO-8601（秒级、零时区、Z 后缀）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def upstream_identity() -> dict[str, Any]:
    """已认证上游事实身份（静态 pin 值，与 QUALIFICATION.md 一致）。"""
    return {
        "repo": UPSTREAM_REPO,
        "source_commit": UPSTREAM_SOURCE_COMMIT,
        "core_version": UPSTREAM_CORE_VERSION,
        "mcp_version": UPSTREAM_MCP_VERSION,
        "license": UPSTREAM_LICENSE,
        "core_image": CORE_IMAGE_TAG_DIGEST,
        "mcp_image": MCP_IMAGE_TAG_DIGEST,
        "integration_authority_ref": GATEWAY_AUTHORITY_REF,
        "usage_boundary": "observation_only_not_an_investment_authority",
    }


def _timeout_seconds_from_env(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0 or parsed > 300:
        return None
    return parsed


@dataclass(frozen=True)
class GatewayConfig:
    """已校验的网关配置（构造成功即代表 URL 合法且 loopback-only）。"""

    mcp_url: str
    timeout_seconds: float

    @property
    def host(self) -> str:
        return urlsplit(self.mcp_url).hostname or ""


def _host_is_loopback(hostname: str | None) -> bool:
    if not hostname:
        return False
    lowered = hostname.lower().strip("[]")
    if lowered in LOOPBACK_HOSTS:
        return True
    # 数值形态统一判回环（127.0.0.0/8 全段都视为本机）
    try:
        return ipaddress.ip_address(lowered).is_loopback
    except ValueError:
        return False


def resolve_config(
    mcp_url: str | None = None, timeout_seconds: Any = None
) -> tuple[GatewayConfig | None, str | None]:
    """解析并强制校验配置；返回 (config, error)。

    - URL 未提供：这是显式 DISABLED 的合法路径（error=None, config=None 由调用方区分）；
    - URL 提供但非回环/非 http(s)/畸形：CONFIG_ERROR fail-closed；
    - timeout 非法：忽略取默认值（不 fail 整个配置——值域内覆写才生效）。
    """
    raw_url = (mcp_url or "").strip()
    if not raw_url:
        return None, None
    parts = urlsplit(raw_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None, "mcp_url must be an absolute http(s) URL"
    if not _host_is_loopback(parts.hostname):
        return None, (
            "TrendRadar gateway is loopback-only; "
            f"refusing non-loopback host {parts.hostname!r}"
        )
    timeout = _timeout_seconds_from_env(timeout_seconds)
    return GatewayConfig(
        mcp_url=raw_url, timeout_seconds=timeout or DEFAULT_TIMEOUT_SECONDS
    ), None


def load_config(env: dict[str, str] | None = None) -> tuple[
    GatewayConfig | None, str | None
]:
    source = env if env is not None else os.environ
    url = source.get(MCP_URL_ENV, "")
    timeout = source.get(TIMEOUT_ENV, "")
    if url.strip():
        config, error = resolve_config(url, timeout)
        return config, error
    # URL 未配置但 timeout 有值：同样走一次校验让坏值可见
    if timeout.strip() and _timeout_seconds_from_env(timeout) is None:
        return None, f"{TIMEOUT_ENV} must be a positive number <= 300"
    return None, None


# ---------------------------------------------------------------------------
# transport 边界：生产实现包一个受支持的 MCP 客户端库；
# 测试注入 fake transport，绝不真实出网。
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    description: str
    input_schema: dict[str, Any] | None


@dataclass(frozen=True)
class RawToolResult:
    is_error: bool
    payload_text: str | None
    structured_content: Any = None


class McpTransportError(RuntimeError):
    """transport 层失败（连接/协议/超时）。reason 用于映射 failure class。"""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class McpSdkHttpTransport:
    """生产 transport：官方 MCP Python SDK Streamable HTTP 客户端。

    选型依据（ops/trendradar/QUALIFICATION.md §client-dependency）：
    - 首选 fastmcp-slim 仅发布 3.x（无与 pinned 服务端 fastmcp==2.12.5
      同代的 2.x 线），PyPI 解析实测 ``No matching distribution found``；
    - 服务端认证 venv 实证其依赖族为官方 ``mcp==1.16.0``；
    - 故按官方 SDK 客户端收口，Windows canonical 锁 pin ``mcp==1.16.0``。

    每次操作独立短连接（本地 sidecar 场景足够），sync 包装 async 实现，
    总deadline 由 asyncio.wait_for 统一强制（含取消语义）。
    """

    def __init__(self, config: GatewayConfig):
        self._config = config

    def _run(self, action_name: str, coro_factory: Callable[[Any], Any]) -> Any:
        import asyncio

        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
        except ModuleNotFoundError as exc:
            raise McpTransportError(
                "UNAVAILABLE",
                "official MCP client package not installed; "
                "install backend/requirements-trendradar*.lock.txt "
                f"({exc.name})",
            ) from exc

        async def _inner() -> Any:
            async with streamablehttp_client(self._config.mcp_url) as (
                read_stream,
                write_stream,
                _get_session_id,
            ):
                # MCP 协议要求先 initialize 才能发起任何请求；
                # 每次（连接, 操作）都是完整生命周期。
                async with ClientSession(read_stream, write_stream) as session:
                    initialize_result = await session.initialize()
                    return await coro_factory(session, initialize_result)

        try:
            return asyncio.run(
                asyncio.wait_for(_inner(), timeout=self._config.timeout_seconds)
            )
        except asyncio.TimeoutError as exc:
            raise McpTransportError("TIMEOUT", f"{action_name} timed out") from exc
        except OSError as exc:
            raise McpTransportError(
                "UNAVAILABLE", f"{action_name} connection failed: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 —— 客户端库异常族过宽，按 UNAVAILABLE 收敛
            raise McpTransportError(
                "UNAVAILABLE", f"{action_name} failed: {exc}"
            ) from exc

    def server_info(self) -> dict[str, Any] | None:
        async def _info(_session: Any, result: Any) -> dict[str, Any] | None:
            server = getattr(result, "serverInfo", None)
            if server is None:
                return None
            return {
                "server_name": str(getattr(server, "name", "")),
                "server_version": str(getattr(server, "version", "")),
                "protocol_version": str(getattr(result, "protocolVersion", "")),
            }

        return self._run("initialize", _info)

    def list_tools(self) -> list[ToolDescriptor]:
        async def _list(session: Any, _init: Any) -> list[ToolDescriptor]:
            result = await session.list_tools()
            descriptors = []
            for tool in getattr(result, "tools", None) or []:
                schema = getattr(tool, "inputSchema", None)
                descriptors.append(
                    ToolDescriptor(
                        name=str(tool.name),
                        description=str(tool.description or ""),
                        input_schema=schema if isinstance(schema, dict) else None,
                    )
                )
            return descriptors

        return self._run("tools/list", _list)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> RawToolResult:
        async def _call(session: Any, _init: Any) -> RawToolResult:
            result = await session.call_tool(name, arguments or {})
            texts = []
            for block in getattr(result, "content", None) or []:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    texts.append(text)
            structured = getattr(result, "structuredContent", None)
            return RawToolResult(
                is_error=bool(getattr(result, "isError", False)),
                payload_text="\n".join(texts) if texts else None,
                structured_content=structured if structured is not None else None,
            )

        return self._run(f"tools/call:{name}", _call)


def default_transport_factory(config: GatewayConfig) -> Any:
    return McpSdkHttpTransport(config)


# ---------------------------------------------------------------------------
# allow-list 语义（TR1-P1 起）：默认全拒；调用方必须显式传入
# allowed_names（trendradar_console.READ_TOOL_NAMES 是唯一的生产名单，
# 且永远不含 send_notification / trigger_crawl / sync_from_remote /
# read_article* 等外发或写类工具——见 console 模块注释）。


def _base_envelope(status: str, error: str | None = None) -> dict[str, Any]:
    if status not in ENVELOPE_STATUSES:
        raise AssertionError(f"unknown status {status!r}")
    envelope: dict[str, Any] = {
        "status": status,
        "retrieved_at": utc_now_iso(),
        "upstream": upstream_identity(),
    }
    if error is not None:
        envelope["error"] = error
    return envelope


def _transport_error_status(error: McpTransportError) -> str:
    return error.reason if error.reason in (STATUS_UNAVAILABLE, STATUS_TIMEOUT) \
        else STATUS_UNAVAILABLE


def _disabled_gateway_view() -> dict[str, Any]:
    return {"enabled": False, "mcp_url_host": None, "timeout_seconds": None}


def status_snapshot(
    env: dict[str, str] | None = None,
    transport_factory: Callable[[GatewayConfig], Any] = default_transport_factory,
) -> dict[str, Any]:
    """enable 态 + 上游身份 + （可达时）服务端自报身份。"""
    config, config_error = load_config(env)
    if config_error is not None:
        # 配置存在但非法：CONFIG_ERROR fail-closed（绝不静默当成未启用）。
        envelope = _base_envelope(STATUS_CONFIG_ERROR, config_error)
        envelope["gateway"] = _disabled_gateway_view()
        return envelope
    if config is None:
        envelope = _base_envelope(STATUS_DISABLED)
        envelope["gateway"] = _disabled_gateway_view()
        return envelope
    enabled_view = {
        "enabled": True,
        "mcp_url_host": config.host,
        "timeout_seconds": config.timeout_seconds,
    }
    try:
        transport = transport_factory(config)
        server_info = getattr(transport, "server_info", lambda: None)()
    except McpTransportError as exc:
        envelope = _base_envelope(_transport_error_status(exc), exc.detail)
        envelope["gateway"] = enabled_view
        return envelope
    envelope = _base_envelope(STATUS_OK)
    envelope["gateway"] = enabled_view
    envelope["server"] = server_info if isinstance(server_info, dict) else None
    return envelope


def tool_inventory(
    env: dict[str, str] | None = None,
    transport_factory: Callable[[GatewayConfig], Any] = default_transport_factory,
) -> dict[str, Any]:
    """strict tools/list 发现（只在 enabled 且可达时返回工具清单）。"""
    config, config_error = load_config(env)
    if config_error is not None:
        return _base_envelope(STATUS_CONFIG_ERROR, config_error)
    if config is None:
        return _base_envelope(STATUS_DISABLED)
    try:
        tools = transport_factory(config).list_tools()
    except McpTransportError as exc:
        return _base_envelope(_transport_error_status(exc), exc.detail)
    envelope = _base_envelope(STATUS_OK)
    envelope["tools"] = [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in tools
    ]
    # inventory 只报告发现结果；allow 名单属调用方（console），不在此泄露/声称。
    envelope["tool_count"] = len(tools)
    return envelope


def call_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    allowed_names: frozenset[str],
    env: dict[str, str] | None = None,
    transport_factory: Callable[[GatewayConfig], Any] = default_transport_factory,
) -> dict[str, Any]:
    """strict allow-listed tool 调用（默认拒绝：allowed_names 必须显式给出）。"""
    config, config_error = load_config(env)
    if config_error is not None:
        return _base_envelope(STATUS_CONFIG_ERROR, config_error)
    if config is None:
        return _base_envelope(STATUS_DISABLED)
    if type(allowed_names) is not frozenset:
        return _base_envelope(STATUS_BAD_ARGUMENT, "allowed_names must be a frozenset")
    if type(name) is not str or name not in allowed_names:
        return _base_envelope(
            STATUS_BAD_ARGUMENT,
            f"tool {name!r} is not in the TrendRadar allow-list",
        )
    if type(arguments) is not dict:
        return _base_envelope(STATUS_BAD_ARGUMENT, "arguments must be an object")
    try:
        raw = transport_factory(config).call_tool(name, arguments)
    except McpTransportError as exc:
        return _base_envelope(_transport_error_status(exc), exc.detail)
    envelope = _base_envelope(
        STATUS_UPSTREAM_ERROR if raw.is_error else STATUS_OK,
        raw.payload_text if raw.is_error else None,
    )
    envelope["tool"] = name
    if raw.structured_content is not None:
        envelope["result"] = raw.structured_content
    elif raw.payload_text is not None:
        envelope["result_text"] = raw.payload_text
    return envelope
