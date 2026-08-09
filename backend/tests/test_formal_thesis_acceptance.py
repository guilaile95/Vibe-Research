"""Formal Thesis Full-Lifecycle Black-Box Acceptance Suite v0.1（P0-PH2-QA1）。

这是长期保留的 product-level acceptance suite：用真实 Router / Service /
临时 SQLite（FastAPI TestClient）端到端验证 Formal Thesis 决策链：

Legacy Thesis → Formal Draft → Confirm → Freeze → Campaign Binding →
Current Thesis → Canonical Delta → Terminal Delta → Formal Archive。

原则：
- BLACK-BOX：优先走真实 HTTP API，不 mock 关键状态机；
- 所有 DB 只在 pytest tmp_path；显式防护绝不触碰真实用户数据库；
- 不修改任何 production 文件（本文件是唯一新增）；
- 发现明确 Frozen Contract violation 时保持 failing regression 并按
  BLOCKING_PRODUCT_DEFECT 报告，不 xfail、不修 production。

Journeys：
A  Full Happy Path（A1–A15，一次完整 golden journey）
B  Lifecycle Rejection Matrix（11 条非法迁移 → 409）
C  Confirmed / Frozen Mutation Closure（update/link/stance/unlink → 409 + 原子性）
D  Confirm Hard Gates（core_claims 3–5 / strategy / horizon ranges / 合法边界）
E  Campaign Binding Gates（semantic conflict / NEEDS_USER_COMPLETION / 404/422）
F  Current Thesis Fail-Closed（10 类 raw SQLite corruption → 500）
G  Revision Identity（revision_kind 时间线 + delta 与 revision 独立维度）
H  API Surface（openapi 真实 route：delta 无 PUT/PATCH/DELETE）
I  No Silent Migration（legacy v1 schema 打开不迁移）
"""

from __future__ import annotations

import copy
import hashlib
import os
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app as app_module
import evidence_thesis_service as svc
import evidence_thesis_store as store

client = TestClient(app_module.app)

STOCK_CODE = "600519"
SWING_HORIZON = {"unit": "TRADING_DAY", "min": 5, "max": 20, "anchor": "FREEZE_AT"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def env(tmp_path, monkeypatch):
    """每测试一个全新临时环境：两个独立 SQLite 落在 tmp_path。

    显式隔离防护：断言 DB 路径位于 tmp_path，且不位于任何真实用户数据路径。
    """
    ev_db = tmp_path / "evidence_thesis.db"
    camp_db = tmp_path / "campaigns.sqlite3"
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(ev_db))
    monkeypatch.setenv("VIBE_RESEARCH_CAMPAIGN_DB", str(camp_db))
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    store.initialize_store(ev_db)
    e = SimpleNamespace(ev_db=str(ev_db), camp_db=str(camp_db), tmp=str(tmp_path))
    _assert_tmp_only(e)
    return e


def _assert_tmp_only(env) -> None:
    """防护：所有测试 DB 必须位于 tmp_path，禁止真实用户数据路径。"""
    for path in (env.ev_db, env.camp_db):
        p = os.path.abspath(path)
        assert os.path.abspath(env.tmp) in p, f"db 不在 tmp_path: {p}"
        assert ".vibe-research" not in p, f"db 指向真实用户目录: {p}"


# ---------------------------------------------------------------------------
# HTTP helpers（走真实 router）
# ---------------------------------------------------------------------------

def _post(path: str, body: dict | None = None, expect: int = 200) -> dict:
    resp = client.post(path, json=body if body is not None else {})
    assert resp.status_code == expect, f"{path} -> {resp.status_code}: {resp.text}"
    payload = resp.json()
    return payload.get("data", payload)  # 2xx 返回 data；4xx/5xx 返回 detail 信封


def _get(path: str, expect: int = 200) -> dict:
    resp = client.get(path)
    assert resp.status_code == expect, f"{path} -> {resp.status_code}: {resp.text}"
    payload = resp.json()
    return payload.get("data", payload)


def _put(path: str, body: dict, expect: int = 200) -> dict:
    resp = client.put(path, json=body)
    assert resp.status_code == expect, f"{path} -> {resp.status_code}: {resp.text}"
    payload = resp.json()
    return payload.get("data", payload)


def _delete(path: str, expect: int = 200) -> dict:
    resp = client.delete(path)
    assert resp.status_code == expect, f"{path} -> {resp.status_code}: {resp.text}"
    payload = resp.json()
    return payload.get("data", payload)


def create_thesis(*, code: str = STOCK_CODE, claims: int = 3, title: str = "测试投资逻辑",
                  subject_type: str = "stock") -> dict:
    body = {
        "subject_type": subject_type,
        "subject_id": code,
        "title": title,
        "summary": "summary",
        "core_claims": [f"claim-{i}" for i in range(1, claims + 1)],
        "catalysts": ["catalyst-1"],
        "risks": ["risk-1"],
        "invalidation_conditions": ["invalid-1"],
    }
    return _post("/api/thesis", body, expect=200)


def create_evidence(*, code: str = STOCK_CODE, claim: str, classification: str = "fact",
                    confidence: str = "high") -> dict:
    body = {
        "subject_type": "stock",
        "subject_id": code,
        "evidence_type": "news",
        "claim": claim,
        "source_title": f"source-{claim[:8]}",
        "source_url": "https://example.com/x",
        "source_date": "2026-08-01",
        "accessed_at": "2026-08-01T10:00:00+00:00",
        "classification": classification,
        "confidence": confidence,
    }
    return _post("/api/evidence", body, expect=200)


def link_evidence(thesis_id: str, evidence_id: str, stance: str, expected_revision: int) -> dict:
    body = {"evidence_id": evidence_id, "stance": stance, "expected_revision": expected_revision}
    return _post(f"/api/thesis/{thesis_id}/evidence", body, expect=200)


