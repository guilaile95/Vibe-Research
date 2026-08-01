"""告警规则 SQLite 存储合同测试。

所有写测试通过 tmp_path + VIBE_RESEARCH_ALERT_RULE_DB 隔离，
不触碰真实 ~/.vibe-research、VR_DATA_DIR 或任何用户数据文件。
"""

from __future__ import annotations

import importlib
import multiprocessing
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import alert_rule_store as store
import alert_rules as ar

_DB_ENV = "VIBE_RESEARCH_ALERT_RULE_DB"
_TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$")

T0 = datetime(2026, 8, 1, 3, 4, 5, 123456, tzinfo=timezone.utc)


@pytest.fixture
def db_path(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "nested" / "alert_rules.sqlite3"
    monkeypatch.setenv(_DB_ENV, str(path))
    monkeypatch.delenv("VR_DATA_DIR", raising=False)
    return path


def trigger_condition(trigger="sma_golden_cross") -> ar.TechnicalTriggerCondition:
    return ar.TechnicalTriggerCondition(kind="technical_trigger", trigger=trigger)


def rule(*, rule_id="rule.1", code="000001", enabled=True, condition=None) -> ar.AlertRule:
    return ar.AlertRule(
        rule_id=rule_id,
        code=code,
        enabled=enabled,
        condition=condition or trigger_condition(),
    )


def raw(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def db_fingerprint(path: Path) -> tuple[int, bytes, list[str]]:
    return (
        path.stat().st_mtime_ns,
        path.read_bytes(),
        sorted(p.name for p in path.parent.iterdir()),
    )


# ---------------------------------------------------------------------------
# 数据库位置与初始化
# ---------------------------------------------------------------------------


def test_db_path_priority(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit.sqlite3"
    data_dir = tmp_path / "data"
    monkeypatch.setenv(_DB_ENV, str(explicit))
    monkeypatch.setenv("VR_DATA_DIR", str(data_dir))
    assert store.alert_rule_db_path() == str(explicit)

    monkeypatch.delenv(_DB_ENV)
    assert store.alert_rule_db_path() == str(data_dir / "alert_rules.sqlite3")

    monkeypatch.delenv("VR_DATA_DIR")
    assert store.alert_rule_db_path() == str(
        Path.home() / ".vibe-research" / "alert_rules.sqlite3"
    )


def test_import_has_no_filesystem_side_effect(db_path):
    importlib.reload(store)
    assert not db_path.exists()
    assert not db_path.parent.exists()


def test_readonly_access_on_missing_db_creates_nothing(db_path):
    assert store.get_alert_rule("rule.1") is None
    assert store.list_alert_rules() == []
    assert not db_path.exists()
    assert not db_path.parent.exists()


def test_first_write_initializes_schema(db_path):
    store.create_alert_rule(rule(), now=T0)
    assert db_path.is_file()
    conn = raw(db_path)
    try:
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        indexes = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(alert_rules)")
        }
    finally:
        conn.close()
    assert version == store.ALERT_RULE_STORE_SCHEMA_VERSION == "alert-rule-store.v0.1"
    assert {"schema_meta", "alert_rules"} <= tables
    assert {
        "idx_alert_rules_code",
        "idx_alert_rules_enabled",
        "idx_alert_rules_updated_at",
    } <= indexes
    assert columns == {
        "rule_id",
        "code",
        "enabled",
        "condition_kind",
        "rule_json",
        "revision",
        "created_at",
        "updated_at",
        "deleted_at",
    }


# ---------------------------------------------------------------------------
# 创建与读取
# ---------------------------------------------------------------------------


def test_create_round_trip(db_path):
    original = rule()
    record = store.create_alert_rule(original, now=T0)
    assert record.schema_version == store.ALERT_RULE_RECORD_SCHEMA_VERSION
    assert record.revision == 1
    assert record.created_at == record.updated_at == "2026-08-01T03:04:05.123456Z"
    assert _TS_RE.fullmatch(record.created_at)
    assert record.deleted_at is None
    assert record.rule == original
    assert original == rule()  # 入参未被修改

    loaded = store.get_alert_rule("rule.1")
    assert loaded == record
    assert loaded.rule.condition.kind == "technical_trigger"


def test_create_uses_real_utc_when_now_is_omitted(db_path):
    before = datetime.now(timezone.utc)
    record = store.create_alert_rule(rule())
    after = datetime.now(timezone.utc)
    observed = datetime.strptime(record.created_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )
    assert before - timedelta(seconds=1) <= observed <= after + timedelta(seconds=1)


def test_create_rejects_naive_now(db_path):
    with pytest.raises(store.AlertRuleStoreInputError):
        store.create_alert_rule(rule(), now=datetime(2026, 8, 1, 3, 4, 5, 123456))
    assert not db_path.exists()


def test_create_normalizes_non_utc_now(db_path):
    offset_now = T0.astimezone(timezone(timedelta(hours=8)))
    record = store.create_alert_rule(rule(), now=offset_now)
    assert record.created_at == "2026-08-01T03:04:05.123456Z"


def test_create_duplicate_rule_id_conflicts(db_path):
    store.create_alert_rule(rule(), now=T0)
    with pytest.raises(store.AlertRuleAlreadyExistsError):
        store.create_alert_rule(rule(code="600000"), now=T0)
    assert store.get_alert_rule("rule.1").rule.code == "000001"


def test_create_duplicate_rule_id_conflicts_even_when_soft_deleted(db_path):
    store.create_alert_rule(rule(), now=T0)
    store.delete_alert_rule("rule.1", expected_revision=1, now=T0)
    with pytest.raises(store.AlertRuleAlreadyExistsError):
        store.create_alert_rule(rule(), now=T0)
    assert store.get_alert_rule("rule.1", include_deleted=True).deleted_at is not None


def test_create_rejects_full_width_code(db_path):
    with pytest.raises(Exception):
        rule(code="０００００１")
    assert not db_path.exists()


def test_create_rejects_non_alert_rule(db_path):
    with pytest.raises(store.AlertRuleStoreInputError):
        store.create_alert_rule({"rule_id": "rule.1"}, now=T0)


@pytest.mark.parametrize("rule_id", ["", " rule.1", "-bad", "x" * 65, 1, None])
def test_get_rejects_invalid_rule_id(db_path, rule_id):
    with pytest.raises(ValueError):
        store.get_alert_rule(rule_id)


def test_get_special_character_rule_id_is_parameterized(db_path):
    record = store.create_alert_rule(rule(rule_id="rule.1-test_test"), now=T0)
    assert store.get_alert_rule("rule.1-test_test") == record
    assert store.list_alert_rules(code="000001")[0].rule.rule_id == "rule.1-test_test"


def test_get_missing_rule_returns_none(db_path):
    store.create_alert_rule(rule(), now=T0)
    assert store.get_alert_rule("rule.404") is None


# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------


def seed_three(db_path) -> None:
    store.create_alert_rule(rule(rule_id="rule.b", code="000001"), now=T0)
    store.create_alert_rule(rule(rule_id="rule.a", code="000001"), now=T0)
    store.create_alert_rule(
        rule(rule_id="rule.c", code="600000", enabled=False),
        now=T0 + timedelta(seconds=1),
    )


def test_list_stable_sort(db_path):
    seed_three(db_path)
    assert [r.rule.rule_id for r in store.list_alert_rules()] == ["rule.c", "rule.a", "rule.b"]


def test_list_code_and_enabled_filters(db_path):
    seed_three(db_path)
    assert [r.rule.rule_id for r in store.list_alert_rules(code="600000")] == ["rule.c"]
    assert [r.rule.rule_id for r in store.list_alert_rules(enabled=True)] == [
        "rule.a",
        "rule.b",
    ]
    assert [r.rule.rule_id for r in store.list_alert_rules(enabled=False)] == ["rule.c"]
    assert store.list_alert_rules(code="000002") == []


def test_list_include_deleted(db_path):
    seed_three(db_path)
    store.delete_alert_rule("rule.a", expected_revision=1, now=T0 + timedelta(seconds=2))
    assert [r.rule.rule_id for r in store.list_alert_rules()] == ["rule.c", "rule.b"]
    assert [r.rule.rule_id for r in store.list_alert_rules(include_deleted=True)] == [
        "rule.a",
        "rule.c",
        "rule.b",
    ]


def test_list_limit_and_offset(db_path):
    seed_three(db_path)
    assert [r.rule.rule_id for r in store.list_alert_rules(limit=2)] == ["rule.c", "rule.a"]
    assert [r.rule.rule_id for r in store.list_alert_rules(limit=2, offset=1)] == [
        "rule.a",
        "rule.b",
    ]
    assert store.list_alert_rules(limit=1, offset=99) == []


@pytest.mark.parametrize("limit", [True, False, "10", 0, -1, 201, 1.0, None])
def test_list_rejects_invalid_limit(db_path, limit):
    with pytest.raises(store.AlertRuleStoreInputError):
        store.list_alert_rules(limit=limit)


@pytest.mark.parametrize("offset", [True, False, "0", -1, 1.0, None])
def test_list_rejects_invalid_offset(db_path, offset):
    with pytest.raises(store.AlertRuleStoreInputError):
        store.list_alert_rules(offset=offset)


@pytest.mark.parametrize("enabled", [0, 1, "true", "false"])
def test_list_rejects_non_bool_enabled(db_path, enabled):
    with pytest.raises(store.AlertRuleStoreInputError):
        store.list_alert_rules(enabled=enabled)


@pytest.mark.parametrize("include_deleted", [0, 1, "true", None])
def test_list_rejects_non_bool_include_deleted(db_path, include_deleted):
    with pytest.raises(store.AlertRuleStoreInputError):
        store.list_alert_rules(include_deleted=include_deleted)


@pytest.mark.parametrize("code", ["abc", "12345", " 000001", "０００００１", 1])
def test_list_rejects_invalid_code(db_path, code):
    store.create_alert_rule(rule(), now=T0)
    with pytest.raises(store.AlertRuleStoreInputError):
        store.list_alert_rules(code=code)


# ---------------------------------------------------------------------------
# 完整替换
# ---------------------------------------------------------------------------


def test_replace_updates_code_enabled_and_condition(db_path):
    store.create_alert_rule(rule(), now=T0)
    replacement = rule(
        code="600000",
        enabled=False,
        condition=ar.MetricThresholdCondition(
            kind="metric_threshold", metric="close", operator="gt", threshold=10.5
        ),
    )
    record = store.replace_alert_rule(
        "rule.1", replacement, expected_revision=1, now=T0 + timedelta(seconds=1)
    )
    assert record.rule == replacement
    assert record.revision == 2
    assert record.created_at == "2026-08-01T03:04:05.123456Z"
    assert record.updated_at == "2026-08-01T03:04:06.123456Z"
    assert record.deleted_at is None
    assert store.get_alert_rule("rule.1") == record

    conn = raw(db_path)
    try:
        row = conn.execute("SELECT * FROM alert_rules WHERE rule_id = 'rule.1'").fetchone()
    finally:
        conn.close()
    assert (row["code"], row["enabled"], row["condition_kind"]) == (
        "600000",
        0,
        "metric_threshold",
    )


def test_replace_updated_at_is_strictly_monotonic(db_path):
    store.create_alert_rule(rule(), now=T0)
    record = store.replace_alert_rule(
        "rule.1", rule(code="600000"), expected_revision=1, now=T0 - timedelta(days=1)
    )
    assert record.updated_at == "2026-08-01T03:04:05.123457Z"

    again = store.replace_alert_rule(
        "rule.1", rule(code="000001"), expected_revision=2, now=T0
    )
    assert again.updated_at == "2026-08-01T03:04:05.123458Z"


def test_replace_rejects_rule_id_mismatch(db_path):
    store.create_alert_rule(rule(), now=T0)
    with pytest.raises(store.AlertRuleStoreInputError):
        store.replace_alert_rule("rule.1", rule(rule_id="rule.2"), expected_revision=1)
    assert store.get_alert_rule("rule.1").revision == 1


@pytest.mark.parametrize("expected_revision", [True, "1", 0, -1, 1.0, None])
def test_replace_rejects_invalid_expected_revision(db_path, expected_revision):
    store.create_alert_rule(rule(), now=T0)
    with pytest.raises(store.AlertRuleStoreInputError):
        store.replace_alert_rule(
            "rule.1", rule(code="600000"), expected_revision=expected_revision
        )


def test_replace_stale_revision_conflicts_and_keeps_data(db_path):
    store.create_alert_rule(rule(), now=T0)
    first = store.replace_alert_rule(
        "rule.1", rule(code="600000"), expected_revision=1, now=T0 + timedelta(seconds=1)
    )
    assert first.revision == 2
    with pytest.raises(store.AlertRuleRevisionConflictError):
        store.replace_alert_rule(
            "rule.1", rule(code="000002"), expected_revision=1, now=T0 + timedelta(seconds=2)
        )
    assert store.get_alert_rule("rule.1") == first


def test_replace_missing_rule_raises_not_found(db_path):
    store.create_alert_rule(rule(), now=T0)
    with pytest.raises(store.AlertRuleNotFoundError):
        store.replace_alert_rule("rule.404", rule(rule_id="rule.404"), expected_revision=1)


def test_replace_deleted_rule_is_not_revived(db_path):
    store.create_alert_rule(rule(), now=T0)
    deleted = store.delete_alert_rule("rule.1", expected_revision=1, now=T0)
    with pytest.raises(store.AlertRuleNotFoundError):
        store.replace_alert_rule(
            "rule.1", rule(code="600000"), expected_revision=deleted.revision
        )
    assert store.get_alert_rule("rule.1", include_deleted=True) == deleted


# ---------------------------------------------------------------------------
# 软删除
# ---------------------------------------------------------------------------


def test_soft_delete_hides_rule_but_keeps_row(db_path):
    store.create_alert_rule(rule(), now=T0)
    record = store.delete_alert_rule(
        "rule.1", expected_revision=1, now=T0 + timedelta(seconds=1)
    )
    assert record.revision == 2
    assert record.deleted_at == record.updated_at == "2026-08-01T03:04:06.123456Z"
    assert record.created_at == "2026-08-01T03:04:05.123456Z"

    assert store.get_alert_rule("rule.1") is None
    assert store.list_alert_rules() == []
    assert store.get_alert_rule("rule.1", include_deleted=True) == record
    assert [r.rule.rule_id for r in store.list_alert_rules(include_deleted=True)] == ["rule.1"]

    conn = raw(db_path)
    try:
        rows = conn.execute("SELECT rule_id, deleted_at FROM alert_rules").fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["deleted_at"] == record.deleted_at


def test_delete_twice_fails(db_path):
    store.create_alert_rule(rule(), now=T0)
    deleted = store.delete_alert_rule("rule.1", expected_revision=1, now=T0)
    with pytest.raises(store.AlertRuleNotFoundError):
        store.delete_alert_rule("rule.1", expected_revision=deleted.revision, now=T0)
    assert store.get_alert_rule("rule.1", include_deleted=True) == deleted


def test_delete_stale_revision_conflicts(db_path):
    store.create_alert_rule(rule(), now=T0)
    store.replace_alert_rule("rule.1", rule(code="600000"), expected_revision=1, now=T0)
    with pytest.raises(store.AlertRuleRevisionConflictError):
        store.delete_alert_rule("rule.1", expected_revision=1, now=T0)
    assert store.get_alert_rule("rule.1").deleted_at is None


def test_delete_missing_rule_raises_not_found(db_path):
    store.create_alert_rule(rule(), now=T0)
    with pytest.raises(store.AlertRuleNotFoundError):
        store.delete_alert_rule("rule.404", expected_revision=1)


@pytest.mark.parametrize("expected_revision", [True, "1", 0, -1, 1.0, None])
def test_delete_rejects_invalid_expected_revision(db_path, expected_revision):
    store.create_alert_rule(rule(), now=T0)
    with pytest.raises(store.AlertRuleStoreInputError):
        store.delete_alert_rule("rule.1", expected_revision=expected_revision)


def test_stale_revision_sequence_keeps_revision_two_intact(db_path):
    created = store.create_alert_rule(rule(), now=T0)
    assert created.revision == 1
    second = store.replace_alert_rule(
        "rule.1", rule(code="600000"), expected_revision=1, now=T0 + timedelta(seconds=1)
    )
    assert second.revision == 2
    with pytest.raises(store.AlertRuleRevisionConflictError):
        store.replace_alert_rule(
            "rule.1", rule(code="000002"), expected_revision=1, now=T0 + timedelta(seconds=2)
        )
    current = store.get_alert_rule("rule.1")
    assert current == second
    assert current.rule.code == "600000"


# ---------------------------------------------------------------------------
# 记录模型
# ---------------------------------------------------------------------------


def test_record_model_is_strict_and_frozen():
    record = store.AlertRuleRecord(
        rule=rule(),
        revision=1,
        created_at="2026-08-01T03:04:05.123456Z",
        updated_at="2026-08-01T03:04:05.123456Z",
        deleted_at=None,
    )
    with pytest.raises(Exception):
        record.revision = 2
    with pytest.raises(Exception):
        store.AlertRuleRecord(
            rule=rule(),
            revision=1,
            created_at="2026-08-01T03:04:05.123456Z",
            updated_at="2026-08-01T03:04:05.123456Z",
            deleted_at=None,
            unexpected=1,
        )


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-08-01T03:04:05.123456",
        "2026-08-01T03:04:05+08:00",
        "2026-08-01T03:04:05Z",
        "2026-08-01T03:04:05.123456+08:00",
        "2026-02-31T03:04:05.123456Z",
        " 2026-08-01T03:04:05.123456Z",
        "2026-08-01T03:04:05.123456Z ",
    ],
)
def test_record_rejects_invalid_timestamp(timestamp):
    with pytest.raises(Exception):
        store.AlertRuleRecord(
            rule=rule(),
            revision=1,
            created_at=timestamp,
            updated_at=timestamp,
            deleted_at=None,
        )


