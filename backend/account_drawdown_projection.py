"""Account Drawdown State Projection Core v0.1 (P0-DD1).

Answers one question only:

> Given an upstream-proven current Account NAV and recent NAV Peak, what
> is the current account drawdown, and which North-Star Drawdown State
> does it belong to?

```text
DRAWDOWN STATE
=
PORTFOLIO RISK CONTEXT
!=
INVESTMENT ACTION
```

Formal formula:

```text
drawdown_ratio
=
(recent_nav_peak - current_account_nav) / recent_nav_peak
```

This module is not a NAV engine and not a Peak engine. It consumes
explicit upstream facts only.

Not BUY/SELL/HOLD/REDUCE/EXIT, Action Envelope, Risk Budget mutation,
position sizing, Asset View, or Trade View.

Numeric contract (v0.1):

```text
DETERMINISTIC FIXED-CONTEXT DECIMAL PROJECTION
GLOBAL_DECIMAL_CONTEXT_DEPENDENCE = NO
HIDDEN_PERCENT_ROUNDING = NO
```

Non-terminating ratios (e.g. 2/3) are projected under a module-owned
frozen Decimal context. This is not a claim of mathematically exact
infinite-decimal representation.

Pure domain: no I/O / SQLite / filesystem / env / network / FastAPI / AI /
wall clock / persistence. Does not import Risk Budget, Sell Engine,
CDA/DDA/CCD, account_reality, or portfolio_advice.
"""

from __future__ import annotations

import copy
import math
import re
from datetime import datetime
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from typing import Any

SCHEMA_VERSION = "account_drawdown.projection.v0.1"
AUTHORITY_REF = "dd:account_drawdown_projection:v0.1"

POLICY_VERSION_V01 = "dd.account_drawdown.v0.1"
POLICY_AUTHORITY_REF_V01 = "dd:account_drawdown_policy:v0.1"

# Frozen v0.1 numeric context: module-owned, versioned, independent of the
# process-global Decimal context. Precision is finite and well above v0.1
# threshold magnitude; it is not the CPython default of 28, not
# input-length-adaptive, and not a percent-rounding contract.
NUMERIC_CONTEXT_VERSION = "dd.numeric.v0.1"
NUMERIC_PRECISION = 50
NUMERIC_ROUNDING = ROUND_HALF_EVEN
ACCOUNT_DRAWDOWN_DECIMAL_CONTEXT = Context(
    prec=NUMERIC_PRECISION,
    rounding=NUMERIC_ROUNDING,
    Emin=-999999,
    Emax=999999,
    capitals=1,
    clamp=0,
    flags=[],
    traps=[InvalidOperation, DivisionByZero, Overflow],
)

NAV_BASES: tuple[str, ...] = ("OFFICIAL_SETTLED", "ESTIMATED_INTRADAY")

DRAWDOWN_STATES: tuple[str, ...] = (
    "NORMAL",
    "CAUTION",
    "HIGH_RISK",
    "DEFENSIVE",
    "CRITICAL_DRAWDOWN",
)

DRAWDOWN_EVALUATIONS: tuple[str, ...] = (
    "EVALUATED",
    "NOT_EVALUATED",
    "ERROR",
)

# Inclusive lower bounds. NORMAL is [0, 0.10); CRITICAL is [0.30, +inf).
_THRESHOLD_CAUTION = Decimal("0.10")
_THRESHOLD_HIGH_RISK = Decimal("0.18")
_THRESHOLD_DEFENSIVE = Decimal("0.25")
_THRESHOLD_CRITICAL = Decimal("0.30")

_POLICY_REGISTRY: dict[str, str] = {
    POLICY_VERSION_V01: POLICY_AUTHORITY_REF_V01,
}

_AS_OF_UTC_FORMS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}\+00:00$"),
)

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
        "RESEARCH MORE",
        "RESEARCH_MORE",
    }
)


class AccountDrawdownError(Exception):
    """Account drawdown domain base error."""


