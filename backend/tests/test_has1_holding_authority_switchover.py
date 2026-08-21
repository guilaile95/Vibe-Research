"""P1-HAS1 Holding Authority Switchover 验收测试（全部离线、isolated tmp）。

覆盖部署 §14 的 backend acceptance：
pre-bootstrap legacy contract 回归 / post-bootstrap 五个 legacy mutation fail closed /
fail closed 时 portfolio.json 字节级不变 / Portfolio canonical read /
Portfolio 与 Position Ledger exact equality / trade & correction propagation /
mismatch 显式且零自动修复 / authority 读取失败 fail closed / 无第三 store /
无 canonical→legacy fallback / portfolio.json 保留。
"""
import pytest
from fastapi.testclient import TestClient

import app as app_module
import astock
import portfolio as pf

client = TestClient(app_module.app)

LEDGER_ENV = "VIBE_RESEARCH_TRADE_LEDGER_DB"
BOOTSTRAP_PAYLOAD = {
    "ledger_start_at": "2026-08-01",
    "opening_cash": 100000.0,
    "note": "HAS1 acceptance bootstrap",
    "positions": [{"code": "600519", "shares": 100, "cost_basis": 8.0}],
}
EMPTY_BOOTSTRAP = {
    "ledger_start_at": "2026-08-01",
    "opening_cash": 100000.0,
    "positions": [],
}
MUTATION_409_PATHS = [
    ("post", "/api/portfolio/holding", {"code": "600519", "shares": 1, "cost": 1.0}),
    ("put", "/api/portfolio/holding", {"code": "600519", "shares": 2, "cost": 2.0}),
    ("delete", "/api/portfolio/holding?code=600519", None),
    ("post", "/api/portfolio/close", {"code": "600519", "date": "2026-08-20", "price": 9.0, "shares": 1, "cost": 8.0}),
    ("delete", "/api/portfolio/close?index=0", None),
]


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(pf, "CACHE_DIR", str(data_dir))
    monkeypatch.setattr(pf, "PF_FILE", str(data_dir / "portfolio.json"))
    monkeypatch.setenv("VR_DATA_DIR", str(data_dir))
    monkeypatch.setenv(LEDGER_ENV, str(data_dir / "trade_ledger.sqlite3"))
    monkeypatch.setattr(
        astock,
        "tencent_quote",
        lambda codes: {c: {"name": f"股{c}", "price": 10.0} for c in codes},
    )
    return data_dir