@pytest.mark.parametrize("revision", [0, -1, True, "1", 1.0])
def test_record_rejects_invalid_revision(revision):
    with pytest.raises(Exception):
        store.AlertRuleRecord(
            rule=rule(),
            revision=revision,
            created_at="2026-08-01T03:04:05.123456Z",
            updated_at="2026-08-01T03:04:05.123456Z",
            deleted_at=None,
        )


# ---------------------------------------------------------------------------
# 损坏防护
# ---------------------------------------------------------------------------


def tamper(db_path: Path, sql: str, params: tuple = ()) -> None:
    conn = raw(db_path)
    try:
        conn.execute(sql, params)
    finally:
        conn.close()


SCHEMA_CORRUPTIONS = {
    "bad_schema_version": ("UPDATE schema_meta SET value = 'alert-rule-store.v9'", ()),
    "missing_schema_meta": ("DROP TABLE schema_meta", ()),
    "illegal_metadata": ("DELETE FROM schema_meta", ()),
    "missing_rules_table": ("DROP TABLE alert_rules", ()),
}

ROW_CORRUPTIONS = {
    "invalid_rule_json": ("UPDATE alert_rules SET rule_json = '{'", (), "rule.1"),
    "wrong_rule_schema": (
        "UPDATE alert_rules SET rule_json = ?",
        (
            '{"schema_version": "alert-rule.v9", "rule_id": "rule.1", "code": "000001", '
            '"enabled": true, "condition": {"kind": "technical_trigger", '
            '"trigger": "sma_golden_cross"}}',
        ),
        "rule.1",
    ),
    "mirror_rule_id": ("UPDATE alert_rules SET rule_id = 'rule.9'", (), "rule.9"),
    "mirror_code": ("UPDATE alert_rules SET code = '600000'", (), "rule.1"),
    "mirror_enabled": ("UPDATE alert_rules SET enabled = 0", (), "rule.1"),
    "mirror_condition_kind": (
        "UPDATE alert_rules SET condition_kind = 'metric_threshold'",
        (),
        "rule.1",
    ),
    "invalid_revision": ("UPDATE alert_rules SET revision = 'x'", (), "rule.1"),
    "invalid_timestamp": (
        "UPDATE alert_rules SET updated_at = '2026-08-01 03:04:05'",
        (),
        "rule.1",
    ),
}


