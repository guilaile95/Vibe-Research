"""BK-11 Slice 2K v0.2：Tushare 生产组合层。

职责：把 Tushare 市场事实 snapshot（``facts_snapshot``）与东方财富连板
producer（或 Tushare 合法零涨停证明）组合为 ``short-term-daily-facts-v0.2``
envelope。

复用已批准纯计算器（不复制指标公式）：

    compute_short_term_market_facts   (Slice 1)
    compute_limit_up_ladder           (Slice 2A)
    compute_ladder_gap                (Slice 2J)

顶层与 v0.1 保持 15 字段兼容形状，仅 schema_version 不同；sections 继续
精确包含 facts / ladder / gap；不修改 v0.1 模块与既有结果。
"""

from __future__ import annotations

import re
from typing import Any

import short_term_board_semantics
import short_term_ladder_gap
import short_term_limit_up_ladder
import short_term_market_facts

SCHEMA_VERSION = "short-term-daily-facts-v0.2"
FACTS_ADAPTER_SCHEMA_VERSION = "bk11-tushare-facts-adapter-v0.1"
PRODUCER_SCHEMA_VERSION = "short-term-limit-up-final-snapshot-v0.1"
ADAPTER_SCHEMA_VERSION = "short-term-limit-up-pool-adapter-v0.2"

_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ZT_STAT_RE = re.compile(r"^(?P<days>[1-9]\d*)/(?P<count>[1-9]\d*)$")
_ALLOWED_SESSIONS = frozenset({
    "pre_open", "call_auction", "morning_session", "midday_break",
    "afternoon_session", "close_pending", "final", "unavailable",
})
_STATUS_RANK = {"normal": 0, "partial": 1, "unavailable": 2, "invalid": 3}

_CROSS_SOURCE_TOLERANCE = 3
_CROSS_SOURCE_RATIO = 0.05

_FIXED_LIMITATIONS = (
    "composed from approved BK-11 pure calculators (v0.2)",
    "facts from Tushare; ladder from Eastmoney final producer",
    "does not validate upstream consecutive-limit-up semantics",
    "does not compute layered promotion rates",
)


def _worst(*statuses: str) -> str:
    return max(statuses, key=lambda s: _STATUS_RANK.get(s, 3))


def _dedup_source_ids(*lists: Any) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for items in lists:
        if not isinstance(items, (list, tuple)):
            continue
        for item in items:
            if isinstance(item, str) and item and item not in seen:
                seen.add(item)
                out.append(item)
    return sorted(out)


def _invalid_envelope(
    trade_date: str,
    reason_codes: list[str],
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "trade_date": trade_date,
        "session": "unavailable",
        "is_final": False,
        "source_ids": [],
        "fetched_at": None,
        "snapshot_at": None,
        "status": "invalid",
        "reason_codes": list(reason_codes) + ["OUTPUT_SUPPRESSED"],
        "warnings": [],
        "limitations": limitations or ["v0.2 组合合同校验失败"],
        "source_schema_version": None,
        "source_status": None,
        "source_reason_codes": [],
        "sections": {"facts": None, "ladder": None, "gap": None},
    }


def _validate_facts_snapshot(facts_snapshot: Any) -> dict[str, Any] | None:
    if type(facts_snapshot) is not dict:
        return None
    trade_date = facts_snapshot.get("trade_date")
    if not isinstance(trade_date, str) or _TRADE_DATE_RE.match(trade_date) is None:
        return None
    session = facts_snapshot.get("session")
    if session != "final" or facts_snapshot.get("is_final") is not True:
        return None
    status = facts_snapshot.get("status")
    if status not in ("normal", "partial"):
        return None
    breadth = facts_snapshot.get("breadth")
    activity = facts_snapshot.get("limit_activity")
    health = facts_snapshot.get("facts_data_health")
    if not isinstance(breadth, dict) or not isinstance(activity, dict):
        return None
    if not isinstance(health, dict):
        return None
    return facts_snapshot


def _validate_producer(producer: Any) -> dict[str, Any] | None:
    if type(producer) is not dict:
        return None
    if producer.get("schema_version") != PRODUCER_SCHEMA_VERSION:
        return None
    trade_date = producer.get("requested_trade_date")
    if not isinstance(trade_date, str) or _TRADE_DATE_RE.match(trade_date) is None:
        return None
    status = producer.get("status")
    if status not in ("normal", "partial", "unavailable"):
        return None
    if producer.get("session") not in ("final", "not_final"):
        return None
    if type(producer.get("is_final")) is not bool:
        return None
    snapshot = producer.get("snapshot")
    if snapshot is not None and type(snapshot) is not dict:
        return None
    if status in ("partial", "unavailable") and snapshot is not None:
        return None
    return producer


