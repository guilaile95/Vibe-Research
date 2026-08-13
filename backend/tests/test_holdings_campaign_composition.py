"""P0-DI2A holdings -> Campaign composition service contract.

These tests exercise only injected read authorities.  They deliberately do not
open the real position or Campaign stores: the composition is a detached,
read-only projection and must never manufacture allocation facts.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

import pytest

import campaign_service
import holdings_campaign_composition as composition
import position_reality_service


SCHEMA_VERSION = "holdings-campaign-composition.v0.1"


def _position(
    code: str,
    *,
    name: str | None = None,
    shares: int = 100,
    cost_basis: float | None = 150_000.0,
    avg_cost: float | None = 1_500.0,
    status: str = "OPEN",
    origin: str = "PRE_VIBE",
    cost_known: bool = True,
) -> dict[str, Any]:
    return {
        "code": code,
        "name": name or code,
        "shares": shares,
        "cost_basis": cost_basis,
        "avg_cost": avg_cost,
        "status": status,
        "origin": origin,
        "cost_known": cost_known,
    }


def _derived(
    *positions: dict[str, Any],
    canonical: bool = True,
    bootstrap_status: str = "BOOTSTRAPPED",
    derivation_status: str = "OK",
) -> dict[str, Any]:
    return {
        "derivation_status": derivation_status,
        "bootstrap_status": bootstrap_status,
        "canonical": canonical,
        "ledger_start": {
            "ledger_start_at": "2026-01-01T00:00:00.000000Z",
            "opening_cash": None,
            "pre_vibe_history": "UNKNOWN",
            "bootstrapped_at": "2026-01-01T00:00:00.000000Z",
        }
        if canonical
        else None,
        "positions": list(positions),
        "data_limitations": [],
    }


def _campaign(
    seed: int,
    code: str,
    *,
    strategy: str = "SWING",
    status: str = "ACTIVE",
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "campaign_id": f"campaign_{seed:032x}",
        "security_code": code,
        "strategy": strategy,
        "status": status,
        "created_at": created_at or f"2026-08-01T00:00:{seed:02d}.000000Z",
    }


def _binding(seed: int, campaign: dict[str, Any]) -> dict[str, Any]:
    return {
        "campaign_id": campaign["campaign_id"],
        "thesis_id": f"{seed:032x}",
        "thesis_revision_at_bind": seed,
        "campaign_strategy_at_bind": campaign["strategy"],
        "bound_at": f"2026-08-02T00:00:{seed:02d}.000000Z",
    }


def _readers(
    derived: dict[str, Any],
    campaigns: list[dict[str, Any]] | None = None,
    bindings: dict[str, dict[str, Any]] | None = None,
) -> tuple[Callable[[], dict[str, Any]], Callable[..., list[dict[str, Any]]], Callable[[str], dict[str, Any]]]:
    campaign_rows = campaigns or []
    binding_rows = bindings or {}

    def position_reader() -> dict[str, Any]:
        return derived

    def campaign_reader(**filters: Any) -> list[dict[str, Any]]:
        rows = campaign_rows
        for key, value in filters.items():
            if value is not None:
                rows = [row for row in rows if row.get(key) == value]
        return rows

    def binding_reader(campaign_id: str) -> dict[str, Any]:
        try:
            return binding_rows[campaign_id]
        except KeyError as exc:
            raise campaign_service.ThesisBindingNotFoundError(
                f"campaign {campaign_id} has no thesis binding"
            ) from exc

    return position_reader, campaign_reader, binding_reader


def _assemble(
    derived: dict[str, Any],
    campaigns: list[dict[str, Any]] | None = None,
    bindings: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    position_reader, campaign_reader, binding_reader = _readers(
        derived, campaigns, bindings
    )
    return composition.assemble_holdings_campaign_composition(
        position_reader=position_reader,
        campaign_reader=campaign_reader,
        binding_reader=binding_reader,
    )


def test_canonical_open_position_with_active_campaign_exact_shape() -> None:
    campaign = _campaign(1, "600519")
    binding = _binding(1, campaign)

    assert _assemble(
        _derived(_position("600519", name="贵州茅台")),
        [campaign],
        {campaign["campaign_id"]: binding},
    ) == {
        "schema_version": SCHEMA_VERSION,
        "evaluation_status": "EVALUATED",
        "canonical": True,
        "reason_codes": [],
        "items": [
            {
                "item_kind": "HOLDING_COMPOSITION",
                "security_code": "600519",
                "security_name": "贵州茅台",
                "holding": {
                    "status": "OPEN",
                    "shares": 100,
                    "cost_basis": 150_000.0,
                    "avg_cost": 1_500.0,
                    "cost_known": True,
                    "origin": "PRE_VIBE",
                },
                "composition_status": "ASSIGNED_HOLDING",
                "campaigns": [
                    {
                        **campaign,
                        "thesis_binding_status": "BOUND",
                        "thesis_binding": {
                            "thesis_id": binding["thesis_id"],
                            "thesis_revision_at_bind": 1,
                            "campaign_strategy_at_bind": "SWING",
                            "bound_at": binding["bound_at"],
                        },
                    }
                ],
                "allocation_status": "UNKNOWN",
            }
        ],
        "total_holdings": 1,
    }


def test_open_position_without_current_campaign_is_unassigned_without_fake_identity() -> None:
    result = _assemble(_derived(_position("000001", name="平安银行")))
    item = result["items"][0]

    assert item["composition_status"] == "UNASSIGNED_HOLDING"
    assert item["campaigns"] == []
    assert item["allocation_status"] == "NOT_APPLICABLE"
    assert "campaign_id" not in item
    assert "strategy" not in item
    assert "thesis_id" not in item


@pytest.mark.parametrize("inactive_status", ["DRAFT", "RESEARCHING", "PRE-ENTRY", "CLOSED"])
def test_inactive_campaign_does_not_assign_holding(inactive_status: str) -> None:
    inactive = _campaign(2, "600519", status=inactive_status)

    item = _assemble(_derived(_position("600519")), [inactive])["items"][0]

    assert item["composition_status"] == "UNASSIGNED_HOLDING"
    assert item["campaigns"] == []


def test_reducing_campaign_is_current() -> None:
    reducing = _campaign(3, "600519", status="REDUCING")
    item = _assemble(_derived(_position("600519")), [reducing])["items"][0]

    assert item["composition_status"] == "ASSIGNED_HOLDING"
    assert [row["campaign_id"] for row in item["campaigns"]] == [
        reducing["campaign_id"]
    ]


def test_multiple_current_campaigns_are_related_but_explicitly_unallocated() -> None:
    later_id = _campaign(
        20,
        "600519",
        strategy="MEDIUM",
        status="REDUCING",
        created_at="2026-08-03T00:00:00.000000Z",
    )
    same_time_high_id = _campaign(
        19,
        "600519",
        strategy="SHORT",
        created_at="2026-08-01T00:00:00.000000Z",
    )
    same_time_low_id = _campaign(
        18,
        "600519",
        strategy="SWING",
        created_at="2026-08-01T00:00:00.000000Z",
    )
    item = _assemble(
        _derived(_position("600519", shares=300)),
        [later_id, same_time_high_id, same_time_low_id],
    )["items"][0]

    assert item["composition_status"] == "MULTIPLE_CAMPAIGNS_UNALLOCATED"
    assert item["allocation_status"] == "UNKNOWN"
    assert [row["campaign_id"] for row in item["campaigns"]] == [
        same_time_low_id["campaign_id"],
        same_time_high_id["campaign_id"],
        later_id["campaign_id"],
    ]
    assert item["holding"]["shares"] == 300

    forbidden = {
        "shares",
        "campaign_shares",
        "campaign_cost_basis",
        "campaign_market_value",
        "campaign_capital",
        "campaign_pnl",
        "ownership_pct",
        "allocation_pct",
    }
    for campaign_row in item["campaigns"]:
        assert forbidden.isdisjoint(campaign_row)


def test_unbound_current_campaign_remains_related() -> None:
    campaign = _campaign(4, "600519")
    item = _assemble(_derived(_position("600519")), [campaign])["items"][0]

    assert item["composition_status"] == "ASSIGNED_HOLDING"
    assert item["campaigns"] == [
        {
            **campaign,
            "thesis_binding_status": "NOT_BOUND",
            "thesis_binding": None,
        }
    ]


def test_unknown_cost_stays_unknown_and_closed_positions_are_excluded() -> None:
    result = _assemble(
        _derived(
            _position(
                "000001",
                cost_basis=None,
                avg_cost=None,
                cost_known=False,
                origin="MIXED",
            ),
            _position(
                "600519",
                shares=0,
                cost_basis=0.0,
                avg_cost=None,
                status="CLOSED",
            ),
        )
    )

    assert [item["security_code"] for item in result["items"]] == ["000001"]
    assert result["items"][0]["holding"] == {
        "status": "OPEN",
        "shares": 100,
        "cost_basis": None,
        "avg_cost": None,
        "cost_known": False,
        "origin": "MIXED",
    }


def test_noncanonical_position_authority_is_not_evaluated_with_no_items() -> None:
    result = _assemble(
        _derived(
            _position("600519"),
            canonical=False,
            bootstrap_status="NOT_BOOTSTRAPPED",
        ),
        [_campaign(5, "600519")],
    )

    assert result == {
        "schema_version": SCHEMA_VERSION,
        "evaluation_status": "NOT_EVALUATED",
        "canonical": False,
        "reason_codes": ["POSITION_LEDGER_NOT_BOOTSTRAPPED"],
        "items": [],
        "total_holdings": 0,
    }


def test_position_derivation_error_becomes_typed_composition_error() -> None:
    cause = position_reality_service.PositionDerivationError("sensitive ledger detail")

    def failing_position_reader() -> dict[str, Any]:
        raise cause

    with pytest.raises(composition.HoldingsCampaignCompositionError) as exc_info:
        composition.assemble_holdings_campaign_composition(
            position_reader=failing_position_reader,
            campaign_reader=lambda **_kwargs: [],
            binding_reader=lambda _campaign_id: {},
        )

    assert exc_info.value.__cause__ is cause


def test_root_and_nested_sort_are_deterministic() -> None:
    campaign_b = _campaign(9, "600519", created_at="2026-08-02T00:00:00.000000Z")
    campaign_a = _campaign(8, "600519", created_at="2026-08-01T00:00:00.000000Z")
    result = _assemble(
        _derived(_position("600519"), _position("000001")),
        [campaign_b, campaign_a],
    )

    assert [item["security_code"] for item in result["items"]] == ["000001", "600519"]
    assert [row["campaign_id"] for row in result["items"][1]["campaigns"]] == [
        campaign_a["campaign_id"],
        campaign_b["campaign_id"],
    ]


def test_projection_is_idempotent_detached_and_uses_only_injected_readers() -> None:
    position_source = _derived(_position("600519"))
    campaign = _campaign(10, "600519")
    campaign_source = [campaign]
    binding_source = {campaign["campaign_id"]: _binding(10, campaign)}
    position_before = deepcopy(position_source)
    campaign_before = deepcopy(campaign_source)
    binding_before = deepcopy(binding_source)
    calls = {"position": 0, "campaign": 0, "binding": 0}

    def position_reader() -> dict[str, Any]:
        calls["position"] += 1
        return position_source

    def campaign_reader(**filters: Any) -> list[dict[str, Any]]:
        calls["campaign"] += 1
        return [
            row
            for row in campaign_source
            if all(value is None or row.get(key) == value for key, value in filters.items())
        ]

    def binding_reader(campaign_id: str) -> dict[str, Any]:
        calls["binding"] += 1
        return binding_source[campaign_id]

    kwargs = {
        "position_reader": position_reader,
        "campaign_reader": campaign_reader,
        "binding_reader": binding_reader,
    }
    first = composition.assemble_holdings_campaign_composition(**kwargs)
    second = composition.assemble_holdings_campaign_composition(**kwargs)

    assert first == second
    assert first is not second
    first["items"][0]["holding"]["shares"] = 999
    first["items"][0]["campaigns"][0]["strategy"] = "MUTATED"

    assert position_source == position_before
    assert campaign_source == campaign_before
    assert binding_source == binding_before
    assert second["items"][0]["holding"]["shares"] == 100
    assert second["items"][0]["campaigns"][0]["strategy"] == "SWING"
    assert calls["position"] == 2
    assert calls["binding"] == 2
    assert calls["campaign"] >= 2
