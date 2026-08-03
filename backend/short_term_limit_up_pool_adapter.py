"""BK-11 涨停池结构化来源适配器 v0.1。

通过 ``astock.em_get`` 请求东财 push2ex 的 ``getTopicZTPool``，
标准化为 ``stock_code + lbc`` 最小行集，并输出失败关闭的十字段合同。

公开 API
--------
``fetch_limit_up_pool_snapshot(requested_trade_date: str) -> dict``

返回的 dict 始终包含完整合同字段（见 __all__ 下方的 SCHEMA_VERSION 与函数签名）。

本版 ``legal_zero`` 始终为 ``False``：本仓库尚无可信 final 快照生产者
可独立证明"当日全市场确实无涨停"，因此适配器阻止空数组被误判为合法零值。
正向 legal-zero 证据依赖未来可信 final 生产者或明确来源证据。

仅使用 ``astock.em_get``，不引入新的 requests Session，不绕过东财
限流路径。不修改 ``trade_calendar`` / ``astock`` 等既有模块。
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import astock
import trade_calendar

__all__ = [
    "SCHEMA_VERSION",
    "fetch_limit_up_pool_snapshot",
]

SCHEMA_VERSION = "short-term-limit-up-pool-adapter-v0.1"

_SOURCE_ID = "eastmoney_getTopicZTPool"
_ENDPOINT = "getTopicZTPool"
_URL = f"https://push2ex.eastmoney.com/{_ENDPOINT}"
_TIMEOUT_SECONDS = 10
_SHANGHAI_TZ = timezone(timedelta(hours=8))

_STRICT_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_EIGHT_DIGIT_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_SIX_DIGIT_RE = re.compile(r"^\d{6}$")
_INCLUDED_PREFIXES = ("60", "00", "30", "68")
_VALID_SESSION_TYPES = (tuple, list, set, frozenset)

# Reason code 固定集合与顺序（未知 code 不得进入输出）
_REASON_CODE_ORDER: tuple[str, ...] = (
    "NON_TRADING_DATE",
    "TRADING_CALENDAR_UNAVAILABLE",
    "REQUEST_TIMEOUT",
    "TRANSPORT_ERROR",
    "RATE_LIMITED",
    "ACCESS_RESTRICTED",
    "HTTP_ERROR",
    "PARSE_ERROR",
    "UPSTREAM_NULL",
    "REQUIRED_FIELD_MISSING",
    "DATA_ARRAY_INVALID",
    "TRADE_DATE_MISMATCH",
    "DATE_BINDING_UNVERIFIED",
    "INVALID_POOL_ROW",
    "DUPLICATE_STOCK_CODE",
    "UNEXPLAINED_EMPTY",
)
_REASON_CODE_SET = frozenset(_REASON_CODE_ORDER)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _strict_parse_date(s: str) -> Optional[date]:
    """严格 YYYY-MM-DD → date 对象；无效日历日期返回 None。"""
    m = _STRICT_DATE_RE.match(s)
    if m is None:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _strict_parse_eight_digit(s: str) -> Optional[date]:
    """严格 YYYYMMDD → date 对象；无效日历日期返回 None。"""
    m = _EIGHT_DIGIT_RE.match(s)
    if m is None:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _safe_http_status(response: object) -> Optional[int]:
    """安全提取 HTTP 状态码。仅接受 int（非 bool），100-599 范围。"""
    if response is None:
        return None
    try:
        code = getattr(response, "status_code", None)
    except Exception:
        return None
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    if code < 100 or code > 599:
        return None
    return code


def _safe_call_json(response: object) -> tuple[Any, Optional[str]]:
    """安全调用 response.json()。返回 ``(payload, error_code)``。

    error_code 为 None 表示成功；否则为 "PARSE_ERROR"。
    """
    if response is None:
        return None, "PARSE_ERROR"
    try:
        json_fn = getattr(response, "json", None)
    except Exception:
        return None, "PARSE_ERROR"
    if json_fn is None or not callable(json_fn):
        return None, "PARSE_ERROR"
    try:
        payload = json_fn()
    except Exception:
        return None, "PARSE_ERROR"
    return payload, None


def _normalize_reason_codes(codes: list[str]) -> list[str]:
    """去重、固定顺序；未知 reason code 丢弃（不得进入输出）。"""
    seen: set[str] = set()
    out: list[str] = []
    for code in _REASON_CODE_ORDER:
        if code in codes and code not in seen:
            out.append(code)
            seen.add(code)
    return out


def _error_class_for(status: str, reason_codes: list[str]) -> str:
    """normal → NONE；partial/unavailable → reason_codes[0]（若空则 NONE）。"""
    if status == "normal":
        return "NONE"
    return reason_codes[0] if reason_codes else "NONE"


def _is_timeout(exc: BaseException) -> bool:
    try:
        import requests
    except Exception:
        return False
    return isinstance(exc, requests.Timeout)


def _is_connection_error(exc: BaseException) -> bool:
    try:
        import requests
    except Exception:
        return False
    return isinstance(exc, requests.ConnectionError)


def _empty_contract(
    *,
    requested_trade_date: str,
    status: str,
    reason_codes: list[str],
    transport_success: bool,
    parse_success: bool,
    required_field_present: bool,
    data_array_present: bool,
    trade_date_match: Optional[bool],
    upstream_null: bool = False,
    unexplained_empty: bool = False,
    coverage_warning: bool = False,
    target_universe_empty_after_filter: bool = False,
    legal_zero: bool = False,
    http_status: Optional[int] = None,
    excluded_universe_count: int = 0,
    invalid_row_count: int = 0,
    duplicate_code_count: int = 0,
    source_pool_row_count: int = 0,
) -> dict:
    normalized = _normalize_reason_codes(reason_codes)
    ec = _error_class_for(status, normalized)
    return {
        "schema_version": SCHEMA_VERSION,
        "source_id": _SOURCE_ID,
        "endpoint": _ENDPOINT,
        "requested_trade_date": requested_trade_date,
        "observed_at": _now_utc_iso(),
        "status": status,
        "reason_codes": normalized,
        "rows": [],
        "transport_success": transport_success,
        "parse_success": parse_success,
        "required_field_present": required_field_present,
        "data_array_present": data_array_present,
        "trade_date_match": trade_date_match,
        "row_count": 0,
        "legal_zero": legal_zero,
        "upstream_null": upstream_null,
        "unexplained_empty": unexplained_empty,
        "coverage_warning": coverage_warning,
        "target_universe_empty_after_filter": target_universe_empty_after_filter,
        "source_pool_row_count": source_pool_row_count,
        "http_status": http_status,
        "error_class": ec,
        "excluded_universe_count": excluded_universe_count,
        "invalid_row_count": invalid_row_count,
        "duplicate_code_count": duplicate_code_count,
    }


# ---------------------------------------------------------------------------
# 交易日历依赖（失败关闭）
# ---------------------------------------------------------------------------

def _load_sessions_safe() -> tuple[Optional[Any], Optional[str]]:
    """安全加载 sessions。返回 ``(sessions, reason_code)``。

    reason_code 为 None 表示成功。
    KeyboardInterrupt/SystemExit 自然传播。
    """
    try:
        sessions = trade_calendar._load_calendar()
    except Exception:
        return None, "TRADING_CALENDAR_UNAVAILABLE"
    if sessions is None:
        return None, "TRADING_CALENDAR_UNAVAILABLE"
    if not isinstance(sessions, _VALID_SESSION_TYPES):
        return None, "TRADING_CALENDAR_UNAVAILABLE"
    return sessions, None


def _today_shanghai_safe() -> tuple[Optional[date], Optional[str]]:
    """安全获取上海今日。返回 ``(today, reason_code)``。"""
    try:
        today = trade_calendar._today_shanghai()
    except Exception:
        return None, "TRADING_CALENDAR_UNAVAILABLE"
    if not isinstance(today, date):
        return None, "TRADING_CALENDAR_UNAVAILABLE"
    return today, None


# ---------------------------------------------------------------------------
# 日期绑定（严格收集全部候选）
# ---------------------------------------------------------------------------

def _evaluate_trade_date_match(
    payload: dict, data_obj: dict, requested_trade_date: str
) -> tuple[Optional[bool], bool]:
    """返回 ``(trade_date_match, mismatch)``。

    收集所有存在且非 null 的候选字段，严格解析为日历日期。
    若存在至少一个合法候选与 requested 不同 → mismatch。
    若所有合法候选均等于 requested → true。
    若无合法候选 → null（不产生 mismatch）。
    """
    candidates_raw: list[Any] = []
    for key in ("trade_date", "date", "qdate"):
        v = payload.get(key)
        if v is not None:
            candidates_raw.append(v)
        v2 = data_obj.get(key)
        if v2 is not None:
            candidates_raw.append(v2)

    parsed_dates: list[date] = []
    has_invalid = False

    for v in candidates_raw:
        d: Optional[date] = None
        if isinstance(v, bool):
            has_invalid = True
            continue
        if isinstance(v, str):
            s = v.strip()
            if _STRICT_DATE_RE.match(s):
                d = _strict_parse_date(s)
            elif _EIGHT_DIGIT_RE.match(s):
                d = _strict_parse_eight_digit(s)
            else:
                has_invalid = True
                continue
        elif isinstance(v, int):
            s = str(v)
            if _EIGHT_DIGIT_RE.match(s):
                d = _strict_parse_eight_digit(s)
            else:
                has_invalid = True
                continue
        else:
            has_invalid = True
            continue
        if d is None:
            has_invalid = True
        else:
            parsed_dates.append(d)

    if not parsed_dates:
        return None, False

    req_date = _strict_parse_date(requested_trade_date)
    has_match = any(d == req_date for d in parsed_dates)
    has_mismatch = any(d != req_date for d in parsed_dates)

    if has_mismatch:
        return False, True
    if has_match:
        return True, False
    return None, False


# ---------------------------------------------------------------------------
# 行标准化
# ---------------------------------------------------------------------------

def _normalize_rows(pool: list) -> tuple[list[dict], int, int, int]:
    """返回 ``(rows, excluded_universe_count, invalid_row_count, duplicate_code_count)``。

    duplicate_code_count 只统计通过格式、lbc 和 universe 校验后的目标 universe 重复。
    excluded_universe_count 每条合法但不属于目标 universe 的来源行均计数
    （重复的 excluded 行仍按来源行分别计入 excluded_universe_count，
    不计 duplicate_code_count）。
    """
    seen: set[str] = set()
    rows: list[dict] = []
    excluded = 0
    invalid = 0
    duplicates = 0
    for entry in pool:
        if not isinstance(entry, dict):
            invalid += 1
            continue
        code = entry.get("c")
        if code is None:
            code = entry.get("code")
        if not isinstance(code, str):
            invalid += 1
            continue
        code = code.strip()
        if not _SIX_DIGIT_RE.match(code):
            invalid += 1
            continue
        lbc_raw = entry.get("lbc")
        if isinstance(lbc_raw, bool) or not isinstance(lbc_raw, int):
            invalid += 1
            continue
        if lbc_raw <= 0:
            invalid += 1
            continue
        # universe 过滤
        if not code.startswith(_INCLUDED_PREFIXES):
            excluded += 1
            continue
        if code in seen:
            duplicates += 1
            continue
        seen.add(code)
        rows.append({"stock_code": code, "lbc": int(lbc_raw)})
    rows.sort(key=lambda x: x["stock_code"])
    return rows, excluded, invalid, duplicates


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def fetch_limit_up_pool_snapshot(requested_trade_date: str) -> dict:
    """对 ``requested_trade_date`` 的涨停池快照执行失败关闭读取。

    返回结构化适配器合同。本函数不会抛出未处理的 transport / timeout /
    JSON / 结构 / 类型异常。KeyboardInterrupt / SystemExit 自然传播。
    """
    # 1) 输入预检
    if not isinstance(requested_trade_date, str) or not requested_trade_date:
        return _empty_contract(
            requested_trade_date=requested_trade_date if isinstance(requested_trade_date, str) else "",
            status="unavailable",
            reason_codes=["NON_TRADING_DATE"],
            transport_success=False,
            parse_success=False,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
        )
    if _STRICT_DATE_RE.match(requested_trade_date) is None:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["NON_TRADING_DATE"],
            transport_success=False,
            parse_success=False,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
        )

    # 2) 交易日校验（不发请求）
    sessions, cal_err = _load_sessions_safe()
    if cal_err is not None:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=[cal_err],
            transport_success=False,
            parse_success=False,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
        )

    today, today_err = _today_shanghai_safe()
    if today_err is not None:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=[today_err],
            transport_success=False,
            parse_success=False,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
        )

    if requested_trade_date not in sessions:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["NON_TRADING_DATE"],
            transport_success=False,
            parse_success=False,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
        )
    req_date_obj = _strict_parse_date(requested_trade_date)
    if req_date_obj is None or req_date_obj > today:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["NON_TRADING_DATE"],
            transport_success=False,
            parse_success=False,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
        )

    # 3) 网络传输
    params = {
        "ut": astock._ZTB_UT,
        "dpt": "wz.ztzt",
        "Pageindex": 0,
        "pagesize": 10000,
        "sort": "fbt:asc",
        "date": requested_trade_date.replace("-", ""),
    }
    headers = {"User-Agent": astock.UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        response = astock.em_get(_URL, params=params, headers=headers,
                                  timeout=_TIMEOUT_SECONDS)
    except Exception as exc:
        if _is_timeout(exc):
            code = "REQUEST_TIMEOUT"
        elif _is_connection_error(exc):
            code = "TRANSPORT_ERROR"
        else:
            code = "TRANSPORT_ERROR"
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=[code],
            transport_success=False,
            parse_success=False,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
        )

    # 4) HTTP 分类（安全提取状态码）
    status_code = _safe_http_status(response)
    if status_code is None:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["HTTP_ERROR"],
            transport_success=True,
            parse_success=False,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
            http_status=None,
        )
    if status_code < 200 or status_code >= 300:
        if status_code == 429:
            code = "RATE_LIMITED"
        elif status_code in (401, 403):
            code = "ACCESS_RESTRICTED"
        else:
            code = "HTTP_ERROR"
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=[code],
            transport_success=True,
            parse_success=False,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
            http_status=status_code,
        )

    # 5) JSON 解析（安全 callable 检查）
    payload, json_err = _safe_call_json(response)
    if json_err is not None:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["PARSE_ERROR"],
            transport_success=True,
            parse_success=False,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
            http_status=status_code,
        )
    if not isinstance(payload, dict):
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["DATA_ARRAY_INVALID"],
            transport_success=True,
            parse_success=False,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
            http_status=status_code,
        )

    # 6) schema：data / data.pool
    #    parse_success = true（JSON 解码成功且顶层为 dict）
    #    required_field_present = data 和 pool 均存在
    #    data_array_present = pool 为 list
    if "data" not in payload:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["REQUIRED_FIELD_MISSING"],
            transport_success=True,
            parse_success=True,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
            http_status=status_code,
        )
    data_obj: Any = payload.get("data")
    if data_obj is None:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["UPSTREAM_NULL"],
            transport_success=True,
            parse_success=True,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
            http_status=status_code,
            upstream_null=True,
        )
    if not isinstance(data_obj, dict):
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["DATA_ARRAY_INVALID"],
            transport_success=True,
            parse_success=True,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
            http_status=status_code,
        )

    if "pool" not in data_obj:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["REQUIRED_FIELD_MISSING"],
            transport_success=True,
            parse_success=True,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
            http_status=status_code,
        )
    pool: Any = data_obj.get("pool")
    if pool is None:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["UPSTREAM_NULL"],
            transport_success=True,
            parse_success=True,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
            http_status=status_code,
            upstream_null=True,
        )
    if not isinstance(pool, list):
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["DATA_ARRAY_INVALID"],
            transport_success=True,
            parse_success=True,
            required_field_present=True,
            data_array_present=False,
            trade_date_match=None,
            http_status=status_code,
        )

    # pool 为 list → source_pool_row_count 可确定
    source_count = len(pool)

    # 7) trade_date_match（严格收集全部候选）
    trade_date_match, mismatch = _evaluate_trade_date_match(
        payload, data_obj, requested_trade_date)
    if mismatch:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["TRADE_DATE_MISMATCH"],
            transport_success=True,
            parse_success=True,
            required_field_present=True,
            data_array_present=True,
            trade_date_match=False,
            http_status=status_code,
            source_pool_row_count=source_count,
        )

    # 8) 行标准化 + universe 过滤
    rows, excluded_universe, invalid_rows, duplicates = _normalize_rows(pool)

    # 9) 空结果分类（三种类型）
    if not rows:
        # 类型 1: source pool 原始为空
        if source_count == 0:
            return _empty_contract(
                requested_trade_date=requested_trade_date,
                status="partial",
                reason_codes=["UNEXPLAINED_EMPTY"],
                transport_success=True,
                parse_success=True,
                required_field_present=True,
                data_array_present=True,
                trade_date_match=trade_date_match,
                http_status=status_code,
                unexplained_empty=True,
                coverage_warning=True,
                source_pool_row_count=0,
            )

        # 类型 2: 全部因 universe 排除（无 invalid，无 duplicate）
        target_universe = (
            excluded_universe > 0
            and invalid_rows == 0
            and duplicates == 0
            and excluded_universe == source_count
        )

        if target_universe:
            reason_codes: list[str] = []
            if trade_date_match is None:
                reason_codes.append("DATE_BINDING_UNVERIFIED")
            is_normal = (trade_date_match is True)
            return _empty_contract(
                requested_trade_date=requested_trade_date,
                status="normal" if is_normal else "partial",
                reason_codes=reason_codes,
                transport_success=True,
                parse_success=True,
                required_field_present=True,
                data_array_present=True,
                trade_date_match=trade_date_match,
                http_status=status_code,
                unexplained_empty=False,
                coverage_warning=not is_normal,
                target_universe_empty_after_filter=True,
                source_pool_row_count=source_count,
                excluded_universe_count=excluded_universe,
            )

        # 类型 3: 全部无效 或 invalid+excluded 混合
        reason_codes = []
        if trade_date_match is None:
            reason_codes.append("DATE_BINDING_UNVERIFIED")
        if invalid_rows:
            reason_codes.append("INVALID_POOL_ROW")
        if duplicates:
            reason_codes.append("DUPLICATE_STOCK_CODE")
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="partial",
            reason_codes=reason_codes,
            transport_success=True,
            parse_success=True,
            required_field_present=True,
            data_array_present=True,
            trade_date_match=trade_date_match,
            http_status=status_code,
            unexplained_empty=False,
            coverage_warning=True,
            source_pool_row_count=source_count,
            excluded_universe_count=excluded_universe,
            invalid_row_count=invalid_rows,
            duplicate_code_count=duplicates,
        )

    # 10) 非空结果
    reason_codes = []
    coverage_warning = False
    if trade_date_match is None:
        reason_codes.append("DATE_BINDING_UNVERIFIED")
        coverage_warning = True
    if invalid_rows:
        reason_codes.append("INVALID_POOL_ROW")
        coverage_warning = True
    if duplicates:
        reason_codes.append("DUPLICATE_STOCK_CODE")
        coverage_warning = True
    status = "normal" if (trade_date_match is True
                           and not invalid_rows and not duplicates) else "partial"
    normalized = _normalize_reason_codes(reason_codes)
    ec = _error_class_for(status, normalized)
    return {
        "schema_version": SCHEMA_VERSION,
        "source_id": _SOURCE_ID,
        "endpoint": _ENDPOINT,
        "requested_trade_date": requested_trade_date,
        "observed_at": _now_utc_iso(),
        "status": status,
        "reason_codes": normalized,
        "rows": rows,
        "transport_success": True,
        "parse_success": True,
        "required_field_present": True,
        "data_array_present": True,
        "trade_date_match": trade_date_match,
        "row_count": len(rows),
        "legal_zero": False,
        "upstream_null": False,
        "unexplained_empty": False,
        "coverage_warning": coverage_warning,
        "target_universe_empty_after_filter": False,
        "source_pool_row_count": source_count,
        "http_status": status_code,
        "error_class": ec,
        "excluded_universe_count": excluded_universe,
        "invalid_row_count": invalid_rows,
        "duplicate_code_count": duplicates,
    }
