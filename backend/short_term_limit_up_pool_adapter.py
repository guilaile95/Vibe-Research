"""BK-11 涨停池结构化来源适配器 v0.1。

通过 ``astock.em_get`` 请求东财 push2ex 的 ``getTopicZTPool``，
标准化为 ``stock_code + lbc`` 最小行集，并输出失败关闭的十字段合同。

公开 API
--------
``fetch_limit_up_pool_snapshot(requested_trade_date: str) -> dict``

返回的 dict 始终包含 ``schema_version / source_id / endpoint /
requested_trade_date / observed_at / status / reason_codes / rows /
transport_success / parse_success / required_field_present /
data_array_present / trade_date_match / row_count / legal_zero /
upstream_null / unexplained_empty / coverage_warning / http_status /
error_class / excluded_universe_count / invalid_row_count /
duplicate_code_count``。

本版 ``legal_zero`` 始终为 ``False``：本仓库尚无可信 final 快照生产者
可独立证明"当日全市场确实无涨停"，因此适配器阻止空数组被误判为合法零值。
正向 legal-zero 证据依赖未来可信 final 生产者或明确来源证据。

仅使用 ``astock.em_get``，不引入新的 requests Session，不绕过东财
限流路径。不修改 ``trade_calendar`` / ``astock`` 等既有模块。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
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

# Reason code 固定顺序（不得依赖 set 无序输出）
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


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _today_shanghai():
    # 只读复用 trade_calendar 私有函数；不修改其模块
    return trade_calendar._today_shanghai()


def _strict_parse_date(s: str):
    m = _STRICT_DATE_RE.match(s)
    if m is None:
        return None
    try:
        from datetime import date
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


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
    legal_zero: bool = False,
    http_status: Optional[int] = None,
    error_class: str = "NONE",
    excluded_universe_count: int = 0,
    invalid_row_count: int = 0,
    duplicate_code_count: int = 0,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_id": _SOURCE_ID,
        "endpoint": _ENDPOINT,
        "requested_trade_date": requested_trade_date,
        "observed_at": _now_utc_iso(),
        "status": status,
        "reason_codes": _normalize_reason_codes(reason_codes),
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
        "http_status": http_status,
        "error_class": error_class,
        "excluded_universe_count": excluded_universe_count,
        "invalid_row_count": invalid_row_count,
        "duplicate_code_count": duplicate_code_count,
    }


def _normalize_reason_codes(codes: list[str]) -> list[str]:
    """去重、保持固定顺序；不允许集合无序输出。"""
    seen: set[str] = set()
    out: list[str] = []
    for code in _REASON_CODE_ORDER:
        if code in codes and code not in seen:
            out.append(code)
            seen.add(code)
    for code in codes:
        if code not in seen:
            # 未知 reason code 也保留，但追加在末尾（防御性）
            out.append(code)
            seen.add(code)
    return out


def _is_timeout(exc: BaseException) -> bool:
    """精确判断超时类异常（不依赖字符串匹配）。"""
    # requests 异常层级：ConnectTimeout/ReadTimeout 都继承 Timeout
    try:
        import requests  # local import：仅用于异常类型判断
    except Exception:
        return False
    return isinstance(exc, requests.Timeout)


def _is_connection_error(exc: BaseException) -> bool:
    try:
        import requests
    except Exception:
        return False
    return isinstance(exc, requests.ConnectionError)


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def fetch_limit_up_pool_snapshot(requested_trade_date: str) -> dict:
    """对 ``requested_trade_date`` 的涨停池快照执行失败关闭读取。

    返回结构化适配器合同（见模块 docstring）。本函数永远不会抛出未处理的
    transport / timeout / JSON / 结构 / 类型异常。
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
    sessions = trade_calendar._load_calendar()
    if sessions is None:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["TRADING_CALENDAR_UNAVAILABLE"],
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
    if req_date_obj is None or req_date_obj > _today_shanghai():
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

    # 3) 网络传输（精确异常分类）
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
    except BaseException as exc:  # noqa: BLE001 - 精确分类后结构化返回
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
            error_class=code,
        )

    # 4) HTTP 分类
    status_code = int(getattr(response, "status_code", 0) or 0)
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
            error_class=code,
        )

    # 5) JSON 解析
    try:
        payload = response.json()
    except BaseException:  # noqa: BLE001
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
            error_class="PARSE_ERROR",
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
            error_class="DATA_ARRAY_INVALID",
        )

    # 6) schema：data / data.pool
    if "data" not in payload:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["REQUIRED_FIELD_MISSING"],
            transport_success=True,
            parse_success=False,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
            http_status=status_code,
            error_class="REQUIRED_FIELD_MISSING",
        )
    data_obj: Any = payload.get("data")
    if data_obj is None:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["UPSTREAM_NULL"],
            transport_success=True,
            parse_success=False,
            required_field_present=True,
            data_array_present=False,
            trade_date_match=None,
            http_status=status_code,
            upstream_null=True,
            error_class="UPSTREAM_NULL",
        )
    if not isinstance(data_obj, dict):
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["DATA_ARRAY_INVALID"],
            transport_success=True,
            parse_success=False,
            required_field_present=True,
            data_array_present=False,
            trade_date_match=None,
            http_status=status_code,
            error_class="DATA_ARRAY_INVALID",
        )

    if "pool" not in data_obj:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["REQUIRED_FIELD_MISSING"],
            transport_success=True,
            parse_success=False,
            required_field_present=False,
            data_array_present=False,
            trade_date_match=None,
            http_status=status_code,
            error_class="REQUIRED_FIELD_MISSING",
        )
    pool: Any = data_obj.get("pool")
    if pool is None:
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["UPSTREAM_NULL"],
            transport_success=True,
            parse_success=False,
            required_field_present=True,
            data_array_present=False,
            trade_date_match=None,
            http_status=status_code,
            upstream_null=True,
            error_class="UPSTREAM_NULL",
        )
    if not isinstance(pool, list):
        return _empty_contract(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["DATA_ARRAY_INVALID"],
            transport_success=True,
            parse_success=False,
            required_field_present=True,
            data_array_present=True,
            trade_date_match=None,
            http_status=status_code,
            error_class="DATA_ARRAY_INVALID",
        )

    # 7) trade_date_match
    trade_date_match, mismatch = _evaluate_trade_date_match(payload, data_obj,
                                                              requested_trade_date)
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
            error_class="TRADE_DATE_MISMATCH",
        )

    # 8) 行标准化 + universe 过滤
    rows, excluded_universe, invalid_rows, duplicates = _normalize_rows(pool)

    # 9) 空池语义：legal_zero 始终 false；unexplained_empty = true
    if not rows and not pool:
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
            legal_zero=False,
            excluded_universe_count=excluded_universe,
            invalid_row_count=invalid_rows,
            duplicate_code_count=duplicates,
            error_class="UNEXPLAINED_EMPTY",
        )
    if not rows and pool:
        # pool 非空但全部被过滤：根据具体原因附加 reason codes
        reason_codes: list[str] = []
        if invalid_rows:
            reason_codes.append("INVALID_POOL_ROW")
        if duplicates:
            reason_codes.append("DUPLICATE_STOCK_CODE")
        if excluded_universe and not invalid_rows and not duplicates:
            # 全部因 universe 排除，仍为部分可用
            pass
        # 若没有任何行进入 rows，也视为 coverage_warning
        reason_codes.append("UNEXPLAINED_EMPTY")
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
            unexplained_empty=True,
            coverage_warning=True,
            legal_zero=False,
            excluded_universe_count=excluded_universe,
            invalid_row_count=invalid_rows,
            duplicate_code_count=duplicates,
            error_class="UNEXPLAINED_EMPTY",
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
    return {
        "schema_version": SCHEMA_VERSION,
        "source_id": _SOURCE_ID,
        "endpoint": _ENDPOINT,
        "requested_trade_date": requested_trade_date,
        "observed_at": _now_utc_iso(),
        "status": status,
        "reason_codes": _normalize_reason_codes(reason_codes),
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
        "http_status": status_code,
        "error_class": "NONE",
        "excluded_universe_count": excluded_universe,
        "invalid_row_count": invalid_rows,
        "duplicate_code_count": duplicates,
    }