def update_thesis(thesis_id: str, *, expected_revision: int, strategy: str | None = None,
                  horizon: dict | None = None, free_notes: str | None = None,
                  claims: list[str] | None = None, expect: int = 200) -> dict:
    body = {
        "title": "测试投资逻辑",
        "summary": "summary",
        "status": "active",
        "core_claims": claims or [f"claim-{i}" for i in range(1, 4)],
        "catalysts": ["catalyst-1"],
        "risks": ["risk-1"],
        "invalidation_conditions": ["invalid-1"],
        "expected_revision": expected_revision,
        "change_summary": "edit",
        "free_notes": free_notes,
        "strategy": strategy,
        "expected_horizon": horizon,
    }
    return _put(f"/api/thesis/{thesis_id}", body, expect=expect)


def begin_formalization(thesis_id: str, expect: int = 200) -> dict:
    return _post(f"/api/thesis/{thesis_id}/begin-formalization", expect=expect)


def confirm_formalization(thesis_id: str, expect: int = 200) -> dict:
    return _post(f"/api/thesis/{thesis_id}/confirm", expect=expect)


def freeze_formalization(thesis_id: str, expected_revision: int, expect: int = 200) -> dict:
    return _post(f"/api/thesis/{thesis_id}/freeze", {"expected_revision": expected_revision},
                 expect=expect)


def archive_formal(thesis_id: str, expected_revision: int, expect: int = 200) -> dict:
    return _post(f"/api/thesis/{thesis_id}/archive", {"expected_revision": expected_revision},
                 expect=expect)


def create_delta(thesis_id: str, delta_state: str, reason: str,
                 evidence_ids: list[str] | None = None,
                 base_revision: int | None = None, expect: int = 200) -> dict:
    body = {"delta_state": delta_state, "reason": reason, "evidence_ids": evidence_ids or []}
    if base_revision is not None:
        body["base_revision"] = base_revision
    return _post(f"/api/thesis/{thesis_id}/deltas", body, expect=expect)


def list_deltas(thesis_id: str, expect: int = 200) -> dict:
    return _get(f"/api/thesis/{thesis_id}/deltas", expect=expect)


def list_revisions(thesis_id: str, expect: int = 200) -> dict:
    return _get(f"/api/thesis/{thesis_id}/revisions", expect=expect)


def get_revision(thesis_id: str, revision_number: int, expect: int = 200) -> dict:
    """GET /api/thesis/{id}/revisions/{n}：revision_kind 的唯一黑盒来源。"""
    return _get(f"/api/thesis/{thesis_id}/revisions/{revision_number}", expect=expect)


def get_thesis(thesis_id: str, expect: int = 200) -> dict:
    return _get(f"/api/thesis/{thesis_id}", expect=expect)


def create_campaign(code: str, strategy: str, expect: int = 201) -> dict:
    return _post("/api/campaigns", {"security_code": code, "strategy": strategy}, expect=expect)


def bind_campaign(campaign_id: str, thesis_id: str, expect: int = 201) -> dict:
    return _post(f"/api/campaigns/{campaign_id}/thesis-binding", {"thesis_id": thesis_id},
                 expect=expect)


def current_thesis(campaign_id: str, expect: int = 200) -> dict:
    return _get(f"/api/campaigns/{campaign_id}/current-thesis", expect=expect)


def _build_frozen_thesis(*, code: str = STOCK_CODE, strategy: str = "SWING",
                         horizon: dict | None = None) -> dict:
    """完整走到 frozen（create→begin→edit→confirm→freeze），返回关键状态。"""
    agg = create_thesis(code=code)
    thesis_id = agg["thesis"]["id"]
    begin_formalization(thesis_id)
    # begin 不 bump：edit 时 expected_revision 仍为 1
    update_thesis(thesis_id, expected_revision=1, strategy=strategy,
                  horizon=horizon or SWING_HORIZON, claims=[f"c{i}" for i in range(1, 4)])
    confirmed = confirm_formalization(thesis_id)
    confirmed_rev = confirmed["thesis"]["current_revision"]
    frozen = freeze_formalization(thesis_id, expected_revision=confirmed_rev)
    return {
        "thesis_id": thesis_id,
        "frozen_revision": frozen["thesis"]["frozen_revision"],
        "current_revision": frozen["thesis"]["current_revision"],
    }


def _snapshot_evidence_claims(snapshot: dict) -> list[str]:
    """从 snapshot（顶层 evidence_links）提取 claim 列表。"""
    return [e["claim"] for e in snapshot.get("evidence_links", [])]


# ---------------------------------------------------------------------------
# Journey A — Full Happy Path（A1–A15）
# ---------------------------------------------------------------------------

