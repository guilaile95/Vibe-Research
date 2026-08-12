"""P0-SEC1 本地 API 访问边界测试（全部离线，不联网）。

覆盖（对应任务 §28 A–P + R1 服务端 Origin gate）：
- 默认 CORS 白名单 = 官方本地前端 Origin；通配符 * 不是默认，显式配置 * / 空 / 畸形值 fail closed；
- 服务端 Origin gate：evil Origin 在路由执行前 403（handler 不被调用，不只检查 ACAO）；
- 缺 Origin（非浏览器客户端）/ 白名单 / same-origin → 放行；
- 本地前端 GET/POST/PUT/PATCH/DELETE 工作流不被破坏；
- 配置 key 三态：缺 key 401 / 错 key 401 / 对 key 放行，且 token 永不回显；
- /api/health 匿名豁免且不含私有数据；preflight 两态；
- 非 loopback 绑定 + 无 key → 全部请求 503；VR_HOST 声明非 loopback + 无 key → 启动失败；
- Host gate：拒绝未知 Host，放行 localhost/127.0.0.1/[::1]/VR_TRUSTED_HOSTS/缺失。
"""
import base64
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

import app as app_module

client = TestClient(app_module.app)

_BACKEND_DIR = os.path.dirname(os.path.abspath(app_module.__file__))
_LOCAL_ORIGIN = "http://localhost:5899"
_LOCAL_ORIGIN_127 = "http://127.0.0.1:5899"


# ── A/C：默认 Origin 白名单，通配符不是默认 ──────────────────────────────

def test_default_allowed_origins_are_local_frontend_only():
    assert app_module._ALLOWED_ORIGINS == [_LOCAL_ORIGIN, _LOCAL_ORIGIN_127]
    assert "*" not in app_module._ALLOWED_ORIGINS


def test_default_origin_localhost_allowed():
    r = client.get("/api/health", headers={"Origin": _LOCAL_ORIGIN})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == _LOCAL_ORIGIN


def test_default_origin_127_allowed():
    r = client.get("/api/health", headers={"Origin": _LOCAL_ORIGIN_127})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == _LOCAL_ORIGIN_127


# ── B：evil Origin 在路由执行前拒绝（HANDLER_NOT_CALLED 证明） ──────────

