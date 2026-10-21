"""Read-only HTTP surface for Historical Signal Validation v0.1."""
from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import historical_signal_validation as hsv
import research_data_plane as rdp
import experiment_ledger

router = APIRouter(prefix="/api/signals/validation", tags=["historical-signal-validation"])
_CODE_RE = re.compile(r"^\d{6}$")


class HistoricalSignalValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_id: str = Field(min_length=1, max_length=80)
    codes: list[str] = Field(min_length=1, max_length=100)
    benchmark_code: str | None = None
    date_from: str | None = None
    date_to: str | None = None

    @field_validator("codes")
    @classmethod
    def normalize_codes(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in values:
            code = str(raw).strip()
            if not _CODE_RE.fullmatch(code):
                raise ValueError("codes must contain six-digit A-share codes")
            if code not in normalized:
                normalized.append(code)
        if not normalized:
            raise ValueError("codes must not be empty")
        return normalized

    @field_validator("benchmark_code")
    @classmethod
    def normalize_benchmark(cls, value: str | None) -> str | None:
        if value is None:
            return None
        code = value.strip()
        if not _CODE_RE.fullmatch(code):
            raise ValueError("benchmark_code must be a six-digit A-share code")
        return code

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
        "schema_version": hsv.SCHEMA_VERSION,
        "research_only": True,
        "signals": hsv.signal_registry(),
        "limitations": list(hsv.LIMITATIONS),
    }


def _evaluate(body: HistoricalSignalValidationRequest):
    if body.signal_id not in {item["id"] for item in hsv.SIGNAL_REGISTRY}:
        raise HTTPException(status_code=422, detail="unknown historical validation signal")
    request = body.model_dump()
    try:
        return hsv.evaluate_rdp(**request)
    except rdp.ResearchDataPlaneUnavailableError as exc:
        return hsv.unavailable_report(body.signal_id, request, str(exc))
    except rdp.ResearchDataPlaneValidationError as exc:
        return hsv.unavailable_report(body.signal_id, request, f"Research Runtime 数据校验失败：{exc}")


@router.post("/evaluate")
def evaluate(body: HistoricalSignalValidationRequest, record_id: str | None = None):
    try:
        return experiment_ledger.execute(record_id, 'signal', body.model_dump(), lambda: _evaluate(body))
    except (ValueError, LookupError, experiment_ledger.store.StoreError):
        raise HTTPException(status_code=422, detail="实验记录与请求不匹配") from None


# Shares the same local-only read plane and existing experiment lifecycle.
import rolling_signal_validation as rolling


@router.post('/rolling')
def evaluate_rolling(body: rolling.RollingSignalValidationRequest, record_id: str | None = None):
    def cancelled():
        if record_id is None:
            return False
        with experiment_ledger.store.read() as conn:
            return experiment_ledger._find(conn, record_id)['status'] == 'CANCELLED'

    def calculate():
        try:
            return rolling.evaluate_rdp(body, cancelled)
        except (rdp.ResearchDataPlaneUnavailableError, rdp.ResearchDataPlaneValidationError):
            report = rolling.evaluate_series(body, {}, None, None)
            report['status'] = 'unavailable'
            report['limitations'].insert(0, 'Research Runtime 数据不可用或未通过快照校验；没有计算结果')
            return report
    try:
        return experiment_ledger.execute(record_id, 'rolling-signal', body.model_dump(), calculate)
    except (ValueError, LookupError, experiment_ledger.store.StoreError):
        raise HTTPException(status_code=422, detail='滚动验证输入、工作上限或实验记录不匹配') from None
