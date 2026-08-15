"""P0-HR1 shared Hard Risk runtime contract v0.1.

This module freezes only the cross-lane wire contract.  It does not decide
which facts constitute Hard Risk, does not read I/O, and does not generate an
investment action.

Safety semantics:
- CLEAR and CONFIRMED are positive-proof states and therefore require an
  EVALUATED result plus at least one authority reference.
- UNKNOWN is distinct from NOT_EVALUATED and may also represent an evaluator
  ERROR; downstream RA1 keeps that ERROR distinct.
- NOT_EVALUATED is never treated as CLEAR.
- Hard Risk narrows the deterministic Action Envelope elsewhere; this contract
  never emits BUY/SELL/EXIT or allows AI to override a confirmed result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

SCHEMA_VERSION = "hard_risk_runtime.v0.1"
POLICY_VERSION_V01 = "hard_risk_policy.v0.1"

HARD_RISK_STATES: tuple[str, ...] = (
    "CLEAR",
    "CONFIRMED",
    "UNKNOWN",
    "NOT_EVALUATED",
)
EVALUATION_STATES: tuple[str, ...] = (
    "EVALUATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)
VALID_STRATEGIES: tuple[str, ...] = ("SHORT", "SWING", "MEDIUM")

LEGAL_STATE_EVALUATION_PAIRS = frozenset(
    {
        ("CLEAR", "EVALUATED"),
        ("CONFIRMED", "EVALUATED"),
        ("UNKNOWN", "UNKNOWN"),
        ("UNKNOWN", "ERROR"),
        ("NOT_EVALUATED", "NOT_EVALUATED"),
    }
)

_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")


class HardRiskContractError(ValueError):
    """The normalized Hard Risk result violates the shared HR1 contract."""


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise HardRiskContractError(f"{field} must be a non-empty trimmed string")
    return value


def _utc_zero_offset(value: object) -> str:
    text = _nonempty(value, "as_of")
    if not (text.endswith("Z") or text.endswith("+00:00")):
        raise HardRiskContractError("as_of must use explicit UTC zero offset")
    parse_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(parse_text)
    except ValueError as exc:
        raise HardRiskContractError("as_of must be a valid UTC instant") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HardRiskContractError("as_of must be timezone-aware UTC")
    if parsed.utcoffset().total_seconds() != 0:
        raise HardRiskContractError("as_of must use UTC zero offset")
    return text


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise HardRiskContractError(f"{field} must be a list/tuple of strings")
    items = tuple(_nonempty(item, f"{field}[]") for item in value)
    if len(items) != len(set(items)):
        raise HardRiskContractError(f"{field} must not contain duplicates")
    return items


@dataclass(frozen=True)
class HardRiskEvaluation:
    """Normalized result consumed by HR1 integration/UI/E2E lanes."""

    security_code: str
    strategy: str
    campaign_id: str
    as_of: str
    hard_risk_state: str
    hard_risk_evaluation: str
    reason_codes: tuple[str, ...]
    authority_refs: tuple[str, ...]
    policy_version: str = POLICY_VERSION_V01
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.security_code, str) or _SECURITY_CODE_RE.fullmatch(self.security_code) is None:
            raise HardRiskContractError("security_code must be exactly 6 digits")
        if self.strategy not in VALID_STRATEGIES:
            raise HardRiskContractError(f"strategy must be one of {VALID_STRATEGIES}")
        if not isinstance(self.campaign_id, str) or _CAMPAIGN_ID_RE.fullmatch(self.campaign_id) is None:
            raise HardRiskContractError("campaign_id must match campaign_<32 lowercase hex>")
        object.__setattr__(self, "as_of", _utc_zero_offset(self.as_of))
        if self.hard_risk_state not in HARD_RISK_STATES:
            raise HardRiskContractError(f"hard_risk_state must be one of {HARD_RISK_STATES}")
        if self.hard_risk_evaluation not in EVALUATION_STATES:
            raise HardRiskContractError(f"hard_risk_evaluation must be one of {EVALUATION_STATES}")
        pair = (self.hard_risk_state, self.hard_risk_evaluation)
        if pair not in LEGAL_STATE_EVALUATION_PAIRS:
            raise HardRiskContractError(f"illegal Hard Risk state/evaluation pair: {pair}")
        reasons = _string_tuple(self.reason_codes, "reason_codes")
        refs = _string_tuple(self.authority_refs, "authority_refs")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "authority_refs", refs)
        if self.hard_risk_state != "CLEAR" and not reasons:
            raise HardRiskContractError("non-CLEAR Hard Risk results require reason_codes")
        if self.hard_risk_evaluation == "EVALUATED" and not refs:
            raise HardRiskContractError("EVALUATED Hard Risk results require positive authority_refs")
        if self.policy_version != POLICY_VERSION_V01:
            raise HardRiskContractError("unsupported hard_risk policy_version")
        if self.schema_version != SCHEMA_VERSION:
            raise HardRiskContractError("unsupported hard_risk schema_version")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "security_code": self.security_code,
            "strategy": self.strategy,
            "campaign_id": self.campaign_id,
            "as_of": self.as_of,
            "hard_risk_state": self.hard_risk_state,
            "hard_risk_evaluation": self.hard_risk_evaluation,
            "reason_codes": list(self.reason_codes),
            "authority_refs": list(self.authority_refs),
        }


def hard_risk_evaluation_from_mapping(record: Mapping[str, Any]) -> HardRiskEvaluation:
    if not isinstance(record, Mapping):
        raise HardRiskContractError("record must be a Mapping")
    expected = {
        "schema_version",
        "policy_version",
        "security_code",
        "strategy",
        "campaign_id",
        "as_of",
        "hard_risk_state",
        "hard_risk_evaluation",
        "reason_codes",
        "authority_refs",
    }
    if set(record) != expected:
        raise HardRiskContractError(f"record fields must exactly equal {sorted(expected)}")
    return HardRiskEvaluation(**dict(record))


__all__ = [
    "EVALUATION_STATES",
    "HARD_RISK_STATES",
    "HardRiskContractError",
    "HardRiskEvaluation",
    "LEGAL_STATE_EVALUATION_PAIRS",
    "POLICY_VERSION_V01",
    "SCHEMA_VERSION",
    "VALID_STRATEGIES",
    "hard_risk_evaluation_from_mapping",
]
