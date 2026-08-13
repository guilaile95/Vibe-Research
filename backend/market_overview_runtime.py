"""Current Market Overview Runtime v0.1（P0-MO1）。

回答 P0 用户第一层问题：

> 现在 A 股整体市场环境怎么样？

本模块是**市场上下文只读 read model**——不是决策权威。它组合已冻结的
``short_term_market_facts`` producer，把规范化 market facts 投影成首页可消费的
Overview envelope，**不重算任何市场事实**（breadth / limit activity / session /
freshness / data health 全部来自既有 authority）。

- **纯组合层，零 I/O**：不调 provider、不读时钟、不落库；输入 = 一份符合
  ``short_term_market_facts.compute_short_term_market_facts`` 输出契约的
  facts envelope（由上层从既有 snapshot producer 获取）。
- **诚实降级**：data_state 仅从 facts.status 派生（AVAILABLE / PARTIAL /
  UNAVAILABLE）；0 limit_up ≠ limit_up data unavailable；unavailable 绝不用 0
  代替未知；旧 snapshot 绝不静默伪装 current（session / is_final / fetched_at /
  snapshot_at / trade_date 全保留）。
- **描述性 label 规则与既有权威一致**：breadth_state 阈值分档与
  ``market.py:_breadth_label``（冰点/偏弱/中性/偏强/普涨）、speculation_activity
  与 ``market.py:_speculation_label``（冰点/普通/活跃/亢奋）**完全一致**
  （同一阈值权威，不重新发明；label 只是数值的机械分档展示）。
- **明确非权威**：不生成 BUY/SELL/REDUCE/EXIT、不推断 market regime、不产生
  risk appetite / exposure / NBA；涨停多≠牛市、炸板多≠SELL、情绪差≠REDUCE。
- **无 AI**：所有状态 deterministic。
"""

from __future__ import annotations

from typing import Any, Mapping

# 复用既有 producer 的契约常量（事实数值 authority，不重算）
from short_term_market_facts import (
    SCHEMA_VERSION as FACTS_SCHEMA_VERSION,
    _STATUS_NORMAL,
    _STATUS_PARTIAL,
    _STATUS_UNAVAILABLE,
)

SCHEMA_VERSION = "market-overview-runtime.v0.1"

# 描述性 label 阈值（与 market.py:_breadth_label / _speculation_label 同一权威；
# 本模块只做数值→label 的机械分档展示，不重新定义阈值）
# breadth（market.py）：r<0.25 冰点 · r<0.40 偏弱 · r<=0.60 中性 · r<=0.75 偏强 · else 普涨
# speculation（market.py）：z>=100 亢奋 · z>=60 活跃 · z>=30 普通 · else 冰点
# 注意边界语义：中性/偏强含上界（<=），冰点/偏弱不含（<）——与 market.py 逐字一致
_BREADTH_LABEL_RULES: tuple[tuple[float, str, bool], ...] = (
    (0.25, "冰点", False),
    (0.40, "偏弱", False),
    (0.60, "中性", True),
    (0.75, "偏强", True),
)
_BREADTH_LABEL_ABOVE = "普涨"
_SPECULATION_LABEL_RULES: tuple[tuple[int, str], ...] = (
    (100, "亢奋"),
    (60, "活跃"),
    (30, "普通"),
)
_SPECULATION_LABEL_BELOW = "冰点"

# data_state 合法值
DATA_STATE_AVAILABLE = "AVAILABLE"
DATA_STATE_PARTIAL = "PARTIAL"
DATA_STATE_STALE = "STALE"
DATA_STATE_UNAVAILABLE = "UNAVAILABLE"

# snapshot temporal state（§5.1 用户可区分四态；HISTORICAL 需上层 reference date）
TEMPORAL_STATE_UNAVAILABLE = "UNAVAILABLE"
TEMPORAL_STATE_INTRADAY = "INTRADAY"
TEMPORAL_STATE_AFTER_CLOSE_FINAL = "AFTER_CLOSE_FINAL"
TEMPORAL_STATE_UNKNOWN = "UNKNOWN"

_FINAL_SESSIONS = frozenset({"final"})
_INTRADAY_SESSIONS = frozenset({
    "pre_open", "call_auction", "morning_session", "midday_break",
    "afternoon_session", "close_pending",
})


class MarketOverviewError(Exception):
    """Market Overview 领域异常基类（fail closed）。"""


class MarketOverviewInputError(MarketOverviewError):
    """输入契约违反（malformed envelope → fail closed，不产出伪造 overview）。"""


