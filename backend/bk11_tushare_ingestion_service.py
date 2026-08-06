"""BK-11 Tushare 生产 ingestion service（v0.2）。

显式入口流程（每个交易日 single-flight，只处理已确认结束的交易日）：

    Tushare facts snapshot
      → limit_up_count==0 且 legal_zero ? 空 ladder 证明 : 东财 final producer
      → compute_daily_facts_v02
      → 输出重校验
      → save_daily_facts_monotonic

边界：

- 不在 GET / 应用启动 / Daily Review / history API / Data Health 中调用；
- 无自动调度、无批量回填、无最近非空交易日回退；
- 异常文案清洗，不泄漏 Token / URL / 路径 / 原始异常 / provider 原文；
- KeyboardInterrupt / SystemExit / GeneratorExit 自然传播。
"""

from __future__ import annotations

import re
import threading
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import bk11_tushare_facts_adapter as facts_adapter
import short_term_daily_facts_v02 as facts_v02
import short_term_fact_store as store
import trade_calendar
import tushare_pro_client as tpc

SCHEMA_VERSION = "bk11-tushare-ingestion-v0.2"

_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BEIJING = ZoneInfo("Asia/Shanghai")

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


def _lock_for(trade_date: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(trade_date)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[trade_date] = lock
        return lock


def _sessions_safe() -> tuple[set[str] | None, str | None]:
    try:
        sessions = trade_calendar._load_calendar()
    except Exception:
        return None, "TRADING_CALENDAR_UNAVAILABLE"
    if not isinstance(sessions, (tuple, list, set, frozenset)) or not sessions:
        return None, "TRADING_CALENDAR_UNAVAILABLE"
    for item in sessions:
        if not isinstance(item, str) or _TRADE_DATE_RE.match(item) is None:
            return None, "TRADING_CALENDAR_UNAVAILABLE"
    return set(sessions), None


def _today_shanghai() -> str | None:
    try:
        return datetime.now(_BEIJING).date().isoformat()
    except Exception:
        return None


def _error_response(
    trade_date: str,
    *,
    status: str,
    reason_code: str,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "action": "ingest",
        "trade_date": trade_date,
        "status": status,
        "saved": False,
        "deduped": False,
        "upgraded": False,
        "blocked": True,
        "reason_code": reason_code,
        "limitations": limitations or [reason_code],
        "snapshot": None,
    }


def ingest_trade_date(
    trade_date: str,
    *,
    client: tpc.TushareClient | None = None,
    store_db: str | None = None,
) -> dict[str, Any]:
    """对单个已确认结束的交易日执行显式 ingestion（single-flight）。"""
    if type(trade_date) is not str or _TRADE_DATE_RE.match(trade_date) is None:
        return _error_response(
            trade_date if isinstance(trade_date, str) else "",
            status="error",
            reason_code="INVALID_TRADE_DATE",
        )
    try:
        date.fromisoformat(trade_date)
    except ValueError:
        return _error_response(
            trade_date, status="error", reason_code="INVALID_TRADE_DATE")

    today = _today_shanghai()
    if today is None:
        return _error_response(
            trade_date, status="error", reason_code="CLOCK_UNAVAILABLE")
    if trade_date >= today:
        return _error_response(
            trade_date,
            status="blocked",
            reason_code="NOT_FINALIZED",
            limitations=["只处理严格早于今日的已确认结束交易日"],
        )

    sessions, cal_reason = _sessions_safe()
    if sessions is None:
        return _error_response(
            trade_date, status="error", reason_code=cal_reason or "CALENDAR_UNAVAILABLE")
    if trade_date not in sessions:
        return _error_response(
            trade_date,
            status="blocked",
            reason_code="NON_TRADING_DATE",
            limitations=["目标日期不是离线日历确认的交易日"],
        )

    lock = _lock_for(trade_date)
    with lock:
        try:
            existing = _existing_v02(trade_date, store_db)
        except store.FactStoreCorruptedError:
            return _error_response(
                trade_date, status="error", reason_code="STORAGE_FAILED",
                limitations=["短期事实存储无法安全读取"])
        if existing is not None:
            return {
                "schema_version": SCHEMA_VERSION,
                "action": "ingest",
                "trade_date": trade_date,
                "status": "deduped",
                "saved": False,
                "deduped": True,
                "upgraded": False,
                "blocked": False,
                "reason_code": "DEDUPED",
                "limitations": ["该交易日已存在 v0.2 normal 记录，未重复采集"],
                "snapshot": existing,
            }
        return _ingest_locked(trade_date, client=client, store_db=store_db)


def _existing_v02(
    trade_date: str,
    store_db: str | None,
) -> dict[str, Any] | None:
    """只读检查该 key 是否已有 v0.2 记录（不创建数据库）。"""
    path = store.resolve_db_path(store_db)
    if not path.exists():
        return None
    try:
        envelope = store.load_daily_facts(trade_date, "final", db_path=path)
    except store.FactStoreCorruptedError:
        raise
    except store.FactStoreError:
        return None
    if envelope is None or envelope.get("schema_version") != (
            store.STORED_SCHEMA_VERSION_V02):
        return None
    if envelope.get("status") != "normal":
        # partial 记录放行：允许生产入口重跑升级为 normal（store 单调规则）
        return None
    return {
        "trade_date": envelope.get("trade_date"),
        "session": envelope.get("session"),
        "schema_version": envelope.get("schema_version"),
        "stored_at": None,
    }


def _ingest_locked(
    trade_date: str,
    *,
    client: tpc.TushareClient | None,
    store_db: str | None,
) -> dict[str, Any]:
    try:
        facts = facts_adapter.fetch_tushare_facts_snapshot(trade_date, client)
    except tpc.TushareCredentialMissing:
        return _error_response(
            trade_date, status="error", reason_code="CREDENTIAL_MISSING",
            limitations=["TUSHARE_TOKEN 未配置"])
    except tpc.TusharePermissionDenied:
        return _error_response(
            trade_date, status="error", reason_code="PERMISSION_DENIED",
            limitations=["Tushare 权限不足"])
    except tpc.TushareTransportError:
        return _error_response(
            trade_date, status="error", reason_code="SOURCE_UNAVAILABLE",
            limitations=["Tushare 网络请求失败"])

    if facts.get("status") != "normal" and facts.get("status") != "partial":
        return _error_response(
            trade_date, status="error", reason_code="CONTRACT_FAILED",
            limitations=facts.get("limitations") or ["Tushare 合同校验失败"])

    limit_up_count = int(facts.get("limit_activity", {}).get("limit_up_count") or 0)
    if limit_up_count == 0 and facts.get("legal_zero") is True:
        ladder_input: dict[str, Any] = {"kind": "empty_ladder_proof"}
    else:
        import short_term_limit_up_final_snapshot as final_producer
        producer = final_producer.fetch_final_limit_up_pool_snapshot(trade_date)
        ladder_input = {"kind": "producer", "envelope": producer}

    envelope = facts_v02.compute_daily_facts_v02(facts, ladder_input)
    if (
        envelope.get("schema_version") != facts_v02.SCHEMA_VERSION
        or envelope.get("trade_date") != trade_date
        or envelope.get("session") != "final"
        or envelope.get("is_final") is not True
        or envelope.get("status") not in ("normal", "partial")
    ):
        return _error_response(
            trade_date, status="error", reason_code="ENVELOPE_VALIDATION_FAILED",
            limitations=["v0.2 输出重校验失败"])

    try:
        result = store.save_daily_facts_monotonic(
            envelope, db_path=store_db)
    except store.FactStoreCorruptedError:
        return _error_response(
            trade_date, status="error", reason_code="STORAGE_FAILED",
            limitations=["短期事实存储无法安全写入"])
    except store.FactStoreError:
        return _error_response(
            trade_date, status="error", reason_code="STORAGE_FAILED",
            limitations=["短期事实存储写入被拒绝"])

    status = envelope.get("status")
    if result.get("blocked"):
        status = "blocked"
    elif result.get("deduped"):
        status = "deduped"
    return {
        "schema_version": SCHEMA_VERSION,
        "action": "ingest",
        "trade_date": trade_date,
        "status": status,
        "saved": bool(result.get("saved")),
        "deduped": bool(result.get("deduped")),
        "upgraded": bool(result.get("upgraded")),
        "blocked": bool(result.get("blocked")),
        "reason_code": result.get("reason_code"),
        "limitations": envelope.get("limitations") or [],
        "snapshot": result.get("snapshot"),
    }
