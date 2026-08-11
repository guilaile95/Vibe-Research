"""Campaign ↔ Thesis Binding v0.1 专项测试（P0-S2C，确定性 Mock，不联网）。

service/API 层使用 fake evidence thesis provider（monkeypatch canonical read API），
不触碰 evidence_thesis 生产文件、不写 thesis。

覆盖：绑定基础 / subject match / immutability / ONE-THESIS-ONE-CAMPAIGN /
revision anchor / strategy snapshot / 多 Campaign 独立 / API contract / 错误脱敏。
"""
from __future__ import annotations

import re
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import campaign_router
import campaign_service
import campaign_store
from campaign_service import (
    CampaignInputError,
    CampaignNotFoundError,
    CampaignThesisBindingConflictError,
    ThesisBindingNotFoundError,
    ThesisNotFoundError,
    bind_campaign_thesis,
    create_campaign,
    get_campaign,
    get_campaign_thesis_binding,
    transition_campaign,
)

_TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$")


def _tid(seed: int = 0) -> str:
    return f"{seed:032x}"


def _thesis(
    thesis_id: str,
    *,
    subject_type="stock",
    subject_id="600519",
    revision=3,
    status="active",
    formal_state="frozen",
    strategy="SWING",
) -> dict:
    """fake thesis dict：S2D-E 起正式绑定要求 frozen + strategy 一致（SWING 默认）。"""
    return {
        "id": thesis_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "market": None,
        "title": "test thesis",
        "summary": "summary",
        "status": status,
        "core_claims": [],
        "catalysts": [],
        "risks": [],
        "invalidation_conditions": [],
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "current_revision": revision,
        "formal_state": formal_state,
        "strategy": strategy,
        "frozen_revision": revision,
    }


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "campaigns.sqlite3"
    monkeypatch.setenv("VIBE_RESEARCH_CAMPAIGN_DB", str(path))
    return path


@pytest.fixture
def fake_evidence(monkeypatch, tmp_path):
    """fake canonical read API（evidence_thesis_service.get_thesis / resolve_db_path）。"""
    theses: dict[str, dict] = {}

    def install(*, thesis_id: str | None = None, **kwargs) -> str:
        tid = thesis_id or _tid(len(theses) + 1)
        theses[tid] = _thesis(tid, **kwargs)
        return tid

    def fake_get_thesis(db_path_arg, thesis_id):
        return theses.get(thesis_id)

    monkeypatch.setattr(
        campaign_service.evidence_thesis_service, "get_thesis", fake_get_thesis
    )
    monkeypatch.setattr(
        campaign_service.evidence_thesis_service,
        "resolve_db_path",
        lambda: tmp_path / "evidence_thesis.db",
    )
    return SimpleNamespace(install=install, theses=theses)


def _campaign(code="600519", strategy="SWING"):
    return create_campaign(code, strategy)


# ---------------------------------------------------------------------------
# A. Binding Basic
# ---------------------------------------------------------------------------
def test_bind_success_fields_exact(db_path, fake_evidence):
    rec = _campaign(strategy="SWING")
    tid = fake_evidence.install(subject_type="stock", subject_id="600519", revision=3)
    binding = bind_campaign_thesis(rec["campaign_id"], tid)
    assert binding == {
        "campaign_id": rec["campaign_id"],
        "thesis_id": tid,
        "thesis_revision_at_bind": 3,
        "campaign_strategy_at_bind": "SWING",
        "bound_at": binding["bound_at"],
    }
    assert _TS_RE.fullmatch(binding["bound_at"])
    assert get_campaign_thesis_binding(rec["campaign_id"]) == binding  # durable


# ---------------------------------------------------------------------------
# B. Subject Contract
# ---------------------------------------------------------------------------
def test_bind_unknown_thesis_not_found(db_path, fake_evidence):
    rec = _campaign()
    with pytest.raises(ThesisNotFoundError):
        bind_campaign_thesis(rec["campaign_id"], _tid(99))  # fake 中不存在


