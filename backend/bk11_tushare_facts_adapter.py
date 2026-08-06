"""BK-11 Tushare 市场事实适配器（ingestion v0.2）。

对指定、已确认结束的 A 股交易日 T，通过 Tushare 的 daily / suspend_d /
stk_limit / stock_basic 四个接口生成具备严格交易日绑定的市场宽度与
涨跌停活动输入（``facts_snapshot``），供 ``short_term_daily_facts_v02``
组合使用。

职责边界：

- 市场宽度 / 涨跌停活动 / facts_data_health 由 Tushare 提供；
- 连板梯队与断层仍由东方财富 final producer 负责（本模块不调用）；
- 不修改任何输入；失败关闭；不把空响应解释为合法零；
- 不使用 stock_basic 总数反推 eligible_count。
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import tushare_pro_client as tpc

SCHEMA_VERSION = "bk11-tushare-facts-adapter-v0.1"

_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TS_CODE_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
_SYMBOL_PREFIXES = ("60", "00", "30", "68")  # A 股：排除 B 股/基金/指数/北交所
_ALLOWED_LIST_STATUS = ("L", "D", "P", "G")
_SUSPEND_TYPE_FULL_DAY = "S"
_PRICE_PRECISION = Decimal("0.01")

# 未解释缺口安全阈值（审计确定：相对 5% 或绝对 50 只）
_MISSING_RATIO_LIMIT = 0.05
_MISSING_COUNT_LIMIT = 50


class TushareFactsContractError(RuntimeError):
    """来源合同失败（fail-closed，不写入任何数据）。"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="microseconds").replace("+00:00", "Z")


def _strict_date(value: Any) -> str | None:
    """归一化 YYYYMMDD / YYYY-MM-DD；非法返回 None。"""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _TRADE_DATE_RE.match(text):
        return text
    if len(text) == 8 and text.isdigit():
        try:
            d = date(int(text[:4]), int(text[4:6]), int(text[6:]))
            return d.isoformat()
        except ValueError:
            return None
    return None


def _valid_ts_code(code: Any) -> bool:
    if not isinstance(code, str):
        return False
    m = _TS_CODE_RE.match(code.strip())
    if m is None:
        return False
    symbol = code.strip()[:6]
    return symbol.startswith(_SYMBOL_PREFIXES)


def _finite_number(value: Any) -> float | None:
    """把 Tushare 数值（数字或数字字符串）归一化为有限 float；否则 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        return num if math.isfinite(num) else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            num = float(text)
        except ValueError:
            return None
        return num if math.isfinite(num) else None
    return None


def _decimal(value: Any) -> Decimal | None:
    """严格 Decimal 归一化（0.01 价位比较用）；非法返回 None。"""
    num = _finite_number(value)
    if num is None:
        return None
    return Decimal(str(num))


def _normalize_rows(
    rows: list[dict[str, Any]],
    trade_date: str,
    api_name: str,
    required: tuple[str, ...],
    *,
    retain_missing_numeric: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """逐行校验：日期匹配、ts_code 合法、唯一、必需字段、有限数值。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    errors: list[str] = []
    for row in rows:
        if type(row) is not dict:
            errors.append("ROW_NOT_DICT")
            continue
        code = row.get("ts_code")
        if not _valid_ts_code(code):
            errors.append("INVALID_TS_CODE")
            continue
        code = code.strip()
        if code in seen:
            errors.append("DUPLICATE_TS_CODE")
            continue
        row_date = _strict_date(row.get("trade_date"))
        if row_date != trade_date:
            errors.append("TRADE_DATE_MISMATCH")
            continue
        missing = [f for f in required if f not in row or row[f] is None]
        if missing:
            errors.append(f"MISSING_FIELD:{missing[0]}")
            # daily 数值字段缺失：保留行以便后续 fail-closed 判定
            # （不得静默丢弃后当作未解释缺口或停牌）。
            if retain_missing_numeric and missing[0] in (
                    "pct_chg", "close", "high"):
                seen.add(code)
                out.append(dict(row))
            continue
        seen.add(code)
        out.append(dict(row))
    return out, errors