@pytest.mark.parametrize("case", sorted(SCHEMA_CORRUPTIONS))
def test_schema_corruption_fails_closed_for_reads_and_writes(db_path, case):
    store.create_alert_rule(rule(), now=T0)
    sql, params = SCHEMA_CORRUPTIONS[case]
    tamper(db_path, sql, params)
    before = db_fingerprint(db_path)

    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules(include_deleted=True)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.get_alert_rule("rule.1", include_deleted=True)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(rule_id="rule.2"), now=T0)

    assert db_fingerprint(db_path) == before


@pytest.mark.parametrize("case", sorted(ROW_CORRUPTIONS))
def test_row_corruption_fails_closed_without_rewriting_db(db_path, case):
    store.create_alert_rule(rule(), now=T0)
    sql, params, rule_id = ROW_CORRUPTIONS[case]
    tamper(db_path, sql, params)
    before = db_fingerprint(db_path)

    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules(include_deleted=True)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.get_alert_rule(rule_id, include_deleted=True)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.replace_alert_rule(
            rule_id, rule(rule_id=rule_id, code="600000"), expected_revision=1, now=T0
        )

    assert db_fingerprint(db_path) == before



def test_corrupted_db_is_not_reported_as_empty(db_path):
    store.create_alert_rule(rule(), now=T0)
    tamper(db_path, "DROP TABLE schema_meta")
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()