def test_evil_origin_read_rejected_before_handler(monkeypatch):
    calls = {"n": 0}

    def spy():
        calls["n"] += 1
        return {"holdings": []}

    monkeypatch.setattr(app_module.pf, "get_portfolio", spy)
    r = client.get("/api/portfolio", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert r.json()["detail"] == "Origin not allowed"
    assert calls["n"] == 0                    # 路由未执行
    assert r.headers.get("access-control-allow-origin") is None
    assert "evil.example" not in r.text       # 不反射 hostile Origin


def test_evil_origin_simple_post_rejected_before_handler(monkeypatch):
    calls = {"n": 0}
    real = app_module.newsradar.fetch_radar

    def spy():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(app_module.newsradar, "fetch_radar", spy)
    r = client.post("/api/radar/refresh", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert calls["n"] == 0                    # simple POST 同样不执行路由
    assert r.headers.get("access-control-allow-origin") is None
    assert "evil.example" not in r.text


# ── A/C：缺 Origin（非浏览器客户端）与 same-origin ───────────────────────

def test_no_origin_header_local_client_allowed(monkeypatch):
    calls = {"n": 0}

    def spy():
        calls["n"] += 1
        return {"holdings": []}

    monkeypatch.setattr(app_module.pf, "get_portfolio", spy)
    r = client.get("/api/portfolio")          # 无 Origin 头（curl/本地脚本）
    assert r.status_code == 200
    assert calls["n"] == 1


def test_same_origin_backend_request_allowed(monkeypatch):
    calls = {"n": 0}

    def spy():
        calls["n"] += 1
        return {"holdings": []}

    monkeypatch.setattr(app_module.pf, "get_portfolio", spy)
    # TestClient Host=testserver → Origin http://testserver 为 same-origin
    r = client.post("/api/portfolio/refresh", headers={"Origin": "http://testserver"})
    assert r.status_code == 200
    assert calls["n"] == 1


def test_same_origin_with_explicit_port_allowed(monkeypatch):
    monkeypatch.setattr(app_module.pf, "get_portfolio", lambda: {"holdings": []})
    r = client.post(
        "/api/portfolio/refresh",
        headers={"Origin": "http://localhost:8900", "host": "localhost:8900"},
    )
    assert r.status_code == 200


def test_origin_port_mismatch_rejected(monkeypatch):
    monkeypatch.setattr(app_module.pf, "get_portfolio", lambda: {"holdings": []})
    r = client.post(
        "/api/portfolio/refresh",
        headers={"Origin": "http://localhost:9999", "host": "localhost:8900"},
    )
    assert r.status_code == 403


def test_origin_allowed_helper():
    f = app_module._origin_allowed
    assert f("", "testserver", "http") is True                     # 缺 Origin
    assert f("http://localhost:5899", "testserver", "http") is True  # 白名单
    assert f("http://127.0.0.1:5899", "testserver", "http") is True  # 白名单
    assert f("http://testserver", "testserver", "http") is True      # same-origin
    assert f("http://testserver", "testserver:80", "http") is True   # 默认端口归一
    assert f("https://evil.example", "testserver", "http") is False
    assert f("null", "testserver", "http") is False


# ── K/C：畸形 / 通配配置 fail closed ─────────────────────────────────────

def test_parse_origins_rejects_wildcard_and_malformed():
    for bad in (
        "*",
        "http://ok.example,*",
        "null",
        "not-an-origin",
        "ftp://a.com",
        "http://a.com/path",
        "http://a.com?q=1",
        "http://user@a.com",
        "https://a.com#frag",
    ):
        with pytest.raises(RuntimeError):
            app_module._parse_origins(bad)


def test_parse_origins_empty_fails_closed():
    with pytest.raises(RuntimeError):
        app_module._parse_origins("")


def test_parse_origins_valid_values():
    assert app_module._parse_origins("https://myhost") == ["https://myhost"]
    assert app_module._parse_origins("https://myhost:8443, http://other") == [
        "https://myhost:8443",
        "http://other",
    ]
    assert app_module._parse_origins("HTTPS://MyHost/") == ["https://myhost"]


def _subprocess_env(extra: dict[str, str]) -> dict[str, str]:
    """子进程环境：显式注入 backend 目录到 PYTHONPATH，不依赖子进程 cwd 解析。"""
    env = {**os.environ, **extra}
    env["PYTHONPATH"] = _BACKEND_DIR + os.pathsep + env.get("PYTHONPATH", "")
    return env


def test_import_with_wildcard_env_fails_closed():
    proc = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=_BACKEND_DIR,
        env=_subprocess_env({"VR_ALLOW_ORIGINS": "*"}),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode != 0
    assert "VR_ALLOW_ORIGINS" in proc.stderr


def test_import_with_valid_origins_env_ok():
    proc = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=_BACKEND_DIR,
        env=_subprocess_env({"VR_ALLOW_ORIGINS": "https://myhost"}),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr


def test_parse_trusted_hosts_rejects_malformed():
    for bad in ("evil.com:8080", "http://evil.com", "bad host", "a/b", "user@host"):
        with pytest.raises(RuntimeError):
            app_module._parse_trusted_hosts(bad)


def test_parse_trusted_hosts_valid_values():
    assert app_module._parse_trusted_hosts("vrhost.lan, api.local") == {"vrhost.lan", "api.local"}


def test_parse_bind_host():
    assert app_module._parse_bind_host("127.0.0.1") == "127.0.0.1"
    assert app_module._parse_bind_host("[::1]") == "::1"
    assert app_module._parse_bind_host("LOCALHOST") == "localhost"
    for bad in ("http://x", "0.0.0.0:8000", "", "bad host", "a/b"):
        with pytest.raises(RuntimeError):
            app_module._parse_bind_host(bad)


# ── D：本地前端工作流不被破坏（GET/POST/PUT/PATCH/DELETE 均带 ACAO） ─────

def test_local_frontend_crud_workflow_with_cors(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.mr, "REPORTS_DIR", tmp_path / "myreports")
    b64 = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 x").decode()
    origin = {"Origin": _LOCAL_ORIGIN}

    r = client.post("/api/myreports", json={"name": "sec.pdf", "content_b64": b64}, headers=origin)
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == _LOCAL_ORIGIN
    rid = r.json()["data"]["id"]
    try:
        rg = client.get(f"/api/myreports/file/{rid}", headers=origin)
        assert rg.status_code == 200
        assert rg.headers.get("access-control-allow-origin") == _LOCAL_ORIGIN
        rp = client.patch(f"/api/myreports/{rid}", json={"title": "t"}, headers=origin)
        assert rp.status_code == 200
        assert rp.headers.get("access-control-allow-origin") == _LOCAL_ORIGIN
    finally:
        rd = client.delete(f"/api/myreports/{rid}", headers=origin)
        assert rd.status_code == 200
        assert rd.headers.get("access-control-allow-origin") == _LOCAL_ORIGIN


@pytest.fixture()
def tmp_pf(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.pf, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(app_module.pf, "PF_FILE", str(tmp_path / "portfolio.json"))
    monkeypatch.setattr(
        app_module.astock, "tencent_quote", lambda codes: {c: {"name": "股", "price": 10.0} for c in codes}
    )


def test_local_frontend_put_workflow_with_cors(tmp_pf):
    origin = {"Origin": _LOCAL_ORIGIN_127}
    r = client.post("/api/portfolio/holding", json={"code": "600519", "shares": 100, "cost": 8.0}, headers=origin)
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == _LOCAL_ORIGIN_127
    try:
        r2 = client.put("/api/portfolio/holding", json={"code": "600519", "shares": 200, "cost": 9.0}, headers=origin)
        assert r2.status_code == 200
        assert r2.headers.get("access-control-allow-origin") == _LOCAL_ORIGIN_127
    finally:
        client.request("DELETE", "/api/portfolio/holding", params={"code": "600519"})


# ── E/F/G：配置 key 三态 ─────────────────────────────────────────────────

def test_configured_key_missing_rejected(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "sekret")
    assert client.get("/api/portfolio").status_code == 401


def test_configured_key_wrong_rejected(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "sekret")
    r = client.get("/api/portfolio", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_configured_key_correct_accepted(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "sekret")
    r = client.get("/api/quote", params={"codes": "abc"}, headers={"Authorization": "Bearer sekret"})
    assert r.status_code != 401


def test_configured_key_blocks_all_private_methods(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "sekret")
    assert client.post("/api/myreports", json={}).status_code == 401
    assert client.put("/api/portfolio/holding", json={}).status_code == 401
    assert client.patch("/api/myreports/x", json={}).status_code == 401
    assert client.delete("/api/myreports/x").status_code == 401


# ── H/I：health 匿名豁免且不含私有数据 ───────────────────────────────────

def test_health_anonymous_allowed_with_key(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "sekret")
    assert client.get("/api/health").status_code == 200


def test_health_does_not_expose_private_data():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert set(r.json()) == {"ok", "service", "version"}
    body = r.text.lower()
    for needle in ("secret", "token", "password", "account", "portfolio", "path", "dir", "sqlite"):
        assert needle not in body


def test_evil_origin_blocked_from_health():
    """evil Origin 的浏览器请求连 health 都拿不到（无 CORS 可读性）。"""
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert r.headers.get("access-control-allow-origin") is None


def test_no_routes_outside_api_prefix():
    # 仅统计业务路由（APIRoute）：/docs、/openapi.json 等框架自带路由不参与判定
    from fastapi.routing import APIRoute

    extra = [
        route.path
        for route in app_module.app.routes
        if isinstance(route, APIRoute) and not route.path.startswith("/api")
    ]
    assert extra == []


# ── J：非 loopback 矩阵 ──────────────────────────────────────────────────

def test_non_loopback_without_key_fails_closed():
    remote = TestClient(app_module.app, base_url="http://192.168.1.5/")
    r = remote.get("/api/portfolio")
    assert r.status_code == 503
    assert "VR_API_KEY" in r.json()["detail"]
    # 整个部署 fail closed：health 也不得伪装健康
    assert remote.get("/api/health").status_code == 503


def test_non_loopback_with_key_allowed(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "sekret")
    monkeypatch.setattr(app_module, "_ALLOWED_HOSTS", app_module._ALLOWED_HOSTS | {"192.168.1.5"})
    remote = TestClient(app_module.app, base_url="http://192.168.1.5/")
    r = remote.get("/api/health", headers={"Authorization": "Bearer sekret"})
    assert r.status_code == 200


# ── J：VR_HOST 启动 fail-closed ──────────────────────────────────────────

def test_vr_host_non_loopback_without_key_startup_fails(monkeypatch):
    monkeypatch.setenv("VR_HOST", "0.0.0.0")
    monkeypatch.setattr(app_module, "_API_KEY", "")
    monkeypatch.setattr(app_module.pf, "start_scheduler", lambda interval: None)
    with pytest.raises(RuntimeError):
        with TestClient(app_module.app):
            pass


def test_vr_host_loopback_without_key_startup_ok(monkeypatch):
    monkeypatch.setenv("VR_HOST", "127.0.0.1")
    monkeypatch.setattr(app_module, "_API_KEY", "")
    monkeypatch.setattr(app_module.pf, "start_scheduler", lambda interval: None)
    with TestClient(app_module.app):
        pass


def test_vr_host_non_loopback_with_key_startup_ok(monkeypatch):
    monkeypatch.setenv("VR_HOST", "0.0.0.0")
    monkeypatch.setattr(app_module, "_API_KEY", "sekret")
    monkeypatch.setattr(app_module.pf, "start_scheduler", lambda interval: None)
    with TestClient(app_module.app):
        pass


# ── L/M：CORS preflight 两态 ─────────────────────────────────────────────

def test_preflight_allowed_origin():
    r = client.options(
        "/api/portfolio",
        headers={"Origin": _LOCAL_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == _LOCAL_ORIGIN


def test_preflight_evil_origin_not_permissive():
    r = client.options(
        "/api/portfolio",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code >= 400
    assert r.headers.get("access-control-allow-origin") is None


def test_preflight_with_configured_key_exempt(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "sekret")
    r = client.options(
        "/api/portfolio",
        headers={"Origin": _LOCAL_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 200


# ── N：token 永不回显 ────────────────────────────────────────────────────

def test_token_never_echoed(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "supersecretkey")
    r = client.get("/api/portfolio", headers={"Authorization": "Bearer attacker-token"})
    assert r.status_code == 401
    body = r.text
    assert "attacker-token" not in body
    assert "supersecretkey" not in body
    assert "Bearer" not in body


# ── Host gate ────────────────────────────────────────────────────────────

def test_host_gate_rejects_unknown_host():
    r = client.get("/api/health", headers={"host": "evil.example"})
    assert r.status_code == 400
    assert "evil.example" not in r.text  # 不反射原值


def test_host_gate_accepts_local_hosts():
    for h in ("localhost", "127.0.0.1", "[::1]", "localhost:8900", "127.0.0.1:8900", "[::1]:8900"):
        r = client.get("/api/health", headers={"host": h})
        assert r.status_code == 200, h


def test_host_gate_trusted_extra_host(monkeypatch):
    monkeypatch.setattr(app_module, "_ALLOWED_HOSTS", app_module._ALLOWED_HOSTS | {"vrhost.lan"})
    assert client.get("/api/health", headers={"host": "vrhost.lan"}).status_code == 200


def test_missing_host_header_passes_gate():
    """原始 ASGI 直调（无 Host 头）不触发 Host gate：缺 Host 不构成 rebinding 攻击面。"""
    import asyncio

    async def exercise() -> int:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/health",
            "raw_path": b"/api/health",
            "query_string": b"",
            "root_path": "",
            "headers": [],  # 故意不带 Host
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 80),
            "state": {},
        }
        messages: list[dict] = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await app_module.app(scope, receive, send)
        return next(m["status"] for m in messages if m["type"] == "http.response.start")

    assert asyncio.run(exercise()) == 200
