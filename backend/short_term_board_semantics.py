"""Pure short-term board semantics derived from existing in-memory rows.

This module does not fetch EastMoney data or persist a second short-term
authority.  ``boards`` remains the consecutive-board field; ``zt_stat`` is an
optional EastMoney ``N/M`` window statistic and is never silently substituted
for consecutive height.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable, Mapping

_N_M_RE = re.compile(r"^(?P<days>[1-9]\d*)/(?P<count>[1-9]\d*)$")

REASON_ZT_STAT_INVALID = "ZT_STAT_INVALID"
REASON_THEME_PROJECTION_UNAVAILABLE = "THEME_PROJECTION_UNAVAILABLE"


def _strict_positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def parse_zt_stat(value: Any) -> tuple[int, int] | None:
    """Return ``(N, M)`` for an exact positive ``N/M`` string."""
    if type(value) is not str:
        return None
    match = _N_M_RE.fullmatch(value)
    if match is None:
        return None
    days = int(match.group("days"))
    count = int(match.group("count"))
    if days < count:
        return None
    return days, count


def _row_semantics(row: Mapping[str, Any]) -> dict[str, Any]:
    boards = _strict_positive_int(row.get("boards"), "boards")
    raw_stat = row.get("zt_stat")
    parsed = parse_zt_stat(raw_stat)
    result: dict[str, Any] = {
        "boards": boards,
        "zt_stat": raw_stat if type(raw_stat) is str else None,
        "stat_days": parsed[0] if parsed else None,
        "stat_boards": parsed[1] if parsed else None,
        "effective_height": max(boards, parsed[1]) if parsed else boards,
        "is_rebound": bool(parsed and parsed[0] > parsed[1]),
        "zt_stat_status": "VALID" if parsed else "UNKNOWN",
        "reason_codes": [],
    }
    if raw_stat is not None and parsed is None:
        result["reason_codes"].append(REASON_ZT_STAT_INVALID)
    if parsed and parsed[0] > parsed[1]:
        result["label"] = f"{parsed[0]}天{parsed[1]}板"
    else:
        result["label"] = f"{boards}板"
    return result


def classify_board(row: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one row while preserving consecutive and window semantics."""
    if not isinstance(row, Mapping):
        raise ValueError("row must be a mapping")
    return _row_semantics(row)


def exact_board_tiers(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, int]]:
    """Count exact consecutive board heights; never compress to ``5+``."""
    counts: Counter[int] = Counter()
    for row in rows:
        counts[_strict_positive_int(row.get("boards"), "boards")] += 1
    return [
        {"boards": boards, "count": counts[boards]}
        for boards in sorted(counts)
    ]


def order_by_effective_height(
    *,
    theme_projection: Iterable[Mapping[str, Any]] | None,
    limit: int = 8,
) -> dict[str, Any]:
    """Order an existing theme projection, or explicitly decline applicability."""
    if theme_projection is None:
        return {
            "status": "NOT_APPLICABLE",
            "reason_codes": [REASON_THEME_PROJECTION_UNAVAILABLE],
            "members": [],
        }
    if type(limit) is not int or limit <= 0:
        raise ValueError("limit must be a positive integer")
    members = [classify_board(row) for row in theme_projection]
    members.sort(key=lambda item: (-item["effective_height"], str(item.get("code", ""))))
    return {"status": "APPLICABLE", "reason_codes": [], "members": members[:limit]}


__all__ = [
    "REASON_THEME_PROJECTION_UNAVAILABLE",
    "REASON_ZT_STAT_INVALID",
    "classify_board",
    "exact_board_tiers",
    "order_by_effective_height",
    "parse_zt_stat",
]
