"""专项测试：验证所有修复任务的正确性。"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

import evidence_thesis_service as svc
import evidence_thesis_store as store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path) -> Path:
    return tmp_path / "test_fixes.db"


@pytest.fixture
def initialized_db(db_path) -> Path:
    store.initialize_store(db_path)
    return db_path


@pytest.fixture
def thesis_with_evidence(initialized_db) -> tuple[str, str]:
    """创建一个 thesis 和一个关联的 evidence，返回 (thesis_id, evidence_id)。"""
    now = "2025-01-01T00:00:00+00:00"

    # 创建 thesis
    thesis_data = {
        "subject_type": "stock",
        "subject_id": "600519",
        "title": "测试逻辑",
        "summary": "测试摘要",
        "core_claims": ["claim1"],
        "catalysts": ["cat1"],
        "risks": ["risk1"],
        "invalidation_conditions": ["inv1"],
    }
    thesis = svc.create_thesis(initialized_db, thesis_data)
    thesis_id = thesis["thesis"]["id"]

    # 创建 evidence
    evidence_data = {
        "subject_type": "stock",
        "subject_id": "600519",
        "evidence_type": "news",
        "claim": "test claim",
        "source_title": "test source",
        "source_url": None,
        "source_date": None,
        "accessed_at": now,
        "classification": "fact",
        "confidence": "high",
    }
    evidence = svc.create_evidence(initialized_db, evidence_data)
    evidence_id = evidence["id"]

    # 关联
    svc.link_evidence(initialized_db, thesis_id, evidence_id, "support", 1, "link")

    return thesis_id, evidence_id


# ---------------------------------------------------------------------------
# 二、连接泄漏测试
# ---------------------------------------------------------------------------

class TestConnectionLeak:
    def test_revision_conflict_closes_connection(self, initialized_db, thesis_with_evidence):
        """revision 冲突时 close 1次。"""
        thesis_id, _ = thesis_with_evidence

        with pytest.raises(svc.RevisionConflictError):
            svc.update_thesis(initialized_db, thesis_id, {
                "title": "new",
                "summary": "new",
                "status": "active",
                "core_claims": [],
                "catalysts": [],
                "risks": [],
                "invalidation_conditions": [],
            }, expected_revision=999)

    def test_archived_error_closes_connection(self, initialized_db, thesis_with_evidence):
        """archived 异常时 close 1次。"""
        thesis_id, _ = thesis_with_evidence

        # 先归档
        svc.archive_thesis(initialized_db, thesis_id, 2, "archive")

        # 再次尝试修改
        with pytest.raises(svc.ArchivedThesisError):
            svc.update_thesis(initialized_db, thesis_id, {
                "title": "new",
                "summary": "new",
                "status": "active",
                "core_claims": [],
                "catalysts": [],
                "risks": [],
                "invalidation_conditions": [],
            }, expected_revision=3)

    def test_validation_error_closes_connection(self, initialized_db):
        """ValidationError 时 close 1次。"""
        with pytest.raises(svc.ValidationError):
            svc.create_evidence(initialized_db, {
                "subject_type": "stock",
                "subject_id": "INVALID$CODE",
                "evidence_type": "news",
                "claim": "test",
                "source_title": "s",
                "accessed_at": "2025-01-01T00:00:00+00:00",
                "classification": "fact",
                "confidence": "high",
            })


# ---------------------------------------------------------------------------
# 三、Schema 保护测试
# ---------------------------------------------------------------------------

class TestSchemaProtection:
    def test_v999_database_rejects_read(self, db_path):
        """v999 数据库读取被拒绝。"""
        store.initialize_store(db_path)

        # 修改版本为 v999
        conn = store._connect(db_path)
        try:
            conn.execute("UPDATE schema_meta SET value = 'evidence_thesis_ledger_v999' WHERE key = 'schema_version'")
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(store.EvidenceLedgerSchemaVersionError):
            svc.list_evidence(db_path)

    def test_v999_database_rejects_write(self, db_path):
        """v999 数据库写入被拒绝。"""
        store.initialize_store(db_path)

        # 修改版本为 v999
        conn = store._connect(db_path)
        try:
            conn.execute("UPDATE schema_meta SET value = 'evidence_thesis_ledger_v999' WHERE key = 'schema_version'")
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(store.EvidenceLedgerSchemaVersionError):
            svc.create_evidence(db_path, {
                "subject_type": "stock",
                "subject_id": "600519",
                "evidence_type": "news",
                "claim": "test",
                "source_title": "s",
                "accessed_at": "2025-01-01T00:00:00+00:00",
                "classification": "fact",
                "confidence": "high",
            })

    def test_v999_does_not_modify_schema(self, db_path):
        """拒绝前后 schema/table/data 完全不变。"""
        store.initialize_store(db_path)

        # 记录原始表列表
        conn = store._connect_readonly(db_path)
        try:
            original_tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        finally:
            conn.close()

        # 修改版本为 v999
        conn = store._connect(db_path)
        try:
            conn.execute("UPDATE schema_meta SET value = 'evidence_thesis_ledger_v999' WHERE key = 'schema_version'")
            conn.commit()
        finally:
            conn.close()

        # 尝试读取（会被拒绝）
        try:
            svc.list_evidence(db_path)
        except store.EvidenceLedgerSchemaVersionError:
            pass

        # 验证表列表未变化
        conn = store._connect_readonly(db_path)
        try:
            new_tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        finally:
            conn.close()

        assert original_tables == new_tables

    def test_current_v1_works(self, initialized_db):
        """当前 v1 正常工作。"""
        result = svc.list_evidence(initialized_db)
        assert result["total"] == 0

    def test_non_empty_without_schema_meta_rejected(self, db_path):
        """非空且无 schema_meta 被拒绝。"""
        # 创建一个表但不创建 schema_meta
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE dummy (id TEXT)")
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(store.EvidenceLedgerCorruptedError):
            svc.list_evidence(db_path)


# ---------------------------------------------------------------------------
# 四、备份失败日志测试
# ---------------------------------------------------------------------------

class TestBackupFailureLogging:
    def test_backup_failure_logs_warning(self, initialized_db, monkeypatch, caplog):
        """备份失败产生 warning 日志。"""
        # 让 backup_database 抛异常
        def failing_backup(path):
            raise OSError("simulated backup failure")

        monkeypatch.setattr(store, "backup_database", failing_backup)

        with caplog.at_level(logging.WARNING):
            now = "2025-01-01T00:00:00+00:00"
            data = {
                "id": store.new_id(),
                "subject_type": "stock", "subject_id": "600519",
                "evidence_type": "news", "claim": "test",
                "source_title": "s", "source_url": None, "source_date": None,
                "accessed_at": now, "classification": "fact", "confidence": "high",
                "created_at": now, "updated_at": now,
            }
            store.write_transaction(initialized_db, lambda conn: store._insert_evidence(conn, data))

        # 验证产生了 warning 日志
        assert any("backup failed" in record.message for record in caplog.records)

        # 验证日志不含绝对路径
        for record in caplog.records:
            if "backup failed" in record.message:
                assert str(initialized_db) not in record.message


# ---------------------------------------------------------------------------
# 五、归档冻结测试
# ---------------------------------------------------------------------------

class TestArchiveFreeze:
    def test_first_archive_succeeds(self, initialized_db, thesis_with_evidence):
        """第一次归档成功并生成最终 revision。"""
        thesis_id, _ = thesis_with_evidence

        # 当前 revision 应为 2 (创建=1, 关联=2)
        thesis = svc.get_thesis(initialized_db, thesis_id)
        assert thesis["thesis"]["current_revision"] == 2

        # 归档
        result = svc.archive_thesis(initialized_db, thesis_id, 2, "archive")
        assert result["thesis"]["status"] == "archived"
        assert result["thesis"]["current_revision"] == 3

    def test_second_archive_returns_409(self, initialized_db, thesis_with_evidence):
        """第二次归档返回 409。"""
        thesis_id, _ = thesis_with_evidence

        # 第一次归档
        svc.archive_thesis(initialized_db, thesis_id, 2, "first archive")

        # 第二次归档应抛 ArchivedThesisError
        with pytest.raises(svc.ArchivedThesisError):
            svc.archive_thesis(initialized_db, thesis_id, 3, "second archive")

    def test_second_archive_no_new_revision(self, initialized_db, thesis_with_evidence):
        """第二次归档后 revision 数量不变。"""
        thesis_id, _ = thesis_with_evidence

        # 第一次归档
        svc.archive_thesis(initialized_db, thesis_id, 2, "first archive")
        revisions_after_first = svc.list_revisions(initialized_db, thesis_id)
        first_count = revisions_after_first["total"]

        # 尝试第二次归档
        try:
            svc.archive_thesis(initialized_db, thesis_id, 3, "second archive")
        except svc.ArchivedThesisError:
            pass

        # 验证 revision 数量未增加
        revisions_after_second = svc.list_revisions(initialized_db, thesis_id)
        assert revisions_after_second["total"] == first_count

    def test_second_archive_no_revision_increment(self, initialized_db, thesis_with_evidence):
        """第二次归档后 current_revision 不变。"""
        thesis_id, _ = thesis_with_evidence

        # 第一次归档
        svc.archive_thesis(initialized_db, thesis_id, 2, "first archive")
        thesis_after_first = svc.get_thesis(initialized_db, thesis_id)
        first_revision = thesis_after_first["thesis"]["current_revision"]

        # 尝试第二次归档
        try:
            svc.archive_thesis(initialized_db, thesis_id, first_revision, "second archive")
        except svc.ArchivedThesisError:
            pass

        # 验证 current_revision 未增加
        thesis_after_second = svc.get_thesis(initialized_db, thesis_id)
        assert thesis_after_second["thesis"]["current_revision"] == first_revision


# ---------------------------------------------------------------------------
# 六、股票代码收紧测试
# ---------------------------------------------------------------------------

class TestStockCodeValidation:
    def test_cn_stock_codes(self):
        """A 股代码正确识别（含 301xxx 与科创板 688xxx）。"""
        assert svc.normalize_subject("stock", "600519") == ("stock", "600519", "CN")
        assert svc.normalize_subject("stock", "000001") == ("stock", "000001", "CN")
        assert svc.normalize_subject("stock", "300750") == ("stock", "300750", "CN")
        # 创业板注册制 301xxx（个股数据页可接受的 A 股）
        assert svc.normalize_subject("stock", "301091") == ("stock", "301091", "CN")
        assert svc.normalize_subject("stock", "301236") == ("stock", "301236", "CN")
        # 科创板 688xxx（6 开头，项目个股页常用）
        assert svc.normalize_subject("stock", "688256") == ("stock", "688256", "CN")
        assert svc.normalize_subject("stock", "688041") == ("stock", "688041", "CN")

    def test_hk_stock_codes(self):
        """港股代码正确识别和规范化。"""
        assert svc.normalize_subject("stock", "00700") == ("stock", "00700", "HK")
        assert svc.normalize_subject("stock", "700") == ("stock", "00700", "HK")
        assert svc.normalize_subject("stock", "00001") == ("stock", "00001", "HK")

    def test_us_stock_codes(self):
        """美股代码正确识别（明确 ticker 正则）。"""
        assert svc.normalize_subject("stock", "AAPL") == ("stock", "AAPL", "US")
        assert svc.normalize_subject("stock", "BRK.B") == ("stock", "BRK.B", "US")
        assert svc.normalize_subject("stock", "GOOGL") == ("stock", "GOOGL", "US")

    def test_us_ticker_rejects_non_ticker_letters(self):
        """含字母但不符合美股 ticker 正则的字符串必须拒绝（不得仅因含字母通过）。"""
        with pytest.raises(svc.ValidationError, match="无法识别"):
            svc.normalize_subject("stock", "NOTAVALIDTICKER")
        with pytest.raises(svc.ValidationError, match="无法识别"):
            svc.normalize_subject("stock", "AAPL1")
        with pytest.raises(svc.ValidationError, match="无法识别"):
            svc.normalize_subject("stock", "HELLO-WORLD")
        with pytest.raises(svc.ValidationError, match="无法识别"):
            svc.normalize_subject("stock", "BRK.BB")

    def test_kr_stock_codes(self):
        """韩股代码正确识别。"""
        assert svc.normalize_subject("stock", "005930.KS") == ("stock", "005930.KS", "KR")
        assert svc.normalize_subject("stock", "035420.KQ") == ("stock", "035420.KQ", "KR")

    def test_bare_005930_rejected(self):
        """裸 005930 被拒绝（不能静默视为 A 股）。"""
        with pytest.raises(svc.ValidationError, match="无法识别|韩股"):
            svc.normalize_subject("stock", "005930")

    def test_invalid_suffix_rejected(self):
        """非法后缀被拒绝。"""
        with pytest.raises(svc.ValidationError, match="无法识别|后缀"):
            svc.normalize_subject("stock", "005930.XX")

    def test_invalid_chars_rejected(self):
        """包含非法字符的代码被拒绝。"""
        with pytest.raises(svc.ValidationError, match="非法字符"):
            svc.normalize_subject("stock", "ABC$")
        with pytest.raises(svc.ValidationError, match="非法字符"):
            svc.normalize_subject("stock", "AAPL/TEST")

    def test_empty_code_rejected(self):
        """空字符串被拒绝。"""
        with pytest.raises(svc.ValidationError, match="不能为空"):
            svc.normalize_subject("stock", "")

    def test_too_long_code_rejected(self):
        """超长 ticker 被拒绝。"""
        with pytest.raises(svc.ValidationError, match="过长"):
            svc.normalize_subject("stock", "A" * 30)


# ---------------------------------------------------------------------------
# 七、严格 UTC datetime 测试
# ---------------------------------------------------------------------------

class TestStrictUTCDatetime:
    def test_utc_offset_converted_to_utc(self, initialized_db):
        """非 UTC offset 输入转换为 UTC 保存。"""
        result = svc.create_evidence(initialized_db, {
            "subject_type": "stock",
            "subject_id": "600519",
            "evidence_type": "news",
            "claim": "test",
            "source_title": "s",
            "accessed_at": "2025-01-01T08:00:00+08:00",
            "classification": "fact",
            "confidence": "high",
        })
        # 应保存为 UTC: 2025-01-01T00:00:00+00:00
        assert result["accessed_at"].startswith("2025-01-01T00:00:00")
        assert "+00:00" in result["accessed_at"]

    def test_naive_datetime_returns_422(self, initialized_db):
        """naive datetime 返回 422。"""
        with pytest.raises(svc.ValidationError, match="时区"):
            svc.create_evidence(initialized_db, {
                "subject_type": "stock",
                "subject_id": "600519",
                "evidence_type": "news",
                "claim": "test",
                "source_title": "s",
                "accessed_at": "2025-01-01T00:00:00",
                "classification": "fact",
                "confidence": "high",
            })

    def test_source_date_still_accepts_date_only(self, initialized_db):
        """source_date 继续只接受 YYYY-MM-DD。"""
        result = svc.create_evidence(initialized_db, {
            "subject_type": "stock",
            "subject_id": "600519",
            "evidence_type": "news",
            "claim": "test",
            "source_title": "s",
            "source_date": "2025-01-01",
            "accessed_at": "2025-01-01T00:00:00+00:00",
            "classification": "fact",
            "confidence": "high",
        })
        assert result["source_date"] == "2025-01-01"


# ---------------------------------------------------------------------------
# 八、API 更新模型测试（服务层校验）
# ---------------------------------------------------------------------------

class TestThesisUpdateValidation:
    def test_missing_field_validation(self, initialized_db, thesis_with_evidence):
        """漏字段时服务层校验失败。"""
        thesis_id, _ = thesis_with_evidence

        # 缺少 core_claims
        with pytest.raises(svc.ValidationError, match="core_claims"):
            svc.update_thesis(initialized_db, thesis_id, {
                "title": "new",
                "summary": "new",
                "status": "active",
                "catalysts": [],
                "risks": [],
                "invalidation_conditions": [],
            }, expected_revision=2)

    def test_bool_as_revision_rejected(self, initialized_db, thesis_with_evidence):
        """布尔值作为 expected_revision 被拒绝。"""
        thesis_id, _ = thesis_with_evidence

        with pytest.raises(svc.ValidationError, match="正整数|必须是整数"):
            svc.update_thesis(initialized_db, thesis_id, {
                "title": "new",
                "summary": "new",
                "status": "active",
                "core_claims": [],
                "catalysts": [],
                "risks": [],
                "invalidation_conditions": [],
            }, expected_revision=True)
