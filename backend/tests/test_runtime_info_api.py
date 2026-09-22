"""运行快照与降级契约；只用临时目录和合成信息，不启动后台任务。"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import runtime_info_router as runtime

_SHA = "a" * 40


@pytest.fixture()
def source_directory(tmp_path, monkeypatch):
    # 模拟 worktree 的 .git 文件；不得实际读取其他 checkout。
    (tmp_path / ".git").write_text("gitdir: fixture-only", encoding="utf-8")
    monkeypatch.setattr(runtime, "_SOURCE_DIRECTORY", tmp_path)
    return tmp_path


@pytest.mark.parametrize("changes, expected", [("", "clean"), ("? private-fixture-token.txt\n", "modified")])
def test_startup_snapshot_is_read_once_and_response_is_allowlisted(source_directory, monkeypatch, changes, expected):
    calls = []

    def fake_git(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=f"# branch.oid {_SHA}\n# branch.head fixture-branch\n{changes}",
            stderr="https://fixture-user:fixture-token@proxy.invalid",
        )

    monkeypatch.setattr(runtime.subprocess, "run", fake_git)
    app = FastAPI()
    app.include_router(runtime.create_router("1.2.3"))
    client = TestClient(app)
    response = client.get("/api/runtime-info")
    assert client.get("/api/runtime-info").json() == response.json()
    assert len(calls) == 1
    assert "--no-optional-locks" in calls[0][0]
    assert calls[0][1]["timeout"] == 2
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"data": {
        "service": "vibe-research-api",
        "version": "1.2.3",
        "git_sha": _SHA,
        "source_state": expected,
        "source_directory": str(source_directory),
        "working_directory": str(runtime.Path.cwd()),
    }}
    assert "fixture-token" not in response.text
    assert "proxy.invalid" not in response.text
    assert "fixture-branch" not in response.text


@pytest.mark.parametrize("failure", [
    FileNotFoundError("fixture-token"),
    subprocess.TimeoutExpired("git", 2, stderr="fixture-token"),
    SimpleNamespace(returncode=128, stdout="", stderr="fixture-token"),
    SimpleNamespace(returncode=0, stdout="# branch.oid (initial)\n", stderr=""),
])
def test_git_failure_keeps_runtime_available_with_unknown_sha(source_directory, monkeypatch, failure):
    def fake_git(*args, **kwargs):
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(runtime.subprocess, "run", fake_git)
    app = FastAPI()
    app.include_router(runtime.create_router("unknown"))
    response = TestClient(app).get("/api/runtime-info")
    assert response.status_code == 200
    assert response.json()["data"]["git_sha"] is None
    assert response.json()["data"]["source_state"] == "unknown"
    assert response.json()["data"]["version"] == "unknown"
    assert "fixture-token" not in response.text


def test_source_archive_does_not_inherit_an_ancestor_git_version(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not query ancestor Git"))
    assert runtime._git_snapshot(tmp_path) == (None, "unknown")


def test_unreadable_git_directory_returns_unknown(tmp_path, monkeypatch):
    def denied(path):
        raise PermissionError("fixture-sensitive-token")

    monkeypatch.setattr(runtime.Path, "exists", denied)
    assert runtime._git_snapshot(tmp_path) == (None, "unknown")


def test_runtime_info_uses_existing_private_api_boundary(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VR_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(tmp_path / "evidence.db"))
    monkeypatch.setenv("VIBE_RESEARCH_NEWS_RADAR_CACHE", str(tmp_path / "radar.json"))
    monkeypatch.setenv("VR_API_KEY", "fixture-access-key")
    monkeypatch.setattr(runtime, "_git_snapshot", lambda path: (None, "unknown"))
    import app as app_module

    monkeypatch.setattr(app_module, "_API_KEY", "fixture-access-key")
    # 不进入 lifespan，不启动调度器或读取真实账户；只验证两个只读接口。
    client = TestClient(app_module.app)
    assert client.get("/api/health").status_code == 200
    unauthenticated = client.get("/api/runtime-info")
    assert unauthenticated.status_code == 401
    assert "source_directory" not in unauthenticated.text
    headers = {"Authorization": "Bearer fixture-access-key"}
    assert client.get("/api/runtime-info", headers=headers).status_code == 200
    assert client.get("/api/runtime-info", headers={**headers, "Origin": "https://untrusted.invalid"}).status_code == 403
    assert client.get("/api/runtime-info", headers={**headers, "Host": "untrusted.invalid"}).status_code == 400
