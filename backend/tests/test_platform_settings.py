"""Offline settings contracts; no provider, release-server, or model activation."""
import json
import ipaddress
import socket
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import platform_settings as ps

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
RELEASE = {"draft": False, "prerelease": False, "tag_name": "v0.1.4", "published_at": "2026-10-11T12:00:00Z", "html_url": "https://evil.invalid/token", "body": "PRIVATE_FIXTURE"}


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("VR_SEC_CONTACT", raising=False)
    monkeypatch.setattr(ps, "_UPDATE", None)
    monkeypatch.setattr(ps, "read_version", lambda: "0.1.3")
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    getaddrinfo = socket.getaddrinfo
    create_connection = socket.create_connection
    def local(address):
        try:
            return isinstance(address, tuple) and ipaddress.ip_address(address[0]).is_loopback
        except ValueError:
            return False
    def guarded_connect(sock, address):
        # Windows ProactorEventLoop may create a local socketpair for TestClient.
        if sock.family == getattr(socket, "AF_UNIX", None) or local(address):
            return connect(sock, address)
        pytest.fail("outbound network attempted")
    def guarded_create(address, *args, **kwargs):
        if local(address):
            return create_connection(address, *args, **kwargs)
        pytest.fail("outbound network attempted")
    def guarded_connect_ex(sock, address):
        if sock.family == getattr(socket, "AF_UNIX", None) or local(address):
            return connect_ex(sock, address)
        pytest.fail("outbound network attempted")
    def guarded_dns(host, port, *args, **kwargs):
        if local((host, port)):
            return getaddrinfo(host, port, *args, **kwargs)
        pytest.fail("outbound DNS attempted")
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_dns)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create)


def client(host="127.0.0.1"):
    app = FastAPI()
    app.include_router(ps.router)
    return TestClient(app, client=(host, 12345), base_url="http://127.0.0.1")


def transport(body=RELEASE, status=200, headers=None):
    def handler(request):
        assert str(request.url) == ps.RELEASES_API
        assert request.method == "GET"
        assert "authorization" not in request.headers
        assert request.headers["user-agent"] == "Vibe-Research-Manual-Update-Check"
        assert "SYNTHETIC" not in str(request.headers)
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        return httpx.Response(status, stream=httpx.ByteStream(raw), headers=headers)
    def factory(**options):
        assert options == {"timeout": 5.0, "follow_redirects": False, "trust_env": False}
        return httpx.Client(transport=httpx.MockTransport(handler), **options)
    return factory


def test_status_is_readonly_private_and_no_outbound():
    c = client()
    response = c.get("/api/settings/platform")
    assert response.headers["cache-control"] == "no-store"
    data = response.json()["data"]
    assert data["sec_contact"] == {"source": "none", "configured": False, "revision": "absent", "editable": True}
    assert data["update"]["status"] == "not_checked"
    assert data["platforms"]["macos"] == "unsupported_launcher"
    assert not ps._path().exists()
    assert "source_directory" not in response.text


def test_contact_save_clear_and_conflict_without_transmission():
    c = client()
    saved = c.put("/api/settings/platform/sec-contact", json={"contact": "Synthetic User synthetic@example.invalid", "revision": "absent"})
    assert saved.status_code == 200
    status = saved.json()["data"]
    assert status["configured"] and status["revision"] != "absent"
    assert "synthetic@example" not in saved.text
    assert ps._read()["contact"] == "Synthetic User synthetic@example.invalid"
    assert c.get("/api/settings/platform").json()["data"]["sec_contact"] == status
    assert c.put("/api/settings/platform/sec-contact", json={"contact": "", "revision": "absent"}).status_code == 409
    assert c.put("/api/settings/platform/sec-contact", json={"contact": "", "revision": status["revision"]}).json()["data"]["configured"] is False


@pytest.mark.parametrize("contact", [None, 42, True, [], {}, "X x@a", "X x@a.invalid\r\nInjected: yes", "姓名 x@a.invalid", "A" * 201, "X https://a.invalid", "X x@a.invalid\t"])
def test_contact_exact_string_and_header_validation(contact):
    c = client()
    r = c.put("/api/settings/platform/sec-contact", json={"contact": contact, "revision": "absent"})
    assert r.status_code == 422
    assert not ps._path().exists()