def test_unreadable_database_file_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_bytes(b"this is not a sqlite database")
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.get_alert_rule("rule.1")


# ---------------------------------------------------------------------------
# 只读纪律
# ---------------------------------------------------------------------------


def test_reads_do_not_touch_existing_database(db_path):
    record = store.create_alert_rule(rule(), now=T0)
    before = db_fingerprint(db_path)

    assert store.get_alert_rule("rule.1") == record
    assert store.list_alert_rules() == [record]
    assert store.get_alert_rule("rule.404") is None

    after = db_fingerprint(db_path)
    assert after == before
    assert after[2] == ["alert_rules.sqlite3"]


# ---------------------------------------------------------------------------
# 已存在数据库保护 (P1)
# ---------------------------------------------------------------------------


def test_preexisting_zero_byte_file_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_bytes(b"")
    before = db_fingerprint(db_path)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.get_alert_rule("rule.1")
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)
    assert db_fingerprint(db_path) == before


def test_preexisting_empty_sqlite_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.close()
    before = db_fingerprint(db_path)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.get_alert_rule("rule.1")
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)
    assert db_fingerprint(db_path) == before


def test_preexisting_unrelated_table_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.execute("CREATE TABLE other_app (id INTEGER PRIMARY KEY, data TEXT)")
    conn.execute("INSERT INTO other_app (data) VALUES ('hello')")
    conn.close()
    before = db_fingerprint(db_path)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)
    assert db_fingerprint(db_path) == before
    # Verify unrelated table is intact
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT data FROM other_app").fetchall()
    conn.close()
    assert rows == [("hello",)]


def test_preexisting_only_schema_meta_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', 'alert-rule-store.v0.1')"
    )
    conn.close()
    before = db_fingerprint(db_path)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)
    assert db_fingerprint(db_path) == before


def test_preexisting_only_alert_rules_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.execute(
        "CREATE TABLE alert_rules (rule_id TEXT PRIMARY KEY, code TEXT NOT NULL, "
        "enabled INTEGER NOT NULL, condition_kind TEXT NOT NULL, rule_json TEXT NOT NULL, "
        "revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "deleted_at TEXT)"
    )
    conn.close()
    before = db_fingerprint(db_path)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)
    assert db_fingerprint(db_path) == before


# ---------------------------------------------------------------------------
# TOCTOU 原子初始化资格 (P1)
# ---------------------------------------------------------------------------