def test_a_full_golden_path(env):  # noqa: ARG001 — env 保证 tmp 隔离
    # ---- A1. Create Legacy Thesis ----
    agg = create_thesis(claims=3)
    thesis_id = agg["thesis"]["id"]
    assert agg["thesis"]["formal_state"] is None
    revisions = list_revisions(thesis_id)
    assert revisions["total"] >= 1
    assert revisions["items"][0]["revision_number"] == 1

    # ---- A2. Create + link 3 evidence（support / oppose 不同 stance）----
    ev_support = create_evidence(claim="support-evidence-1")
    ev_oppose = create_evidence(claim="oppose-evidence-1", classification="inference", confidence="medium")
    ev_neutral = create_evidence(claim="neutral-evidence-1", confidence="low")
    link_evidence(thesis_id, ev_support["id"], "support", expected_revision=1)
    link_evidence(thesis_id, ev_oppose["id"], "oppose", expected_revision=2)
    link_evidence(thesis_id, ev_neutral["id"], "neutral", expected_revision=3)
    pre_confirm_snapshot = get_thesis(thesis_id)
    pre_confirm_claims = sorted(_snapshot_evidence_claims(pre_confirm_snapshot))
    assert sorted(pre_confirm_claims) == [
        "neutral-evidence-1", "oppose-evidence-1", "support-evidence-1",
    ]

    # ---- A3. Begin Formalization：draft + started_at，NO revision bump ----
    before = get_thesis(thesis_id)["thesis"]["current_revision"]
    began = begin_formalization(thesis_id)
    assert began["thesis"]["formal_state"] == "draft"
    assert began["thesis"]["formalization_started_at"] is not None
    assert began["thesis"]["current_revision"] == before  # BEGIN_FORMALIZATION_REVISION_BUMP = NO

    # ---- A4. Complete Formal Draft：SWING + horizon + free_notes + 3 claims ----
    edited = update_thesis(
        thesis_id, expected_revision=before, strategy="SWING",
        horizon=dict(SWING_HORIZON), free_notes="free-notes-1",
        claims=[f"core-{i}" for i in range(1, 4)],
    )
    assert edited["thesis"]["formal_state"] == "draft"
    assert edited["thesis"]["strategy"] == "SWING"
    assert edited["thesis"]["expected_horizon"] == SWING_HORIZON
    assert edited["thesis"]["free_notes"] == "free-notes-1"
    draft_rev = edited["thesis"]["current_revision"]
    assert get_revision(thesis_id, draft_rev)["revision_kind"] == "CONTENT"  # A4: draft edit → CONTENT

    # ---- A5. Confirm：confirmed + confirmed_at，NO revision bump ----
    confirmed = confirm_formalization(thesis_id)
    assert confirmed["thesis"]["formal_state"] == "confirmed"
    assert confirmed["thesis"]["confirmed_at"] is not None
    confirmed_rev = confirmed["thesis"]["current_revision"]
    assert confirmed_rev == draft_rev  # CONFIRMED_REVISION = N（不 bump）

    # ---- A6. Evidence Mutation After Confirm：不得 bump thesis revision ----
    _put(f"/api/evidence/{ev_support['id']}", {
        "evidence_type": "news",
        "claim": "support-evidence-MUTATED",
        "source_title": "source-mutated",
        "source_url": "https://example.com/mutated",
        "source_date": "2026-08-02",
        "accessed_at": "2026-08-02T10:00:00+00:00",
        "classification": "inference",
        "confidence": "low",
    }, expect=200)
    _delete(f"/api/evidence/{ev_neutral['id']}?confirm=true", expect=200)  # soft-delete
    still = get_thesis(thesis_id)
    assert still["thesis"]["current_revision"] == confirmed_rev  # CONFIRMED_CONTENT_LOCK

    # ---- A7. Freeze：expected_revision=N → frozen_revision=N+1 / FORMAL_FREEZE ----
    frozen = freeze_formalization(thesis_id, expected_revision=confirmed_rev)
    frozen_rev = frozen["thesis"]["frozen_revision"]
    assert frozen["thesis"]["formal_state"] == "frozen"
    assert frozen_rev == confirmed_rev + 1
    assert frozen["thesis"]["current_revision"] == frozen_rev
    revisions = list_revisions(thesis_id)
    assert get_revision(thesis_id, frozen_rev)["revision_kind"] == "FORMAL_FREEZE"
    # Frozen Original 来自 confirm 时 authoritative snapshot（evidence 是 pre-mutation 的）
    frozen_claims = sorted(_snapshot_evidence_claims(frozen))
    assert frozen_claims == ["neutral-evidence-1", "oppose-evidence-1", "support-evidence-1"]
    assert "support-evidence-MUTATED" not in frozen_claims  # 不是 A6 后的 live evidence

    # ---- A8. Campaign + Bind ----
    campaign = create_campaign(STOCK_CODE, "SWING")
    campaign_id = campaign["campaign_id"]
    binding = bind_campaign(campaign_id, thesis_id)
    assert binding["campaign_strategy_at_bind"] == "SWING"
    assert binding["thesis_revision_at_bind"] == frozen_rev  # audit fact

    # ---- A9. Current Thesis：READY，Original 来自 frozen_revision ----
    projection = current_thesis(campaign_id)
    assert projection["formal_status"] == "READY"
    assert projection["ready"] is True
    assert projection["frozen_revision"] == frozen_rev
    assert projection["binding"]["thesis_revision_at_bind"] == frozen_rev
    assert sorted(_snapshot_evidence_claims(projection["original_snapshot"])) == frozen_claims
    assert projection["effective_state"] == "STABLE"  # 无 delta

    # ---- A10. Canonical Delta STRENGTHENED + evidence snapshot 固化 ----
    delta1 = create_delta(thesis_id, "STRENGTHENED", "strengthened-by-evidence",
                          evidence_ids=[ev_support["id"]])
    assert delta1["delta_sequence"] == 1
    assert delta1["base_revision"] == frozen_rev
    assert delta1["evidence_links"][0]["claim"] == "support-evidence-MUTATED"  # 创建时固化

    # ---- A11. Mutate evidence after delta：历史 snapshot 不变 ----
    _put(f"/api/evidence/{ev_support['id']}", {
        "evidence_type": "news",
        "claim": "support-evidence-MUTATED-AGAIN",
        "source_title": "source-again",
        "source_url": "https://example.com/again",
        "source_date": "2026-08-03",
        "accessed_at": "2026-08-03T10:00:00+00:00",
        "classification": "fact",
        "confidence": "high",
    }, expect=200)
    after = list_deltas(thesis_id)
    assert after["items"][0]["evidence_links"][0]["claim"] == "support-evidence-MUTATED"
    projection_again = current_thesis(campaign_id)
    assert projection_again["deltas"][0]["evidence_links"][0]["claim"] == "support-evidence-MUTATED"

    # ---- A12. Additional Delta WEAKENED：sequence=2 / effective=WEAKENED ----
    delta2 = create_delta(thesis_id, "WEAKENED", "weakened-after-recheck")
    assert delta2["delta_sequence"] == 2
    projection3 = current_thesis(campaign_id)
    assert projection3["effective_state"] == "WEAKENED"

    # ---- A13. Terminal Delta INVALIDATED（sequence 3）+ 后续 append → 409 ----
    delta3 = create_delta(thesis_id, "INVALIDATED", "invalidated-terminal")
    assert delta3["delta_sequence"] == 3
    projection4 = current_thesis(campaign_id)
    assert projection4["effective_state"] == "INVALIDATED"
    create_delta(thesis_id, "STABLE", "post-terminal-append",
                 expect=409)  # POST_TERMINAL_APPEND = REJECTED

    # ---- A14. Formal Archive：FROZEN ACTIVE → FROZEN ARCHIVED ----
    archived = archive_formal(thesis_id, expected_revision=frozen_rev)
    assert archived["thesis"]["status"] == "archived"
    assert archived["thesis"]["current_revision"] == frozen_rev + 1
    assert archived["thesis"]["frozen_revision"] == frozen_rev  # frozen_revision 不变
    assert get_revision(thesis_id, frozen_rev + 1)["revision_kind"] == "FORMAL_ARCHIVE"
    assert sorted(_snapshot_evidence_claims(archived)) == frozen_claims  # Formal Original 内容不变

    # ---- A15. Existing Binding After Archive：仍可 projection ----
    final = current_thesis(campaign_id)
    assert final["formal_status"] == "READY"
    assert final["frozen_revision"] == frozen_rev
    assert sorted(_snapshot_evidence_claims(final["original_snapshot"])) == frozen_claims
    assert final["effective_state"] == "INVALIDATED"  # 来自 Delta，不是 archive status


