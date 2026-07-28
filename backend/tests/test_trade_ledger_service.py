"""Tests for trade_ledger_service validation and computed fields."""
from __future__ import annotations

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
        }
        data.update(overrides)
        return data

    def test_full_buy_valid(self):
        record = svc.validate_and_build_record(self._base_input())
        assert record["execution_status"] == "full"
        assert record["actual_price"] == 1500.0
        assert record["actual_quantity"] == 100
        assert record["trade_id"] is not None

    def test_full_sell_valid(self):
        record = svc.validate_and_build_record(
            self._base_input(operation="sell")
        )
        assert record["operation"] == "sell"

    def test_partial_valid(self):
        record = svc.validate_and_build_record(
            self._base_input(
                execution_status="partial",
                planned_quantity=200,
                actual_quantity=100,
                unexecuted_reason="价格未到位",
            )
        )
        assert record["execution_status"] == "partial"

    def test_not_executed_valid(self):
        record = svc.validate_and_build_record(
            self._base_input(
                execution_status="not_executed",
                unexecuted_reason="取消",
            )
        )
        assert record["actual_price"] is None
        assert record["actual_quantity"] == 0
        assert record["executed_at"] is None
        assert record["fee"] == 0.0
        assert record["other_cost"] == 0.0

    def test_invalid_code_format(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(code="60051"))

    def test_invalid_code_letters(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(code="ABCDEF"))

    def test_invalid_operation(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(operation="hold"))

    def test_invalid_status(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(execution_status="done"))

    def test_unknown_field_rejected(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(extra_field="x"))

    def test_full_requires_actual_price(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(actual_price=None))

    def test_full_requires_actual_quantity_positive(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(actual_quantity=0))

    def test_full_quantity_mismatch(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(planned_quantity=200))

    def test_full_rejects_unexecuted_reason(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(unexecuted_reason="不应该有"))

    def test_partial_requires_planned_quantity(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(
                self._base_input(execution_status="partial", actual_quantity=50,
                unexecuted_reason="x")
            )

    def test_partial_requires_reason(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(
                self._base_input(
                    execution_status="partial",
                    planned_quantity=200,
                    actual_quantity=100,
                )
            )

    def test_partial_quantity_bounds(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(
                self._base_input(
                    execution_status="partial",
                    planned_quantity=100,
                    actual_quantity=100,
                    unexecuted_reason="x",
                )
            )

    def test_not_executed_requires_reason(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(
                self._base_input(execution_status="not_executed")
            )

    def test_not_executed_clears_actual_price(self):
        record = svc.validate_and_build_record(
            self._base_input(
                execution_status="not_executed",
                actual_price=100.0,
                unexecuted_reason="取消",
            )
        )
        assert record["actual_price"] is None

    def test_not_executed_zeroes_fees(self):
        record = svc.validate_and_build_record(
            self._base_input(
                execution_status="not_executed",
                fee=50.0,
                other_cost=10.0,
                unexecuted_reason="取消",
            )
        )
        assert record["fee"] == 0.0
        assert record["other_cost"] == 0.0

    def test_negative_fee_rejected(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(fee=-1))

    def test_negative_other_cost_rejected(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(other_cost=-1))

    def test_price_must_be_positive(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(actual_price=0))

    def test_quantity_must_be_integer(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(actual_quantity=1.5))

    def test_quantity_rejects_bool(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(actual_quantity=True))

    def test_strict_number_types(self):
        with pytest.raises(svc.TradeValidationError):
            svc.validate_and_build_record(self._base_input(actual_price="1500"))


class TestComputedFields:
    def test_buy_cash_flow(self):
        record = {
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 100.0,
            "actual_quantity": 100,
            "fee": 5.0,
            "other_cost": 0.0,
            "planned_price": None,
            "planned_quantity": None,
        }
        result = svc.compute_fields(record)
        assert result["gross_amount"] == 10000.0
        assert result["total_cost"] == 10005.0
        assert result["net_cash_flow"] == -10005.0

    def test_sell_cash_flow(self):
        record = {
            "operation": "sell",
            "execution_status": "full",
            "actual_price": 120.0,
            "actual_quantity": 100,
            "fee": 5.0,
            "other_cost": 1.0,
            "planned_price": None,
            "planned_quantity": None,
        }
        result = svc.compute_fields(record)
        assert result["gross_amount"] == 12000.0
        assert result["total_cost"] == 11994.0
        assert result["net_cash_flow"] == 11994.0

    def test_not_executed_cash_flow_zero(self):
        record = {
            "operation": "buy",
            "execution_status": "not_executed",
            "actual_price": None,
            "actual_quantity": 0,
            "fee": 0.0,
            "other_cost": 0.0,
            "planned_price": None,
            "planned_quantity": None,
        }
        result = svc.compute_fields(record)
        assert result["gross_amount"] == 0.0
        assert result["net_cash_flow"] == 0.0

    def test_price_variance(self):
        record = {
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 105.0,
            "actual_quantity": 100,
            "fee": 0.0,
            "other_cost": 0.0,
            "planned_price": 100.0,
            "planned_quantity": 100,
        }
        result = svc.compute_fields(record)
        assert result["price_variance"] == 5.0
        assert result["price_variance_pct"] == 5.0

    def test_quantity_completion(self):
        record = {
            "operation": "buy",
            "execution_status": "partial",
            "actual_price": 100.0,
            "actual_quantity": 50,
            "fee": 0.0,
            "other_cost": 0.0,
            "planned_price": 100.0,
            "planned_quantity": 200,
        }
        result = svc.compute_fields(record)
        assert result["quantity_completion_pct"] == 25.0

    def test_no_variance_for_not_executed(self):
        record = {
            "operation": "buy",
            "execution_status": "not_executed",
            "actual_price": None,
            "actual_quantity": 0,
            "fee": 0.0,
            "other_cost": 0.0,
            "planned_price": 100.0,
            "planned_quantity": 100,
        }
        result = svc.compute_fields(record)
        assert result["price_variance"] is None
        assert result["quantity_completion_pct"] is None