def test_toctou_external_empty_file_race(db_path, monkeypatch):
    """A observes a missing path, B creates an empty SQLite file, A must fail-closed."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(store, "_OPEN_WAIT_TOTAL_SECONDS", 0.3)
    real_open = os.open

    def fake_open(path, flags, *args, **kwargs):
        # B creates a legal empty SQLite database at the race point
        sqlite3.connect(str(path)).close()
        raise FileExistsError(f"[Errno 17] File exists: {str(path)}")

    monkeypatch.setattr(store.os, "open", fake_open)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)

    fp1 = db_fingerprint(db_path)
    # B's file must be untouched: still empty, no project objects
    assert len(fp1[1]) == 0
    conn = sqlite3.connect(str(db_path))
    objects = conn.execute(
        "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    ).fetchall()
    conn.close()
    assert objects == []

    # Second attempt (file now pre-existing) also fails closed and changes nothing
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(rule_id="rule.2"), now=T0)
    fp2 = db_fingerprint(db_path)
    assert fp2 == fp1


def test_toctou_external_unrelated_db_race(db_path, monkeypatch):
    """A observes a missing path, B creates an unrelated database, A must fail-closed."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    real_open = os.open

    def fake_open(path, flags, *args, **kwargs):
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE other_app (id INTEGER PRIMARY KEY, data TEXT)")
        conn.execute("INSERT INTO other_app (data) VALUES ('hello')")
        conn.commit()
        conn.close()
        raise FileExistsError(f"[Errno 17] File exists: {str(path)}")

    monkeypatch.setattr(store.os, "open", fake_open)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)

    conn = sqlite3.connect(str(db_path))
    assert conn.execute("SELECT data FROM other_app").fetchall() == [("hello",)]
    names = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    ]
    conn.close()
    assert "alert_rules" not in names
    assert "schema_meta" not in names


def test_toctou_legitimate_concurrent_initialization(db_path, monkeypatch):
    """A and B both see a missing path; B wins O_EXCL, A waits and re-validates."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    real_open = os.open
    started = threading.Event()
    release = threading.Event()
    results: dict[str, str] = {}

    def fake_open(path, flags, *args, **kwargs):
        if not started.is_set():
            # First caller (A) is parked before its O_EXCL so B wins the race.
            started.set()
            assert release.wait(timeout=10), "A was not released in time"
        return real_open(path, flags, *args, **kwargs)

    def worker_a():
        try:
            store.create_alert_rule(rule(rule_id="race.1"), now=T0)
            results["a"] = "ok"
        except Exception as exc:
            results["a"] = type(exc).__name__

    def worker_b():
        try:
            store.create_alert_rule(rule(rule_id="race.1"), now=T0)
            results["b"] = "ok"
        except Exception as exc:
            results["b"] = type(exc).__name__

    monkeypatch.setattr(store.os, "open", fake_open)
    try:
        t_a = threading.Thread(target=worker_a)
        t_a.start()
        assert started.wait(timeout=5), "A never reached the race point"
        t_b = threading.Thread(target=worker_b)
        t_b.start()
        t_b.join(timeout=15)
        assert results["b"] == "ok", results
        release.set()
        t_a.join(timeout=15)
        assert results["a"] == "AlertRuleAlreadyExistsError", results
    finally:
        release.set()

    records = store.list_alert_rules()
    assert len(records) == 1
    assert records[0].rule.rule_id == "race.1"
    assert records[0].revision == 1


# ---------------------------------------------------------------------------
# Schema 结构验证 (P2)
# ---------------------------------------------------------------------------


def _create_valid_db(path: Path) -> None:
    """Create a valid database using the store itself."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    for stmt in store._DDL:
        conn.execute(stmt)
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES (?, ?)",
        ("schema_version", store.ALERT_RULE_STORE_SCHEMA_VERSION),
    )
    conn.close()


def test_missing_code_index_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _create_valid_db(db_path)
    tamper(db_path, "DROP INDEX idx_alert_rules_code")
    before = db_fingerprint(db_path)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)
    assert db_fingerprint(db_path) == before


def test_missing_enabled_index_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _create_valid_db(db_path)
    tamper(db_path, "DROP INDEX idx_alert_rules_enabled")
    before = db_fingerprint(db_path)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)
    assert db_fingerprint(db_path) == before


def test_missing_updated_at_index_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _create_valid_db(db_path)
    tamper(db_path, "DROP INDEX idx_alert_rules_updated_at")
    before = db_fingerprint(db_path)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)
    assert db_fingerprint(db_path) == before


def test_wrong_column_index_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _create_valid_db(db_path)
    tamper(db_path, "DROP INDEX idx_alert_rules_code")
    tamper(db_path, "CREATE INDEX idx_alert_rules_code ON alert_rules (rule_id)")
    before = db_fingerprint(db_path)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)
    assert db_fingerprint(db_path) == before


def test_rule_id_without_primary_key_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.execute(
        "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE alert_rules (rule_id TEXT, code TEXT NOT NULL, "
        "enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)), "
        "condition_kind TEXT NOT NULL, rule_json TEXT NOT NULL, "
        "revision INTEGER NOT NULL CHECK (revision >= 1), "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT)"
    )
    conn.execute("CREATE INDEX idx_alert_rules_code ON alert_rules (code)")
    conn.execute("CREATE INDEX idx_alert_rules_enabled ON alert_rules (enabled)")
    conn.execute("CREATE INDEX idx_alert_rules_updated_at ON alert_rules (updated_at)")
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', 'alert-rule-store.v0.1')"
    )
    conn.close()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)


def test_enabled_without_check_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.execute(
        "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE alert_rules (rule_id TEXT PRIMARY KEY, code TEXT NOT NULL, "
        "enabled INTEGER NOT NULL, "
        "condition_kind TEXT NOT NULL, rule_json TEXT NOT NULL, "
        "revision INTEGER NOT NULL CHECK (revision >= 1), "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT)"
    )
    conn.execute("CREATE INDEX idx_alert_rules_code ON alert_rules (code)")
    conn.execute("CREATE INDEX idx_alert_rules_enabled ON alert_rules (enabled)")
    conn.execute("CREATE INDEX idx_alert_rules_updated_at ON alert_rules (updated_at)")
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', 'alert-rule-store.v0.1')"
    )
    conn.close()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)


def test_revision_without_check_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.execute(
        "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE alert_rules (rule_id TEXT PRIMARY KEY, code TEXT NOT NULL, "
        "enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)), "
        "condition_kind TEXT NOT NULL, rule_json TEXT NOT NULL, "
        "revision INTEGER NOT NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT)"
    )
    conn.execute("CREATE INDEX idx_alert_rules_code ON alert_rules (code)")
    conn.execute("CREATE INDEX idx_alert_rules_enabled ON alert_rules (enabled)")
    conn.execute("CREATE INDEX idx_alert_rules_updated_at ON alert_rules (updated_at)")
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', 'alert-rule-store.v0.1')"
    )
    conn.close()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)