def _bootstrap(payload=None):
    r = client.post("/api/position/bootstrap-commit", json=payload or BOOTSTRAP_PAYLOAD)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _create_trade(qty=50, price=10.0, code="600519"):
    r = client.post("/api/trades", json={
        "code": code,
        "name": "贵州茅台",
        "operation": "buy",
        "execution_status": "full",
        "actual_price": price,
        "actual_quantity": qty,
        "executed_at": "2026-08-05T10:00:00Z",
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ── §14-1 pre-bootstrap：legacy contract 完整保留 ─────────────────────


def test_pre_bootstrap_legacy_crud_contract(isolated):
    data = client.get("/api/portfolio").json()["data"]
    assert data["holding_authority"] == "LEGACY_PORTFOLIO"
    assert data["holdings"] == []

    assert client.post("/api/portfolio/holding", json={"code": "600519", "shares": 100, "cost": 8.0}).status_code == 200
    assert client.put("/api/portfolio/holding", json={"code": "600519", "shares": 120, "cost": 8.5}).status_code == 200
    assert client.post(
        "/api/portfolio/close",
        json={"code": "600519", "date": "2026-08-20", "price": 9.0, "shares": 20, "cost": 8.5},
    ).status_code == 200
    assert client.delete("/api/portfolio/close?index=0").status_code == 200
    r = client.delete("/api/portfolio/holding?code=600519")
    assert r.status_code == 200
    assert r.json()["data"]["holdings"] == []


def test_pre_bootstrap_refresh_marks_legacy_authority(isolated):
    data = client.post("/api/portfolio/refresh").json()["data"]
    assert data["holding_authority"] == "LEGACY_PORTFOLIO"


# ── §14-2/3 post-bootstrap：五 mutation fail closed 且字节级不变 ────────


def test_post_bootstrap_mutations_fail_closed_bytes_unchanged(isolated):
    assert client.post("/api/portfolio/holding", json={"code": "600519", "shares": 100, "cost": 8.0}).status_code == 200
    pf_file = isolated / "portfolio.json"
    before = pf_file.read_bytes()

    _bootstrap()

    for method, path, body in MUTATION_409_PATHS:
        r = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
        assert r.status_code == 409, (path, r.status_code, r.text)
        assert "HOLDING_AUTHORITY_SWITCHED" in r.json()["detail"], path

    assert pf_file.read_bytes() == before


# ── §14-4/6 Portfolio canonical read 与 Position Ledger exact equality ─


def test_post_bootstrap_get_derives_from_ledger(isolated):
    # 真实产品流：legacy 记录与 bootstrap 期初一致 → 对账 MATCH。
    (isolated / "portfolio.json").write_text(
        '{"holdings": [{"code": "600519", "shares": 100, "cost": 8.0}], "last_refresh": null}',
        encoding="utf-8",
    )
    _bootstrap()

    portfolio_data = client.get("/api/portfolio").json()["data"]
    derived = client.get("/api/position/derived").json()["data"]

    assert portfolio_data["holding_authority"] == "LEDGER_DERIVED"
    assert derived["bootstrap_status"] == "BOOTSTRAPPED"

    open_rows = [p for p in derived["positions"] if p["status"] == "OPEN"]
    assert [(h["code"], h["shares"], h["cost"]) for h in portfolio_data["holdings"]] == [
        (p["code"], p["shares"], p["avg_cost"]) for p in open_rows
    ]
    assert portfolio_data["totals"]["cost"] == 800.0

    recon = portfolio_data["ledger_view"]["reconciliation"]
    assert recon["summary"]["match"] == 1
    assert recon["summary"]["mismatch"] == 0


def test_unarchived_ledger_position_shows_missing_in_portfolio(isolated):
    # 无 legacy 文件时，对账必须诚实报 MISSING_IN_PORTFOLIO，不得伪装成 MATCH。
    _bootstrap()
    data = client.get("/api/portfolio").json()["data"]
    recon = data["ledger_view"]["reconciliation"]
    assert data["holding_authority"] == "LEDGER_DERIVED"
    assert [h["code"] for h in data["holdings"]] == ["600519"]
    assert recon["summary"]["missing_in_portfolio"] == 1
    assert recon["summary"]["match"] == 0


def test_refresh_follows_same_authority(isolated):
    _bootstrap()
    data = client.post("/api/portfolio/refresh").json()["data"]
    assert data["holding_authority"] == "LEDGER_DERIVED"


# ── §14-7/8 trade / correction propagation ────────────────────────────


def test_trade_propagates_to_portfolio_read(isolated):
    _bootstrap(EMPTY_BOOTSTRAP)
    record = _create_trade(qty=50, price=10.0)

    data = client.get("/api/portfolio").json()["data"]
    assert data["holding_authority"] == "LEDGER_DERIVED"
    assert [(h["code"], h["shares"], h["cost"]) for h in data["holdings"]] == [
        ("600519", 50, 10.0)
    ]
    assert record["trade_id"]


def test_correction_propagates_to_portfolio_read(isolated):
    _bootstrap(EMPTY_BOOTSTRAP)
    record = _create_trade(qty=50, price=10.0)

    r = client.post("/api/position/correction", json={
        "target_event_type": "trade",
        "target_event_id": record["trade_id"],
        "after_payload": {"actual_quantity": 80},
        "reason": "HAS1 propagation acceptance",
    })
    assert r.status_code == 200, r.text

    data = client.get("/api/portfolio").json()["data"]
    assert [h["shares"] for h in data["holdings"]] == [80]


# ── §14-9/12 mismatch 显式、零自动修复、无 canonical→legacy fallback ───


def test_mismatch_explicit_without_auto_fix_or_fallback(isolated):
    _bootstrap()

    # 故意制造 legacy portfolio.json ≠ ledger-derived 的分歧。
    pf_file = isolated / "portfolio.json"
    pf_file.write_text(
        '{"holdings": [{"code": "600519", "shares": 999, "cost": 1.0}], "last_refresh": null}',
        encoding="utf-8",
    )
    poisoned = pf_file.read_bytes()

    data = client.get("/api/portfolio").json()["data"]
    recon = data["ledger_view"]["reconciliation"]

    assert data["holding_authority"] == "LEDGER_DERIVED"
    # 不 fallback 到 portfolio.json：显示的仍是 canonical 值。
    assert [(h["shares"], h["cost"]) for h in data["holdings"]] == [(100, 8.0)]
    assert recon["summary"]["mismatch"] >= 1
    assert any(i["status"] == "MISMATCH" for i in recon["items"])

    # 读操作不修平任何一边。
    assert pf_file.read_bytes() == poisoned


# ── §14-10 authority 读取失败 fail closed ─────────────────────────────


def test_authority_error_fails_closed_mutations(isolated):
    # 权威不可读时，连“看起来无害”的 legacy 写也必须拒绝。
    (isolated / "portfolio.json").write_text(
        '{"holdings": [{"code": "600519", "shares": 100, "cost": 8.0}], "last_refresh": null}',
        encoding="utf-8",
    )
    (isolated / "trade_ledger.sqlite3").write_bytes(b"this is not a sqlite database")
    pf_before = (isolated / "portfolio.json").read_bytes()

    for method, path, body in MUTATION_409_PATHS:
        r = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
        assert r.status_code == 503, (path, r.status_code, r.text)
        assert "HOLDING_AUTHORITY_UNPROVEN" in r.json()["detail"], path

    assert (isolated / "portfolio.json").read_bytes() == pf_before

    # 读路径诚实降级：明确 UNKNOWN，不伪装成权威数据。
    data = client.get("/api/portfolio").json()["data"]
    assert data["holding_authority"] == "UNKNOWN"


# ── §14-11/§9 portfolio.json 保留、无第三 Holding store ────────────────


def test_portfolio_json_preserved_and_no_third_store(isolated):
    assert client.post("/api/portfolio/holding", json={"code": "600519", "shares": 100, "cost": 8.0}).status_code == 200
    original = (isolated / "portfolio.json").read_bytes()

    _bootstrap()
    for method, path, body in MUTATION_409_PATHS:
        r = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
        assert r.status_code == 409

    client.get("/api/portfolio")

    assert (isolated / "portfolio.json").read_bytes() == original

    allowed = {
        "portfolio.json",
        "portfolio.json.bak",
        "trade_ledger.sqlite3",
        "data_health_events.json",
    }
    unexpected = [p.name for p in isolated.iterdir() if p.name not in allowed]
    assert unexpected == []