class AccountDrawdownValidationError(AccountDrawdownError, ValueError):
    """Illegal caller input / contract violation → fail closed."""


def _require_nonempty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AccountDrawdownValidationError(f"{field} must be a non-empty string")
    if value != value.strip():
        raise AccountDrawdownValidationError(
            f"{field} must not have leading/trailing whitespace"
        )
    return value


def _require_policy_version(value: object) -> str:
    return _require_nonempty_str(value, "policy_version")


def _require_nav_basis(value: object, field: str) -> str:
    basis = _require_nonempty_str(value, field)
    if basis not in NAV_BASES:
        raise AccountDrawdownValidationError(
            f"{field} must be one of {NAV_BASES}, got {basis!r}"
        )
    return basis


def _parse_utc_instant(value: object, field: str) -> tuple[str, datetime]:
    raw = _require_nonempty_str(value, field)
    if not any(p.fullmatch(raw) for p in _AS_OF_UTC_FORMS):
        raise AccountDrawdownValidationError(
            f"{field} must be a UTC zero-offset instant "
            "(...Z or ...+00:00); wall clock is forbidden"
        )
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AccountDrawdownValidationError(
            f"{field} is not a parseable UTC instant: {raw!r}"
        ) from exc
    if dt.tzinfo is None or dt.utcoffset() is None or dt.utcoffset().total_seconds() != 0:
        raise AccountDrawdownValidationError(
            f"{field} must be zero-offset UTC (Z or +00:00)"
        )
    return raw, dt


def _require_authority_refs(value: object, field: str) -> list[str]:
    if value is None:
        raise AccountDrawdownValidationError(f"{field} is required")
    if not isinstance(value, (list, tuple)):
        raise AccountDrawdownValidationError(f"{field} must be a list/tuple of strings")
    if len(value) == 0:
        raise AccountDrawdownValidationError(
            f"{field} must be non-empty for formal drawdown inputs "
            "(naked self-asserted proof rejected; refs are provenance "
            "witnesses, not verified bindings)"
        )
    refs: list[str] = []
    for i, ref in enumerate(value):
        if not isinstance(ref, str) or not ref.strip() or ref != ref.strip():
            raise AccountDrawdownValidationError(
                f"{field}[{i}] must be a non-empty stripped string"
            )
        refs.append(ref)
    return refs


