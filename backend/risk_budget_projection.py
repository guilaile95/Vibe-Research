"""Risk Budget & Risk Allowed Cap Projection Core v0.1 (P0-RB1).

Answers one question only:

> For Security + Strategy + Campaign, given explicit Account NAV and explicit
> Entry-to-Invalidation Distance under a pinned Risk Budget Policy, what is the
> maximum risk capital this Campaign may expose (Risk Allowed Cap)?

```text
RISK ALLOWED CAP
=
risk constraint (notional)
```

Not Asset Optimal Position, Portfolio Adjusted Position, Recommended Position,
Executable Quantity, BUY/SELL, stop-loss discovery, or NAV engine.

North Star Capital-First formula:

```text
risk_allowed_cap_notional
=
account_nav × risk_budget_ratio ÷ entry_to_invalidation_distance_ratio
```

Authority boundary:

- Policy owns strategy → risk_budget_ratio / policy_backstop_ratio only.
- Cap owns NAV + budget + explicit invalidation distance → risk-only notional.
- Backstop is policy comparison only; never substitutes invalidation distance
  and never silently clamps the cap.
- Cap > NAV is retained raw (portfolio constraints are other authorities).

Pure domain: no I/O / SQLite / filesystem / env / network / FastAPI / AI /
wall clock / persistence.
"""

from __future__ import annotations

import copy
import math
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

SCHEMA_VERSION = "risk_budget.projection.v0.1"
AUTHORITY_REF = "rb:risk_budget_projection:v0.1"

POLICY_VERSION_V01 = "rb.risk_budget.v0.1"
POLICY_AUTHORITY_REF_V01 = "rb:risk_budget_policy:v0.1"

VALID_STRATEGIES: tuple[str, ...] = ("SHORT", "SWING", "MEDIUM")

NAV_BASES: tuple[str, ...] = ("OFFICIAL_SETTLED", "ESTIMATED_INTRADAY")

CAP_EVALUATIONS: tuple[str, ...] = (
    "EVALUATED",
    "NOT_EVALUATED",
    "ERROR",
)

BACKSTOP_COMPARISONS: tuple[str, ...] = (
    "WITHIN_BACKSTOP",
    "AT_BACKSTOP",
    "BEYOND_BACKSTOP",
)

# Frozen v0.1 policy table (ratios as exact Decimal strings).
# Do not silent-mutate; calibration requires a new policy_version.
_POLICY_V01: Mapping[str, Mapping[str, Decimal]] = {
    "SHORT": {
        "risk_budget_ratio": Decimal("0.0075"),
        "policy_backstop_ratio": Decimal("0.07"),
    },
    "SWING": {
        "risk_budget_ratio": Decimal("0.0100"),
        "policy_backstop_ratio": Decimal("0.12"),
    },
    "MEDIUM": {
        "risk_budget_ratio": Decimal("0.0125"),
        "policy_backstop_ratio": Decimal("0.20"),
    },
}

_POLICY_REGISTRY: Mapping[str, Mapping[str, Mapping[str, Decimal]]] = {
    POLICY_VERSION_V01: _POLICY_V01,
}

_POLICY_AUTHORITY_REF_BY_VERSION: Mapping[str, str] = {
    POLICY_VERSION_V01: POLICY_AUTHORITY_REF_V01,
}

_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")

_AS_OF_UTC_FORMS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}\+00:00$"),
)

# Action vocabulary that must never appear as this authority's outputs.
_FORBIDDEN_ACTION_VOCAB: frozenset[str] = frozenset(
    {
        "BUY NOW",
        "BUY_SMALL",
        "BUY SMALL",
        "SCALE IN",
        "SCALE_IN",
        "WAIT",
        "HOLD",
        "WATCH TO REDUCE",
        "WATCH_TO_REDUCE",
        "REDUCE",
        "EXIT",
        "AVOID",
        "THESIS_INVALIDATED",
    }
)


class RiskBudgetError(Exception):
    """Risk budget domain base error."""


