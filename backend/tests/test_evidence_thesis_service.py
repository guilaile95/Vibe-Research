"""服务层专项测试：revision 生成、乐观并发、archived 冻结、Evidence 联动、subject 一致性、diff。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import evidence_thesis_service as svc
import evidence_thesis_store as store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path) -> Path:
    return tmp_path / "test_svc.db"


@pytest.fixture
def db(db_path) -> Path:
    store.initialize_store(db_path)
    return db_path


def _now() -> str:
    return "2025-01-01T00:00:00+00:00"


def _make_evidence_payload(subject_type: str = "stock", subject_id: str = "600519",
                           evidence_type: str = "news", claim: str = "claim",
                           classification: str = "fact", confidence: str = "high") -> dict:
    return {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "evidence_type": evidence_type,
        "claim": claim,
        "source_title": "src",
        "source_url": "https://example.com",
        "source_date": "2025-01-01",
        "accessed_at": _now(),
        "classification": classification,
        "confidence": confidence,
    }


def _make_thesis_payload(subject_type: str = "stock", subject_id: str = "600519",
                         title: str = "thesis", summary: str = "summary") -> dict:
    return {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "title": title,
        "summary": summary,
        "core_claims": ["c1"],
        "catalysts": ["cat1"],
        "risks": ["r1"],
        "invalidation_conditions": ["ic1"],
        "change_summary": "创建",
    }


# ---------------------------------------------------------------------------
# 标识规范化
# ---------------------------------------------------------------------------

class TestNormalization:
    def test_a_share_normalizes_to_cn(self):
        stype, sid, market = svc.normalize_subject("stock", "600519")
        assert (stype, sid, market) == ("stock", "600519", "CN")

    def test_hk_stock_zero_pads_to_5(self):
        stype, sid, market = svc.normalize_subject("stock", "700")
        assert (stype, sid, market) == ("stock", "00700", "HK")

    def test_hk_stock_5_digit(self):
        stype, sid, market = svc.normalize_subject("stock", "00700")
        assert market == "HK"

    def test_us_stock_uppercase(self):
        stype, sid, market = svc.normalize_subject("stock", "aapl")
        assert (stype, sid, market) == ("stock", "AAPL", "US")

    def test_kr_stock_keeps_suffix(self):
        stype, sid, market = svc.normalize_subject("stock", "005930.KS")
        assert (stype, sid, market) == ("stock", "005930.KS", "KR")

    def test_kr_stock_lowercase_suffix_uppercased(self):
        stype, sid, market = svc.normalize_subject("stock", "005930.ks")
        assert (stype, sid, market) == ("stock", "005930.KS", "KR")

    def test_kr_stock_kq_suffix(self):
        stype, sid, market = svc.normalize_subject("stock", "035420.KQ")
        assert market == "KR"

    def test_invalid_subject_type(self):
        with pytest.raises(svc.ValidationError):
            svc.normalize_subject("industry", "x")

    def test_invalid_theme_slug(self):
        with pytest.raises(svc.ValidationError):
            svc.normalize_subject("theme", "Invalid Slug!")

    def test_theme_slug_max_length(self):
        with pytest.raises(svc.ValidationError):
            svc.normalize_subject("theme", "a" * 65)

    def test_sector_lowercase(self):
        stype, sid, market = svc.normalize_subject("sector", "Semi-Conductor")
        assert (stype, sid, market) == ("sector", "semi-conductor", None)


# ---------------------------------------------------------------------------
# revision 1
# ---------------------------------------------------------------------------

class TestRevisionOne:
    def test_create_thesis_generates_revision_1(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        assert thesis["thesis"]["current_revision"] == 1

        revs = svc.list_revisions(db, thesis["thesis"]["id"])
        assert revs["total"] == 1
        assert revs["items"][0]["revision_number"] == 1

    def test_revision_1_snapshot_contains_thesis_fields(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload(title="t1", summary="s1"))
        rev = svc.get_revision(db, thesis["thesis"]["id"], 1)
        assert rev is not None
        snap = rev["snapshot"]
        assert snap["thesis"]["title"] == "t1"
        assert snap["thesis"]["summary"] == "s1"
        assert snap["thesis"]["status"] == "active"
        assert snap["evidence_links"] == []

    def test_no_thesis_without_revision_1(self, db):
        """thesis 创建和 revision 1 在同一事务内完成。"""
        # 通过服务层正常创建
        thesis = svc.create_thesis(db, _make_thesis_payload())
        # 验证 revision 1 已存在
        rev = svc.get_revision(db, thesis["thesis"]["id"], 1)
        assert rev is not None


# ---------------------------------------------------------------------------
# thesis 编辑 revision
# ---------------------------------------------------------------------------

class TestThesisEditRevision:
    def test_edit_generates_new_revision(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        tid = thesis["thesis"]["id"]
        updated = svc.update_thesis(db, tid, {
            "title": "t2", "summary": "s2", "status": "active",
            "core_claims": ["c1"], "catalysts": ["cat1"],
            "risks": ["r1"], "invalidation_conditions": ["ic1"],
            "expected_revision": 1, "change_summary": "edit",
        }, expected_revision=1)
        assert updated["thesis"]["current_revision"] == 2
        assert updated["thesis"]["title"] == "t2"

    def test_edit_invalid_expected_revision(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        tid = thesis["thesis"]["id"]
        with pytest.raises(svc.RevisionConflictError) as ei:
            svc.update_thesis(db, tid, {
                "title": "t2", "summary": "s2", "status": "active",
                "core_claims": [], "catalysts": [], "risks": [], "invalidation_conditions": [],
                "expected_revision": 99, "change_summary": "x",
            }, expected_revision=99)
        assert ei.value.current_revision == 1


# ---------------------------------------------------------------------------
# 关联 revision / stance revision / 取消关联 revision
# ---------------------------------------------------------------------------

class TestLinkRevisions:
    def test_link_evidence_generates_revision(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload())
        tid = thesis["thesis"]["id"]
        result = svc.link_evidence(db, tid, ev["id"], "support", 1, "link")
        assert result["thesis"]["current_revision"] == 2
        assert len(result["evidence_links"]) == 1
        assert result["evidence_links"][0]["stance"] == "support"

    def test_update_stance_generates_revision(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload())
        tid = thesis["thesis"]["id"]
        svc.link_evidence(db, tid, ev["id"], "support", 1, "link")
        result = svc.update_stance(db, tid, ev["id"], "oppose", 2, "change stance")
        assert result["thesis"]["current_revision"] == 3
        assert result["evidence_links"][0]["stance"] == "oppose"

    def test_unlink_evidence_generates_revision(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload())
        tid = thesis["thesis"]["id"]
        svc.link_evidence(db, tid, ev["id"], "support", 1, "link")
        result = svc.unlink_evidence(db, tid, ev["id"], 2, "unlink")
        assert result["thesis"]["current_revision"] == 3
        assert len(result["evidence_links"]) == 0

    def test_invalid_stance(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload())
        with pytest.raises(svc.ValidationError):
            svc.link_evidence(db, thesis["thesis"]["id"], ev["id"], "invalid", 1, "x")


# ---------------------------------------------------------------------------
# Evidence 联动 revision
# ---------------------------------------------------------------------------

class TestEvidenceCascade:
    def test_evidence_edit_cascades_to_non_archived_thesis(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload(claim="c1"))
        tid = thesis["thesis"]["id"]
        svc.link_evidence(db, tid, ev["id"], "support", 1, "link")
        # 现在 revision=2

        # 编辑证据 → 应联动生成 revision 3
        updated_ev = svc.update_evidence(db, ev["id"], _make_evidence_payload(claim="c2"))
        assert updated_ev["claim"] == "c2"

        thesis_after = svc.get_thesis(db, tid)
        assert thesis_after["thesis"]["current_revision"] == 3
        # snapshot 中的 claim 也应更新
        assert thesis_after["evidence_links"][0]["claim"] == "c2"

    def test_evidence_delete_cascades_to_non_archived_thesis(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload())
        tid = thesis["thesis"]["id"]
        svc.link_evidence(db, tid, ev["id"], "support", 1, "link")
        # revision=2

        svc.soft_delete_evidence(db, ev["id"])
        thesis_after = svc.get_thesis(db, tid)
        assert thesis_after["thesis"]["current_revision"] == 3
        # 当前聚合状态不含已删除证据
        assert len(thesis_after["evidence_links"]) == 0

    def test_cascade_skips_archived_thesis(self, db):
        """Evidence 编辑不联动 archived thesis。"""
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload())
        tid = thesis["thesis"]["id"]
        svc.link_evidence(db, tid, ev["id"], "support", 1, "link")  # rev=2
        svc.archive_thesis(db, tid, expected_revision=2)  # rev=3

        # 编辑证据：不应联动 archived thesis
        svc.update_evidence(db, ev["id"], _make_evidence_payload(claim="new"))
        thesis_after = svc.get_thesis(db, tid)
        assert thesis_after["thesis"]["current_revision"] == 3  # 未增加
        # archived snapshot 保留旧 claim
        assert thesis_after["evidence_links"][0]["claim"] == "claim"

    def test_cascade_to_multiple_theses(self, db):
        """一个证据关联多个非归档 thesis，编辑时全部联动。"""
        t1 = svc.create_thesis(db, _make_thesis_payload(subject_id="600519", title="t1"))
        t2 = svc.create_thesis(db, _make_thesis_payload(subject_id="600519", title="t2"))
        ev = svc.create_evidence(db, _make_evidence_payload())
        # 两个 thesis 都关联同一证据
        svc.link_evidence(db, t1["thesis"]["id"], ev["id"], "support", 1, "l1")  # t1 rev=2
        svc.link_evidence(db, t2["thesis"]["id"], ev["id"], "oppose", 1, "l2")  # t2 rev=2

        svc.update_evidence(db, ev["id"], _make_evidence_payload(claim="updated"))
        assert svc.get_thesis(db, t1["thesis"]["id"])["thesis"]["current_revision"] == 3
        assert svc.get_thesis(db, t2["thesis"]["id"])["thesis"]["current_revision"] == 3


# ---------------------------------------------------------------------------
# archived 冻结
# ---------------------------------------------------------------------------

class TestArchivedFreeze:
    def test_archive_generates_final_revision(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        tid = thesis["thesis"]["id"]
        result = svc.archive_thesis(db, tid, expected_revision=1, change_summary="archive")
        assert result["thesis"]["status"] == "archived"
        assert result["thesis"]["current_revision"] == 2

    def test_archived_thesis_cannot_edit(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        tid = thesis["thesis"]["id"]
        svc.archive_thesis(db, tid, expected_revision=1)
        with pytest.raises(svc.ArchivedThesisError):
            svc.update_thesis(db, tid, {
                "title": "x", "summary": "x", "status": "active",
                "core_claims": [], "catalysts": [], "risks": [], "invalidation_conditions": [],
                "expected_revision": 2, "change_summary": "x",
            }, expected_revision=2)

    def test_archived_thesis_cannot_link(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload())
        tid = thesis["thesis"]["id"]
        svc.archive_thesis(db, tid, expected_revision=1)
        with pytest.raises(svc.ArchivedThesisError):
            svc.link_evidence(db, tid, ev["id"], "support", 2, "x")

    def test_archived_thesis_cannot_update_stance(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload())
        tid = thesis["thesis"]["id"]
        svc.link_evidence(db, tid, ev["id"], "support", 1, "l")
        svc.archive_thesis(db, tid, expected_revision=2)
        with pytest.raises(svc.ArchivedThesisError):
            svc.update_stance(db, tid, ev["id"], "oppose", 3, "x")

    def test_archived_thesis_cannot_unlink(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload())
        tid = thesis["thesis"]["id"]
        svc.link_evidence(db, tid, ev["id"], "support", 1, "l")
        svc.archive_thesis(db, tid, expected_revision=2)
        with pytest.raises(svc.ArchivedThesisError):
            svc.unlink_evidence(db, tid, ev["id"], 3, "x")

    def test_archived_thesis_get_uses_snapshot(self, db):
        """GET /api/thesis/{id} archived 以冻结 snapshot 为权威。"""
        thesis = svc.create_thesis(db, _make_thesis_payload(title="original"))
        tid = thesis["thesis"]["id"]
        ev = svc.create_evidence(db, _make_evidence_payload())
        svc.link_evidence(db, tid, ev["id"], "support", 1, "l")  # rev=2
        svc.archive_thesis(db, tid, expected_revision=2)  # rev=3

        # GET 应返回 archived snapshot（与 revision 3 的 snapshot 等价）
        get_result = svc.get_thesis(db, tid)
        rev3 = svc.get_revision(db, tid, 3)
        assert get_result == rev3["snapshot"]
        assert get_result["thesis"]["status"] == "archived"
        assert get_result["thesis"]["title"] == "original"
        assert get_result["thesis"]["current_revision"] == 3


# ---------------------------------------------------------------------------
# expected_revision 冲突
# ---------------------------------------------------------------------------

class TestOptimisticConcurrency:
    def test_link_with_stale_revision_conflicts(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload())
        tid = thesis["thesis"]["id"]
        svc.link_evidence(db, tid, ev["id"], "support", 1, "l")  # rev=2

        with pytest.raises(svc.RevisionConflictError) as ei:
            svc.link_evidence(db, tid, ev["id"], "oppose", 1, "x")  # stale rev=1
        assert ei.value.current_revision == 2

    def test_archive_with_stale_revision_conflicts(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload())
        tid = thesis["thesis"]["id"]
        svc.link_evidence(db, tid, ev["id"], "support", 1, "l")  # rev=2

        with pytest.raises(svc.RevisionConflictError):
            svc.archive_thesis(db, tid, expected_revision=1)


# ---------------------------------------------------------------------------
# 跨 subject 关联拒绝
# ---------------------------------------------------------------------------

class TestSubjectMismatch:
    def test_cross_subject_link_rejected(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload(subject_id="600519"))
        ev = svc.create_evidence(db, _make_evidence_payload(subject_id="000001"))
        with pytest.raises(svc.SubjectMismatchError):
            svc.link_evidence(db, thesis["thesis"]["id"], ev["id"], "support", 1, "x")

    def test_cross_type_link_rejected(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload(subject_type="sector", subject_id="semi"))
        ev = svc.create_evidence(db, _make_evidence_payload(subject_type="stock", subject_id="600519"))
        with pytest.raises(svc.SubjectMismatchError):
            svc.link_evidence(db, thesis["thesis"]["id"], ev["id"], "support", 1, "x")


# ---------------------------------------------------------------------------
# 当前聚合状态与 snapshot 等价
# ---------------------------------------------------------------------------

class TestAggregateInvariant:
    def test_current_state_equals_snapshot(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload())
        tid = thesis["thesis"]["id"]
        svc.link_evidence(db, tid, ev["id"], "support", 1, "l")  # rev=2

        current = svc.get_thesis(db, tid)
        rev = svc.get_revision(db, tid, 2)

        assert current == rev["snapshot"]

    def test_invariant_after_multiple_mutations(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev1 = svc.create_evidence(db, _make_evidence_payload(claim="e1"))
        ev2 = svc.create_evidence(db, _make_evidence_payload(claim="e2"))
        tid = thesis["thesis"]["id"]

        svc.link_evidence(db, tid, ev1["id"], "support", 1, "l1")  # rev=2
        svc.link_evidence(db, tid, ev2["id"], "oppose", 2, "l2")  # rev=3
        svc.update_stance(db, tid, ev1["id"], "neutral", 3, "s")  # rev=4

        current = svc.get_thesis(db, tid)
        rev = svc.get_revision(db, tid, 4)
        assert current == rev["snapshot"]


# ---------------------------------------------------------------------------
# revision 编号连续且唯一
# ---------------------------------------------------------------------------

class TestRevisionNumbering:
    def test_revision_numbers_are_consecutive_and_unique(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload())
        tid = thesis["thesis"]["id"]
        svc.link_evidence(db, tid, ev["id"], "support", 1, "l")  # 2
        svc.update_stance(db, tid, ev["id"], "oppose", 2, "s")  # 3
        svc.unlink_evidence(db, tid, ev["id"], 3, "u")  # 4

        revs = svc.list_revisions(db, tid)
        numbers = [r["revision_number"] for r in revs["items"]]
        assert numbers == [1, 2, 3, 4]


# ---------------------------------------------------------------------------
# 历史 snapshot 不可变
# ---------------------------------------------------------------------------

class TestSnapshotImmutability:
    def test_historical_snapshot_preserves_deleted_evidence(self, db):
        """软删除证据后，历史 snapshot 仍保留删除前的证据内容。"""
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload(claim="original"))
        tid = thesis["thesis"]["id"]
        svc.link_evidence(db, tid, ev["id"], "support", 1, "l")  # rev=2，含证据

        # 删除证据 → rev=3，当前不含证据
        svc.soft_delete_evidence(db, ev["id"])

        # rev=2 的 snapshot 仍应包含证据
        rev2 = svc.get_revision(db, tid, 2)
        assert len(rev2["snapshot"]["evidence_links"]) == 1
        assert rev2["snapshot"]["evidence_links"][0]["claim"] == "original"

        # 当前聚合状态不含证据
        current = svc.get_thesis(db, tid)
        assert len(current["evidence_links"]) == 0

    def test_historical_snapshot_preserves_old_field_values(self, db):
        """thesis 编辑后，旧 revision 的 snapshot 保留旧字段。"""
        thesis = svc.create_thesis(db, _make_thesis_payload(title="t1"))
        tid = thesis["thesis"]["id"]
        svc.update_thesis(db, tid, {
            "title": "t2", "summary": "s2", "status": "active",
            "core_claims": [], "catalysts": [], "risks": [], "invalidation_conditions": [],
            "expected_revision": 1, "change_summary": "edit",
        }, expected_revision=1)

        rev1 = svc.get_revision(db, tid, 1)
        rev2 = svc.get_revision(db, tid, 2)
        assert rev1["snapshot"]["thesis"]["title"] == "t1"
        assert rev2["snapshot"]["thesis"]["title"] == "t2"


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

class TestDiff:
    def test_diff_thesis_field_change(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload(title="t1"))
        tid = thesis["thesis"]["id"]
        svc.update_thesis(db, tid, {
            "title": "t2", "summary": "s2", "status": "active",
            "core_claims": [], "catalysts": [], "risks": [], "invalidation_conditions": [],
            "expected_revision": 1, "change_summary": "edit",
        }, expected_revision=1)

        diff = svc.diff_revisions(db, tid, 1, 2)
        assert diff["from_revision"] == 1
        assert diff["to_revision"] == 2
        assert diff["thesis_changes"]["title"] == {"from": "t1", "to": "t2"}

    def test_diff_evidence_added(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload())
        tid = thesis["thesis"]["id"]
        svc.link_evidence(db, tid, ev["id"], "support", 1, "l")

        diff = svc.diff_revisions(db, tid, 1, 2)
        assert len(diff["evidence_added"]) == 1
        assert diff["evidence_added"][0]["evidence_id"] == ev["id"]

    def test_diff_evidence_removed(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload())
        tid = thesis["thesis"]["id"]
        svc.link_evidence(db, tid, ev["id"], "support", 1, "l")  # rev=2
        svc.unlink_evidence(db, tid, ev["id"], 2, "u")  # rev=3

        diff = svc.diff_revisions(db, tid, 2, 3)
        assert len(diff["evidence_removed"]) == 1

    def test_diff_stance_change(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        ev = svc.create_evidence(db, _make_evidence_payload())
        tid = thesis["thesis"]["id"]
        svc.link_evidence(db, tid, ev["id"], "support", 1, "l")  # rev=2
        svc.update_stance(db, tid, ev["id"], "oppose", 2, "s")  # rev=3

        diff = svc.diff_revisions(db, tid, 2, 3)
        assert len(diff["evidence_changed"]) == 1
        assert diff["evidence_changed"][0]["changes"]["stance"] == {"from": "support", "to": "oppose"}


# ---------------------------------------------------------------------------
# 分页
# ---------------------------------------------------------------------------

class TestPagination:
    def test_invalid_limit_zero(self):
        with pytest.raises(svc.ValidationError):
            svc.validate_pagination(limit=0, offset=0)

    def test_invalid_limit_over_max(self):
        with pytest.raises(svc.ValidationError):
            svc.validate_pagination(limit=201, offset=0)

    def test_invalid_offset_negative(self):
        with pytest.raises(svc.ValidationError):
            svc.validate_pagination(limit=50, offset=-1)

    def test_valid_pagination(self):
        assert svc.validate_pagination(50, 0) == (50, 0)
        assert svc.validate_pagination(200, 100) == (200, 100)


# ---------------------------------------------------------------------------
# 数据库路径解析
# ---------------------------------------------------------------------------

class TestResolveDbPath:
    def test_explicit_path_wins(self, tmp_path):
        p = tmp_path / "x.db"
        assert svc.resolve_db_path(p) == p

    def test_env_var(self, monkeypatch, tmp_path):
        p = tmp_path / "env.db"
        monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(p))
        assert svc.resolve_db_path() == p

    def test_vr_data_dir(self, monkeypatch, tmp_path):
        monkeypatch.delenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", raising=False)
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        assert svc.resolve_db_path() == tmp_path / "evidence_thesis.db"


# ---------------------------------------------------------------------------
# 损坏数据库
# ---------------------------------------------------------------------------

class TestCorruptedDb:
    def test_service_raises_corrupted_error(self, db, monkeypatch):
        """服务层异常应透传 EvidenceLedgerCorruptedError。"""
        def _raise_corrupted(*args, **kwargs):
            raise store.EvidenceLedgerCorruptedError()
        monkeypatch.setattr(store, "read_transaction", _raise_corrupted)
        with pytest.raises(store.EvidenceLedgerCorruptedError):
            svc.list_evidence(db)


# ---------------------------------------------------------------------------
# 创建证据的校验
# ---------------------------------------------------------------------------

class TestEvidenceValidation:
    def test_invalid_evidence_type(self, db):
        payload = _make_evidence_payload()
        payload["evidence_type"] = "invalid"
        with pytest.raises(svc.ValidationError):
            svc.create_evidence(db, payload)

    def test_invalid_classification(self, db):
        payload = _make_evidence_payload()
        payload["classification"] = "invalid"
        with pytest.raises(svc.ValidationError):
            svc.create_evidence(db, payload)

    def test_invalid_confidence(self, db):
        payload = _make_evidence_payload()
        payload["confidence"] = "invalid"
        with pytest.raises(svc.ValidationError):
            svc.create_evidence(db, payload)

    def test_empty_claim(self, db):
        payload = _make_evidence_payload()
        payload["claim"] = ""
        with pytest.raises(svc.ValidationError):
            svc.create_evidence(db, payload)

    def test_invalid_source_date(self, db):
        payload = _make_evidence_payload()
        payload["source_date"] = "not-a-date"
        with pytest.raises(svc.ValidationError):
            svc.create_evidence(db, payload)

    def test_missing_accessed_at(self, db):
        payload = _make_evidence_payload()
        payload["accessed_at"] = ""
        with pytest.raises(svc.ValidationError):
            svc.create_evidence(db, payload)

    def test_source_date_can_be_none(self, db):
        payload = _make_evidence_payload()
        payload["source_date"] = None
        result = svc.create_evidence(db, payload)
        assert result["source_date"] is None


# ---------------------------------------------------------------------------
# thesis 创建校验
# ---------------------------------------------------------------------------

class TestThesisValidation:
    def test_empty_title(self, db):
        payload = _make_thesis_payload()
        payload["title"] = ""
        with pytest.raises(svc.ValidationError):
            svc.create_thesis(db, payload)

    def test_core_claims_must_be_list(self, db):
        payload = _make_thesis_payload()
        payload["core_claims"] = "not a list"
        with pytest.raises(svc.ValidationError):
            svc.create_thesis(db, payload)

    def test_put_cannot_set_archived(self, db):
        thesis = svc.create_thesis(db, _make_thesis_payload())
        with pytest.raises(svc.ValidationError):
            svc.update_thesis(db, thesis["thesis"]["id"], {
                "title": "x", "summary": "x", "status": "archived",
                "core_claims": [], "catalysts": [], "risks": [], "invalidation_conditions": [],
                "expected_revision": 1, "change_summary": "x",
            }, expected_revision=1)


# ---------------------------------------------------------------------------
# 列表查询
# ---------------------------------------------------------------------------

class TestListQueries:
    def test_list_evidence_by_subject(self, db):
        svc.create_evidence(db, _make_evidence_payload(subject_id="600519"))
        svc.create_evidence(db, _make_evidence_payload(subject_id="000001"))
        result = svc.list_evidence(db, subject_type="stock", subject_id="600519")
        assert result["total"] == 1

    def test_list_thesis_by_status(self, db):
        t1 = svc.create_thesis(db, _make_thesis_payload())
        svc.archive_thesis(db, t1["thesis"]["id"], expected_revision=1)
        svc.create_thesis(db, _make_thesis_payload(title="t2"))

        active = svc.list_thesis(db, status="active")
        archived = svc.list_thesis(db, status="archived")
        assert active["total"] == 1
        assert archived["total"] == 1

    def test_list_evidence_excludes_deleted(self, db):
        ev = svc.create_evidence(db, _make_evidence_payload())
        svc.soft_delete_evidence(db, ev["id"])
        result = svc.list_evidence(db)
        assert result["total"] == 0