def test_a1_new_revision_must_be_content(env):  # noqa: ARG001
    """最终冻结合同：新建 thesis 的 revision 1 必须是 CONTENT（黑盒 API）。

    当前若仍为 legacy NULL kind → 按 BLOCKING_PRODUCT_DEFECT 报告，不弱化。
    """
    agg = create_thesis(claims=3)
    thesis_id = agg["thesis"]["id"]
    assert get_revision(thesis_id, 1)["revision_number"] == 1
    assert get_revision(thesis_id, 1)["revision_kind"] == "CONTENT"


# ---------------------------------------------------------------------------
# Journey B — Lifecycle Rejection Matrix
# ---------------------------------------------------------------------------

def test_b1_legacy_confirm_rejected(env):  # noqa: ARG001
    agg = create_thesis()
    confirm_formalization(agg["thesis"]["id"], expect=409)


def test_b2_legacy_freeze_rejected(env):  # noqa: ARG001
    agg = create_thesis()
    freeze_formalization(agg["thesis"]["id"], expected_revision=1, expect=409)


def test_b3_begin_formalization_twice_rejected(env):  # noqa: ARG001
    agg = create_thesis()
    thesis_id = agg["thesis"]["id"]
    begin_formalization(thesis_id)
    begin_formalization(thesis_id, expect=409)


def test_b4_draft_freeze_rejected(env):  # noqa: ARG001
    agg = create_thesis()
    thesis_id = agg["thesis"]["id"]
    begin_formalization(thesis_id)
    freeze_formalization(thesis_id, expected_revision=1, expect=409)


def test_b5_confirmed_begin_formalization_rejected(env):  # noqa: ARG001
    agg = create_thesis()
    thesis_id = agg["thesis"]["id"]
    begin_formalization(thesis_id)
    update_thesis(thesis_id, expected_revision=1, strategy="SWING", horizon=dict(SWING_HORIZON))
    confirm_formalization(thesis_id)
    begin_formalization(thesis_id, expect=409)


def test_b6_confirmed_confirm_again_rejected(env):  # noqa: ARG001
    agg = create_thesis()
    thesis_id = agg["thesis"]["id"]
    begin_formalization(thesis_id)
    update_thesis(thesis_id, expected_revision=1, strategy="SWING", horizon=dict(SWING_HORIZON))
    confirm_formalization(thesis_id)
    confirm_formalization(thesis_id, expect=409)


def test_b7_frozen_confirm_rejected(env):  # noqa: ARG001
    state = _build_frozen_thesis()
    confirm_formalization(state["thesis_id"], expect=409)


def test_b8_frozen_freeze_again_rejected(env):  # noqa: ARG001
    state = _build_frozen_thesis()
    freeze_formalization(state["thesis_id"], expected_revision=state["frozen_revision"], expect=409)


def test_b9_draft_legacy_archive_rejected(env):  # noqa: ARG001
    agg = create_thesis()
    thesis_id = agg["thesis"]["id"]
    begin_formalization(thesis_id)
    _delete(f"/api/thesis/{thesis_id}?confirm=true&expected_revision=1", expect=409)


def test_b10_confirmed_legacy_archive_rejected(env):  # noqa: ARG001
    agg = create_thesis()
    thesis_id = agg["thesis"]["id"]
    begin_formalization(thesis_id)
    update_thesis(thesis_id, expected_revision=1, strategy="SWING", horizon=dict(SWING_HORIZON))
    confirm_formalization(thesis_id)
    confirmed_rev = get_thesis(thesis_id)["thesis"]["current_revision"]
    _delete(f"/api/thesis/{thesis_id}?confirm=true&expected_revision={confirmed_rev}", expect=409)


def test_b11_frozen_legacy_archive_rejected(env):  # noqa: ARG001
    """FROZEN 走 legacy DELETE 归档 → 409；必须使用 Formal Archive endpoint。"""
    state = _build_frozen_thesis()
    _delete(f"/api/thesis/{state['thesis_id']}?confirm=true"
            f"&expected_revision={state['frozen_revision']}", expect=409)


# ---------------------------------------------------------------------------
# Journey C — Confirmed / Frozen Mutation Closure（409 + 原子性）
# ---------------------------------------------------------------------------