def _stock_basic_pool(
    rows: list[dict[str, Any]],
    trade_date: str,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """历史 A 股股票池：状态合并、按 ts_code 去重、冲突失败关闭。"""
    pool: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for row in rows:
        if type(row) is not dict:
            errors.append("BASIC_ROW_NOT_DICT")
            continue
        code = row.get("ts_code")
        if not _valid_ts_code(code):
            continue  # 非 A 股代码不进池（B 股/基金/指数等）
        code = code.strip()
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or symbol != code[:6]:
            errors.append("BASIC_SYMBOL_MISMATCH")
            continue
        list_status = row.get("list_status")
        if list_status not in _ALLOWED_LIST_STATUS:
            errors.append("BASIC_LIST_STATUS_INVALID")
            continue
        list_date = _strict_date(row.get("list_date"))
        delist_date = _strict_date(row.get("delist_date"))
        if list_date is None:
            errors.append("BASIC_LIST_DATE_MISSING")
            continue
        entry = {
            "ts_code": code,
            "symbol": symbol,
            "list_status": list_status,
            "list_date": list_date,
            "delist_date": delist_date,
        }
        existing = pool.get(code)
        if existing is not None:
            if (
                existing["list_status"] != list_status
                or existing["list_date"] != list_date
                or existing["delist_date"] != delist_date
            ):
                errors.append("BASIC_STATUS_CONFLICT")
            continue
        pool[code] = entry
    return pool, errors


def _price_bucket(
    close: Decimal | None,
    high: Decimal | None,
    up_limit: Decimal | None,
    down_limit: Decimal | None,
) -> tuple[str | None, str | None]:
    """按 0.01 价位归一化判定：返回 (limit_hit, failed) 标记。"""
    if close is None:
        return None, None
    cq = close.quantize(_PRICE_PRECISION)
    hit: str | None = None
    failed: str | None = None
    if up_limit is not None:
        uq = up_limit.quantize(_PRICE_PRECISION)
        if cq >= uq:
            hit = "up"
        elif high is not None:
            hq = high.quantize(_PRICE_PRECISION)
            if hq >= uq:
                failed = "up"
    if down_limit is not None:
        dq = down_limit.quantize(_PRICE_PRECISION)
        if cq <= dq:
            hit = "down"
    return hit, failed


def fetch_tushare_facts_snapshot(
    trade_date: str,
    client: tpc.TushareClient | None = None,
) -> dict[str, Any]:
    """获取 T 日 Tushare 市场事实 snapshot（失败关闭，永不写库）。"""
    if type(trade_date) is not str or _TRADE_DATE_RE.match(trade_date) is None:
        return _invalid_envelope(trade_date, ["INVALID_TRADE_DATE"])
    try:
        date.fromisoformat(trade_date)
    except ValueError:
        return _invalid_envelope(trade_date, ["INVALID_TRADE_DATE"])
    if client is None:
        client = tpc.TushareClient()

    try:
        daily_rows = client.query(
            "daily",
            {"trade_date": trade_date.replace("-", "")},
            "ts_code,trade_date,high,close,pct_chg",
        )
        suspend_rows = client.query(
            "suspend_d",
            {"trade_date": trade_date.replace("-", "")},
            "ts_code,trade_date,suspend_timing,suspend_type",
        )
        stk_rows = client.query(
            "stk_limit",
            {"trade_date": trade_date.replace("-", "")},
            "ts_code,trade_date,up_limit,down_limit",
        )
        basic_rows: list[dict[str, Any]] = []
        for status in _ALLOWED_LIST_STATUS:
            basic_rows.extend(
                client.query(
                    "stock_basic",
                    {"list_status": status},
                    "ts_code,symbol,exchange,market,list_status,list_date,delist_date",
                )
            )
    except (tpc.TushareCredentialMissing, tpc.TusharePermissionDenied,
            tpc.TushareTransportError):
        raise
    except tpc.TushareClientError:
        return _invalid_envelope(trade_date, ["SOURCE_CONTRACT_INVALID"])

    # ---- 逐接口行校验 ----
    daily, daily_err = _normalize_rows(
        daily_rows, trade_date, "daily",
        ("trade_date", "close", "pct_chg"),
        retain_missing_numeric=True)
    if not daily_rows:
        # 空响应绝不等于合法零：当日无任何 daily 记录 → 失败关闭
        return _invalid_envelope(
            trade_date,
            ["EMPTY_DAILY"],
            limitations=["Tushare daily 返回空（不得解释为合法零）"],
        )
    suspend, suspend_err = _normalize_rows(
        suspend_rows, trade_date, "suspend_d", ("trade_date", "suspend_type"))
    stk, stk_err = _normalize_rows(
        stk_rows, trade_date, "stk_limit", ("trade_date", "up_limit", "down_limit"))
    pool, basic_err = _stock_basic_pool(basic_rows, trade_date)

    all_errors = (daily_err + suspend_err + stk_err + basic_err)
    strict_errors = [
        e for e in all_errors
        if e != "INVALID_TS_CODE" and not e.startswith("MISSING_FIELD")
    ]
    transport_ok = True  # 异常已在上方处理

    # ---- 股票池过滤：上市/退市边界 ----
    pool_codes = set()
    delisted_excluded = 0
    boundary_uncertain = False
    for code, entry in pool.items():
        if entry["list_date"] > trade_date:
            continue
        if entry["delist_date"] is not None:
            boundary_uncertain = True
            if entry["delist_date"] <= trade_date:
                delisted_excluded += 1
                continue
        pool_codes.add(code)

    daily_codes = {r["ts_code"] for r in daily}
    suspend_full = {
        r["ts_code"] for r in suspend
        if str(r.get("suspend_type")) == _SUSPEND_TYPE_FULL_DAY
    }
    suspend_any = {r["ts_code"] for r in suspend}

    suspended_codes = suspend_full - daily_codes
    intraday_suspend = suspend_full & daily_codes
    eligible_codes = daily_codes | suspended_codes

    # ---- 未解释缺口 ----
    unexplained = pool_codes - daily_codes - suspended_codes
    out_of_pool = (daily_codes | suspended_codes) - pool_codes
    coverage_warning = (
        bool(unexplained) or bool(out_of_pool) or boundary_uncertain)
    pool_total = max(1, len(pool_codes))
    missing_ratio = len(unexplained) / pool_total
    if (len(unexplained) > _MISSING_COUNT_LIMIT
            and missing_ratio > _MISSING_RATIO_LIMIT):
        return _invalid_envelope(
            trade_date,
            ["UNEXPLAINED_UNIVERSE_GAP"],
            limitations=["未解释股票池缺口超过安全阈值"],
        )

    # ---- 市场宽度 ----
    invalid_pct = [r for r in daily if _finite_number(r.get("pct_chg")) is None]
    if invalid_pct:
        return _invalid_envelope(
            trade_date,
            ["INVALID_PCT_CHG"],
            limitations=["daily 中存在非法 pct_chg，无法满足 eligible 恒等式"],
        )
    advance = sum(1 for r in daily if (_finite_number(r["pct_chg"]) or 0) > 0)
    decline = sum(1 for r in daily if (_finite_number(r["pct_chg"]) or 0) < 0)
    flat = sum(1 for r in daily if (_finite_number(r["pct_chg"]) or 0) == 0)
    valid_count = advance + decline + flat
    if len(eligible_codes) != valid_count + len(suspended_codes):
        return _invalid_envelope(
            trade_date,
            ["BREADTH_IDENTITY_INVALID"],
            limitations=["eligible 恒等式不成立"],
        )

    # ---- 涨跌停活动 ----
    stk_by_code = {r["ts_code"]: r for r in stk}
    join_gap = [c for c in daily_codes if c not in stk_by_code]
    if join_gap:
        coverage_warning = True
    gap_ratio = len(join_gap) / max(1, len(daily_codes))
    if (len(join_gap) > _MISSING_COUNT_LIMIT
            and gap_ratio > _MISSING_RATIO_LIMIT):
        return _invalid_envelope(
            trade_date,
            ["STK_LIMIT_JOIN_GAP"],
            limitations=["stk_limit 对 daily 覆盖缺口超过安全阈值"],
        )

    limit_up_count = 0
    limit_down_count = 0
    failed_limit_up_count = 0
    invalid_price_rows = 0
    for r in daily:
        close = _decimal(r.get("close"))
        high = _decimal(r.get("high"))
        stk = stk_by_code.get(r["ts_code"])
        up_limit = _decimal(stk.get("up_limit")) if stk else None
        down_limit = _decimal(stk.get("down_limit")) if stk else None
        if close is None or up_limit is None or down_limit is None:
            invalid_price_rows += 1
            continue
        hit, failed = _price_bucket(close, high, up_limit, down_limit)
        if hit == "up":
            limit_up_count += 1
        elif hit == "down":
            limit_down_count += 1
        if failed == "up":
            failed_limit_up_count += 1
    if invalid_price_rows:
        coverage_warning = True

    touched = limit_up_count + failed_limit_up_count
    seal_rate = round(limit_up_count / touched, 4) if touched else None
    failed_board_rate = round(failed_limit_up_count / touched, 4) if touched else None

    # ---- legal zero：11 条件 ----
    legal_zero = (
        not strict_errors
        and bool(daily_rows)
        and len(join_gap) == 0
        and invalid_price_rows == 0
        and not unexplained
        and not out_of_pool
        and limit_up_count == 0
        and limit_down_count == 0
        and failed_limit_up_count == 0
        and isinstance(suspend_rows, list)
    )

    status = "normal"
    reason_codes: list[str] = []
    warnings: list[str] = []
    if strict_errors:
        status = "unavailable"
        reason_codes = ["ROW_CONTRACT_INVALID"]
    elif coverage_warning or join_gap or invalid_price_rows:
        status = "partial"
        reason_codes = ["COVERAGE_WARNING"]
    if intraday_suspend:
        warnings.append(
            f"intraday suspend stocks: {len(intraday_suspend)}")
    if delisted_excluded:
        warnings.append(f"delisted excluded from pool: {delisted_excluded}")

    health = {
        "transport_success": transport_ok,
        "parse_success": transport_ok and not strict_errors,
        "required_field_present": not strict_errors,
        "data_array_present": bool(daily_rows),
        "trade_date_match": not strict_errors,
        "row_count": len(daily_rows) + len(suspend_rows) + len(stk_rows),
        "legal_zero": legal_zero,
        "upstream_null": False,
        "unexplained_empty": bool(unexplained),
        "coverage_warning": coverage_warning,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "trade_date": trade_date,
        "session": "final",
        "is_final": True,
        "source_ids": [
            "tushare_daily",
            "tushare_suspend_d",
            "tushare_stk_limit",
            "tushare_stock_basic",
        ],
        "fetched_at": _utc_now_iso(),
        "snapshot_at": _utc_now_iso(),
        "status": status,
        "reason_codes": reason_codes,
        "warnings": warnings,
        "limitations": (
            ["Tushare 第三方数据服务，非交易所直发"]
            + (["stk_limit 对 daily 存在未解释 join 缺口"]
               if join_gap else [])
            + (["退市边界按 T < delist_date 在池；官方合同语义未确认"]
               if boundary_uncertain else [])
        ),
        "breadth": {
            "advance_count": advance,
            "decline_count": decline,
            "flat_count": flat,
            "suspended_count": len(suspended_codes),
            "eligible_count": len(eligible_codes),
            "valid_count": valid_count,
            "intraday_suspend_count": len(intraday_suspend),
        },
        "limit_activity": {
            "limit_up_count": limit_up_count,
            "limit_down_count": limit_down_count,
            "failed_limit_up_count": failed_limit_up_count,
            "touched_limit_up_count": touched,
            "sealed_limit_up_count": limit_up_count,
            "failed_board_rate": failed_board_rate,
            "seal_rate": seal_rate,
        },
        "facts_data_health": health,
        "legal_zero": legal_zero,
        "universe": {
            "historical_pool_count": len(pool_codes),
            "daily_unique_count": len(daily_codes),
            "suspended_full_day_count": len(suspended_codes),
            "intraday_suspend_count": len(intraday_suspend),
            "unexplained_missing_count": len(unexplained),
            "out_of_pool_count": len(out_of_pool),
            "stk_limit_join_gap_count": len(join_gap),
            "invalid_price_rows": invalid_price_rows,
            "delisted_excluded_count": delisted_excluded,
            "boundary_uncertain": boundary_uncertain,
        },
        "sources": [
            {"source_id": "tushare_daily", "api_name": "daily",
             "row_count": len(daily_rows)},
            {"source_id": "tushare_suspend_d", "api_name": "suspend_d",
             "row_count": len(suspend_rows)},
            {"source_id": "tushare_stk_limit", "api_name": "stk_limit",
             "row_count": len(stk_rows)},
            {"source_id": "tushare_stock_basic", "api_name": "stock_basic",
             "row_count": len(basic_rows)},
        ],
    }


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
        "fetched_at": _utc_now_iso(),
        "snapshot_at": _utc_now_iso(),
        "status": "unavailable",
        "reason_codes": reason_codes,
        "warnings": [],
        "limitations": limitations or ["Tushare 市场事实合同校验失败"],
        "breadth": None,
        "limit_activity": None,
        "facts_data_health": {
            "transport_success": True,
            "parse_success": False,
            "required_field_present": False,
            "data_array_present": False,
            "trade_date_match": False,
            "row_count": 0,
            "legal_zero": False,
            "upstream_null": False,
            "unexplained_empty": False,
            "coverage_warning": True,
        },
        "legal_zero": False,
        "universe": None,
        "sources": [],
    }
