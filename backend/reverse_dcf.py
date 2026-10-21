"""Deterministic two-stage FCFF reverse DCF. No fetches, persistence or model calls.

All monetary inputs are entered explicitly; source labels are user declarations,
not verified facts. Annual end-of-period FCFF, constant diluted shares and net debt.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Observation(StrictInput):
    value: float = Field(strict=True, ge=-1e15, le=1e15)
    unit: Literal["currency_per_share", "currency", "million_currency", "shares", "million_shares"]
    currency: Literal["CNY", "HKD", "USD", "NONE"]
    source: str = Field(min_length=1, max_length=300)
    as_of: date

    @field_validator("source")
    @classmethod
    def source_nonblank(cls, value):
        if not value.strip():
            raise ValueError("source must identify the entered observation")
        return value.strip()

    def normalized(self):
        return self.value * (1e6 if self.unit.startswith("million_") else 1)


class Assumptions(StrictInput):
    wacc: float = Field(strict=True, gt=0, le=1)
    terminal_growth: float = Field(strict=True, gt=-1, le=.2)
    years: int = Field(strict=True, ge=1, le=30)
    growth_lower: float = Field(strict=True, gt=-1, le=1)
    growth_upper: float = Field(strict=True, gt=-1, le=3)
    sensitivity_wacc: list[float] = Field(min_length=1, max_length=9)
    rationale: str = Field(min_length=1, max_length=1000)

    @field_validator("sensitivity_wacc", mode="before")
    @classmethod
    def finite_rates(cls, value):
        if not isinstance(value, list) or any(type(x) not in (float, int) or not math.isfinite(x) or not 0 < x <= 1 for x in value):
            raise ValueError("sensitivity WACC must contain finite rates in (0,1]")
        return value

    @model_validator(mode="after")
    def economics(self):
        if self.wacc <= self.terminal_growth or any(x <= self.terminal_growth for x in self.sensitivity_wacc):
            raise ValueError("WACC must exceed terminal growth in every scenario")
        if min([self.wacc, *self.sensitivity_wacc]) - self.terminal_growth < 1e-8:
            raise ValueError("WACC minus terminal growth must be at least 1e-8 for numerical stability")
        if self.growth_lower >= self.growth_upper or not self.rationale.strip():
            raise ValueError("ordered growth bounds and an assumption rationale are required")
        return self


class ReverseDcfInput(StrictInput):
    market: Literal["A", "HK", "US"]
    symbol: str = Field(min_length=1, max_length=15, pattern=r"^[A-Za-z0-9.\-]+$")
    industry: Literal["non_financial", "financial", "unknown"]
    industry_source: str = Field(min_length=1, max_length=300)
    fcf_basis: Literal["annual_unlevered_fcff", "unknown"]
    price: Observation
    fcff: Observation
    net_debt: Observation
    shares: Observation
    assumptions: Assumptions

    @model_validator(mode="after")
    def compatible(self):
        if not self.industry_source.strip():
            raise ValueError("industry source required")
        if self.price.unit != "currency_per_share" or self.fcff.unit not in ("currency", "million_currency") or self.net_debt.unit not in ("currency", "million_currency") or self.shares.unit not in ("shares", "million_shares"):
            raise ValueError("incompatible input units")
        if self.price.currency == "NONE" or len({self.price.currency, self.fcff.currency, self.net_debt.currency}) != 1 or self.shares.currency != "NONE":
            raise ValueError("currency mismatch; FX conversion is not performed")
        if self.price.value <= 0 or self.shares.value <= 0:
            raise ValueError("positive price and diluted share count required")
        return self


def enterprise_value(fcff: float, growth: float, wacc: float, terminal_growth: float, years: int) -> float:
    """Present value, without rounding intermediate cash flows."""
    ratio = (1 + growth) / (1 + wacc)
    return fcff * (sum(ratio ** year for year in range(1, years + 1)) + ratio ** years * (1 + terminal_growth) / (wacc - terminal_growth))


def solve_growth(fcff, target_ev, wacc, terminal_growth, years, lower, upper):
    low_value = enterprise_value(fcff, lower, wacc, terminal_growth, years)
    high_value = enterprise_value(fcff, upper, wacc, terminal_growth, years)
    if target_ev < low_value or target_ev > high_value:
        return {"status": "NO_ROOT", "implied_growth": None, "residual_ev": None}
    for _ in range(100):
        mid = (lower + upper) / 2
        value = enterprise_value(fcff, mid, wacc, terminal_growth, years)
        if value < target_ev:
            lower = mid
        else:
            upper = mid
    growth = (lower + upper) / 2
    return {"status": "SOLVED", "implied_growth": growth, "residual_ev": enterprise_value(fcff, growth, wacc, terminal_growth, years) - target_ev}


def calculate(body: ReverseDcfInput, *, today: date | None = None):
    today = today or datetime.now(timezone.utc).date()
    result = {"schema_version": "reverse-dcf.v1", "classification": "MODEL_IMPLIED_NOT_FORECAST", "input_verification": "USER_ENTERED_UNVERIFIED", "evaluated_on": today.isoformat(), "inputs": body.model_dump(mode="json"), "status": "UNKNOWN", "reason_codes": [], "implied_growth": None, "residual_ev": None, "sensitivity": []}
    reasons = result["reason_codes"]
    if body.industry == "financial": reasons.append("FINANCIAL_FIRM_INAPPLICABLE")
    if body.industry == "unknown": reasons.append("INDUSTRY_UNKNOWN")
    if body.fcf_basis != "annual_unlevered_fcff": reasons.append("FCFF_BASIS_UNKNOWN")
    if body.fcff.value <= 0: reasons.append("NONPOSITIVE_FCFF_INAPPLICABLE")
    for name, max_days in (("price", 7), ("fcff", 550), ("net_debt", 180), ("shares", 180)):
        age = (today - getattr(body, name).as_of).days
        if age < 0: reasons.append(f"{name.upper()}_FUTURE")
        elif age > max_days: reasons.append(f"{name.upper()}_STALE")
    target = body.price.value * body.shares.normalized() + body.net_debt.normalized()
    if target <= 0: reasons.append("NONPOSITIVE_ENTERPRISE_VALUE_INAPPLICABLE")
    if reasons:
        result["status"] = "INAPPLICABLE" if any(x.endswith("INAPPLICABLE") for x in reasons) else "UNKNOWN"
        return result
    a = body.assumptions
    def solve(wacc):
        return solve_growth(body.fcff.normalized(), target, wacc, a.terminal_growth, a.years, a.growth_lower, a.growth_upper)
    result.update(solve(a.wacc))
    result["target_enterprise_value"] = target
    result["sensitivity"] = [{"wacc": wacc, **solve(wacc)} for wacc in a.sensitivity_wacc]
    return result