def _to_decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise AccountDrawdownValidationError(
            f"{field} must be a finite number, got {value!r}"
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise AccountDrawdownValidationError(
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
                raise AccountDrawdownValidationError(
                    f"{field} string must be non-empty without outer whitespace"
                )
            dec = Decimal(s)
        elif isinstance(value, float):
            dec = Decimal(str(value))
        else:
            raise AccountDrawdownValidationError(
                f"{field} must be int/str/float/Decimal, got {type(value).__name__}"
            )
    except (InvalidOperation, ValueError) as exc:
        raise AccountDrawdownValidationError(
            f"{field} is not a valid decimal number: {value!r}"
        ) from exc
    if not dec.is_finite():
        raise AccountDrawdownValidationError(
            f"{field} must be finite (NaN/Infinity rejected)"
        )
    return dec


def _require_current_nav(value: object) -> Decimal:
    dec = _to_decimal(value, "current_account_nav")
    if dec < 0:
        raise AccountDrawdownValidationError(
            f"current_account_nav must be >= 0, got {dec}"
        )
    return dec


def _require_peak_nav(value: object) -> Decimal:
    dec = _to_decimal(value, "recent_nav_peak")
    if dec <= 0:
        raise AccountDrawdownValidationError(
            f"recent_nav_peak must be > 0, got {dec}"
        )
    return dec


def _decimal_to_str(value: Decimal) -> str:
    """Canonical non-scientific decimal string (no percent rounding)."""
    s = format(value, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s else "0"


def _project_ratio_under_frozen_context(peak: Decimal, current: Decimal) -> Decimal:
    with localcontext(ACCOUNT_DRAWDOWN_DECIMAL_CONTEXT.copy()):
        return (peak - current) / peak


def _state_for_ratio(drawdown: Decimal) -> str:
    if drawdown < _THRESHOLD_CAUTION:
        return "NORMAL"
    if drawdown < _THRESHOLD_HIGH_RISK:
        return "CAUTION"
    if drawdown < _THRESHOLD_DEFENSIVE:
        return "HIGH_RISK"
    if drawdown < _THRESHOLD_CRITICAL:
        return "DEFENSIVE"
    return "CRITICAL_DRAWDOWN"


def _numeric_context_note() -> str:
    return (
        "FROZEN_V0.1; "
        f"prec={NUMERIC_PRECISION}; "
        "ROUND_HALF_EVEN; "
        "GLOBAL_DECIMAL_CONTEXT_DEPENDENCE=NO; "
        "HIDDEN_PERCENT_ROUNDING=NO"
    )


def project_account_drawdown(
    *,
    as_of: str,
    policy_version: str,
    current_account_nav: object,
    current_nav_basis: str,
    current_nav_authority_refs: object,
    recent_nav_peak: object,
    peak_nav_basis: str,
    nav_peak_at: str,
    nav_peak_authority_refs: object,
) -> dict[str, Any]:
    """Project Account Drawdown State from explicit NAV + Peak + policy.

    ``policy_version`` is required (no default / latest / as_of selection).
    Formal EVALUATED requires official current NAV, official peak, known
    policy, and current_account_nav <= recent_nav_peak. ESTIMATED_INTRADAY
    current NAV and non-official peak basis are valid inputs but cannot
    form a formal EVALUATED drawdown in v0.1.

    Returns a detached dict. Never mutates inputs. Never reads wall clock.
    Never depends on process-global Decimal context.
    """
    as_of_s, as_of_dt = _parse_utc_instant(as_of, "as_of")
    peak_at_s, peak_at_dt = _parse_utc_instant(nav_peak_at, "nav_peak_at")
    if peak_at_dt > as_of_dt:
        raise AccountDrawdownValidationError(
            "nav_peak_at must be <= as_of (future peak timestamp rejected)"
        )

    version = _require_policy_version(policy_version)
    current_basis = _require_nav_basis(current_nav_basis, "current_nav_basis")
    peak_basis = _require_nav_basis(peak_nav_basis, "peak_nav_basis")
    current_refs = _require_authority_refs(
        current_nav_authority_refs, "current_nav_authority_refs"
    )
    peak_refs = _require_authority_refs(
        nav_peak_authority_refs, "nav_peak_authority_refs"
    )

    current = _require_current_nav(current_account_nav)
    peak = _require_peak_nav(recent_nav_peak)

    reason_codes: list[str] = []
    policy_ref = _POLICY_REGISTRY.get(version)
    if policy_ref is None:
        reason_codes.append("POLICY_VERSION_NOT_AVAILABLE")

    if current_basis == "ESTIMATED_INTRADAY":
        reason_codes.append("INTRADAY_NAV_QUALITY_NOT_PROVEN")
    if peak_basis != "OFFICIAL_SETTLED":
        reason_codes.append("NAV_PEAK_BASIS_NOT_FORMAL")
    if current > peak:
        reason_codes.append("NAV_PEAK_INCONSISTENT")

    authority_refs = [AUTHORITY_REF]
    if policy_ref is not None:
        authority_refs.append(policy_ref)
    for ref in current_refs + peak_refs:
        if ref not in authority_refs:
            authority_refs.append(ref)

    if reason_codes:
        result = {
            "schema_version": SCHEMA_VERSION,
            "authority_ref": AUTHORITY_REF,
            "policy_version": version,
            "policy_authority_ref": policy_ref,
            "as_of": as_of_s,
            "current_account_nav": _decimal_to_str(current),
            "current_nav_basis": current_basis,
            "recent_nav_peak": _decimal_to_str(peak),
            "peak_nav_basis": peak_basis,
            "nav_peak_at": peak_at_s,
            "drawdown_evaluation": "NOT_EVALUATED",
            "drawdown_ratio": None,
            "drawdown_state": None,
            "reason_codes": list(reason_codes),
            "current_nav_authority_refs": list(current_refs),
            "nav_peak_authority_refs": list(peak_refs),
            "authority_refs": authority_refs,
            "explainability": {
                "why_this_state": "; ".join(reason_codes),
                "formula": (
                    "(recent_nav_peak - current_account_nav) / recent_nav_peak"
                ),
                "note": (
                    "as_of does not select policy_version; "
                    "no implicit latest policy; "
                    "NAV_BASIS_PRESERVED; "
                    "INTRADAY_TO_SETTLED_FALLBACK=NO; "
                    "NO_SILENT_PEAK_REPAIR; "
                    "RUNTIME_INTRADAY_NAV_QUALITY=OUT_OF_SCOPE; "
                    "DRAWDOWN_STATE_NE_INVESTMENT_ACTION"
                ),
                "numeric_context": _numeric_context_note(),
            },
        }
        return copy.deepcopy(result)

    ratio = _project_ratio_under_frozen_context(peak, current)
    state = _state_for_ratio(ratio)
    why = (
        f"current_account_nav={_decimal_to_str(current)}; "
        f"recent_nav_peak={_decimal_to_str(peak)}; "
        f"drawdown_ratio={_decimal_to_str(ratio)}; "
        f"drawdown_state={state}"
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "authority_ref": AUTHORITY_REF,
        "policy_version": version,
        "policy_authority_ref": policy_ref,
        "as_of": as_of_s,
        "current_account_nav": _decimal_to_str(current),
        "current_nav_basis": current_basis,
        "recent_nav_peak": _decimal_to_str(peak),
        "peak_nav_basis": peak_basis,
        "nav_peak_at": peak_at_s,
        "drawdown_evaluation": "EVALUATED",
        "drawdown_ratio": _decimal_to_str(ratio),
        "drawdown_state": state,
        "reason_codes": ["ACCOUNT_DRAWDOWN_COMPUTED"],
        "current_nav_authority_refs": list(current_refs),
        "nav_peak_authority_refs": list(peak_refs),
        "authority_refs": authority_refs,
        "explainability": {
            "why_this_state": why,
            "formula": (
                "(recent_nav_peak - current_account_nav) / recent_nav_peak"
            ),
            "thresholds": (
                "NORMAL [0, 0.10); "
                "CAUTION [0.10, 0.18); "
                "HIGH_RISK [0.18, 0.25); "
                "DEFENSIVE [0.25, 0.30); "
                "CRITICAL_DRAWDOWN [0.30, +inf)"
            ),
            "cap_semantics": (
                "PORTFOLIO_RISK_CONTEXT; "
                "DRAWDOWN_STATE_NE_INVESTMENT_ACTION; "
                "NO_BUY_SELL_AUTHORITY; "
                "NO_RISK_BUDGET_MUTATION; "
                "NO_POSITION_SIZING"
            ),
            "provenance": (
                "authority_refs are provenance witnesses only; "
                "UPSTREAM_AUTHORITY_BINDING_VERIFIED=NO; "
                "RUNTIME_AUTHORITY_BINDING=OUT_OF_SCOPE"
            ),
            "numeric_context": _numeric_context_note(),
        },
    }

    flat_values: list[str] = []
    for v in result.values():
        if isinstance(v, str):
            flat_values.append(v)
        elif isinstance(v, list):
            flat_values.extend(x for x in v if isinstance(x, str))
    for token in _FORBIDDEN_ACTION_VOCAB:
        if token in flat_values:
            raise AccountDrawdownValidationError(
                f"internal integrity: forbidden action token {token!r}"
            )

    return copy.deepcopy(result)
