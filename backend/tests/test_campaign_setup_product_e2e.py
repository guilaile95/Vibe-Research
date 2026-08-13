"""P0-CS1 — Campaign Setup Product Activation end-to-end matrix.

真实 isolated temp DB 上跑完整产品链（不用任何 monkeypatch 的权威）：

    bootstrap holding
    → composition UNASSIGNED_HOLDING
    → inbox SETUP_REQUIRED / CREATE_CAMPAIGN
    → POST /api/campaigns（DRAFT，服务端 id）
    → DRAFT/RESEARCHING/PRE-ENTRY 均不伪造 current Campaign
    → 显式 transitions → ACTIVE
    → composition 识别 current Campaign
    → inbox 出 campaign item（无 false clean、无重复 UNASSIGNED）

全部使用 tmp / isolated DB，绝不触碰真实用户数据。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import campaign_router
import campaign_service
import decision_inbox_runtime_assembler as inbox_runtime
import holdings_campaign_composition as composition
import position_reality_service as position_svc

SECURITY = "600519"
SECURITY_NAME = "贵州茅台"
STRATEGY_SWING = "SWING"
STRATEGY_MEDIUM = "MEDIUM"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(campaign_router.router)
    return app


def _isolate_all_db(tmp_path, monkeypatch) -> None:
    """每个测试独立全套 DB（ledger / campaign / frozen / evidence）。"""
    isolated = tmp_path / "isolated"
    isolated.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(isolated / "trade_ledger.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(isolated / "daily_reviews.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(isolated / "evidence_thesis.db"))
    monkeypatch.setenv("VIBE_RESEARCH_CAMPAIGN_DB", str(isolated / "campaigns.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_FROZEN_DECISION_DB", str(isolated / "frozen_decisions.sqlite3"))
    monkeypatch.setenv("VR_DATA_DIR", str(isolated))
    monkeypatch.delenv("VR_FACT_LAKE_ROOT", raising=False)


@pytest.fixture
def env(tmp_path, monkeypatch):
    _isolate_all_db(tmp_path, monkeypatch)
    return tmp_path


@pytest.fixture
def client(env, tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_RESEARCH_CAMPAIGN_DB", str(tmp_path / "isolated" / "campaigns.sqlite3"))
    return TestClient(_make_app())


def _bootstrap_holding() -> None:
    """bootstrap 一只真实 OPEN holding（600519，PRE_VIBE legacy）。"""
    position_svc.bootstrap_commit({
        "ledger_start_at": "2026-08-01",
        "opening_cash": 100000.0,
        "positions": [
            {
                "code": SECURITY,
                "name": SECURITY_NAME,
                "shares": 100,
                "cost_basis": 150000.0,
            }
        ],
    })


def _composition() -> dict:
    return composition.assemble_holdings_campaign_composition()


def _inbox() -> dict:
    return inbox_runtime.assemble_current_decision_inbox()


def _create_campaign(client, strategy: str = STRATEGY_SWING) -> dict:
    resp = client.post("/api/campaigns", json={
        "security_code": SECURITY,
        "strategy": strategy,
    })
    assert resp.status_code == 201
    return resp.json()["data"]


def _transition(client, campaign_id: str, expected: str, to: str) -> dict:
    resp = client.post(
        f"/api/campaigns/{campaign_id}/transitions",
        json={"expected_status": expected, "to_status": to},
    )
    assert resp.status_code == 200
    return resp.json()["data"]


def _composition_items(comp: dict) -> list[dict]:
    assert comp["evaluation_status"] == "EVALUATED"
    return comp["items"]


def _setup_item(inbox: dict, security_code: str) -> dict | None:
    for item in inbox["holding_setup_items"]:
        if item["security_code"] == security_code:
            return item
    return None


def _campaign_item(inbox: dict, security_code: str) -> dict | None:
    for item in inbox["campaign_items"]:
        if item["security_code"] == security_code:
            return item
    return None


# ---------------------------------------------------------------------------
# §8-A：Before Campaign
# ---------------------------------------------------------------------------

def test_matrix_a_before_campaign_unassigned_and_create_campaign(client, env):
    _bootstrap_holding()

    comp = _composition()
    assert comp["canonical"] is True
    items = _composition_items(comp)
    assert len(items) == 1
    assert items[0]["security_code"] == SECURITY
    assert items[0]["composition_status"] == "UNASSIGNED_HOLDING"
    assert items[0]["campaigns"] == []

    inbox = _inbox()
    assert inbox["evaluation_status"] == "EVALUATED"
    assert inbox["canonical"] is True
    item = _setup_item(inbox, SECURITY)
    assert item is not None
    assert item["item_kind"] == "UNASSIGNED_HOLDING"
    assert item["next_workflow_action"] == "CREATE_CAMPAIGN"
    assert inbox["campaign_items"] == []


# ---------------------------------------------------------------------------
# §8-B：After Create（DRAFT 不伪造 current）
# ---------------------------------------------------------------------------

def test_matrix_b_after_create_draft_not_treated_current(client, env):
    _bootstrap_holding()
    campaign = _create_campaign(client)

    assert campaign["security_code"] == SECURITY
    assert campaign["strategy"] == STRATEGY_SWING
    assert campaign["status"] == "DRAFT"
    assert campaign["campaign_id"].startswith("campaign_")

    comp = _composition_items(_composition())
    assert comp[0]["composition_status"] == "UNASSIGNED_HOLDING"
    assert comp[0]["campaigns"] == []

    inbox = _inbox()
    assert _setup_item(inbox, SECURITY) is not None
    assert _campaign_item(inbox, SECURITY) is None


# ---------------------------------------------------------------------------
# §8-C/D/E：显式推进到 ACTIVE，中间态不伪造 current
# ---------------------------------------------------------------------------

def test_matrix_cde_explicit_transitions_to_active(client, env):
    _bootstrap_holding()
    campaign = _create_campaign(client)
    cid = campaign["campaign_id"]

    for expected, to in (
        ("DRAFT", "RESEARCHING"),
        ("RESEARCHING", "PRE-ENTRY"),
        ("PRE-ENTRY", "ACTIVE"),
    ):
        campaign = _transition(client, cid, expected, to)["campaign"]
        assert campaign["status"] == to
        # RESEARCHING / PRE-ENTRY 不伪造 current Campaign（ACTIVE 见 §8-F）
        if to in ("RESEARCHING", "PRE-ENTRY"):
            comp = _composition_items(_composition())
            assert comp[0]["composition_status"] == "UNASSIGNED_HOLDING"
            assert comp[0]["campaigns"] == []

    # transition history durable（3 次显式迁移）
    history = client.get(f"/api/campaigns/{cid}/transitions").json()["data"]
    assert [row["to_status"] for row in history] == [
        "RESEARCHING", "PRE-ENTRY", "ACTIVE",
    ]


# ---------------------------------------------------------------------------
# §8-F：ACTIVE 被 composition / inbox 识别
# ---------------------------------------------------------------------------

def test_matrix_f_active_recognized_by_composition_and_inbox(client, env):
    _bootstrap_holding()
    campaign = _create_campaign(client)
    cid = campaign["campaign_id"]
    for expected, to in (
        ("DRAFT", "RESEARCHING"),
        ("RESEARCHING", "PRE-ENTRY"),
        ("PRE-ENTRY", "ACTIVE"),
    ):
        _transition(client, cid, expected, to)

    comp = _composition_items(_composition())
    assert comp[0]["composition_status"] == "ASSIGNED_HOLDING"
    assert len(comp[0]["campaigns"]) == 1
    assert comp[0]["campaigns"][0]["campaign_id"] == cid
    assert comp[0]["campaigns"][0]["status"] == "ACTIVE"

    inbox = _inbox()
    # 同一 holding 不再作为 UNASSIGNED 出现
    assert _setup_item(inbox, SECURITY) is None
    item = _campaign_item(inbox, SECURITY)
    assert item is not None
    assert item["campaign_id"] == cid
    assert item["campaign_status"] == "ACTIVE"
    # 无 Formal Thesis → 禁止 false clean（NO_ACTION_REQUIRED）
    assert item["visible_state"] != "NO_ACTION_REQUIRED"
    assert item["visible_state"] in ("SETUP_REQUIRED", "REVIEW_THESIS", "BLOCKED_BY_DATA")
    assert item["current_thesis"]["thesis_state"] == "MISSING"
    assert item["last_frozen_decision"] is None


# ---------------------------------------------------------------------------
# §9：非法 transition 拒绝 + status unchanged（在真实链上抽查全枚举）
# ---------------------------------------------------------------------------

def test_matrix_illegal_transitions_rejected_status_unchanged(client, env):
    _bootstrap_holding()
    campaign = _create_campaign(client)
    cid = campaign["campaign_id"]

    illegal_edges = [
        ("DRAFT", "ACTIVE"),
        ("DRAFT", "CLOSED"),
        ("DRAFT", "REDUCING"),
        ("DRAFT", "DRAFT"),
    ]
    for expected, to in illegal_edges:
        resp = client.post(
            f"/api/campaigns/{cid}/transitions",
            json={"expected_status": expected, "to_status": to},
        )
        assert resp.status_code == 409, (expected, to)
    assert client.get(f"/api/campaigns/{cid}").json()["data"]["status"] == "DRAFT"

    # wrong expected_status（CAS 冲突）
    resp = client.post(
        f"/api/campaigns/{cid}/transitions",
        json={"expected_status": "RESEARCHING", "to_status": "PRE-ENTRY"},
    )
    assert resp.status_code == 409
    assert client.get(f"/api/campaigns/{cid}").json()["data"]["status"] == "DRAFT"

    # 推进到 RESEARCHING 后继续抽查
    _transition(client, cid, "DRAFT", "RESEARCHING")
    for expected, to in (
        ("RESEARCHING", "ACTIVE"),
        ("RESEARCHING", "DRAFT"),
        ("RESEARCHING", "RESEARCHING"),
    ):
        resp = client.post(
            f"/api/campaigns/{cid}/transitions",
            json={"expected_status": expected, "to_status": to},
        )
        assert resp.status_code == 409, (expected, to)
    assert client.get(f"/api/campaigns/{cid}").json()["data"]["status"] == "RESEARCHING"

    # PRE-ENTRY 阶段
    _transition(client, cid, "RESEARCHING", "PRE-ENTRY")
    resp = client.post(
        f"/api/campaigns/{cid}/transitions",
        json={"expected_status": "PRE-ENTRY", "to_status": "REDUCING"},
    )
    assert resp.status_code == 409
    assert client.get(f"/api/campaigns/{cid}").json()["data"]["status"] == "PRE-ENTRY"

    # 走到 ACTIVE → REDUCING 后：REDUCING→ACTIVE 拒绝
    _transition(client, cid, "PRE-ENTRY", "ACTIVE")
    _transition(client, cid, "ACTIVE", "REDUCING")
    resp = client.post(
        f"/api/campaigns/{cid}/transitions",
        json={"expected_status": "REDUCING", "to_status": "ACTIVE"},
    )
    assert resp.status_code == 409
    assert client.get(f"/api/campaigns/{cid}").json()["data"]["status"] == "REDUCING"

    # terminal 保护：CLOSED / REJECTED / EXPIRED → anything 拒绝
    all_statuses = (
        "DRAFT", "RESEARCHING", "PRE-ENTRY", "ACTIVE", "REDUCING",
        "CLOSED", "REJECTED", "EXPIRED",
    )
    for terminal in ("CLOSED", "REJECTED", "EXPIRED"):
        terminal_campaign = _to_terminal(client, terminal)
        for to in all_statuses:
            resp = client.post(
                f"/api/campaigns/{terminal_campaign['campaign_id']}/transitions",
                json={"expected_status": terminal, "to_status": to},
            )
            assert resp.status_code == 409, (terminal, to)
        assert client.get(
            f"/api/campaigns/{terminal_campaign['campaign_id']}"
        ).json()["data"]["status"] == terminal


def _to_terminal(client, terminal: str) -> dict:
    """创建新 campaign 并显式走到指定 terminal 状态，返回该 campaign。"""
    campaign = _create_campaign(client)
    path = {
        "CLOSED": (
            ("DRAFT", "RESEARCHING"),
            ("RESEARCHING", "PRE-ENTRY"),
            ("PRE-ENTRY", "ACTIVE"),
            ("ACTIVE", "REDUCING"),
            ("REDUCING", "CLOSED"),
        ),
        "REJECTED": (("DRAFT", "REJECTED"),),
        "EXPIRED": (("DRAFT", "EXPIRED"),),
    }[terminal]
    for expected, to in path:
        campaign = _transition(client, campaign["campaign_id"], expected, to)["campaign"]
    assert campaign["status"] == terminal
    return campaign


# ---------------------------------------------------------------------------
# §10：同一 Security 多个 Campaign（都 ACTIVE 时 composition 保留两个）
# ---------------------------------------------------------------------------

def test_multi_campaign_same_security_both_active(client, env):
    _bootstrap_holding()
    swing = _create_campaign(client, STRATEGY_SWING)
    medium = _create_campaign(client, STRATEGY_MEDIUM)
    assert swing["campaign_id"] != medium["campaign_id"]

    for cid in (swing["campaign_id"], medium["campaign_id"]):
        for expected, to in (
            ("DRAFT", "RESEARCHING"),
            ("RESEARCHING", "PRE-ENTRY"),
            ("PRE-ENTRY", "ACTIVE"),
        ):
            _transition(client, cid, expected, to)

    comp = _composition_items(_composition())
    assert len(comp) == 1
    campaigns = comp[0]["campaigns"]
    assert len(campaigns) == 2
    assert {c["strategy"] for c in campaigns} == {STRATEGY_SWING, STRATEGY_MEDIUM}
    # 无 allocation 推断：allocation_status 保持 UNKNOWN（不发明分配）
    assert comp[0]["allocation_status"] == "UNKNOWN"

    inbox = _inbox()
    assert len(inbox["campaign_items"]) == 2
    for item in inbox["campaign_items"]:
        assert item["visible_state"] != "NO_ACTION_REQUIRED"


# ---------------------------------------------------------------------------
# §17：no auto thesis / no auto formal decision / no auto activation
# ---------------------------------------------------------------------------

def test_no_auto_thesis_no_auto_formal_decision_no_auto_activation(client, env):
    _bootstrap_holding()
    campaign = _create_campaign(client)
    cid = campaign["campaign_id"]

    # create 后：无自动 thesis binding
    resp = client.get(f"/api/campaigns/{cid}/thesis-binding")
    assert resp.status_code == 404

    # create 后：状态仍是 DRAFT（无自动激活）
    assert client.get(f"/api/campaigns/{cid}").json()["data"]["status"] == "DRAFT"

    # 完整 transition 后仍无 thesis binding / 无 frozen decision
    for expected, to in (
        ("DRAFT", "RESEARCHING"),
        ("RESEARCHING", "PRE-ENTRY"),
        ("PRE-ENTRY", "ACTIVE"),
    ):
        _transition(client, cid, expected, to)
    resp = client.get(f"/api/campaigns/{cid}/thesis-binding")
    assert resp.status_code == 404

    inbox = _inbox()
    item = _campaign_item(inbox, SECURITY)
    assert item is not None
    assert item["last_frozen_decision"] is None
    assert item["current_thesis"]["thesis_state"] == "MISSING"
    assert item["visible_state"] != "NO_ACTION_REQUIRED"
