"""Tests for trade_ledger_service validation and computed fields."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import trade_ledger_service as svc


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
        # Naive ISO string without timezone -> rejected
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


class TestAdviceSnapshotStructure:
    def test_valid_advice_snapshot_extraction(self):
        holding = {
            "code": "600519",
            "action": "add",
            "execution_quantity": 100,
            "price_conditions": ["低于1500"],
            "execution_plan": ["分批建仓"],
            "risk_conditions": ["回撤不超5%"],
            "invalidation_conditions": ["基本面恶化"],
            "confidence": "high",
        }
        extracted = svc._validate_and_extract_advice_snapshot(holding)
        assert extracted["action"] == "add"
        assert extracted["confidence"] == "high"

    def test_advice_snapshot_missing_key_rejected(self):
        holding = {
            "code": "600519",
            "action": "add",
            # missing confidence and other keys
        }
        with pytest.raises(svc.TradeValidationError) as exc:
            svc._validate_and_extract_advice_snapshot(holding)
        assert "建议持仓缺少必需字段" in str(exc.value)


class TestThesisRefValidation:
    def test_thesis_ref_extra_field_rejected(self):
        ref = {
            "thesis_id": "th-123",
            "revision_number": 1,
            "extra_key": "x",
        }
        with pytest.raises(svc.TradeValidationError) as exc:
            svc._resolve_thesis_ref(ref)
        assert "thesis_ref 含有未知字段" in str(exc.value)

    def test_thesis_ref_bool_revision_rejected(self):
        ref = {
            "thesis_id": "th-123",
            "revision_number": True,
        }
        with pytest.raises(svc.TradeValidationError) as exc:
            svc._resolve_thesis_ref(ref)
        assert "revision_number 必须是正整数" in str(exc.value)


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

        # Run trade service operations
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
