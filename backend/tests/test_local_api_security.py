"""Local-private runtime security boundary tests (offline, fixture-only)."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

import app as app_module


client = TestClient(app_module.app)
_BACKEND_DIR = os.path.dirname(os.path.abspath(app_module.__file__))
_LOCALHOST_ORIGIN = "http://localhost:5899"
_LOOPBACK_IP_ORIGIN = "http://127.0.0.1:5899"


def _clean_subprocess_env(extra: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    for name in ("VR_ALLOW_ORIGINS", "VR_TRUSTED_HOSTS", "VR_API_KEY"):
        env.pop(name, None)
    env.update(extra)
    env["PYTHONPATH"] = _BACKEND_DIR + os.pathsep + env.get("PYTHONPATH", "")
    return env


def test_default_origins_are_only_supported_local_frontends():
    assert app_module._ALLOWED_ORIGINS == [_LOCALHOST_ORIGIN, _LOOPBACK_IP_ORIGIN]
    assert "*" not in app_module._ALLOWED_ORIGINS


@pytest.mark.parametrize("origin", [_LOCALHOST_ORIGIN, _LOOPBACK_IP_ORIGIN])
def test_supported_local_frontend_origin_has_cors_access(origin):
    response = client.get("/api/health", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin


def test_foreign_origin_is_rejected_before_private_handler(monkeypatch):
    calls = 0

    def spy():
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(app_module.pf, "get_portfolio", spy)
    response = client.get(
        "/api/portfolio",
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": app_module._ORIGIN_ERROR_DETAIL}
    assert response.headers.get("access-control-allow-origin") is None
    assert "evil.example" not in response.text
    assert calls == 0


@pytest.mark.parametrize(
    "origins",
    [
        (_LOCALHOST_ORIGIN, "https://evil.example"),
        ("https://evil.example", _LOCALHOST_ORIGIN),
    ],
)
def test_duplicate_origin_headers_fail_closed(origins):
    response = client.get(
        "/api/health",
        headers=[("Origin", origin) for origin in origins],
    )
    assert response.status_code == 403
    assert response.json() == {"detail": app_module._ORIGIN_ERROR_DETAIL}
    assert response.headers.get("access-control-allow-origin") is None


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "http://localhost:5899/",
        "HTTP://LOCALHOST:5899",
        "http://localhost:80",
        "http://user@localhost:5899",
        "http://localhost:5899?",
        "http://localhost:5899?query=1",
        "http://localhost:5899#",
    ],
)
def test_noncanonical_or_malformed_request_origin_fails_closed(origin):
    response = client.get("/api/health", headers={"Origin": origin})
    assert response.status_code == 403
    assert response.headers.get("access-control-allow-origin") is None


def test_no_origin_and_exact_same_origin_clients_remain_supported():
    assert client.get("/api/health").status_code == 200
    response = client.get(
        "/api/health",
        headers={"host": "localhost:8900", "Origin": "http://localhost:8900"},
    )
    assert response.status_code == 200


@pytest.mark.parametrize("origin", [_LOCALHOST_ORIGIN, _LOOPBACK_IP_ORIGIN])
def test_allowed_preflight_succeeds(origin):
    response = client.options(
        "/api/portfolio",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin


def test_foreign_preflight_fails_without_cors_access():
    response = client.options(
        "/api/portfolio",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code >= 400
    assert response.headers.get("access-control-allow-origin") is None


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " ",
        "*",
        "http://localhost:5899,*",
        "http://localhost:5899,",
        "http://localhost:5899,,https://example.com",
        "null",
        "localhost:5899",
        "ftp://example.com",
        "http://example.com/path",
        "http://user@example.com",
        "https://example.com?",
        "https://example.com?query=1",
        "https://example.com#",
        "https://example.com#fragment",
        "http://example.com:99999",
    ],
)
def test_origin_override_parser_rejects_wildcard_empty_and_malformed(raw):
    with pytest.raises(RuntimeError):
        app_module._parse_origins(raw)


def test_origin_override_parser_canonicalizes_and_deduplicates_valid_values():
    assert app_module._parse_origins(
        "HTTPS://Example.COM:443,http://127.0.0.1:5899,https://example.com"
    ) == ["https://example.com", "http://127.0.0.1:5899"]


@pytest.mark.parametrize("raw", ["", "*", "http://localhost:5899,"])
def test_invalid_origin_environment_fails_during_import(raw):
    process = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=_BACKEND_DIR,
        env=_clean_subprocess_env({"VR_ALLOW_ORIGINS": raw}),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert process.returncode != 0
    assert "VR_ALLOW_ORIGINS" in process.stderr


def test_valid_origin_environment_is_applied_during_import():
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app; print(','.join(app._ALLOWED_ORIGINS))",
        ],
        cwd=_BACKEND_DIR,
        env=_clean_subprocess_env(
            {"VR_ALLOW_ORIGINS": "https://frontend.example,http://localhost:5899"}
        ),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout.strip().endswith(
        "https://frontend.example,http://localhost:5899"
    )


@pytest.mark.parametrize(
    "raw",
    [
        "host.example:",
        "host.example:8900",
        "http://host.example",
        "host.example/path",
        "user@host.example",
        "host.example,,other.example",
        "*.example",
        "999.999.999.999",
    ],
)
def test_trusted_host_parser_rejects_malformed_values(raw):
    with pytest.raises(RuntimeError):
        app_module._parse_trusted_hosts(raw)


def test_trusted_host_parser_canonicalizes_valid_values():
    assert app_module._parse_trusted_hosts(
        "VRHOST.LAN,192.168.1.5,[2001:DB8::1]"
    ) == {"vrhost.lan", "192.168.1.5", "[2001:db8::1]"}


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "localhost:8900",
        "127.0.0.1",
        "127.0.0.1:8900",
        "[::1]",
        "[::1]:8900",
    ],
)
def test_host_gate_accepts_supported_loopback_hosts(host):
    assert client.get("/api/health", headers={"host": host}).status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        "",
        "evil.example",
        "evil.example:bad",
        "evil.example:99999",
        "[::1]evil",
        "[::1]:bad",
        "user@localhost",
        "localhost/path",
        "999.999.999.999",
    ],
)
def test_host_gate_rejects_missing_unknown_and_malformed_hosts(host):
    response = client.get("/api/health", headers={"host": host})
    assert response.status_code == 400
    assert response.json() == {"detail": app_module._HOST_ERROR_DETAIL}
    if host:
        assert host not in response.text


@pytest.mark.parametrize(
    "hosts",
    [
        ("localhost", "evil.example"),
        ("evil.example", "localhost"),
    ],
)
def test_duplicate_host_headers_fail_closed(hosts):
    response = client.get(
        "/api/health",
        headers=[("Host", host) for host in hosts],
    )
    assert response.status_code == 400
    assert response.json() == {"detail": app_module._HOST_ERROR_DETAIL}


def test_explicit_trusted_host_is_accepted(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_ALLOWED_HOSTS",
        app_module._ALLOWED_HOSTS | {"vibe.lan"},
    )
    response = client.get("/api/health", headers={"host": "VIBE.LAN:8900"})
    assert response.status_code == 200


def test_loopback_without_key_preserves_private_api_access(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "")
    response = client.get("/api/quote", params={"codes": "abc"})
    assert response.status_code == 400


def test_non_loopback_without_key_blocks_private_api_and_health(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "")
    remote = TestClient(app_module.app, base_url="http://192.168.1.5")
    for path in ("/api/quote?codes=abc", "/api/health"):
        response = remote.get(path)
        assert response.status_code == 503
        assert response.json() == {
            "detail": app_module._NON_LOOPBACK_NO_KEY_DETAIL
        }


def test_non_loopback_valid_key_reaches_private_api(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "sekret")
    monkeypatch.setattr(
        app_module,
        "_ALLOWED_HOSTS",
        app_module._ALLOWED_HOSTS | {"192.168.1.5"},
    )
    remote = TestClient(app_module.app, base_url="http://192.168.1.5")
    response = remote.get(
        "/api/quote",
        params={"codes": "abc"},
        headers={"Authorization": "Bearer sekret"},
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "authorizations",
    [
        ("Bearer server-secret", "Bearer wrong"),
        ("Bearer wrong", "Bearer server-secret"),
        ("Bearer server-secret", "Bearer server-secret"),
    ],
)
def test_duplicate_authorization_headers_fail_closed(monkeypatch, authorizations):
    monkeypatch.setattr(app_module, "_API_KEY", "server-secret")
    response = client.get(
        "/api/quote?codes=abc",
        headers=[("Authorization", value) for value in authorizations],
    )
    assert response.status_code == 401
    assert response.json() == {"detail": app_module._AUTH_ERROR_DETAIL}


@pytest.mark.parametrize("authorization", [None, "Bearer wrong"])
def test_non_loopback_missing_or_wrong_key_has_fixed_safe_error(
    monkeypatch,
    authorization,
):
    monkeypatch.setattr(app_module, "_API_KEY", "server-secret")
    monkeypatch.setattr(
        app_module,
        "_ALLOWED_HOSTS",
        app_module._ALLOWED_HOSTS | {"192.168.1.5"},
    )
    remote = TestClient(app_module.app, base_url="http://192.168.1.5")
    headers = {} if authorization is None else {"Authorization": authorization}
    response = remote.get("/api/portfolio", headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": app_module._AUTH_ERROR_DETAIL}
    assert response.headers.get("www-authenticate") == "Bearer"
    for secret in ("server-secret", "wrong"):
        assert secret not in response.text


def test_allowed_origin_can_read_fixed_authentication_error(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "server-secret")
    response = client.get(
        "/api/portfolio",
        headers={"Origin": _LOCALHOST_ORIGIN},
    )
    assert response.status_code == 401
    assert response.headers.get("access-control-allow-origin") == _LOCALHOST_ORIGIN
    assert response.json() == {"detail": app_module._AUTH_ERROR_DETAIL}


def test_health_is_intentionally_public_and_contains_only_fixed_metadata(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "server-secret")
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "service": "vibe-research-api",
        "version": "0.1.3",
    }
    body = response.text.lower()
    for needle in (
        "secret",
        "token",
        "password",
        "account",
        "portfolio",
        "thesis",
        "trade",
        "sqlite",
        "path",
        "dir",
        "traceback",
    ):
        assert needle not in body


def test_foreign_origin_cannot_read_public_health():
    response = client.get(
        "/api/health",
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.headers.get("access-control-allow-origin") is None
