"""P0-DI2A — canonical Actual Holding to current Campaign composition.

This read model composes existing authorities without creating Campaigns,
Theses, allocations, prices, or capital attribution.  Aggregate holding facts
remain security-scoped; every Campaign relation keeps its real campaign_id.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Callable, Mapping

import campaign_service
import position_reality_service


SCHEMA_VERSION = "holdings-campaign-composition.v0.1"
CURRENT_CAMPAIGN_STATUSES = frozenset({"ACTIVE", "REDUCING"})

_SECURITY_CODE_RE = re.compile(r"^[0-9]{6}$")
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_STRATEGIES = frozenset({"SHORT", "SWING", "MEDIUM"})
_POSITION_STATUSES = frozenset({"OPEN", "CLOSED"})
_POSITION_ORIGINS = frozenset({"PRE_VIBE", "POST_VIBE", "MIXED"})


class HoldingsCampaignCompositionError(RuntimeError):
    """Base error for the read-model composition boundary."""


class HoldingsCampaignCompositionIntegrityError(
    HoldingsCampaignCompositionError
):
    """An upstream authority returned an internally invalid contract."""


PositionReader = Callable[[], Mapping[str, Any]]
CampaignReader = Callable[[], list[Mapping[str, Any]]]
BindingReader = Callable[[str], Mapping[str, Any]]


def _require_text(value: Any, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise HoldingsCampaignCompositionIntegrityError(
            f"{field} must be canonical non-empty text"
        )
    return value


def _validate_position(position: Any) -> dict[str, Any]:
    if not isinstance(position, Mapping):
        raise HoldingsCampaignCompositionIntegrityError(
            "position must be a mapping"
        )
    required = {
        "code", "name", "shares", "cost_basis", "avg_cost", "status",
        "origin", "cost_known",
    }
    if set(position) != required:
        raise HoldingsCampaignCompositionIntegrityError(
            "position fields do not match the canonical contract"
        )
    code = _require_text(position["code"], "position.code")
    if _SECURITY_CODE_RE.fullmatch(code) is None:
        raise HoldingsCampaignCompositionIntegrityError(
            "position.code must be six ASCII digits"
        )
    name = _require_text(position["name"], "position.name")
    shares = position["shares"]
    if type(shares) is not int or shares < 0:
        raise HoldingsCampaignCompositionIntegrityError(
            "position.shares must be a non-negative integer"
        )
    status = position["status"]
    if status not in _POSITION_STATUSES:
        raise HoldingsCampaignCompositionIntegrityError(
            "position.status is unknown"
        )
    origin = position["origin"]
    if origin not in _POSITION_ORIGINS:
        raise HoldingsCampaignCompositionIntegrityError(
            "position.origin is unknown"
        )
    cost_known = position["cost_known"]
    if type(cost_known) is not bool:
        raise HoldingsCampaignCompositionIntegrityError(
            "position.cost_known must be bool"
        )
    cost_basis = position["cost_basis"]
    avg_cost = position["avg_cost"]
    if cost_known and status == "OPEN":
        if type(cost_basis) not in (int, float) or isinstance(cost_basis, bool):
            raise HoldingsCampaignCompositionIntegrityError(
                "known open position cost_basis must be numeric"
            )
        if type(avg_cost) not in (int, float) or isinstance(avg_cost, bool):
            raise HoldingsCampaignCompositionIntegrityError(
                "known open position avg_cost must be numeric"
            )
    elif status == "OPEN" and (cost_basis is not None or avg_cost is not None):
        raise HoldingsCampaignCompositionIntegrityError(
            "unknown open position cost must remain null"
        )
    return {
        "security_code": code,
        "security_name": name,
        "holding": {
            "status": status,
            "shares": shares,
            "cost_basis": cost_basis,
            "avg_cost": avg_cost,
            "cost_known": cost_known,
            "origin": origin,
        },
    }


def _validate_campaign(record: Any) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise HoldingsCampaignCompositionIntegrityError(
            "campaign must be a mapping"
        )
    required = {
        "campaign_id", "security_code", "strategy", "status", "created_at"
    }
    if set(record) != required:
        raise HoldingsCampaignCompositionIntegrityError(
            "campaign fields do not match the canonical contract"
        )
    campaign_id = _require_text(record["campaign_id"], "campaign_id")
    if _CAMPAIGN_ID_RE.fullmatch(campaign_id) is None:
        raise HoldingsCampaignCompositionIntegrityError(
            "campaign_id is invalid"
        )
    security_code = _require_text(
        record["security_code"], "campaign.security_code"
    )
    if _SECURITY_CODE_RE.fullmatch(security_code) is None:
        raise HoldingsCampaignCompositionIntegrityError(
            "campaign.security_code is invalid"
        )
    strategy = record["strategy"]
    if strategy not in _STRATEGIES:
        raise HoldingsCampaignCompositionIntegrityError(
            "campaign.strategy is unknown"
        )
    status = record["status"]
    if status not in campaign_service.STATUSES:
        raise HoldingsCampaignCompositionIntegrityError(
            "campaign.status is unknown"
        )
    created_at = _require_text(record["created_at"], "campaign.created_at")
    return {
        "campaign_id": campaign_id,
        "security_code": security_code,
        "strategy": strategy,
        "status": status,
        "created_at": created_at,
    }


def _validate_binding(
    binding: Any, *, campaign: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(binding, Mapping):
        raise HoldingsCampaignCompositionIntegrityError(
            "thesis binding must be a mapping"
        )
    required = {
        "campaign_id", "thesis_id", "thesis_revision_at_bind",
        "campaign_strategy_at_bind", "bound_at",
    }
    if set(binding) != required:
        raise HoldingsCampaignCompositionIntegrityError(
            "thesis binding fields do not match the canonical contract"
        )
    if binding["campaign_id"] != campaign["campaign_id"]:
        raise HoldingsCampaignCompositionIntegrityError(
            "thesis binding campaign identity mismatched"
        )
    thesis_id = _require_text(binding["thesis_id"], "binding.thesis_id")
    revision = binding["thesis_revision_at_bind"]
    if type(revision) is not int or revision < 1:
        raise HoldingsCampaignCompositionIntegrityError(
            "binding revision must be a positive integer"
        )
    strategy = binding["campaign_strategy_at_bind"]
    if strategy != campaign["strategy"]:
        raise HoldingsCampaignCompositionIntegrityError(
            "thesis binding strategy mismatched"
        )
    bound_at = _require_text(binding["bound_at"], "binding.bound_at")
    return {
        "thesis_id": thesis_id,
        "thesis_revision_at_bind": revision,
        "campaign_strategy_at_bind": strategy,
        "bound_at": bound_at,
    }


def _production_campaign_reader() -> list[dict]:
    # One canonical snapshot avoids cross-call status drift; current statuses
    # are filtered only after every returned Campaign validates.
    return campaign_service.list_campaigns()


def _adapt_campaign(
    campaign: dict[str, Any], binding_reader: BindingReader
) -> dict[str, Any]:
    try:
        raw_binding = binding_reader(campaign["campaign_id"])
    except campaign_service.ThesisBindingNotFoundError:
        binding_status = "NOT_BOUND"
        binding = None
    else:
        binding_status = "BOUND"
        binding = _validate_binding(raw_binding, campaign=campaign)
    return {
        **campaign,
        "thesis_binding_status": binding_status,
        "thesis_binding": binding,
    }


def assemble_holdings_campaign_composition(
    *,
    position_reader: PositionReader = position_reality_service.derive_positions,
    campaign_reader: CampaignReader = _production_campaign_reader,
    binding_reader: BindingReader = campaign_service.get_campaign_thesis_binding,
) -> dict[str, Any]:
    """Build a detached, deterministic, zero-write holding read model."""
    try:
        derived = position_reader()
    except position_reality_service.PositionDerivationError as exc:
        raise HoldingsCampaignCompositionError(
            "canonical position derivation failed"
        ) from exc
    if not isinstance(derived, Mapping):
        raise HoldingsCampaignCompositionIntegrityError(
            "position authority result must be a mapping"
        )
    required = {
        "derivation_status", "bootstrap_status", "canonical", "ledger_start",
        "positions", "data_limitations",
    }
    if set(derived) != required:
        raise HoldingsCampaignCompositionIntegrityError(
            "position authority fields do not match the canonical contract"
        )
    if derived["derivation_status"] != "OK":
        raise HoldingsCampaignCompositionIntegrityError(
            "position derivation did not complete"
        )
    if type(derived["canonical"]) is not bool:
        raise HoldingsCampaignCompositionIntegrityError(
            "position canonical flag must be bool"
        )
    if type(derived["positions"]) is not list:
        raise HoldingsCampaignCompositionIntegrityError(
            "positions must be a list"
        )

    positions = [_validate_position(value) for value in derived["positions"]]
    if (
        derived["bootstrap_status"] != "BOOTSTRAPPED"
        or derived["canonical"] is not True
    ):
        return {
            "schema_version": SCHEMA_VERSION,
            "evaluation_status": "NOT_EVALUATED",
            "canonical": False,
            "reason_codes": ["POSITION_LEDGER_NOT_BOOTSTRAPPED"],
            "items": [],
            "total_holdings": 0,
        }

    raw_campaigns = campaign_reader()
    if type(raw_campaigns) is not list:
        raise HoldingsCampaignCompositionIntegrityError(
            "campaign authority result must be a list"
        )
    campaigns = [_validate_campaign(record) for record in raw_campaigns]
    current = [
        campaign for campaign in campaigns
        if campaign["status"] in CURRENT_CAMPAIGN_STATUSES
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    seen_campaign_ids: set[str] = set()
    for campaign in current:
        if campaign["campaign_id"] in seen_campaign_ids:
            raise HoldingsCampaignCompositionIntegrityError(
                "duplicate campaign identity"
            )
        seen_campaign_ids.add(campaign["campaign_id"])
        grouped.setdefault(campaign["security_code"], []).append(campaign)
    for records in grouped.values():
        records.sort(key=lambda item: (item["created_at"], item["campaign_id"]))

    items: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for position in positions:
        if position["holding"]["status"] != "OPEN":
            continue
        code = position["security_code"]
        if code in seen_codes:
            raise HoldingsCampaignCompositionIntegrityError(
                "duplicate open holding security identity"
            )
        seen_codes.add(code)
        matched = [
            _adapt_campaign(campaign, binding_reader)
            for campaign in grouped.get(code, [])
        ]
        if not matched:
            composition_status = "UNASSIGNED_HOLDING"
            allocation_status = "NOT_APPLICABLE"
        elif len(matched) == 1:
            composition_status = "ASSIGNED_HOLDING"
            allocation_status = "UNKNOWN"
        else:
            composition_status = "MULTIPLE_CAMPAIGNS_UNALLOCATED"
            allocation_status = "UNKNOWN"
        items.append({
            "item_kind": "HOLDING_COMPOSITION",
            **position,
            "composition_status": composition_status,
            "campaigns": matched,
            "allocation_status": allocation_status,
        })
    items.sort(key=lambda item: item["security_code"])

    return deepcopy({
        "schema_version": SCHEMA_VERSION,
        "evaluation_status": "EVALUATED",
        "canonical": True,
        "reason_codes": [],
        "items": items,
        "total_holdings": len(items),
    })


__all__ = [
    "CURRENT_CAMPAIGN_STATUSES",
    "HoldingsCampaignCompositionError",
    "HoldingsCampaignCompositionIntegrityError",
    "SCHEMA_VERSION",
    "assemble_holdings_campaign_composition",
]