def _ladder_rows_from_producer(producer: dict[str, Any]) -> list[dict[str, Any]]:
    """保留 lbc authority，并将 optional zt_stat 穿透到既有 ladder 输入。"""
    snapshot = producer.get("snapshot") or {}
    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        raise ValueError("producer snapshot rows missing")
    out: list[dict[str, Any]] = []
    for row in rows:
        if type(row) is not dict:
            raise ValueError("invalid producer row")
        code = row.get("stock_code")
        lbc = row.get("lbc")
        zt_stat = row.get("zt_stat")
        if (not isinstance(code, str) or not isinstance(lbc, int)
                or isinstance(lbc, bool) or lbc <= 0):
            raise ValueError("invalid producer row fields")
        if zt_stat is not None:
            match = _ZT_STAT_RE.fullmatch(zt_stat) if isinstance(zt_stat, str) else None
            if match is None or int(match.group("days")) < int(match.group("count")):
                raise ValueError("invalid producer row fields")
        out.append({
            "stock_code": code,
            "consecutive_limit_up_days": lbc,
            "zt_stat": zt_stat,
        })
    return out


def _empty_ladder_snapshot(facts: dict[str, Any]) -> dict[str, Any]:
    """Tushare 合法零涨停证明 → 空 ladder 输入（不伪造任何连板股）。"""
    health = dict(facts.get("facts_data_health") or {})
    health["legal_zero"] = True
    health["row_count"] = 0
    return {
        "trade_date": facts["trade_date"],
        "session": "final",
        "is_final": True,
        "source_ids": ["tushare_daily"],
        "fetched_at": facts.get("fetched_at"),
        "snapshot_at": facts.get("snapshot_at"),
        "data_health": health,
        "limit_up_pool": [],
    }


