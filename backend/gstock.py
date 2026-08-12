"""美股 / 港股数据层 —— 移植自 global-stock-data（美港股全栈工具包）。

只并入「域内(东财)」子集：全球指数 + 美港股行情 + 关键财务指标。
用途＝A 股「看隔夜外围脸色」+ 个股页支持美港股代码。

工程要点：
- 东财调用全部复用 `astock.em_get`（直连优先、避开用户 Clash 代理挂国内站）+
  `astock.eastmoney_datacenter`（datacenter 三表/指标已封装）。
- push2 stock/get 直连偶发掉连 → **push2 优先、失败降级 push2delay**（延时行情，研究场景足够），
  latch 到可用主机整进程复用（同成交额榜的做法）。
- 指数分时按能力分层：腾讯负责恒生/恒科/上证，Yahoo 负责美股/日经/KOSPI；
  全部零 key，单源失败即隔离并显式报告缺失，不跨源拼接。
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import astock

_UA_H = {"User-Agent": astock.UA}
_GS_HOSTS = ("push2.eastmoney.com", "push2delay.eastmoney.com")
_gs_host = [0]  # 当前可用主机下标；首次 push2 掉连后 latch 到 push2delay

# 全球指数（东财 push2 secid）—— A 股看隔夜外围脸色的核心几个，均已实测。
_INDICES = (
    {"key": "dji", "name": "道琼斯", "secid": "100.DJIA", "region": "美股", "yahoo_symbol": "%5EDJI"},
    {"key": "spx", "name": "标普500", "secid": "100.SPX", "region": "美股", "yahoo_symbol": "%5EGSPC"},
    {"key": "ndx", "name": "纳斯达克", "secid": "100.NDX", "region": "美股", "yahoo_symbol": "%5EIXIC"},
    {"key": "hsi", "name": "恒生指数", "secid": "100.HSI", "region": "港股", "tencent_code": "hkHSI"},
    {"key": "hstech", "name": "恒生科技", "secid": "124.HSTECH", "region": "港股", "tencent_code": "hkHSTECH"},
    {"key": "nikkei", "name": "日经225", "secid": "100.N225", "region": "日本", "yahoo_symbol": "%5EN225"},
    {"key": "kospi", "name": "韩国KOSPI", "secid": "100.KS11", "region": "韩国", "yahoo_symbol": "%5EKS11"},
    {"key": "shcomp", "name": "上证指数", "secid": "1.000001", "region": "A股", "tencent_code": "sh000001"},
)

# 搜索返回的 MktNum → (secucode 后缀, 市场名)
_MKT = {105: (".O", "NASDAQ"), 106: (".N", "NYSE"), 107: (".O", "US"), 116: (".HK", "HK"),
        177: (".KS", "KR")}  # 177=韩股（Kospi/Kosdaq，含三星/SK海力士等半导体龙头）；东财仅行情、无 F10 财务

_QUOTE_FIELDS = "f43,f44,f45,f46,f48,f57,f58,f59,f60,f116,f170"


def _push2_stock_get(secid: str, fields: str) -> dict | None:
    """东财 push2 stock/get：push2 优先、失败降级 push2delay；latch 可用主机。空数据返回 None。"""
    params = {"secid": secid, "fields": fields}
    for i in range(_gs_host[0], len(_GS_HOSTS)):
        try:
            r = astock.em_get(f"https://{_GS_HOSTS[i]}/api/qt/stock/get",
                              params=params, headers=_UA_H, timeout=10)
            d = r.json().get("data")
        except Exception:
            continue
        if d:
            _gs_host[0] = i
            return d
    return None


def _price(d: dict, key: str):
    """f43 等价格字段：除以 10^f59 还原。'-' / None → None。"""
    v = d.get(key)
    if not isinstance(v, (int, float)):
        return None
    dec = d.get("f59")
    if not isinstance(dec, int):  # 注意：不能用 `or 2`——韩元等 f59=0 会被误判成 2，价格被多除 100 倍
        dec = 2
    return round(v / (10 ** dec), dec)


def _quote_from(d: dict) -> dict:
    chg = d.get("f170")
    return {
        "code": d.get("f57"), "name": d.get("f58"),
        "price": _price(d, "f43"), "open": _price(d, "f46"),
        "high": _price(d, "f44"), "low": _price(d, "f45"),
        "prev_close": _price(d, "f60"),
        "amount": d.get("f48") if isinstance(d.get("f48"), (int, float)) else None,
        "mcap": d.get("f116") if isinstance(d.get("f116"), (int, float)) and d.get("f116") else None,
        "change_pct": round(chg / 100, 2) if isinstance(chg, (int, float)) else None,
    }


def global_indices() -> list[dict]:
    """全球与亚洲核心指数快照。源无的档跳过。"""
    out = []
    for idx in _INDICES:
        d = _push2_stock_get(idx["secid"], "f43,f57,f58,f59,f60,f169,f170")
        if not d:
            continue
        chg = d.get("f170")
        out.append({
            "key": idx["key"], "name": idx["name"], "region": idx["region"],
            "price": _price(d, "f43"),
            "change_amt": _price(d, "f169"),
            "change_pct": round(chg / 100, 2) if isinstance(chg, (int, float)) else None,
        })
    return out


_TREND_RUN_BUDGET_SECONDS = 30.0
_TREND_PROVIDER_TIMEOUT_SECONDS = 8.0


def _trend_series(idx: dict, timeout: float) -> dict | None:
    """读取单指数最近交易日分时，并归一化为相对昨收涨跌幅。"""
    if idx.get("tencent_code"):
        return _tencent_trend_series(idx, timeout)
    if idx.get("yahoo_symbol"):
        return _yahoo_trend_series(idx, timeout)
    return None


def _tencent_trend_series(idx: dict, timeout: float = _TREND_PROVIDER_TIMEOUT_SECONDS) -> dict | None:
    """腾讯指数分钟线（恒生、恒生科技、上证）；该源优先且不依赖东财。"""
    code = idx["tencent_code"]
    url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={code}"
    request = Request(url, headers={"User-Agent": astock.UA, "Referer": "https://gu.qq.com/"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - 固定 HTTPS 主机
        payload = json.loads(response.read())
    node = ((payload.get("data") or {}).get(code) or {})
    data = node.get("data") or {}
    quote = ((node.get("qt") or {}).get(code) or [])
    date_raw = str(data.get("date") or "")
    try:
        trade_date = datetime.strptime(date_raw, "%Y%m%d").strftime("%Y-%m-%d")
        previous_close = float(quote[4])
    except (IndexError, TypeError, ValueError):
        return None
    if not math.isfinite(previous_close) or previous_close <= 0:
        return None

    deduped: dict[str, dict] = {}
    for raw in data.get("data") or []:
        if not isinstance(raw, str):
            continue
        parts = raw.split()
        if len(parts) < 2 or len(parts[0]) != 4:
            continue
        timestamp = f"{trade_date} {parts[0][:2]}:{parts[0][2:]}"
        try:
            datetime.strptime(timestamp, "%Y-%m-%d %H:%M")
            price = float(parts[1])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(price) or price <= 0:
            continue
        deduped[timestamp] = {
            "time": timestamp,
            "price": price,
            "change_pct": round((price / previous_close - 1) * 100, 4),
        }
    points = [deduped[key] for key in sorted(deduped)]
    if len(points) < 2:
        return None
    last = points[-1]
    return {
        "key": idx["key"],
        "name": idx["name"],
        "region": idx["region"],
        "source": "tencent",
        "trade_date": trade_date,
        "source_timezone": "Asia/Shanghai",
        "display_timezone": "Asia/Shanghai",
        "previous_close": previous_close,
        "price": last["price"],
        "change_amt": round(last["price"] - previous_close, 4),
        "change_pct": last["change_pct"],
        "points": points,
    }


def _yahoo_trend_series(idx: dict, timeout: float = _TREND_PROVIDER_TIMEOUT_SECONDS) -> dict | None:
    """Yahoo 5 分钟 chart（美股、日本、韩国）；使用 UTC epoch 后统一转北京时间。"""
    symbol = idx["yahoo_symbol"]
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=5m&range=1d"
    request = Request(url, headers={"User-Agent": astock.UA})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - 固定 HTTPS 主机
        payload = json.loads(response.read())
    results = ((payload.get("chart") or {}).get("result") or [])
    if not results:
        return None
    result = results[0]
    meta = result.get("meta") or {}
    previous_close = meta.get("previousClose")
    timestamps = result.get("timestamp") or []
    quote_rows = (((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
    if not isinstance(previous_close, (int, float)) or not math.isfinite(previous_close) or previous_close <= 0:
        return None

    beijing = timezone(timedelta(hours=8))
    deduped: dict[str, dict] = {}
    for timestamp_raw, price_raw in zip(timestamps, quote_rows):
        if not isinstance(timestamp_raw, (int, float)) or not isinstance(price_raw, (int, float)):
            continue
        price = float(price_raw)
        if not math.isfinite(price) or price <= 0:
            continue
        timestamp = datetime.fromtimestamp(timestamp_raw, timezone.utc).astimezone(beijing).strftime("%Y-%m-%d %H:%M")
        deduped[timestamp] = {
            "time": timestamp,
            "price": price,
            "change_pct": round((price / previous_close - 1) * 100, 4),
        }
    points = [deduped[key] for key in sorted(deduped)]
    if len(points) < 2:
        return None
    last = points[-1]
    source_timezone = str(meta.get("exchangeTimezoneName") or "UTC")
    try:
        source_zone = ZoneInfo(source_timezone)
    except Exception:  # noqa: BLE001 - 非法上游时区必须失败关闭
        return None
    last_epoch = max(value for value in timestamps if isinstance(value, (int, float)))
    trade_date = datetime.fromtimestamp(last_epoch, timezone.utc).astimezone(source_zone).strftime("%Y-%m-%d")
    return {
        "key": idx["key"],
        "name": idx["name"],
        "region": idx["region"],
        "source": "yahoo",
        "trade_date": trade_date,
        "source_timezone": source_timezone,
        "display_timezone": "Asia/Shanghai",
        "previous_close": previous_close,
        "price": last["price"],
        "change_amt": round(last["price"] - previous_close, 4),
        "change_pct": last["change_pct"],
        "points": points,
    }


def global_index_trends() -> dict:
    """八个核心指数的最近交易日分时对比；30 秒总预算，单源失败隔离。"""
    series = []
    missing_keys = []
    deadline = time.monotonic() + _TREND_RUN_BUDGET_SECONDS
    for position, idx in enumerate(_INDICES):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            missing_keys.extend(item["key"] for item in _INDICES[position:])
            break
        try:
            trend = _trend_series(idx, min(_TREND_PROVIDER_TIMEOUT_SECONDS, max(1.0, remaining)))
        except Exception:  # noqa: BLE001 - 单指数失败不得拖垮其余序列
            trend = None
        if trend is None:
            missing_keys.append(idx["key"])
        else:
            series.append(trend)
    return {
        "series": series,
        "missing_keys": missing_keys,
        "budget_seconds": _TREND_RUN_BUDGET_SECONDS,
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def _search(q: str) -> dict | None:
    """东财搜索一次：市场过滤 + **精确代码匹配优先**，退而取第一条。

    只按 MktNum 过滤挑不出正股——东财搜 AAPL 会混入 AAPL22(票据)/AAPB(2倍做多ETF)，
    搜 BABA 混入 05593(窝轮)，且 SecurityType 分不开(正股与 ETF 同为 Type7、正股港股与窝轮同为 Type6)。
    正股的 Code 恰好等于查询词，故精确匹配 Code==q 最稳；无精确匹配(名称查询)才退回第一条。
    """
    url = "https://searchapi.eastmoney.com/api/suggest/get"
    params = {"input": q, "type": 14,
              "token": "D43BF722C8E33BDC906FB84D85E326E8", "count": 10}
    try:
        r = astock.em_get(url, params=params, headers=_UA_H, timeout=10)
        rows = (r.json().get("QuotationCodeTable") or {}).get("Data") or []
    except Exception:
        return None
    matches = []
    for s in rows:
        try:
            mkt = int(s.get("MktNum"))
        except (TypeError, ValueError):
            continue
        if mkt in _MKT:
            matches.append((mkt, s))
    if not matches:
        return None
    mkt, s = next(((m, x) for m, x in matches if str(x.get("Code", "")).upper() == q), matches[0])
    suffix, market = _MKT[mkt]
    code = s.get("Code", "")
    return {"code": code, "name": s.get("Name", ""), "secid_prefix": mkt,
            "secucode": f"{code}{suffix}", "market": market}


def resolve_symbol(query: str) -> dict | None:
    """代码/名称 → {code, name, secid_prefix, secucode, market}。认美股/港股/韩股。
    数字型港股短代码（如 `700`）补零到 5 位再试一次（东财按 `00700` 收）。
    韩股用国际后缀 `.KS`/`.KQ`/`.KR`（如三星 `005930.KS`）——韩股代码与 A 股同为 6 位数字，
    需显式后缀区分，否则前端会按 A 股处理、后端也搜不到韩股。"""
    q = query.strip().upper()
    if not q:
        return None
    for suf in (".KS", ".KQ", ".KR"):  # 剥掉韩股后缀，按裸代码搜（东财 177=韩股）
        if q.endswith(suf):
            q = q[: -len(suf)]
            break
    hit = _search(q)
    if hit is None and q.isdigit() and len(q) < 5:
        hit = _search(q.zfill(5))
    return hit


def _key_metrics(secucode: str) -> dict | None:
    """东财 GMAININDICATOR 最新一期关键财务指标（美股/港股中文字段）。"""
    market = "HK" if secucode.endswith(".HK") else "US"
    rows = astock.eastmoney_datacenter(
        f"RPT_{market}F10_FN_GMAININDICATOR",
        filter_str=f'(SECUCODE="{secucode}")',
        page_size=1, sort_columns="REPORT_DATE", sort_types="-1")
    if not rows:
        return None
    m = rows[0]
    return {
        "report_date": str(m.get("REPORT_DATE") or "")[:10],
        "revenue": m.get("OPERATE_INCOME"),
        "revenue_yoy": m.get("OPERATE_INCOME_YOY"),
        "net_profit": m.get("PARENT_HOLDER_NETPROFIT") or m.get("HOLDER_PROFIT"),
        "eps": m.get("BASIC_EPS"),
        "roe": m.get("ROE_AVG"),
        "gross_margin": m.get("GROSS_PROFIT_RATIO"),
        "net_margin": m.get("NET_PROFIT_RATIO"),
        "debt_ratio": m.get("DEBT_ASSET_RATIO"),
    }


def us_hk_stock(query: str) -> dict:
    """个股聚合（美/港）：解析代码 → 行情 + 关键财务指标。查不到返回 {}。"""
    info = resolve_symbol(query)
    if not info:
        return {}
    d = _push2_stock_get(f"{info['secid_prefix']}.{info['code']}", _QUOTE_FIELDS)
    quote = _quote_from(d or {})  # 行情临时取不到也返回完整 null 形状，契合 GlobalQuote 类型
    return {
        "code": info["code"],
        "name": info["name"] or quote.get("name") or info["code"],
        "market": info["market"],
        "quote": quote,
        "metrics": _key_metrics(info["secucode"]) if info["market"] != "KR" else None,  # 韩股东财无 F10 财务
    }
