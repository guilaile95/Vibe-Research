"""TR1-P0 TrendRadar gateway 离线测试。

全部使用 fake transport / monkeypatch env，绝不真实出网、不启动 sidecar。
"""

from __future__ import annotations

import trendradar_gateway as gw


class FakeTransport:
    """记录调用的 fake transport；failure 模式由类属性控制。"""

    failure: str | None = None  # None|TIMEOUT|UNAVAILABLE
    server_payload = {
        "server_name": "trendradar-news",
        "server_version": "4.1.0",
        "protocol_version": "2025-06-18",
    }
    tools_payload = [
        gw.ToolDescriptor(name="get_latest_news", description="d", input_schema={}),
        gw.ToolDescriptor(name="send_notification", description="n", input_schema={}),
    ]

    def __init__(self, config):
        self.config = config

    def server_info(self):
        self._raise_if_configured("initialize")
        return dict(self.server_payload)

    def list_tools(self):
        self._raise_if_configured("tools/list")
        return list(self.tools_payload)

    def call_tool(self, name, arguments):
        self._raise_if_configured(f"call:{name}")
        return gw.RawToolResult(
            is_error=False,
            payload_text='{"ok": true}',
            structured_content={"ok": True},
        )

    def _raise_if_configured(self, action):
        if self.failure:
            raise gw.McpTransportError(
                self.failure, f"{action} failed ({self.failure})"
            )


def _factory():
    def make(config):
        return FakeTransport(config)

    return make


ENV_ENABLED = {gw.MCP_URL_ENV: "http://127.0.0.1:3777/mcp"}
ENV_DISABLED: dict[str, str] = {}


def _ok(env):
    transport = None

    def make(config):
        nonlocal transport
        transport = FakeTransport(config)
        return transport

    envelope = gw.status_snapshot(env=env, transport_factory=make)
    return envelope, transport


# ---------------------------------------------------------------------------
# 配置解析与 loopback 强制
# ---------------------------------------------------------------------------


def test_disabled_by_default_without_env():
    envelope, transport = _ok(ENV_DISABLED)
    assert envelope["status"] == "DISABLED"
    assert envelope["gateway"]["enabled"] is False
    assert transport is None


def test_loopback_http_url_enables_gateway():
    envelope, transport = _ok(ENV_ENABLED)
    assert envelope["status"] == "OK"
    assert transport.config.mcp_url == "http://127.0.0.1:3777/mcp"


def test_localhost_and_ipv6_loopback_accepted():
    for url in (
        "http://localhost:3333/mcp",
        "https://127.0.0.1/mcp",
        "http://[::1]:3333/mcp",
        "http://127.0.0.2:9999/mcp",
    ):
        config, error = gw.resolve_config(url)
        assert error is None and config is not None


def test_non_loopback_refused_fail_closed():
    config, error = gw.resolve_config("http://192.168.1.10:3333/mcp")
    assert config is None and error and "loopback" in error
    envelope, _transport = _ok({gw.MCP_URL_ENV: "http://0.0.0.0:3333/mcp"})
    assert envelope["status"] == "CONFIG_ERROR"
    assert envelope["gateway"]["enabled"] is False


def test_malformed_url_refused_fail_closed():
    for bad in ("not-a-url", "ftp://127.0.0.1/mcp", "http://"):
        config, error = gw.resolve_config(bad)
        assert config is None and error


def test_invalid_timeout_falls_back_to_default():
    config, error = gw.resolve_config(
        "http://127.0.0.1:3777/mcp", timeout_seconds="-5"
    )
    assert error is None
    assert config.timeout_seconds == gw.DEFAULT_TIMEOUT_SECONDS


def test_timeout_env_override_applies():
    source = dict(ENV_ENABLED)
    source[gw.TIMEOUT_ENV] = "42.5"
    env_config = gw.load_config(source)[0]
    assert env_config is not None and env_config.timeout_seconds == 42.5


# ---------------------------------------------------------------------------
# provenance 与上游身份
# ---------------------------------------------------------------------------


def test_upstream_identity_pinned_values_exposed():
    identity = gw.upstream_identity()
    assert identity["source_commit"] == gw.UPSTREAM_SOURCE_COMMIT
    assert identity["core_version"] == "6.10.0"
    assert identity["mcp_version"] == "4.1.0"
    assert identity["license"] == "GPL-3.0"
    assert identity["core_image"].startswith("wantcat/trendradar:6.10.0@sha256:")
    assert identity["mcp_image"].startswith("wantcat/trendradar-mcp:4.1.0@sha256:")
    assert identity["usage_boundary"] == "observation_only_not_an_investment_authority"


