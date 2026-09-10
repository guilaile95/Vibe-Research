"""Read-only HTTP surface for Cross-Sectional Factor Validation v0.1."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import factor_validation as fv
import research_data_plane as rdp

router = APIRouter(prefix="/api/signals/factor-validation", tags=["factor-validation"])


class FactorValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor_id: str = Field(min_length=1, max_length=80)
    forward_windows: list[int] = Field(default_factory=lambda: list(fv.FORWARD_WINDOWS), min_length=1, max_length=2)
    date_from: str | None = None
    date_to: str | None = None

    @field_validator("forward_windows")
    @classmethod
    def validate_windows(cls, values: list[int]) -> list[int]:
        normalized = sorted(set(values))
        if normalized != list(fv.FORWARD_WINDOWS):
            raise ValueError("forward_windows must contain exactly 5 and 20")
        return normalized

    @model_validator(mode="after")
    def validate_dates(self):
        for name in ("date_from", "date_to"):
            value = getattr(self, name)
            if value is not None:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError(f"{name} must use YYYY-MM-DD") from exc
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not exceed date_to")
        return self


@router.get("/registry")
def registry():
    return {
        "schema_version": fv.SCHEMA_VERSION,
        "research_only": True,
        "factors": fv.factor_registry(),
        "forward_windows": list(fv.FORWARD_WINDOWS),
        "limitations": list(fv.FACTOR_LIMITATIONS),
    }


@router.post("/evaluate")
def evaluate(body: FactorValidationRequest):
    if body.factor_id not in {item["factor_id"] for item in fv.FACTOR_REGISTRY}:
        raise HTTPException(status_code=422, detail="unknown factor")
    request = body.model_dump()
    try:
        return fv.evaluate_rdp(**request)
    except rdp.ResearchDataPlaneUnavailableError as exc:
        return fv.unavailable_report(body.factor_id, request, str(exc))
    except rdp.ResearchDataPlaneValidationError as exc:
        return fv.unavailable_report(body.factor_id, request, f"Research Runtime 数据校验失败：{exc}")