def test_check_block_comment_fake_fails_closed(db_path):
    """CHECK text inside /* */ comments is not a real constraint."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _create_schema_variant(
        db_path,
        "CREATE TABLE alert_rules (rule_id TEXT PRIMARY KEY, code TEXT NOT NULL, "
        "enabled INTEGER NOT NULL /* CHECK (enabled IN (0, 1)) */, "
        "condition_kind TEXT NOT NULL, rule_json TEXT NOT NULL, "
        "revision INTEGER NOT NULL /* CHECK (revision >= 1) */, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT)",
    )
    before = db_fingerprint(db_path)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)
    assert db_fingerprint(db_path) == before


def test_check_line_comment_fake_fails_closed(db_path):
    """CHECK text inside -- comments is not a real constraint."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _create_schema_variant(
        db_path,
        "CREATE TABLE alert_rules (rule_id TEXT PRIMARY KEY, code TEXT NOT NULL,\n"
        "enabled INTEGER NOT NULL -- CHECK (enabled IN (0, 1))\n"
        ", condition_kind TEXT NOT NULL, rule_json TEXT NOT NULL,\n"
        "revision INTEGER NOT NULL -- CHECK (revision >= 1)\n"
        ", created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT)",
    )
    before = db_fingerprint(db_path)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)
    assert db_fingerprint(db_path) == before


def test_check_string_default_fake_fails_closed(db_path):
    """CHECK-like text inside string defaults is not a real constraint."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _create_schema_variant(
        db_path,
        "CREATE TABLE alert_rules (rule_id TEXT PRIMARY KEY, code TEXT NOT NULL "
        "DEFAULT 'CHECK (enabled IN (0, 1))', "
        "enabled INTEGER NOT NULL, "
        "condition_kind TEXT NOT NULL, rule_json TEXT NOT NULL, "
        "revision INTEGER NOT NULL DEFAULT 0, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT)",
    )
    before = db_fingerprint(db_path)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(), now=T0)
    assert db_fingerprint(db_path) == before


# ---------------------------------------------------------------------------
# 初始化原子性 (P2)
# ---------------------------------------------------------------------------


def _run_initialization_failure(db_path, monkeypatch, target: str) -> None:
    """让 _initialize 的指定语句失败，验证回滚、无锁残留、半成品不被复用。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    real_connect = sqlite3.connect
    armed = {"on": True}

    class FailingConnection:
        """把 execute 拦截至目标语句；其余能力透传真实连接。"""

        def __init__(self, conn):
            self._conn = conn

        @property
        def row_factory(self):
            return self._conn.row_factory

        @row_factory.setter
        def row_factory(self, value):
            self._conn.row_factory = value

        def execute(self, sql, *params):
            if armed["on"] and isinstance(sql, str) and target in sql:
                raise sqlite3.OperationalError("simulated failure")
            return self._conn.execute(sql, *params)

        def close(self):
            return self._conn.close()

    def failing_connect(*args, **kwargs):
        return FailingConnection(real_connect(*args, **kwargs))

    monkeypatch.setattr(store.sqlite3, "connect", failing_connect)
    try:
        with pytest.raises(store.AlertRuleStoreError):
            store.create_alert_rule(rule(), now=T0)
    finally:
        armed["on"] = False

    # 无部分项目 schema（表、索引、metadata 均不残留）
    conn = real_connect(str(db_path))
    objects = conn.execute(
        "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    ).fetchall()
    conn.close()
    bad = [
        name
        for _, name in objects
        if name in ("schema_meta", "alert_rules") or name.startswith("idx_alert_rules")
    ]
    assert bad == [], f"partial schema objects remain: {bad}"

    # 无锁残留：新连接立即可取写锁
    conn = real_connect(str(db_path), isolation_level=None)
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("ROLLBACK")
    conn.close()

    # 半成品文件永远不会被当作合法数据库或再次初始化
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(rule_id="rule.2"), now=T0)


def test_initialization_table_failure_rolls_back(db_path, monkeypatch):
    _run_initialization_failure(db_path, monkeypatch, "CREATE TABLE alert_rules")


def test_initialization_index_failure_rolls_back(db_path, monkeypatch):
    _run_initialization_failure(
        db_path, monkeypatch, "CREATE INDEX idx_alert_rules_code"
    )


def test_initialization_metadata_failure_rolls_back(db_path, monkeypatch):
    _run_initialization_failure(db_path, monkeypatch, "INSERT INTO schema_meta")


def test_initialization_commit_failure_rolls_back(db_path, monkeypatch):
    _run_initialization_failure(db_path, monkeypatch, "COMMIT")


# ---------------------------------------------------------------------------
# 并发测试 (P2)
# ---------------------------------------------------------------------------


def _concurrent_create_worker(db_path_str: str, rule_id: str, result_queue):
    """Worker for concurrent tests - runs in a separate thread."""
    import os
    os.environ["VIBE_RESEARCH_ALERT_RULE_DB"] = db_path_str
    try:
        importlib.reload(store)
        r = ar.AlertRule(
            rule_id=rule_id,
            code="000001",
            enabled=True,
            condition=ar.TechnicalTriggerCondition(
                kind="technical_trigger", trigger="sma_golden_cross"
            ),
        )
        store.create_alert_rule(r, now=T0)
        result_queue.append("ok")
    except store.AlertRuleAlreadyExistsError:
        result_queue.append("duplicate")
    except store.AlertRuleStoreError as exc:
        result_queue.append(f"error:{type(exc).__name__}")
    except Exception as exc:
        result_queue.append(f"unexpected:{type(exc).__name__}:{exc}")


def test_concurrent_first_initialization(db_path):
    """Two threads race to initialize the same new database."""
    rounds = 5
    for round_idx in range(rounds):
        round_path = db_path.parent / f"round_{round_idx}" / "alert_rules.sqlite3"
        round_path.parent.mkdir(parents=True, exist_ok=True)
        db_str = str(round_path)

        results: list[str] = []
        barrier = threading.Barrier(2, timeout=10)

        def worker(path_str=db_str, results_list=results):
            import os
            os.environ["VIBE_RESEARCH_ALERT_RULE_DB"] = path_str
            importlib.reload(store)
            barrier.wait()
            try:
                r = ar.AlertRule(
                    rule_id="race.rule",
                    code="000001",
                    enabled=True,
                    condition=ar.TechnicalTriggerCondition(
                        kind="technical_trigger", trigger="sma_golden_cross"
                    ),
                )
                store.create_alert_rule(r, now=T0)
                results_list.append("ok")
            except store.AlertRuleAlreadyExistsError:
                results_list.append("duplicate")
            except store.AlertRuleStoreError as exc:
                results_list.append(f"error:{type(exc).__name__}")
            except Exception as exc:
                results_list.append(f"unexpected:{type(exc).__name__}:{exc}")

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        assert sorted(results) == ["duplicate", "ok"], f"Round {round_idx}: {results}"

        # Verify database state
        import os
        os.environ["VIBE_RESEARCH_ALERT_RULE_DB"] = db_str
        importlib.reload(store)
        records = store.list_alert_rules()
        assert len(records) == 1
        assert records[0].rule.rule_id == "race.rule"
        assert records[0].revision == 1


