"""北向资金（沪股通 / 深股通）权威日统计。

数据源：HKEX 官方 Stock Connect Daily Statistics
    https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_YYYYMMDDe.js

真实性边界（硬约束，勿"优化"掉）：
- HKEX 北向 tradingTable 只发布 Total Turnover / Total Trade Count / DQB / ETF Turnover，
  没有 Buy/Sell 拆分，因此「净买入」在权威源里不存在也无法推导 → net_* 字段固定 None。
- 成交额绝不能命名或解释为「净流入 / 净买入」。
- DQB 实测恒为占位值 999,999,999，不是真实额度余额 → 置 None 并记 limitation。
- 东财 NET_DEAL_AMT / FUND_INFLOW / BUY_AMT / SELL_AMT / NET_BUY_AMT 自 2024-08-19 起
  对北向全部为 null，push2 kamt 北向腿恒为 0 → 禁止用作净买入来源。
- trade_date 只能取自上游 payload 的 date 字段，绝不用本地当前日期伪装。
- 缺失一律 None，禁止用 0 代表缺失。
- 上游原文 / URL / traceback 绝不透传给调用方，错误只用固定安全分类字符串。
"""

from __future__ import annotations

import json
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

_NB_SSE = "SSE Northbound"
_NB_SZSE = "SZSE Northbound"

ERR_UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
ERR_UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
ERR_PARSE_FAILED = "PARSE_FAILED"

_NULL_PLACEHOLDERS = frozenset({"", "-", "--", "n/a", "na", "n.a.", "null", "none"})

LIMITATION_NET_BUY = {
    "field": "data.northbound.net_buy_mn",
    "reason_code": "NOT_PUBLISHED_BY_SOURCE",
    "detail": "HKEX 北向日统计仅发布成交额，未发布买入/卖出拆分，净买入无法计算。",
}
LIMITATION_ACTIVE_STOCKS_NET_BUY = {
    "field": "data.active_stocks[].net_buy_yuan",
    "reason_code": "NOT_PUBLISHED_BY_SOURCE",
    "detail": "HKEX 十大成交股仅发布成交额，未发布买入/卖出拆分，净买入无法计算。",
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


def _to_int(raw: Any) -> int | None:
    v = _to_float(raw)
    if v is None:
        return None
    try:
        return int(round(v))
    except (ValueError, OverflowError):
        return None


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
    rhs = text[eq + 1:].strip()
    start = rhs.find("[")
    if start < 0:
        raise NorthboundParseError(ERR_PARSE_FAILED)
    end = rhs.rfind("]")
    if end <= start:
        raise NorthboundParseError(ERR_PARSE_FAILED)
    payload = rhs[start:end + 1]
    try:
        parsed = json.loads(payload)
    except Exception as exc:
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


def _row_cells(row: Any) -> list[Any]:
    if not isinstance(row, dict):
        return []
    td = row.get("td")
    if not isinstance(td, list):
        return []
    cells: list[Any] = []
    for cell in td:
        if isinstance(cell, list):
            cells.append(cell[0] if cell else None)
        else:
            cells.append(cell)
    return cells


def _schema_labels(table: dict) -> list[str]:
    schema = table.get("schema")
    labels: list[str] = []
    if isinstance(schema, list):
        for col in schema:
            if isinstance(col, dict):
                labels.append(str(col.get("ref") or col.get("label") or col.get("name") or "").strip())
            else:
                labels.append(str(col).strip())
    return labels


def _trading_values(table: dict | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not isinstance(table, dict):
        return out
    labels = _schema_labels(table)
    rows = table.get("tr")
    if not isinstance(rows, list) or not rows:
        return out
    cells = _row_cells(rows[0])
    for i, label in enumerate(labels):
        out[label] = cells[i] if i < len(cells) else None
    return out


def _leg_metrics(entry: dict | None) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    trading, _ = _tables(entry)
    if not isinstance(trading, dict):
        return None
    vals = _trading_values(trading)
    if not vals:
        return None
    dqb_raw = _to_float(vals.get("DQB"))
    dqb_is_placeholder = dqb_raw is not None and abs(dqb_raw - _DQB_PLACEHOLDER) < 0.5
    return {
        "total_turnover_mn": _to_float(vals.get("Total Turnover")),
        "trade_count": _to_int(vals.get("Total Trade Count")),
        "etf_turnover_mn": _to_float(vals.get("ETF Turnover")),
        "daily_quota_balance_mn": None if dqb_is_placeholder else dqb_raw,
        "dqb_is_placeholder": dqb_is_placeholder,
    }


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
        rank = _to_int(rec.get("Rank"))
        code = rec.get("Stock Code")
        name = rec.get("Stock Name")
        out.append({
            "market": market,
            "rank": rank,
            "code": "" if code is None else str(code).strip(),
            "name": "" if name is None else str(name).strip(),
            "total_turnover_yuan": _to_float(rec.get("Total Turnover")),
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


def build_envelope(
    tab_data: list[dict],
    *,
    trade_date: str | None = None,
    fetched_at: str | None = None,
) -> dict:
    fetched_at_str = fetched_at or _now_iso()
    sse_entry = _market_entry(tab_data or [], _NB_SSE)
    szse_entry = _market_entry(tab_data or [], _NB_SZSE)

    sse = _leg_metrics(sse_entry)
    szse = _leg_metrics(szse_entry)

    sse_date = str(sse_entry.get("date") or "").strip()[:10] if isinstance(sse_entry, dict) else ""
    szse_date = str(szse_entry.get("date") or "").strip()[:10] if isinstance(szse_entry, dict) else ""

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

    resolved_date: str | None = None
    if sse_ok and szse_ok:
        if sse_date and sse_date == szse_date:
            resolved_date = sse_date
        else:
            resolved_date = sse_date or szse_date or trade_date
            warnings.append("沪股通与深股通 trade_date 不一致，合计字段不做相加")
    elif sse_ok:
        resolved_date = sse_date or trade_date
        warnings.append("深股通北向日统计缺失或解析失败，北向合计不可用")
    else:
        resolved_date = szse_date or trade_date
        warnings.append("沪股通北向日统计缺失或解析失败，北向合计不可用")

    dates_aligned = bool(sse_ok and szse_ok and sse_date and sse_date == szse_date)
    if sse_ok and szse_ok and not dates_aligned:
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