def test_extra_fields_and_remote_write_rejected(monkeypatch):
    c = client("203.0.113.1")
    assert c.get("/api/settings/platform").json()["data"]["sec_contact"]["editable"] is False
    assert c.post("/api/settings/platform/check-update").status_code == 403
    assert c.put("/api/settings/platform/sec-contact", json={"contact": "", "revision": "absent"}).status_code == 403
    assert client().put("/api/settings/platform/sec-contact", json={"contact": "", "revision": "absent", "token": "SYNTHETIC"}).status_code == 422
    monkeypatch.setenv("VR_SEC_CONTACT", "Invalid\nSYNTHETIC_SECRET")
    r = client().get("/api/settings/platform")
    assert "SYNTHETIC_SECRET" not in r.text
    assert r.json()["data"]["sec_contact"] == {"source": "environment", "configured": False, "revision": "environment", "editable": False}
    assert client().put("/api/settings/platform/sec-contact", json={"contact": "", "revision": "environment"}).status_code == 403


def test_failed_write_preserves_previous_file_and_sanitizes(monkeypatch):
    c = client()
    before = c.put("/api/settings/platform/sec-contact", json={"contact": "Synthetic User synthetic@example.invalid", "revision": "absent"}).json()["data"]
    def fail(*args, **kwargs):
        raise OSError("SYNTHETIC_SECRET /private/owner/path")
    monkeypatch.setattr(ps.os, "replace", fail)
    r = c.put("/api/settings/platform/sec-contact", json={"contact": "Other User other@example.invalid", "revision": before["revision"]})
    assert r.status_code == 503 and "SYNTHETIC_SECRET" not in r.text and "/private" not in r.text
    assert ps._read()["contact"] == "Synthetic User synthetic@example.invalid"
    assert not list(ps._path().parent.glob("*.tmp"))


def test_corrupt_store_cannot_be_overwritten():
    path = ps._path()
    path.parent.mkdir(parents=True)
    path.write_text('{"schema":"wrong", "contact":"PRIVATE_FIXTURE"}')
    assert client().get("/api/settings/platform").status_code == 503
    r = client().put("/api/settings/platform/sec-contact", json={"contact": "", "revision": "absent"})
    assert r.status_code == 503 and "PRIVATE_FIXTURE" not in r.text


@pytest.mark.parametrize("tag,current,expected", [("v0.1.4", "0.1.3", "update_available"), ("0.1.3", "0.1.3", "current"), ("v0.1.2", "0.1.3", "ahead"), ("v1.10.0", "1.9.9", "update_available"), ("v1.0.0", "unknown", "current_unknown")])
def test_manual_release_strict_semantics(monkeypatch, tag, current, expected):
    monkeypatch.setattr(ps, "read_version", lambda: current)
    out = ps.check_update(client_factory=transport({**RELEASE, "tag_name": tag}), now=NOW)
    assert out["status"] == expected
    assert out["checked_at"] == "2026-10-12T12:00:00Z"
    assert out["latest"]["published_at"] == RELEASE["published_at"]
    assert out["latest"]["url"] == f"{ps.RELEASES_PAGE}/tag/{tag}"
    assert "PRIVATE_FIXTURE" not in str(out) and "evil.invalid" not in str(out)


@pytest.mark.parametrize("patch", [{"draft": True}, {"draft": 0}, {"prerelease": True}, {"tag_name": 123}, {"tag_name": "v01.2.3"}, {"tag_name": "v1.2.3\n"}, {"tag_name": "v1.2.3-rc1"}, {"published_at": "2026-10-13T00:00:00Z"}, {"published_at": "2026-02-30T00:00:00Z"}, {"published_at": "2026-1-2T00:00:00Z"}, {"published_at": None}])
def test_malformed_release_never_claims_current(patch):
    out = ps.check_update(client_factory=transport({**RELEASE, **patch}), now=NOW)
    assert out["status"] == "unavailable" and out["latest"] is None


@pytest.mark.parametrize("status,expected", [(404, "release_not_found"), (302, "unavailable"), (403, "unavailable"), (429, "unavailable"), (500, "unavailable")])
def test_http_failures_no_redirect(status, expected):
    assert ps.check_update(client_factory=transport(status=status, headers={"location": "https://evil.invalid/"}), now=NOW)["status"] == expected


@pytest.mark.parametrize("body,headers", [(b"x" * (ps.MAX_BODY + 1), {}), (b"not json PRIVATE_FIXTURE", {}), ([], {}), (RELEASE, {"content-encoding": "gzip"})], ids=["oversized-body", "invalid-json", "invalid-envelope", "compressed-body"])
def test_response_byte_cap_and_shape(body, headers):
    out = ps.check_update(client_factory=transport(body, headers=headers), now=NOW)
    assert out["status"] == "unavailable" and "PRIVATE_FIXTURE" not in str(out)


def test_manual_action_only_and_inflight_lock(monkeypatch):
    calls = []
    monkeypatch.setattr(ps, "check_update", lambda: calls.append(True) or ps.update_status())
    c = client()
    c.get("/api/settings/platform")
    assert calls == []
    assert c.post("/api/settings/platform/check-update").status_code == 200
    assert calls == [True]
    ps._CHECK_LOCK.acquire()
    try:
        assert c.post("/api/settings/platform/check-update").status_code == 409
    finally:
        ps._CHECK_LOCK.release()


