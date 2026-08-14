"""P0-DS1 — cap.security.financials runtime evaluator.

复用既有真实财务读取路径（astock.financials，同花顺财务摘要）做 retrieval
probe，但**绝不**把 provider 的「最新报告期」当作 authoritative latest：

- 禁止 local latest == authoritative latest；
- 禁止 implicit report-period applicability；
- DI2 尚无 required report period applicability authority →
  retrieval 成功也只能 NOT_EVALUATED，且 blocker 必须显式为
  ``REPORT_PERIOD_APPLICABILITY_NOT_RESOLVED``（而不是 NO_ADAPTER）；
- provider failure → ERROR；无数据 → UNKNOWN。

dataset 语义对齐 ds_financial_indicator（REPORT_PERIOD / RESTATABLE），
本模块只引用其权威常量做 provenance 声明，不重新实现 dataset 管道。
"""

from __future__ import annotations

import re
from typing import Any, Callable, Mapping

from critical_data_dependency_policy import CAP_SECURITY_FINANCIALS
from financial_indicator_shadow import (
    DATASET_CONTRACT_REVISION,
    DATASET_ID as FINANCIAL_DATASET_ID,
)

DEPENDENCY_ID = CAP_SECURITY_FINANCIALS
ADAPTER_AUTHORITY_REF = "critical_data:financials:v0.1"
REPORT_PERIOD_BLOCKER_REF = (
    "financials:blocker=REPORT_PERIOD_APPLICABILITY_NOT_RESOLVED"
)

_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_UTC_ZERO_OFFSET_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|\+00:00)$"
)


class FinancialsCapabilityError(RuntimeError):
    """capability 评估输入或权威链无效。"""


def _result(state: str, as_of: str, refs: list[str]) -> dict[str, Any]:
    return {
        "dependency_id": DEPENDENCY_ID,
        "state": state,
        "as_of": as_of,
        "authority_refs": list(dict.fromkeys(refs)),
    }


def _require_inputs(security_code: str, campaign_id: str, as_of: str) -> None:
    if type(security_code) is not str \
            or re.fullmatch(r"[0-9]{6}", security_code) is None:
        raise FinancialsCapabilityError(
            "security_code must be six ASCII digits"
        )
    if type(campaign_id) is not str \
            or _CAMPAIGN_ID_RE.fullmatch(campaign_id) is None:
        raise FinancialsCapabilityError("campaign_id is invalid")
    if type(as_of) is not str \
            or _UTC_ZERO_OFFSET_RE.fullmatch(as_of) is None:
        raise FinancialsCapabilityError(
            "as_of must be a canonical UTC instant"
        )


def evaluate_financials_capability(
    *,
    security_code: str,
    campaign_id: str,
    as_of: str,
    financials_reader: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """评估 financials capability（per-security 财务数据 retrieval probe）。

    ``financials_reader(security_code)`` 默认绑定生产读取路径（同花顺财务
    摘要），返回 ``{...}``（含 provider 声称的 period）或 ``{}``；测试注入
    isolated fake。无论 retrieval 成功与否，report-period applicability
    未解决时 capability 恒不为 USABLE。
    """
    _require_inputs(security_code, campaign_id, as_of)
    refs = [
        ADAPTER_AUTHORITY_REF,
        f"dataset-semantics:{FINANCIAL_DATASET_ID}:{DATASET_CONTRACT_REVISION}",
    ]

    if financials_reader is None:
        import astock as astock_module

        def _production_reader(code: str) -> Mapping[str, Any] | None:
            return astock_module.financials(code)

        financials_reader = _production_reader

    try:
        payload = financials_reader(security_code)
    except Exception:
        # provider failure 如实暴露
        return _result("ERROR", as_of, refs)
    if payload is None:
        return _result("UNKNOWN", as_of, refs)
    if not isinstance(payload, Mapping):
        return _result("ERROR", as_of, refs)

    if not payload:
        # 真实检索成功但无数据 → UNKNOWN（数据缺失，非 provider failure）
        return _result("UNKNOWN", as_of, refs)

    # 真实 retrieval 成功：数据存在。但「最新报告期」只是 provider 声称，
    # 不是 applicability authority —— 本 Slice 不伪造 USABLE。
    period = payload.get("period")
    if type(period) is str and period.strip() and period == period.strip():
        refs.append(f"financials:provider-claimed-period={period}")
    refs.append(REPORT_PERIOD_BLOCKER_REF)
    return _result("NOT_EVALUATED", as_of, refs)


__all__ = [
    "ADAPTER_AUTHORITY_REF",
    "DEPENDENCY_ID",
    "FinancialsCapabilityError",
    "REPORT_PERIOD_BLOCKER_REF",
    "evaluate_financials_capability",
]