def _require_facts_envelope(envelope: Any) -> Mapping[str, Any]:
    if not isinstance(envelope, Mapping):
        raise MarketOverviewInputError("facts envelope 必须是 Mapping")
    if envelope.get("schema_version") != FACTS_SCHEMA_VERSION:
        raise MarketOverviewInputError(
            f"facts envelope schema_version 必须是 {FACTS_SCHEMA_VERSION!r}")
    return envelope


def _strict_int(value: Any, field: str, *, allow_none: bool = True) -> int | None:
    """严格非负 int（拒绝 bool / NaN / inf / 负数 / 非 int）。

    None 默认允许——producer 的 unavailable envelope 中 facts 数值全为 None
    （未知 ≠ 0），这是合法业务状态，不是 schema corruption。
    """
    if value is None and allow_none:
        return None
    if type(value) is not int or isinstance(value, bool):
        raise MarketOverviewInputError(f"{field} 必须是 int")
    if value < 0:
        raise MarketOverviewInputError(f"{field} 不得为负")
    return value


def _strict_float(value: Any, field: str, *, allow_none: bool = True) -> float | None:
    if value is None and allow_none:
        return None
    if type(value) not in (int, float) or isinstance(value, bool):
        raise MarketOverviewInputError(f"{field} 必须是数值")
    f = float(value)
    if f != f or f in (float("inf"), float("-inf")):
        raise MarketOverviewInputError(f"{field} 不得为 NaN/inf")
    if f < 0:
        raise MarketOverviewInputError(f"{field} 不得为负")
    return f


def _breadth_state(up_ratio: float | None) -> str | None:
    """与 market.py:_breadth_label 同一阈值权威的机械分档（None → None）。"""
    if up_ratio is None:
        return None
    for threshold, label, inclusive in _BREADTH_LABEL_RULES:
        if up_ratio <= threshold if inclusive else up_ratio < threshold:
            return label
    return _BREADTH_LABEL_ABOVE


def _speculation_activity(limit_up_count: int | None) -> str | None:
    """与 market.py:_speculation_label 同一阈值权威的机械分档（None → None）。"""
    if limit_up_count is None:
        return None
    for threshold, label in _SPECULATION_LABEL_RULES:
        if limit_up_count >= threshold:
            return label
    return _SPECULATION_LABEL_BELOW


def _derive_data_state(status: str) -> str:
    """data_state 仅从 facts.status 派生（诚实降级，无隐式阈值）。"""
    if status == _STATUS_NORMAL:
        return DATA_STATE_AVAILABLE
    if status == _STATUS_PARTIAL:
        return DATA_STATE_PARTIAL
    if status == _STATUS_UNAVAILABLE:
        return DATA_STATE_UNAVAILABLE
    raise MarketOverviewInputError(f"未知 facts status: {status!r}")


def _derive_temporal_state(session: str, is_final: bool, status: str) -> str:
    """snapshot temporal state（§5.1 四态；HISTORICAL 需上层提供 reference）。"""
    if status == _STATUS_UNAVAILABLE:
        return TEMPORAL_STATE_UNAVAILABLE
    if is_final or session in _FINAL_SESSIONS:
        return TEMPORAL_STATE_AFTER_CLOSE_FINAL
    if session in _INTRADAY_SESSIONS:
        return TEMPORAL_STATE_INTRADAY
    return TEMPORAL_STATE_UNKNOWN


