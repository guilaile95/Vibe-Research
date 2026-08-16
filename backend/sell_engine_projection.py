"""Sell Engine vNext domain composition for P0-DC1.

The useful #107 state and reason vocabulary is retained, but its generic
``Mapping(state=WATCH|REDUCE|EXIT)`` input surface is intentionally gone.  A
sell pressure can enter this projection only through a distinct, named
authority-adapter type (for example ``ExpectationPriceInAuthority``).  The
types are contracts for already-authoritative upstream adapters; this module
does not manufacture those facts from PnL, price, technical text, or AI.

The currently implemented product authorities are Current Thesis, HR1 Hard
Risk, and DC1 Material Change.  The seven legacy sell dimensions remain
explicitly named adapter slots so O/Z/G can wire a real producer later.  A
missing slot is ``NOT_EVALUATED`` and cannot create a positive HOLD proof.

Pure-domain boundary: no I/O, provider, database, network, AI, randomness, or
wall clock.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar, Mapping

from hard_risk_contract import HardRiskEvaluation
from material_change_projection import (
    AUTHORITY_REF as MATERIAL_CHANGE_AUTHORITY_REF,
    CurrentThesisAuthority,
    MaterialChangeProjection,
)


SCHEMA_VERSION = "sell_engine.projection.vnext.v0.1"
AUTHORITY_REF = "sell_engine:projection:vnext.v0.1"

SELL_STATES: tuple[str, ...] = (
    "HOLD",
    "WATCH_TO_REDUCE",
    "REDUCE",
    "EXIT",
    "THESIS_INVALIDATED",
)
SELL_EVALUATIONS: tuple[str, ...] = (
    "EVALUATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)
REASON_CATEGORIES: tuple[str, ...] = (
    "THESIS_INVALIDATION",
    "RISK_EXIT",
    "EXPECTATION_PRICE_IN",
    "RISK_REWARD_DETERIORATION",
    "CATALYST_FAILURE",
    "PORTFOLIO_REBALANCE",
    "OPPORTUNITY_COST",
    "TECHNICAL_EXECUTION",
)

PRESSURE_STATES: tuple[str, ...] = (
    "NONE",
    "WATCH",
    "REDUCE",
    "EXIT",
    "UNKNOWN",
    "NOT_EVALUATED",
    "NOT_APPLICABLE",
    "NOT_YET",
)
EVALUATION_STATES: tuple[str, ...] = (
    "EVALUATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)
VALID_STRATEGIES = ("SHORT", "SWING", "MEDIUM")
THESIS_STATES = (
    "STRENGTHENED",
    "STABLE",
    "WEAKENED",
    "DISPROVEN",
    "INVALIDATED",
    "UNKNOWN",
)

_STATE_RANK = {
    "HOLD": 0,
    "WATCH_TO_REDUCE": 1,
    "REDUCE": 2,
    "EXIT": 3,
    "THESIS_INVALIDATED": 4,
}
_EVALUATION_RANK = {
    "EVALUATED": 0,
    "UNKNOWN": 1,
    "NOT_EVALUATED": 2,
    "ERROR": 3,
}
_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_THESIS_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_AS_OF_UTC_FORMS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}\+00:00$"),
)


class SellEngineError(ValueError):
    """Base Sell Engine contract error."""


class SellEngineValidationError(SellEngineError):
    """Malformed or mismatched named authority input."""


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise SellEngineValidationError(
            f"{field} must be a non-empty trimmed string"
        )
    return value


def _require_security_code(value: object) -> str:
    text = _require_text(value, "security_code")
    if _SECURITY_CODE_RE.fullmatch(text) is None:
        raise SellEngineValidationError("security_code must be exactly 6 digits")
    return text


def _require_strategy(value: object) -> str:
    text = _require_text(value, "strategy")
    if text not in VALID_STRATEGIES:
        raise SellEngineValidationError(
            f"strategy must be one of {VALID_STRATEGIES}, got {text!r}"
        )
    return text


def _require_campaign_id(value: object) -> str:
    text = _require_text(value, "campaign_id")
    if _CAMPAIGN_ID_RE.fullmatch(text) is None:
        raise SellEngineValidationError(
            "campaign_id must match campaign_<32 lowercase hex>"
        )
    return text


def _parse_utc(value: object, field: str) -> tuple[str, datetime]:
    text = _require_text(value, field)
    if not any(pattern.fullmatch(text) for pattern in _AS_OF_UTC_FORMS):
        raise SellEngineValidationError(
            f"{field} must be an explicit UTC zero-offset instant"
        )
    parse_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(parse_text)
    except ValueError as exc:
        raise SellEngineValidationError(f"{field} is not a valid UTC instant") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SellEngineValidationError(f"{field} must be timezone-aware UTC")
    if parsed.utcoffset().total_seconds() != 0:
        raise SellEngineValidationError(f"{field} must use UTC zero offset")
    return text, parsed.astimezone(timezone.utc)


def _ordered_refs(value: tuple[str, ...] | list[str], *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise SellEngineValidationError("authority_refs must be a tuple/list")
    if not value and not allow_empty:
        raise SellEngineValidationError("evaluated authority requires authority_refs")
    refs = []
    for index, item in enumerate(value):
        refs.append(_require_text(item, f"authority_refs[{index}]"))
    if len(refs) != len(set(refs)):
        raise SellEngineValidationError("authority_refs must not contain duplicates")
    return tuple(sorted(refs))


@dataclass(frozen=True)
class _NamedPressureAuthority:
    """Private common validation for distinct public source adapter types."""

    state: str
    evaluation: str = "EVALUATED"
    authority_refs: tuple[str, ...] = ()
    source_name: ClassVar[str] = "named_pressure_authority"

    def __post_init__(self) -> None:
        if self.state not in PRESSURE_STATES:
            raise SellEngineValidationError(
                f"{self.source_name}.state must be one of {PRESSURE_STATES}"
            )
        if self.evaluation not in EVALUATION_STATES:
            raise SellEngineValidationError(
                f"{self.source_name}.evaluation must be one of {EVALUATION_STATES}"
            )
        legal = {
            "EVALUATED": {"NONE", "WATCH", "REDUCE", "EXIT", "NOT_APPLICABLE", "NOT_YET"},
            "UNKNOWN": {"UNKNOWN"},
            "NOT_EVALUATED": {"NOT_EVALUATED"},
            "ERROR": {"UNKNOWN"},
        }
        if self.state not in legal[self.evaluation]:
            raise SellEngineValidationError(
                f"{self.source_name} has illegal state/evaluation pair"
            )
        object.__setattr__(
            self,
            "authority_refs",
            _ordered_refs(self.authority_refs, allow_empty=self.evaluation != "EVALUATED"),
        )


@dataclass(frozen=True)
class RiskExitAuthority(_NamedPressureAuthority):
    source_name: ClassVar[str] = "risk_exit_authority"


@dataclass(frozen=True)
class ExpectationPriceInAuthority(_NamedPressureAuthority):
    source_name: ClassVar[str] = "expectation_price_in_authority"


@dataclass(frozen=True)
class RiskRewardAuthority(_NamedPressureAuthority):
    source_name: ClassVar[str] = "risk_reward_authority"


@dataclass(frozen=True)
class CatalystAuthority(_NamedPressureAuthority):
    source_name: ClassVar[str] = "catalyst_authority"


@dataclass(frozen=True)
class PortfolioRebalanceAuthority(_NamedPressureAuthority):
    source_name: ClassVar[str] = "portfolio_rebalance_authority"


@dataclass(frozen=True)
class OpportunityCostAuthority(_NamedPressureAuthority):
    source_name: ClassVar[str] = "opportunity_cost_authority"


@dataclass(frozen=True)
class TechnicalExecutionAuthority(_NamedPressureAuthority):
    source_name: ClassVar[str] = "technical_execution_authority"


@dataclass(frozen=True)
class SellEngineProjection:
    """Detached Sell Engine result consumed by the Proposal layer."""

    schema_version: str
    authority_ref: str
    security_code: str
    strategy: str
    campaign_id: str
    as_of: str
    sell_state: str | None
    sell_evaluation: str
    primary_reason: str | None
    reason_codes: tuple[str, ...]
    supporting_reasons: tuple[str, ...]
    opposing_reasons: tuple[str, ...]
    uncertainties: tuple[str, ...]
    hold_positive_proof: bool
    review_pressure: bool
    thesis_id: str | None
    thesis_revision: int | None
    authority_refs: tuple[str, ...]
    dimensions: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise SellEngineValidationError("unsupported Sell Engine schema")
        if self.authority_ref != AUTHORITY_REF:
            raise SellEngineValidationError("invalid Sell Engine authority_ref")
        _require_security_code(self.security_code)
        _require_strategy(self.strategy)
        _require_campaign_id(self.campaign_id)
        _parse_utc(self.as_of, "as_of")
        if self.sell_state is not None and self.sell_state not in SELL_STATES:
            raise SellEngineValidationError("invalid sell_state")
        if self.sell_evaluation not in SELL_EVALUATIONS:
            raise SellEngineValidationError("invalid sell_evaluation")
        if self.sell_state == "HOLD" and not self.hold_positive_proof:
            raise SellEngineValidationError("HOLD requires hold_positive_proof")
        if type(self.hold_positive_proof) is not bool or type(self.review_pressure) is not bool:
            raise SellEngineValidationError("Sell Engine proof flags must be bool")
        if self.primary_reason is not None and self.primary_reason not in REASON_CATEGORIES:
            raise SellEngineValidationError("invalid primary_reason")
        if self.thesis_id is not None and _THESIS_ID_RE.fullmatch(self.thesis_id) is None:
            raise SellEngineValidationError("thesis_id must be 32 lowercase hex")
        if self.thesis_revision is not None and (
            not isinstance(self.thesis_revision, int)
            or isinstance(self.thesis_revision, bool)
            or self.thesis_revision < 1
        ):
            raise SellEngineValidationError("thesis_revision must be a positive integer")
        object.__setattr__(self, "reason_codes", _ordered_refs(self.reason_codes, allow_empty=True))
        object.__setattr__(self, "supporting_reasons", _ordered_refs(self.supporting_reasons, allow_empty=True))
        object.__setattr__(self, "opposing_reasons", _ordered_refs(self.opposing_reasons, allow_empty=True))
        object.__setattr__(self, "uncertainties", _ordered_refs(self.uncertainties, allow_empty=True))
        object.__setattr__(self, "authority_refs", _ordered_refs(self.authority_refs))
        if not isinstance(self.dimensions, Mapping):
            raise SellEngineValidationError("dimensions must be a Mapping")
        object.__setattr__(self, "dimensions", copy.deepcopy(dict(self.dimensions)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authority_ref": self.authority_ref,
            "security_code": self.security_code,
            "strategy": self.strategy,
            "campaign_id": self.campaign_id,
            "as_of": self.as_of,
            "sell_state": self.sell_state,
            "sell_evaluation": self.sell_evaluation,
            "primary_reason": self.primary_reason,
            "reason_codes": list(self.reason_codes),
            "supporting_reasons": list(self.supporting_reasons),
            "opposing_reasons": list(self.opposing_reasons),
            "uncertainties": list(self.uncertainties),
            "hold_positive_proof": self.hold_positive_proof,
            "review_pressure": self.review_pressure,
            "thesis_id": self.thesis_id,
            "thesis_revision": self.thesis_revision,
            "authority_refs": list(self.authority_refs),
            "dimensions": copy.deepcopy(dict(self.dimensions)),
        }


def sell_engine_projection_from_mapping(value: Mapping[str, Any]) -> SellEngineProjection:
    if not isinstance(value, Mapping):
        raise SellEngineValidationError("Sell Engine result must be a Mapping")
    expected = {
        "schema_version",
        "authority_ref",
        "security_code",
        "strategy",
        "campaign_id",
        "as_of",
        "sell_state",
        "sell_evaluation",
        "primary_reason",
        "reason_codes",
        "supporting_reasons",
        "opposing_reasons",
        "uncertainties",
        "hold_positive_proof",
        "review_pressure",
        "thesis_id",
        "thesis_revision",
        "authority_refs",
        "dimensions",
    }
    if set(value) != expected:
        raise SellEngineValidationError(
            f"Sell Engine result fields must exactly equal {sorted(expected)}"
        )
    return SellEngineProjection(
        schema_version=value["schema_version"],
        authority_ref=value["authority_ref"],
        security_code=value["security_code"],
        strategy=value["strategy"],
        campaign_id=value["campaign_id"],
        as_of=value["as_of"],
        sell_state=value["sell_state"],
        sell_evaluation=value["sell_evaluation"],
        primary_reason=value["primary_reason"],
        reason_codes=tuple(value["reason_codes"]),
        supporting_reasons=tuple(value["supporting_reasons"]),
        opposing_reasons=tuple(value["opposing_reasons"]),
        uncertainties=tuple(value["uncertainties"]),
        hold_positive_proof=value["hold_positive_proof"],
        review_pressure=value["review_pressure"],
        thesis_id=value["thesis_id"],
        thesis_revision=value["thesis_revision"],
        authority_refs=tuple(value["authority_refs"]),
        dimensions=value["dimensions"],
    )


def _max_evaluation(current: str, candidate: str) -> str:
    return candidate if _EVALUATION_RANK[candidate] > _EVALUATION_RANK[current] else current


def _pressure_to_sell_state(state: str) -> str | None:
    return {
        "WATCH": "WATCH_TO_REDUCE",
        "REDUCE": "REDUCE",
        "EXIT": "EXIT",
    }.get(state)


def _max_sell_state(current: str | None, candidate: str | None) -> str | None:
    if current is None:
        return candidate
    if candidate is None:
        return current
    return candidate if _STATE_RANK[candidate] > _STATE_RANK[current] else current


def _named_pressure_dimension(
    value: _NamedPressureAuthority | None,
    *,
    field_name: str,
    category: str,
) -> dict[str, Any]:
    if value is None:
        return {
            "source_contract": f"{field_name}_authority",
            "input_state": "NOT_EVALUATED",
            "pressure_state": None,
            "category": None,
            "evaluation": "NOT_EVALUATED",
            "applicable": True,
            "hold_ok": False,
            "reason_codes": [f"{field_name.upper()}_NOT_EVALUATED"],
            "authority_refs": [],
        }
    pressure = _pressure_to_sell_state(value.state)
    if value.evaluation != "EVALUATED":
        return {
            "source_contract": value.source_name,
            "input_state": value.state,
            "pressure_state": None,
            "category": None,
            "evaluation": value.evaluation,
            "applicable": True,
            "hold_ok": False,
            "reason_codes": [f"{field_name.upper()}_{value.evaluation}"],
            "authority_refs": list(value.authority_refs),
        }
    if value.state in {"NONE", "NOT_APPLICABLE", "NOT_YET"}:
        return {
            "source_contract": value.source_name,
            "input_state": value.state,
            "pressure_state": None,
            "category": None,
            "evaluation": "EVALUATED",
            "applicable": value.state not in {"NOT_APPLICABLE"},
            "hold_ok": True,
            "reason_codes": [f"{field_name.upper()}_{value.state}"],
            "authority_refs": list(value.authority_refs),
        }
    return {
        "source_contract": value.source_name,
        "input_state": value.state,
        "pressure_state": pressure,
        "category": category,
        "evaluation": "EVALUATED",
        "applicable": True,
        "hold_ok": False,
        "reason_codes": [f"{field_name.upper()}_{value.state}"],
        "authority_refs": list(value.authority_refs),
    }


def _thesis_dimension(
    value: CurrentThesisAuthority | None,
) -> tuple[dict[str, Any], str | None, int | None]:
    if value is None:
        return (
            {
                "source_contract": "formal_current_thesis.projection.v0.1",
                "input_state": "NOT_EVALUATED",
                "pressure_state": None,
                "category": None,
                "evaluation": "NOT_EVALUATED",
                "applicable": True,
                "hold_ok": False,
                "reason_codes": ["THESIS_NOT_EVALUATED"],
                "authority_refs": [],
            },
            None,
            None,
        )
    projection = dict(value.projection)
    if projection.get("campaign_id") != value.campaign_id:
        raise SellEngineValidationError("Current Thesis projection campaign mismatch")
    if projection.get("strategy") not in (None, value.strategy):
        raise SellEngineValidationError("Current Thesis projection strategy mismatch")
    thesis_id = projection.get("thesis_id")
    if not isinstance(thesis_id, str) or _THESIS_ID_RE.fullmatch(thesis_id) is None:
        raise SellEngineValidationError("Current Thesis projection thesis_id is invalid")
    if projection.get("formal_status") != "READY":
        return (
            {
                "source_contract": "formal_current_thesis.projection.v0.1",
                "input_state": "NOT_READY",
                "pressure_state": None,
                "category": None,
                "evaluation": "NOT_EVALUATED",
                "applicable": True,
                "hold_ok": False,
                "reason_codes": ["THESIS_NOT_READY"],
                "authority_refs": list(value.authority_refs),
            },
            thesis_id,
            None,
        )
    if projection.get("schema_version") != "formal_current_thesis.projection.v0.1":
        raise SellEngineValidationError("Current Thesis projection schema mismatch")
    state = projection.get("effective_state")
    terminal = projection.get("terminal")
    if state not in THESIS_STATES or type(terminal) is not bool or terminal != (state in {"DISPROVEN", "INVALIDATED"}):
        raise SellEngineValidationError("Current Thesis state/terminal contract invalid")
    revision = projection.get("original", {}).get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise SellEngineValidationError("Current Thesis original revision is invalid")
    if state in {"DISPROVEN", "INVALIDATED"}:
        pressure_state = "THESIS_INVALIDATED"
        category = "THESIS_INVALIDATION"
        hold_ok = False
        reason_codes = [f"THESIS_{state}"]
    elif state == "WEAKENED":
        pressure_state = None
        category = None
        hold_ok = False
        reason_codes = ["THESIS_WEAKENED"]
    elif state == "UNKNOWN":
        pressure_state = None
        category = None
        hold_ok = False
        reason_codes = ["THESIS_UNKNOWN"]
    else:
        pressure_state = None
        category = None
        hold_ok = True
        reason_codes = [f"THESIS_{state}_NO_SELL_PRESSURE"]
    return (
        {
            "source_contract": "formal_current_thesis.projection.v0.1",
            "input_state": state,
            "pressure_state": pressure_state,
            "category": category,
            "evaluation": "UNKNOWN" if state == "UNKNOWN" else "EVALUATED",
            "applicable": True,
            "hold_ok": hold_ok,
            "reason_codes": reason_codes,
            "authority_refs": list(value.authority_refs),
        },
        thesis_id,
        revision,
    )


def _hard_risk_dimension(
    value: HardRiskEvaluation | None,
    *,
    security_code: str,
    strategy: str,
    campaign_id: str,
    as_of: str,
) -> dict[str, Any]:
    if value is None:
        return {
            "source_contract": "hard_risk_runtime.v0.1",
            "input_state": "NOT_EVALUATED",
            "pressure_state": None,
            "category": None,
            "evaluation": "NOT_EVALUATED",
            "applicable": True,
            "hold_ok": False,
            "reason_codes": ["HARD_RISK_NOT_EVALUATED"],
            "authority_refs": [],
        }
    if (
        value.security_code != security_code
        or value.strategy != strategy
        or value.campaign_id != campaign_id
        or value.as_of != as_of
    ):
        raise SellEngineValidationError("Hard Risk identity/as_of mismatch")
    if value.hard_risk_state == "CONFIRMED":
        return {
            "source_contract": "hard_risk_runtime.v0.1",
            "input_state": "CONFIRMED",
            "pressure_state": "WATCH_TO_REDUCE",
            "category": "RISK_EXIT",
            "evaluation": "EVALUATED",
            "applicable": True,
            "hold_ok": False,
            "reason_codes": ["HARD_RISK_CONFIRMED_REVIEW_PRESSURE"],
            "authority_refs": list(value.authority_refs),
        }
    return {
        "source_contract": "hard_risk_runtime.v0.1",
        "input_state": value.hard_risk_state,
        "pressure_state": None,
        "category": None,
        "evaluation": value.hard_risk_evaluation,
        "applicable": True,
        "hold_ok": value.hard_risk_state == "CLEAR" and value.hard_risk_evaluation == "EVALUATED",
        "reason_codes": [f"HARD_RISK_{value.hard_risk_state}"],
        "authority_refs": list(value.authority_refs),
    }


def _material_dimension(
    value: MaterialChangeProjection | None,
    *,
    security_code: str,
    strategy: str,
    campaign_id: str,
    as_of: str,
) -> dict[str, Any]:
    if value is None:
        return {
            "source_contract": MATERIAL_CHANGE_AUTHORITY_REF,
            "input_state": "NOT_EVALUATED",
            "pressure_state": None,
            "category": None,
            "evaluation": "NOT_EVALUATED",
            "applicable": True,
            "hold_ok": False,
            "reason_codes": ["MATERIAL_CHANGE_NOT_EVALUATED"],
            "authority_refs": [],
        }
    if (
        value.security_code != security_code
        or value.strategy != strategy
        or value.campaign_id != campaign_id
        or value.as_of != as_of
    ):
        raise SellEngineValidationError("Material Change identity/as_of mismatch")
    if value.material_change_state == "CONFIRMED":
        return {
            "source_contract": MATERIAL_CHANGE_AUTHORITY_REF,
            "input_state": "CONFIRMED",
            "pressure_state": None,
            "category": None,
            "evaluation": "EVALUATED",
            "applicable": True,
            "hold_ok": False,
            "reason_codes": ["MATERIAL_CHANGE_CONFIRMED_REVIEW_ONLY"],
            "authority_refs": list(value.authority_refs),
        }
    return {
        "source_contract": MATERIAL_CHANGE_AUTHORITY_REF,
        "input_state": value.material_change_state,
        "pressure_state": None,
        "category": None,
        "evaluation": value.material_change_evaluation,
        "applicable": True,
        "hold_ok": value.material_change_state == "NONE" and value.material_change_evaluation == "EVALUATED",
        "reason_codes": [f"MATERIAL_CHANGE_{value.material_change_state}"],
        "authority_refs": list(value.authority_refs),
    }


def project_sell_engine(
    *,
    security_code: str,
    strategy: str,
    campaign_id: str,
    as_of: str,
    current_thesis_authority: CurrentThesisAuthority | None,
    hard_risk_evaluation: HardRiskEvaluation | None,
    material_change: MaterialChangeProjection | None,
    risk_exit: RiskExitAuthority | None = None,
    expectation_price_in: ExpectationPriceInAuthority | None = None,
    risk_reward: RiskRewardAuthority | None = None,
    catalyst: CatalystAuthority | None = None,
    portfolio_rebalance: PortfolioRebalanceAuthority | None = None,
    opportunity_cost: OpportunityCostAuthority | None = None,
    technical_execution: TechnicalExecutionAuthority | None = None,
) -> SellEngineProjection:
    """Compose sell-side state from named authority results only.

    Passing a plain Mapping, a raw Hard Risk label, PnL, price, or technical
    payload is rejected by the typed signature and runtime type checks.  A
    named adapter may produce REDUCE/EXIT for its own dimension, but this
    composition module never infers that pressure from unrelated facts.
    """

    security = _require_security_code(security_code)
    strategy_value = _require_strategy(strategy)
    campaign = _require_campaign_id(campaign_id)
    as_of_text, _ = _parse_utc(as_of, "as_of")

    if current_thesis_authority is not None and not isinstance(current_thesis_authority, CurrentThesisAuthority):
        raise SellEngineValidationError("current_thesis_authority must be CurrentThesisAuthority or None")
    if hard_risk_evaluation is not None and not isinstance(hard_risk_evaluation, HardRiskEvaluation):
        raise SellEngineValidationError("hard_risk_evaluation must be HardRiskEvaluation or None")
    if material_change is not None and not isinstance(material_change, MaterialChangeProjection):
        raise SellEngineValidationError("material_change must be MaterialChangeProjection or None")
    if current_thesis_authority is not None and (
        current_thesis_authority.security_code != security
        or current_thesis_authority.strategy != strategy_value
        or current_thesis_authority.campaign_id != campaign
        or current_thesis_authority.as_of != as_of_text
    ):
        raise SellEngineValidationError("Current Thesis identity/as_of mismatch")

    expected_types = {
        "risk_exit": RiskExitAuthority,
        "expectation_price_in": ExpectationPriceInAuthority,
        "risk_reward": RiskRewardAuthority,
        "catalyst": CatalystAuthority,
        "portfolio_rebalance": PortfolioRebalanceAuthority,
        "opportunity_cost": OpportunityCostAuthority,
        "technical_execution": TechnicalExecutionAuthority,
    }
    provided = {
        "risk_exit": risk_exit,
        "expectation_price_in": expectation_price_in,
        "risk_reward": risk_reward,
        "catalyst": catalyst,
        "portfolio_rebalance": portfolio_rebalance,
        "opportunity_cost": opportunity_cost,
        "technical_execution": technical_execution,
    }
    for field_name, value in provided.items():
        expected = expected_types[field_name]
        if value is not None and type(value) is not expected:
            raise SellEngineValidationError(
                f"{field_name} must be the named {expected.__name__} adapter result; "
                "generic Mapping is not accepted"
            )
    if strategy_value == "MEDIUM" and technical_execution is not None and technical_execution.state == "EXIT":
        raise SellEngineValidationError(
            "technical_execution EXIT is not an independent MEDIUM long-horizon authority"
        )

    thesis_dimension, thesis_id, thesis_revision = _thesis_dimension(current_thesis_authority)
    hard_dimension = _hard_risk_dimension(
        hard_risk_evaluation,
        security_code=security,
        strategy=strategy_value,
        campaign_id=campaign,
        as_of=as_of_text,
    )
    material_dimension = _material_dimension(
        material_change,
        security_code=security,
        strategy=strategy_value,
        campaign_id=campaign,
        as_of=as_of_text,
    )
    dimensions: dict[str, dict[str, Any]] = {
        "thesis": thesis_dimension,
        "hard_risk": hard_dimension,
        "material_change": material_dimension,
        "risk_exit": _named_pressure_dimension(
            risk_exit, field_name="risk_exit", category="RISK_EXIT"
        ),
        "expectation_price_in": _named_pressure_dimension(
            expectation_price_in,
            field_name="expectation_price_in",
            category="EXPECTATION_PRICE_IN",
        ),
        "risk_reward": _named_pressure_dimension(
            risk_reward,
            field_name="risk_reward",
            category="RISK_REWARD_DETERIORATION",
        ),
        "catalyst": _named_pressure_dimension(
            catalyst, field_name="catalyst", category="CATALYST_FAILURE"
        ),
        "portfolio_rebalance": _named_pressure_dimension(
            portfolio_rebalance,
            field_name="portfolio_rebalance",
            category="PORTFOLIO_REBALANCE",
        ),
        "opportunity_cost": _named_pressure_dimension(
            opportunity_cost,
            field_name="opportunity_cost",
            category="OPPORTUNITY_COST",
        ),
        "technical_execution": _named_pressure_dimension(
            technical_execution,
            field_name="technical_execution",
            category="TECHNICAL_EXECUTION",
        ),
    }

    evaluation = "EVALUATED"
    reason_codes: list[str] = []
    uncertainties: list[str] = []
    opposing: list[str] = []
    supporting: list[str] = []
    authority_refs: list[str] = [AUTHORITY_REF]
    pressure_drivers: list[tuple[str, str]] = []
    hold_ok = True
    review_pressure = False

    for name, dimension in dimensions.items():
        evaluation = _max_evaluation(evaluation, dimension["evaluation"])
        reason_codes.extend(dimension["reason_codes"])
        authority_refs.extend(dimension["authority_refs"])
        if not dimension["hold_ok"]:
            hold_ok = False
        if dimension["evaluation"] != "EVALUATED":
            uncertainties.extend(dimension["reason_codes"])
        if dimension["input_state"] in {"STABLE", "STRENGTHENED", "NONE", "NOT_APPLICABLE", "NOT_YET"}:
            opposing.extend(dimension["reason_codes"])
        category = dimension["category"]
        pressure_state = dimension["pressure_state"]
        if category is not None and pressure_state is not None:
            pressure_drivers.append((category, pressure_state))
            supporting.append(category)
        if name in {"hard_risk", "material_change"} and dimension["input_state"] == "CONFIRMED":
            review_pressure = True
        if name == "thesis" and dimension["input_state"] == "WEAKENED":
            review_pressure = True

    sell_state: str | None = None
    primary_reason: str | None = None
    # Thesis terminality is a Product Authority transform and wins over all
    # other sell-side pressure, exactly as in #107.
    if thesis_dimension["pressure_state"] == "THESIS_INVALIDATED":
        sell_state = "THESIS_INVALIDATED"
        primary_reason = "THESIS_INVALIDATION"
    else:
        for category, pressure_state in pressure_drivers:
            sell_state = _max_sell_state(sell_state, pressure_state)
        if sell_state is not None:
            final_drivers = [category for category, state in pressure_drivers if state == sell_state]
            primary_reason = final_drivers[0] if len(final_drivers) == 1 else final_drivers[0]

    hold_positive_proof = False
    if sell_state is None and hold_ok and evaluation == "EVALUATED":
        sell_state = "HOLD"
        hold_positive_proof = True
        reason_codes.append("HOLD_POSITIVE_PROOF")

    if primary_reason is not None and primary_reason not in supporting:
        supporting.insert(0, primary_reason)
    authority_refs.extend(
        current_thesis_authority.authority_refs
        if current_thesis_authority is not None
        else ()
    )
    if hard_risk_evaluation is not None:
        authority_refs.extend(hard_risk_evaluation.authority_refs)
    if material_change is not None:
        authority_refs.extend(material_change.authority_refs)

    def unique(values: list[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value for value in values if value))

    return SellEngineProjection(
        schema_version=SCHEMA_VERSION,
        authority_ref=AUTHORITY_REF,
        security_code=security,
        strategy=strategy_value,
        campaign_id=campaign,
        as_of=as_of_text,
        sell_state=sell_state,
        sell_evaluation=evaluation,
        primary_reason=primary_reason,
        reason_codes=unique(reason_codes),
        supporting_reasons=unique(supporting),
        opposing_reasons=unique(opposing),
        uncertainties=unique(uncertainties),
        hold_positive_proof=hold_positive_proof,
        review_pressure=review_pressure,
        thesis_id=thesis_id,
        thesis_revision=thesis_revision,
        authority_refs=unique(authority_refs),
        dimensions=dimensions,
    )


__all__ = [
    "AUTHORITY_REF",
    "CatalystAuthority",
    "EVALUATION_STATES",
    "ExpectationPriceInAuthority",
    "OpportunityCostAuthority",
    "PortfolioRebalanceAuthority",
    "REASON_CATEGORIES",
    "RiskExitAuthority",
    "RiskRewardAuthority",
    "SCHEMA_VERSION",
    "SELL_EVALUATIONS",
    "SELL_STATES",
    "SellEngineError",
    "SellEngineProjection",
    "SellEngineValidationError",
    "TechnicalExecutionAuthority",
    "project_sell_engine",
    "sell_engine_projection_from_mapping",
]
