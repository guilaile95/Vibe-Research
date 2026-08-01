"""北向资金（沪股通 / 深股通）权威日统计。

数据源：HKEX 官方 Stock Connect Daily Statistics
    https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_YYYYMMDDe.js

真实性边界（硬约束，勿"优化"掉）：
- 当前 HKEX payload 可能包含 Buy/Sell Turnover 列；本版本未验证这些列在历史日期、
  单位和口径上的一致性，因此不据此生成 net_buy 字段 → net_* 字段固定 None。
- 成交额绝不能命名或解释为「净流入 / 净买入」。
- DQB 实测恒为占位值 999,999,999，不是真实额度余额 → 置 None 并记 limitation。
- 东财 NET_DEAL_AMT / FUND_INFLOW / BUY_AMT / SELL_AMT / NET_BUY_AMT 自 2024-08-19 起
  对北向全部为 null，push2 kamt 北向腿恒为 0 → 禁止用作净买入来源。
- trade_date 只能取自上游 payload 的 date 字段，绝不用本地当前日期伪装。
- 缺失一律 None，禁止用 0 代表缺失。
- 上游原文 / URL / traceback 绝不透传给调用方，错误只用固定安全分类字符串。
- 腿级成功至少要求 total_turnover_mn 为有限非负数；否则该腿视为解析失败。
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

import astock
import data_health_service as dhs

SCHEMA_VERSION = "northbound-capital-flow-v0.1"
SOURCE_NAME = "HKEX Stock Connect Daily Statistics"
SOURCE_TIER = "authoritative"
CURRENCY = "CNY"
AMOUNT_UNIT = "million"

_BASE_URL = "https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_{ymd}e.js"
_REFERER = "https://www.hkex.com.hk/eng/csm/DailyStat/"
_TIMEOUT = 15
_MAX_BYTES = 2 * 1024 * 1024
_LOOKBACK_DAYS = 7

_DQB_PLACEHOLDER = 999_999_999.0
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_NB_SSE = "SSE Northbound"
_NB_SZSE = "SZSE Northbound"

ERR_UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
ERR_UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
ERR_PARSE_FAILED = "PARSE_FAILED"

_NULL_PLACEHOLDERS = frozenset({"", "-", "--", "n/a", "na", "n.a.", "null", "none"})

_NET_BUY_DETAIL = (
    "当前 HKEX payload 可能包含 Buy/Sell Turnover 列；"
    "本版本未验证这些列在历史日期、单位和口径上的一致性，因此不据此生成 net_buy 字段。"
)

LIMITATION_NET_BUY = {
    "field": "data.northbound.net_buy_mn",
    "reason_code": "NOT_PUBLISHED_BY_SOURCE",
    "detail": _NET_BUY_DETAIL,
}
LIMITATION_ACTIVE_STOCKS_NET_BUY = {
    "field": "data.active_stocks[].net_buy_yuan",
    "reason_code": "NOT_PUBLISHED_BY_SOURCE",
    "detail": _NET_BUY_DETAIL,
}


class NorthboundParseError(Exception):
    """解析失败。消息只允许固定安全分类字符串，不得含上游原文。"""


def _to_float(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str):
        return None
    s = raw.strip().replace(",", "").replace("\u00a0", "")
    if s.lower() in _NULL_PLACEHOLDERS:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _nonneg_finite(raw: Any) -> float | None:
    """Parse a value and accept only finite, non-negative numbers."""
    v = _to_float(raw)
    if v is None:
        return None
    if not math.isfinite(v) or v < 0:
        return None
    return v


def _to_int(raw: Any) -> int | None:
    v = _to_float(raw)
    if v is None:
        return None
    try:
        return int(round(v))
    except (ValueError, OverflowError):
        return None


def _nonneg_finite_int(raw: Any) -> int | None:
    v = _nonneg_finite(raw)
    if v is None:
        return None
    try:
        return int(round(v))
    except (ValueError, OverflowError):
        return None


def _is_valid_trade_date(value: str | None) -> bool:
    if not value or not _DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _fetch_daily_stat_js(date_str: str) -> str | None:
    """抓某个自然日的 daily stat JS 文本。非 200 / 类型不符 → None。"""
    ymd = date_str.replace("-", "")
    url = _BASE_URL.format(ymd=ymd)
    headers = {
        "User-Agent": getattr(astock, "UA", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"),
        "Referer": _REFERER,
        "Accept": "*/*",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=_TIMEOUT, stream=True)
        try:
            if resp.status_code != 200:
                return None
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if ctype and ("javascript" not in ctype and "text" not in ctype):
                return None
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > _MAX_BYTES:
                    chunks.append(chunk[: max(0, _MAX_BYTES - (total - len(chunk)))])
                    break
                chunks.append(chunk)
            body = b"".join(chunks)
        finally:
            resp.close()
        if not body:
            return None
        return body.decode("utf-8", errors="replace")
    except requests.RequestException:
        return None


def parse_daily_stat_js(text: str) -> list[dict]:
    """从裸 JS 语句 `tabData = [ ... ];` 中切出右侧 JSON 并解析。"""
    if not isinstance(text, str) or not text.strip():
        raise NorthboundParseError(ERR_PARSE_FAILED)
    idx = text.find("tabData")
    if idx < 0:
        raise NorthboundParseError(ERR_PARSE_FAILED)
    eq = text.find("=", idx + len("tabData"))
    if eq < 0:
        raise NorthboundParseError(ERR_PARSE_FAILED)
    rhs = text[eq + 1 :].strip()
    start = rhs.find("[")
    if start < 0:
        raise NorthboundParseError(ERR_PARSE_FAILED)
    end = rhs.rfind("]")
    if end <= start:
        raise NorthboundParseError(ERR_PARSE_FAILED)
    payload = rhs[start : end + 1]
    try:
        parsed = json.loads(payload)
    except Exception:
        raise NorthboundParseError(ERR_PARSE_FAILED) from None
    if not isinstance(parsed, list):
        raise NorthboundParseError(ERR_PARSE_FAILED)
    return [item for item in parsed if isinstance(item, dict)]


def _market_entry(tab_data: list[dict], market_label: str) -> dict | None:
    for item in tab_data:
        if isinstance(item, dict) and item.get("market") == market_label:
            return item
    return None


def _tables(entry: dict) -> tuple[dict | None, dict | None]:
    trading: dict | None = None
    top10: dict | None = None
    content = entry.get("content")
    if not isinstance(content, list):
        return None, None
    for block in content:
        if not isinstance(block, dict):
            continue
        table = block.get("table")
        if not isinstance(table, dict):
            continue
        classname = str(table.get("classname") or "").strip()
        if classname == "tradingTable":
            trading = table
            continue
        if classname == "top10Table":
            top10 = table
            continue
        style = block.get("style")
        if style in (1, "1") and trading is None:
            trading = table
        elif style in (2, "2") and top10 is None:
            top10 = table
    return trading, top10


def _normalize_schema_labels(schema: Any) -> list[str]:
    """Normalize HKEX table schema into ordered string labels.

    Compatible shapes:
    - flat: ["Total Turnover", ...]
    - one-level nested: [["Total Turnover", ...]]
    - dict columns: [{"ref": "..."}] / label / name
    """
    if not isinstance(schema, list):
        return []
    cols = schema
    # Unwrap exactly one nesting level when schema is a single list cell.
    if len(cols) == 1 and isinstance(cols[0], list):
        cols = cols[0]

    labels: list[str] = []
    for col in cols:
        if isinstance(col, dict):
            labels.append(str(col.get("ref") or col.get("label") or col.get("name") or "").strip())
        elif isinstance(col, list):
            # Unknown deeper nesting: keep positional slot with empty label.
            labels.append("")
        elif col is None:
            labels.append("")
        else:
            labels.append(str(col).strip())
    return labels


def _row_cells(row: Any) -> list[Any]:
    """Normalize one table row's cells.

    Compatible shapes:
    - per-cell wrap: {"td": [["159,927.12"], ["1,234"], ...]}
    - whole-row wrap: {"td": [["159,927.12", "1,234", ...]]}
    """
    if not isinstance(row, dict):
        return []
    td = row.get("td")
    if not isinstance(td, list):
        return []

    # Whole-row wrapper: single cell that is itself the full row list.
    if len(td) == 1 and isinstance(td[0], list):
        return list(td[0])

    cells: list[Any] = []
    for cell in td:
        if isinstance(cell, list):
            cells.append(cell[0] if cell else None)
        else:
            cells.append(cell)
    return cells


def _schema_labels(table: dict) -> list[str]:
    return _normalize_schema_labels(table.get("schema"))


def _trading_values(table: dict | None) -> dict[str, Any]:
    """Map tradingTable labels to values.

    Compatible shapes:
    - one data row, N cells (legacy flat / whole-row nested)
    - N data rows, each contributing one value (observed live HKEX shape)
    """
    out: dict[str, Any] = {}
    if not isinstance(table, dict):
        return out
    labels = _schema_labels(table)
    rows = table.get("tr")
    if not isinstance(rows, list) or not rows or not labels:
        return out

    # Single row → align cells[i] to labels[i]
    if len(rows) == 1:
        cells = _row_cells(rows[0])
        for i, label in enumerate(labels):
            if not label:
                continue
            out[label] = cells[i] if i < len(cells) else None
        return out

    # Multi-row → each row's first cell maps to the same-index label.
    for i, label in enumerate(labels):
        if not label:
            continue
        if i >= len(rows):
            out[label] = None
            continue
        cells = _row_cells(rows[i])
        out[label] = cells[0] if cells else None
    return out


def _leg_metrics(entry: dict | None) -> dict[str, Any] | None:
    """Parse one northbound leg. Requires finite non-negative total_turnover_mn."""
    if not isinstance(entry, dict):
        return None
    trading, _ = _tables(entry)
    if not isinstance(trading, dict):
        return None
    vals = _trading_values(trading)
    if not vals:
        return None

    total_turnover = _nonneg_finite(vals.get("Total Turnover"))
    if total_turnover is None:
        # Core field missing/invalid → leg parse failure (do not emit empty "success").
        return None

    dqb_raw = _nonneg_finite(vals.get("DQB"))
    dqb_is_placeholder = dqb_raw is not None and abs(dqb_raw - _DQB_PLACEHOLDER) < 0.5

    return {
        "total_turnover_mn": total_turnover,
        "trade_count": _nonneg_finite_int(vals.get("Total Trade Count")),
        "etf_turnover_mn": _nonneg_finite(vals.get("ETF Turnover")),
        "daily_quota_balance_mn": None if dqb_is_placeholder else dqb_raw,
        "dqb_is_placeholder": dqb_is_placeholder,
    }


def _leg_optional_complete(leg: dict[str, Any] | None) -> bool:
    if leg is None:
        return False
    return leg.get("trade_count") is not None and leg.get("etf_turnover_mn") is not None


def _field_unavailable(field: str) -> dict:
    return {
        "field": field,
        "reason_code": "FIELD_UNAVAILABLE",
        "detail": "该字段在当前 HKEX 日统计中缺失或无法解析为有效非负有限值。",
    }


def _append_optional_field_limitations(
    limitations: list[dict],
    *,
    leg: dict[str, Any] | None,
    leg_key: str,
) -> None:
    if leg is None:
        return
    if leg.get("trade_count") is None:
        limitations.append(_field_unavailable(f"data.{leg_key}.trade_count"))
    if leg.get("etf_turnover_mn") is None:
        limitations.append(_field_unavailable(f"data.{leg_key}.etf_turnover_mn"))


def _leg_active_stocks(entry: dict | None, market: str) -> list[dict]:
    if not isinstance(entry, dict):
        return []
    _, top10 = _tables(entry)
    if not isinstance(top10, dict):
        return []
    labels = _schema_labels(top10)
    rows = top10.get("tr")
    if not isinstance(rows, list):
        return []
    out: list[dict] = []
    for row in rows:
        cells = _row_cells(row)
        if not cells:
            continue
        rec = {labels[i] if i < len(labels) else f"col{i}": cells[i] for i in range(len(cells))}
        rank = _nonneg_finite_int(rec.get("Rank"))
        code = rec.get("Stock Code")
        name = rec.get("Stock Name")
        out.append({
            "market": market,
            "rank": rank,
            "code": "" if code is None else str(code).strip(),
            "name": "" if name is None else str(name).strip(),
            "total_turnover_yuan": _nonneg_finite(rec.get("Total Turnover")),
            "net_buy_yuan": None,
        })
    return out


def resolve_status(sse_ok: bool, szse_ok: bool) -> str:
    if sse_ok and szse_ok:
        return "normal"
    if sse_ok or szse_ok:
        return "partial"
    return "unavailable"


def _empty_leg(market: str) -> dict:
    return {
        "market": market,
        "total_turnover_mn": None,
        "trade_count": None,
        "etf_turnover_mn": None,
        "daily_quota_balance_mn": None,
        "net_buy_mn": None,
    }


def _empty_data() -> dict:
    return {
        "northbound": {
            "total_turnover_mn": None,
            "trade_count": None,
            "etf_turnover_mn": None,
            "net_buy_mn": None,
        },
        "shanghai_connect": _empty_leg("SSE"),
        "shenzhen_connect": _empty_leg("SZSE"),
        "active_stocks": [],
    }


def _envelope(
    *,
    trade_date: str | None,
    fetched_at: str,
    status: str,
    is_stale: bool,
    warnings: list[str],
    limitations: list[dict],
    data: dict,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "source_tier": SOURCE_TIER,
        "trade_date": trade_date,
        "fetched_at": fetched_at,
        "status": status,
        "is_stale": is_stale,
        "currency": CURRENCY,
        "amount_unit": AMOUNT_UNIT,
        "warnings": warnings,
        "limitations": limitations,
        "data": data,
    }


def unavailable_envelope(
    *,
    fetched_at: str | None = None,
    reason_code: str = ERR_UPSTREAM_UNAVAILABLE,
    warnings: list[str] | None = None,
) -> dict:
    return _envelope(
        trade_date=None,
        fetched_at=fetched_at or _now_iso(),
        status="unavailable",
        is_stale=False,
        warnings=list(warnings) if warnings else [f"上游不可用：{reason_code}"],
        limitations=[dict(LIMITATION_NET_BUY)],
        data=_empty_data(),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stale_flag(trade_date: str | None, now_utc: datetime) -> bool:
    if not trade_date:
        return False
    return bool(dhs.is_stale_cn_trade_date(trade_date, None, now_utc))


def _payload_date(entry: dict | None) -> str:
    if not isinstance(entry, dict):
        return ""
    raw = str(entry.get("date") or "").strip()[:10]
    return raw if _is_valid_trade_date(raw) else ""


def build_envelope(
    tab_data: list[dict],
    *,
    trade_date: str | None = None,  # noqa: ARG001 — kept for call-site compatibility; never fills trade_date
    fetched_at: str | None = None,
) -> dict:
    fetched_at_str = fetched_at or _now_iso()
    sse_entry = _market_entry(tab_data or [], _NB_SSE)
    szse_entry = _market_entry(tab_data or [], _NB_SZSE)

    sse = _leg_metrics(sse_entry)
    szse = _leg_metrics(szse_entry)

    sse_date = _payload_date(sse_entry)
    szse_date = _payload_date(szse_entry)

    sse_ok = sse is not None
    szse_ok = szse is not None
    status = resolve_status(sse_ok, szse_ok)

    warnings: list[str] = []
    limitations: list[dict] = [dict(LIMITATION_NET_BUY)]

    if status == "unavailable":
        return _envelope(
            trade_date=None,
            fetched_at=fetched_at_str,
            status="unavailable",
            is_stale=False,
            warnings=["沪股通与深股通北向日统计均解析失败"],
            limitations=limitations,
            data=_empty_data(),
        )

    dates_aligned = bool(sse_ok and szse_ok and sse_date and szse_date and sse_date == szse_date)

    resolved_date: str | None = None
    if dates_aligned:
        resolved_date = sse_date
    elif sse_ok and not szse_ok and sse_date:
        resolved_date = sse_date
        warnings.append("深股通北向日统计缺失或解析失败，北向合计不可用")
    elif szse_ok and not sse_ok and szse_date:
        resolved_date = szse_date
        warnings.append("沪股通北向日统计缺失或解析失败，北向合计不可用")
    elif sse_ok and szse_ok:
        # Both cores present but dates missing/mismatched — fail-closed partial.
        status = "partial"
        if sse_date and szse_date and sse_date != szse_date:
            warnings.append("沪股通与深股通 trade_date 不一致，合计字段不做相加")
        else:
            warnings.append("沪股通与深股通 trade_date 缺失或非法，合计字段不做相加")
    else:
        # Single-leg without valid payload date.
        if sse_ok and not sse_date:
            warnings.append("沪股通 trade_date 缺失或非法")
        if szse_ok and not szse_date:
            warnings.append("深股通 trade_date 缺失或非法")
        if not szse_ok:
            warnings.append("深股通北向日统计缺失或解析失败，北向合计不可用")
        if not sse_ok:
            warnings.append("沪股通北向日统计缺失或解析失败，北向合计不可用")

    # Optional-field completeness: missing trade_count / etf_turnover cannot be normal.
    if sse_ok:
        _append_optional_field_limitations(limitations, leg=sse, leg_key="shanghai_connect")
    if szse_ok:
        _append_optional_field_limitations(limitations, leg=szse, leg_key="shenzhen_connect")

    optionals_complete = (
        (not sse_ok or _leg_optional_complete(sse))
        and (not szse_ok or _leg_optional_complete(szse))
    )
    if status == "normal" and (not dates_aligned or not optionals_complete):
        status = "partial"

    def _leg_out(leg: dict | None, market: str) -> dict:
        if leg is None:
            return _empty_leg(market)
        return {
            "market": market,
            "total_turnover_mn": leg["total_turnover_mn"],
            "trade_count": leg["trade_count"],
            "etf_turnover_mn": leg["etf_turnover_mn"],
            "daily_quota_balance_mn": leg["daily_quota_balance_mn"],
            "net_buy_mn": None,
        }

    def _sum(key: str):
        if not dates_aligned:
            return None
        a = sse[key] if sse else None
        b = szse[key] if szse else None
        if a is None or b is None:
            return None
        return a + b

    total_sum = _sum("total_turnover_mn")
    etf_sum = _sum("etf_turnover_mn")
    count_sum = _sum("trade_count")

    active_stocks = _leg_active_stocks(sse_entry, "SSE") + _leg_active_stocks(szse_entry, "SZSE")

    if sse and sse["dqb_is_placeholder"]:
        limitations.append({
            "field": "data.shanghai_connect.daily_quota_balance_mn",
            "reason_code": "PLACEHOLDER_VALUE",
            "detail": "HKEX 发布的 DQB 为固定占位值 999,999,999，不是真实每日额度余额，已置为 null。",
        })
    if szse and szse["dqb_is_placeholder"]:
        limitations.append({
            "field": "data.shenzhen_connect.daily_quota_balance_mn",
            "reason_code": "PLACEHOLDER_VALUE",
            "detail": "HKEX 发布的 DQB 为固定占位值 999,999,999，不是真实每日额度余额，已置为 null。",
        })
    if active_stocks:
        limitations.append(dict(LIMITATION_ACTIVE_STOCKS_NET_BUY))

    # Guard: never emit normal with null northbound total_turnover.
    if status == "normal" and total_sum is None:
        status = "partial"

    try:
        now_utc = datetime.fromisoformat(fetched_at_str)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        now_utc = datetime.now(timezone.utc)

    return _envelope(
        trade_date=resolved_date,
        fetched_at=fetched_at_str,
        status=status,
        is_stale=_stale_flag(resolved_date, now_utc),
        warnings=warnings,
        limitations=limitations,
        data={
            "northbound": {
                "total_turnover_mn": total_sum,
                "trade_count": count_sum,
                "etf_turnover_mn": etf_sum,
                "net_buy_mn": None,
            },
            "shanghai_connect": _leg_out(sse, "SSE"),
            "shenzhen_connect": _leg_out(szse, "SZSE"),
            "active_stocks": active_stocks,
        },
    )


def _candidate_dates(today: date) -> list[str]:
    return [(today - timedelta(days=i)).isoformat() for i in range(_LOOKBACK_DAYS)]


def get_northbound_capital_flow() -> dict:
    fetched_at = _now_iso()
    today = datetime.now(dhs.BEIJING).date()
    text: str | None = None
    for date_str in _candidate_dates(today):
        try:
            text = _fetch_daily_stat_js(date_str)
        except Exception:  # noqa: BLE001
            text = None
            continue
        if text:
            break

    if not text:
        return unavailable_envelope(
            fetched_at=fetched_at,
            reason_code=ERR_UPSTREAM_UNAVAILABLE,
            warnings=[f"上游不可用：{ERR_UPSTREAM_UNAVAILABLE}（回溯 {_LOOKBACK_DAYS} 个自然日均无可用文件）"],
        )

    try:
        tab_data = parse_daily_stat_js(text)
    except NorthboundParseError:
        return unavailable_envelope(
            fetched_at=fetched_at,
            reason_code=ERR_PARSE_FAILED,
            warnings=[f"上游不可用：{ERR_PARSE_FAILED}"],
        )
    except Exception:  # noqa: BLE001
        return unavailable_envelope(
            fetched_at=fetched_at,
            reason_code=ERR_PARSE_FAILED,
            warnings=[f"上游不可用：{ERR_PARSE_FAILED}"],
        )

    try:
        return build_envelope(tab_data, trade_date=None, fetched_at=fetched_at)
    except Exception:  # noqa: BLE001
        return unavailable_envelope(
            fetched_at=fetched_at,
            reason_code=ERR_PARSE_FAILED,
            warnings=[f"上游不可用：{ERR_PARSE_FAILED}"],
        )


# ---------------------------------------------------------------------------
# 北向成交历史（成交额 / 成交笔数 / ETF 成交额）—— 不含净买入
# ---------------------------------------------------------------------------

HISTORY_SCHEMA_VERSION = "northbound-history-v0.1"
HISTORY_ALLOWED_DAYS = frozenset({10, 20, 30})
HISTORY_DAYS_ERROR = "days 仅支持 10、20、30"

LIMITATION_HISTORY_NET_BUY = {
    "field": "series[].net_buy_mn",
    "reason_code": "UNVERIFIED_SOURCE_SEMANTICS",
    "detail": (
        "HKEX payload 可能包含 Buy/Sell Turnover，但本版本未验证其历史单位与口径一致性，"
        "因此北向成交历史接口不提供净买入字段。"
    ),
}
LIMITATION_HISTORY_SOURCE_UNAVAILABLE = {
    "field": "series",
    "reason_code": "SOURCE_UNAVAILABLE",
    "detail": "北向成交历史生成暂不可用，请稍后重试。",
}
LIMITATION_HISTORY_PARTIAL_SOURCE_FAILURE = {
    "field": "series",
    "reason_code": "PARTIAL_SOURCE_FAILURE",
    "detail": "扫描历史期间有部分日期抓取或解析失败，已返回其余可用交易日。",
}


class NorthboundHistoryDaysError(ValueError):
    """Invalid history days parameter (safe fixed message only)."""


def validate_history_days(days: Any) -> int:
    """Validate days for the history endpoint. Raises NorthboundHistoryDaysError."""
    if isinstance(days, bool) or not isinstance(days, int):
        raise NorthboundHistoryDaysError(HISTORY_DAYS_ERROR)
    if days not in HISTORY_ALLOWED_DAYS:
        raise NorthboundHistoryDaysError(HISTORY_DAYS_ERROR)
    return days


def _is_valid_history_envelope(data: Any, requested_days: int) -> bool:
    """Minimal fail-closed shape check for history envelopes returned to the route."""
    if not isinstance(data, dict):
        return False
    if data.get("schema_version") != HISTORY_SCHEMA_VERSION:
        return False
    status = data.get("status")
    if status not in {"normal", "partial", "unavailable"}:
        return False
    if data.get("requested_days") != requested_days:
        return False
    series = data.get("series")
    limitations = data.get("limitations")
    if not isinstance(series, list) or not isinstance(limitations, list):
        return False
    returned = data.get("returned_points")
    if not isinstance(returned, int) or isinstance(returned, bool) or returned < 0:
        return False
    if returned != len(series):
        return False
    if status == "unavailable" and series:
        return False
    if status == "normal" and returned != requested_days:
        return False
    if status == "partial" and not series:
        return False
    return True


def _history_point_from_envelope(env: dict) -> dict | None:
    """Extract one northbound turnover history point from a daily envelope.

    Requires a real payload trade_date and finite non-negative northbound total.
    Does not mutate the input envelope. Never invents net_buy fields.
    """
    if not isinstance(env, dict):
        return None
    trade_date = env.get("trade_date")
    if not isinstance(trade_date, str) or not _is_valid_trade_date(trade_date):
        return None
    data = env.get("data")
    if not isinstance(data, dict):
        return None
    nb = data.get("northbound")
    if not isinstance(nb, dict):
        return None
    total = _nonneg_finite(nb.get("total_turnover_mn"))
    if total is None:
        return None
    trade_count = _nonneg_finite_int(nb.get("trade_count"))
    etf = _nonneg_finite(nb.get("etf_turnover_mn"))
    return {
        "trade_date": trade_date,
        "total_turnover_mn": total,
        "trade_count": trade_count,
        "etf_turnover_mn": etf,
    }


def _unavailable_history_envelope(
    *,
    requested_days: int,
    fetched_at: str | None = None,
    limitations: list[dict] | None = None,
) -> dict:
    lims = [dict(LIMITATION_HISTORY_NET_BUY)]
    if limitations:
        for item in limitations:
            if isinstance(item, dict):
                lims.append(dict(item))
    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "source_tier": SOURCE_TIER,
        "status": "unavailable",
        "fetched_at": fetched_at or _now_iso(),
        "requested_days": requested_days,
        "returned_points": 0,
        "limitations": lims,
        "series": [],
    }


def get_northbound_history(days: int, *, today: date | None = None) -> dict:
    """Fetch northbound turnover history (not net-buy history).

    ``today`` is for deterministic unit tests only; never expose as HTTP param.
    """
    try:
        requested_days = validate_history_days(days)
    except NorthboundHistoryDaysError:
        # Callers (HTTP) should validate first; keep fail-closed if misused internally.
        raise

    fetched_at = _now_iso()
    anchor = today if isinstance(today, date) else datetime.now(dhs.BEIJING).date()
    max_calendar_days = requested_days * 2

    points_newest_first: list[dict] = []
    seen_dates: set[str] = set()
    calendar_scanned = 0
    had_scan_issue = False  # parse/unavailable/fetch failures (weekends excluded)

    for offset in range(max_calendar_days):
        calendar_scanned += 1
        day = anchor - timedelta(days=offset)

        # Weekends: skip without external request.
        if day.weekday() >= 5:
            continue

        date_str = day.isoformat()
        try:
            text = _fetch_daily_stat_js(date_str)
        except Exception:  # noqa: BLE001
            had_scan_issue = True
            continue
        if not text:
            # 404 / empty / non-200 — holiday or missing file; continue.
            continue

        try:
            tab_data = parse_daily_stat_js(text)
            env = build_envelope(tab_data, trade_date=None, fetched_at=fetched_at)
        except Exception:  # noqa: BLE001
            had_scan_issue = True
            continue

        if not isinstance(env, dict) or env.get("status") == "unavailable":
            had_scan_issue = True
            continue

        point = _history_point_from_envelope(env)
        if point is None:
            had_scan_issue = True
            continue

        td = point["trade_date"]
        if td in seen_dates:
            continue
        seen_dates.add(td)
        points_newest_first.append(point)

        if len(points_newest_first) >= requested_days:
            break

    # Keep newest requested_days points, return ascending by trade_date.
    selected = points_newest_first[:requested_days]
    series = sorted(selected, key=lambda p: p["trade_date"])

    limitations: list[dict] = [dict(LIMITATION_HISTORY_NET_BUY)]
    missing_trade_count = any(p.get("trade_count") is None for p in series)
    missing_etf = any(p.get("etf_turnover_mn") is None for p in series)
    if missing_trade_count:
        limitations.append({
            "field": "series[].trade_count",
            "reason_code": "FIELD_UNAVAILABLE",
            "detail": "至少一个历史点的成交笔数缺失或无法解析为有效非负整数。",
        })
    if missing_etf:
        limitations.append({
            "field": "series[].etf_turnover_mn",
            "reason_code": "FIELD_UNAVAILABLE",
            "detail": "至少一个历史点的 ETF 成交额缺失或无法解析为有效非负有限值。",
        })

    hit_scan_cap = (
        calendar_scanned >= max_calendar_days
        and len(series) < requested_days
    )
    if hit_scan_cap:
        limitations.append({
            "field": "series",
            "reason_code": "INSUFFICIENT_HISTORY_POINTS",
            "detail": (
                f"达到历史扫描上限，仅返回 {len(series)}/{requested_days} 个有效交易日。"
            ),
        })

    # Real scan faults only (not weekends / fetch None). Add once when any points remain.
    if had_scan_issue and series:
        limitations.append(dict(LIMITATION_HISTORY_PARTIAL_SOURCE_FAILURE))

    if not series:
        return _unavailable_history_envelope(
            requested_days=requested_days,
            fetched_at=fetched_at,
            limitations=[lim for lim in limitations if lim.get("reason_code") != "UNVERIFIED_SOURCE_SEMANTICS"],
        )

    complete = (
        len(series) == requested_days
        and not missing_trade_count
        and not missing_etf
    )
    # Weekends / ordinary missing files (fetch None) do not force partial.
    # Real parse/build/semantic/fetch exceptions force partial even when points are full.
    status = "normal" if complete and not had_scan_issue else "partial"

    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "source_tier": SOURCE_TIER,
        "status": status,
        "fetched_at": fetched_at,
        "requested_days": requested_days,
        "returned_points": len(series),
        "limitations": limitations,
        "series": series,
    }