class RiskBudgetValidationError(RiskBudgetError, ValueError):
    """Illegal caller input / contract violation → fail closed."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_nonempty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RiskBudgetValidationError(f"{field} must be a non-empty string")
    if value != value.strip():
        raise RiskBudgetValidationError(
            f"{field} must not have leading/trailing whitespace"
        )
    return value


def _require_security_code(value: object) -> str:
    code = _require_nonempty_str(value, "security_code")
    if _SECURITY_CODE_RE.fullmatch(code) is None:
        raise RiskBudgetValidationError(
            "security_code must be a 6-digit A-share code"
        )
    return code


def _require_strategy(value: object) -> str:
    strategy = _require_nonempty_str(value, "strategy")
    if strategy not in VALID_STRATEGIES:
        raise RiskBudgetValidationError(
            f"strategy must be one of {VALID_STRATEGIES}, got {strategy!r}"
        )
    return strategy


def _require_campaign_id(value: object) -> str:
    campaign_id = _require_nonempty_str(value, "campaign_id")
    if _CAMPAIGN_ID_RE.fullmatch(campaign_id) is None:
        raise RiskBudgetValidationError(
            "campaign_id must match campaign_<32 lowercase hex>"
        )
    return campaign_id


def _require_as_of(value: object) -> str:
    as_of = _require_nonempty_str(value, "as_of")
    if not any(p.fullmatch(as_of) for p in _AS_OF_UTC_FORMS):
        raise RiskBudgetValidationError(
            "as_of must be a UTC zero-offset instant "
            "(...Z or ...+00:00); wall clock is forbidden"
        )
    try:
        dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RiskBudgetValidationError(
            f"as_of is not a parseable UTC instant: {as_of!r}"
        ) from exc
    if dt.tzinfo is None or dt.utcoffset() is None or dt.utcoffset().total_seconds() != 0:
        raise RiskBudgetValidationError(
            "as_of must be zero-offset UTC (Z or +00:00)"
        )
    return as_of


def _require_policy_version(value: object) -> str:
    return _require_nonempty_str(value, "policy_version")


def _require_nav_basis(value: object) -> str:
    basis = _require_nonempty_str(value, "nav_basis")
    if basis not in NAV_BASES:
        raise RiskBudgetValidationError(
            f"nav_basis must be one of {NAV_BASES}, got {basis!r}"
        )
    return basis


def _require_authority_refs(value: object, field: str) -> list[str]:
    if value is None:
        raise RiskBudgetValidationError(f"{field} is required")
    if not isinstance(value, (list, tuple)):
        raise RiskBudgetValidationError(
            f"{field} must be a list/tuple of strings"
        )
    if len(value) == 0:
        raise RiskBudgetValidationError(
            f"{field} must be non-empty for evaluated risk-cap inputs "
            "(naked self-asserted proof rejected; refs are provenance "
            "witnesses, not verified bindings)"
        )
    refs: list[str] = []
    for i, ref in enumerate(value):
        if not isinstance(ref, str) or not ref.strip() or ref != ref.strip():
            raise RiskBudgetValidationError(
                f"{field}[{i}] must be a non-empty stripped string"
            )
        refs.append(ref)
    return refs


def _to_decimal_positive(value: object, field: str) -> Decimal:
    """Strict positive finite Decimal (rejects bool, NaN, Inf, <=0)."""
    if isinstance(value, bool) or value is None:
        raise RiskBudgetValidationError(
            f"{field} must be a positive finite number, got {value!r}"
        )
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RiskBudgetValidationError(
                f"{field} must be finite (NaN/Infinity rejected)"
            )
    try:
        if isinstance(value, Decimal):
            dec = value
        elif isinstance(value, int):
            dec = Decimal(value)
        elif isinstance(value, str):
            s = value.strip()
            if not s or s != value:
                raise RiskBudgetValidationError(
                    f"{field} string must be non-empty without outer whitespace"
                )
            dec = Decimal(s)
        elif isinstance(value, float):
            # Exact binary float → Decimal via str for reproducibility of
            # common decimal literals (e.g. 1000000.0); still reject non-finite.
            dec = Decimal(str(value))
        else:
            raise RiskBudgetValidationError(
                f"{field} must be int/str/float/Decimal, got {type(value).__name__}"
            )
    except (InvalidOperation, ValueError) as exc:
        raise RiskBudgetValidationError(
            f"{field} is not a valid decimal number: {value!r}"
        ) from exc

    if not dec.is_finite():
        raise RiskBudgetValidationError(
            f"{field} must be finite (NaN/Infinity rejected)"
        )
    if dec <= 0:
        raise RiskBudgetValidationError(f"{field} must be > 0, got {dec}")
    return dec


def _decimal_to_str(value: Decimal) -> str:
    """Canonical non-scientific decimal string (exact, no forced money quantize)."""
    # normalize() collapses trailing zeros in exponent form; use format that
    # preserves exact value without scientific notation.
    s = format(value, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s else "0"


def _backstop_comparison(distance: Decimal, backstop: Decimal) -> str:
    if distance < backstop:
        return "WITHIN_BACKSTOP"
    if distance == backstop:
        return "AT_BACKSTOP"
    return "BEYOND_BACKSTOP"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def project_risk_budget(
    *,
    security_code: str,
    strategy: str,
    campaign_id: str,
    as_of: str,
    policy_version: str,
    account_nav: object,
    nav_basis: str,
    nav_authority_refs: object,
    entry_to_invalidation_distance_ratio: object,
    invalidation_authority_refs: object,
) -> dict[str, Any]:
    """Project Campaign Risk Allowed Cap from explicit NAV + distance + policy.

    ``policy_version`` is required (no default / latest / as_of selection).
    Unknown but well-formed policy_version → cap_evaluation NOT_EVALUATED
    (no implicit latest). Illegal inputs → RiskBudgetValidationError.

    Returns a detached dict. Never mutates inputs. Never reads wall clock.
    """
    sec = _require_security_code(security_code)
    strat = _require_strategy(strategy)
    camp = _require_campaign_id(campaign_id)
    as_of_s = _require_as_of(as_of)
    version = _require_policy_version(policy_version)
    basis = _require_nav_basis(nav_basis)

    # Provenance witnesses required whenever we attempt formal evaluation.
    nav_refs = _require_authority_refs(nav_authority_refs, "nav_authority_refs")
    inv_refs = _require_authority_refs(
        invalidation_authority_refs, "invalidation_authority_refs"
    )

    nav = _to_decimal_positive(account_nav, "account_nav")
    distance = _to_decimal_positive(
        entry_to_invalidation_distance_ratio,
        "entry_to_invalidation_distance_ratio",
    )

    # Unknown policy: honest NOT_EVALUATED — never fall back to latest.
    table = _POLICY_REGISTRY.get(version)
    if table is None:
        result = {
            "schema_version": SCHEMA_VERSION,
            "authority_ref": AUTHORITY_REF,
            "policy_version": version,
            "policy_authority_ref": None,
            "security_code": sec,
            "strategy": strat,
            "campaign_id": camp,
            "as_of": as_of_s,
            "cap_evaluation": "NOT_EVALUATED",
            "reason_codes": ["POLICY_VERSION_NOT_AVAILABLE"],
            "account_nav": _decimal_to_str(nav),
            "nav_basis": basis,
            "entry_to_invalidation_distance_ratio": _decimal_to_str(distance),
            "risk_budget_ratio": None,
            "policy_backstop_ratio": None,
            "risk_allowed_cap_notional": None,
            "risk_allowed_cap_nav_ratio": None,
            "backstop_comparison": None,
            "nav_authority_refs": list(nav_refs),
            "invalidation_authority_refs": list(inv_refs),
            "authority_refs": [AUTHORITY_REF] + list(nav_refs) + list(inv_refs),
            "explainability": {
                "why_this_cap": "POLICY_VERSION_NOT_AVAILABLE",
                "formula": (
                    "account_nav × risk_budget_ratio "
                    "÷ entry_to_invalidation_distance_ratio"
                ),
                "note": (
                    "as_of does not select policy_version; "
                    "no implicit latest policy"
                ),
            },
        }
        return copy.deepcopy(result)

    try:
        row = table[strat]
        budget = row["risk_budget_ratio"]
        backstop = row["policy_backstop_ratio"]
    except KeyError as exc:
        # Integrity: known policy must cover all VALID_STRATEGIES.
        raise RiskBudgetValidationError(
            f"policy {version!r} missing strategy {strat!r}"
        ) from exc

    # Exact Decimal division — no silent clamp to NAV, no backstop substitute.
    cap = (nav * budget) / distance
    cap_nav_ratio = cap / nav
    comparison = _backstop_comparison(distance, backstop)
    policy_ref = _POLICY_AUTHORITY_REF_BY_VERSION[version]

    why = (
        f"{strat} risk_budget_ratio={_decimal_to_str(budget)}; "
        f"entry_to_invalidation_distance_ratio={_decimal_to_str(distance)}; "
        f"account_nav={_decimal_to_str(nav)}; "
        f"risk_allowed_cap_notional="
        f"{_decimal_to_str(nav)}×{_decimal_to_str(budget)}"
        f"÷{_decimal_to_str(distance)}={_decimal_to_str(cap)}"
    )

    authority_refs: list[str] = [AUTHORITY_REF, policy_ref]
    for ref in nav_refs + inv_refs:
        if ref not in authority_refs:
            authority_refs.append(ref)

    result = {
        "schema_version": SCHEMA_VERSION,
        "authority_ref": AUTHORITY_REF,
        "policy_version": version,
        "policy_authority_ref": policy_ref,
        "security_code": sec,
        "strategy": strat,
        "campaign_id": camp,
        "as_of": as_of_s,
        "cap_evaluation": "EVALUATED",
        "reason_codes": ["RISK_ALLOWED_CAP_COMPUTED"],
        "account_nav": _decimal_to_str(nav),
        "nav_basis": basis,
        "entry_to_invalidation_distance_ratio": _decimal_to_str(distance),
        "risk_budget_ratio": _decimal_to_str(budget),
        "policy_backstop_ratio": _decimal_to_str(backstop),
        "risk_allowed_cap_notional": _decimal_to_str(cap),
        "risk_allowed_cap_nav_ratio": _decimal_to_str(cap_nav_ratio),
        "backstop_comparison": comparison,
        "nav_authority_refs": list(nav_refs),
        "invalidation_authority_refs": list(inv_refs),
        "authority_refs": authority_refs,
        "explainability": {
            "why_this_cap": why,
            "formula": (
                "account_nav × risk_budget_ratio "
                "÷ entry_to_invalidation_distance_ratio"
            ),
            "backstop_role": (
                "POLICY_COMPARISON_ONLY; "
                "BACKSTOP_NE_DEFAULT_INVALIDATION; "
                "NO_SILENT_CLAMP; "
                "NO_SELL_ACTION"
            ),
            "cap_semantics": (
                "RISK_CONSTRAINT_NOTIONAL; "
                "NE_ASSET_OPTIMAL; "
                "NE_PORTFOLIO_ADJUSTED; "
                "NE_RECOMMENDED_POSITION; "
                "NE_EXECUTABLE_QUANTITY; "
                "NO_NAV_PORTFOLIO_CLAMP"
            ),
            "provenance": (
                "authority_refs are provenance witnesses only; "
                "UPSTREAM_AUTHORITY_BINDING_VERIFIED=NO; "
                "RUNTIME_AUTHORITY_BINDING=OUT_OF_SCOPE"
            ),
        },
    }

    # Fail closed if any forbidden action vocabulary leaked into output values.
    flat_values = []
    for k, v in result.items():
        if isinstance(v, str):
            flat_values.append(v)
        elif isinstance(v, list):
            flat_values.extend(x for x in v if isinstance(x, str))
    for token in _FORBIDDEN_ACTION_VOCAB:
        for v in flat_values:
            if v == token:
                raise RiskBudgetValidationError(
                    f"internal integrity: forbidden action token {token!r}"
                )

    return copy.deepcopy(result)