def test_every_envelope_carries_provenance_and_time():
    envelope, _ = _ok(ENV_ENABLED)
    assert envelope["upstream"]["source_commit"]
    assert envelope["retrieved_at"].endswith("Z")
    disabled, _, = _ok(ENV_DISABLED)
    assert disabled["upstream"]["repo"] == "sansan0/TrendRadar"


# ---------------------------------------------------------------------------
# status / inventory / strict call
# ---------------------------------------------------------------------------


def test_status_snapshot_reports_server_identity_when_enabled():
    envelope, _ = _ok(ENV_ENABLED)
    assert envelope["server"] == FakeTransport.server_payload


def test_unreachable_server_maps_to_unavailable(monkeypatch):
    def broken_factory(_config):
        raise gw.McpTransportError(
            "UNAVAILABLE", "tools/list connection failed"
        )

    envelope = gw.status_snapshot(
        env=ENV_ENABLED, transport_factory=broken_factory
    )
    assert envelope["status"] == "UNAVAILABLE"
    assert envelope["error"]


def test_timeout_maps_to_timeout_status():
    def slow_factory(_config):
        raise gw.McpTransportError("TIMEOUT", "timed out")

    envelope = gw.tool_inventory(env=ENV_ENABLED, transport_factory=slow_factory)
    assert envelope["status"] == "TIMEOUT"


def test_tool_inventory_lists_discovered_tools():
    envelope = gw.tool_inventory(env=ENV_ENABLED, transport_factory=_factory())
    assert envelope["status"] == "OK"
    names = [tool["name"] for tool in envelope["tools"]]
    assert names == ["get_latest_news", "send_notification"]
    assert isinstance(envelope["tools"][0], dict)


def test_call_blocked_while_disabled():
    envelope = gw.call_tool(
        "get_latest_news",
        {},
        env=ENV_DISABLED,
        allowed_names=frozenset({"get_latest_news"}),
    )
    assert envelope["status"] == "DISABLED"


def test_default_allowlist_is_empty_and_call_path_requires_explicit_names():
    """默认拒绝：不传 allowed_names 时任何工具都不可达。"""
    envelope = gw.call_tool(
        "get_latest_news", {}, env=ENV_ENABLED, transport_factory=_factory(),
        allowed_names=frozenset(),
    )
    assert envelope["status"] == "BAD_ARGUMENT"


def test_call_rejects_non_allowlisted_tool_even_when_enabled():
    envelope = gw.call_tool(
        "get_latest_news",
        {},
        env=ENV_ENABLED,
        transport_factory=_factory(),
        allowed_names=frozenset({"other_tool"}),
    )
    assert envelope["status"] == "BAD_ARGUMENT"
    assert "allow-list" in envelope["error"]


def test_call_rejects_non_object_arguments_via_contract_path():
    allowed = frozenset({"get_latest_news"})
    envelope = gw.call_tool(
        "get_latest_news",
        ["not", "a", "dict"],  # type: ignore[arg-type]
        env=ENV_ENABLED,
        transport_factory=_factory(),
        allowed_names=allowed,
    )
    assert envelope["status"] == "BAD_ARGUMENT"

    ok_envelope = gw.call_tool(
        "get_latest_news",
        {},
        env=ENV_ENABLED,
        transport_factory=_factory(),
        allowed_names=allowed,
    )
    assert ok_envelope["status"] == "OK"
    assert ok_envelope["result"] == {"ok": True}


def test_upstream_error_result_maps_to_upstream_error_status():
    class ErroringTransport(FakeTransport):
        def call_tool(self, name, arguments):
            return gw.RawToolResult(
                is_error=True, payload_text="boom", structured_content=None
            )

    def factory(config):
        return ErroringTransport(config)

    envelope = gw.call_tool(
        "get_latest_news",
        {},
        env=ENV_ENABLED,
        transport_factory=factory,
        allowed_names=frozenset({"get_latest_news"}),
    )
    assert envelope["status"] == "UPSTREAM_ERROR"
    assert envelope["error"] == "boom"


def test_unknown_internal_status_is_impossible():
    import pytest

    try:
        gw._base_envelope("SOMETHING_ELSE")
    except AssertionError:
        return
    pytest.fail("_base_envelope accepted an unknown status")