def test_concurrent_create_same_rule_id(db_path):
    """Two threads race to create the same rule_id on an already-initialized db."""
    store.create_alert_rule(rule(rule_id="seed"), now=T0)  # initialize db
    rounds = 20
    for round_idx in range(rounds):
        target_id = f"race.{round_idx}"
        results: list[str] = []
        barrier = threading.Barrier(2, timeout=10)

        def worker(rid=target_id, results_list=results):
            barrier.wait()
            try:
                r = ar.AlertRule(
                    rule_id=rid,
                    code="000001",
                    enabled=True,
                    condition=ar.TechnicalTriggerCondition(
                        kind="technical_trigger", trigger="sma_golden_cross"
                    ),
                )
                store.create_alert_rule(r, now=T0)
                results_list.append("ok")
            except store.AlertRuleAlreadyExistsError:
                results_list.append("duplicate")
            except store.AlertRuleStoreError as exc:
                results_list.append(f"error:{type(exc).__name__}")
            except Exception as exc:
                results_list.append(f"unexpected:{type(exc).__name__}:{exc}")

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        assert sorted(results) == ["duplicate", "ok"], f"Round {round_idx}: {results}"
        rec = store.get_alert_rule(target_id)
        assert rec is not None
        assert rec.revision == 1


# ---------------------------------------------------------------------------
# URI 特殊字符 (P2)
# ---------------------------------------------------------------------------


def test_uri_space_in_path(tmp_path, monkeypatch):
    space_dir = tmp_path / "dir with spaces"
    db = space_dir / "alert rules.sqlite3"
    monkeypatch.setenv(_DB_ENV, str(db))
    monkeypatch.delenv("VR_DATA_DIR", raising=False)
    record = store.create_alert_rule(rule(), now=T0)
    assert store.get_alert_rule("rule.1") == record
    assert store.list_alert_rules() == [record]


def test_uri_unicode_in_path(tmp_path, monkeypatch):
    uni_dir = tmp_path / "数据目录"
    db = uni_dir / "告警规则.sqlite3"
    monkeypatch.setenv(_DB_ENV, str(db))
    monkeypatch.delenv("VR_DATA_DIR", raising=False)
    record = store.create_alert_rule(rule(), now=T0)
    assert store.get_alert_rule("rule.1") == record
    assert store.list_alert_rules() == [record]


def test_uri_hash_in_path(tmp_path, monkeypatch):
    hash_dir = tmp_path / "dir#fragment"
    db = hash_dir / "alert#rules.sqlite3"
    monkeypatch.setenv(_DB_ENV, str(db))
    monkeypatch.delenv("VR_DATA_DIR", raising=False)
    record = store.create_alert_rule(rule(), now=T0)
    assert store.get_alert_rule("rule.1") == record
    assert store.list_alert_rules() == [record]
    # Verify no wrong-prefix file was created
    assert sorted(p.name for p in hash_dir.iterdir()) == ["alert#rules.sqlite3"]


def test_uri_percent_in_path(tmp_path, monkeypatch):
    pct_dir = tmp_path / "dir%with%percent"
    db = pct_dir / "alert%rules.sqlite3"
    monkeypatch.setenv(_DB_ENV, str(db))
    monkeypatch.delenv("VR_DATA_DIR", raising=False)
    record = store.create_alert_rule(rule(), now=T0)
    assert store.get_alert_rule("rule.1") == record
    assert store.list_alert_rules() == [record]
    assert sorted(p.name for p in pct_dir.iterdir()) == ["alert%rules.sqlite3"]


def test_uri_quote_in_path(tmp_path, monkeypatch):
    quote_dir = tmp_path / "dir'quote"
    db = quote_dir / "alert'rules.sqlite3"
    monkeypatch.setenv(_DB_ENV, str(db))
    monkeypatch.delenv("VR_DATA_DIR", raising=False)
    record = store.create_alert_rule(rule(), now=T0)
    assert store.get_alert_rule("rule.1") == record
    assert store.list_alert_rules() == [record]
    assert sorted(p.name for p in quote_dir.iterdir()) == ["alert'rules.sqlite3"]


def test_uri_windows_question_mark_safe_failure(tmp_path, monkeypatch):
    """On Windows, '?' is illegal in filenames. Must fail with wrapped error."""
    bad_dir = tmp_path / "normal"
    bad_db = bad_dir / "bad?name.sqlite3"
    monkeypatch.setenv(_DB_ENV, str(bad_db))
    monkeypatch.delenv("VR_DATA_DIR", raising=False)
    with pytest.raises(store.AlertRuleStoreError):
        store.create_alert_rule(rule(), now=T0)
    # Must not create a truncated file
    if bad_dir.exists():
        assert not any(p.name.startswith("bad") for p in bad_dir.iterdir())


# ---------------------------------------------------------------------------
# 时间上限 (P2)
# ---------------------------------------------------------------------------


MAX_TS = datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_year_9999_replace_raises_store_error(db_path):
    store.create_alert_rule(rule(), now=MAX_TS)
    with pytest.raises(store.AlertRuleStoreError) as exc_info:
        store.replace_alert_rule(
            "rule.1", rule(code="600000"), expected_revision=1, now=MAX_TS
        )
    assert "Traceback" not in str(exc_info.value)
    # Data unchanged
    rec = store.get_alert_rule("rule.1")
    assert rec.revision == 1
    assert rec.rule.code == "000001"
    # No lock residue - subsequent read works
    assert store.list_alert_rules() == [rec]


