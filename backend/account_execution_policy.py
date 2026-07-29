"""Account execution policy storage and resolution service (P2-3).

Manages account-level capital allocation and trading execution constraints:
- lot_size: Lot size unit (default 100 shares for A-shares)
- min_cash_reserve_pct: Cash reserve percentage required (default 0.10, i.e. 10%)
- max_single_stock_allocation_pct: Single stock position cap relative to total assets (default 0.30)
- tie_breaker_order: Multi-add capital allocation priority order (default "code_asc")
- allow_partial_execution: Allow scaling down execution quantity to available cash (default True)
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Mapping

_LOCK = threading.Lock()

DEFAULT_POLICY: dict[str, Any] = {
    "lot_size": 100,
    "min_cash_reserve_pct": 0.10,
    "max_single_stock_allocation_pct": 0.30,
    "tie_breaker_order": "code_asc",
    "allow_partial_execution": True,
}


def resolve_policy_file_path() -> Path:
    """Resolve account execution policy file path.

    Priority:
    1. Environment variable `VR_DATA_DIR` / account_execution_policy.json
    2. Default: ~/.vibe-research/account_execution_policy.json
    """
    env_dir = os.environ.get("VR_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir) / "account_execution_policy.json"
    return Path.home() / ".vibe-research" / "account_execution_policy.json"


def validate_policy_data(data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate policy dictionary and return sanitized policy dict."""
    if not isinstance(data, dict):
        raise ValueError("Policy content must be a JSON object")

    lot_size = data.get("lot_size", 100)
    if isinstance(lot_size, bool) or not isinstance(lot_size, int) or lot_size <= 0:
        raise ValueError("lot_size 必须为大于 0 的整数")

    reserve_pct = data.get("min_cash_reserve_pct", 0.10)
    if (
        isinstance(reserve_pct, bool)
        or not isinstance(reserve_pct, (int, float))
        or reserve_pct < 0
        or reserve_pct >= 1.0
    ):
        raise ValueError("min_cash_reserve_pct 必须在 [0, 1) 范围内")

    single_cap = data.get("max_single_stock_allocation_pct", 0.30)
    if (
        isinstance(single_cap, bool)
        or not isinstance(single_cap, (int, float))
        or single_cap <= 0
        or single_cap > 1.0
    ):
        raise ValueError("max_single_stock_allocation_pct 必须在 (0, 1] 范围内")

    order = str(data.get("tie_breaker_order") or "code_asc").strip().lower()
    if order not in ("code_asc", "code_desc", "proportional"):
        raise ValueError("tie_breaker_order 必须为 code_asc、code_desc 或 proportional")

    allow_partial = bool(data.get("allow_partial_execution", True))

    return {
        "lot_size": lot_size,
        "min_cash_reserve_pct": float(reserve_pct),
        "max_single_stock_allocation_pct": float(single_cap),
        "tie_breaker_order": order,
        "allow_partial_execution": allow_partial,
    }


def get_account_execution_policy(db_file: Path | None = None) -> dict[str, Any]:
    """Load policy from file, falling back to default policy if missing or corrupt."""
    path = db_file or resolve_policy_file_path()
    if not path.exists():
        return dict(DEFAULT_POLICY)

    with _LOCK:
        try:
            content = path.read_text(encoding="utf-8")
            raw = json.loads(content)
            return validate_policy_data(raw)
        except Exception:
            return dict(DEFAULT_POLICY)


def save_account_execution_policy(data: Mapping[str, Any], db_file: Path | None = None) -> dict[str, Any]:
    """Validate and write policy to file atomically."""
    sanitized = validate_policy_data(data)
    path = db_file or resolve_policy_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    with _LOCK:
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    return sanitized
