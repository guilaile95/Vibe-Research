"""存储层专项测试：Schema、约束、CRUD、PRAGMA、损坏检测、备份、事务回滚。"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

import pytest

import evidence_thesis_store as store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path) -> Path:
    return tmp_path / "test_evidence_thesis.db"


@pytest.fixture
def initialized_db(db_path) -> Path:
    store.initialize_store(db_path)
    return db_path


# ---------------------------------------------------------------------------
# Schema 初始化
# ---------------------------------------------------------------------------

class TestSchemaInit:
    def test_initialize_creates_all_tables(self, initialized_db):
        conn = store._connect_readonly(initialized_db)
        try:
            for table in ("schema_meta", "evidence_records", "investment_theses",
                          "thesis_revisions", "thesis_evidence_links"):
                assert store._table_exists(conn, table), f"表 {table} 应存在"
        finally:
            conn.close()

    def test_initialize_writes_schema_version(self, initialized_db):
        conn = store._connect_readonly(initialized_db)
        try:
            version = store._read_schema_version(conn)
            assert version == store.SCHEMA_VERSION
        finally:
            conn.close()

    def test_initialize_is_idempotent(self, db_path):
        store.initialize_store(db_path)
        store.initialize_store(db_path)
        conn = store._connect_readonly(db_path)
        try:
            assert store._table_exists(conn, "evidence_records")
        finally:
            conn.close()

    def test_creates_6_indexes(self, initialized_db):
        conn = store._connect_readonly(initialized_db)
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            ).fetchall()
            index_names = {r["name"] for r in rows}
            expected = {
                "idx_evidence_subject",
                "idx_evidence_classification",
                "idx_thesis_subject",
                "idx_thesis_status",
                "idx_revisions_thesis",
                "idx_links_evidence",
            }
            assert expected.issubset(index_names)
            # 不应有 idx_links_thesis（主键已覆盖）
            assert "idx_links_thesis" not in index_names
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# PRAGMA
# ---------------------------------------------------------------------------

class TestPragmas:
    def test_writable_connection_has_foreign_keys(self, initialized_db):
        conn = store._connect(initialized_db)
        try:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        finally:
            conn.close()

    def test_readonly_connection_has_foreign_keys(self, initialized_db):
        conn = store._connect_readonly(initialized_db)
        try:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        finally:
            conn.close()

    def test_journal_mode_is_wal(self, initialized_db):
        conn = store._connect_readonly(initialized_db)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

class TestEvidenceCRUD:
    def test_insert_and_get_evidence(self, initialized_db):
        data = {
            "id": store.new_id(),
            "subject_type": "stock",
            "subject_id": "600519",
            "evidence_type": "announcement",
            "claim": "Q3 营收增长 20%",
            "source_title": "贵州茅台三季报",
            "source_url": "https://example.com",
            "source_date": "2025-10-28",
            "accessed_at": "2025-10-28T10:00:00+00:00",
            "classification": "fact",
            "confidence": "high",
            "created_at": "2025-10-28T10:00:00+00:00",
            "updated_at": "2025-10-28T10:00:00+00:00",
        }

        def _do(conn):
            store._insert_evidence(conn, data)
            row = store._get_evidence_row(conn, data["id"])
            return store._evidence_row_to_dict(row)

        result = store.write_transaction(initialized_db, _do)
        assert result["id"] == data["id"]
        assert result["claim"] == "Q3 营收增长 20%"
        assert result["deleted"] == 0
        assert result["deleted_at"] is None

    def test_soft_delete_sets_deleted_and_deleted_at(self, initialized_db):
        data = {
            "id": store.new_id(),
            "subject_type": "stock", "subject_id": "600519",
            "evidence_type": "news", "claim": "test",
            "source_title": "src", "source_url": None, "source_date": None,
            "accessed_at": "2025-01-01T00:00:00+00:00",
            "classification": "fact", "confidence": "high",
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
        }

        def _do(conn):
            store._insert_evidence(conn, data)
            store._soft_delete_evidence(conn, data["id"], "2025-01-02T00:00:00+00:00")
            row = store._get_evidence_row(conn, data["id"])
            return store._evidence_row_to_dict(row)

        result = store.write_transaction(initialized_db, _do)
        assert result["deleted"] == 1
        assert result["deleted_at"] == "2025-01-02T00:00:00+00:00"

    def test_list_evidence_excludes_deleted(self, initialized_db):
        for i in range(3):
            data = {
                "id": store.new_id(),
                "subject_type": "stock", "subject_id": "600519",
                "evidence_type": "news", "claim": f"claim-{i}",
                "source_title": "src", "source_url": None, "source_date": None,
                "accessed_at": "2025-01-01T00:00:00+00:00",
                "classification": "fact", "confidence": "high",
                "created_at": f"2025-01-0{i+1}T00:00:00+00:00",
                "updated_at": f"2025-01-0{i+1}T00:00:00+00:00",
            }
            store.write_transaction(initialized_db, lambda conn, d=data: store._insert_evidence(conn, d))

        # 软删除第一条
        first_id = store.read_transaction(initialized_db, lambda conn: store._list_evidence_rows(conn)[0]["id"])
        store.write_transaction(initialized_db, lambda conn: store._soft_delete_evidence(conn, first_id, "2025-01-02T00:00:00+00:00"))

        rows = store.read_transaction(initialized_db, lambda conn: store._list_evidence_rows(conn))
        assert len(rows) == 2  # 3 - 1 deleted


class TestThesisCRUD:
    def test_insert_and_get_thesis(self, initialized_db):
        data = {
            "id": store.new_id(),
            "subject_type": "stock", "subject_id": "600519", "market": "CN",
            "title": "茅台投资逻辑", "summary": "高端白酒龙头",
            "status": "active",
            "core_claims": ["品牌壁垒强"], "catalysts": ["提价"],
            "risks": ["政策"], "invalidation_conditions": ["增速低于 10%"],
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
            "current_revision": 1,
        }

        def _do(conn):
            store._insert_thesis(conn, data)
            row = store._get_thesis_row(conn, data["id"])
            return store._thesis_row_to_dict(row)

        result = store.write_transaction(initialized_db, _do)
        assert result["title"] == "茅台投资逻辑"
        assert result["current_revision"] == 1
        assert result["core_claims"] == ["品牌壁垒强"]


class TestRevisionCRUD:
    def test_insert_and_get_revision(self, initialized_db):
        thesis_id = store.new_id()
        thesis_data = {
            "id": thesis_id, "subject_type": "stock", "subject_id": "600519",
            "market": "CN", "title": "test", "summary": "test",
            "status": "active", "core_claims": [], "catalysts": [],
            "risks": [], "invalidation_conditions": [],
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
            "current_revision": 1,
        }
        rev_data = {
            "id": store.new_id(), "thesis_id": thesis_id,
            "revision_number": 1, "snapshot": {"thesis": thesis_data, "evidence_links": []},
            "change_summary": "创建", "created_at": "2025-01-01T00:00:00+00:00",
        }

        def _do(conn):
            store._insert_thesis(conn, thesis_data)
            store._insert_revision(conn, rev_data)
            row = store._get_revision_row(conn, thesis_id, 1)
            return store._revision_row_to_dict(row)

        result = store.write_transaction(initialized_db, _do)
        assert result["revision_number"] == 1
        assert result["snapshot"]["thesis"]["title"] == "test"


class TestLinkCRUD:
    def test_insert_and_get_link(self, initialized_db):
        thesis_id = store.new_id()
        evidence_id = store.new_id()
        now = "2025-01-01T00:00:00+00:00"

        thesis_data = {
            "id": thesis_id, "subject_type": "stock", "subject_id": "600519",
            "market": "CN", "title": "t", "summary": "s", "status": "active",
            "core_claims": [], "catalysts": [], "risks": [], "invalidation_conditions": [],
            "created_at": now, "updated_at": now, "current_revision": 1,
        }
        evidence_data = {
            "id": evidence_id, "subject_type": "stock", "subject_id": "600519",
            "evidence_type": "news", "claim": "c", "source_title": "s",
            "source_url": None, "source_date": None,
            "accessed_at": now, "classification": "fact", "confidence": "high",
            "created_at": now, "updated_at": now,
        }
        link_data = {
            "thesis_id": thesis_id, "evidence_id": evidence_id,
            "stance": "support", "created_at": now, "updated_at": now,
        }

        def _do(conn):
            store._insert_thesis(conn, thesis_data)
            store._insert_evidence(conn, evidence_data)
            store._insert_link(conn, link_data)
            row = store._get_link_row(conn, thesis_id, evidence_id)
            return store._link_row_to_dict(row)

        result = store.write_transaction(initialized_db, _do)
        assert result["stance"] == "support"


# ---------------------------------------------------------------------------
# 约束
# ---------------------------------------------------------------------------

class TestConstraints:
    def test_foreign_key_thesis_revision(self, initialized_db):
        """thesis_revisions.thesis_id 必须引用已存在的 investment_theses.id。"""
        def _do(conn):
            store._insert_revision(conn, {
                "id": store.new_id(), "thesis_id": "nonexistent",
                "revision_number": 1, "snapshot": {},
                "change_summary": "x", "created_at": "2025-01-01T00:00:00+00:00",
            })

        with pytest.raises(store.EvidenceLedgerCorruptedError):
            store.write_transaction(initialized_db, _do)

    def test_check_constraint_stance(self, initialized_db):
        """stance 必须是 support/oppose/neutral。"""
        thesis_id = store.new_id()
        evidence_id = store.new_id()
        now = "2025-01-01T00:00:00+00:00"
        thesis_data = {
            "id": thesis_id, "subject_type": "stock", "subject_id": "600519",
            "market": "CN", "title": "t", "summary": "s", "status": "active",
            "core_claims": [], "catalysts": [], "risks": [], "invalidation_conditions": [],
            "created_at": now, "updated_at": now, "current_revision": 1,
        }
        evidence_data = {
            "id": evidence_id, "subject_type": "stock", "subject_id": "600519",
            "evidence_type": "news", "claim": "c", "source_title": "s",
            "source_url": None, "source_date": None,
            "accessed_at": now, "classification": "fact", "confidence": "high",
            "created_at": now, "updated_at": now,
        }

        def _do(conn):
            store._insert_thesis(conn, thesis_data)
            store._insert_evidence(conn, evidence_data)
            # 直接 SQL 插入非法 stance
            conn.execute(
                "INSERT INTO thesis_evidence_links (thesis_id, evidence_id, stance, created_at, updated_at) "
                "VALUES (?, ?, 'invalid', ?, ?)",
                (thesis_id, evidence_id, now, now),
            )

        with pytest.raises(store.EvidenceLedgerCorruptedError):
            store.write_transaction(initialized_db, _do)

    def test_unique_thesis_revision(self, initialized_db):
        """(thesis_id, revision_number) 唯一约束。"""
        thesis_id = store.new_id()
        now = "2025-01-01T00:00:00+00:00"
        thesis_data = {
            "id": thesis_id, "subject_type": "stock", "subject_id": "600519",
            "market": "CN", "title": "t", "summary": "s", "status": "active",
            "core_claims": [], "catalysts": [], "risks": [], "invalidation_conditions": [],
            "created_at": now, "updated_at": now, "current_revision": 1,
        }

        def _do(conn):
            store._insert_thesis(conn, thesis_data)
            store._insert_revision(conn, {
                "id": store.new_id(), "thesis_id": thesis_id,
                "revision_number": 1, "snapshot": {},
                "change_summary": "first", "created_at": now,
            })
            store._insert_revision(conn, {
                "id": store.new_id(), "thesis_id": thesis_id,
                "revision_number": 1, "snapshot": {},
                "change_summary": "dup", "created_at": now,
            })

        with pytest.raises(store.EvidenceLedgerCorruptedError):
            store.write_transaction(initialized_db, _do)


# ---------------------------------------------------------------------------
# Schema 版本
# ---------------------------------------------------------------------------

class TestSchemaVersion:
    def test_higher_schema_version_rejected(self, db_path):
        """版本高于代码版本拒绝打开。"""
        store.initialize_store(db_path)
        # 手动修改版本为更高版本
        conn = store._connect(db_path)
        try:
            conn.execute("UPDATE schema_meta SET value = 'evidence_thesis_ledger_v999' WHERE key = 'schema_version'")
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(store.EvidenceLedgerCorruptedError):
            store.check_schema_version(db_path)

    def test_matching_schema_version_ok(self, initialized_db):
        store.check_schema_version(initialized_db)


# ---------------------------------------------------------------------------
# 损坏检测
# ---------------------------------------------------------------------------

class TestCorruption:
    def test_integrity_check_passes_on_clean_db(self, initialized_db):
        store.integrity_check(initialized_db)

    def test_corrupted_db_raises(self, db_path):
        """写入非 SQLite 内容到数据库文件，integrity_check 应抛异常。"""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        Path(db_path).write_bytes(b"not a sqlite database")
        with pytest.raises(store.EvidenceLedgerCorruptedError):
            store.integrity_check(db_path)

    def test_read_transaction_on_missing_file_raises_filenotfound(self, tmp_path):
        missing = tmp_path / "missing.db"
        with pytest.raises(FileNotFoundError):
            store.read_transaction(missing, lambda conn: None)


# ---------------------------------------------------------------------------
# 事务回滚
# ---------------------------------------------------------------------------

class TestTransactionRollback:
    def test_write_transaction_rolls_back_on_exception(self, initialized_db):
        evidence_id = store.new_id()
        now = "2025-01-01T00:00:00+00:00"
        data = {
            "id": evidence_id, "subject_type": "stock", "subject_id": "600519",
            "evidence_type": "news", "claim": "before",
            "source_title": "s", "source_url": None, "source_date": None,
            "accessed_at": now, "classification": "fact", "confidence": "high",
            "created_at": now, "updated_at": now,
        }

        # 先正常插入
        store.write_transaction(initialized_db, lambda conn: store._insert_evidence(conn, data))

        # 尝试在事务内修改后抛异常
        def _do_fail(conn):
            store._update_evidence(conn, evidence_id, {**data, "claim": "after", "updated_at": now})
            raise RuntimeError("simulated failure")

        with pytest.raises(RuntimeError):
            store.write_transaction(initialized_db, _do_fail)

        # 验证旧数据不变
        result = store.read_transaction(initialized_db, lambda conn: store._evidence_row_to_dict(store._get_evidence_row(conn, evidence_id)))
        assert result["claim"] == "before"


# ---------------------------------------------------------------------------
# 备份
# ---------------------------------------------------------------------------

class TestBackup:
    def test_backup_creates_bak_file(self, initialized_db):
        # 写入一些数据
        now = "2025-01-01T00:00:00+00:00"
        data = {
            "id": store.new_id(), "subject_type": "stock", "subject_id": "600519",
            "evidence_type": "news", "claim": "test",
            "source_title": "s", "source_url": None, "source_date": None,
            "accessed_at": now, "classification": "fact", "confidence": "high",
            "created_at": now, "updated_at": now,
        }
        store.write_transaction(initialized_db, lambda conn: store._insert_evidence(conn, data))

        bak_path = Path(str(initialized_db) + ".bak")
        assert bak_path.exists()

        # 验证备份是有效 SQLite
        conn = sqlite3.connect(str(bak_path))
        try:
            row = conn.execute("SELECT COUNT(*) FROM evidence_records").fetchone()
            assert row[0] == 1
        finally:
            conn.close()

    def test_backup_failure_doesnt_rollback_business(self, initialized_db, monkeypatch):
        """备份失败不回滚已提交业务写入。"""
        now = "2025-01-01T00:00:00+00:00"
        data = {
            "id": store.new_id(), "subject_type": "stock", "subject_id": "600519",
            "evidence_type": "news", "claim": "test",
            "source_title": "s", "source_url": None, "source_date": None,
            "accessed_at": now, "classification": "fact", "confidence": "high",
            "created_at": now, "updated_at": now,
        }

        # 让 backup_database 抛异常
        original_backup = store.backup_database
        call_count = [0]
        def failing_backup(path):
            call_count[0] += 1
            raise OSError("backup failed")

        monkeypatch.setattr(store, "backup_database", failing_backup)

        # 写入应成功（备份失败不影响业务）
        result = store.write_transaction(initialized_db, lambda conn: store._insert_evidence(conn, data))
        assert call_count[0] == 1  # 备份被调用了

        # 验证数据确实写入了
        row = store.read_transaction(initialized_db, lambda conn: store._get_evidence_row(conn, data["id"]))
        assert row is not None

        monkeypatch.setattr(store, "backup_database", original_backup)


# ---------------------------------------------------------------------------
# 临时数据库隔离
# ---------------------------------------------------------------------------

class TestIsolation:
    def test_each_test_uses_isolated_db(self, tmp_path):
        db1 = tmp_path / "test1.db"
        db2 = tmp_path / "test2.db"
        store.initialize_store(db1)
        store.initialize_store(db2)

        # 写入 db1
        now = "2025-01-01T00:00:00+00:00"
        data = {
            "id": store.new_id(), "subject_type": "stock", "subject_id": "600519",
            "evidence_type": "news", "claim": "in db1",
            "source_title": "s", "source_url": None, "source_date": None,
            "accessed_at": now, "classification": "fact", "confidence": "high",
            "created_at": now, "updated_at": now,
        }
        store.write_transaction(db1, lambda conn: store._insert_evidence(conn, data))

        # db2 应为空
        rows = store.read_transaction(db2, lambda conn: store._list_evidence_rows(conn))
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# 并发写锁
# ---------------------------------------------------------------------------

class TestConcurrency:
    def test_lock_protects_concurrent_writes(self, initialized_db):
        """多线程同时写入不产生 database is locked 错误。"""
        results = []
        errors = []

        def writer(thread_id):
            try:
                now = "2025-01-01T00:00:00+00:00"
                data = {
                    "id": store.new_id(), "subject_type": "stock", "subject_id": "600519",
                    "evidence_type": "news", "claim": f"thread-{thread_id}",
                    "source_title": "s", "source_url": None, "source_date": None,
                    "accessed_at": now, "classification": "fact", "confidence": "high",
                    "created_at": now, "updated_at": now,
                }
                store.write_transaction(initialized_db, lambda conn: store._insert_evidence(conn, data))
                results.append(thread_id)
            except Exception as e:
                errors.append((thread_id, str(e)))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发写入出错: {errors}"
        assert len(results) == 5
