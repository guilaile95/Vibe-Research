"""告警规则 CRUD API 合同测试。

正常 CRUD 使用真实 Store + 临时 SQLite；异常映射通过 monkeypatch 单个 Store 调用注入。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import alert_rule_store as store
from alert_rules import (
    AlertRule,
    DataHealthStatusCondition,
    MetricComparisonCondition,
    MetricThresholdCondition,
    TechnicalStatusCondition,
    TechnicalTriggerCondition,
)

_DB_ENV = "VIBE_RESEARCH_ALERT_RULE_DB"
T0 = datetime(2026, 8, 1, 3, 4, 5, 123456, tzinfo=timezone.utc)

CONDITION_KINDS = [
    {"kind": "technical_trigger", "trigger": "sma_golden_cross"},
    {"kind": "metric_threshold", "metric": "close", "operator": "gt", "threshold": 10.5},
    {"kind": "metric_comparison", "left": "close", "operator": "gt", "right": "sma20"},
    {"kind": "technical_status", "status": "partial"},
    {"kind": "data_health_status", "source_id": "quotes", "status": "partial"},
]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "nested" / "alert_rules.sqlite3"
    monkeypatch.setenv(_DB_ENV, str(db_path))
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    import app as app_module

    return TestClient(app_module.app), tmp_path, db_path


def payload(
    rule_id: str = "rule.sma-cross",
    code: str = "000001",
    enabled: bool = True,
    condition: dict | None = None,
) -> dict:
    body = {
        "rule_id": rule_id,
        "code": code,
        "enabled": enabled,
        "condition": condition
        or {"kind": "technical_trigger", "trigger": "sma_golden_cross"},
    }
    return body


def seed_rule(
    rule_id: str,
    code: str = "000001",
    enabled: bool = True,
    *,
    now: datetime = T0,
    condition_kind: str = "technical_trigger",
) -> None:
    condition = TechnicalTriggerCondition(
        kind="technical_trigger", trigger="sma_golden_cross"
    )
    if condition_kind == "metric_threshold":
        condition = MetricThresholdCondition(
            kind="metric_threshold", metric="close", operator="gt", threshold=10.5
        )
    elif condition_kind == "metric_comparison":
        condition = MetricComparisonCondition(
            kind="metric_comparison", left="close", operator="gt", right="sma20"
        )
    elif condition_kind == "technical_status":
        condition = TechnicalStatusCondition(kind="technical_status", status="partial")
    elif condition_kind == "data_health_status":
        condition = DataHealthStatusCondition(
            kind="data_health_status", source_id="quotes", status="partial"
        )
    store.create_alert_rule(
        AlertRule(rule_id=rule_id, code=code, enabled=enabled, condition=condition),
        now=now,
    )


def db_objects(db_path: Path) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# 路由注册与导入副作用
# ---------------------------------------------------------------------------


def test_route_registration(client):
    c, _, _ = client
    found = set()
    all_routes = []
    for route in c.app.routes:
        if hasattr(route, "original_router"):
            all_routes.extend(route.original_router.routes)
        else:
            all_routes.append(route)
    for route in all_routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/alert-rules"):
            continue
        for method in getattr(route, "methods", set()) or set():
            # 排除 FastAPI 自动生成的 HEAD/OPTIONS，产品路由集合必须精确相等。
            if method in ("HEAD", "OPTIONS"):
                continue
            found.add((method, path))
    assert found == {
        ("POST", "/api/alert-rules"),
        ("GET", "/api/alert-rules"),
        ("GET", "/api/alert-rules/{rule_id}"),
        ("PUT", "/api/alert-rules/{rule_id}"),
        ("DELETE", "/api/alert-rules/{rule_id}"),
    }, found


def test_import_has_no_filesystem_side_effect(tmp_path, monkeypatch):
    db_path = tmp_path / "import_check" / "alert_rules.sqlite3"
    monkeypatch.setenv(_DB_ENV, str(db_path))
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    import alert_rule_router  # noqa: F401
    import app as app_module  # noqa: F401

    assert not db_path.exists()
    assert not db_path.parent.exists()


# ---------------------------------------------------------------------------
# POST /api/alert-rules
# ---------------------------------------------------------------------------


def test_create_all_five_condition_kinds(client):
    c, _, _ = client
    for index, condition in enumerate(CONDITION_KINDS):
        r = c.post(
            "/api/alert-rules", json=payload(rule_id=f"rule.kind-{index}", condition=condition)
        )
        assert r.status_code == 201, r.text
        body = r.json()["data"]
        assert body["rule"]["condition"]["kind"] == condition["kind"]
        assert body["revision"] == 1
        assert body["created_at"] == body["updated_at"]
        assert body["deleted_at"] is None
    assert len(c.get("/api/alert-rules").json()["data"]) == 5


def test_create_enabled_defaults_true_and_schema_version_filled(client):
    c, _, _ = client
    body = payload()
    body.pop("enabled")
    body.pop("schema_version", None)
    r = c.post("/api/alert-rules", json=body)
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["schema_version"] == "alert-rule-record.v0.1"
    assert data["rule"]["schema_version"] == "alert-rule.v0.1"
    assert data["rule"]["enabled"] is True


def test_create_explicit_schema_version_accepted(client):
    c, _, _ = client
    body = payload()
    body["schema_version"] = "alert-rule.v0.1"
    assert c.post("/api/alert-rules", json=body).status_code == 201


def test_create_wrong_schema_version_422(client):
    c, _, db_path = client
    body = payload()
    body["schema_version"] = "alert-rule.v9"
    assert c.post("/api/alert-rules", json=body).status_code == 422
    assert not db_path.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b.update({"unknown_field": 1}),
        lambda b: b["condition"].update({"unknown_condition_field": 1}),
        lambda b: b["condition"].update({"kind": "unknown_kind"}),
        lambda b: b["condition"].pop("kind"),
        lambda b: b.update({"code": "０００００１"}),
        lambda b: b.update({"code": 123456}),
        lambda b: b.update({"rule_id": True}),
        lambda b: b.update({"code": True}),
    ],
)
def test_create_invalid_bodies_422(client, mutation):
    c, _, db_path = client
    body = payload()
    mutation(body)
    r = c.post("/api/alert-rules", json=body)
    assert r.status_code == 422, r.text
    assert not db_path.exists()


def test_create_duplicate_rule_id_409(client):
    c, _, _ = client
    assert c.post("/api/alert-rules", json=payload()).status_code == 201
    r = c.post("/api/alert-rules", json=payload())
    assert r.status_code == 409
    assert r.json()["detail"] == "告警规则已存在"


def test_create_duplicate_after_soft_delete_409(client):
    c, _, _ = client
    assert c.post("/api/alert-rules", json=payload()).status_code == 201
    assert (
        c.delete("/api/alert-rules/rule.sma-cross", params={"expected_revision": "1"}).status_code
        == 200
    )
    r = c.post("/api/alert-rules", json=payload())
    assert r.status_code == 409
    assert r.json()["detail"] == "告警规则已存在"


def test_create_malformed_json_422(client):
    c, _, db_path = client
    r = c.post(
        "/api/alert-rules",
        content="{not json",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422
    assert not db_path.exists()


def test_create_empty_body_422(client):
    c, _, db_path = client
    assert c.post("/api/alert-rules").status_code == 422
    assert not db_path.exists()


# ---------------------------------------------------------------------------
# GET /api/alert-rules（列表）
# ---------------------------------------------------------------------------


def test_list_missing_database_returns_empty_without_side_effects(client):
    c, tmp_path, db_path = client
    before = sorted(p.name for p in tmp_path.iterdir())
    r = c.get("/api/alert-rules")
    assert r.status_code == 200
    assert r.json() == {"data": []}
    assert not db_path.exists()
    assert not db_path.parent.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_list_hides_deleted_by_default_and_include_deleted(client):
    c, _, _ = client
    seed_rule("rule.a")
    seed_rule("rule.b", code="600000")
    assert c.delete("/api/alert-rules/rule.a", params={"expected_revision": "1"}).status_code == 200
    assert [r["rule"]["rule_id"] for r in c.get("/api/alert-rules").json()["data"]] == ["rule.b"]
    listed = c.get("/api/alert-rules", params={"include_deleted": "true"}).json()["data"]
    assert {r["rule"]["rule_id"] for r in listed} == {"rule.a", "rule.b"}
    deleted = next(r for r in listed if r["rule"]["rule_id"] == "rule.a")
    assert deleted["deleted_at"] == deleted["updated_at"]
    assert deleted["revision"] == 2


def test_list_code_and_enabled_filters(client):
    c, _, _ = client
    seed_rule("rule.a", code="000001", enabled=True)
    seed_rule("rule.b", code="000001", enabled=False)
    seed_rule("rule.c", code="600000", enabled=True)
    assert [r["rule"]["rule_id"] for r in c.get("/api/alert-rules", params={"code": "000001"}).json()["data"]] == [
        "rule.a",
        "rule.b",
    ]
    assert [r["rule"]["rule_id"] for r in c.get("/api/alert-rules", params={"enabled": "true"}).json()["data"]] == [
        "rule.a",
        "rule.c",
    ]
    assert [r["rule"]["rule_id"] for r in c.get("/api/alert-rules", params={"enabled": "false"}).json()["data"]] == [
        "rule.b"
    ]


def test_list_limit_offset_and_fixed_sort(client):
    c, _, _ = client
    seed_rule("rule.b", now=T0)
    seed_rule("rule.a", now=T0)
    seed_rule("rule.c", now=datetime(2026, 8, 1, 4, 0, 0, tzinfo=timezone.utc))
    assert [r["rule"]["rule_id"] for r in c.get("/api/alert-rules").json()["data"]] == [
        "rule.c",
        "rule.a",
        "rule.b",
    ]
    assert [r["rule"]["rule_id"] for r in c.get("/api/alert-rules", params={"limit": "2"}).json()["data"]] == [
        "rule.c",
        "rule.a",
    ]
    assert [r["rule"]["rule_id"] for r in c.get(
        "/api/alert-rules", params={"limit": "2", "offset": "1"}
    ).json()["data"]] == ["rule.a", "rule.b"]


def test_list_filters_before_pagination(client):
    c, _, _ = client
    for i in range(3):
        seed_rule(f"rule.p{i}", code="000001")
    seed_rule("rule.q0", code="600000")
    seed_rule("rule.q1", code="600000")
    listed = c.get(
        "/api/alert-rules", params={"code": "000001", "limit": "2", "offset": "1"}
    ).json()["data"]
    assert [r["rule"]["rule_id"] for r in listed] == ["rule.p1", "rule.p2"]


@pytest.mark.parametrize(
    "query",
    [
        [("limit", "0")],
        [("limit", "201")],
        [("limit", "01")],
        [("limit", "+1")],
        [("limit", "1.0")],
        [("limit", "true")],
        [("limit", " ")],
        [("limit", "１")],
        [("limit", "1"), ("limit", "2")],
        [("offset", "-1")],
        [("offset", "00")],
        [("offset", "01")],
        [("offset", "+1")],
        [("offset", "1.0")],
        [("offset", "true")],
        [("offset", " ")],
        [("offset", "１")],
        [("offset", "1"), ("offset", "2")],
        [("enabled", "True")],
        [("enabled", "TRUE")],
        [("enabled", "1")],
        [("enabled", "0")],
        [("enabled", "yes")],
        [("enabled", "on")],
        [("enabled", "")],
        [("enabled", " true")],
        [("enabled", "true ")],
        [("enabled", "true"), ("enabled", "false")],
        [("include_deleted", "True")],
        [("include_deleted", "1")],
        [("include_deleted", "yes")],
        [("include_deleted", "true"), ("include_deleted", "false")],
        [("code", "０００００１")],
        [("code", " 000001")],
        [("code", "000001 ")],
        [("code", "sh600000")],
        [("code", "12345")],
        [("code", "1234567")],
        [("code", "000001"), ("code", "600000")],
    ],
)
def test_list_rejects_illegal_query_values(client, query):
    c, _, db_path = client
    seed_rule("rule.a")
    r = c.get("/api/alert-rules", params=query)
    assert r.status_code == 422, (query, r.text)


# ---------------------------------------------------------------------------
# GET /api/alert-rules/{rule_id}
# ---------------------------------------------------------------------------


def test_get_existing_rule(client):
    c, _, _ = client
    assert c.post("/api/alert-rules", json=payload()).status_code == 201
    r = c.get("/api/alert-rules/rule.sma-cross")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["rule"]["rule_id"] == "rule.sma-cross"
    assert data["rule"]["code"] == "000001"
    assert data["rule"]["enabled"] is True
    assert data["rule"]["condition"]["kind"] == "technical_trigger"


def test_get_missing_rule_404(client):
    c, _, _ = client
    seed_rule("rule.a")
    r = c.get("/api/alert-rules/rule.missing")
    assert r.status_code == 404
    assert r.json()["detail"] == "告警规则不存在"


def test_get_missing_database_404_without_side_effects(client):
    c, _, db_path = client
    r = c.get("/api/alert-rules/rule.a")
    assert r.status_code == 404
    assert not db_path.exists()
    assert not db_path.parent.exists()


def test_get_soft_deleted_default_404_include_deleted_200(client):
    c, _, _ = client
    seed_rule("rule.a")
    assert c.delete("/api/alert-rules/rule.a", params={"expected_revision": "1"}).status_code == 200
    assert c.get("/api/alert-rules/rule.a").status_code == 404
    r = c.get("/api/alert-rules/rule.a", params={"include_deleted": "true"})
    assert r.status_code == 200
    assert r.json()["data"]["deleted_at"] is not None


@pytest.mark.parametrize(
    "rule_id",
    ["bad id", "中文", "-bad", "rule@id"],
)
def test_get_invalid_rule_id_422(client, rule_id):
    c, _, db_path = client
    r = c.get(f"/api/alert-rules/{rule_id}")
    assert r.status_code == 422
    assert not db_path.exists()


@pytest.mark.parametrize(
    "include_deleted",
    ["True", "1", "yes", "on", "", " true", "true "],
)
def test_get_invalid_include_deleted_422(client, include_deleted):
    c, _, _ = client
    seed_rule("rule.a")
    r = c.get("/api/alert-rules/rule.a", params={"include_deleted": include_deleted})
    assert r.status_code == 422


def test_get_duplicate_include_deleted_422(client):
    c, _, _ = client
    seed_rule("rule.a")
    r = c.get(
        "/api/alert-rules/rule.a",
        params=[("include_deleted", "true"), ("include_deleted", "false")],
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# PUT /api/alert-rules/{rule_id}
# ---------------------------------------------------------------------------


def test_put_full_replace(client):
    c, _, _ = client
    assert c.post("/api/alert-rules", json=payload()).status_code == 201
    created = c.get("/api/alert-rules/rule.sma-cross").json()["data"]
    replacement = payload(
        rule_id="rule.sma-cross",
        code="600000",
        enabled=False,
        condition={"kind": "metric_threshold", "metric": "close", "operator": "gt", "threshold": 5.0},
    )
    r = c.put("/api/alert-rules/rule.sma-cross", params={"expected_revision": "1"}, json=replacement)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["rule"]["code"] == "600000"
    assert data["rule"]["enabled"] is False
    assert data["rule"]["condition"]["kind"] == "metric_threshold"
    assert data["revision"] == 2
    assert data["created_at"] == created["created_at"]
    assert data["updated_at"] != created["updated_at"]
    assert data["deleted_at"] is None


def test_put_path_body_rule_id_mismatch_422(client):
    c, _, db_path = client
    seed_rule("rule.a")
    r = c.put(
        "/api/alert-rules/rule.other",
        params={"expected_revision": "1"},
        json=payload(rule_id="rule.a"),
    )
    assert r.status_code == 422


@pytest.mark.parametrize(
    "revision",
    ["0", "01", "%2B1", "1.0", "true", " ", "１"],
)
def test_put_invalid_expected_revision_422(client, revision):
    c, _, _ = client
    seed_rule("rule.a")
    r = c.put(
        "/api/alert-rules/rule.a",
        params={"expected_revision": revision},
        json=payload(rule_id="rule.a"),
    )
    assert r.status_code == 422, revision


def test_put_missing_expected_revision_422(client):
    c, _, _ = client
    seed_rule("rule.a")
    r = c.put("/api/alert-rules/rule.a", json=payload(rule_id="rule.a"))
    assert r.status_code == 422


def test_put_duplicate_expected_revision_422(client):
    c, _, _ = client
    seed_rule("rule.a")
    r = c.put(
        "/api/alert-rules/rule.a",
        params=[("expected_revision", "1"), ("expected_revision", "2")],
        json=payload(rule_id="rule.a"),
    )
    assert r.status_code == 422


def test_put_stale_revision_409(client):
    c, _, _ = client
    seed_rule("rule.a")
    r = c.put(
        "/api/alert-rules/rule.a",
        params={"expected_revision": "2"},
        json=payload(rule_id="rule.a"),
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "告警规则已发生变化，请重新加载后重试"


def test_put_missing_rule_404(client):
    c, _, _ = client
    r = c.put(
        "/api/alert-rules/rule.missing",
        params={"expected_revision": "1"},
        json=payload(rule_id="rule.missing"),
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "告警规则不存在"


def test_put_deleted_rule_404(client):
    c, _, _ = client
    seed_rule("rule.a")
    assert c.delete("/api/alert-rules/rule.a", params={"expected_revision": "1"}).status_code == 200
    r = c.put(
        "/api/alert-rules/rule.a",
        params={"expected_revision": "2"},
        json=payload(rule_id="rule.a"),
    )
    assert r.status_code == 404


def test_put_wrong_body_schema_422(client):
    c, _, _ = client
    seed_rule("rule.a")
    body = payload(rule_id="rule.a")
    body["schema_version"] = "alert-rule.v9"
    r = c.put(
        "/api/alert-rules/rule.a",
        params={"expected_revision": "1"},
        json=body,
    )
    assert r.status_code == 422


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b.pop("code"),
        lambda b: b.pop("condition"),
        lambda b: b.pop("rule_id"),
        lambda b: b.update({"code": 123456}),
    ],
)
def test_put_partial_or_invalid_body_422(client, mutation):
    c, _, _ = client
    seed_rule("rule.a")
    body = payload(rule_id="rule.a")
    mutation(body)
    r = c.put(
        "/api/alert-rules/rule.a",
        params={"expected_revision": "1"},
        json=body,
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/alert-rules/{rule_id}
# ---------------------------------------------------------------------------


def test_delete_soft_deletes(client):
    c, _, db_path = client
    seed_rule("rule.a")
    r = c.delete("/api/alert-rules/rule.a", params={"expected_revision": "1"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["rule"]["rule_id"] == "rule.a"
    assert data["revision"] == 2
    assert data["updated_at"] == data["deleted_at"]
    # 物理行仍在
    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM alert_rules").fetchone()[0]
    conn.close()
    assert count == 1
    # 默认读取隐藏，include_deleted 可见
    assert c.get("/api/alert-rules/rule.a").status_code == 404
    assert c.get("/api/alert-rules/rule.a", params={"include_deleted": "true"}).status_code == 200


def test_delete_stale_revision_409(client):
    c, _, _ = client
    seed_rule("rule.a")
    r = c.delete("/api/alert-rules/rule.a", params={"expected_revision": "2"})
    assert r.status_code == 409
    assert r.json()["detail"] == "告警规则已发生变化，请重新加载后重试"


def test_delete_missing_rule_404(client):
    c, _, _ = client
    r = c.delete("/api/alert-rules/rule.missing", params={"expected_revision": "1"})
    assert r.status_code == 404
    assert r.json()["detail"] == "告警规则不存在"


def test_delete_twice_404(client):
    c, _, _ = client
    seed_rule("rule.a")
    assert c.delete("/api/alert-rules/rule.a", params={"expected_revision": "1"}).status_code == 200
    r = c.delete("/api/alert-rules/rule.a", params={"expected_revision": "2"})
    assert r.status_code == 404


@pytest.mark.parametrize("revision", ["0", "01", "%2B1", "1.0", "true", " ", "１"])
def test_delete_invalid_expected_revision_422(client, revision):
    c, _, _ = client
    seed_rule("rule.a")
    r = c.delete("/api/alert-rules/rule.a", params={"expected_revision": revision})
    assert r.status_code == 422


def test_delete_missing_expected_revision_422(client):
    c, _, _ = client
    seed_rule("rule.a")
    assert c.delete("/api/alert-rules/rule.a").status_code == 422


def test_delete_duplicate_expected_revision_422(client):
    c, _, _ = client
    seed_rule("rule.a")
    r = c.delete(
        "/api/alert-rules/rule.a",
        params=[("expected_revision", "1"), ("expected_revision", "2")],
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 异常安全映射
# ---------------------------------------------------------------------------


def _raiser(exc):
    def _raise(*args, **kwargs):
        raise exc

    return _raise


@pytest.mark.parametrize(
    ("exc_name", "status"),
    [
        ("AlertRuleStoreInputError", 422),
        ("AlertRuleNotFoundError", 404),
        ("AlertRuleAlreadyExistsError", 409),
        ("AlertRuleRevisionConflictError", 409),
        ("AlertRuleStoreCorruptedError", 500),
        ("AlertRuleStoreError", 500),
    ],
)
def test_store_error_mapping(client, monkeypatch, exc_name, status):
    c, _, _ = client
    # 异常类在测试运行时解析，避免 store 测试中 importlib.reload 造成的类身份漂移。
    exc_cls = getattr(store, exc_name)
    expected_detail = {
        "AlertRuleStoreInputError": "告警规则参数无效",
        "AlertRuleNotFoundError": "告警规则不存在",
        "AlertRuleAlreadyExistsError": "告警规则已存在",
        "AlertRuleRevisionConflictError": "告警规则已发生变化，请重新加载后重试",
        "AlertRuleStoreCorruptedError": store.AlertRuleStoreCorruptedError.MESSAGE,
        "AlertRuleStoreError": "告警规则存储暂时不可用",
    }[exc_name]
    monkeypatch.setattr(store, "create_alert_rule", _raiser(exc_cls()))
    r = c.post("/api/alert-rules", json=payload())
    assert r.status_code == status
    assert r.json()["detail"] == expected_detail
    text = r.text
    assert "Traceback" not in text
    assert "secret" not in text
    assert "C:\\Users" not in text
    assert "sqlite" not in text.lower()
    assert "SELECT" not in text
    assert "INSERT" not in text


def test_sqlite_warning_maps_to_internal_error(client, monkeypatch):
    c, _, _ = client
    monkeypatch.setattr(
        store, "create_alert_rule", _raiser(sqlite3.Warning("sqlite warning"))
    )
    r = c.post("/api/alert-rules", json=payload())
    assert r.status_code == 500
    assert r.json()["detail"] == "告警规则服务内部错误"
    assert "sqlite" not in r.text.lower()


def test_unexpected_runtime_error_does_not_leak_internals(client, monkeypatch):
    c, _, _ = client
    monkeypatch.setattr(
        store,
        "create_alert_rule",
        _raiser(RuntimeError("secret path C:\\Users\\secret\\db.sqlite3")),
    )
    r = c.post("/api/alert-rules", json=payload())
    assert r.status_code == 500
    assert r.json()["detail"] == "告警规则服务内部错误"
    text = r.text
    assert "secret" not in text
    assert "C:\\Users" not in text
    assert "Traceback" not in text


def test_put_revision_conflict_mapping(client, monkeypatch):
    c, _, _ = client
    monkeypatch.setattr(
        store, "replace_alert_rule", _raiser(store.AlertRuleRevisionConflictError())
    )
    r = c.put(
        "/api/alert-rules/rule.a",
        params={"expected_revision": "1"},
        json=payload(rule_id="rule.a"),
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "告警规则已发生变化，请重新加载后重试"


def test_delete_not_found_mapping(client, monkeypatch):
    c, _, _ = client
    monkeypatch.setattr(
        store, "delete_alert_rule", _raiser(store.AlertRuleNotFoundError())
    )
    r = c.delete("/api/alert-rules/rule.a", params={"expected_revision": "1"})
    assert r.status_code == 404
    assert r.json()["detail"] == "告警规则不存在"


def test_get_corrupted_mapping(client, monkeypatch):
    c, _, _ = client
    monkeypatch.setattr(
        store, "get_alert_rule", _raiser(store.AlertRuleStoreCorruptedError())
    )
    r = c.get("/api/alert-rules/rule.a")
    assert r.status_code == 500
    assert r.json()["detail"] == store.AlertRuleStoreCorruptedError.MESSAGE


# ---------------------------------------------------------------------------
# 方法边界
# ---------------------------------------------------------------------------


def test_patch_not_allowed(client):
    c, _, _ = client
    seed_rule("rule.a")
    r = c.patch("/api/alert-rules/rule.a", json=payload(rule_id="rule.a"))
    assert r.status_code == 405


def test_restore_and_evaluate_routes_absent(client):
    c, _, _ = client
    seed_rule("rule.a")
    assert c.post("/api/alert-rules/rule.a/restore").status_code in (404, 405)
    assert c.post("/api/alert-rules/rule.a/evaluate").status_code in (404, 405)


# ---------------------------------------------------------------------------
# 复审修复：PUT 必须显式包含全部必需字段
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["rule_id", "code", "enabled", "condition"])
def test_put_missing_required_field_422_no_side_effects(client, monkeypatch, missing):
    c, _, _ = client
    seed_rule("rule.a", enabled=False)
    before = store.get_alert_rule("rule.a")
    calls = {"n": 0}
    real_replace = store.replace_alert_rule

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real_replace(*args, **kwargs)

    monkeypatch.setattr(store, "replace_alert_rule", counting)
    body = payload(rule_id="rule.a", enabled=False)
    body.pop(missing)
    r = c.put(
        "/api/alert-rules/rule.a",
        params={"expected_revision": "1"},
        json=body,
    )
    assert r.status_code == 422, missing
    if missing == "enabled":
        # 只有 enabled 缺失时能通过 Pydantic（有默认值），由端点显式检查给出固定 detail。
        assert r.json()["detail"] == "告警规则参数无效"
    assert calls["n"] == 0
    after = store.get_alert_rule("rule.a")
    assert after == before
    assert after.rule.enabled is False
    assert after.revision == 1
    assert after.deleted_at is None


# ---------------------------------------------------------------------------
# 复审修复：超长整数与固定上限
# ---------------------------------------------------------------------------


HUGE_INTEGER_VALUES = [
    "9" * 100,
    "9" * 1000,
    "9" * 5000,
    "9" * 10000,
    str(2**63 - 1),
    str(2**63),
    "1" + "0" * 30,
]


@pytest.mark.parametrize("huge", HUGE_INTEGER_VALUES)
def test_list_huge_limit_422_store_not_called(client, monkeypatch, huge):
    c, _, db_path = client
    calls = {"n": 0}
    real_list = store.list_alert_rules

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real_list(*args, **kwargs)

    monkeypatch.setattr(store, "list_alert_rules", counting)
    r = c.get("/api/alert-rules", params={"limit": huge})
    assert r.status_code == 422
    assert r.json()["detail"] == "告警规则参数无效"
    assert calls["n"] == 0
    assert not db_path.exists()


@pytest.mark.parametrize("huge", HUGE_INTEGER_VALUES)
def test_list_huge_offset_422_store_not_called(client, monkeypatch, huge):
    c, _, db_path = client
    calls = {"n": 0}
    real_list = store.list_alert_rules

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real_list(*args, **kwargs)

    monkeypatch.setattr(store, "list_alert_rules", counting)
    r = c.get("/api/alert-rules", params={"offset": huge})
    assert r.status_code == 422
    assert r.json()["detail"] == "告警规则参数无效"
    assert calls["n"] == 0
    assert not db_path.exists()


@pytest.mark.parametrize("huge", HUGE_INTEGER_VALUES)
def test_put_huge_expected_revision_422_store_not_called(client, monkeypatch, huge):
    c, _, db_path = client
    calls = {"n": 0}
    real_replace = store.replace_alert_rule

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real_replace(*args, **kwargs)

    monkeypatch.setattr(store, "replace_alert_rule", counting)
    r = c.put(
        "/api/alert-rules/rule.a",
        params={"expected_revision": huge},
        json=payload(rule_id="rule.a"),
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "告警规则参数无效"
    assert calls["n"] == 0
    assert not db_path.exists()


@pytest.mark.parametrize("huge", HUGE_INTEGER_VALUES)
def test_delete_huge_expected_revision_422_store_not_called(client, monkeypatch, huge):
    c, _, db_path = client
    calls = {"n": 0}
    real_delete = store.delete_alert_rule

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real_delete(*args, **kwargs)

    monkeypatch.setattr(store, "delete_alert_rule", counting)
    r = c.delete("/api/alert-rules/rule.a", params={"expected_revision": huge})
    assert r.status_code == 422
    assert r.json()["detail"] == "告警规则参数无效"
    assert calls["n"] == 0
    assert not db_path.exists()


def test_integer_boundary_maximums_accepted(client):
    c, _, _ = client
    seed_rule("rule.a")
    # offset 上限与 expected_revision 上限：合法值必须正常进入 Store 路径
    r = c.get("/api/alert-rules", params={"offset": "2147483647"})
    assert r.status_code == 200
    r = c.put(
        "/api/alert-rules/rule.a",
        params={"expected_revision": "1"},
        json=payload(rule_id="rule.a"),
    )
    assert r.status_code == 200
    # 2147483648 越界
    assert (
        c.get("/api/alert-rules", params={"offset": "2147483648"}).status_code == 422
    )
    assert (
        c.put(
            "/api/alert-rules/rule.a",
            params={"expected_revision": "2147483648"},
            json=payload(rule_id="rule.a"),
        ).status_code
        == 422
    )


# ---------------------------------------------------------------------------
# 复审修复：DELETE 拒绝任何请求体
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "{}",
        '{"unexpected": true}',
        "[]",
        '"string"',
        "null",
        "   ",
        "\n",
        "{bad json",
        "not json at all",
    ],
)
def test_delete_with_any_body_422_store_not_called(client, monkeypatch, content):
    c, _, _ = client
    seed_rule("rule.a")
    calls = {"n": 0}
    real_delete = store.delete_alert_rule

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real_delete(*args, **kwargs)

    monkeypatch.setattr(store, "delete_alert_rule", counting)
    r = c.request(
        "DELETE",
        "/api/alert-rules/rule.a",
        params={"expected_revision": "1"},
        content=content,
    )
    assert r.status_code == 422, content
    assert r.json()["detail"] == "告警规则参数无效"
    assert calls["n"] == 0
    rec = store.get_alert_rule("rule.a", include_deleted=True)
    assert rec is not None
    assert rec.deleted_at is None
    assert rec.revision == 1


def test_delete_without_body_still_works(client):
    c, _, _ = client
    seed_rule("rule.a")
    r = c.request(
        "DELETE",
        "/api/alert-rules/rule.a",
        params={"expected_revision": "1"},
    )
    assert r.status_code == 200
    assert store.get_alert_rule("rule.a", include_deleted=True).deleted_at is not None


# ---------------------------------------------------------------------------
# 复审修复：序列化异常封闭
# ---------------------------------------------------------------------------


class StubRecord:
    """按行为模拟损坏的 record 对象。"""

    def __init__(self, behavior: str):
        self._behavior = behavior

    def model_dump(self, mode="python"):
        if self._behavior == "raise":
            raise RuntimeError("secret path C:\\Users\\secret\\db.sqlite3")
        if self._behavior == "non_dict":
            return ["not", "a", "dict"]
        if self._behavior == "non_json":
            return {"bad": object()}
        if self._behavior == "nan":
            return {"value": float("nan")}
        return {"ok": True}


@pytest.mark.parametrize(
    "behavior",
    ["missing", "raise", "non_dict", "non_json", "nan"],
)
def test_post_serialization_failure_500(client, monkeypatch, behavior):
    c, _, _ = client
    record = object() if behavior == "missing" else StubRecord(behavior)
    monkeypatch.setattr(store, "create_alert_rule", lambda *a, **k: record)
    r = c.post("/api/alert-rules", json=payload())
    assert r.status_code == 500
    assert r.json()["detail"] == "告警规则服务内部错误"
    assert "secret" not in r.text
    assert "C:\\Users" not in r.text
    assert "Traceback" not in r.text


@pytest.mark.parametrize(
    "records",
    [
        [StubRecord("ok"), StubRecord("raise")],
        [StubRecord("ok"), StubRecord("non_dict")],
        [StubRecord("ok"), StubRecord("non_json")],
        [StubRecord("ok"), StubRecord("nan")],
        42,
        None,
    ],
)
def test_list_serialization_failure_500(client, monkeypatch, records):
    c, _, _ = client
    monkeypatch.setattr(store, "list_alert_rules", lambda *a, **k: records)
    r = c.get("/api/alert-rules")
    assert r.status_code == 500
    assert r.json()["detail"] == "告警规则服务内部错误"
    assert "Traceback" not in r.text


@pytest.mark.parametrize("behavior", ["missing", "raise", "non_dict", "non_json"])
def test_get_serialization_failure_500(client, monkeypatch, behavior):
    c, _, _ = client
    record = object() if behavior == "missing" else StubRecord(behavior)
    monkeypatch.setattr(store, "get_alert_rule", lambda *a, **k: record)
    r = c.get("/api/alert-rules/rule.a")
    assert r.status_code == 500
    assert r.json()["detail"] == "告警规则服务内部错误"
    assert "secret" not in r.text


def test_put_serialization_failure_500(client, monkeypatch):
    c, _, _ = client
    monkeypatch.setattr(
        store, "replace_alert_rule", lambda *a, **k: StubRecord("raise")
    )
    r = c.put(
        "/api/alert-rules/rule.a",
        params={"expected_revision": "1"},
        json=payload(rule_id="rule.a"),
    )
    assert r.status_code == 500
    assert r.json()["detail"] == "告警规则服务内部错误"
    assert "secret" not in r.text


def test_delete_serialization_failure_500(client, monkeypatch):
    c, _, _ = client
    monkeypatch.setattr(
        store, "delete_alert_rule", lambda *a, **k: StubRecord("raise")
    )
    r = c.delete("/api/alert-rules/rule.a", params={"expected_revision": "1"})
    assert r.status_code == 500
    assert r.json()["detail"] == "告警规则服务内部错误"
    assert "secret" not in r.text


# ---------------------------------------------------------------------------
# 复审修复：非法输入 Store 零调用
# ---------------------------------------------------------------------------


def test_invalid_inputs_do_not_call_store(client, monkeypatch):
    c, _, db_path = client
    calls = {"create": 0, "list": 0, "get": 0, "replace": 0, "delete": 0}
    targets = {
        "create_alert_rule": store.create_alert_rule,
        "list_alert_rules": store.list_alert_rules,
        "get_alert_rule": store.get_alert_rule,
        "replace_alert_rule": store.replace_alert_rule,
        "delete_alert_rule": store.delete_alert_rule,
    }
    for func_name, real in targets.items():

        def counting(*args, _name=func_name, _real=real, **kwargs):
            calls[_name] += 1
            return _real(*args, **kwargs)

        monkeypatch.setattr(store, func_name, counting)

    assert c.post("/api/alert-rules", json={"rule_id": 123}).status_code == 422
    assert c.post("/api/alert-rules", json=payload(rule_id="bad id")).status_code == 422
    assert c.get("/api/alert-rules/bad id").status_code == 422
    assert (
        c.put(
            "/api/alert-rules/bad id",
            params={"expected_revision": "1"},
            json=payload(rule_id="bad id"),
        ).status_code
        == 422
    )
    assert (
        c.delete("/api/alert-rules/bad id", params={"expected_revision": "1"}).status_code
        == 422
    )
    assert c.get("/api/alert-rules", params={"code": "00000"}).status_code == 422
    assert c.get("/api/alert-rules", params={"enabled": "1"}).status_code == 422
    assert c.get("/api/alert-rules", params={"limit": "0"}).status_code == 422
    assert c.get("/api/alert-rules", params={"offset": "-1"}).status_code == 422
    assert (
        c.get(
            "/api/alert-rules",
            params=[("limit", "1"), ("limit", "2")],
        ).status_code
        == 422
    )
    assert (
        c.put(
            "/api/alert-rules/rule.a",
            params={"expected_revision": "0"},
            json=payload(rule_id="rule.a"),
        ).status_code
        == 422
    )
    assert (
        c.delete(
            "/api/alert-rules/rule.a",
            params={"expected_revision": "0"},
        ).status_code
        == 422
    )
    assert calls == {"create": 0, "list": 0, "get": 0, "replace": 0, "delete": 0}
    assert not db_path.exists()


# ---------------------------------------------------------------------------
# 复审修复：API Key 实际继承
# ---------------------------------------------------------------------------


def test_api_key_inheritance(client):
    c, _, _ = client
    import app as app_module

    original_key = app_module._API_KEY
    app_module._API_KEY = "test-secret-key"
    try:
        assert c.get("/api/alert-rules").status_code == 401
        assert c.post("/api/alert-rules", json=payload()).status_code == 401
        assert (
            c.delete("/api/alert-rules/rule.a", params={"expected_revision": "1"}).status_code
            == 401
        )
        assert (
            c.get(
                "/api/alert-rules",
                headers={"authorization": "Bearer wrong-key"},
            ).status_code
            == 401
        )
        assert (
            c.get(
                "/api/alert-rules",
                headers={"authorization": "Bearer test-secret-key"},
            ).status_code
            == 200
        )
        assert (
            c.post(
                "/api/alert-rules",
                headers={"authorization": "Bearer test-secret-key"},
                json=payload(),
            ).status_code
            == 201
        )
        assert (
            c.delete(
                "/api/alert-rules/rule.sma-cross",
                headers={"authorization": "Bearer test-secret-key"},
                params={"expected_revision": "1"},
            ).status_code
            == 200
        )
        # OPTIONS 与 /api/health 豁免鉴权
        assert c.options("/api/alert-rules").status_code != 401
        assert c.get("/api/health").status_code != 401
    finally:
        app_module._API_KEY = original_key


# ---------------------------------------------------------------------------
# 复审修复：API 并发乐观锁
# ---------------------------------------------------------------------------


def test_api_put_concurrent_optimistic_lock(client):
    c, _, _ = client
    rounds = 20
    for round_idx in range(rounds):
        rule_id = f"rule.cput.{round_idx}"
        seed_rule(rule_id)
        results: list[int] = []
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            r = c.put(
                f"/api/alert-rules/{rule_id}",
                params={"expected_revision": "1"},
                json=payload(rule_id=rule_id, code="600000"),
            )
            results.append(r.status_code)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)
        assert not t1.is_alive() and not t2.is_alive()
        assert sorted(results) == [200, 409], (round_idx, results)
        rec = store.get_alert_rule(rule_id)
        assert rec is not None and rec.revision == 2


def test_api_delete_concurrent_optimistic_lock(client):
    c, _, _ = client
    rounds = 20
    for round_idx in range(rounds):
        rule_id = f"rule.cdel.{round_idx}"
        seed_rule(rule_id)
        results: list[int] = []
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            r = c.delete(
                f"/api/alert-rules/{rule_id}",
                params={"expected_revision": "1"},
            )
            results.append(r.status_code)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)
        assert not t1.is_alive() and not t2.is_alive()
        assert sorted(results) == [200, 404], (round_idx, results)
        rec = store.get_alert_rule(rule_id, include_deleted=True)
        assert rec is not None and rec.deleted_at is not None and rec.revision == 2
