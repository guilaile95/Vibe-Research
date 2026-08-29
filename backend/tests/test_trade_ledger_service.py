"""Tests for trade_ledger_service validation, linking, and computed fields."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

import ai_result_store
import evidence_thesis_service
import review_db_path
import trade_ledger_service as svc


@pytest.fixture(autouse=True)
def _isolate_dbs(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    trade_db = data_dir / "trade_ledger.sqlite3"
    review_db = data_dir / "daily_reviews.sqlite3"
    thesis_db = data_dir / "evidence_thesis.db"

    monkeypatch.setenv("VR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(trade_db))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(review_db))
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(thesis_db))
    yield


class TestValidation:
    def _base_input(self, **overrides):
        data = {
            "code": "600519",
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 1500.0,
            "actual_quantity": 100,
            "executed_at": "2026-07-28T09:30:00+08:00",
        }
        data.update(overrides)
        return data

    def test_full_buy_valid(self):
        record = svc.validate_and_build_record(self._base_input())
        assert record["execution_status"] == "full"
        assert record["actual_price"] == 1500.0
        assert record["actual_quantity"] == 100
        assert record["executed_at"] == "2026-07-28T01:30:00.000000+00:00"
        assert record["trade_id"] is not None

    def test_missing_required_fields_raises_validation_error(self):
        for req in ("code", "name", "operation", "execution_status"):
            inp = self._base_input()
            del inp[req]
            with pytest.raises(svc.TradeValidationError) as exc:
                svc.validate_and_build_record(inp)
            assert f"{req} 必填" in str(exc.value)

    def test_executed_at_timezone_required(self):
        with pytest.raises(svc.TradeValidationError) as exc:
            svc.validate_and_build_record(self._base_input(executed_at="2026-07-28T09:30:00"))
        assert "时区" in str(exc.value)

    def test_not_executed_forces_executed_at_null(self):
        record = svc.validate_and_build_record(
            self._base_input(
                execution_status="not_executed",
                executed_at="2026-07-28T09:30:00+08:00",
                unexecuted_reason="取消",
            )
        )
        assert record["executed_at"] is None

    def test_invalid_code_format(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(code="60051"))

    def test_invalid_operation(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(operation="hold"))

    def test_unknown_field_rejected(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(extra_field="x"))


class TestAdviceRefValidation:
    def test_advice_ref_extra_field_rejected(self):
        ref = {
            "trade_date": "2026-07-28",
            "generated_at": "2026-07-28 09:00:00",
            "unknown_field": "val",
        }
        with pytest.raises(svc.TradeValidationError) as exc:
            svc._resolve_advice_ref(ref, "600519")
        assert "advice_ref 含有未知字段" in str(exc.value)

    def test_invalid_calendar_date_rejected(self):
        for bad_date in ("2026-02-30", "2026-13-01", "2026-00-01", "2026-7-1"):
            ref = {"trade_date": bad_date, "generated_at": "2026-07-28 09:00:00"}
            with pytest.raises(svc.TradeValidationError) as exc:
                svc._resolve_advice_ref(ref, "600519")
            assert "advice_ref.trade_date" in str(exc.value)


class TestSharedReviewDbPath:
    _REF = {
        "trade_date": "2026-07-28",
        "generated_at": "2026-07-28 09:00:00",
    }

    @staticmethod
    def _capture_lookup(monkeypatch):
        seen = []

        def fake_get_result(db_path, *_args):
            seen.append(Path(db_path))
            return None

        monkeypatch.setattr(ai_result_store, "get_result", fake_get_result)
        with pytest.raises(svc.AdviceNotFoundError):
            svc._resolve_advice_ref(TestSharedReviewDbPath._REF, "600519")
        return seen

    def test_override_uses_shared_contract_without_creating_files(self, tmp_path, monkeypatch):
        target = tmp_path / "external" / "daily_reviews.sqlite3"
        monkeypatch.setenv(review_db_path.REVIEW_DB_ENV, str(target))

        assert self._capture_lookup(monkeypatch) == [target.resolve()]
        assert not target.parent.exists()
        assert not target.exists()

    def test_windows_default_ignores_vr_data_dir_without_creating_sidecars(
        self, tmp_path, monkeypatch
    ):
        local_app_data = tmp_path / "Local"
        monkeypatch.delenv(review_db_path.REVIEW_DB_ENV, raising=False)
        monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
        with monkeypatch.context() as platform_patch:
            platform_patch.setattr(review_db_path.sys, "platform", "win32")
            expected = (
                local_app_data / "VibeResearch" / "daily_reviews.sqlite3"
            ).resolve()
            assert self._capture_lookup(platform_patch) == [expected]

        assert expected != (Path(os.environ["VR_DATA_DIR"]) / "daily_reviews.sqlite3").resolve()
        assert not expected.parent.exists()
        assert not expected.exists()
        for suffix in ("-wal", "-shm", "-journal"):
            assert not expected.with_name(expected.name + suffix).exists()


class TestRealAdviceReference:
    def _create_sample_advice(self, trade_date="2026-07-28", generated_at="2026-07-28 09:00:00"):
        review_db = Path(os.environ["VIBE_RESEARCH_REVIEW_DB"])
        payload = {
            "trade_date": trade_date,
            "generated_at": generated_at,
            "holdings": [
                {
                    "code": "600519",
                    "action": "add",
                    "execution_quantity": 100,
                    "price_conditions": ["低于1500"],
                    "execution_plan": ["分批建仓"],
                    "risk_conditions": ["止损点1400"],
                    "invalidation_conditions": ["财报转亏"],
                    "confidence": "high",
                }
            ],
        }
        record = {
            "result_type": "portfolio_advice",
            "trade_date": trade_date,
            "schema_version": "portfolio_advice.v1",
            "payload": payload,
            "generated_at": generated_at,
            "model_provider": "api-compatible",
            "model_name": "gpt-4",
        }
        ai_result_store.upsert_result(review_db, record)

    def test_real_advice_ref_success(self):
        self._create_sample_advice()
        ref = {"trade_date": "2026-07-28", "generated_at": "2026-07-28 09:00:00"}
        date_out, gen_out, snapshot_json = svc._resolve_advice_ref(ref, "600519")
        assert date_out == "2026-07-28"
        assert gen_out == "2026-07-28 09:00:00"

        snapshot = json.loads(snapshot_json)
        assert set(snapshot.keys()) == {
            "action", "execution_quantity", "price_conditions",
            "execution_plan", "risk_conditions", "invalidation_conditions", "confidence",
        }
        assert snapshot["action"] == "add"
        assert snapshot["execution_quantity"] == 100
        assert snapshot["confidence"] == "high"

    def test_real_advice_ref_not_found(self):
        ref = {"trade_date": "2026-07-28", "generated_at": "2026-07-28 09:00:00"}
        with pytest.raises(svc.AdviceNotFoundError):
            svc._resolve_advice_ref(ref, "600519")

    def test_real_advice_ref_generated_at_conflict(self):
        self._create_sample_advice(generated_at="2026-07-28 09:00:00")
        ref = {"trade_date": "2026-07-28", "generated_at": "2026-07-28 10:00:00"}
        with pytest.raises(svc.AdviceConflictError):
            svc._resolve_advice_ref(ref, "600519")

    def test_real_advice_ref_payload_trade_date_conflict(self):
        review_db = Path(os.environ["VIBE_RESEARCH_REVIEW_DB"])
        payload = {
            "trade_date": "2026-07-27",  # Mismatch with record trade_date
            "generated_at": "2026-07-28 09:00:00",
            "holdings": [{"code": "600519"}],
        }
        record = {
            "result_type": "portfolio_advice",
            "trade_date": "2026-07-28",
            "schema_version": "portfolio_advice.v1",
            "payload": payload,
            "generated_at": "2026-07-28 09:00:00",
            "model_provider": "api-compatible",
            "model_name": "gpt-4",
        }
        ai_result_store.upsert_result(review_db, record)

        ref = {"trade_date": "2026-07-28", "generated_at": "2026-07-28 09:00:00"}
        with pytest.raises(svc.AdviceConflictError):
            svc._resolve_advice_ref(ref, "600519")

    def test_real_advice_ref_stock_not_found(self):
        self._create_sample_advice()
        ref = {"trade_date": "2026-07-28", "generated_at": "2026-07-28 09:00:00"}
        with pytest.raises(svc.AdviceHoldingNotFoundError):
            svc._resolve_advice_ref(ref, "000001")

    def test_real_advice_ref_missing_snapshot_field(self):
        review_db = Path(os.environ["VIBE_RESEARCH_REVIEW_DB"])
        payload = {
            "trade_date": "2026-07-28",
            "generated_at": "2026-07-28 09:00:00",
            "holdings": [
                {
                    "code": "600519",
                    "action": "add",
                    # Missing 6 other fields
                }
            ],
        }
        record = {
            "result_type": "portfolio_advice",
            "trade_date": "2026-07-28",
            "schema_version": "portfolio_advice.v1",
            "payload": payload,
            "generated_at": "2026-07-28 09:00:00",
            "model_provider": "api-compatible",
            "model_name": "gpt-4",
        }
        ai_result_store.upsert_result(review_db, record)

        ref = {"trade_date": "2026-07-28", "generated_at": "2026-07-28 09:00:00"}
        with pytest.raises(svc.TradeValidationError) as exc:
            svc._resolve_advice_ref(ref, "600519")
        assert "缺少必需字段" in str(exc.value)


class TestRealThesisReference:
    def test_real_thesis_ref_success(self):
        thesis_db = Path(os.environ["VIBE_RESEARCH_EVIDENCE_THESIS_DB"])
        created = evidence_thesis_service.create_thesis(thesis_db, {
            "subject_type": "stock",
            "subject_id": "600519",
            "title": "茅台投资逻辑",
            "summary": "龙头溢价",
            "core_claims": ["核心主张"],
            "catalysts": ["催化剂"],
            "risks": ["风险点"],
            "invalidation_conditions": ["证伪条件"],
        })
        thesis_id = created["thesis"]["id"]
        updated = evidence_thesis_service.update_thesis(thesis_db, thesis_id, {
            "title": "茅台投资逻辑 v2",
            "summary": "龙头溢价+渠道改革",
            "core_claims": ["核心主张"],
            "catalysts": ["催化剂"],
            "risks": ["风险点"],
            "invalidation_conditions": ["证伪条件"],
        }, expected_revision=1)
        assert updated["thesis"]["current_revision"] == 2

        tid_out, rev_out = svc._resolve_thesis_ref({
            "thesis_id": thesis_id,
            "revision_number": 2,
        })
        assert tid_out == thesis_id
        assert rev_out == 2

    def test_real_thesis_ref_thesis_not_found(self):
        with pytest.raises(svc.ThesisNotFoundError):
            svc._resolve_thesis_ref({"thesis_id": "nonexistent-id", "revision_number": 1})

    def test_real_thesis_ref_revision_not_found(self):
        thesis_db = Path(os.environ["VIBE_RESEARCH_EVIDENCE_THESIS_DB"])
        created = evidence_thesis_service.create_thesis(thesis_db, {
            "subject_type": "stock",
            "subject_id": "600519",
            "title": "茅台投资逻辑",
            "summary": "龙头溢价",
            "core_claims": ["核心主张"],
            "catalysts": ["催化剂"],
            "risks": ["风险点"],
            "invalidation_conditions": ["证伪条件"],
        })
        thesis_id = created["thesis"]["id"]

        with pytest.raises(svc.ThesisRevisionNotFoundError):
            svc._resolve_thesis_ref({"thesis_id": thesis_id, "revision_number": 999})

    def test_thesis_db_unmodified_by_reference_read(self):
        thesis_db = Path(os.environ["VIBE_RESEARCH_EVIDENCE_THESIS_DB"])
        created = evidence_thesis_service.create_thesis(thesis_db, {
            "subject_type": "stock",
            "subject_id": "600519",
            "title": "茅台投资逻辑",
            "summary": "龙头溢价",
            "core_claims": ["核心主张"],
            "catalysts": ["催化剂"],
            "risks": ["风险点"],
            "invalidation_conditions": ["证伪条件"],
        })
        thesis_id = created["thesis"]["id"]

        # Record file size, mtime, and sqlite tables before reading
        stat_before = thesis_db.stat()
        conn = sqlite3.connect(str(thesis_db))
        tables_before = set(conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
        conn.close()

        # Execute thesis reference resolution
        svc._resolve_thesis_ref({"thesis_id": thesis_id, "revision_number": 1})

        # Verify source DB completely untouched
        stat_after = thesis_db.stat()
        conn2 = sqlite3.connect(str(thesis_db))
        tables_after = set(conn2.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
        conn2.close()

        assert stat_before.st_size == stat_after.st_size
        assert stat_before.st_mtime == stat_after.st_mtime
        assert tables_before == tables_after


class TestTotalCostAndCashFlowSemantics:
    def test_sell_cost_and_cash_flow(self):
        record = {
            "operation": "sell",
            "execution_status": "full",
            "actual_price": 120.0,
            "actual_quantity": 100,
            "fee": 5.0,
            "other_cost": 1.0,
            "planned_price": None,
            "planned_quantity": None,
            "advice_snapshot": None,
        }
        result = svc.compute_fields(record)
        assert result["gross_amount"] == 12000.0
        assert result["total_cost"] == 6.0
        assert result["net_cash_flow"] == 11994.0

    def test_buy_cost_and_cash_flow(self):
        record = {
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 100.0,
            "actual_quantity": 100,
            "fee": 5.0,
            "other_cost": 1.0,
            "planned_price": None,
            "planned_quantity": None,
            "advice_snapshot": None,
        }
        result = svc.compute_fields(record)
        assert result["gross_amount"] == 10000.0
        assert result["total_cost"] == 6.0
        assert result["net_cash_flow"] == -10006.0


class TestPortfolioJsonZeroSideEffects:
    def test_portfolio_json_unmodified(self, tmp_path, monkeypatch):
        portfolio_file = tmp_path / "portfolio.json"
        portfolio_content = '{"holdings": [{"code": "600519", "quantity": 100}]}'
        portfolio_file.write_text(portfolio_content, encoding="utf-8")

        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(tmp_path / "trade_ledger.sqlite3"))

        stat_before = portfolio_file.stat()

        data = {
            "code": "600519",
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 1500.0,
            "actual_quantity": 100,
            "executed_at": "2026-07-28T09:30:00+08:00",
        }
        trade = svc.create_trade(data)
        svc.get_trade(trade["trade_id"])
        svc.list_trades()
        svc.void_trade(trade["trade_id"], "测试")

        stat_after = portfolio_file.stat()
        assert portfolio_file.read_text(encoding="utf-8") == portfolio_content
        assert stat_before.st_size == stat_after.st_size
        assert stat_before.st_mtime == stat_after.st_mtime