def _producer_ladder_snapshot(
    producer: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    adapter = producer.get("snapshot") or {}
    health = {
        name: adapter.get(name, False)
        for name in (
            "transport_success", "parse_success", "required_field_present",
            "data_array_present", "trade_date_match", "legal_zero",
            "upstream_null", "unexplained_empty", "coverage_warning",
        )
    }
    health["row_count"] = adapter.get("row_count", 0)
    return {
        "trade_date": producer["requested_trade_date"],
        "session": "final",
        "is_final": True,
        "source_ids": [adapter.get("source_id", "eastmoney_getTopicZTPool")],
        "fetched_at": adapter.get("observed_at"),
        "snapshot_at": producer.get("observed_at"),
        "data_health": health,
        "limit_up_pool": rows,
    }


def compute_daily_facts_v02(
    facts_snapshot: dict[str, Any],
    ladder_input: dict[str, Any],
) -> dict[str, Any]:
    """组合 v0.2 daily facts（永不抛异常；进程控制异常自然传播）。

    ``ladder_input`` 两种形态：

    - ``{"kind": "producer", "envelope": <final-snapshot-v0.1>}``
    - ``{"kind": "empty_ladder_proof"}``（Tushare 已证明 limit_up_count=0
      且 legal_zero=true）
    """
    facts = _validate_facts_snapshot(facts_snapshot)
    if facts is None:
        return _invalid_envelope(
            str((facts_snapshot or {}).get("trade_date") or ""),
            ["INPUT_CONTRACT_INVALID"],
        )
    trade_date = facts["trade_date"]

    if type(ladder_input) is not dict:
        return _invalid_envelope(trade_date, ["LADDER_INPUT_INVALID"])
    kind = ladder_input.get("kind")

    # ---- facts section（Tushare 口径）----
    facts_for_calculator = dict(facts)
    facts_for_calculator["data_health"] = facts.get("facts_data_health")
    facts_envelope = short_term_market_facts.compute_short_term_market_facts(
        facts_for_calculator)

    # ---- ladder / gap section ----
    ladder_envelope: dict[str, Any] | None = None
    gap_envelope: dict[str, Any] | None = None
    ladder_status = "unavailable"
    ladder_source_ids: list[str] = []
    cross_codes: list[str] = []
    cross_warnings: list[str] = []

    if kind == "empty_ladder_proof":
        if (
            facts.get("legal_zero") is not True
            or facts.get("limit_activity", {}).get("limit_up_count") != 0
        ):
            return _invalid_envelope(
                trade_date,
                ["LEGAL_ZERO_PROOF_INVALID"],
                limitations=["空 ladder 证明缺少合法零涨停证据"],
            )
        ladder_envelope = short_term_limit_up_ladder.compute_limit_up_ladder(
            _empty_ladder_snapshot(facts))
        gap_envelope = short_term_ladder_gap.compute_ladder_gap(ladder_envelope)
        ladder_status = ladder_envelope.get("status", "unavailable")
        ladder_source_ids = ["tushare_daily"]
    elif kind == "producer":
        producer = _validate_producer(ladder_input.get("envelope"))
        if producer is None:
            return _invalid_envelope(
                trade_date,
                ["PRODUCER_CONTRACT_INVALID"],
            )
        if producer["requested_trade_date"] != trade_date:
            return _invalid_envelope(
                trade_date,
                ["TRADE_DATE_MISMATCH"],
                limitations=["Tushare 与东方财富日期不一致"],
            )
        if producer["status"] == "normal":
            try:
                em_rows = _ladder_rows_from_producer(producer)
                ladder_envelope = short_term_limit_up_ladder.compute_limit_up_ladder(
                    _producer_ladder_snapshot(producer, em_rows))
                gap_envelope = short_term_ladder_gap.compute_ladder_gap(
                    ladder_envelope)
                ladder_envelope["board_semantics"] = [
                    short_term_board_semantics.classify_board({
                        "stock_code": row["stock_code"],
                        "boards": row["consecutive_limit_up_days"],
                        "zt_stat": row.get("zt_stat"),
                    })
                    for row in em_rows
                ]
            except Exception:  # noqa: BLE001
                ladder_envelope = None
                gap_envelope = None
            if ladder_envelope is not None:
                ladder_status = ladder_envelope.get("status", "unavailable")
            else:
                ladder_status = "unavailable"
            ladder_source_ids = ["eastmoney_getTopicZTPool"]

            # ---- 跨源校验：Tushare limit_up_count vs 东财 row_count ----
            if ladder_envelope is not None:
                em_count = len(em_rows)
                ts_count = int(facts.get("limit_activity", {}).get(
                    "limit_up_count") or 0)
                if abs(ts_count - em_count) > max(
                        _CROSS_SOURCE_TOLERANCE, em_count * _CROSS_SOURCE_RATIO):
                    cross_codes.append("CROSS_SOURCE_COUNT_MISMATCH")
                    cross_warnings.append(
                        f"cross-source limit-up count mismatch: "
                        f"tushare={ts_count} eastmoney={em_count}")
        else:
            # producer unavailable/partial：facts 保留，ladder 缺失
            ladder_status = "unavailable" if producer["status"] == "unavailable" \
                else "partial"
            if producer["status"] == "unavailable":
                cross_codes.append("UPSTREAM_LADDER_UNAVAILABLE")
            else:
                cross_codes.append("UPSTREAM_LADDER_PARTIAL")
    else:
        return _invalid_envelope(trade_date, ["LADDER_INPUT_INVALID"])

    sections = {
        "facts": facts_envelope,
        "ladder": ladder_envelope,
        "gap": gap_envelope,
    }
    section_statuses = [facts_envelope["status"]]
    if ladder_envelope is not None:
        section_statuses.append(ladder_status)
    if gap_envelope is not None:
        section_statuses.append(gap_envelope.get("status", "unavailable"))
    if ladder_envelope is None:
        section_statuses.append(ladder_status)

    status = _worst(*section_statuses)
    if cross_codes and status == "normal":
        status = "partial"

    reason_codes = list(cross_codes)
    if facts_envelope.get("status") != "normal":
        reason_codes.append("SOURCE_PARTIAL")
    if ladder_envelope is None:
        reason_codes.append("OUTPUT_SUPPRESSED")
    if status != "normal":
        reason_codes.append("OUTPUT_SUPPRESSED")

    source_ids = _dedup_source_ids(
        facts.get("source_ids"),
        ladder_source_ids,
    )
    warnings = list(facts.get("warnings") or []) + list(cross_warnings)
    limitations = list(_FIXED_LIMITATIONS)
    limitations.extend(facts.get("limitations") or [])
    if cross_warnings:
        limitations.append("跨源涨停数量不一致，整体状态至少 partial")

    fetched_at = facts.get("fetched_at")
    snapshot_at = facts.get("snapshot_at")
    producer_observed = (
        (ladder_input.get("envelope") or {}).get("observed_at")
        if kind == "producer" else None
    )
    times = [t for t in (fetched_at, producer_observed, snapshot_at) if t]
    if times:
        fetched_at = min(times)
        snapshot_at = max(times)

    return {
        "schema_version": SCHEMA_VERSION,
        "trade_date": trade_date,
        "session": "final",
        "is_final": True,
        "source_ids": source_ids,
        "fetched_at": fetched_at,
        "snapshot_at": snapshot_at,
        "status": status,
        "reason_codes": reason_codes,
        "warnings": warnings,
        "limitations": limitations,
        "source_schema_version": SCHEMA_VERSION,
        "source_status": status,
        "source_reason_codes": reason_codes,
        "sections": sections,
    }
