"""A-share security-code to canonical-exchange routing policy v0.1.

This module answers one narrow question:

    exact six-digit ``security_code`` + explicit ``policy_version``
    -> canonical exchange routing (SSE / SZSE / BSE)

The policy is a pure-domain, versioned mechanical encoding of official
exchange code-allocation sources.  A resolved route does *not* claim that an
instrument exists, is listed, is active/tradable, or has data coverage.

There is deliberately no provider alias (``.SH`` / ``.SZ`` / ``.BJ``), I/O,
database, filesystem, network, environment, or wall-clock dependency here.
"""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Any, Final, Mapping

SCHEMA_VERSION: Final = "security_exchange_resolution.v0.1"
POLICY_VERSION_V01: Final = "security_exchange_policy.v0.1"
POLICY_AUTHORITY_REF_V01: Final = "security_exchange_policy:v0.1"

CANONICAL_EXCHANGES: tuple[str, ...] = ("SSE", "SZSE", "BSE")
EXCHANGE_RESOLUTION_STATES: tuple[str, ...] = (
    "RESOLVED",
    "NOT_RESOLVED",
    "NOT_EVALUATED",
)

# Official source revisions frozen by policy v0.1.  Source documents and the
# exact policy scope are described in docs/p0/SECURITY_EXCHANGE_POLICY_V01.md.
SSE_SOURCE_REFS_V01: tuple[str, ...] = (
    "https://www.sse.com.cn/lawandrules/guide/stock/jyglywznylc/zn/c/"
    "c_20260713_10825354.shtml",
    "https://www.sse.com.cn/lawandrules/guide/stock/jyglywznylc/zn/c/"
    "10825354/files/2ecb5d88e9894872843765b4f0661c2b.docx",
)
SZSE_SOURCE_REFS_V01: tuple[str, ...] = (
    "https://www.szse.cn/marketServices/technicalservice/doc/"
    "P020260306733846760075.pdf",
)
BSE_SOURCE_REFS_V01: tuple[str, ...] = (
    "https://www.bse.cn/fxrz_list/200021628.html",
    "https://www.bse.cn/jygl_list/200021626.html",
    "https://www.bse.cn/important_news/200026735.html",
    "https://www.bse.cn/code_mapping/200025792.html",
)

SOURCE_REFS_BY_EXCHANGE_V01: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "SSE": SSE_SOURCE_REFS_V01,
        "SZSE": SZSE_SOURCE_REFS_V01,
        "BSE": BSE_SOURCE_REFS_V01,
    }
)
SOURCE_REFS_V01: tuple[str, ...] = (
    *SSE_SOURCE_REFS_V01,
    *SZSE_SOURCE_REFS_V01,
    *BSE_SOURCE_REFS_V01,
)

# Inclusive official A-share stock allocation segments.  They intentionally
# exclude DR, B-share, fund, bond, index, repo and unproven gaps.
SSE_STOCK_CODE_SEGMENTS_V01: tuple[tuple[int, int], ...] = (
    (600000, 600999),
    (601000, 601999),
    (603000, 603999),
    (605000, 605999),
    (688000, 688999),
)
SZSE_STOCK_CODE_SEGMENTS_V01: tuple[tuple[int, int], ...] = (
    (0, 999),              # 000000-000999; integer form preserves range only
    (1200, 1999),          # 001200-001999
    (2000, 4999),          # 002000-004999
    (300000, 309799),
)
BSE_CURRENT_STOCK_CODE_SEGMENTS_V01: tuple[tuple[int, int], ...] = (
    (920000, 920999),
)

# Official BSE 2025-09-12 old/new code mapping, frozen as exact old-code
# identities.  Broad 4xx/8xx matching and arithmetic rewrite are forbidden:
# e.g. the official mapping includes 837023 -> 920123, so suffix replacement
# is not a valid identity rule.
BSE_LEGACY_STOCK_CODES_V01: frozenset[str] = frozenset(
    """
    872931 837023 835438 873706 870656 831396 837403 873806 873690
    871263 836961 833284 831175 836547 873703 835579 873570 832522
    873132 873679 873833 833030 839493 873693 873726 832786 832978
    873665 832469 836419 831627 870976 872953 837174 836504 837748
    834058 870726 832982 838701 833751 873576 837592 836717 832175
    836208 832651 833455 836221 830779 430017 839719 832471 837006
    838837 871478 836699 833394 871694 830896 831304 873593 872895
    834261 839792 830809 430556 837663 833575 835857 872541 830974
    836422 834770 430478 831906 839273 832149 834407 873167 832802
    832023 430425 873152 839371 834950 872392 838262 831195 831855
    872351 838227 873001 833781 836247 872190 430718 831526 873305
    834033 830879 836807 838810 870508 833429 833171 836957 833075
    834014 836414 870866 833230 836942 430300 831087 832110 831641
    870199 872374 832662 835237 871634 872808 870357 873339 833914
    832876 871753 430139 873527 835892 430476 837046 430685 838402
    838971 873122 835207 839790 836270 836395 831152 831834 835985
    836871 839725 834062 834639 837821 838670 833943 831278 430564
    832491 870299 873223 838171 831167 833533 871970 833580 873169
    831689 832419 835179 871857 833346 870204 871245 836720 871981
    833873 831832 839680 833454 870436 836260 832171 832145 837092
    832089 831305 838924 836892 872925 836077 835305 835174 831039
    871642 832566 430090 871553 839946 832885 834765 831768 837212
    833523 831726 832225 830832 834599 832735 836239 833427 838275
    836826 833509 837344 836675 430510 831856 832000 835670 838030
    430047 871396 830839 830964 831961 830946 833819 830799 839729
    834682 835640 835508 430489 834475 831445 836433 430418 834415
    831370 835368 832278 833266 836263 837242 430198 835185 835184
    839167 838163 836149 834021 831010
    """.split()
)

