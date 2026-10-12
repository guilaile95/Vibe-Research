"""美股 / 港股数据层 —— 移植自 global-stock-data（美港股全栈工具包）。

只并入「域内(东财)」子集：全球指数 + 美港股行情 + 关键财务指标。
用途＝A 股「看隔夜外围脸色」+ 个股页支持美港股代码。

工程要点：
- 东财调用全部复用 `astock.em_get`（直连优先、避开用户 Clash 代理挂国内站）+
  `astock.eastmoney_datacenter`（datacenter 三表/指标已封装）。
- push2 stock/get 直连偶发掉连 → **push2 优先、失败降级 push2delay**（延时行情，研究场景足够），
  优先复用上次成功主机；其失败时仍尝试另一台既有主机。
- Yahoo / SEC 等国外源不并入（需科学上网、且非必要）。
"""

from __future__ import annotations

import re

import astock

_UA_H = {"User-Agent": astock.UA}
_GS_HOSTS = ("push2.eastmoney.com", "push2delay.eastmoney.com")
_gs_host = [0]  # 上次成功主机；失败时仍可回到另一台既有主机

# 全球指数（东财 push2 secid）—— A 股看隔夜外围脸色的核心几个，均已实测。
_INDICES = (
    {"key": "dji", "name": "道琼斯", "secid": "100.DJIA", "region": "美股"},
    {"key": "spx", "name": "标普500", "secid": "100.SPX", "region": "美股"},
    {"key": "ndx", "name": "纳斯达克", "secid": "100.NDX", "region": "美股"},
    {"key": "hsi", "name": "恒生指数", "secid": "100.HSI", "region": "港股"},
    {"key": "hstech", "name": "恒生科技", "secid": "124.HSTECH", "region": "港股"},
)

# 搜索返回的 MktNum → (secucode 后缀, 市场名)
_MKT = {105: (".O", "NASDAQ"), 106: (".N", "NYSE"), 107: (".O", "US"), 116: (".HK", "HK"),
        177: (".KS", "KR")}  # 177=韩股（Kospi/Kosdaq，含三星/SK海力士等半导体龙头）；东财仅行情、无 F10 财务

_QUOTE_FIELDS = "f43,f44,f45,f46,f48,f57,f58,f59,f60,f116,f170"


def _push2_stock_get(secid: str, fields: str) -> dict | None:
    """东财 stock/get：优先上次成功主机，失败尝试另一台。空数据返回 None。"""
    params = {"secid": secid, "fields": fields}
    preferred = _gs_host[0]
    for i in (preferred, *(index for index in range(len(_GS_HOSTS)) if index != preferred)):
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
    """全球指数快照（道指 / 标普500 / 纳斯达克 / 恒生 / 恒生科技）。源无的档跳过。"""
    out = []
    for idx in _INDICES:
        d = _push2_stock_get(idx["secid"], "f43,f57,f58,f59,f60,f170")
        if not d:
            continue
        chg = d.get("f170")
        out.append({
            "key": idx["key"], "name": idx["name"], "region": idx["region"],
            "price": _price(d, "f43"),
            "change_pct": round(chg / 100, 2) if isinstance(chg, (int, float)) else None,
        })
    return out


class SearchUnavailable(RuntimeError):
    """证券搜索接口不可用（网络 / 风控 / 返回体变形）。

    ⚠️ 与「查无此代码」严格区分：前者是基础设施问题、重试可能就好，后者是用户输错了。
    压成同一个 None 会让用户对着"未找到对应美股/港股/韩股代码"完全无从下手（upstream #26）。
    """


# 主端点 + 备用端点。单一端点被风控/变更就让整块功能瘫痪，代价太大。
_SEARCH_ENDPOINTS = (
    "https://searchapi.eastmoney.com/api/suggest/get",
    "https://searchadapter.eastmoney.com/api/suggest/get",
)


class SearchAmbiguous(RuntimeError):
    """Several distinct provider identities match; never choose by result order."""


SEARCH_UNAVAILABLE_MESSAGE = "证券搜索接口暂时不可用，请稍后重试；这与「查无此代码」不同。"
SEARCH_AMBIGUOUS_MESSAGE = "证券标识存在歧义，请核对并输入准确代码及适用的市场后缀。"


def _search_rows(data: list) -> list[tuple[int, dict]]:
    """Validate identity fields before trusting even an exact-looking candidate."""
    matches = []
    for row in data:
        if not isinstance(row, dict):
            raise ValueError("invalid search row")
        raw_market = row.get("MktNum")
        if type(raw_market) is int:
            market = raw_market
        elif isinstance(raw_market, str) and re.fullmatch(r"[0-9]+", raw_market):
            market = int(raw_market)
        else:
            raise ValueError("invalid search market")
        if market not in _MKT:
            continue
        code, name = row.get("Code"), row.get("Name", "")
        pattern = r"[0-9]{5}" if market == 116 else r"[0-9]{6}" if market == 177 else r"[A-Z][A-Z0-9.-]{0,15}"
        if not isinstance(code, str) or not re.fullmatch(pattern, code) or not isinstance(name, str):
            raise ValueError("invalid search identity")
        matches.append((market, row))
    return matches