def test_bind_sector_thesis_conflict(db_path, fake_evidence):
    rec = _campaign()
    tid = fake_evidence.install(subject_type="sector", subject_id="baijiu")
    with pytest.raises(CampaignThesisBindingConflictError):
        bind_campaign_thesis(rec["campaign_id"], tid)


def test_bind_theme_thesis_conflict(db_path, fake_evidence):
    rec = _campaign()
    tid = fake_evidence.install(subject_type="theme", subject_id="ai")
    with pytest.raises(CampaignThesisBindingConflictError):
        bind_campaign_thesis(rec["campaign_id"], tid)


def test_bind_stock_wrong_code_conflict(db_path, fake_evidence):
    rec = _campaign("600519")
    tid = fake_evidence.install(subject_type="stock", subject_id="000001")
    with pytest.raises(CampaignThesisBindingConflictError):
        bind_campaign_thesis(rec["campaign_id"], tid)


def test_bind_unknown_campaign_not_found(db_path, fake_evidence):
    tid = fake_evidence.install()
    with pytest.raises(CampaignNotFoundError):
        bind_campaign_thesis(f"campaign_{uuid.uuid4().hex}", tid)


def test_bind_invalid_thesis_id_format(db_path, fake_evidence):
    rec = _campaign()
    for bad in ("", "abc", "campaign_xyz", "0" * 31):
        with pytest.raises(CampaignInputError):
            bind_campaign_thesis(rec["campaign_id"], bad)


# ---------------------------------------------------------------------------
# C. Immutability
# ---------------------------------------------------------------------------
def test_second_bind_same_campaign_conflict(db_path, fake_evidence):
    rec = _campaign()
    tid1 = fake_evidence.install(thesis_id=_tid(1))
    first = bind_campaign_thesis(rec["campaign_id"], tid1)
    tid2 = fake_evidence.install(thesis_id=_tid(2))
    with pytest.raises(CampaignThesisBindingConflictError):
        bind_campaign_thesis(rec["campaign_id"], tid2)
    assert get_campaign_thesis_binding(rec["campaign_id"]) == first  # 未覆盖


def test_no_replace_delete_generic_apis(db_path):
    for name in ("update_campaign_thesis_binding", "replace_campaign_thesis",
                 "set_current_thesis", "delete_campaign_thesis_binding",
                 "generic_update"):
        assert not hasattr(campaign_service, name), f"forbidden path: {name}"


# ---------------------------------------------------------------------------
# D. One Thesis / One Campaign
# ---------------------------------------------------------------------------
def test_thesis_bound_elsewhere_conflict(db_path, fake_evidence):
    a = _campaign()
    # 同一 thesis 先绑 a 再绑 b：strategy gate 需与两个 Campaign 都一致，
    # 才能命中 ONE-THESIS-ONE-CAMPAIGN 的 store 冲突（保持原断言语义）。
    b = _campaign(strategy="SWING")
    tid = fake_evidence.install(thesis_id=_tid(1))
    first = bind_campaign_thesis(a["campaign_id"], tid)
    with pytest.raises(CampaignThesisBindingConflictError):
        bind_campaign_thesis(b["campaign_id"], tid)
    assert get_campaign_thesis_binding(a["campaign_id"]) == first  # 不变化


# ---------------------------------------------------------------------------
# E. Revision Anchor
# ---------------------------------------------------------------------------
def test_revision_anchor_immutable(db_path, fake_evidence):
    rec = _campaign()
    tid = fake_evidence.install(revision=3)
    binding = bind_campaign_thesis(rec["campaign_id"], tid)
    assert binding["thesis_revision_at_bind"] == 3
    # 后续 thesis revision 3→4→5：binding snapshot 不得变化
    fake_evidence.theses[tid]["current_revision"] = 5
    assert get_campaign_thesis_binding(rec["campaign_id"])["thesis_revision_at_bind"] == 3


@pytest.mark.parametrize("bad_revision", [0, -1, "3", None])
def test_bind_invalid_revision_conflict(db_path, fake_evidence, bad_revision):
    rec = _campaign()
    tid = fake_evidence.install(revision=bad_revision)
    with pytest.raises(CampaignThesisBindingConflictError):
        bind_campaign_thesis(rec["campaign_id"], tid)