def test_c_confirmed_mutation_closure(env):  # noqa: ARG001
    agg = create_thesis(claims=3)
    thesis_id = agg["thesis"]["id"]
    ev = create_evidence(claim="ev-for-closure")
    link_evidence(thesis_id, ev["id"], "support", expected_revision=1)
    rev_after_link = get_thesis(thesis_id)["thesis"]["current_revision"]
    begin_formalization(thesis_id)
    update_thesis(thesis_id, expected_revision=rev_after_link, strategy="SWING",
                  horizon=dict(SWING_HORIZON))
    confirm_formalization(thesis_id)
    confirmed_rev = get_thesis(thesis_id)["thesis"]["current_revision"]
    link_count = len(get_thesis(thesis_id)["evidence_links"])

    # update_thesis → 409
    update_thesis(thesis_id, expected_revision=confirmed_rev, strategy="SWING",
                  horizon=dict(SWING_HORIZON), expect=409)
    # link_evidence → 409
    _post(f"/api/thesis/{thesis_id}/evidence",
          {"evidence_id": ev["id"], "stance": "neutral", "expected_revision": confirmed_rev},
          expect=409)
    # update_stance → 409
    _put(f"/api/thesis/{thesis_id}/evidence/{ev['id']}",
         {"stance": "oppose", "expected_revision": confirmed_rev}, expect=409)
    # unlink_evidence → 409
    _delete(f"/api/thesis/{thesis_id}/evidence/{ev['id']}?expected_revision={confirmed_rev}",
            expect=409)

    # REJECTION IS ATOMIC：revision / link count / stance 全部不变
    after = get_thesis(thesis_id)
    assert after["thesis"]["current_revision"] == confirmed_rev
    assert len(after["evidence_links"]) == link_count
    assert after["evidence_links"][0]["stance"] == "support"


def test_c_frozen_mutation_closure(env):  # noqa: ARG001
    agg = create_thesis(claims=3)
    thesis_id = agg["thesis"]["id"]
    ev = create_evidence(claim="ev-for-frozen-closure")
    link_evidence(thesis_id, ev["id"], "support", expected_revision=1)
    rev_after_link = get_thesis(thesis_id)["thesis"]["current_revision"]
    begin_formalization(thesis_id)
    update_thesis(thesis_id, expected_revision=rev_after_link, strategy="SWING",
                  horizon=dict(SWING_HORIZON))
    confirm_formalization(thesis_id)
    confirmed_rev = get_thesis(thesis_id)["thesis"]["current_revision"]
    freeze_formalization(thesis_id, expected_revision=confirmed_rev)
    frozen_rev = get_thesis(thesis_id)["thesis"]["frozen_revision"]

    update_thesis(thesis_id, expected_revision=frozen_rev, strategy="SWING",
                  horizon=dict(SWING_HORIZON), expect=409)
    _post(f"/api/thesis/{thesis_id}/evidence",
          {"evidence_id": ev["id"], "stance": "neutral", "expected_revision": frozen_rev},
          expect=409)
    _put(f"/api/thesis/{thesis_id}/evidence/{ev['id']}",
         {"stance": "oppose", "expected_revision": frozen_rev}, expect=409)
    _delete(f"/api/thesis/{thesis_id}/evidence/{ev['id']}?expected_revision={frozen_rev}",
            expect=409)

    after = get_thesis(thesis_id)
    assert after["thesis"]["current_revision"] == frozen_rev
    assert len(after["evidence_links"]) == 1
    assert after["evidence_links"][0]["stance"] == "support"


# ---------------------------------------------------------------------------
# Journey D — Confirm Hard Gates
# ---------------------------------------------------------------------------

def _draft_ready_thesis(*, claims: int = 3, strategy: str = "SWING",
                        horizon: dict | None = None) -> str:
    """创建并完成 draft 编辑，返回 thesis_id（尚未 confirm）。"""
    agg = create_thesis(claims=3)
    thesis_id = agg["thesis"]["id"]
    begin_formalization(thesis_id)
    update_thesis(thesis_id, expected_revision=1, strategy=strategy,
                  horizon=horizon or dict(SWING_HORIZON), claims=[f"c{i}" for i in range(1, claims + 1)])
    return thesis_id


def test_d_core_claims_too_few(env):  # noqa: ARG001
    thesis_id = _draft_ready_thesis()
    agg = get_thesis(thesis_id)
    update_thesis(thesis_id, expected_revision=agg["thesis"]["current_revision"],
                  claims=["c1", "c2"])  # 2 claims（合法数量 update）
    confirm_formalization(thesis_id, expect=422)  # confirm 硬门：< 3 → reject


def test_d_core_claims_too_many(env):  # noqa: ARG001
    thesis_id = _draft_ready_thesis()
    agg = get_thesis(thesis_id)
    update_thesis(thesis_id, expected_revision=agg["thesis"]["current_revision"],
                  claims=[f"c{i}" for i in range(1, 7)])  # 6 claims
    confirm_formalization(thesis_id, expect=422)


def test_d_strategy_missing(env):  # noqa: ARG001
    agg = create_thesis(claims=3)
    thesis_id = agg["thesis"]["id"]
    begin_formalization(thesis_id)
    # 只写 free_notes，不提供 strategy/horizon
    update_thesis(thesis_id, expected_revision=1, free_notes="notes", strategy=None, horizon=None)
    confirm_formalization(thesis_id, expect=422)


def test_d_expected_horizon_missing(env):  # noqa: ARG001
    agg = create_thesis(claims=3)
    thesis_id = agg["thesis"]["id"]
    begin_formalization(thesis_id)
    update_thesis(thesis_id, expected_revision=1, strategy="SWING", horizon=None)
    confirm_formalization(thesis_id, expect=422)


@pytest.mark.parametrize("strategy,horizon", [
    ("SHORT", {"unit": "TRADING_DAY", "min": 1, "max": 180, "anchor": "FREEZE_AT"}),   # SHORT + 180 days
    ("SWING", {"unit": "TRADING_DAY", "min": 5, "max": 200, "anchor": "FREEZE_AT"}),   # SWING + 200 days
    ("MEDIUM", {"unit": "TRADING_DAY", "min": 20, "max": 40, "anchor": "FREEZE_AT"}),  # MEDIUM + 20 days
])
def test_d_horizon_out_of_range_rejected(env, strategy, horizon):  # noqa: ARG001
    agg = create_thesis(claims=3)
    thesis_id = agg["thesis"]["id"]
    begin_formalization(thesis_id)
    # draft 编辑阶段即拦截非法 range（_validate_formal_fields）
    update_thesis(thesis_id, expected_revision=1, strategy=strategy, horizon=horizon, expect=422)


