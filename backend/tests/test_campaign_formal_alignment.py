"""P0-PH2 S2D-E：Campaign Formal Alignment binding gates 专项测试。

确定性 Mock（monkeypatch evidence_thesis_service.get_thesis），不触碰
evidence_thesis 生产文件、不写 thesis。

覆盖：archived 409 / NEEDS_USER_COMPLETION（NULL/draft/confirmed/缺失）/
strategy mismatch 409（semantic conflict，detail 含两 strategy）/
422 / 404 保持 / gate 顺序（subject 校验优先）/
Freeze → Bind 成功路径 / 错误类层级（均为 binding conflict 子类）。
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
from campaign_service import (
    CampaignInputError,
    CampaignNotFoundError,
    CampaignThesisArchivedError,
    CampaignThesisBindingConflictError,
    CampaignThesisFormalIncompleteError,
    CampaignThesisStrategyConflictError,
    ThesisNotFoundError,
    bind_campaign_thesis,
    create_campaign,
    get_campaign_thesis_binding,
)


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
    include_formal=True,
) -> dict:
    thesis = {
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
    }
    if include_formal:
        thesis["formal_state"] = formal_state
        thesis["strategy"] = strategy
        thesis["frozen_revision"] = revision
    return thesis


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
# A. Formal Alignment Gates（service 层）
# ---------------------------------------------------------------------------

def test_bind_archived_thesis_conflict(db_path, fake_evidence):
    rec = _campaign()
    tid = fake_evidence.install(status="archived")
    with pytest.raises(CampaignThesisArchivedError):
        bind_campaign_thesis(rec["campaign_id"], tid)


def test_bind_archived_wins_over_formal_incomplete(db_path, fake_evidence):
    """archived gate 优先于 formal gate：archived + formal 缺失 → archived 冲突。"""
    rec = _campaign()
    tid = fake_evidence.install(status="archived", include_formal=False)
    with pytest.raises(CampaignThesisArchivedError):
        bind_campaign_thesis(rec["campaign_id"], tid)


@pytest.mark.parametrize(
    ("formal_state", "label"),
    [
        (None, "LEGACY"),
        ("draft", "DRAFT"),
        ("confirmed", "CONFIRMED"),
    ],
)
def test_bind_unfrozen_thesis_needs_user_completion(
    db_path, fake_evidence, formal_state, label
):
    rec = _campaign()
    tid = fake_evidence.install(formal_state=formal_state)
    with pytest.raises(CampaignThesisFormalIncompleteError) as exc_info:
        bind_campaign_thesis(rec["campaign_id"], tid)
    assert "NEEDS_USER_COMPLETION" in str(exc_info.value)


def test_bind_thesis_without_formal_fields_needs_user_completion(
    db_path, fake_evidence
):
    """fake thesis 无 formal 字段（S2C 旧形状）→ 归入 NEEDS_USER_COMPLETION。"""
    rec = _campaign()
    tid = fake_evidence.install(include_formal=False)
    with pytest.raises(CampaignThesisFormalIncompleteError):
        bind_campaign_thesis(rec["campaign_id"], tid)


def test_bind_frozen_thesis_missing_strategy_needs_user_completion(
    db_path, fake_evidence
):
    """frozen 但 strategy 缺失（LEGACY/不完整）→ NEEDS_USER_COMPLETION。"""
    rec = _campaign()
    tid = fake_evidence.install(formal_state="frozen", strategy=None)
    with pytest.raises(CampaignThesisFormalIncompleteError):
        bind_campaign_thesis(rec["campaign_id"], tid)


def test_bind_strategy_mismatch_semantic_conflict(db_path, fake_evidence):
    rec = _campaign(strategy="SWING")
    tid = fake_evidence.install(formal_state="frozen", strategy="SHORT")
    with pytest.raises(CampaignThesisStrategyConflictError) as exc_info:
        bind_campaign_thesis(rec["campaign_id"], tid)
    assert exc_info.value.thesis_strategy == "SHORT"
    assert exc_info.value.campaign_strategy == "SWING"
    assert "SHORT" in str(exc_info.value) and "SWING" in str(exc_info.value)


def test_bind_gate_errors_are_binding_conflict_subclasses(db_path, fake_evidence):
    """所有新 gate 错误保持 binding-conflict 语义（409 家族）。"""
    for cls in (
        CampaignThesisArchivedError,
        CampaignThesisFormalIncompleteError,
        CampaignThesisStrategyConflictError,
    ):
        assert issubclass(cls, CampaignThesisBindingConflictError)


def test_bind_subject_mismatch_still_wins_over_formal_gates(db_path, fake_evidence):
    """S2C subject 契约 gate 优先：sector/错误代码仍报 subject 冲突。"""
    rec = _campaign("600519")
    tid = fake_evidence.install(subject_type="sector", subject_id="baijiu")
    with pytest.raises(CampaignThesisBindingConflictError):
        bind_campaign_thesis(rec["campaign_id"], tid)
    tid2 = fake_evidence.install(thesis_id=_tid(2), subject_id="000001")
    with pytest.raises(CampaignThesisBindingConflictError):
        bind_campaign_thesis(rec["campaign_id"], tid2)


# ---------------------------------------------------------------------------
# B. Freeze → Bind 成功路径
# ---------------------------------------------------------------------------

def test_bind_frozen_matching_strategy_success(db_path, fake_evidence):
    rec = _campaign(strategy="MEDIUM")
    tid = fake_evidence.install(strategy="MEDIUM", revision=5)
    binding = bind_campaign_thesis(rec["campaign_id"], tid)
    assert binding == {
        "campaign_id": rec["campaign_id"],
        "thesis_id": tid,
        "thesis_revision_at_bind": 5,
        "campaign_strategy_at_bind": "MEDIUM",
        "bound_at": binding["bound_at"],
    }
    assert get_campaign_thesis_binding(rec["campaign_id"]) == binding


# ---------------------------------------------------------------------------
# C. 422 / 404 保持
# ---------------------------------------------------------------------------

def test_bind_invalid_thesis_id_still_422(db_path, fake_evidence):
    rec = _campaign()
    for bad in ("", "abc", "0" * 31):
        with pytest.raises(CampaignInputError):
            bind_campaign_thesis(rec["campaign_id"], bad)


def test_bind_unknown_thesis_still_404(db_path, fake_evidence):
    rec = _campaign()
    with pytest.raises(ThesisNotFoundError):
        bind_campaign_thesis(rec["campaign_id"], _tid(99))


def test_bind_unknown_campaign_still_404(db_path, fake_evidence):
    tid = fake_evidence.install()
    with pytest.raises(CampaignNotFoundError):
        bind_campaign_thesis(f"campaign_{uuid.uuid4().hex}", tid)


# ---------------------------------------------------------------------------
# D. API contract
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


def test_api_bind_archived_409(client, fake_evidence):
    rec = _campaign()
    tid = fake_evidence.install(status="archived")
    r = _post_bind(client, rec["campaign_id"], tid)
    assert r.status_code == 409
    assert r.json()["detail"] == "Thesis 已归档，不可绑定"


@pytest.mark.parametrize("formal_state", [None, "draft", "confirmed"])
def test_api_bind_unfrozen_409_needs_user_completion(
    client, fake_evidence, formal_state
):
    rec = _campaign()
    tid = fake_evidence.install(formal_state=formal_state)
    r = _post_bind(client, rec["campaign_id"], tid)
    assert r.status_code == 409
    assert r.json()["detail"] == "Thesis 未完成 Formal 化（NEEDS_USER_COMPLETION）"


def test_api_bind_strategy_mismatch_409_with_both_strategies(client, fake_evidence):
    rec = _campaign(strategy="SWING")
    tid = fake_evidence.install(formal_state="frozen", strategy="MEDIUM")
    r = _post_bind(client, rec["campaign_id"], tid)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "MEDIUM" in detail and "SWING" in detail
    assert "不一致" in detail


def test_api_bind_frozen_matching_201(client, fake_evidence):
    rec = _campaign(strategy="SWING")
    tid = fake_evidence.install(revision=2)
    r = _post_bind(client, rec["campaign_id"], tid)
    assert r.status_code == 201
    assert r.json()["data"]["thesis_revision_at_bind"] == 2
    assert r.json()["data"]["campaign_strategy_at_bind"] == "SWING"


def test_api_bind_invalid_thesis_id_still_422(client):
    rec = _campaign()
    r = _post_bind(client, rec["campaign_id"], "abc")
    assert r.status_code == 422
    assert r.json()["detail"] == "Campaign 参数无效"


def test_api_bind_unknown_thesis_still_404(client):
    rec = _campaign()
    r = _post_bind(client, rec["campaign_id"], _tid(99))
    assert r.status_code == 404
    assert r.json()["detail"] == "Thesis 不存在"


def test_api_bind_unknown_campaign_still_404(client, fake_evidence):
    tid = fake_evidence.install()
    r = _post_bind(client, "campaign_" + "0" * 32, tid)
    assert r.status_code == 404
    assert r.json()["detail"] == "Campaign 不存在"


_TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$")


def test_api_bind_success_response_has_stable_binding_shape(client, fake_evidence):
    rec = _campaign(strategy="SWING")
    tid = fake_evidence.install(revision=3)
    r = _post_bind(client, rec["campaign_id"], tid)
    data = r.json()["data"]
    assert set(data) == {
        "campaign_id", "thesis_id", "thesis_revision_at_bind",
        "campaign_strategy_at_bind", "bound_at",
    }
    assert _TS_RE.fullmatch(data["bound_at"])
