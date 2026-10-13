"""Synthetic archive-to-research journeys through production HTTP and storage."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as application
import myreports as reports


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "REPORTS_DIR", tmp_path / "reports")
    return TestClient(application.app, raise_server_exceptions=False)


def upload(client, *, title="Original title", institution=""):
    response = client.post("/api/myreports", json={
        "name": "synthetic.txt", "content_b64": base64.b64encode(b"synthetic catalyst evidence").decode(),
        "title": title, "institution": institution,
    })
    assert response.status_code == 200, response.text
    return response.json()["data"]


def search(client):
    response = client.get("/api/myreports/fulltext-search", params={"q": "catalyst"})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_archive_edit_duplicate_download_delete_journey(archive):
    original = upload(archive)
    rid = original["id"]
    response = archive.patch(f"/api/myreports/{rid}", json={"title": "User edited title"})
    assert response.status_code == 200
    duplicate = upload(archive, title="Incoming duplicate title", institution="Synthetic Institute")
    assert duplicate["id"] == rid and duplicate["deduped"] is True
    hits = search(archive)
    assert len(hits) == 1
    assert hits[0]["title"] == "User edited title"
    assert hits[0]["institution"] == "Synthetic Institute"
    assert archive.get(f"/api/myreports/file/{rid}").content == b"synthetic catalyst evidence"
    assert len(json.loads((reports.REPORTS_DIR / "index.json").read_text())) == 1
    assert archive.delete(f"/api/myreports/{rid}").json()["data"]["ok"] is True
    assert search(archive) == []
    assert archive.get(f"/api/myreports/file/{rid}").status_code == 404
    assert archive.delete(f"/api/myreports/{rid}").json()["data"]["ok"] is False


def test_failed_delete_preserves_searchable_archive_and_retry(archive, monkeypatch):
    original = upload(archive)
    rid = original["id"]
    before_hits = search(archive)
    index = reports.REPORTS_DIR / "index.json"
    before_index = index.read_bytes()
    real_replace = reports.os.replace

    def fail_index_publish(src, dst):
        if Path(dst) == index:
            raise OSError("synthetic archive index publish failure")
        return real_replace(src, dst)

    with monkeypatch.context() as patch:
        patch.setattr(reports.os, "replace", fail_index_publish)
        response = archive.delete(f"/api/myreports/{rid}")
    assert response.status_code == 500
    assert index.read_bytes() == before_index
    assert archive.get(f"/api/myreports/file/{rid}").content == b"synthetic catalyst evidence"
    assert search(archive) == before_hits
    assert archive.get("/api/myreports").json()["data"][0]["text_index_status"] == "SEARCHABLE"
    assert archive.delete(f"/api/myreports/{rid}").json()["data"]["ok"] is True
    assert search(archive) == []


@pytest.mark.parametrize("stage", ["connect", "delete_index", "commit"])
def test_fulltext_delete_failure_rolls_back_archive_and_allows_retry(archive, monkeypatch, stage):
    import sqlite3

    original = upload(archive)
    rid = original["id"]
    before_hits = search(archive)
    before_index = (reports.REPORTS_DIR / "index.json").read_bytes()
    connect = reports.fulltext._connect_write
    handles = []

    class FailingConnection:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, *args):
            if ((stage == "delete_index" and sql.startswith("DELETE FROM report_text_index"))
                    or (stage == "commit" and sql == "COMMIT")):
                raise sqlite3.OperationalError("synthetic text-index transaction failure")
            return self.conn.execute(sql, *args)

        def close(self):
            self.conn.close()
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                self.conn.execute("SELECT 1")
            handles.append("closed")

    def failed_connect(directory):
        assert reports._LOCK.locked()
        if stage == "connect":
            raise sqlite3.OperationalError("synthetic text-index open failure")
        conn = connect(directory)
        return FailingConnection(conn)

    with monkeypatch.context() as patch:
        patch.setattr(reports.fulltext, "_connect_write", failed_connect)
        response = archive.delete(f"/api/myreports/{rid}")
    assert response.status_code == 500
    assert (reports.REPORTS_DIR / "index.json").read_bytes() == before_index
    assert archive.get(f"/api/myreports/file/{rid}").content == b"synthetic catalyst evidence"
    assert search(archive) == before_hits
    assert handles == ([] if stage == "connect" else ["closed"])
    assert archive.delete(f"/api/myreports/{rid}").json()["data"]["ok"] is True
    assert search(archive) == []


def test_double_failure_is_not_reported_as_success_and_keeps_original_bytes(archive, monkeypatch):
    original = upload(archive)
    rid = original["id"]
    index = reports.REPORTS_DIR / "index.json"
    replace = reports.os.replace
    publishes = 0

    def fail_rollback(src, dst):
        nonlocal publishes
        if Path(dst) == index:
            publishes += 1
            if publishes == 2:
                raise OSError("synthetic rollback disk failure")
        return replace(src, dst)

    def fail_cleanup(*_args):
        raise OSError("synthetic cache failure")

    with monkeypatch.context() as patch:
        patch.setattr(reports.os, "replace", fail_rollback)
        patch.setattr(reports.fulltext, "remove_report", fail_cleanup)
        response = archive.delete(f"/api/myreports/{rid}")
    assert response.status_code == 500
    assert publishes == 2
    assert (reports.REPORTS_DIR / f"{rid}.txt").read_bytes() == b"synthetic catalyst evidence"
    # Explicit cross-store limit: both the operation and its rollback failed.
    # No claim of archive-level atomicity or a successful delete is made.
    assert json.loads(index.read_text()) == []
    assert json.loads((reports.REPORTS_DIR / "index.json.bak").read_text())[0]["id"] == rid
    assert not list(reports.REPORTS_DIR.glob("*.tmp.*"))
    assert search(archive) == []