@pytest.mark.parametrize("strategy,horizon", [
    ("SHORT", {"unit": "TRADING_DAY", "min": 1, "max": 10, "anchor": "FREEZE_AT"}),    # 合法边界
    ("SWING", {"unit": "TRADING_DAY", "min": 5, "max": 45, "anchor": "FREEZE_AT"}),
    ("MEDIUM", {"unit": "TRADING_DAY", "min": 40, "max": 252, "anchor": "FREEZE_AT"}),
    ("SHORT", {"unit": "TRADING_DAY", "min": 5, "max": 10, "anchor": "FREEZE_AT"}),    # 合法 overlap
    ("SWING", {"unit": "TRADING_DAY", "min": 5, "max": 10, "anchor": "FREEZE_AT"}),
    ("SWING", {"unit": "TRADING_DAY", "min": 40, "max": 45, "anchor": "FREEZE_AT"}),
    ("MEDIUM", {"unit": "TRADING_DAY", "min": 40, "max": 45, "anchor": "FREEZE_AT"}),
])
def test_d_valid_horizon_accepted(env, strategy, horizon):  # noqa: ARG001
    thesis_id = _draft_ready_thesis(strategy=strategy, horizon=horizon)
    confirmed = confirm_formalization(thesis_id)
    assert confirmed["thesis"]["formal_state"] == "confirmed"


# ---------------------------------------------------------------------------
# Journey E — Campaign Binding Gates
# ---------------------------------------------------------------------------

def test_e_campaign_short_thesis_swing_semantic_conflict(env):  # noqa: ARG001
    state = _build_frozen_thesis(strategy="SWING")
    campaign = create_campaign(STOCK_CODE, "SHORT")
    bind_campaign(campaign["campaign_id"], state["thesis_id"], expect=409)


def test_e_unfrozen_thesis_needs_user_completion(env):  # noqa: ARG001
    agg = create_thesis(claims=3)
    thesis_id = agg["thesis"]["id"]
    begin_formalization(thesis_id)
    update_thesis(thesis_id, expected_revision=1, strategy="SWING", horizon=dict(SWING_HORIZON))
    # confirmed（未 freeze）→ NEEDS_USER_COMPLETION 409
    confirm_formalization(thesis_id)
    campaign = create_campaign(STOCK_CODE, "SWING")
    bind_campaign(campaign["campaign_id"], thesis_id, expect=409)


def test_e_archived_thesis_rejected(env):  # noqa: ARG001
    state = _build_frozen_thesis()
    archive_formal(state["thesis_id"], expected_revision=state["frozen_revision"])
    campaign = create_campaign(STOCK_CODE, "SWING")
    bind_campaign(campaign["campaign_id"], state["thesis_id"], expect=409)


def test_e_subject_id_mismatch_rejected(env):  # noqa: ARG001
    state = _build_frozen_thesis(code=STOCK_CODE)
    campaign = create_campaign("000001", "SWING")  # security_code 与 thesis.subject_id 不一致
    bind_campaign(campaign["campaign_id"], state["thesis_id"], expect=409)


def test_e_non_stock_thesis_rejected(env):  # noqa: ARG001
    """非 stock thesis（sector）完整走到 frozen 后绑定到 stock campaign → 409。"""
    agg = create_thesis(code="sector-ai", subject_type="sector")
    thesis_id = agg["thesis"]["id"]
    begin_formalization(thesis_id)
    update_thesis(thesis_id, expected_revision=1, strategy="SWING", horizon=dict(SWING_HORIZON))
    confirm_formalization(thesis_id)
    confirmed_rev = get_thesis(thesis_id)["thesis"]["current_revision"]
    freeze_formalization(thesis_id, expected_revision=confirmed_rev)
    campaign = create_campaign(STOCK_CODE, "SWING")
    bind_campaign(campaign["campaign_id"], thesis_id, expect=409)


def test_e_missing_thesis_404(env):  # noqa: ARG001
    campaign = create_campaign(STOCK_CODE, "SWING")
    bind_campaign(campaign["campaign_id"], "f" * 32, expect=404)


def test_e_invalid_thesis_id_422(env):  # noqa: ARG001
    campaign = create_campaign(STOCK_CODE, "SWING")
    bind_campaign(campaign["campaign_id"], "not-a-32hex-id", expect=422)


def test_e_failed_binding_leaves_no_binding_row(env):  # noqa: ARG001
    state = _build_frozen_thesis(strategy="SWING")
    campaign = create_campaign(STOCK_CODE, "SHORT")
    bind_campaign(campaign["campaign_id"], state["thesis_id"], expect=409)
    _get(f"/api/campaigns/{campaign['campaign_id']}/thesis-binding", expect=404)  # 无 binding row


# ---------------------------------------------------------------------------
# Journey F — Current Thesis Fail-Closed（raw SQLite corruption → 500）
# ---------------------------------------------------------------------------

def _corrupt(env, sql: str, params: tuple = ()) -> None:
    with sqlite3.connect(env.ev_db) as conn:
        conn.execute(sql, params)
        conn.commit()


def _frozen_with_deltas(env, *, count: int = 2, terminal: bool = False):
    """建 frozen thesis + count 个 delta，返回 thesis_id/campaign_id/frozen_revision。"""
    state = _build_frozen_thesis()
    thesis_id = state["thesis_id"]
    for i in range(1, count + 1):
        state_name = "STABLE" if i < count else ("INVALIDATED" if terminal else "STABLE")
        create_delta(thesis_id, state_name, f"delta-{i}")
    campaign = create_campaign(STOCK_CODE, "SWING")
    campaign_id = campaign["campaign_id"]
    bind_campaign(campaign_id, thesis_id)
    return {"thesis_id": thesis_id, "campaign_id": campaign_id,
            "frozen_revision": state["frozen_revision"]}


