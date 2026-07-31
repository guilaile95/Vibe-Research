"""Pydantic contracts for candidate signal screener v0.1.

Strict validation only — no portfolio/watchlist I/O, no trade advice fields.
"""

from __future__ import annotations

import math
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "screener-v0.1"
MAX_CODES = 30
MIN_CODES = 1
MAX_CONDITIONS = 20
MIN_CONDITIONS = 1
_CODE_RE = re.compile(r"^\d{6}$")

# Fixed kline lookback for all evaluations (not client-configurable in v0.1)
SCREENER_KLINE_DAYS = 120


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Conditions (discriminated by id; no free-form params dict)
# ---------------------------------------------------------------------------


class CondPriceGtSma20(_StrictModel):
    id: Literal["price_gt_sma20"]


class CondPriceLtSma20(_StrictModel):
    id: Literal["price_lt_sma20"]


class CondPriceGtSma60(_StrictModel):
    id: Literal["price_gt_sma60"]


class CondPriceLtSma60(_StrictModel):
    id: Literal["price_lt_sma60"]


class CondSma20GtSma60(_StrictModel):
    id: Literal["sma20_gt_sma60"]


class CondSma20LtSma60(_StrictModel):
    id: Literal["sma20_lt_sma60"]


class CondMacdHistPositive(_StrictModel):
    id: Literal["macd_hist_positive"]


class CondMacdHistNegative(_StrictModel):
    id: Literal["macd_hist_negative"]


class CondBreakout20dHigh(_StrictModel):
    id: Literal["breakout_20d_high"]


class CondBreakdown20dLow(_StrictModel):
    id: Literal["breakdown_20d_low"]


def _require_finite(v: float, name: str) -> float:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise ValueError(f"{name} must be a finite number")
    f = float(v)
    if not math.isfinite(f):
        raise ValueError(f"{name} must be a finite number (got NaN/Infinity)")
    return f


class RsiBetweenParams(_StrictModel):
    min: float
    max: float

    @field_validator("min", "max", mode="before")
    @classmethod
    def _finite(cls, v: Any, info) -> float:
        return _require_finite(v, info.field_name)

    @model_validator(mode="after")
    def _order(self) -> RsiBetweenParams:
        if self.min > self.max:
            raise ValueError("rsi_between requires min <= max")
        return self


class CondRsiBetween(_StrictModel):
    id: Literal["rsi_between"]
    params: RsiBetweenParams


class VolumeRatioParams(_StrictModel):
    threshold: float

    @field_validator("threshold", mode="before")
    @classmethod
    def _finite_positive(cls, v: Any) -> float:
        f = _require_finite(v, "threshold")
        if f <= 0:
            raise ValueError("threshold must be > 0")
        return f


class CondVolumeRatioGte(_StrictModel):
    id: Literal["volume_ratio_gte"]
    params: VolumeRatioParams


class CondVolumeRatioLte(_StrictModel):
    id: Literal["volume_ratio_lte"]
    params: VolumeRatioParams


ScreenerCondition = Annotated[
    CondPriceGtSma20
    | CondPriceLtSma20
    | CondPriceGtSma60
    | CondPriceLtSma60
    | CondSma20GtSma60
    | CondSma20LtSma60
    | CondMacdHistPositive
    | CondMacdHistNegative
    | CondBreakout20dHigh
    | CondBreakdown20dLow
    | CondRsiBetween
    | CondVolumeRatioGte
    | CondVolumeRatioLte,
    Field(discriminator="id"),
]


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class ScreenerEvaluateIn(_StrictModel):
    codes: list[str] = Field(..., min_length=MIN_CODES, max_length=MAX_CODES)
    conditions: list[ScreenerCondition] = Field(
        ..., min_length=MIN_CONDITIONS, max_length=MAX_CONDITIONS
    )

    @field_validator("codes")
    @classmethod
    def validate_and_normalize_codes(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("codes must contain at least 1 code")
        if len(v) > MAX_CODES:
            raise ValueError(f"codes must contain at most {MAX_CODES} items")
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in v:
            if not isinstance(raw, str):
                raise ValueError("each code must be a string")
            code = raw.strip()
            if not _CODE_RE.fullmatch(code):
                raise ValueError(f"invalid stock code (must be 6 digits): {raw!r}")
            if code not in seen:
                seen.add(code)
                normalized.append(code)
        if not normalized:
            raise ValueError("codes must contain at least 1 valid code")
        # Deterministic ascending order after dedupe
        normalized.sort()
        return normalized

    @field_validator("conditions")
    @classmethod
    def no_duplicate_condition_ids(cls, v: list[Any]) -> list[Any]:
        ids = [c.id if hasattr(c, "id") else c.get("id") for c in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate condition id is not allowed")
        return v


# ---------------------------------------------------------------------------
# Response models (also used for serialization helpers)
# ---------------------------------------------------------------------------


class ConditionResultOut(_StrictModel):
    id: str
    evaluable: bool
    passed: bool | None
    evidence: dict[str, Any] = Field(default_factory=dict)


class StockResultOut(_StrictModel):
    code: str
    bucket: Literal["matched", "rejected", "unavailable"]
    matched: bool | None
    technical_status: str
    trade_date: str | None
    condition_results: list[ConditionResultOut]
    limitations: list[str] = Field(default_factory=list)


class ScreenerEvaluateOut(_StrictModel):
    status: Literal["normal", "partial", "unavailable"]
    evaluated_at: str
    logic: Literal["AND"] = "AND"
    matched: list[StockResultOut]
    rejected: list[StockResultOut]
    unavailable: list[StockResultOut]
    limitations: list[str] = Field(default_factory=list)
    schema_version: Literal["screener-v0.1"] = SCHEMA_VERSION


# Forbidden top-level / nested keys (asserted in tests)
FORBIDDEN_RESPONSE_KEYS = frozenset(
    {
        "buy",
        "sell",
        "add",
        "reduce",
        "hold",
        "action",
        "score",
        "weight",
        "target_position",
        "expected_return",
        "risk_score",
        "top_risk_note",
    }
)