def test_bind_does_not_call_thesis_write_api(db_path, fake_evidence, monkeypatch):
    """绑定全程只读 thesis：任何 thesis 写 API 被调用即测试失败。"""
    rec = _campaign()
    tid = fake_evidence.install()
    evidence = campaign_service.evidence_thesis_service
    for write_name in (
        "create_thesis", "update_thesis", "archive_thesis", "create_revision",
        "link_evidence", "create_evidence", "update_evidence",
        "soft_delete_evidence", "write_transaction",
    ):
        if hasattr(evidence, write_name):
            monkeypatch.setattr(
                evidence, write_name,
                lambda *a, **k: pytest.fail(f"thesis write API {write_name} called"),
            )
    binding = bind_campaign_thesis(rec["campaign_id"], tid)
    assert binding["thesis_id"] == tid


def test_no_thesis_write_imports_in_service():
    """campaign_service 命名空间不得包含 thesis 写函数。"""
    for name in ("create_thesis", "update_thesis", "archive_thesis",
                 "link_evidence", "create_evidence", "write_transaction"):
        assert name not in campaign_service.__dict__, f"thesis write import: {name}"


# ---------------------------------------------------------------------------
# F. Strategy Snapshot
# ---------------------------------------------------------------------------
def test_strategy_snapshot_survives_lifecycle(db_path, fake_evidence):
    """SWING Campaign 绑定后走完生命周期：strategy 与 binding snapshot 均保持 SWING。"""
    rec = _campaign(strategy="SWING")
    tid = fake_evidence.install(subject_type="stock", subject_id="600519")
    binding = bind_campaign_thesis(rec["campaign_id"], tid)
    assert binding["campaign_strategy_at_bind"] == "SWING"
    for frm, to in (
        ("DRAFT", "RESEARCHING"), ("RESEARCHING", "PRE-ENTRY"),
        ("PRE-ENTRY", "ACTIVE"), ("ACTIVE", "REDUCING"), ("REDUCING", "CLOSED"),
    ):
        campaign, _ = transition_campaign(rec["campaign_id"], frm, to)
        assert campaign["strategy"] == "SWING"
    assert get_campaign(rec["campaign_id"])["strategy"] == "SWING"
    assert get_campaign_thesis_binding(rec["campaign_id"])["campaign_strategy_at_bind"] == "SWING"


# ---------------------------------------------------------------------------
# G. Multi-Campaign
# ---------------------------------------------------------------------------
def test_multi_campaign_same_security_different_theses(db_path, fake_evidence):
    a = _campaign(strategy="MEDIUM")
    b = _campaign(strategy="SWING")
    ta = fake_evidence.install(
        thesis_id=_tid(1), subject_id="600519", strategy="MEDIUM"
    )
    tb = fake_evidence.install(thesis_id=_tid(2), subject_id="600519")
    ba = bind_campaign_thesis(a["campaign_id"], ta)
    bb = bind_campaign_thesis(b["campaign_id"], tb)
    assert ba["campaign_id"] == a["campaign_id"]
    assert bb["campaign_id"] == b["campaign_id"]
    assert get_campaign_thesis_binding(a["campaign_id"]) == ba
    assert get_campaign_thesis_binding(b["campaign_id"]) == bb


# ---------------------------------------------------------------------------
# API（test-only FastAPI app）
# ---------------------------------------------------------------------------
def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(campaign_router.router)
    return app


@pytest.fixture
def client(db_path, fake_evidence):
    return TestClient(make_app())


def _post_bind(client, cid, thesis_id):
    return client.post(
        f"/api/campaigns/{cid}/thesis-binding", json={"thesis_id": thesis_id}
    )


