"""Local server-side AI credential mirror — Owner option B."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import ai_credential_store as cred
import native_intel_store as store
import native_intel_timeline as timeline

SECRET = "test-secret-never-log"
ANALYSIS = {
    "core_trends": "液冷需求上升",
    "sentiment_controversy": "中性",
    "signals": "无",
    "rss_insights": "暂无显著增量",
    "outlook_strategy": "观察",
    "standalone_summaries": {},
}


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "vr-data"
    monkeypatch.setenv("VR_DATA_DIR", str(root))
    monkeypatch.delenv("VR_API_KEY", raising=False)
    return root


def _seed_intel(db: Path) -> Path:
    store.initialize_store(db)
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
        db_path=db,
    )
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    store.start_run("run_cred", "test", 1, db_path=db, started_at=now_iso)
    store.upsert_observation(
        "run_cred",
        "hotlist-weibo",
        {
            "item_key": "hotlist-weibo:https://weibo.com/news1",
            "canonical_url": "https://weibo.com/news1",
            "url": "https://weibo.com/news1",
            "title": "液冷需求上升",
            "title_key": "液冷需求上升",
            "summary": "数据中心液冷",
            "published_at": now_iso,
            "published_ts": int(now_dt.timestamp()),
            "rank": 1,
        },
        observed_at=now_iso,
        has_real_rank=True,
        db_path=db,
    )
    store.record_source_run(
        "run_cred", "hotlist-weibo", status="ok", item_count=1, db_path=db
    )
    store.finish_run(
        "run_cred",
        status=store.RUN_STATUS_OK,
        source_ok=1,
        source_failed=0,
        item_seen=1,
        item_new=1,
        db_path=db,
    )
    return db


def _enable_ai_segment(db: Path) -> None:
    timeline.save_policy(
        {
            "enabled": True,
            "preset": "custom",
            "custom": {
                "default": {
                    "fetch": False,
                    "report": False,
                    "mode": "CURRENT",
                    "once": False,
                    "ai_analysis": False,
                    "ai_mode": "CURRENT",
                    "ai_once": True,
                },
                "segments": [
                    {
                        "name": "定时AI分析",
                        "start": "20:00",
                        "end": "22:00",
                        "days": [1, 2, 3, 4, 5, 6, 7],
                        "fetch": False,
                        "report": True,
                        "mode": "DAILY",
                        "once": False,
                        "ai_analysis": True,
                        "ai_mode": "DAILY",
                        "ai_once": False,
                    }
                ],
            },
        },
        str(db),
    )


def _meta(db: Path, key: str) -> dict:
    raw = store.get_meta(key, db)
    assert raw is not None
    return json.loads(raw)


def _tick_now() -> datetime:
    return datetime(2026, 9, 5, 12, 30, tzinfo=timezone.utc)


def test_status_empty(data_dir: Path) -> None:
    status = cred.status()
    assert status["configured"] is False
    assert status["scheduled_available"] is False
    assert status["error"] == cred.UNAVAILABLE_CREDENTIAL
    assert "apiKey" not in status


def test_save_api_and_status_hides_secret(data_dir: Path) -> None:
    status = cred.save(
        {
            "provider": "openai-compatible",
            "baseURL": "http://127.0.0.1:9",
            "model": "fixture-model",
            "apiKey": SECRET,
        }
    )
    assert status["configured"] is True
    assert status["provider"] == "openai-compatible"
    assert "apiKey" not in status
    assert SECRET not in json.dumps(status)
    raw = json.loads(cred.credential_path().read_text(encoding="utf-8"))
    assert raw["apiKey"] == SECRET
    if os.name != "nt":
        file_mode = stat.S_IMODE(cred.credential_path().stat().st_mode)
        dir_mode = stat.S_IMODE(cred.credential_path().parent.stat().st_mode)
        assert file_mode == 0o600
        assert dir_mode == 0o700


def test_save_rejects_incomplete_api(data_dir: Path) -> None:
    with pytest.raises(cred.CredentialStoreError):
        cred.save(
            {"provider": "deepseek", "model": "x", "baseURL": "", "apiKey": SECRET}
        )


def test_save_rejects_unknown_provider(data_dir: Path) -> None:
    with pytest.raises(cred.CredentialStoreError):
        cred.save(
            {
                "provider": "vault-kms",
                "model": "x",
                "baseURL": "http://x",
                "apiKey": SECRET,
            }
        )


def test_codex_save_wipes_api_secret(data_dir: Path) -> None:
    cred.save(
        {
            "provider": "openai-compatible",
            "baseURL": "http://127.0.0.1:9",
            "model": "fixture-model",
            "apiKey": SECRET,
        }
    )
    cred.save({"provider": "cli-codex", "model": "gpt-5-codex"})
    raw = json.loads(cred.credential_path().read_text(encoding="utf-8"))
    assert raw["provider"] == "cli-codex"
    assert raw["apiKey"] == ""
    assert SECRET not in json.dumps(raw)


def test_delete_removes_file(data_dir: Path) -> None:
    cred.save({"provider": "cli-codex", "model": "gpt-5-codex"})
    cred.delete()
    assert not cred.credential_path().exists()
    assert cred.status()["configured"] is False


def test_corrupt_file_is_unavailable(data_dir: Path) -> None:
    path = cred.credential_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    cfg, error = cred.scheduled_config()
    assert cfg is None
    assert error == cred.UNAVAILABLE_CREDENTIAL


def test_redact_secret() -> None:
    assert cred.redact(f"Bearer {SECRET} boom", SECRET) == "Bearer *** boom"


def test_http_put_get_delete(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH", "1")
    import app as app_module

    client = TestClient(app_module.app)
    put = client.put(
        "/api/ai/credential",
        json={
            "provider": "openai-compatible",
            "baseURL": "http://127.0.0.1:9",
            "model": "fixture-model",
            "apiKey": SECRET,
        },
    )
    assert put.status_code == 200
    body = put.json()
    assert body["configured"] is True
    assert "apiKey" not in body
    assert SECRET not in put.text
    status = client.get("/api/ai/credential-status")
    assert status.status_code == 200
    assert status.json()["scheduled_credential_available"] is True
    assert SECRET not in status.text
    deleted = client.delete("/api/ai/credential")
    assert deleted.status_code == 200
    assert client.get("/api/ai/credential-status").json()["configured"] is False


def test_http_rejects_extra_fields(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH", "1")
    import app as app_module

    client = TestClient(app_module.app)
    resp = client.put(
        "/api/ai/credential",
        json={"provider": "cli-codex", "model": "gpt-5-codex", "vault": "no"},
    )
    assert resp.status_code == 422


def test_scheduled_missing_credential_isolated(data_dir: Path, tmp_path: Path) -> None:
    db = _seed_intel(tmp_path / "intel.sqlite3")
    _enable_ai_segment(db)
    store.set_meta(
        "native_intel_last_scheduled_report",
        json.dumps({"status": "SUCCESS", "item_count": 1}),
        db,
    )
    timeline.scheduled_tick(str(db), now=_tick_now(), ai_runner=None)
    last_ai = _meta(db, "native_intel_last_scheduled_ai")
    assert last_ai["status"] == cred.UNAVAILABLE_CREDENTIAL
    last_report = _meta(db, "native_intel_last_scheduled_report")
    assert last_report["status"] in ("SUCCESS", "NORMAL", "normal", "partial")


def test_scheduled_api_fixture_success_and_secret_stays_local(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            captured["auth"] = self.headers.get("Authorization") or ""
            payload = json.dumps(
                {
                    "choices": [
                        {"delta": {"content": json.dumps(ANALYSIS, ensure_ascii=False)}}
                    ]
                }
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(f"data: {payload}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        cred.save(
            {
                "provider": "openai-compatible",
                "baseURL": f"http://127.0.0.1:{port}/v1",
                "model": "fixture-model",
                "apiKey": SECRET,
            }
        )
        db = _seed_intel(tmp_path / "intel.sqlite3")
        _enable_ai_segment(db)
        monkeypatch.delenv("VR_API_KEY", raising=False)
        import chat

        monkeypatch.setattr(chat, "_PUBLIC_MODE", False)
        timeline.scheduled_tick(str(db), now=_tick_now(), ai_runner=None)
    finally:
        server.shutdown()
        server.server_close()

    last_ai = _meta(db, "native_intel_last_scheduled_ai")
    assert last_ai["status"] == "SUCCESS"
    assert last_ai.get("artifact_id")
    assert captured.get("auth") == f"Bearer {SECRET}"
    assert SECRET not in json.dumps(last_ai)
    sqlite_blob = Path(db).read_bytes()
    assert SECRET.encode("utf-8") not in sqlite_blob
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT payload_json, error_message FROM intel_ai_artifacts ORDER BY rowid DESC LIMIT 1"
        ).fetchall()
    assert rows
    assert SECRET not in str(rows[0])


def test_scheduled_does_not_fallback_to_codex(data_dir: Path, tmp_path: Path) -> None:
    db = _seed_intel(tmp_path / "intel.sqlite3")
    _enable_ai_segment(db)
    store.update_native_intel_config({"ai_analysis_provider": "deepseek"}, db_path=db)
    with patch("agent_runtime.stream_chat") as mocked:
        timeline.scheduled_tick(str(db), now=_tick_now(), ai_runner=None)
        mocked.assert_not_called()
    last_ai = _meta(db, "native_intel_last_scheduled_ai")
    assert last_ai["status"] == cred.UNAVAILABLE_CREDENTIAL


def test_get_intel_status_reports_scheduled_flag(
    data_dir: Path, tmp_path: Path
) -> None:
    import native_intel_agent_tools as agent_tools

    db = _seed_intel(tmp_path / "intel.sqlite3")
    tools = agent_tools.NativeIntelAgentTools(str(db))
    empty = tools.get_intel_status()
    assert empty["ai"]["scheduled_credential_available"] is False
    cred.save({"provider": "cli-codex", "model": "gpt-5-codex"})
    filled = tools.get_intel_status()
    assert filled["ai"]["scheduled_credential_available"] is True
    assert filled["ai"]["scheduled_provider"] == "cli-codex"
    assert SECRET not in json.dumps(filled)


def test_http_incomplete_api_is_400(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH", "1")
    import app as app_module

    client = TestClient(app_module.app)
    resp = client.put(
        "/api/ai/credential",
        json={"provider": "deepseek", "model": "x", "baseURL": "", "apiKey": SECRET},
    )
    assert resp.status_code == 400
    assert SECRET not in resp.text


def test_scheduled_error_redacts_secret(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            body = f"invalid key {SECRET}"
            self.send_response(401)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        cred.save(
            {
                "provider": "openai-compatible",
                "baseURL": f"http://127.0.0.1:{port}/v1",
                "model": "fixture-model",
                "apiKey": SECRET,
            }
        )
        db = _seed_intel(tmp_path / "intel.sqlite3")
        _enable_ai_segment(db)
        import chat

        monkeypatch.setattr(chat, "_PUBLIC_MODE", False)
        timeline.scheduled_tick(str(db), now=_tick_now(), ai_runner=None)
    finally:
        server.shutdown()
        server.server_close()

    last_ai = _meta(db, "native_intel_last_scheduled_ai")
    assert last_ai["status"] == "ERROR"
    assert SECRET not in json.dumps(last_ai)


def test_injected_runner_still_bypasses_store(data_dir: Path, tmp_path: Path) -> None:
    db = _seed_intel(tmp_path / "intel.sqlite3")
    _enable_ai_segment(db)

    def runner(_cfg, _messages):
        return json.dumps(ANALYSIS, ensure_ascii=False)

    timeline.scheduled_tick(str(db), now=_tick_now(), ai_runner=runner)
    last_ai = _meta(db, "native_intel_last_scheduled_ai")
    assert last_ai["status"] == "SUCCESS"
