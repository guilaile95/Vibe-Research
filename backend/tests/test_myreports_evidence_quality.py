"""Real report-module regression, synthetic files only, no provider/model calls.

Run without third-party dependencies:
  python -B -m unittest discover -s backend/tests -p test_myreports_evidence_quality.py -v
"""
from __future__ import annotations

import base64
import hashlib
import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


class ReportEvidenceQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.import_dir = tempfile.TemporaryDirectory(prefix="vr-evidence-import-")
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        with patch.dict(os.environ, {"VR_REPORTS_DIR": cls.import_dir.name,
                                     "VR_DATA_DIR": cls.import_dir.name}):
            cls.mr = importlib.import_module("myreports")
            cls.ft = importlib.import_module("myreports_fulltext")

    @classmethod
    def tearDownClass(cls):
        sys.path.pop(0)
        cls.import_dir.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vr-evidence-fixture-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.scope = patch.object(self.mr, "REPORTS_DIR", self.root)
        self.scope.start()
        self.addCleanup(self.scope.stop)

    def upload(self, text, name="report.txt"):
        return self.mr.save_report(name, base64.b64encode(text.encode()).decode())

    def source(self, report):
        return self.root / (report["id"] + report["ext"])

    def search(self, report, term="catalyst"):
        return self.mr.search_report_text(term, report_ids=[report["id"]])

    def context(self, report, hits):
        return self.mr.build_chat_report_context(hits, report_ids=[report["id"]])

    def test_normal_short_report_keeps_citation_and_read_only_behavior(self):
        report = self.upload("catalyst final revenue 80")
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        hits = self.search(report)
        context, sources, coverage = self.context(report, hits)
        self.assertIn("final revenue 80", context)
        self.assertEqual(sources, [{"report_id": report["id"], "title": "report", "page": None}])
        self.assertEqual(hits[0]["file_sha256"], hashlib.sha256(self.source(report).read_bytes()).hexdigest())
        self.assertFalse(coverage["excerpt_truncated"])
        self.assertEqual(coverage["content_coverage"], "EXCERPTS_ONLY")
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_raw_only_change_blocks_search_and_previously_returned_hit(self):
        report = self.upload("catalyst OLD_REVENUE_100")
        hits = self.search(report)
        self.source(report).write_text("catalyst CURRENT_REVENUE_80", encoding="utf-8")
        self.assertEqual(self.search(report), [])
        context, sources, coverage = self.context(report, hits)
        self.assertEqual(sources, [])
        self.assertNotIn("OLD_REVENUE_100", context)
        self.assertEqual(coverage["rejected_hit_count"], 1)
        self.assertEqual(coverage["uncovered_reports"][0]["reason"], "NOT_INDEXED")
        self.assertFalse(coverage["context_truncated"])

    def test_metadata_file_changed_blocks_old_index(self):
        report = self.upload("catalyst OLD_REVENUE_100")
        self.source(report).write_text("catalyst CURRENT_REVENUE_80", encoding="utf-8")
        entries = self.mr._load_index()
        entries[0]["file_sha256"] = hashlib.sha256(self.source(report).read_bytes()).hexdigest()
        self.mr._save_index(entries)
        self.assertEqual(self.mr.list_reports()[0]["text_index_error"], "FILE_CHANGED")
        self.assertEqual(self.search(report), [])

    def test_deleted_source_blocks_cached_hit(self):
        report = self.upload("catalyst OLD_REVENUE_100")
        hits = self.search(report)
        self.source(report).unlink()
        self.assertEqual(self.mr.list_reports()[0]["text_index_error"], "SOURCE_UNAVAILABLE")
        self.assertEqual(self.search(report), [])
        context, sources, coverage = self.context(report, hits)
        self.assertNotIn("OLD_REVENUE_100", context)
        self.assertEqual(sources, [])
        self.assertEqual(coverage["uncovered_reports"][0]["reason"], "NOT_INDEXED")

    def test_legacy_fingerprint_requires_reindex_and_recovers(self):
        report = self.upload("catalyst legacy material")
        with closing(sqlite3.connect(str(self.root / self.ft.INDEX_NAME))) as conn, conn:
            conn.execute("UPDATE report_text_index SET file_sha256='' WHERE report_id=?", [report["id"]])
        self.assertEqual(self.search(report), [])
        self.mr.index_report_text(report["id"])
        self.assertEqual(len(self.search(report)), 1)

    def test_reindex_binds_current_source_and_rejects_old_hit(self):
        report = self.upload("catalyst OLD_REVENUE_100")
        old = self.search(report)
        self.source(report).write_text("catalyst CURRENT_REVENUE_80", encoding="utf-8")
        rebuilt = self.mr.index_report_text(report["id"])
        self.assertEqual(rebuilt["text_index_status"], "SEARCHABLE")
        self.assertEqual(self.mr._load_index()[0]["file_sha256"], rebuilt["file_sha256"])
        context, sources, coverage = self.context(report, old)
        self.assertNotIn("OLD_REVENUE_100", context)
        self.assertEqual(sources, [])
        self.assertEqual(coverage["uncovered_reports"][0]["reason"], "STALE_HIT")
        self.assertIn("CURRENT_REVENUE_80", self.context(report, self.search(report))[0])

    def test_corrected_extraction_of_unchanged_source_rejects_old_hit_even_same_clock(self):
        report = self.upload("catalyst OLD_EXTRACTION_100")
        old = self.search(report)
        before = self.source(report).read_bytes()
        state = self.ft.status_map(self.root, [report])[report["id"]]
        with patch.object(self.ft, "extract", return_value=(
            self.ft.STATUS_SEARCHABLE, [(0, "catalyst CORRECTED_EXTRACTION_80")], None, ""
        )):
            self.mr.index_report_text(report["id"])
        # A wall-clock timestamp is not a unique content version.
        with closing(sqlite3.connect(str(self.root / self.ft.INDEX_NAME))) as conn, conn:
            conn.execute("UPDATE report_text_index SET indexed_at=? WHERE report_id=?",
                         (state["indexed_at"], report["id"]))
        self.assertEqual(self.source(report).read_bytes(), before)
        context, sources, coverage = self.context(report, old)
        self.assertEqual(sources, [])
        self.assertNotIn("OLD_EXTRACTION_100", context)
        self.assertEqual(coverage["rejected_hit_count"], 1)
        self.assertEqual(coverage["uncovered_reports"][0]["reason"], "STALE_HIT")
        current = self.search(report)
        self.assertEqual(current[0]["file_sha256"], old[0]["file_sha256"])
        self.assertIn("CORRECTED_EXTRACTION_80", self.context(report, current)[0])

    def test_identical_reextraction_preserves_content_identity_without_writes(self):
        report = self.upload("catalyst first\n\nline\twith spacing")
        old = self.search(report)
        self.mr.index_report_text(report["id"])
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        context, sources, coverage = self.context(report, old)
        self.assertIn(old[0]["snippet"], context)
        self.assertEqual(len(sources), 1)
        self.assertEqual(coverage["rejected_hit_count"], 0)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_correction_beyond_snippet_still_invalidates_old_chunk_identity(self):
        report = self.upload("catalyst preliminary 100. " + "background " * 70)
        old = self.search(report)
        changed = self.source(report).read_text() + "Correction: final 80."
        with patch.object(self.ft, "extract", return_value=(
            self.ft.STATUS_SEARCHABLE, [(0, changed)], None, ""
        )):
            self.mr.index_report_text(report["id"])
        fresh = self.search(report)
        self.assertEqual(old[0]["snippet"], fresh[0]["snippet"])
        self.assertNotEqual(old[0]["chunk_sha256"], fresh[0]["chunk_sha256"])
        self.assertEqual(self.context(report, old)[1], [])
        self.assertEqual(len(self.context(report, fresh)[1]), 1)
        self.assertTrue(self.context(report, fresh)[2]["excerpt_truncated"])

    def test_missing_digest_changed_snippet_and_wrong_location_are_not_evidence(self):
        report = self.upload("catalyst SOURCE_TEXT")
        hit = self.search(report)[0]
        for change in ({"chunk_sha256": None}, {"chunk_sha256": "wrong"},
                       {"snippet": "catalyst UNSUPPORTED_TEXT"}, {"page": 9},
                       {"page": True}, {"page": -1}):
            with self.subTest(change=change):
                context, sources, coverage = self.context(report, [{**hit, **change}])
                self.assertEqual(sources, [])
                self.assertNotIn("UNSUPPORTED_TEXT", context)
                self.assertEqual(coverage["rejected_hit_count"], 1)
                self.assertEqual(coverage["uncovered_reports"][0]["reason"], "STALE_HIT")

    def test_deleted_chunk_is_rejected_without_removing_current_index(self):
        report = self.upload("catalyst deleted extraction")
        old = self.search(report)
        with closing(sqlite3.connect(str(self.root / self.ft.INDEX_NAME))) as conn, conn:
            conn.execute("DELETE FROM report_text_chunks WHERE report_id=?", (report["id"],))
        self.assertEqual(self.ft.status_map(self.root, [report])[report["id"]]["text_index_status"],
                         self.ft.STATUS_SEARCHABLE)
        context, sources, coverage = self.context(report, old)
        self.assertEqual(sources, [])
        self.assertNotIn("deleted extraction", context)
        self.assertEqual(coverage["uncovered_reports"][0]["reason"], "STALE_HIT")

    def test_extraction_exception_invalidates_old_index_then_recovers(self):
        report = self.upload("catalyst OLD_REVENUE_100")
        old = self.search(report)
        with patch.object(self.ft, "extract", side_effect=RuntimeError("synthetic extraction failure")):
            with self.assertRaises(self.ft.ReportTextIndexError):
                self.mr.index_report_text(report["id"])
        self.assertEqual(self.mr.list_reports()[0]["text_index_status"], "INDEX_ERROR")
        self.assertEqual(self.search(report), [])
        context, sources, coverage = self.context(report, old)
        self.assertEqual(sources, [])
        self.assertNotIn("OLD_REVENUE_100", context)
        self.assertEqual(coverage["uncovered_reports"][0]["reason"], "INDEX_ERROR")
        with closing(sqlite3.connect(str(self.root / self.ft.INDEX_NAME))) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM report_text_chunks").fetchone()[0], 0)
        self.mr.index_report_text(report["id"])
        self.assertEqual(len(self.search(report)), 1)

    def test_returned_index_error_overrides_old_metadata_and_recovers(self):
        report = self.upload("catalyst OLD_REVENUE_100")
        old = self.search(report)
        self.source(report).write_bytes(b"\xff\xfe")
        self.assertEqual(self.mr.index_report_text(report["id"])["text_index_status"], "INDEX_ERROR")
        self.assertEqual(self.context(report, old)[2]["uncovered_reports"][0]["reason"], "INDEX_ERROR")
        self.assertEqual(self.search(report), [])
        self.source(report).write_text("catalyst repaired", encoding="utf-8")
        self.mr.index_report_text(report["id"])
        self.assertIn("repaired", self.context(report, self.search(report))[0])

    def test_source_change_during_extraction_cannot_publish_chunks(self):
        report = self.upload("catalyst ORIGINAL")
        original_extract = self.ft.extract

        def changing_extract(path, ext):
            result = original_extract(path, ext)
            path.write_text("catalyst NEW_CONTENT", encoding="utf-8")
            return result

        with patch.object(self.ft, "extract", side_effect=changing_extract):
            result = self.mr.index_report_text(report["id"])
        self.assertEqual(result["text_index_status"], "INDEX_ERROR")
        self.assertEqual(result["text_index_error"], "FILE_CHANGED_DURING_INDEX")
        self.assertEqual(self.search(report), [])

    def test_late_correction_is_omitted_but_coverage_is_explicitly_partial(self):
        body = "catalyst preliminary revenue 100. " + "background " * 70 + "catalyst correction: final revenue 80."
        report = self.upload(body)
        hits = self.search(report)
        context, sources, coverage = self.context(report, hits)
        self.assertIn("final revenue 80", self.source(report).read_text(encoding="utf-8"))
        self.assertIn("preliminary revenue 100", context)
        self.assertNotIn("final revenue 80", context)  # Known retrieval boundary, not a model pass.
        self.assertEqual(coverage["selected_count"], coverage["included_report_count"])
        self.assertEqual(coverage["uncovered_reports"], [])
        self.assertFalse(coverage["context_truncated"])
        self.assertFalse(coverage["hit_limit_reached"])
        self.assertTrue(coverage["excerpt_truncated"])
        self.assertEqual(coverage["content_coverage"], "EXCERPTS_ONLY")
        self.assertIn("不代表正文或最终结论已覆盖", context)
        self.assertIn("更正或反证", context)

    def test_unselected_source_is_never_hashed_or_included(self):
        report = self.upload("catalyst selected")
        other = self.upload("catalyst SYNTHETIC_UNSELECTED", "unselected.txt")
        original_hash = self.ft._source_sha256
        with patch.object(self.ft, "_source_sha256", wraps=original_hash) as fingerprint:
            context, sources, coverage = self.context(report, self.search(report))
        self.assertTrue(fingerprint.call_args_list)
        self.assertTrue(all(args[0][0] == self.source(report) for args in fingerprint.call_args_list))
        self.assertNotIn("SYNTHETIC_UNSELECTED", context)
        self.assertNotIn(other["id"], context)

    def test_stale_hit_rejections_do_not_change_hit_limit_or_budget_semantics(self):
        report = self.upload("catalyst old")
        hits = self.search(report) * self.mr.CHAT_REPORT_HIT_LIMIT
        self.source(report).write_text("catalyst changed", encoding="utf-8")
        context, sources, coverage = self.context(report, hits)
        self.assertTrue(coverage["hit_limit_reached"])
        self.assertFalse(coverage["context_truncated"])
        self.assertEqual(coverage["rejected_hit_count"], 8)
        self.assertEqual(sources, [])


if __name__ == "__main__":
    unittest.main()