def test_api_bind_201_and_get_200(client, fake_evidence):
    rec = _campaign(strategy="SWING")
    tid = fake_evidence.install(subject_type="stock", subject_id="600519", revision=3)
    r = _post_bind(client, rec["campaign_id"], tid)
    assert r.status_code == 201
    data = r.json()["data"]
    assert set(data) == {
        "campaign_id", "thesis_id", "thesis_revision_at_bind",
        "campaign_strategy_at_bind", "bound_at",
    }
    assert data["thesis_id"] == tid
    assert data["thesis_revision_at_bind"] == 3
    assert data["campaign_strategy_at_bind"] == "SWING"
    g = client.get(f"/api/campaigns/{rec['campaign_id']}/thesis-binding")
    assert g.status_code == 200
    assert g.json()["data"] == data


def test_api_binding_unbound_404(client):
    r = client.get(f"/api/campaigns/{_tid(0) and 'campaign_' + '0' * 32}/thesis-binding")
    assert r.status_code == 404
    assert r.json()["detail"] == "Thesis Binding 不存在"


def test_api_bind_unknown_campaign_404(client, fake_evidence):
    tid = fake_evidence.install()
    r = _post_bind(client, "campaign_" + "0" * 32, tid)
    assert r.status_code == 404
    assert r.json()["detail"] == "Campaign 不存在"


def test_api_bind_unknown_thesis_404(client):
    rec = _campaign()
    r = _post_bind(client, rec["campaign_id"], _tid(99))
    assert r.status_code == 404
    assert r.json()["detail"] == "Thesis 不存在"


def test_api_bind_subject_mismatch_409(client, fake_evidence):
    rec = _campaign("600519")
    tid = fake_evidence.install(subject_type="stock", subject_id="000001")
    r = _post_bind(client, rec["campaign_id"], tid)
    assert r.status_code == 409
    assert r.json()["detail"] == "Thesis Binding 冲突"


def test_api_bind_duplicate_409(client, fake_evidence):
    rec = _campaign()
    tid = fake_evidence.install()
    assert _post_bind(client, rec["campaign_id"], tid).status_code == 201
    r = _post_bind(client, rec["campaign_id"], tid)
    assert r.status_code == 409
    assert r.json()["detail"] == "Thesis Binding 冲突"


def test_api_bind_invalid_thesis_id_422(client):
    rec = _campaign()
    for bad in ("", "abc", "0" * 31):
        r = _post_bind(client, rec["campaign_id"], bad)
        assert r.status_code == 422
        assert r.json()["detail"] == "Campaign 参数无效"


def test_api_bind_extra_strategy_field_422(client, fake_evidence):
    """绑定 body 不允许携带 strategy（extra=forbid → 422）。"""
    rec = _campaign(strategy="MEDIUM")
    tid = fake_evidence.install()
    r = client.post(
        f"/api/campaigns/{rec['campaign_id']}/thesis-binding",
        json={"thesis_id": tid, "strategy": "MEDIUM"},
    )
    assert r.status_code == 422
    assert client.get(f"/api/campaigns/{rec['campaign_id']}/thesis-binding").status_code == 404


def test_api_bind_unexpected_error_500_sanitized(client, monkeypatch):
    rec = _campaign()

    def boom(*a, **k):
        raise RuntimeError(
            "ProxyError https://secret-provider.example/token=abc "
            "C:\\Users\\evil\\campaigns.sqlite3 SELECT * FROM campaign_thesis_bindings"
        )

    monkeypatch.setattr(campaign_router.campaign_service, "bind_campaign_thesis", boom)
    r = _post_bind(client, rec["campaign_id"], _tid(1))
    assert r.status_code == 500
    body = str(r.json())
    assert r.json()["detail"] == "Campaign 服务暂不可用"
    for leaked in ("secret-provider", "token=abc", "Users", "sqlite3", "SELECT", "ProxyError", "Traceback"):
        assert leaked not in body


def test_api_no_patch_put_delete_binding(client):
    cid = "campaign_" + "0" * 32
    assert client.patch(f"/api/campaigns/{cid}/thesis-binding", json={}).status_code in (404, 405)
    assert client.put(f"/api/campaigns/{cid}/thesis-binding", json={}).status_code in (404, 405)
    assert client.delete(f"/api/campaigns/{cid}/thesis-binding").status_code in (404, 405)
