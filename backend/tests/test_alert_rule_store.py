"""告警规则 SQLite 存储合同测试。

所有写测试通过 tmp_path + VIBE_RESEARCH_ALERT_RULE_DB 隔离，
不触碰真实 ~/.vibe-research、VR_DATA_DIR 或任何用户数据文件。
"""

from __future__ import annotations

import importlib
import re
import sqlite3
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







