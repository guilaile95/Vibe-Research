"""HR1 real-app vertical with synthetic public-provider boundaries.

Campaign/Thesis stores, production ports, capability adapters, Hard Risk,
Inbox router and projections are unchanged. This proves authority integration,
not live-provider reliability. No background scheduler or outbound network runs.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
import ipaddress
from pathlib import Path
import socket
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

NETWORK_ATTEMPTS: list[str] = []


def _check_address(address) -> None:
    # Unix-domain IPC and literal loopback are local-only.
    if not isinstance(address, tuple):
        return
    host = address[0]
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == "localhost"
    if not local:
        NETWORK_ATTEMPTS.append("outbound-connect")
        raise OSError("HR1 offline harness blocked outbound network")


_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex
_getaddrinfo = socket.getaddrinfo


def _offline_connect(self, address):
    _check_address(address)
    return _connect(self, address)


def _offline_connect_ex(self, address):
    _check_address(address)
    return _connect_ex(self, address)


def _offline_getaddrinfo(host, *args, **kwargs):
    if host is not None:
        _check_address((host, 0))
    return _getaddrinfo(host, *args, **kwargs)


socket.socket.connect = _offline_connect
socket.socket.connect_ex = _offline_connect_ex
socket.getaddrinfo = _offline_getaddrinfo

import app as app_module
import astock
import market
import research_continuity_service


def _unavailable(*args, **kwargs):
    raise RuntimeError("Synthetic HR1 public provider unavailable")


def _empty_calendar(code, fetched_at):
    return research_continuity_service.project_disclosure_calendar(
        [], as_of=datetime.now(ZoneInfo("Asia/Shanghai")).date(), fetched_at=fetched_at,
    )


# Fixture only external input boundaries; never replace Inbox/HR evaluators.
market.get_market_breadth = _unavailable
astock.announcements = _unavailable
astock.financials = _unavailable
astock.lockup_expiry = lambda *args, **kwargs: {"history": [], "upcoming": []}
astock.dividend_history = lambda *args, **kwargs: []
research_continuity_service._calendar = _empty_calendar


@asynccontextmanager
async def _offline_lifespan(app):
    # HR1 does not exercise background portfolio/Intel ingestion.
    yield


app = app_module.app
app.router.lifespan_context = _offline_lifespan


@app.get("/api/hr1-fixture-network-audit")
def network_audit():
    return {"data": {"mode": "SYNTHETIC_PUBLIC_PROVIDERS", "attempts": list(NETWORK_ATTEMPTS)}}