_SECURITY_CODE_RE = re.compile(r"^[0-9]{6}$", re.ASCII)


class SecurityExchangePolicyError(Exception):
    """Security exchange policy domain base error."""


class SecurityExchangePolicyValidationError(
    SecurityExchangePolicyError, ValueError
):
    """Illegal caller input; resolution fails closed."""


def _require_exact_string(value: object, field: str) -> str:
    # Exact type check rejects int/bool/coercible objects and str subclasses.
    if type(value) is not str or not value:
        raise SecurityExchangePolicyValidationError(
            f"{field} must be a non-empty exact string"
        )
    if value != value.strip():
        raise SecurityExchangePolicyValidationError(
            f"{field} must not have leading/trailing whitespace"
        )
    return value


def _require_security_code(value: object) -> str:
    code = _require_exact_string(value, "security_code")
    if _SECURITY_CODE_RE.fullmatch(code) is None:
        raise SecurityExchangePolicyValidationError(
            "security_code must contain exactly 6 ASCII digits"
        )
    return code


def _require_policy_version(value: object) -> str:
    return _require_exact_string(value, "policy_version")


def _in_segments(value: int, segments: tuple[tuple[int, int], ...]) -> bool:
    return any(start <= value <= end for start, end in segments)


def _resolve_exchange_v01(security_code: str) -> str | None:
    value = int(security_code)
    if _in_segments(value, SSE_STOCK_CODE_SEGMENTS_V01):
        return "SSE"
    if _in_segments(value, SZSE_STOCK_CODE_SEGMENTS_V01):
        return "SZSE"
    if (
        _in_segments(value, BSE_CURRENT_STOCK_CODE_SEGMENTS_V01)
        or security_code in BSE_LEGACY_STOCK_CODES_V01
    ):
        return "BSE"
    return None


def _build_result(
    *,
    security_code: str,
    policy_version: str,
    state: str,
    exchange: str | None,
    authority_ref: str | None,
    source_refs: tuple[str, ...],
) -> dict[str, Any]:
    if state not in EXCHANGE_RESOLUTION_STATES:
        raise RuntimeError(f"invalid exchange resolution state: {state!r}")
    if (state == "RESOLVED") != (exchange in CANONICAL_EXCHANGES):
        raise RuntimeError("resolved state/exchange invariant violated")
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_version": policy_version,
        "security_code": security_code,
        "exchange_resolution_state": state,
        "exchange": exchange,
        "authority_ref": authority_ref,
        # Detached mutable representation for JSON/API consumers.
        "source_refs": list(source_refs),
    }


def resolve_security_exchange(
    *, security_code: str, policy_version: str
) -> dict[str, Any]:
    """Resolve canonical exchange routing under an explicitly pinned policy.

    Unknown non-empty policy versions return ``NOT_EVALUATED``.  Legal
    six-digit codes outside the exact frozen v0.1 authority return
    ``NOT_RESOLVED``.  Malformed inputs raise a validation error.  The
    function is deterministic and has no side effects.
    """

    code = _require_security_code(security_code)
    version = _require_policy_version(policy_version)

    if version != POLICY_VERSION_V01:
        return _build_result(
            security_code=code,
            policy_version=version,
            state="NOT_EVALUATED",
            exchange=None,
            authority_ref=None,
            source_refs=(),
        )

    exchange = _resolve_exchange_v01(code)
    if exchange is None:
        return _build_result(
            security_code=code,
            policy_version=version,
            state="NOT_RESOLVED",
            exchange=None,
            authority_ref=POLICY_AUTHORITY_REF_V01,
            source_refs=SOURCE_REFS_V01,
        )

    return _build_result(
        security_code=code,
        policy_version=version,
        state="RESOLVED",
        exchange=exchange,
        authority_ref=POLICY_AUTHORITY_REF_V01,
        source_refs=SOURCE_REFS_BY_EXCHANGE_V01[exchange],
    )


__all__ = [
    "BSE_CURRENT_STOCK_CODE_SEGMENTS_V01",
    "BSE_LEGACY_STOCK_CODES_V01",
    "BSE_SOURCE_REFS_V01",
    "CANONICAL_EXCHANGES",
    "EXCHANGE_RESOLUTION_STATES",
    "POLICY_AUTHORITY_REF_V01",
    "POLICY_VERSION_V01",
    "SCHEMA_VERSION",
    "SSE_SOURCE_REFS_V01",
    "SSE_STOCK_CODE_SEGMENTS_V01",
    "SZSE_SOURCE_REFS_V01",
    "SZSE_STOCK_CODE_SEGMENTS_V01",
    "SecurityExchangePolicyError",
    "SecurityExchangePolicyValidationError",
    "resolve_security_exchange",
]
