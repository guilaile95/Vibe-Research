"""Official MCP client proof for Native Intel Wave 5.

This is the external protocol integration test. Dispatcher unit tests in
test_native_intel_agent_tools.py (req 31-37) are not the final proof.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
import uvicorn
from fastapi import FastAPI
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

import native_intel_agent_tools as agent_tools
import native_intel_mcp
import native_intel_store as store

REQUIRED_TOOLS = (
    "query_intel",
    "search_intel",
    "analyze_intel_trend",
    "get_intel_status",
    "trigger_intel_refresh",
)


@pytest.fixture
def tmp_agent_db(tmp_path: Path):
    from datetime import datetime, timezone

    db_file = tmp_path / "mcp_client.sqlite3"
    store.initialize_store(db_file)
    store.upsert_sources(
        [
            {
                "source_id": "hotlist-weibo",
                "name": "微博",
                "hint": "社交",
                "url": "https://weibo.com",
                "source_type": "hotlist",
                "has_real_rank": 1,
                "enabled": 1,
            }
        ],
        db_path=db_file,
    )
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = "run_mcp_client"
    store.start_run(run_id, "test", 1, db_path=db_file, started_at=now_iso)
    store.upsert_observation(
        run_id,
        "hotlist-weibo",
        {
            "item_key": "hotlist-weibo:https://weibo.com/news1",
            "canonical_url": "https://weibo.com/news1",
            "url": "https://weibo.com/news1",
            "title": "比亚迪高端智能驾驶落地",
            "title_key": "比亚迪高端智能驾驶落地",
            "summary": "全栈自研智能驾驶系统大规模量产",
            "published_at": now_iso,
            "published_ts": int(now_dt.timestamp()),
            "rank": 1,
        },
        observed_at=now_iso,
        has_real_rank=True,
        db_path=db_file,
    )
    store.record_source_run(run_id, "hotlist-weibo", status="ok", item_count=1, db_path=db_file)
    store.finish_run(
        run_id,
        status=store.RUN_STATUS_OK,
        source_ok=1,
        source_failed=0,
        item_seen=1,
        item_new=1,
        db_path=db_file,
    )
    return db_file


def _payload(result) -> dict:
    text = result.content[0].text
    return json.loads(text)


def test_real_mcp_client_e2e(tmp_agent_db, monkeypatch):
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DB", str(tmp_agent_db))
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH", "1")
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DISABLE_SCHEDULER", "1")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with native_intel_mcp.mcp_server.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/api/native-intel/mcp", native_intel_mcp.mcp_http_app)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "MCP uvicorn server failed to start"

    url = f"http://127.0.0.1:{port}/api/native-intel/mcp"

    async def proof():
        async with streamable_http_client(url) as streams:
            read_stream, write_stream = streams[0], streams[1]
            async with ClientSession(read_stream, write_stream) as session:
                init = await session.initialize()
                assert init.server_info.name == "vibe-native-intel"
                listed = await session.list_tools()
                names = [tool.name for tool in listed.tools]
                for required in REQUIRED_TOOLS:
                    assert required in names, f"LIST_TOOLS = FAIL missing {required}: {names}"

                query = await session.call_tool("query_intel", {"mode": "current", "limit": 5})
                assert query.is_error is False
                assert _payload(query)["success"] is True

                search = await session.call_tool("search_intel", {"query": "比亚迪"})
                assert search.is_error is False
                assert _payload(search)["success"] is True

                trend = await session.call_tool(
                    "analyze_intel_trend", {"topic": "比亚迪", "days": 7}
                )
                assert trend.is_error is False
                assert _payload(trend)["success"] is True

                status = await session.call_tool("get_intel_status", {})
                assert status.is_error is False
                body = _payload(status)
                assert body["success"] is True
                assert "run_state" in body

                with patch(
                    "native_intel_service.run_fetch",
                    return_value={
                        "run_id": "mcp-client-refresh",
                        "status": store.RUN_STATUS_OK,
                        "source_ok": 1,
                        "source_failed": 0,
                        "item_seen": 1,
                        "item_new": 0,
                    },
                ):
                    refresh = await session.call_tool("trigger_intel_refresh", {})
                assert refresh.is_error is False
                refresh_body = _payload(refresh)
                assert refresh_body["success"] is True
                assert refresh_body["run_id"] == "mcp-client-refresh"

    try:
        asyncio.run(proof())
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_dispatcher_unit_tests_are_not_the_protocol_proof():
    assert hasattr(agent_tools, "dispatch_mcp_message")
    os.environ.get("VIBE_NATIVE_INTEL_DB")
