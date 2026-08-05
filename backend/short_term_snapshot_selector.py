"""BK-11 Slice 3e 快照选择器纯计算层 v0.1。

接收快照元数据行列表（与 Slice 3a ``list_snapshots`` 输出同构：
{trade_date, session, schema_version, stored_at}），为每个 trade_date
确定性选择每日权威快照：

1. final 硬优先（任何非 final 会话都不能胜过 final）
2. 无 final 时按会话时间序取最高（unavailable 为最高非 final 状态）
3. 同优先级同会话多版本：取 stored_at 最新
4. 仍相同：取 schema_version 字典序较大者（全序决胜）
5. 全部相等：取排序后的首条（确定性）

服务 Daily Review 历史区块与页面接入前的基础模块。纯计算，不读取
存储、不依赖 live 数据。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional

__all__ = [
    "SCHEMA_VERSION",
    "select_daily_snapshots",
]

SCHEMA_VERSION = "short-term-snapshot-selector-v0.1"

_REASON_ORDER: tuple[str, ...] = (
    "INPUT_CONTRACT_INVALID",
    "ROW_CONTRACT_INVALID",
    "OUTPUT_SUPPRESSED",
)

_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ROW_FIELDS = frozenset({
    "trade_date",
    "session",
    "schema_version",
    "stored_at",
})

_SESSION_ORDER = {
    "pre_open": 0,
    "call_auction": 1,
    "morning_session": 2,
    "midday_break": 3,
    "afternoon_session": 4,
    "close_pending": 5,
    "final": 6,
    "unavailable": 7,
}


def _is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_row(row: Any) -> Optional[Dict[str, Any]]:
    if type(row) is not dict or set(row.keys()) != _ROW_FIELDS:
        return None
    trade_date = row.get("trade_date")
    if type(trade_date) is not str or _TRADE_DATE_RE.match(trade_date) is None:
        return None
    try:
        date.fromisoformat(trade_date)
    except ValueError:
        return None
    session = row.get("session")
    if type(session) is not str or session not in _SESSION_ORDER:
        return None
    schema_version = row.get("schema_version")
    if type(schema_version) is not str or not schema_version:
        return None
    stored_at = row.get("stored_at")
    if type(stored_at) is not str or not stored_at:
        return None
    return {
        "trade_date": trade_date,
        "session": session,
        "session_rank": _SESSION_ORDER[session],
        "schema_version": schema_version,
        "stored_at": stored_at,
    }


def _sort_key(row: Dict[str, Any]) -> tuple:
    # 确定性全序：(trade_date, 选择优先级, session_rank, stored_at,
    # schema_version)；输入顺序不影响结果
    return (
        row["trade_date"],
        _selection_priority(row),
        row["session_rank"],
        row["stored_at"],
        row["schema_version"],
    )


def _selection_priority(row: Dict[str, Any]) -> int:
    # final 硬优先（任何非 final 会话都不能胜过 final）
    return 1 if row["session"] == "final" else 0


def _select_per_date(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = sorted(rows, key=_sort_key)
    best = rows[0]
    for candidate in rows[1:]:
        candidate_key = (
            _selection_priority(candidate),
            candidate["session_rank"],
            candidate["stored_at"],
            candidate["schema_version"],
        )
        best_key = (
            _selection_priority(best),
            best["session_rank"],
            best["stored_at"],
            best["schema_version"],
        )
        if candidate_key > best_key:
            best = candidate
    return best


def _fixed_limitations() -> List[str]:
    return [
        "deterministic per-date snapshot selection",
        "prefers final session, then session time order, then latest stored_at",
        "does not read storage or live data",
        "does not validate snapshot content semantics",
        "no per-stock cross-day identity tracking",
    ]


def _normal_envelope(
    selection: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "normal",
        "reason_codes": [],
        "warnings": [],
        "limitations": _fixed_limitations(),
        "selection": selection,
    }


def _invalid_envelope(reason_code: str) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "invalid",
        "reason_codes": [reason_code, "OUTPUT_SUPPRESSED"],
        "warnings": [],
        "limitations": _fixed_limitations(),
        "selection": [],
    }


def _evaluate(rows: Any) -> Dict[str, Any]:
    if type(rows) is not list:
        return _invalid_envelope("INPUT_CONTRACT_INVALID")
    if not rows:
        return _invalid_envelope("INPUT_CONTRACT_INVALID")
    validated: List[Dict[str, Any]] = []
    for row in rows:
        item = _validate_row(row)
        if item is None:
            return _invalid_envelope("ROW_CONTRACT_INVALID")
        validated.append(item)

    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for item in validated:
        by_date.setdefault(item["trade_date"], []).append(item)

    selection: List[Dict[str, Any]] = []
    for trade_date in sorted(by_date):
        best = _select_per_date(by_date[trade_date])
        selection.append({
            "trade_date": best["trade_date"],
            "session": best["session"],
            "schema_version": best["schema_version"],
            "stored_at": best["stored_at"],
        })
    return _normal_envelope(selection)


def select_daily_snapshots(rows: list) -> dict:
    """为每个 trade_date 选择每日权威快照（Slice 3e 范围），永不抛异常。

    输入为快照元数据行列表。纯计算，不修改输入。普通异常返回固定
    invalid envelope（不调用任何业务 helper、不包含异常文本）；
    KeyboardInterrupt / SystemExit / GeneratorExit 自然传播。
    """
    try:
        return _evaluate(rows)
    except Exception:
        # emergency fail-closed envelope：直接构造完整固定字面量。
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "invalid",
            "reason_codes": ["INPUT_CONTRACT_INVALID", "OUTPUT_SUPPRESSED"],
            "warnings": [],
            "limitations": [
                "deterministic per-date snapshot selection",
                "prefers final session, then session time order, then latest stored_at",
                "does not read storage or live data",
                "does not validate snapshot content semantics",
                "no per-stock cross-day identity tracking",
            ],
            "selection": [],
        }