def _evaluate_trade_date_match(
    payload: dict, data_obj: dict, requested_trade_date: str
) -> tuple[Optional[bool], bool]:
    """返回 ``(trade_date_match, mismatch)``。

    - ``mismatch=True`` 表示发现可解析但不相等（调用方应转 unavailable）
    - 否则返回 ``True/False/None`` 其中之一
    """
    em_date = requested_trade_date.replace("-", "")
    candidates = [
        payload.get("trade_date"), payload.get("date"), payload.get("qdate"),
        data_obj.get("trade_date"), data_obj.get("date"), data_obj.get("qdate"),
    ]
    for v in candidates:
        if v is None:
            continue
        parsed: Optional[str] = None
        if isinstance(v, str):
            s = v.strip()
            if _STRICT_DATE_RE.match(s):
                parsed = s
            else:
                m = _EIGHT_DIGIT_RE.match(s)
                if m:
                    parsed = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        elif isinstance(v, (int,)) and not isinstance(v, bool):
            s = str(v)
            m = _EIGHT_DIGIT_RE.match(s)
            if m:
                parsed = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        if parsed is None:
            continue
        if parsed == requested_trade_date or parsed == em_date:
            return True, False
        return False, True
    return None, False


def _normalize_rows(pool: list) -> tuple[list[dict], int, int, int]:
    """返回 ``(rows, excluded_universe_count, invalid_row_count, duplicate_code_count)``。"""
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
        # universe 过滤：必须先确认严格六位数字
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