def test_f_revision_gap_fails_closed(env):  # noqa: ARG001
    ctx = _frozen_with_deltas(env, count=1)
    _corrupt(env, "DELETE FROM thesis_revisions WHERE revision_number=2")
    current_thesis(ctx["campaign_id"], expect=500)


def test_f_future_orphan_revision_fails_closed(env):  # noqa: ARG001
    ctx = _frozen_with_deltas(env, count=1)
    frozen_rev = ctx["frozen_revision"]
    snapshot = get_thesis(ctx["thesis_id"])
    _corrupt(
        env,
        "INSERT INTO thesis_revisions (id, thesis_id, revision_number, snapshot, change_summary, created_at, revision_kind)"
        " VALUES (?, ?, ?, ?, 'orphan', '2026-08-10T00:00:00+00:00', 'CONTENT')",
        ("0" * 32, ctx["thesis_id"], frozen_rev + 2, sqlite3_json(snapshot)),
    )
    current_thesis(ctx["campaign_id"], expect=500)


def sqlite3_json(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


def test_f_historical_snapshot_empty_fails_closed(env):  # noqa: ARG001
    ctx = _frozen_with_deltas(env, count=1)
    _corrupt(env, "UPDATE thesis_revisions SET snapshot='[]' WHERE revision_number=1")
    current_thesis(ctx["campaign_id"], expect=500)


def test_f_historical_revision_kind_wrong_fails_closed(env):  # noqa: ARG001
    ctx = _frozen_with_deltas(env, count=1)
    # revision 1 是 CONTENT；改成合法枚举但错误位置的 FORMAL_FREEZE → corrupted
    _corrupt(env, "UPDATE thesis_revisions SET revision_kind='FORMAL_FREEZE' WHERE revision_number=1")
    current_thesis(ctx["campaign_id"], expect=500)


def test_f_frozen_revision_kind_not_freeeze_fails_closed(env):  # noqa: ARG001
    ctx = _frozen_with_deltas(env, count=1)
    _corrupt(env, "UPDATE thesis_revisions SET revision_kind='CONTENT' WHERE revision_number=?",
             (ctx["frozen_revision"],))
    current_thesis(ctx["campaign_id"], expect=500)


def test_f_archive_revision_kind_not_archive_fails_closed(env):  # noqa: ARG001
    ctx = _frozen_with_deltas(env, count=1)
    archive_formal(ctx["thesis_id"], expected_revision=ctx["frozen_revision"])
    _corrupt(env, "UPDATE thesis_revisions SET revision_kind='CONTENT' WHERE revision_number=?",
             (ctx["frozen_revision"] + 1,))
    current_thesis(ctx["campaign_id"], expect=500)


def test_f_delta_sequence_gap_fails_closed(env):  # noqa: ARG001
    ctx = _frozen_with_deltas(env, count=2)
    _corrupt(env, "DELETE FROM thesis_deltas WHERE delta_sequence=1")
    current_thesis(ctx["campaign_id"], expect=500)


def test_f_delta_base_revision_mismatch_fails_closed(env):  # noqa: ARG001
    ctx = _frozen_with_deltas(env, count=1)
    _corrupt(env, "UPDATE thesis_deltas SET base_revision=1")
    current_thesis(ctx["campaign_id"], expect=500)


def test_f_post_terminal_delta_fails_closed(env):  # noqa: ARG001
    ctx = _frozen_with_deltas(env, count=1, terminal=True)
    frozen_rev = ctx["frozen_revision"]
    _corrupt(
        env,
        "INSERT INTO thesis_deltas (delta_id, thesis_id, delta_sequence, base_revision, delta_state, reason, confirmed_at)"
        " VALUES (?, ?, ?, ?, 'STABLE', 'post-terminal-corruption', '2026-08-10T00:00:00+00:00')",
        ("1" * 32, ctx["thesis_id"], 2, frozen_rev),
    )
    current_thesis(ctx["campaign_id"], expect=500)


def test_f_strategy_horizon_persisted_mismatch_fails_closed(env):  # noqa: ARG001
    """主行 strategy 与 expected_horizon range 语义冲突（SHORT + 1..180）→ 500。

    frozen snapshot 与 live 主行内容一致性校验会拒绝该漂移，绝不 silent fallback。
    """
    ctx = _frozen_with_deltas(env, count=1)
    _corrupt(
        env,
        "UPDATE investment_theses SET strategy='SHORT',"
        " expected_horizon='{\"unit\":\"TRADING_DAY\",\"min\":1,\"max\":180,\"anchor\":\"FREEZE_AT\"}'"
        " WHERE id=?",
        (ctx["thesis_id"],),
    )
    current_thesis(ctx["campaign_id"], expect=500)


# ---------------------------------------------------------------------------
# Journey G — Revision Identity
# ---------------------------------------------------------------------------

def test_g_revision_timeline(env):  # noqa: ARG001
    """Revision 与 delta 是独立维度；时间线严格符合最终冻结合同。"""
    agg = create_thesis(claims=3)
    thesis_id = agg["thesis"]["id"]
    ev = create_evidence(claim="timeline-evidence")
    link_evidence(thesis_id, ev["id"], "support", expected_revision=1)   # 1 → 2 (CONTENT)
    begin_formalization(thesis_id)                                        # 2，无 bump
    update_thesis(thesis_id, expected_revision=2, strategy="SWING",
                  horizon=dict(SWING_HORIZON))                            # 2 → 3 (CONTENT)
    confirm_formalization(thesis_id)                                      # 3，无 bump
    confirmed_rev = get_thesis(thesis_id)["thesis"]["current_revision"]
    _put(f"/api/evidence/{ev['id']}", {
        "evidence_type": "news", "claim": "timeline-evidence-mutated",
        "source_title": "s", "source_url": "https://example.com/x",
        "source_date": "2026-08-02", "accessed_at": "2026-08-02T10:00:00+00:00",
        "classification": "fact", "confidence": "high",
    }, expect=200)                                                        # 无 thesis bump
    assert get_thesis(thesis_id)["thesis"]["current_revision"] == confirmed_rev
    freeze_formalization(thesis_id, expected_revision=confirmed_rev)      # 3 → 4 (FORMAL_FREEZE)
    frozen_rev = get_thesis(thesis_id)["thesis"]["frozen_revision"]
    assert frozen_rev == confirmed_rev + 1
    create_delta(thesis_id, "STABLE", "timeline-delta")                   # delta 1，无 revision bump
    assert get_thesis(thesis_id)["thesis"]["current_revision"] == frozen_rev
    archive_formal(thesis_id, expected_revision=frozen_rev)               # 4 → 5 (FORMAL_ARCHIVE)

    revisions = list_revisions(thesis_id)["items"]
    timeline = [(r["revision_number"], get_revision(thesis_id, r["revision_number"])["revision_kind"])
                for r in revisions]
    assert timeline == [
        (1, "CONTENT"),   # create（最终合同：revision 1 = CONTENT）
        (2, "CONTENT"),   # evidence link
        (3, "CONTENT"),   # draft edit
        (4, "FORMAL_FREEZE"),
        (5, "FORMAL_ARCHIVE"),
    ]
    # delta 维度独立：1 个 delta，sequence=1
    deltas = list_deltas(thesis_id)
    assert [d["delta_sequence"] for d in deltas["items"]] == [1]


# ---------------------------------------------------------------------------
# Journey H — API Surface（真实 OpenAPI route，不 grep source）
# ---------------------------------------------------------------------------

def test_h_openapi_formal_route_surface():
    openapi = app_module.app.openapi()
    paths = set(openapi["paths"].keys())
    required = {
        "/api/thesis/{thesis_id}/begin-formalization",
        "/api/thesis/{thesis_id}/confirm",
        "/api/thesis/{thesis_id}/freeze",
        "/api/thesis/{thesis_id}/archive",
        "/api/thesis/{thesis_id}/deltas",
        "/api/campaigns/{campaign_id}/current-thesis",
    }
    assert required <= paths, f"missing routes: {required - paths}"
    # Canonical Delta：只允许 POST/GET，不得存在 PUT/PATCH/DELETE
    delta_paths = [p for p in paths if p.endswith("/deltas") or "/deltas/" in p]
    for p in delta_paths:
        methods = set(openapi["paths"][p].keys())
        assert methods <= {"post", "get"}, f"delta route {p} exposes forbidden methods: {methods}"


# ---------------------------------------------------------------------------
# Journey I — No Silent Migration
# ---------------------------------------------------------------------------

def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def _snapshot_sqlite_state(path: str) -> dict:
    conn = sqlite3.connect(path)
    try:
        master = conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()
        meta = conn.execute(
            "SELECT key, value FROM schema_meta ORDER BY key").fetchall()
        return {
            "size": os.path.getsize(path),
            "hash": _file_hash(path),
            "sqlite_master": master,
            "schema_meta": meta,
        }
    finally:
        conn.close()


def test_i_legacy_v1_schema_open_does_not_migrate(tmp_path, monkeypatch):
    """S2D-M 未授权：normal store open 遇到 legacy v1 schema 必须 fail closed，
    且 file hash / size / sqlite_master / schema_meta 四项完全不变。

    不允许任何「WAL header mutation 可以接受」的豁免：open 在版本拒绝之前
    不得对 legacy DB 产生任何持久化改动。若 production 当前仍导致 hash/size
    改变，保持 failing regression（不 xfail / 不弱化 / 不修改 production），
    报告 BLOCKING_PRODUCT_DEFECT = NORMAL_OPEN_MUTATES_LEGACY_DB_BEFORE_VERSION_REJECTION。
    """
    legacy_db = tmp_path / "legacy_v1.db"
    conn = sqlite3.connect(legacy_db)
    conn.executescript("""
        CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO schema_meta (key, value) VALUES ('schema_version', 'evidence_thesis_ledger_v1');
        CREATE TABLE evidence_records (
            id TEXT PRIMARY KEY, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
            evidence_type TEXT NOT NULL, claim TEXT NOT NULL, source_title TEXT NOT NULL,
            classification TEXT NOT NULL, confidence TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0, deleted_at TEXT
        );
        CREATE TABLE investment_theses (
            id TEXT PRIMARY KEY, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
            title TEXT NOT NULL, summary TEXT NOT NULL, status TEXT NOT NULL,
            core_claims TEXT NOT NULL, catalysts TEXT NOT NULL, risks TEXT NOT NULL,
            invalidation_conditions TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, current_revision INTEGER NOT NULL DEFAULT 1
        );
    """)
    conn.commit()
    conn.close()

    before = _snapshot_sqlite_state(str(legacy_db))  # hash / size / sqlite_master / schema_meta

    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(legacy_db))
    # 1) svc readonly open → EvidenceLedgerSchemaVersionError，四项完全不变
    with pytest.raises(store.EvidenceLedgerSchemaVersionError):
        svc.list_thesis(legacy_db)
    assert _snapshot_sqlite_state(str(legacy_db)) == before
    # 2) store.initialize_store → EvidenceLedgerSchemaVersionError，四项也完全不变
    with pytest.raises(store.EvidenceLedgerSchemaVersionError):
        store.initialize_store(legacy_db)
    assert _snapshot_sqlite_state(str(legacy_db)) == before
    # 3) API 层：500 sanitized（不泄漏路径/版本）
    resp = client.get("/api/thesis")
    assert resp.status_code == 500  # NORMAL_STORE_OPEN DOES_NOT_MIGRATE
