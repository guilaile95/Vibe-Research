"""API 专项测试：所有 happy path、400/404/409/422/500、分页边界、confirm、archived mutation、安全文案。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app as app_module
import evidence_thesis_router as router
import evidence_thesis_service as svc
import evidence_thesis_store as store


# ---------------------------------------------------------------------------
# Fixtures：每个测试使用独立的临时数据库
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_db(tmp_path, monkeypatch) -> Path:
    """每个测试独立的临时数据库，通过环境变量注入。"""
    db_path = tmp_path / "test_api.db"
    store.initialize_store(db_path)
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(db_path))
    return db_path


@pytest.fixture
def client(isolated_db) -> TestClient:
    """TestClient；每个测试使用独立数据库。"""
    return TestClient(app_module.app)


def _now() -> str:
    return "2025-01-01T00:00:00+00:00"


def _evidence_payload(**overrides) -> dict:
    payload = {
        "subject_type": "stock",
        "subject_id": "600519",
        "evidence_type": "news",
        "claim": "claim",
        "source_title": "src",
        "source_url": "https://example.com",
        "source_date": "2025-01-01",
        "accessed_at": _now(),
        "classification": "fact",
        "confidence": "high",
    }
    payload.update(overrides)
    return payload


def _evidence_update_payload(**overrides) -> dict:
    """EvidenceUpdateIn 不含 subject_type/subject_id（extra=forbid）。"""
    payload = {
        "evidence_type": "news",
        "claim": "claim",
        "source_title": "src",
        "source_url": "https://example.com",
        "source_date": "2025-01-01",
        "accessed_at": _now(),
        "classification": "fact",
        "confidence": "high",
    }
    payload.update(overrides)
    return payload


def _thesis_payload(**overrides) -> dict:
    payload = {
        "subject_type": "stock",
        "subject_id": "600519",
        "title": "thesis",
        "summary": "summary",
        "core_claims": ["c1"],
        "catalysts": ["cat1"],
        "risks": ["r1"],
        "invalidation_conditions": ["ic1"],
        "change_summary": "创建",
    }
    payload.update(overrides)
    return payload


def _create_evidence(client, **overrides) -> dict:
    r = client.post("/api/evidence", json=_evidence_payload(**overrides))
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _create_thesis(client, **overrides) -> dict:
    r = client.post("/api/thesis", json=_thesis_payload(**overrides))
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ---------------------------------------------------------------------------
# Evidence happy path
# ---------------------------------------------------------------------------

class TestEvidenceHappyPath:
    def test_create_evidence(self, client):
        r = client.post("/api/evidence", json=_evidence_payload())
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["id"]
        assert data["subject_id"] == "600519"
        assert data["classification"] == "fact"

    def test_list_evidence(self, client):
        _create_evidence(client)
        _create_evidence(client, claim="c2")
        r = client.get("/api/evidence")
        assert r.status_code == 200
        assert r.json()["data"]["total"] == 2

    def test_get_evidence(self, client):
        ev = _create_evidence(client)
        r = client.get(f"/api/evidence/{ev['id']}")
        assert r.status_code == 200
        assert r.json()["data"]["id"] == ev["id"]

    def test_update_evidence(self, client):
        ev = _create_evidence(client)
        r = client.put(f"/api/evidence/{ev['id']}", json=_evidence_update_payload(claim="updated"))
        assert r.status_code == 200
        assert r.json()["data"]["claim"] == "updated"

    def test_delete_evidence_with_confirm(self, client):
        ev = _create_evidence(client)
        r = client.delete(f"/api/evidence/{ev['id']}?confirm=true")
        assert r.status_code == 200
        # 软删除：仍可通过 GET 获取（含 deleted=1）
        r2 = client.get(f"/api/evidence/{ev['id']}")
        assert r2.status_code == 200
        assert r2.json()["data"]["deleted"] == 1


# ---------------------------------------------------------------------------
# Thesis happy path
# ---------------------------------------------------------------------------

class TestThesisHappyPath:
    def test_create_thesis(self, client):
        r = client.post("/api/thesis", json=_thesis_payload())
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["thesis"]["current_revision"] == 1
        assert data["thesis"]["status"] == "active"

    def test_list_thesis(self, client):
        _create_thesis(client)
        _create_thesis(client, title="t2")
        r = client.get("/api/thesis")
        assert r.status_code == 200
        assert r.json()["data"]["total"] == 2

    def test_get_thesis(self, client):
        thesis = _create_thesis(client)
        r = client.get(f"/api/thesis/{thesis['thesis']['id']}")
        assert r.status_code == 200
        assert r.json()["data"]["thesis"]["id"] == thesis["thesis"]["id"]

    def test_update_thesis(self, client):
        thesis = _create_thesis(client)
        tid = thesis["thesis"]["id"]
        r = client.put(f"/api/thesis/{tid}", json={
            "title": "t2", "summary": "s2", "status": "active",
            "core_claims": [], "catalysts": [], "risks": [], "invalidation_conditions": [],
            "expected_revision": 1, "change_summary": "edit",
        })
        assert r.status_code == 200
        assert r.json()["data"]["thesis"]["current_revision"] == 2

    def test_archive_thesis_with_confirm(self, client):
        thesis = _create_thesis(client)
        tid = thesis["thesis"]["id"]
        r = client.delete(f"/api/thesis/{tid}?confirm=true&expected_revision=1")
        assert r.status_code == 200
        assert r.json()["data"]["thesis"]["status"] == "archived"


# ---------------------------------------------------------------------------
# Revision & diff happy path
# ---------------------------------------------------------------------------

class TestRevisionHappyPath:
    def test_list_revisions(self, client):
        thesis = _create_thesis(client)
        tid = thesis["thesis"]["id"]
        r = client.get(f"/api/thesis/{tid}/revisions")
        assert r.status_code == 200
        assert r.json()["data"]["total"] == 1

    def test_get_revision(self, client):
        thesis = _create_thesis(client)
        tid = thesis["thesis"]["id"]
        r = client.get(f"/api/thesis/{tid}/revisions/1")
        assert r.status_code == 200
        assert r.json()["data"]["revision_number"] == 1

    def test_diff(self, client):
        thesis = _create_thesis(client)
        tid = thesis["thesis"]["id"]
        client.put(f"/api/thesis/{tid}", json={
            "title": "t2", "summary": "s2", "status": "active",
            "core_claims": [], "catalysts": [], "risks": [], "invalidation_conditions": [],
            "expected_revision": 1, "change_summary": "edit",
        })
        r = client.get(f"/api/thesis/{tid}/diff?from=1&to=2")
        assert r.status_code == 200
        diff = r.json()["data"]
        assert diff["from_revision"] == 1
        assert diff["to_revision"] == 2


# ---------------------------------------------------------------------------
# Link happy path
# ---------------------------------------------------------------------------

class TestLinkHappyPath:
    def test_link_evidence(self, client):
        thesis = _create_thesis(client)
        ev = _create_evidence(client)
        tid = thesis["thesis"]["id"]
        r = client.post(f"/api/thesis/{tid}/evidence", json={
            "evidence_id": ev["id"], "stance": "support",
            "expected_revision": 1, "change_summary": "link",
        })
        assert r.status_code == 200
        assert r.json()["data"]["thesis"]["current_revision"] == 2

    def test_update_stance(self, client):
        thesis = _create_thesis(client)
        ev = _create_evidence(client)
        tid = thesis["thesis"]["id"]
        client.post(f"/api/thesis/{tid}/evidence", json={
            "evidence_id": ev["id"], "stance": "support",
            "expected_revision": 1, "change_summary": "link",
        })
        r = client.put(f"/api/thesis/{tid}/evidence/{ev['id']}", json={
            "stance": "oppose", "expected_revision": 2, "change_summary": "change",
        })
        assert r.status_code == 200
        assert r.json()["data"]["thesis"]["current_revision"] == 3

    def test_unlink_evidence(self, client):
        thesis = _create_thesis(client)
        ev = _create_evidence(client)
        tid = thesis["thesis"]["id"]
        client.post(f"/api/thesis/{tid}/evidence", json={
            "evidence_id": ev["id"], "stance": "support",
            "expected_revision": 1, "change_summary": "link",
        })
        r = client.delete(f"/api/thesis/{tid}/evidence/{ev['id']}?expected_revision=2")
        assert r.status_code == 200
        assert r.json()["data"]["thesis"]["current_revision"] == 3


# ---------------------------------------------------------------------------
# 400 错误
# ---------------------------------------------------------------------------

class TestBadRequest:
    def test_delete_evidence_without_confirm(self, client):
        ev = _create_evidence(client)
        r = client.delete(f"/api/evidence/{ev['id']}")
        assert r.status_code == 400
        assert "confirm" in r.json()["detail"]

    def test_delete_thesis_without_confirm(self, client):
        thesis = _create_thesis(client)
        r = client.delete(f"/api/thesis/{thesis['thesis']['id']}?expected_revision=1")
        assert r.status_code == 400
        assert "confirm" in r.json()["detail"]

    def test_cross_subject_link_returns_400(self, client):
        """跨 subject 关联返回 400（业务请求错误）。"""
        thesis = _create_thesis(client, subject_id="600519")
        ev = _create_evidence(client, subject_id="000001")
        r = client.post(f"/api/thesis/{thesis['thesis']['id']}/evidence", json={
            "evidence_id": ev["id"], "stance": "support",
            "expected_revision": 1, "change_summary": "x",
        })
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# 404 错误
# ---------------------------------------------------------------------------

class TestNotFound:
    def test_get_evidence_not_found(self, client):
        r = client.get("/api/evidence/nonexistent")
        assert r.status_code == 404

    def test_get_thesis_not_found(self, client):
        r = client.get("/api/thesis/nonexistent")
        assert r.status_code == 404

    def test_get_revision_not_found(self, client):
        thesis = _create_thesis(client)
        r = client.get(f"/api/thesis/{thesis['thesis']['id']}/revisions/99")
        assert r.status_code == 404

    def test_link_nonexistent_evidence(self, client):
        thesis = _create_thesis(client)
        r = client.post(f"/api/thesis/{thesis['thesis']['id']}/evidence", json={
            "evidence_id": "nonexistent", "stance": "support",
            "expected_revision": 1, "change_summary": "x",
        })
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 409 冲突
# ---------------------------------------------------------------------------

class TestConflict:
    def test_update_thesis_revision_conflict(self, client):
        """expected_revision 不匹配返回 409，body 含 current_revision。"""
        thesis = _create_thesis(client)
        tid = thesis["thesis"]["id"]
        r = client.put(f"/api/thesis/{tid}", json={
            "title": "t2", "summary": "s2", "status": "active",
            "core_claims": [], "catalysts": [], "risks": [], "invalidation_conditions": [],
            "expected_revision": 99, "change_summary": "x",
        })
        assert r.status_code == 409
        body = r.json()
        # 顶层字段：detail (string) + current_revision (int)
        assert body["detail"] == "投资逻辑已发生变化，请重新加载后重试"
        assert body["current_revision"] == 1

    def test_archived_thesis_mutation_returns_409(self, client):
        thesis = _create_thesis(client)
        tid = thesis["thesis"]["id"]
        client.delete(f"/api/thesis/{tid}?confirm=true&expected_revision=1")
        r = client.put(f"/api/thesis/{tid}", json={
            "title": "x", "summary": "x", "status": "active",
            "core_claims": [], "catalysts": [], "risks": [], "invalidation_conditions": [],
            "expected_revision": 2, "change_summary": "x",
        })
        assert r.status_code == 409
        assert r.json()["detail"] == "已归档的投资逻辑不可修改"

    def test_link_evidence_revision_conflict(self, client):
        thesis = _create_thesis(client)
        ev = _create_evidence(client)
        r = client.post(f"/api/thesis/{thesis['thesis']['id']}/evidence", json={
            "evidence_id": ev["id"], "stance": "support",
            "expected_revision": 99, "change_summary": "x",
        })
        assert r.status_code == 409

    @pytest.mark.parametrize("frozen", [False, True], ids=["confirmed", "frozen"])
    def test_formal_content_mutation_endpoints_return_409(self, client, frozen):
        thesis = _create_thesis(client, core_claims=["c1", "c2", "c3"])
        tid = thesis["thesis"]["id"]
        linked = _create_evidence(client, claim="linked")
        other = _create_evidence(client, claim="other")

        assert client.post(f"/api/thesis/{tid}/begin-formalization").status_code == 200
        assert client.post(f"/api/thesis/{tid}/evidence", json={
            "evidence_id": linked["id"], "stance": "support",
            "expected_revision": 1, "change_summary": "link",
        }).status_code == 200
        update_body = {
            "title": "thesis", "summary": "summary", "status": "active",
            "core_claims": ["c1", "c2", "c3"], "catalysts": ["cat1"],
            "risks": ["r1"], "invalidation_conditions": ["ic1"],
            "strategy": "SWING",
            "expected_horizon": {
                "unit": "TRADING_DAY", "min": 5, "max": 20, "anchor": "FREEZE_AT",
            },
            "free_notes": "note", "expected_revision": 2, "change_summary": "formal content",
        }
        assert client.put(f"/api/thesis/{tid}", json=update_body).status_code == 200
        assert client.post(f"/api/thesis/{tid}/confirm").status_code == 200
        expected_revision = 3
        expected_state = "confirmed"
        if frozen:
            assert client.post(
                f"/api/thesis/{tid}/freeze", json={"expected_revision": 3}
            ).status_code == 200
            expected_revision = 4
            expected_state = "frozen"

        attempts = (
            client.put(f"/api/thesis/{tid}", json={
                **update_body,
                "title": "blocked",
                "expected_revision": expected_revision,
            }),
            client.post(f"/api/thesis/{tid}/evidence", json={
                "evidence_id": other["id"], "stance": "support",
                "expected_revision": expected_revision, "change_summary": "blocked",
            }),
            client.put(f"/api/thesis/{tid}/evidence/{linked['id']}", json={
                "stance": "oppose", "expected_revision": expected_revision,
                "change_summary": "blocked",
            }),
            client.delete(
                f"/api/thesis/{tid}/evidence/{linked['id']}?expected_revision={expected_revision}"
            ),
        )
        assert [response.status_code for response in attempts] == [409, 409, 409, 409]

        current = client.get(f"/api/thesis/{tid}").json()["data"]
        assert current["thesis"]["formal_state"] == expected_state
        assert current["thesis"]["current_revision"] == expected_revision
        assert current["evidence_links"][0]["stance"] == "support"


# ---------------------------------------------------------------------------
# 422 校验失败
# ---------------------------------------------------------------------------

class TestValidationError:
    def test_invalid_evidence_type(self, client):
        r = client.post("/api/evidence", json=_evidence_payload(evidence_type="invalid"))
        assert r.status_code == 422

    def test_invalid_classification(self, client):
        r = client.post("/api/evidence", json=_evidence_payload(classification="invalid"))
        assert r.status_code == 422

    def test_invalid_subject_type(self, client):
        r = client.post("/api/evidence", json=_evidence_payload(subject_type="industry"))
        assert r.status_code == 422

    def test_invalid_stance(self, client):
        thesis = _create_thesis(client)
        ev = _create_evidence(client)
        r = client.post(f"/api/thesis/{thesis['thesis']['id']}/evidence", json={
            "evidence_id": ev["id"], "stance": "invalid",
            "expected_revision": 1, "change_summary": "x",
        })
        assert r.status_code == 422

    def test_invalid_status_in_update(self, client):
        thesis = _create_thesis(client)
        r = client.put(f"/api/thesis/{thesis['thesis']['id']}", json={
            "title": "x", "summary": "x", "status": "invalid_status",
            "core_claims": [], "catalysts": [], "risks": [], "invalidation_conditions": [],
            "expected_revision": 1, "change_summary": "x",
        })
        assert r.status_code == 422

    def test_extra_field_rejected(self, client):
        """Pydantic extra=forbid → 422。"""
        payload = _evidence_payload()
        payload["extra_field"] = "x"
        r = client.post("/api/evidence", json=payload)
        assert r.status_code == 422

    def test_missing_required_field(self, client):
        payload = _evidence_payload()
        del payload["claim"]
        r = client.post("/api/evidence", json=payload)
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# expected_revision 严格正整数（HTTP 边界，TestClient）
# ---------------------------------------------------------------------------

def _thesis_update_body(expected_revision) -> dict:
    return {
        "title": "t",
        "summary": "s",
        "status": "active",
        "core_claims": [],
        "catalysts": [],
        "risks": [],
        "invalidation_conditions": [],
        "expected_revision": expected_revision,
        "change_summary": "x",
    }


class TestExpectedRevisionStrictHttp:
    """JSON body / Query 中非法 expected_revision 必须 422；合法 1 正常。"""

    def test_put_thesis_rejects_true_false_zero_negative_string(self, client):
        thesis = _create_thesis(client)
        tid = thesis["thesis"]["id"]
        for bad in (True, False, 0, -1, "1"):
            r = client.put(f"/api/thesis/{tid}", json=_thesis_update_body(bad))
            assert r.status_code == 422, f"expected_revision={bad!r} should be 422, got {r.status_code}: {r.text}"

    def test_put_thesis_accepts_positive_int(self, client):
        thesis = _create_thesis(client)
        tid = thesis["thesis"]["id"]
        r = client.put(f"/api/thesis/{tid}", json=_thesis_update_body(1))
        assert r.status_code == 200, r.text
        assert r.json()["data"]["thesis"]["current_revision"] == 2

    def test_post_link_rejects_true_zero_negative(self, client):
        thesis = _create_thesis(client)
        ev = _create_evidence(client)
        tid = thesis["thesis"]["id"]
        for bad in (True, 0, -1):
            r = client.post(f"/api/thesis/{tid}/evidence", json={
                "evidence_id": ev["id"],
                "stance": "support",
                "expected_revision": bad,
                "change_summary": "x",
            })
            assert r.status_code == 422, f"link expected_revision={bad!r} → {r.status_code}"

    def test_post_link_accepts_positive_int(self, client):
        thesis = _create_thesis(client)
        ev = _create_evidence(client)
        tid = thesis["thesis"]["id"]
        r = client.post(f"/api/thesis/{tid}/evidence", json={
            "evidence_id": ev["id"],
            "stance": "support",
            "expected_revision": 1,
            "change_summary": "link",
        })
        assert r.status_code == 200, r.text

    def test_put_stance_rejects_true_zero_negative(self, client):
        thesis = _create_thesis(client)
        ev = _create_evidence(client)
        tid = thesis["thesis"]["id"]
        assert client.post(f"/api/thesis/{tid}/evidence", json={
            "evidence_id": ev["id"], "stance": "support",
            "expected_revision": 1, "change_summary": "link",
        }).status_code == 200
        for bad in (True, 0, -1):
            r = client.put(f"/api/thesis/{tid}/evidence/{ev['id']}", json={
                "stance": "neutral",
                "expected_revision": bad,
                "change_summary": "x",
            })
            assert r.status_code == 422, f"stance expected_revision={bad!r} → {r.status_code}"

    def test_put_stance_accepts_positive_int(self, client):
        thesis = _create_thesis(client)
        ev = _create_evidence(client)
        tid = thesis["thesis"]["id"]
        assert client.post(f"/api/thesis/{tid}/evidence", json={
            "evidence_id": ev["id"], "stance": "support",
            "expected_revision": 1, "change_summary": "link",
        }).status_code == 200
        r = client.put(f"/api/thesis/{tid}/evidence/{ev['id']}", json={
            "stance": "oppose",
            "expected_revision": 2,
            "change_summary": "stance",
        })
        assert r.status_code == 200, r.text

    def test_delete_thesis_query_rejects_zero_negative_true(self, client):
        thesis = _create_thesis(client)
        tid = thesis["thesis"]["id"]
        for bad in ("0", "-1", "true"):
            r = client.delete(f"/api/thesis/{tid}?confirm=true&expected_revision={bad}")
            assert r.status_code == 422, f"archive expected_revision={bad!r} → {r.status_code}: {r.text}"

    def test_delete_thesis_query_accepts_positive_int(self, client):
        thesis = _create_thesis(client)
        tid = thesis["thesis"]["id"]
        r = client.delete(f"/api/thesis/{tid}?confirm=true&expected_revision=1")
        assert r.status_code == 200, r.text

    def test_delete_unlink_query_rejects_zero_negative_true(self, client):
        thesis = _create_thesis(client)
        ev = _create_evidence(client)
        tid = thesis["thesis"]["id"]
        assert client.post(f"/api/thesis/{tid}/evidence", json={
            "evidence_id": ev["id"], "stance": "support",
            "expected_revision": 1, "change_summary": "link",
        }).status_code == 200
        for bad in ("0", "-1", "true"):
            r = client.delete(f"/api/thesis/{tid}/evidence/{ev['id']}?expected_revision={bad}")
            assert r.status_code == 422, f"unlink expected_revision={bad!r} → {r.status_code}: {r.text}"

    def test_delete_unlink_query_accepts_positive_int(self, client):
        thesis = _create_thesis(client)
        ev = _create_evidence(client)
        tid = thesis["thesis"]["id"]
        assert client.post(f"/api/thesis/{tid}/evidence", json={
            "evidence_id": ev["id"], "stance": "support",
            "expected_revision": 1, "change_summary": "link",
        }).status_code == 200
        r = client.delete(f"/api/thesis/{tid}/evidence/{ev['id']}?expected_revision=2")
        assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# 分页边界
# ---------------------------------------------------------------------------

class TestPagination:
    def test_limit_over_max_returns_422(self, client):
        r = client.get("/api/evidence?limit=201")
        assert r.status_code == 422

    def test_limit_zero_returns_422(self, client):
        r = client.get("/api/evidence?limit=0")
        assert r.status_code == 422

    def test_offset_negative_returns_422(self, client):
        r = client.get("/api/evidence?offset=-1")
        assert r.status_code == 422

    def test_limit_max_200_ok(self, client):
        r = client.get("/api/evidence?limit=200")
        assert r.status_code == 200

    def test_default_limit_50(self, client):
        for _ in range(3):
            _create_evidence(client)
        r = client.get("/api/evidence")
        assert r.status_code == 200
        assert r.json()["data"]["limit"] == 50

    def test_pagination_offset(self, client):
        for _ in range(5):
            _create_evidence(client)
        r = client.get("/api/evidence?limit=2&offset=0")
        assert r.json()["data"]["total"] == 5
        assert len(r.json()["data"]["items"]) == 2
        r2 = client.get("/api/evidence?limit=2&offset=2")
        assert len(r2.json()["data"]["items"]) == 2


# ---------------------------------------------------------------------------
# confirm=true
# ---------------------------------------------------------------------------

class TestConfirm:
    def test_delete_evidence_confirm_false(self, client):
        ev = _create_evidence(client)
        r = client.delete(f"/api/evidence/{ev['id']}?confirm=false")
        assert r.status_code == 400

    def test_delete_evidence_confirm_true(self, client):
        ev = _create_evidence(client)
        r = client.delete(f"/api/evidence/{ev['id']}?confirm=true")
        assert r.status_code == 200

    def test_delete_thesis_confirm_false(self, client):
        thesis = _create_thesis(client)
        r = client.delete(f"/api/thesis/{thesis['thesis']['id']}?confirm=false&expected_revision=1")
        assert r.status_code == 400

    def test_delete_thesis_confirm_true(self, client):
        thesis = _create_thesis(client)
        r = client.delete(f"/api/thesis/{thesis['thesis']['id']}?confirm=true&expected_revision=1")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# archived mutation
# ---------------------------------------------------------------------------

class TestArchivedMutation:
    def test_archived_cannot_link(self, client):
        thesis = _create_thesis(client)
        ev = _create_evidence(client)
        tid = thesis["thesis"]["id"]
        client.delete(f"/api/thesis/{tid}?confirm=true&expected_revision=1")
        r = client.post(f"/api/thesis/{tid}/evidence", json={
            "evidence_id": ev["id"], "stance": "support",
            "expected_revision": 2, "change_summary": "x",
        })
        assert r.status_code == 409

    def test_archived_cannot_unlink(self, client):
        thesis = _create_thesis(client)
        ev = _create_evidence(client)
        tid = thesis["thesis"]["id"]
        client.post(f"/api/thesis/{tid}/evidence", json={
            "evidence_id": ev["id"], "stance": "support",
            "expected_revision": 1, "change_summary": "l",
        })
        client.delete(f"/api/thesis/{tid}?confirm=true&expected_revision=2")
        r = client.delete(f"/api/thesis/{tid}/evidence/{ev['id']}?expected_revision=3")
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# 安全错误文案（500）
# ---------------------------------------------------------------------------

class TestSafeError:
    def test_corrupted_db_returns_500_safe_message(self, client, monkeypatch):
        """数据库损坏返回 500 + 固定安全文案（不含路径/traceback/SQL）。"""
        def _raise_corrupted(*args, **kwargs):
            raise store.EvidenceLedgerCorruptedError()
        monkeypatch.setattr(svc, "list_evidence", _raise_corrupted)
        r = client.get("/api/evidence")
        assert r.status_code == 500
        detail = r.json()["detail"]
        assert "evidence_thesis.db" in detail  # 固定文案含文件名提示
        # 不应包含绝对路径、traceback、SQL 错误
        assert "Traceback" not in detail
        assert "sqlite3" not in detail.lower()
        assert "C:\\" not in detail
        assert "/tmp/" not in detail


# ---------------------------------------------------------------------------
# 多市场规范化
# ---------------------------------------------------------------------------

class TestMarketNormalization:
    def test_a_share_create_thesis(self, client):
        r = client.post("/api/thesis", json=_thesis_payload(subject_id="600519"))
        assert r.status_code == 200
        assert r.json()["data"]["thesis"]["market"] == "CN"

    def test_hk_stock_create_thesis(self, client):
        r = client.post("/api/thesis", json=_thesis_payload(subject_id="00700"))
        assert r.status_code == 200
        assert r.json()["data"]["thesis"]["market"] == "HK"

    def test_us_stock_create_thesis(self, client):
        r = client.post("/api/thesis", json=_thesis_payload(subject_id="AAPL"))
        assert r.status_code == 200
        assert r.json()["data"]["thesis"]["market"] == "US"

    def test_kr_stock_create_thesis(self, client):
        r = client.post("/api/thesis", json=_thesis_payload(subject_id="005930.KS"))
        assert r.status_code == 200
        assert r.json()["data"]["thesis"]["market"] == "KR"


# ---------------------------------------------------------------------------
# Evidence 联动（API 层）
# ---------------------------------------------------------------------------

class TestEvidenceCascadeApi:
    def test_evidence_edit_cascades_via_api(self, client):
        thesis = _create_thesis(client)
        ev = _create_evidence(client)
        tid = thesis["thesis"]["id"]
        client.post(f"/api/thesis/{tid}/evidence", json={
            "evidence_id": ev["id"], "stance": "support",
            "expected_revision": 1, "change_summary": "l",
        })  # rev=2

        # 编辑证据 → 联动 revision
        r = client.put(f"/api/evidence/{ev['id']}", json=_evidence_update_payload(claim="updated"))
        assert r.status_code == 200

        # thesis revision 应为 3
        r2 = client.get(f"/api/thesis/{tid}")
        assert r2.json()["data"]["thesis"]["current_revision"] == 3

    def test_evidence_delete_cascades_via_api(self, client):
        thesis = _create_thesis(client)
        ev = _create_evidence(client)
        tid = thesis["thesis"]["id"]
        client.post(f"/api/thesis/{tid}/evidence", json={
            "evidence_id": ev["id"], "stance": "support",
            "expected_revision": 1, "change_summary": "l",
        })  # rev=2

        client.delete(f"/api/evidence/{ev['id']}?confirm=true")

        r = client.get(f"/api/thesis/{tid}")
        assert r.json()["data"]["thesis"]["current_revision"] == 3
        assert len(r.json()["data"]["evidence_links"]) == 0


# ---------------------------------------------------------------------------
# Subject 筛选
# ---------------------------------------------------------------------------

class TestSubjectFilter:
    def test_list_evidence_by_subject(self, client):
        _create_evidence(client, subject_id="600519")
        _create_evidence(client, subject_id="000001")
        r = client.get("/api/evidence?subject_type=stock&subject_id=600519")
        assert r.json()["data"]["total"] == 1

    def test_list_thesis_by_subject(self, client):
        _create_thesis(client, subject_id="600519")
        _create_thesis(client, subject_id="000001")
        r = client.get("/api/thesis?subject_type=stock&subject_id=600519")
        assert r.json()["data"]["total"] == 1

    def test_list_thesis_by_status(self, client):
        t1 = _create_thesis(client)
        client.delete(f"/api/thesis/{t1['thesis']['id']}?confirm=true&expected_revision=1")
        _create_thesis(client, title="t2")
        r = client.get("/api/thesis?status=archived")
        assert r.json()["data"]["total"] == 1


# ---------------------------------------------------------------------------
# Diff 完整性
# ---------------------------------------------------------------------------

class TestDiffApi:
    def test_diff_evidence_added(self, client):
        thesis = _create_thesis(client)
        ev = _create_evidence(client)
        tid = thesis["thesis"]["id"]
        client.post(f"/api/thesis/{tid}/evidence", json={
            "evidence_id": ev["id"], "stance": "support",
            "expected_revision": 1, "change_summary": "l",
        })
        r = client.get(f"/api/thesis/{tid}/diff?from=1&to=2")
        assert r.status_code == 200
        diff = r.json()["data"]
        assert len(diff["evidence_added"]) == 1

    def test_diff_invalid_revision_returns_404(self, client):
        thesis = _create_thesis(client)
        r = client.get(f"/api/thesis/{thesis['thesis']['id']}/diff?from=1&to=99")
        assert r.status_code == 404