def _search(q: str, *, market: int | None = None, code_alias: str | None = None) -> dict | None:
    """Exact code first, then unique exact name; suggestions never select a security.

    Only documented HK zero-padding is an alias. Different (MktNum, Code) pairs
    remain distinct, including US provider markets 105 and 107 with .O suffixes.
    """
    params = {"input": q, "type": 14,
              "token": "D43BF722C8E33BDC906FB84D85E326E8", "count": 10}
    matches = None
    for url in _SEARCH_ENDPOINTS:
        try:
            response = astock.em_get(url, params=params, headers=_UA_H, timeout=10)
            if getattr(response, "status_code", 200) >= 400:
                continue
            payload = response.json()
            table = payload.get("QuotationCodeTable") if isinstance(payload, dict) else None
            data = table.get("Data") if isinstance(table, dict) else None
            if not isinstance(data, list):
                continue
            matches = _search_rows(data)
        except Exception:  # network, JSON or malformed identity: try existing backup
            continue
        break
    if matches is None:
        # Public API and AI callers expose exception text; never include provider
        # URLs, response content, credentials or transport exception details.
        raise SearchUnavailable(SEARCH_UNAVAILABLE_MESSAGE)
    candidates = [(m, row) for m, row in matches if market is None or m == market]
    codes = {q, code_alias} if code_alias else {q}
    exact = [(m, row) for m, row in candidates if row["Code"] in codes]
    if not exact:
        # Numeric code intent must not resolve through a coincidentally equal name.
        exact = [] if q.isdigit() else [(m, row) for m, row in candidates if row.get("Name", "").strip().upper() == q]
    identities = {(m, row["Code"]): (m, row) for m, row in exact}
    if not identities:
        return None
    if len(identities) > 1:
        raise SearchAmbiguous(SEARCH_AMBIGUOUS_MESSAGE)
    mkt, row = next(iter(identities.values()))
    suffix, label = _MKT[mkt]
    code = row["Code"]
    return {"code": code, "name": row.get("Name", ""), "secid_prefix": mkt,
            "secucode": f"{code}{suffix}", "market": label}


def resolve_symbol(query: str) -> dict | None:
    """Resolve an exact code/name without silently changing security or market.

    Short numeric codes are HK (zero-padded to five digits). Bare six-digit
    codes belong to the A-share entry point, not this global resolver. Explicit
    .KS/.KQ/.KR expresses KR intent; the existing provider only exposes market
    177, not a verifiable distinction between Korean exchanges.
    """
    q = query.strip().upper()
    if not q:
        return None
    for suffix in (".KS", ".KQ", ".KR"):
        if q.endswith(suffix):
            code = q[:-len(suffix)]
            return _search(code, market=177) if re.fullmatch(r"[0-9]{6}", code) else None
    if q.isdigit():
        if not re.fullmatch(r"[0-9]{1,5}", q):
            return None
        padded = q.zfill(5)
        hit = _search(q, market=116, code_alias=padded)
        return _search(padded, market=116) if hit is None and padded != q else hit
    return _search(q)


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
_HK_CF_ITEMS = {
    "003999": "经营活动现金流净额",
    "005999": "投资活动现金流净额",
    "007999": "筹资活动现金流净额",
    "006999": "汇率变动前现金净额",
    "011997": "汇率变动等其他影响",
    "010999": "现金及等价物净增加",
    "011001": "期初现金及等价物",
    "011999": "期末现金及等价物",
}
_HK_CF_ORDER = ("003999", "005999", "007999", "006999", "011997", "010999", "011001", "011999")


def hk_cashflow(query: str, periods: int = 8) -> dict:
    """港股现金流量表（东财 datacenter RPT_HKSK_FN_CASHFLOW，与已接入 GMAININDICATOR 同为东财域内源）。

    按 REPORT_DATE 分组还原每期汇总（经营 / 投资 / 筹资 / 净增加 / 期初期末），返回最近 `periods` 期。
    金额为原生币种（见 `currency`，港股多为人民币或港元），季度为 YTD 累计、附同比。
    非港股（美/韩股，其现金流走 F10/SK 或无）或查不到 → 返回 {}。
    """
    info = resolve_symbol(query)
    if not info or not info["secucode"].endswith(".HK"):
        return {}
    # ⚠️ 该端点是**按科目逐行**返回的，一期就有几十行（实测腾讯 00700 最多 52 行/期、
    # 工行 01398 38 行/期）。只按 SECUCODE 取 300 行，最新 8 期根本装不下——
    # 最旧的那期会被截断成残缺科目，而且不报错。所以在**服务端**就按需要的科目码过滤：
    # 实测同样 300 行，覆盖期数从 13 期升到 39 期，请求量反而更小。
    item_filter = "(STD_ITEM_CODE in (" + ",".join(f'"{c}"' for c in _HK_CF_ORDER) + "))"
    rows = astock.eastmoney_datacenter(
        "RPT_HKSK_FN_CASHFLOW",
        filter_str=f'(SECUCODE="{info["secucode"]}"){item_filter}',
        page_size=300, sort_columns="REPORT_DATE", sort_types="-1")
    if not rows:
        return {}
    by_period: dict[str, dict] = {}
    for r in rows:
        rd = str(r.get("REPORT_DATE") or "")[:10]
        code = str(r.get("STD_ITEM_CODE") or "")
        if not rd or code not in _HK_CF_ITEMS:
            continue
        p = by_period.setdefault(rd, {
            "report_date": rd, "report": r.get("REPORT"),
            "currency": r.get("CURRENCY"), "account_standard": r.get("ACCOUNT_STANDARD"),
            "items": {},
        })
        amt, yoy = r.get("AMOUNT"), r.get("YOY_RATIO")
        p["items"][_HK_CF_ITEMS[code]] = {
            "amount": amt if isinstance(amt, (int, float)) else None,
            "yoy": yoy if isinstance(yoy, (int, float)) else None,
        }
    if not by_period:
        return {}
    periods_out = sorted(by_period.values(), key=lambda x: x["report_date"], reverse=True)[:periods]
    return {
        "code": info["code"], "name": info["name"], "market": "HK",
        "currency": periods_out[0].get("currency"),
        "item_order": [_HK_CF_ITEMS[c] for c in _HK_CF_ORDER],
        "periods": periods_out,
    }