@pytest.mark.parametrize("target", ["file", "parent"])
def test_symlink_settings_paths_are_rejected(tmp_path, target):
    path = ps._path()
    outside = tmp_path / "outside"
    outside.mkdir()
    if target == "parent":
        path.parent.symlink_to(outside, target_is_directory=True)
    else:
        path.parent.mkdir()
        other = outside / "file.json"
        other.write_text('{"private":"SYNTHETIC"}')
        path.symlink_to(other)
    assert client().get("/api/settings/platform").status_code == 503
    r = client().put("/api/settings/platform/sec-contact", json={"contact": "Synthetic User synthetic@example.invalid", "revision": "absent"})
    assert r.status_code == 503
    assert not (outside / "platform_settings.json").exists()


def test_reparse_semantics_rejected_before_read_or_write(monkeypatch):
    path = ps._path()
    path.parent.mkdir(parents=True)
    real = ps._is_link_or_reparse
    monkeypatch.setattr(ps, "_is_link_or_reparse", lambda p, info=None: p == path.parent or real(p, info))
    assert client().get("/api/settings/platform").status_code == 503
    assert client().put("/api/settings/platform/sec-contact", json={"contact": "", "revision": "absent"}).status_code == 503
    assert not path.exists()


@pytest.mark.skipif(ps.os.name == "nt", reason="POSIX adversarial parent rename; Windows denies deletion with held handles")
def test_parent_swap_cannot_redirect_write_and_cleans_temp(monkeypatch, tmp_path):
    path = ps._path()
    outside = tmp_path / "outside"
    outside.mkdir()
    moved = tmp_path / "moved"
    real = ps.os.fsync
    def swap(fd):
        real(fd)
        path.parent.rename(moved)
        path.parent.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(ps.os, "fsync", swap)
    r = client().put("/api/settings/platform/sec-contact", json={"contact": "Synthetic User synthetic@example.invalid", "revision": "absent"})
    assert r.status_code == 503
    assert list(outside.iterdir()) == [] and list(moved.iterdir()) == []


def test_external_target_change_before_replace_is_not_overwritten(monkeypatch):
    path = ps._path()
    real = ps.os.fsync
    def swap(fd):
        real(fd)
        path.write_text('{"external":"SYNTHETIC"}')
    monkeypatch.setattr(ps.os, "fsync", swap)
    r = client().put("/api/settings/platform/sec-contact", json={"contact": "Synthetic User synthetic@example.invalid", "revision": "absent"})
    assert r.status_code == 503 and path.read_text() == '{"external":"SYNTHETIC"}'
    assert not list(path.parent.glob("*.tmp"))


def test_remote_host_and_origin_cannot_be_treated_as_owner_local():
    c = client()
    for headers in ({"Host": "remote.example.invalid"}, {"Origin": "https://remote.example.invalid"}):
        assert c.get("/api/settings/platform", headers=headers).json()["data"]["sec_contact"]["editable"] is False
        assert c.put("/api/settings/platform/sec-contact", headers=headers, json={"contact": "", "revision": "absent"}).status_code == 403


def test_browser_startup_fixture_matches_real_route_without_write():
    from pathlib import Path
    expected = json.loads((Path(__file__).parents[2] / "frontend/tests/fixtures/platform-settings-startup.json").read_text(encoding="utf-8"))
    response = client().get("/api/settings/platform")
    assert response.status_code == 200
    assert response.json() == expected
    assert response.headers["cache-control"] == "no-store"
    assert not ps._path().exists()
    assert ps._UPDATE is None


def test_browser_workflow_goldens_match_actual_registered_routes(monkeypatch):
    from pathlib import Path
    expected = json.loads((Path(__file__).parents[2] / "frontend/tests/fixtures/platform-settings-workflow.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(ps.secrets, "token_hex", lambda n: "1".zfill(n * 2))
    c = client()
    saved = c.put("/api/settings/platform/sec-contact", json={"contact": "Synthetic User synthetic@example.invalid", "revision": "absent"})
    assert saved.status_code == 200 and saved.json()["data"] == expected["saved"]
    assert c.get("/api/settings/platform").json()["data"]["sec_contact"] == expected["saved"]
    conflict = c.put("/api/settings/platform/sec-contact", json={"contact": "", "revision": "absent"})
    assert conflict.status_code == 409
    original = ps.check_update
    monkeypatch.setattr(ps, "check_update", lambda: original(client_factory=transport(), now=NOW))
    checked = c.post("/api/settings/platform/check-update")
    assert checked.status_code == 200 and checked.json()["data"] == expected["update"]
    assert c.get("/api/settings/platform").json()["data"]["update"] == expected["update"]
