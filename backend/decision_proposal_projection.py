"""Formal Decision Proposal pure-domain contract for P0-DC1.

This is a deterministic, uncommitted composition result.  It preserves
Asset / Trade / Portfolio views, derives a frozen-vocabulary Next Best Action,
and narrows the Action Envelope from named authority results.  It never calls
``frozen_decision_service`` and never creates commit identity, timestamps,
hashes, broker fields, or order fields.

The input surface accepts typed results from the C-lane authorities rather
than a generic ``action`` / ``severity`` / ``material_change_state`` mapping.
Missing or incomplete authorities remain visible as
``UNKNOWN``/``NOT_EVALUATED``/``ERROR`` and can only narrow the envelope.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from frozen_decision_store import NEXT_BEST_ACTIONS
from hard_risk_contract import HardRiskEvaluation
from material_change_projection import (
    CurrentThesisAuthority,
    MaterialChangeProjection,
)
from sell_engine_projection import SellEngineProjection


SCHEMA_VERSION = "decision_proposal.projection.v0.1"
AUTHORITY_REF = "decision_proposal:projection:v0.1"
PROPOSAL_STATUS = "UNCOMMITTED"
EVALUATION_STATES: tuple[str, ...] = (
    "EVALUATED",
    "UNKNOWN",
    "NOT_EVALUATED",
    "ERROR",
)
VALID_STRATEGIES = ("SHORT", "SWING", "MEDIUM")

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
_FORBIDDEN_KEYS = frozenset(
    {
        "decision_id",
        "committed_at",
        "snapshot_hash",
        "broker",
        "broker_id",
        "order",
        "order_id",
        "order_fields",
        "broker_fields",
    }
)


class DecisionProposalError(ValueError):
    """Base Decision Proposal contract error."""


class DecisionProposalValidationError(DecisionProposalError):
    """Malformed or mismatched proposal input."""


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DecisionProposalValidationError(
            f"{field} must be a non-empty trimmed string"
        )
    return value


def _require_security_code(value: object) -> str:
    text = _require_text(value, "security_code")
    if _SECURITY_CODE_RE.fullmatch(text) is None:
        raise DecisionProposalValidationError("security_code must be exactly 6 digits")
    return text


def _require_strategy(value: object) -> str:
    text = _require_text(value, "strategy")
    if text not in VALID_STRATEGIES:
        raise DecisionProposalValidationError(
            f"strategy must be one of {VALID_STRATEGIES}, got {text!r}"
        )
    return text


def _require_campaign_id(value: object) -> str:
    text = _require_text(value, "campaign_id")
    if _CAMPAIGN_ID_RE.fullmatch(text) is None:
        raise DecisionProposalValidationError(
            "campaign_id must match campaign_<32 lowercase hex>"
        )
    return text


def _parse_utc(value: object, field: str) -> datetime:
    text = _require_text(value, field)
    if not any(pattern.fullmatch(text) for pattern in _AS_OF_UTC_FORMS):
        raise DecisionProposalValidationError(
            f"{field} must be an explicit UTC zero-offset instant"
        )
    parse_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(parse_text)
    except ValueError as exc:
        raise DecisionProposalValidationError(
            f"{field} is not a valid UTC instant"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DecisionProposalValidationError(f"{field} must be timezone-aware UTC")
    if parsed.utcoffset().total_seconds() != 0:
        raise DecisionProposalValidationError(f"{field} must use UTC zero offset")
    return parsed.astimezone(timezone.utc)


def _validate_revision(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise DecisionProposalValidationError("thesis_revision must be a positive integer")
    return value


def _reject_forbidden_keys(value: Any, path: str = "view") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in _FORBIDDEN_KEYS:
                raise DecisionProposalValidationError(
                    f"{path}.{key} is outside the uncommitted Proposal contract"
                )
            _reject_forbidden_keys(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_forbidden_keys(nested, f"{path}[{index}]")


def _json_object(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DecisionProposalValidationError(f"{field} must be a JSON object")
    copied = copy.deepcopy(dict(value))
    _reject_forbidden_keys(copied, field)
    try:
        json.dumps(copied, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise DecisionProposalValidationError(f"{field} is not JSON-safe") from exc
    return copied


def _string_list(value: list[str] | tuple[str, ...], field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise DecisionProposalValidationError(f"{field} must be a list/tuple")
    result = []
    for index, item in enumerate(value):
        result.append(_require_text(item, f"{field}[{index}]") )
    if len(result) != len(set(result)):
        raise DecisionProposalValidationError(f"{field} must not contain duplicates")
    return tuple(result)


def _ordered_actions(values: list[str] | tuple[str, ...], field: str) -> tuple[str, ...]:
    actions = _string_list(values, field)
    if any(action not in NEXT_BEST_ACTIONS for action in actions):
        raise DecisionProposalValidationError(f"{field} contains an unknown NBA")
    return tuple(action for action in NEXT_BEST_ACTIONS if action in actions)


@dataclass(frozen=True)
class DecisionProposal:
    """Uncommitted Formal Decision proposal value/result."""

    schema_version: str
    proposal_status: str
    proposal_evaluation: str
    security_code: str
    strategy: str
    campaign_id: str
    thesis_id: str
    thesis_revision: int
    as_of: str
    asset_view: Mapping[str, Any]
    trade_view: Mapping[str, Any]
    portfolio_view: Mapping[str, Any]
    next_best_action: str
    action_envelope: Mapping[str, Any]
    maintain_conditions: tuple[str, ...]
    upgrade_conditions: tuple[str, ...]
    downgrade_conditions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    authority_facts: Mapping[str, Any]
    authority_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise DecisionProposalValidationError("unsupported Decision Proposal schema")
        if self.proposal_status != PROPOSAL_STATUS:
            raise DecisionProposalValidationError("Proposal must remain UNCOMMITTED")
        if self.proposal_evaluation not in EVALUATION_STATES:
            raise DecisionProposalValidationError("invalid proposal_evaluation")
        _require_security_code(self.security_code)
        _require_strategy(self.strategy)
        _require_campaign_id(self.campaign_id)
        if _THESIS_ID_RE.fullmatch(self.thesis_id) is None:
            raise DecisionProposalValidationError("thesis_id must be 32 lowercase hex")
        _validate_revision(self.thesis_revision)
        _parse_utc(self.as_of, "as_of")
        for field_name, value in (
            ("asset_view", self.asset_view),
            ("trade_view", self.trade_view),
            ("portfolio_view", self.portfolio_view),
        ):
            _json_object(value, field_name)
        if self.next_best_action not in NEXT_BEST_ACTIONS:
            raise DecisionProposalValidationError("next_best_action is not frozen vocabulary")
        if not isinstance(self.action_envelope, Mapping):
            raise DecisionProposalValidationError("action_envelope must be a Mapping")
        envelope = dict(self.action_envelope)
        expected_envelope = {
            "allowed_actions",
            "blocked_actions",
            "maintain_conditions",
            "upgrade_conditions",
            "downgrade_conditions",
            "invalidation_conditions",
        }
        if set(envelope) != expected_envelope:
            raise DecisionProposalValidationError(
                "action_envelope fields must exactly match the Frozen Decision condition contract"
            )
        allowed = _ordered_actions(envelope["allowed_actions"], "action_envelope.allowed_actions")
        blocked = _ordered_actions(envelope["blocked_actions"], "action_envelope.blocked_actions")
        if set(allowed) & set(blocked) or set(allowed) | set(blocked) != set(NEXT_BEST_ACTIONS):
            raise DecisionProposalValidationError(
                "action_envelope allowed/blocked actions must partition frozen NBA vocabulary"
            )
        for field_name in (
            "maintain_conditions",
            "upgrade_conditions",
            "downgrade_conditions",
            "invalidation_conditions",
        ):
            _string_list(envelope[field_name], f"action_envelope.{field_name}")
        if tuple(envelope["maintain_conditions"]) != self.maintain_conditions:
            raise DecisionProposalValidationError("maintain_conditions mismatch")
        if tuple(envelope["upgrade_conditions"]) != self.upgrade_conditions:
            raise DecisionProposalValidationError("upgrade_conditions mismatch")
        if tuple(envelope["downgrade_conditions"]) != self.downgrade_conditions:
            raise DecisionProposalValidationError("downgrade_conditions mismatch")
        if tuple(envelope["invalidation_conditions"]) != self.invalidation_conditions:
            raise DecisionProposalValidationError("invalidation_conditions mismatch")
        if not isinstance(self.authority_facts, Mapping):
            raise DecisionProposalValidationError("authority_facts must be a Mapping")
        _reject_forbidden_keys(self.authority_facts, "authority_facts")
        object.__setattr__(self, "asset_view", _json_object(self.asset_view, "asset_view"))
        object.__setattr__(self, "trade_view", _json_object(self.trade_view, "trade_view"))
        object.__setattr__(self, "portfolio_view", _json_object(self.portfolio_view, "portfolio_view"))
        object.__setattr__(self, "action_envelope", copy.deepcopy(envelope))
        object.__setattr__(self, "authority_facts", copy.deepcopy(dict(self.authority_facts)))
        object.__setattr__(self, "authority_refs", _string_list(self.authority_refs, "authority_refs"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "proposal_status": self.proposal_status,
            "proposal_evaluation": self.proposal_evaluation,
            "security_code": self.security_code,
            "strategy": self.strategy,
            "campaign_id": self.campaign_id,
            "thesis_id": self.thesis_id,
            "thesis_revision": self.thesis_revision,
            "as_of": self.as_of,
            "asset_view": copy.deepcopy(dict(self.asset_view)),
            "trade_view": copy.deepcopy(dict(self.trade_view)),
            "portfolio_view": copy.deepcopy(dict(self.portfolio_view)),
            "next_best_action": self.next_best_action,
            "action_envelope": copy.deepcopy(dict(self.action_envelope)),
            "maintain_conditions": list(self.maintain_conditions),
            "upgrade_conditions": list(self.upgrade_conditions),
            "downgrade_conditions": list(self.downgrade_conditions),
            "invalidation_conditions": list(self.invalidation_conditions),
            "authority_facts": copy.deepcopy(dict(self.authority_facts)),
            "authority_refs": list(self.authority_refs),
        }


def decision_proposal_from_mapping(value: Mapping[str, Any]) -> DecisionProposal:
    if not isinstance(value, Mapping):
        raise DecisionProposalValidationError("Decision Proposal result must be a Mapping")
    expected = {
        "schema_version",
        "proposal_status",
        "proposal_evaluation",
        "security_code",
        "strategy",
        "campaign_id",
        "thesis_id",
        "thesis_revision",
        "as_of",
        "asset_view",
        "trade_view",
        "portfolio_view",
        "next_best_action",
        "action_envelope",
        "maintain_conditions",
        "upgrade_conditions",
        "downgrade_conditions",
        "invalidation_conditions",
        "authority_facts",
        "authority_refs",
    }
    if set(value) != expected:
        raise DecisionProposalValidationError(
            f"Decision Proposal fields must exactly equal {sorted(expected)}"
        )
    return DecisionProposal(
        schema_version=value["schema_version"],
        proposal_status=value["proposal_status"],
        proposal_evaluation=value["proposal_evaluation"],
        security_code=value["security_code"],
        strategy=value["strategy"],
        campaign_id=value["campaign_id"],
        thesis_id=value["thesis_id"],
        thesis_revision=value["thesis_revision"],
        as_of=value["as_of"],
        asset_view=value["asset_view"],
        trade_view=value["trade_view"],
        portfolio_view=value["portfolio_view"],
        next_best_action=value["next_best_action"],
        action_envelope=value["action_envelope"],
        maintain_conditions=tuple(value["maintain_conditions"]),
        upgrade_conditions=tuple(value["upgrade_conditions"]),
        downgrade_conditions=tuple(value["downgrade_conditions"]),
        invalidation_conditions=tuple(value["invalidation_conditions"]),
        authority_facts=value["authority_facts"],
        authority_refs=tuple(value["authority_refs"]),
    )


def _status_max(statuses: list[str]) -> str:
    return max(statuses, key=lambda status: _EVALUATION_RANK[status])


def _authority_fact(
    *,
    state: str | None,
    evaluation: str,
    refs: tuple[str, ...] | list[str],
    **extra: Any,
) -> dict[str, Any]:
    return {
        "state": state,
        "evaluation": evaluation,
        "authority_refs": sorted(set(refs)),
        **copy.deepcopy(extra),
    }


def _ordered_action_partition(allowed: set[str]) -> tuple[list[str], list[str]]:
    return (
        [action for action in NEXT_BEST_ACTIONS if action in allowed],
        [action for action in NEXT_BEST_ACTIONS if action not in allowed],
    )


def _conditions_and_envelope(
    *,
    evaluation: str,
    thesis_state: str | None,
    hard_risk_state: str | None,
    material_state: str | None,
    sell_state: str | None,
) -> tuple[dict[str, Any], str]:
    if evaluation != "EVALUATED":
        allowed = {"WAIT", "RESEARCH MORE"}
        maintain = ["all required named authorities evaluate at the same literal as_of"]
        upgrade = ["resolve every UNKNOWN / NOT_EVALUATED / ERROR authority before widening actions"]
        downgrade = [f"proposal_evaluation == {evaluation}"]
        invalidation = ["any authority identity or as_of mismatch"]
        nba = "RESEARCH MORE"
    elif thesis_state in {"DISPROVEN", "INVALIDATED"} or sell_state == "THESIS_INVALIDATED":
        allowed = {"WATCH TO REDUCE", "REDUCE", "EXIT", "WAIT", "RESEARCH MORE"}
        maintain = ["thesis invalidation remains acknowledged", "no positive new-risk action is allowed"]
        upgrade = ["user must create a new valid Current Thesis before any positive action"]
        downgrade = ["Current Thesis remains DISPROVEN or INVALIDATED"]
        invalidation = ["Current Thesis terminal fact is corrected by a new authoritative projection"]
        nba = "EXIT"
    elif hard_risk_state == "CONFIRMED":
        allowed = {"WATCH TO REDUCE", "REDUCE", "EXIT", "WAIT", "RESEARCH MORE"}
        maintain = ["Hard Risk is re-evaluated at the same as_of", "new risk capital remains blocked"]
        upgrade = ["Hard Risk returns a future named CLEAR authority at the same as_of"]
        downgrade = ["hard_risk_state == CONFIRMED", "do not infer EXIT from Hard Risk alone"]
        invalidation = ["a named Hard Risk authority remains CONFIRMED"]
        nba = "WATCH TO REDUCE" if sell_state in {None, "WATCH_TO_REDUCE"} else (
            "REDUCE" if sell_state == "REDUCE" else "EXIT"
        )
    elif sell_state == "EXIT":
        allowed = {"EXIT", "WAIT", "RESEARCH MORE"}
        maintain = ["the named EXIT authority remains valid at the same as_of"]
        upgrade = ["the named EXIT authority is withdrawn by its owner"]
        downgrade = ["sell_state == EXIT"]
        invalidation = ["the named EXIT authority is superseded by a newer valid result"]
        nba = "EXIT"
    elif sell_state == "REDUCE":
        allowed = {"WATCH TO REDUCE", "REDUCE", "EXIT", "WAIT", "RESEARCH MORE"}
        maintain = ["the named REDUCE authority remains valid at the same as_of"]
        upgrade = ["all sell-side authorities return no pressure and Hard Risk is CLEAR"]
        downgrade = ["sell_state == REDUCE"]
        invalidation = ["the named REDUCE authority is superseded by a newer valid result"]
        nba = "REDUCE"
    elif sell_state == "WATCH_TO_REDUCE":
        allowed = {"WATCH TO REDUCE", "REDUCE", "EXIT", "WAIT", "RESEARCH MORE"}
        maintain = ["the named watch/review authority remains valid at the same as_of"]
        upgrade = ["the named authority escalates to an explicit REDUCE or EXIT result"]
        downgrade = ["sell_state == WATCH_TO_REDUCE"]
        invalidation = ["the named watch/review authority is superseded by a newer valid result"]
        nba = "WATCH TO REDUCE"
    elif material_state == "CONFIRMED" or thesis_state == "WEAKENED":
        allowed = {"WAIT", "RESEARCH MORE"}
        maintain = ["review the confirmed change before taking a new positive-risk action"]
        upgrade = ["a new named authority evaluates the changed thesis and action envelope"]
        downgrade = ["material_change_state == CONFIRMED or thesis_state == WEAKENED"]
        invalidation = ["the changed fact is superseded by a newer authoritative projection"]
        nba = "WAIT"
    elif sell_state == "HOLD" and hard_risk_state == "CLEAR" and material_state == "NONE":
        allowed = {"HOLD", "WAIT", "RESEARCH MORE"}
        maintain = ["hard_risk_state == CLEAR", "material_change_state == NONE", "sell_state == HOLD"]
        upgrade = ["a named positive action authority is added and evaluates at the same as_of"]
        downgrade = ["any named sell-side pressure or material change appears"]
        invalidation = ["Hard Risk becomes CONFIRMED or Current Thesis becomes terminal"]
        nba = "HOLD"
    else:
        allowed = {"WAIT", "RESEARCH MORE"}
        maintain = ["keep the proposal uncommitted until the named authority set is complete"]
        upgrade = ["complete the missing named authority evaluation"]
        downgrade = ["the current proposal lacks a clean positive proof"]
        invalidation = ["identity or as_of scope changes"]
        nba = "WAIT"

    allowed_actions, blocked_actions = _ordered_action_partition(allowed)
    envelope = {
        "allowed_actions": allowed_actions,
        "blocked_actions": blocked_actions,
        "maintain_conditions": maintain,
        "upgrade_conditions": upgrade,
        "downgrade_conditions": downgrade,
        "invalidation_conditions": invalidation,
    }
    return envelope, nba


def project_decision_proposal(
    *,
    security_code: str,
    strategy: str,
    campaign_id: str,
    thesis_id: str,
    thesis_revision: int,
    as_of: str,
    asset_view: Mapping[str, Any],
    trade_view: Mapping[str, Any],
    portfolio_view: Mapping[str, Any],
    current_thesis_authority: CurrentThesisAuthority | None,
    hard_risk_evaluation: HardRiskEvaluation | None,
    material_change: MaterialChangeProjection | None,
    sell_engine: SellEngineProjection | None,
) -> DecisionProposal:
    """Compose one exact-scope, uncommitted Formal Decision Proposal."""

    security = _require_security_code(security_code)
    strategy_value = _require_strategy(strategy)
    campaign = _require_campaign_id(campaign_id)
    thesis_id_value = _require_text(thesis_id, "thesis_id")
    if _THESIS_ID_RE.fullmatch(thesis_id_value) is None:
        raise DecisionProposalValidationError("thesis_id must be 32 lowercase hex")
    revision = _validate_revision(thesis_revision)
    as_of_text = _require_text(as_of, "as_of")
    _parse_utc(as_of_text, "as_of")

    for name, value, expected in (
        ("current_thesis_authority", current_thesis_authority, CurrentThesisAuthority),
        ("hard_risk_evaluation", hard_risk_evaluation, HardRiskEvaluation),
        ("material_change", material_change, MaterialChangeProjection),
        ("sell_engine", sell_engine, SellEngineProjection),
    ):
        if value is not None and not isinstance(value, expected):
            raise DecisionProposalValidationError(
                f"{name} must be the named {expected.__name__} result or None"
            )

    if current_thesis_authority is not None:
        if (
            current_thesis_authority.security_code != security
            or current_thesis_authority.strategy != strategy_value
            or current_thesis_authority.campaign_id != campaign
            or current_thesis_authority.as_of != as_of_text
        ):
            raise DecisionProposalValidationError("Current Thesis identity/as_of mismatch")
        projection = dict(current_thesis_authority.projection)
        if projection.get("thesis_id") != thesis_id_value:
            raise DecisionProposalValidationError("Current Thesis thesis_id mismatch")
        if projection.get("formal_status") == "READY":
            source_revision = projection.get("original", {}).get("revision")
            if source_revision != revision:
                raise DecisionProposalValidationError("Current Thesis thesis_revision mismatch")
    if hard_risk_evaluation is not None and (
        hard_risk_evaluation.security_code != security
        or hard_risk_evaluation.strategy != strategy_value
        or hard_risk_evaluation.campaign_id != campaign
        or hard_risk_evaluation.as_of != as_of_text
    ):
        raise DecisionProposalValidationError("Hard Risk identity/as_of mismatch")
    if material_change is not None and (
        material_change.security_code != security
        or material_change.strategy != strategy_value
        or material_change.campaign_id != campaign
        or material_change.as_of != as_of_text
        or material_change.thesis_id not in (None, thesis_id_value)
    ):
        raise DecisionProposalValidationError("Material Change identity/as_of/thesis mismatch")
    if sell_engine is not None and (
        sell_engine.security_code != security
        or sell_engine.strategy != strategy_value
        or sell_engine.campaign_id != campaign
        or sell_engine.as_of != as_of_text
        or sell_engine.thesis_id not in (None, thesis_id_value)
    ):
        raise DecisionProposalValidationError("Sell Engine identity/as_of/thesis mismatch")

    thesis_state = None
    thesis_evaluation = "NOT_EVALUATED"
    thesis_refs: tuple[str, ...] = ()
    if current_thesis_authority is not None:
        projection = dict(current_thesis_authority.projection)
        thesis_state = projection.get("effective_state")
        thesis_evaluation = "EVALUATED" if projection.get("formal_status") == "READY" else "NOT_EVALUATED"
        if thesis_state == "UNKNOWN":
            thesis_evaluation = "UNKNOWN"
        thesis_refs = current_thesis_authority.authority_refs

    hard_state = hard_risk_evaluation.hard_risk_state if hard_risk_evaluation is not None else None
    hard_evaluation = hard_risk_evaluation.hard_risk_evaluation if hard_risk_evaluation is not None else "NOT_EVALUATED"
    material_state = material_change.material_change_state if material_change is not None else None
    material_evaluation = material_change.material_change_evaluation if material_change is not None else "NOT_EVALUATED"
    sell_state = sell_engine.sell_state if sell_engine is not None else None
    sell_evaluation = sell_engine.sell_evaluation if sell_engine is not None else "NOT_EVALUATED"
    proposal_evaluation = _status_max(
        [thesis_evaluation, hard_evaluation, material_evaluation, sell_evaluation]
    )

    authority_facts = {
        "current_thesis": _authority_fact(
            state=thesis_state,
            evaluation=thesis_evaluation,
            refs=thesis_refs,
            authority="formal_current_thesis.projection.v0.1",
        ),
        "hard_risk": _authority_fact(
            state=hard_state,
            evaluation=hard_evaluation,
            refs=hard_risk_evaluation.authority_refs if hard_risk_evaluation is not None else (),
            authority="hard_risk_runtime.v0.1",
        ),
        "material_change": _authority_fact(
            state=material_state,
            evaluation=material_evaluation,
            refs=material_change.authority_refs if material_change is not None else (),
            authority="material_change.projection.v0.1",
        ),
        "sell_engine": _authority_fact(
            state=sell_state,
            evaluation=sell_evaluation,
            refs=sell_engine.authority_refs if sell_engine is not None else (),
            authority="sell_engine.projection.vnext.v0.1",
        ),
    }

    envelope, nba = _conditions_and_envelope(
        evaluation=proposal_evaluation,
        thesis_state=thesis_state,
        hard_risk_state=hard_state,
        material_state=material_state,
        sell_state=sell_state,
    )
    authority_refs = [AUTHORITY_REF]
    authority_refs.extend(thesis_refs)
    if hard_risk_evaluation is not None:
        authority_refs.extend(hard_risk_evaluation.authority_refs)
    if material_change is not None:
        authority_refs.extend(material_change.authority_refs)
    if sell_engine is not None:
        authority_refs.extend(sell_engine.authority_refs)
    return DecisionProposal(
        schema_version=SCHEMA_VERSION,
        proposal_status=PROPOSAL_STATUS,
        proposal_evaluation=proposal_evaluation,
        security_code=security,
        strategy=strategy_value,
        campaign_id=campaign,
        thesis_id=thesis_id_value,
        thesis_revision=revision,
        as_of=as_of_text,
        asset_view=_json_object(asset_view, "asset_view"),
        trade_view=_json_object(trade_view, "trade_view"),
        portfolio_view=_json_object(portfolio_view, "portfolio_view"),
        next_best_action=nba,
        action_envelope=envelope,
        maintain_conditions=tuple(envelope["maintain_conditions"]),
        upgrade_conditions=tuple(envelope["upgrade_conditions"]),
        downgrade_conditions=tuple(envelope["downgrade_conditions"]),
        invalidation_conditions=tuple(envelope["invalidation_conditions"]),
        authority_facts=authority_facts,
        authority_refs=tuple(dict.fromkeys(authority_refs)),
    )


__all__ = [
    "AUTHORITY_REF",
    "DecisionProposal",
    "DecisionProposalError",
    "DecisionProposalValidationError",
    "EVALUATION_STATES",
    "NEXT_BEST_ACTIONS",
    "PROPOSAL_STATUS",
    "SCHEMA_VERSION",
    "decision_proposal_from_mapping",
    "project_decision_proposal",
]