def test_year_9999_delete_raises_store_error(db_path):
    store.create_alert_rule(rule(), now=MAX_TS)
    with pytest.raises(store.AlertRuleStoreError) as exc_info:
        store.delete_alert_rule("rule.1", expected_revision=1, now=MAX_TS)
    assert "Traceback" not in str(exc_info.value)
    # Data unchanged
    rec = store.get_alert_rule("rule.1")
    assert rec.revision == 1
    assert rec.deleted_at is None
    # No lock residue
    assert store.list_alert_rules() == [rec]


def test_year_9999_no_lock_residue_after_failure(db_path):
    store.create_alert_rule(rule(), now=MAX_TS)
    with pytest.raises(store.AlertRuleStoreError):
        store.replace_alert_rule(
            "rule.1", rule(code="600000"), expected_revision=1, now=MAX_TS
        )
    # Subsequent operations work without "database locked"
    with pytest.raises(store.AlertRuleStoreError):
        store.delete_alert_rule("rule.1", expected_revision=1, now=MAX_TS)
    # A normal-time operation still works
    rec = store.get_alert_rule("rule.1")
    assert rec is not None


# ---------------------------------------------------------------------------
# 补充边界测试：并发不同 rule_id、索引/列变体、等价 DDL、路径异常包装
# ---------------------------------------------------------------------------


def test_concurrent_create_different_rule_ids(db_path):
    """Two threads concurrently create different rule_ids on a fresh database."""
    rounds = 10
    for round_idx in range(rounds):
        round_path = db_path.parent / f"diff_{round_idx}" / "alert_rules.sqlite3"
        round_path.parent.mkdir(parents=True, exist_ok=True)
        db_str = str(round_path)
        results: list[str] = []
        barrier = threading.Barrier(2, timeout=10)

        def worker(rule_id, path_str=db_str, results_list=results):
            import os

            os.environ["VIBE_RESEARCH_ALERT_RULE_DB"] = path_str
            importlib.reload(store)
            barrier.wait()
            try:
                r = ar.AlertRule(
                    rule_id=rule_id,
                    code="000001",
                    enabled=True,
                    condition=ar.TechnicalTriggerCondition(
                        kind="technical_trigger", trigger="sma_golden_cross"
                    ),
                )
                store.create_alert_rule(r, now=T0)
                results_list.append("ok")
            except Exception as exc:
                results_list.append(f"error:{type(exc).__name__}:{exc}")

        t1 = threading.Thread(target=worker, args=("diff.a",))
        t2 = threading.Thread(target=worker, args=("diff.b",))
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        assert results == ["ok", "ok"], f"Round {round_idx}: {results}"
        import os

        os.environ["VIBE_RESEARCH_ALERT_RULE_DB"] = db_str
        importlib.reload(store)
        records = store.list_alert_rules()
        assert {rec.rule.rule_id for rec in records} == {"diff.a", "diff.b"}
        assert all(rec.revision == 1 for rec in records)


def _create_schema_variant(path: Path, table_sql: str) -> None:
    """Create schema_meta + a custom alert_rules table + the three indexes."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(table_sql)
    conn.execute("CREATE INDEX idx_alert_rules_code ON alert_rules (code)")
    conn.execute("CREATE INDEX idx_alert_rules_enabled ON alert_rules (enabled)")
    conn.execute("CREATE INDEX idx_alert_rules_updated_at ON alert_rules (updated_at)")
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?)",
        (store.ALERT_RULE_STORE_SCHEMA_VERSION,),
    )
    conn.close()


def test_partial_index_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _create_valid_db(db_path)
    tamper(db_path, "DROP INDEX idx_alert_rules_code")
    tamper(
        db_path,
        "CREATE INDEX idx_alert_rules_code ON alert_rules (code) WHERE enabled = 1",
    )
    before = db_fingerprint(db_path)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(rule_id="rule.2"), now=T0)
    assert db_fingerprint(db_path) == before


def test_composite_index_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _create_valid_db(db_path)
    tamper(db_path, "DROP INDEX idx_alert_rules_code")
    tamper(db_path, "CREATE INDEX idx_alert_rules_code ON alert_rules (code, enabled)")
    before = db_fingerprint(db_path)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(rule_id="rule.2"), now=T0)
    assert db_fingerprint(db_path) == before


def test_wrong_column_type_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _create_schema_variant(
        db_path,
        "CREATE TABLE alert_rules (rule_id TEXT PRIMARY KEY, code INTEGER NOT NULL, "
        "enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)), "
        "condition_kind TEXT NOT NULL, rule_json TEXT NOT NULL, "
        "revision INTEGER NOT NULL CHECK (revision >= 1), "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT)",
    )
    before = db_fingerprint(db_path)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(rule_id="rule.2"), now=T0)
    assert db_fingerprint(db_path) == before


def test_removed_not_null_fails_closed(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _create_schema_variant(
        db_path,
        "CREATE TABLE alert_rules (rule_id TEXT PRIMARY KEY, code TEXT, "
        "enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)), "
        "condition_kind TEXT NOT NULL, rule_json TEXT NOT NULL, "
        "revision INTEGER NOT NULL CHECK (revision >= 1), "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT)",
    )
    before = db_fingerprint(db_path)
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.create_alert_rule(rule(rule_id="rule.2"), now=T0)
    assert db_fingerprint(db_path) == before


def test_equivalent_check_format_accepted(db_path):
    """Same constraints with different spacing/case must still validate."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _create_schema_variant(
        db_path,
        "CREATE TABLE alert_rules (rule_id TEXT PRIMARY KEY, code TEXT NOT NULL, "
        "enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), "
        "condition_kind TEXT NOT NULL, rule_json TEXT NOT NULL, "
        "revision INTEGER NOT NULL check (revision>=1), "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT)",
    )
    assert store.list_alert_rules() == []
    record = store.create_alert_rule(rule(), now=T0)
    assert store.get_alert_rule("rule.1") == record


def test_mkdir_parent_blocked_wrapped(tmp_path, monkeypatch):
    """Parent path component is a file: must raise AlertRuleStoreError, not OSError."""
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"x")
    blocked_path = blocker / "alert_rules.sqlite3"
    monkeypatch.setenv(_DB_ENV, str(blocked_path))
    monkeypatch.delenv("VR_DATA_DIR", raising=False)
    with pytest.raises(store.AlertRuleStoreError):
        store.create_alert_rule(rule(), now=T0)
    assert store.list_alert_rules() == []
