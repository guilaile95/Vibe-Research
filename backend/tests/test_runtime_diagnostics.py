"""Synthetic-only diagnostics: no services, files containing credentials, or live probes."""
import builtins
import json
import socket
import stat
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import runtime_diagnostics as diagnostic
import runtime_info_router as runtime

STARTUP = dict(service="vibe-research-api", version="1.2.3", git_sha="a" * 40, source_state="clean",
               source_directory="PRIVATE_SOURCE", working_directory="PRIVATE_CWD")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VR_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.delenv("VR_AGENT_RUNTIME_URL", raising=False)
    monkeypatch.delenv("VR_AGENT_RUNTIME_PORT", raising=False)
    monkeypatch.setattr(diagnostic.agent_runtime, "status", lambda: pytest.fail("runtime probe forbidden"))
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network forbidden"))


@pytest.mark.parametrize("url,port,state,target,declared", [
    (None, None, "PORTS_MATCH", 8911, 8911),
    (None, "8912", "PORT_MISMATCH", 8911, 8912),
    ("http://localhost:8912", "8912junk", "PORTS_MATCH", 8912, 8912),
    ("http://[::1]:8912", "8912", "PORTS_MATCH", 8912, 8912),
    ("http://localhost", "80", "PORTS_MATCH", 80, 80),
    (None, "000008911", "PORTS_MATCH", 8911, 8911),
    (None, "0", "DYNAMIC_PORT_UNVERIFIED", 8911, 0),
    (None, "bad-secret", "INVALID_CONFIGURATION", 8911, None),
    (None, "999999999999999999999999", "INVALID_CONFIGURATION", 8911, None),
    ("http://user:secret@localhost:8911", None, "INVALID_CONFIGURATION", None, 8911),
    ("https://localhost:8911", None, "INVALID_CONFIGURATION", None, 8911),
    ("http://remote.invalid:8911", None, "INVALID_CONFIGURATION", None, 8911),
    ("http://localhost:secret", None, "INVALID_CONFIGURATION", None, 8911),
    ("http://localhost:0", None, "INVALID_CONFIGURATION", None, 8911),
    ("http://localhost:8911/private?token=secret", None, "INVALID_CONFIGURATION", None, 8911),
    ("http://[invalid", None, "INVALID_CONFIGURATION", None, 8911),
])
def test_runtime_port_contract(monkeypatch, url, port, state, target, declared):
    if url is not None: monkeypatch.setenv("VR_AGENT_RUNTIME_URL", url)
    if port is not None: monkeypatch.setenv("VR_AGENT_RUNTIME_PORT", port)
    result = diagnostic.build_report(STARTUP)["agent_runtime"]
    assert result["configuration_status"] == state
    assert result["backend_target_port"] == target
    assert result["declared_runtime_port"] == declared
    assert result["availability"] == "NOT_EVALUATED"
    assert result["probe_performed"] is False
    assert "secret" not in json.dumps(result)


def test_report_never_opens_files_or_reads_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv("HITHINK_FINANCE_API_KEY", "DO_NOT_READ")
    monkeypatch.setenv("UNRELATED_PRIVATE_NAME", "DO_NOT_EXPORT")
    original_get = diagnostic.os.environ.get
    def safe_get(name, *args):
        assert name not in {"HITHINK_FINANCE_API_KEY", "TUSHARE_TOKEN", "VR_API_KEY", "VR_SEC_CONTACT"}
        return original_get(name, *args)
    original_item = type(diagnostic.os.environ).__getitem__
    def safe_item(self, name):
        assert name not in {"HITHINK_FINANCE_API_KEY", "TUSHARE_TOKEN", "VR_API_KEY", "VR_SEC_CONTACT"}
        return original_item(self, name)
    monkeypatch.setattr(type(diagnostic.os.environ), "__getitem__", safe_item)
    monkeypatch.setattr(diagnostic.os.environ, "get", safe_get)
    monkeypatch.setattr(builtins, "open", lambda *a, **k: pytest.fail("file read forbidden"))
    monkeypatch.setattr(diagnostic.Path, "open", lambda *a, **k: pytest.fail("file read forbidden"))
    report = diagnostic.build_report(STARTUP)
    text = json.dumps(report)
    for private in (str(tmp_path), "PRIVATE_SOURCE", "PRIVATE_CWD", "DO_NOT_READ", "UNRELATED_PRIVATE_NAME"):
        assert private not in text
    assert report["directories"]["reports"] == "MISSING"
    assert all(row["verification"] == "NOT_EVALUATED" for row in report["source_capabilities"])
    assert report["source_capabilities"][1]["configuration"] == "ENV_NAME_PRESENT_VALUE_NOT_INSPECTED"


def test_directory_metadata_only(tmp_path, monkeypatch):
    assert diagnostic._directory_status(tmp_path) == "ACCESS_CHECK_OK"
    monkeypatch.setattr(diagnostic.os, "access", lambda *a: False)
    assert diagnostic._directory_status(tmp_path) == "ACCESS_CHECK_FAILED"
    file = tmp_path / "fixture"
    file.touch()
    assert diagnostic._directory_status(file) == "NOT_DIRECTORY"
    for metadata in (SimpleNamespace(st_mode=stat.S_IFLNK), SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)):
        with monkeypatch.context() as scoped:
            scoped.setattr(diagnostic.Path, "lstat", lambda *a: metadata)
            assert diagnostic._directory_status(tmp_path) == "LINK_NOT_INSPECTED"
    monkeypatch.setattr(diagnostic.Path, "lstat", lambda *a: (_ for _ in ()).throw(PermissionError("private path")))
    assert diagnostic._directory_status(tmp_path) == "UNAVAILABLE"


def test_router_reuses_startup_identity_and_redacts_export(monkeypatch):
    calls = []
    monkeypatch.setattr(runtime, "_git_snapshot", lambda path: (calls.append(1) or "a" * 40, "clean"))
    app = FastAPI()
    app.include_router(runtime.create_router("1.2.3"))
    client = TestClient(app)
    info = client.get("/api/runtime-info").json()["data"]
    for path in ("/api/runtime-diagnostics", "/api/runtime-diagnostics/export"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["data"]["startup"] == {key: info[key] for key in STARTUP if key not in ("source_directory", "working_directory")}
        assert "source_directory" not in response.text
    assert len(calls) == 1
    assert response.headers["content-disposition"] == 'attachment; filename="vibe-runtime-diagnostics.json"'


def test_diagnostics_inherit_private_api_boundary(monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "_API_KEY", "synthetic-access")
    client = TestClient(app_module.app)  # No lifespan: no services/schedulers.
    for path in ("/api/runtime-diagnostics", "/api/runtime-diagnostics/export"):
        assert client.get(path).status_code == 401
        headers = {"Authorization": "Bearer synthetic-access"}
        assert client.get(path, headers=headers).status_code == 200
        assert client.get(path, headers={**headers, "Origin": "https://untrusted.invalid"}).status_code == 403
        assert client.get(path, headers={**headers, "Host": "untrusted.invalid"}).status_code == 400


def test_backend_report_matches_frontend_export_golden(monkeypatch):
    fixture = Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/runtime-diagnostics.json"
    expected = json.loads(fixture.read_text(encoding="utf-8"))
    with patch.dict(diagnostic.os.environ, {"VR_DATA_DIR": "SYNTHETIC_DATA", "VR_REPORTS_DIR": "SYNTHETIC_REPORTS"}, clear=True):
        monkeypatch.setattr(diagnostic, "_directory_status", lambda path: "MISSING")
        assert diagnostic.build_report(STARTUP) == expected
