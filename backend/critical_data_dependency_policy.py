"""Critical Data Dependency Policy Core v0.1 (P0-DDA1).

Answers one question only:

> For this Security + Strategy + Campaign, given an explicitly pinned
> dependency-policy version, what Strategy-baseline critical-data
> capabilities are required?

```text
DDA1 =
STRATEGY BASELINE DEPENDENCY DEFINITION AUTHORITY
```

Not Critical Data usability, Data Health, Thesis Evidence, Hard Risk, or
Material Change authority.

```text
CRITICAL_DATA_SCOPE_V01 =
STRATEGY_BASELINE_CRITICAL_CONTEXT

BASELINE CRITICAL DATA
!=
ALL DATA NEEDED BY THIS CAMPAIGN
```

Pure domain boundary:
- no I/O, SQLite, filesystem, env, network, FastAPI, AI, wall clock
- no imports of campaign/thesis/frozen/fact-lake/data-health/CCD/RA/DI
- consumes only explicit inputs; policy_version is required (no default)
- parsing supplied UTC as_of is allowed; never read wall clock
- as_of does not select policy version
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = "critical_data_dependency_policy.v0.1"

POLICY_VERSION_V01 = "dda.strategy_dependency.v0.1"
POLICY_AUTHORITY_REF_V01 = "dda:strategy_dependency_policy:v0.1"

VALID_STRATEGIES: tuple[str, ...] = ("SHORT", "SWING", "MEDIUM")

DEPENDENCY_SET_STATES: tuple[str, ...] = (
    "RESOLVED",
    "NOT_EVALUATED",
    "ERROR",
)

# v0.1 stable semantic capability IDs (provider/dataset independent).
CAP_SECURITY_PRICE_REFERENCE = "cap.security.price_reference"
CAP_CONTEXT_MARKET_SECTOR = "cap.context.market_sector"
CAP_SECURITY_DISCLOSURES = "cap.security.disclosures"
CAP_SECURITY_FINANCIALS = "cap.security.financials"

CAPABILITY_IDS_V01: tuple[str, ...] = (
    CAP_SECURITY_PRICE_REFERENCE,
    CAP_CONTEXT_MARKET_SECTOR,
    CAP_SECURITY_DISCLOSURES,
    CAP_SECURITY_FINANCIALS,
)

# Policy order is the contract; do not alphabetically sort.
SHORT_REQUIRED: tuple[str, ...] = (
    CAP_SECURITY_PRICE_REFERENCE,
    CAP_CONTEXT_MARKET_SECTOR,
    CAP_SECURITY_DISCLOSURES,
)
SWING_REQUIRED: tuple[str, ...] = (
    CAP_SECURITY_PRICE_REFERENCE,
    CAP_CONTEXT_MARKET_SECTOR,
    CAP_SECURITY_DISCLOSURES,
)
MEDIUM_REQUIRED: tuple[str, ...] = (
    CAP_SECURITY_PRICE_REFERENCE,
    CAP_SECURITY_DISCLOSURES,
    CAP_SECURITY_FINANCIALS,
)

REASON_DEPENDENCY_POLICY_RESOLVED = "DEPENDENCY_POLICY_RESOLVED"
REASON_POLICY_VERSION_NOT_AVAILABLE = "POLICY_VERSION_NOT_AVAILABLE"
REASON_POLICY_INTEGRITY_ERROR = "POLICY_INTEGRITY_ERROR"

REASON_CODES: tuple[str, ...] = (
    REASON_DEPENDENCY_POLICY_RESOLVED,
    REASON_POLICY_VERSION_NOT_AVAILABLE,
    REASON_POLICY_INTEGRITY_ERROR,
)

_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")

# Strict allowlist of UTC zero-offset instant forms only.
_AS_OF_UTC_FORMS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}Z$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}\+00:00$"),
)

# Internal immutable production registry for the known v0.1 policy.
# Values must remain exact tuples; integrity is validated on module load and
# again on every resolve of the known version.
_POLICY_REGISTRY_V01: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    POLICY_VERSION_V01: {
        "SHORT": SHORT_REQUIRED,
        "SWING": SWING_REQUIRED,
        "MEDIUM": MEDIUM_REQUIRED,
    }
}

_POLICY_AUTHORITY_REF_BY_VERSION: Mapping[str, str] = {
    POLICY_VERSION_V01: POLICY_AUTHORITY_REF_V01,
}


class DependencyPolicyError(Exception):
    """Dependency policy domain base error."""


class DependencyPolicyValidationError(DependencyPolicyError, ValueError):
    """Illegal caller input / contract violation → fail closed."""


def _require_nonempty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DependencyPolicyValidationError(
            f"{field} must be a non-empty string"
        )
    if value != value.strip():
        raise DependencyPolicyValidationError(
            f"{field} must not have leading/trailing whitespace"
        )
    return value


def _require_security_code(value: object) -> str:
    code = _require_nonempty_str(value, "security_code")
    if _SECURITY_CODE_RE.fullmatch(code) is None:
        raise DependencyPolicyValidationError(
            "security_code must be a 6-digit A-share code"
        )
    return code


def _require_strategy(value: object) -> str:
    strategy = _require_nonempty_str(value, "strategy")
    if strategy not in VALID_STRATEGIES:
        raise DependencyPolicyValidationError(
            f"strategy must be one of {VALID_STRATEGIES}, got {strategy!r}"
        )
    return strategy


def _require_campaign_id(value: object) -> str:
    campaign_id = _require_nonempty_str(value, "campaign_id")
    if _CAMPAIGN_ID_RE.fullmatch(campaign_id) is None:
        raise DependencyPolicyValidationError(
            "campaign_id must match campaign_<32 lowercase hex>"
        )
    return campaign_id


def _require_as_of(value: object) -> str:
    """Strict UTC zero-offset instant; preserve exact accepted string."""
    as_of = _require_nonempty_str(value, "as_of")
    if not any(pattern.fullmatch(as_of) for pattern in _AS_OF_UTC_FORMS):
        raise DependencyPolicyValidationError(
            "as_of must be a canonical UTC zero-offset instant "
            "(...Z or ...+00:00); non-zero offsets and naive times are rejected"
        )
    parse_text = as_of[:-1] + "+00:00" if as_of.endswith("Z") else as_of
    try:
        parsed = datetime.fromisoformat(parse_text)
    except ValueError as exc:
        raise DependencyPolicyValidationError(
            f"as_of is not a deterministically parseable UTC instant: {as_of!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise DependencyPolicyValidationError(
            "as_of must be timezone-aware UTC"
        )
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise DependencyPolicyValidationError(
            "as_of must use UTC zero offset only"
        )
    _ = parsed.astimezone(timezone.utc)
    return as_of


def _require_policy_version(value: object) -> str:
    # Missing / empty / whitespace-only is validation failure.
    # Unknown non-empty versions are handled as NOT_EVALUATED by resolve.
    return _require_nonempty_str(value, "policy_version")


def _validate_required_set(
    strategy: str,
    required: object,
    *,
    allowed_capabilities: frozenset[str],
) -> tuple[str, ...]:
    """Validate one strategy entry; return exact tuple or raise integrity error.

    Used both for production registry self-check and adversarial test seam.
    """
    if not isinstance(required, tuple):
        raise RuntimeError(
            f"policy integrity: {strategy} required set must be a tuple"
        )
    if not required:
        raise RuntimeError(
            f"policy integrity: {strategy} required set must be non-empty"
        )
    seen: set[str] = set()
    out: list[str] = []
    for item in required:
        if not isinstance(item, str) or not item.strip() or item != item.strip():
            raise RuntimeError(
                f"policy integrity: {strategy} contains illegal capability id"
            )
        if item not in allowed_capabilities:
            raise RuntimeError(
                f"policy integrity: {strategy} contains unknown capability "
                f"{item!r}"
            )
        if item in seen:
            raise RuntimeError(
                f"policy integrity: {strategy} contains duplicate capability "
                f"{item!r}"
            )
        seen.add(item)
        out.append(item)
    return tuple(out)


def _validate_policy_table(
    table: Mapping[str, object],
    *,
    allowed_capabilities: frozenset[str],
) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(table, Mapping):
        raise RuntimeError("policy integrity: strategy table must be a mapping")
    missing = [s for s in VALID_STRATEGIES if s not in table]
    if missing:
        raise RuntimeError(
            f"policy integrity: missing strategy entr(y/ies): {missing}"
        )
    extra = [key for key in table.keys() if key not in VALID_STRATEGIES]
    if extra:
        raise RuntimeError(
            f"policy integrity: unknown strategy entr(y/ies): {sorted(extra)}"
        )
    validated: dict[str, tuple[str, ...]] = {}
    for strategy in VALID_STRATEGIES:
        validated[strategy] = _validate_required_set(
            strategy,
            table[strategy],
            allowed_capabilities=allowed_capabilities,
        )
    return validated


def _production_allowed_capabilities() -> frozenset[str]:
    return frozenset(CAPABILITY_IDS_V01)


# Fail closed at import if production registry is corrupt.
_VALIDATED_POLICY_REGISTRY_V01: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    POLICY_VERSION_V01: _validate_policy_table(
        _POLICY_REGISTRY_V01[POLICY_VERSION_V01],
        allowed_capabilities=_production_allowed_capabilities(),
    )
}


def _build_output(
    *,
    security_code: str,
    strategy: str,
    campaign_id: str,
    as_of: str,
    policy_version: str,
    dependency_set_state: str,
    dependency_set_authority_refs: tuple[str, ...],
    required_dependency_ids: tuple[str, ...],
    reason_codes: tuple[str, ...],
) -> dict[str, Any]:
    if dependency_set_state not in DEPENDENCY_SET_STATES:
        raise RuntimeError(
            f"internal dependency_set_state invalid: {dependency_set_state!r}"
        )
    # Detached lists for CCD1-friendly consumption (no shared mutables).
    return {
        "schema_version": SCHEMA_VERSION,
        "security_code": security_code,
        "strategy": strategy,
        "campaign_id": campaign_id,
        "as_of": as_of,
        "policy_version": policy_version,
        "dependency_set_state": dependency_set_state,
        "dependency_set_authority_refs": list(dependency_set_authority_refs),
        "required_dependency_ids": list(required_dependency_ids),
        "reason_codes": list(reason_codes),
    }


def resolve_strategy_dependencies(
    *,
    security_code: str,
    strategy: str,
    campaign_id: str,
    as_of: str,
    policy_version: str,
) -> dict[str, Any]:
    """Resolve Strategy-baseline required critical-data capabilities.

    Pure function of explicit identity + pinned policy_version.
    Does not invent requirements from available data. Does not read wall
    clock. Caller cannot inject authority provenance.
    """
    sec = _require_security_code(security_code)
    strat = _require_strategy(strategy)
    camp = _require_campaign_id(campaign_id)
    as_of_value = _require_as_of(as_of)
    version = _require_policy_version(policy_version)

    # Unknown / unsupported non-empty policy version → NOT_EVALUATED.
    if version not in _VALIDATED_POLICY_REGISTRY_V01:
        return _build_output(
            security_code=sec,
            strategy=strat,
            campaign_id=camp,
            as_of=as_of_value,
            policy_version=version,
            dependency_set_state="NOT_EVALUATED",
            dependency_set_authority_refs=(),
            required_dependency_ids=(),
            reason_codes=(REASON_POLICY_VERSION_NOT_AVAILABLE,),
        )

    # Known version: re-validate integrity (no silent repair).
    authority_ref = _POLICY_AUTHORITY_REF_BY_VERSION[version]
    try:
        table = _validate_policy_table(
            _POLICY_REGISTRY_V01[version],
            allowed_capabilities=_production_allowed_capabilities(),
        )
        required = table[strat]
    except RuntimeError:
        return _build_output(
            security_code=sec,
            strategy=strat,
            campaign_id=camp,
            as_of=as_of_value,
            policy_version=version,
            dependency_set_state="ERROR",
            dependency_set_authority_refs=(authority_ref,),
            required_dependency_ids=(),
            reason_codes=(REASON_POLICY_INTEGRITY_ERROR,),
        )

    return _build_output(
        security_code=sec,
        strategy=strat,
        campaign_id=camp,
        as_of=as_of_value,
        policy_version=version,
        dependency_set_state="RESOLVED",
        dependency_set_authority_refs=(authority_ref,),
        required_dependency_ids=required,
        reason_codes=(REASON_DEPENDENCY_POLICY_RESOLVED,),
    )


def _adversarial_resolve_with_registry(
    *,
    security_code: str,
    strategy: str,
    campaign_id: str,
    as_of: str,
    policy_version: str,
    registry: Mapping[str, Mapping[str, object]],
    authority_ref_by_version: Mapping[str, str],
    allowed_capabilities: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Test-only seam for integrity adversarial cases.

    Not part of the public production API surface for callers. Production
    resolve_strategy_dependencies never accepts arbitrary registries.
    """
    sec = _require_security_code(security_code)
    strat = _require_strategy(strategy)
    camp = _require_campaign_id(campaign_id)
    as_of_value = _require_as_of(as_of)
    version = _require_policy_version(policy_version)

    if version not in registry:
        return _build_output(
            security_code=sec,
            strategy=strat,
            campaign_id=camp,
            as_of=as_of_value,
            policy_version=version,
            dependency_set_state="NOT_EVALUATED",
            dependency_set_authority_refs=(),
            required_dependency_ids=(),
            reason_codes=(REASON_POLICY_VERSION_NOT_AVAILABLE,),
        )

    allowed = (
        allowed_capabilities
        if allowed_capabilities is not None
        else _production_allowed_capabilities()
    )
    authority_ref = authority_ref_by_version.get(version)
    try:
        table = _validate_policy_table(
            registry[version],
            allowed_capabilities=allowed,
        )
        required = table[strat]
    except RuntimeError:
        refs: tuple[str, ...]
        if isinstance(authority_ref, str) and authority_ref.strip():
            refs = (authority_ref,)
        else:
            refs = ()
        return _build_output(
            security_code=sec,
            strategy=strat,
            campaign_id=camp,
            as_of=as_of_value,
            policy_version=version,
            dependency_set_state="ERROR",
            dependency_set_authority_refs=refs,
            required_dependency_ids=(),
            reason_codes=(REASON_POLICY_INTEGRITY_ERROR,),
        )

    if not isinstance(authority_ref, str) or not authority_ref.strip():
        # Known version without authority provenance is integrity failure.
        return _build_output(
            security_code=sec,
            strategy=strat,
            campaign_id=camp,
            as_of=as_of_value,
            policy_version=version,
            dependency_set_state="ERROR",
            dependency_set_authority_refs=(),
            required_dependency_ids=(),
            reason_codes=(REASON_POLICY_INTEGRITY_ERROR,),
        )

    return _build_output(
        security_code=sec,
        strategy=strat,
        campaign_id=camp,
        as_of=as_of_value,
        policy_version=version,
        dependency_set_state="RESOLVED",
        dependency_set_authority_refs=(authority_ref,),
        required_dependency_ids=required,
        reason_codes=(REASON_DEPENDENCY_POLICY_RESOLVED,),
    )


__all__ = [
    "SCHEMA_VERSION",
    "POLICY_VERSION_V01",
    "POLICY_AUTHORITY_REF_V01",
    "VALID_STRATEGIES",
    "DEPENDENCY_SET_STATES",
    "CAPABILITY_IDS_V01",
    "CAP_SECURITY_PRICE_REFERENCE",
    "CAP_CONTEXT_MARKET_SECTOR",
    "CAP_SECURITY_DISCLOSURES",
    "CAP_SECURITY_FINANCIALS",
    "SHORT_REQUIRED",
    "SWING_REQUIRED",
    "MEDIUM_REQUIRED",
    "REASON_CODES",
    "REASON_DEPENDENCY_POLICY_RESOLVED",
    "REASON_POLICY_VERSION_NOT_AVAILABLE",
    "REASON_POLICY_INTEGRITY_ERROR",
    "DependencyPolicyError",
    "DependencyPolicyValidationError",
    "resolve_strategy_dependencies",
]