def build_market_overview(facts_envelope: Mapping[str, Any]) -> dict:
    """把一份已冻结的 market facts envelope 投影为 P0 Market Overview。

    输入 = ``compute_short_term_market_facts(snapshot)`` 输出契约（或同结构 dict）。
    零 I/O、零墙钟、确定性；不修改输入；所有数值直接透传 facts authority，
    label / data_state / temporal_state 为机械派生。
    """
    envelope = _require_facts_envelope(facts_envelope)

    # ---- snapshot identity（§5.1 全保留，绝不让旧快照看起来 current）----
    trade_date = envelope.get("trade_date")
    session = envelope.get("session")
    is_final = envelope.get("is_final")
    fetched_at = envelope.get("fetched_at")
    snapshot_at = envelope.get("snapshot_at")
    source_ids = envelope.get("source_ids", [])
    if trade_date is not None and (type(trade_date) is not str or not trade_date):
        raise MarketOverviewInputError("trade_date 必须是非空字符串或 None")
    if session is not None and type(session) is not str:
        raise MarketOverviewInputError("session 必须是字符串")
    if type(is_final) is not bool:
        raise MarketOverviewInputError("is_final 必须是 bool")
    if not isinstance(source_ids, list) or \
            any(type(s) is not str for s in source_ids):
        raise MarketOverviewInputError("source_ids 必须是字符串列表")

    status = envelope.get("status")
    if status not in (_STATUS_NORMAL, _STATUS_PARTIAL, _STATUS_UNAVAILABLE):
        raise MarketOverviewInputError(f"未知 status: {status!r}")
    reason_codes = envelope.get("reason_codes", [])
    warnings = envelope.get("warnings", [])
    limitations = envelope.get("limitations", [])
    if not isinstance(reason_codes, list) or not isinstance(warnings, list) \
            or not isinstance(limitations, list):
        raise MarketOverviewInputError("reason_codes/warnings/limitations 必须是列表")

    # ---- facts（数值 authority，直接透传；缺失/畸形 → fail closed）----
    # facts 是扁平结构（advance_count / limit_up_count / ... 直接在 facts 顶层）
    facts = envelope.get("facts")
    if not isinstance(facts, Mapping):
        raise MarketOverviewInputError("facts 必须是 Mapping")

    advance_count = _strict_int(facts.get("advance_count"), "advance_count")
    decline_count = _strict_int(facts.get("decline_count"), "decline_count")
    flat_count = _strict_int(facts.get("flat_count"), "flat_count")
    suspended_count = _strict_int(facts.get("suspended_count"), "suspended_count")
    valid_count = _strict_int(facts.get("valid_count"), "valid_count")
    up_ratio = _strict_float(facts.get("up_ratio"), "up_ratio")

    limit_up_count = _strict_int(facts.get("limit_up_count"), "limit_up_count")
    limit_down_count = _strict_int(facts.get("limit_down_count"), "limit_down_count")
    failed_limit_up_count = _strict_int(
        facts.get("failed_limit_up_count"), "failed_limit_up_count")
    touched_limit_up_count = _strict_int(
        facts.get("touched_limit_up_count"), "touched_limit_up_count")
    sealed_limit_up_count = _strict_int(
        facts.get("sealed_limit_up_count"), "sealed_limit_up_count")
    failed_board_rate = _strict_float(
        facts.get("failed_board_rate"), "failed_board_rate")
    seal_rate = _strict_float(facts.get("seal_rate"), "seal_rate")

    # ---- 机械派生（label 阈值与 market.py 一致；data/temporal state 诚实）----
    data_state = _derive_data_state(status)
    temporal_state = _derive_temporal_state(session, is_final, status)
    breadth_state = _breadth_state(up_ratio)
    speculation_activity = _speculation_activity(limit_up_count)

    return {
        "schema_version": SCHEMA_VERSION,
        "facts_schema_version": FACTS_SCHEMA_VERSION,
        # snapshot identity
        "trade_date": trade_date,
        "session": session,
        "is_final": is_final,
        "snapshot_at": snapshot_at,
        "fetched_at": fetched_at,
        "source_ids": list(source_ids),
        "temporal_state": temporal_state,
        # breadth（facts authority 透传）
        "breadth": {
            "advance_count": advance_count,
            "decline_count": decline_count,
            "flat_count": flat_count,
            "suspended_count": suspended_count,
            "valid_count": valid_count,
            "up_ratio": up_ratio,
            "breadth_state": breadth_state,
        },
        # limit / speculation activity（facts authority 透传）
        "limit_activity": {
            "limit_up_count": limit_up_count,
            "limit_down_count": limit_down_count,
            "failed_limit_up_count": failed_limit_up_count,
            "touched_limit_up_count": touched_limit_up_count,
            "sealed_limit_up_count": sealed_limit_up_count,
            "failed_board_rate": failed_board_rate,
            "seal_rate": seal_rate,
            "speculation_activity": speculation_activity,
        },
        # honesty
        "data_state": data_state,
        "status": status,
        "reason_codes": list(reason_codes),
        "warnings": list(warnings),
        "limitations": list(limitations),
        "data_health": envelope.get("data_health"),
    }


__all__ = [
    "SCHEMA_VERSION",
    "DATA_STATE_AVAILABLE",
    "DATA_STATE_PARTIAL",
    "DATA_STATE_STALE",
    "DATA_STATE_UNAVAILABLE",
    "TEMPORAL_STATE_UNAVAILABLE",
    "TEMPORAL_STATE_INTRADAY",
    "TEMPORAL_STATE_AFTER_CLOSE_FINAL",
    "TEMPORAL_STATE_UNKNOWN",
    "MarketOverviewError",
    "MarketOverviewInputError",
    "build_market_overview",
]
