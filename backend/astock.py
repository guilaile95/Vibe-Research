"""A股全栈数据层 —— 移植自 a-stock-data 工具包（五层数据源，自包含）。

分级依赖：
  - 行情（腾讯）        : 仅需标准库 urllib —— 永远可用
  - 研报（东财）+ PDF   : 仅需 requests —— 轻量必装
  - 一致预期/新闻/公告  : akshare（惰性导入，缺失时优雅报错）
  - K线/财务/F10        : mootdx（惰性导入，缺失时优雅报错）

按用户传入的代码返回行情 / 研报 / 资金等数据。
"""

from __future__ import annotations

import math
import os
import random
import re
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def get_prefix(code: str) -> str:
    """6 位代码 → 交易所前缀。5 开头是沪市基金/ETF（51/56/58 等），深市基金 15/16 开头走默认 sz。"""
    if code.startswith(("6", "9", "5")):
        return "sh"
    if code.startswith("8"):
        return "bj"
    return "sz"


class DependencyMissing(RuntimeError):
    """惰性依赖未安装时抛出，前端据此提示 pip install。"""


# ---------------------------------------------------------------------------
# Layer 1 · 行情（腾讯财经，仅标准库，不封 IP）
# ---------------------------------------------------------------------------

def _fetch_gtimg(prefixed_codes: list[str]) -> str:
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed_codes)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("gbk")


def _parse_gtimg(data: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]

        def num(i: int) -> float:
            try:
                return float(vals[i]) if vals[i] else 0.0
            except (ValueError, IndexError):
                return 0.0

        result[code] = {
            "name": vals[1],
            "price": num(3),
            "last_close": num(4),
            "open": num(5),
            "change_amt": num(31),
            "change_pct": num(32),
            "high": num(33),
            "low": num(34),
            "amount_wan": num(37),
            "turnover_pct": num(38),
            "pe_ttm": num(39),
            "amplitude_pct": num(43),
            "mcap_yi": num(44),
            "float_mcap_yi": num(45),
            "pb": num(46),
            "limit_up": num(47),
            "limit_down": num(48),
            "vol_ratio": num(49),
            "pe_static": num(52),
        }
    return result


def tencent_quote(codes: list[str]) -> dict[str, dict]:
    """批量个股实时行情：现价 / 涨跌 / PE / PB / 市值 / 换手 / 涨跌停。"""
    prefixed = [f"{get_prefix(c)}{c}" for c in codes]
    return _parse_gtimg(_fetch_gtimg(prefixed))


# A股大盘指数（前缀规则与个股不同，固定带前缀代码）
A_INDICES = ["sh000001", "sz399001", "sz399006", "sh000300"]


def index_quote() -> list[dict]:
    """A股大盘指数实时行情（上证/深证成指/创业板指/沪深300）。"""
    parsed = _parse_gtimg(_fetch_gtimg(A_INDICES))
    out = []
    for full in A_INDICES:
        q = parsed.get(full[2:])
        if q:
            out.append({"name": q["name"], "price": q["price"], "change_pct": q["change_pct"], "change_amt": q["change_amt"]})
    return out


# ---------------------------------------------------------------------------
# Layer 2 · 研报（东财 reportapi，仅 requests）
# ---------------------------------------------------------------------------

_REPORT_API = "https://reportapi.eastmoney.com/report/list"
_PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"


def _report_session():
    import requests  # 轻依赖，随后端一起装

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
    return s


def eastmoney_reports(code: str, max_pages: int = 3) -> list[dict]:
    """按个股代码拉研报列表（qType=0）。"""
    session = _report_session()
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": "2000-01-01", "endTime": "2030-01-01",
            "pageNo": str(page), "fields": "", "qType": "0",
            "orgCode": "", "code": code, "rcode": "",
            "p": str(page), "pageNum": str(page), "pageNumber": str(page),
        }
        r = session.get(_REPORT_API, params=params, timeout=30)
        d = r.json()
        rows = d.get("data") or []
        if not rows:
            break
        out.extend(rows)
        if page >= (d.get("TotalPage", 1) or 1):
            break
        time.sleep(0.3)
    return out


def eastmoney_industry_reports(keywords: list[str] | None = None, days: int = 90, max_pages: int = 3) -> list[dict]:
    """按行业拉研报（qType=1）——适合产业链 / 主题级检索。keywords 在标题上过滤。"""
    from datetime import date, timedelta

    session = _report_session()
    end = date.today()
    begin = end - timedelta(days=days)
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": begin.isoformat(), "endTime": end.isoformat(),
            "pageNo": str(page), "fields": "", "qType": "1",
            "orgCode": "", "code": "", "rcode": "",
        }
        r = session.get(_REPORT_API, params=params, timeout=30)
        rows = r.json().get("data") or []
        if not rows:
            break
        out.extend(rows)
        time.sleep(0.3)
    if keywords:
        out = [r for r in out if any(k in r.get("title", "") for k in keywords)]
    return out


def pdf_url(info_code: str) -> str:
    return _PDF_TPL.format(info_code=info_code)


# ---------------------------------------------------------------------------
# Layer 3/4/5 · akshare 惰性封装（一致预期 / 新闻 / 公告 / 基本面）
# ---------------------------------------------------------------------------

def _akshare():
    try:
        import akshare as ak
        return ak
    except ImportError as e:
        raise DependencyMissing("akshare 未安装：pip install akshare") from e


def profit_forecast(code: str) -> list[dict]:
    """机构一致预期 EPS（同花顺）。"""
    ak = _akshare()
    df = ak.stock_profit_forecast_ths(symbol=code, indicator="预测年报每股收益")
    return df.to_dict("records") if df is not None and not df.empty else []


def stock_news(code: str, limit: int = 20) -> list[dict]:
    """个股新闻（东财）。"""
    ak = _akshare()
    df = ak.stock_news_em(symbol=code)
    return df.head(limit).to_dict("records") if df is not None and not df.empty else []


def individual_info(code: str) -> dict:
    """个股基本面（东财）：行业 / 总股本 / 上市时间等。"""
    ak = _akshare()
    df = ak.stock_individual_info_em(symbol=code)
    if df is None or df.empty:
        return {}
    return {str(row["item"]): row["value"] for _, row in df.iterrows()}


def security_profile(code: str, *, strict: bool = False) -> dict:
    """单只 A 股代码、简称与行业（东财 stock/get，实时源失败后走延迟源）。"""
    if not (isinstance(code, str) and len(code) == 6 and code.isdigit()):
        raise ValueError("code must be a 6-digit A-share code")
    secid = f"{1 if code.startswith('6') else 0}.{code}"
    params = {"secid": secid, "fields": "f57,f58,f127"}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    last_error: Exception | None = None
    for host in _A_SHARE_CLIST_HOSTS:
        try:
            payload = em_get(
                f"https://{host}/api/qt/stock/get",
                params=params,
                headers=headers,
                timeout=15,
            ).json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                raise RuntimeError("security_profile response missing data")
            name = str(data.get("f58") or "").strip()
            if not name:
                raise RuntimeError("security_profile response missing name")
            return {
                "code": str(data.get("f57") or code).strip(),
                "name": name,
                "industry": str(data.get("f127") or "").strip(),
            }
        except Exception as exc:  # noqa: BLE001 - 有限主机降级，最终仍 fail closed
            last_error = exc
    if strict:
        raise RuntimeError("security_profile unavailable") from last_error
    return {}


def disclosure(code: str) -> list[dict]:
    """巨潮公告全文列表（akshare cninfo，本环境不稳，保留作备用）。"""
    ak = _akshare()
    market = "沪市" if code.startswith("6") else ("北交所" if code.startswith("8") else "深市")
    df = ak.stock_zh_a_disclosure_report_cninfo(symbol=code, market=market)
    return df.head(30).to_dict("records") if df is not None and not df.empty else []


def announcements(code: str, limit: int = 15) -> list[dict]:
    """个股近期公告（东财公开接口，仅 requests，稳定）。返回 日期/标题/类型/详情链接。

    与其他东财数据路径一致使用固定直连会话（trust_env=False）：系统代理
    （Clash 等）停机会把该请求掐断，公告能力不应受代理环境影响。
    """
    r = _em_session(True).get(
        "https://np-anotice-stock.eastmoney.com/api/security/ann",
        params={"sr": -1, "page_size": limit, "page_index": 1, "ann_type": "A",
                "client_source": "web", "stock_list": code, "f_node": 0, "s_node": 0},
        headers={"User-Agent": UA}, timeout=20,
    )
    lst = (r.json().get("data") or {}).get("list") or []
    out = []
    for a in lst:
        cols = [c.get("column_name") for c in (a.get("columns") or []) if c.get("column_name")]
        art = a.get("art_code", "")
        raw_date = a.get("notice_date", "") or ""
        # 保留 provider 原始时间戳（notice_at，北京时间语义）；date 仅为展示
        # 截断。下游 time 判定不得依赖 [:10] 截断丢失的时间。
        notice_at = raw_date if isinstance(raw_date, str) and len(raw_date) >= 10 else None
        out.append({
            "date": raw_date[:10] if isinstance(raw_date, str) else "",
            "notice_at": notice_at,
            "title": a.get("title", ""),
            "type": cols[0] if cols else "",
            "url": f"https://data.eastmoney.com/notices/detail/{code}/{art}.html" if art else "",
        })
    return out


# ---------------------------------------------------------------------------
# mootdx 惰性封装（K线 / 财务 / F10）
# ---------------------------------------------------------------------------

def _mootdx_client():
    try:
        from mootdx.quotes import Quotes
        return Quotes.factory(market="std")
    except ImportError as e:
        raise DependencyMissing("mootdx 未安装：pip install mootdx") from e


def kline(code: str, category: int = 4, offset: int = 60) -> list[dict]:
    """K线：category 4=日 5=周 6=月 11=60分钟。

    日线在配置 HiThink credential 时优先使用已资格认定的 direct API；
    未配置、身份不覆盖、传输失败或契约失败时保留既有 mootdx 路径。
    周/月/60 分钟不在本次 HiThink cutover 范围内。
    """
    if category == 4:
        try:
            import hithink_finance_client as hithink

            if hithink.is_configured():
                return hithink.fetch_daily_bars(code, offset)
        except hithink.HiThinkClientError:
            # A failed provider observation is never consumed.  Availability
            # falls back to the pre-existing route without changing the
            # Tushare Fact Lake or any formal investment authority.
            # Current BSE 920xxx codes cannot use mootdx 0.11.7 as fallback:
            # it misroutes them to Shanghai.  Fail closed instead.
            if hithink.is_current_bse_security(code):
                raise
        if hithink.is_current_bse_security(code):
            raise hithink.HiThinkNotConfiguredError(
                "HiThink is required for current BSE daily bars"
            )
    client = _mootdx_client()
    df = client.bars(symbol=code, category=category, offset=offset)
    return df.to_dict("records") if df is not None and not df.empty else []


def finance(code: str) -> dict:
    """季报财务快照（37 字段）。"""
    client = _mootdx_client()
    df = client.finance(symbol=code)
    if df is None or (hasattr(df, "empty") and df.empty):
        return {}
    return df.to_dict("records")[0] if hasattr(df, "to_dict") else dict(df)


# ---------------------------------------------------------------------------
# 估值计算
# ---------------------------------------------------------------------------

def calc_peg(pe: float, cagr: float) -> float:
    if cagr <= 0:
        return float("inf")
    return pe / (cagr * 100)


def pe_digestion(current_pe: float, cagr: float, target_pe: float = 30) -> float:
    if current_pe <= target_pe:
        return 0.0
    if cagr <= 0:
        return float("inf")
    return math.log(current_pe / target_pe) / math.log(1 + cagr)


def financials(code: str, *, include_health: bool = False) -> dict:
    """同花顺财务体检：最新摘要 + 同报告期现金流/资产负债事实。

    注：mootdx finance() 的营收/净利数值不可靠(实测放大数倍)，故财务摘要走此源。
    新版三表中的 ``report_date`` 实际是报告期末，不是公告日；公开契约因此
    始终把 ``report_date`` 保持为 ``None``，不提供历史 PIT 保证。
    三表 enrichment 仅供 StockData 产品面显式开启，避免拖慢既有批量消费者。
    """
    ak = _akshare()
    df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
    if df is None or df.empty:
        return {}
    summary_rows = df.to_dict("records")

    def present(value):
        if value in (False, "false", "", None):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value

    def summary(row: dict) -> dict:
        period_end = present(row.get("报告期"))
        return {
            "period": period_end,  # legacy consumer alias
            "period_end": period_end,
            "report_date": None,
            "revenue": present(row.get("营业总收入")),
            "revenue_yoy": present(row.get("营业总收入同比增长率")),
            "net_profit": present(row.get("净利润")),
            "net_profit_yoy": present(row.get("净利润同比增长率")),
            "deduct_net_profit": present(row.get("扣非净利润")),
            "deduct_net_profit_yoy": present(row.get("扣非净利润同比增长率")),
            "eps": present(row.get("基本每股收益")),
            "bvps": present(row.get("每股净资产")),
            "roe": present(row.get("净资产收益率")),
            "gross_margin": present(row.get("销售毛利率")),
            "net_margin": present(row.get("销售净利率")),
            "op_cf_ps": present(row.get("每股经营现金流")),
            "current_ratio": present(row.get("流动比率")),
            "quick_ratio": present(row.get("速动比率")),
            "debt_to_equity_ratio": present(row.get("产权比率")),
            "debt_ratio": present(row.get("资产负债率")),
        }

    history = [summary(row) for row in summary_rows[-5:]]
    if not include_health:
        return history[-1]
    warnings: list[str] = []

    def metric_rows(frame, wanted: set[str], source: str) -> dict[str, dict[str, float | None]]:
        if frame is None or frame.empty:
            warnings.append(f"{source}_unavailable")
            return {}
        result: dict[str, dict[str, float | None]] = {}
        for raw in frame.to_dict("records"):
            metric = raw.get("metric_name")
            if metric not in wanted:
                continue
            period_end = raw.get("report_date")
            if not isinstance(period_end, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", period_end):
                raise ValueError(f"{source} period_end contract drifted")
            bucket = result.setdefault(period_end, {})
            if metric in bucket:
                raise ValueError(f"{source} contains duplicate period metric")
            value = raw.get("value")
            if value in (False, "false", "", None):
                bucket[metric] = None
                continue
            try:
                parsed = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{source} metric is not numeric") from exc
            if not math.isfinite(parsed):
                raise ValueError(f"{source} metric is not finite")
            bucket[metric] = parsed
        return result

    tables: dict[str, dict[str, dict[str, float | None]]] = {}
    table_specs = (
        (
            "income",
            "stock_financial_benefit_new_ths",
            {"operating_income_total", "net_profit", "parent_holder_net_profit"},
        ),
        (
            "cashflow",
            "stock_financial_cash_new_ths",
            {"act_cash_flow_net", "pay_fixed_assets_etc_cash"},
        ),
        (
            "balance",
            "stock_financial_debt_new_ths",
            {"assets_total", "cash", "accounts_receivable", "total_debt", "holder_equity_total"},
        ),
    )
    for source, function_name, wanted in table_specs:
        try:
            frame = getattr(ak, function_name)(symbol=code, indicator="按报告期")
            tables[source] = metric_rows(frame, wanted, source)
        except Exception:  # one optional statement must not erase the reliable summary
            warnings.append(f"{source}_unavailable")
            tables[source] = {}

    def ratio(numerator: float | None, denominator: float | None) -> float | None:
        if numerator is None or denominator in (None, 0):
            return None
        result = numerator / denominator
        return result if math.isfinite(result) else None

    for item in history:
        period_end = item["period_end"]
        income = tables["income"].get(period_end, {})
        cashflow = tables["cashflow"].get(period_end, {})
        balance = tables["balance"].get(period_end, {})
        revenue = income.get("operating_income_total")
        net_profit = income.get("net_profit")
        operating_cash_flow = cashflow.get("act_cash_flow_net")
        capital_expenditure = cashflow.get("pay_fixed_assets_etc_cash")
        assets_total = balance.get("assets_total")
        cash = balance.get("cash")
        accounts_receivable = balance.get("accounts_receivable")
        total_debt = balance.get("total_debt")
        free_cash_flow = (
            operating_cash_flow - capital_expenditure
            if operating_cash_flow is not None and capital_expenditure is not None
            else None
        )
        item.update({
            "revenue_amount": revenue,
            "net_profit_amount": net_profit,
            "parent_holder_net_profit_amount": income.get("parent_holder_net_profit"),
            "operating_cash_flow": operating_cash_flow,
            "capital_expenditure": capital_expenditure,
            "free_cash_flow": free_cash_flow,
            "assets_total": assets_total,
            "cash": cash,
            "accounts_receivable": accounts_receivable,
            "total_debt": total_debt,
            "holder_equity_total": balance.get("holder_equity_total"),
            "cash_conversion_ratio": ratio(operating_cash_flow, net_profit),
            "free_cash_flow_margin": ratio(free_cash_flow, revenue),
            "accrual_ratio": ratio(
                net_profit - operating_cash_flow
                if net_profit is not None and operating_cash_flow is not None
                else None,
                assets_total,
            ),
            "receivables_pressure": ratio(accounts_receivable, revenue),
            "net_cash_ratio": ratio(
                cash - total_debt if cash is not None and total_debt is not None else None,
                assets_total,
            ),
        })

    latest = history[-1]
    required = (
        "revenue", "net_profit", "roe", "gross_margin", "net_margin",
        "operating_cash_flow", "capital_expenditure", "assets_total",
        "accounts_receivable", "total_debt", "cash",
    )
    missing_fields = [field for field in required if latest.get(field) is None]
    return {
        **latest,
        "history": list(reversed(history)),
        "data_quality": {
            "status": "partial" if warnings or missing_fields else "normal",
            "source": "tonghuashun_via_akshare",
            "fetch_mode": "snapshot",
            "report_basis": "cumulative_report_period",
            "point_in_time_supported": False,
            "publication_date_known": False,
            "missing_fields": missing_fields,
            "warnings": list(dict.fromkeys(warnings)),
        },
    }


def valuation_percentile(code: str, period: str = "近五年") -> dict:
    """历史估值分位（百度股市通）：PE-TTM / PB 的当前值 + 历史 20/50/80 分位带 + 所处分位。"""
    ak = _akshare()

    def _q(vals: list, p: float) -> float:
        if not vals:
            return 0.0
        idx = p * (len(vals) - 1)
        lo = int(idx)
        if lo + 1 >= len(vals):
            return vals[-1]
        frac = idx - lo
        return vals[lo] * (1 - frac) + vals[lo + 1] * frac

    metrics = {}
    for key, ind in (("pe_ttm", "市盈率(TTM)"), ("pb", "市净率")):
        try:
            df = ak.stock_zh_valuation_baidu(symbol=code, indicator=ind, period=period)
            raw = df.iloc[:, 1].dropna().astype(float).tolist()
            if not raw:
                continue
            cur = float(raw[-1])
            s = sorted(raw)
            below = sum(1 for x in s if x < cur)
            metrics[key] = {
                "current": round(cur, 2),
                "percentile": round(below / max(len(s) - 1, 1) * 100, 1),
                "min": round(s[0], 2), "max": round(s[-1], 2),
                "p20": round(_q(s, 0.2), 2), "p50": round(_q(s, 0.5), 2), "p80": round(_q(s, 0.8), 2),
                "n": len(s),
            }
        except Exception:
            continue
    return {"period": "近5年", "metrics": metrics}


def full_valuation(code: str) -> dict:
    """单票完整估值：腾讯行情 + 一致预期 EPS + 前向PE/PEG/消化年数。"""
    quotes = tencent_quote([code])
    q = quotes.get(code)
    if not q:
        raise ValueError(f"未取到 {code} 的行情")

    price = q["price"]
    out = {
        "name": q["name"], "code": code, "price": price,
        "mcap_yi": q["mcap_yi"], "pe_ttm": q["pe_ttm"], "pb": q["pb"],
        "eps_26e": None, "eps_27e": None, "pe_26e": None,
        "cagr_pct": None, "peg": None, "digest_years": None, "analyst_count": 0,
    }

    try:
        rows = profit_forecast(code)
    except DependencyMissing:
        out["forecast_note"] = "一致预期需安装 akshare"
        return out

    def _eps(row: dict):
        # 同花顺对覆盖不全的股票会缺「均值」或给 '-' 占位，硬取会让整只票的估值接口 502
        try:
            return float(str(row.get("均值", "")).replace(",", ""))
        except ValueError:
            return None

    eps_26 = eps_27 = None
    for row in rows:
        y = str(row.get("年度", ""))
        if "2026" in y:
            eps_26 = _eps(row)
            try:
                out["analyst_count"] = int(float(row.get("预测机构数") or 0))
            except (TypeError, ValueError):
                pass
        elif "2027" in y:
            eps_27 = _eps(row)

    out["eps_26e"], out["eps_27e"] = eps_26, eps_27
    if eps_26 and eps_26 > 0:
        pe_26e = price / eps_26
        out["pe_26e"] = round(pe_26e, 1)
        if eps_27:
            cagr = eps_27 / eps_26 - 1
            out["cagr_pct"] = round(cagr * 100, 0)
            peg = calc_peg(pe_26e, cagr)
            out["peg"] = round(peg, 2) if peg != float("inf") else None
            dig = pe_digestion(pe_26e, cagr)
            out["digest_years"] = round(dig, 1) if dig != float("inf") else None
    return out


# ===========================================================================
# Layer 3/4/10 · 资金面 / 筹码 / 信号（东财数据中心，移植自 a-stock-data v3.3）
# 按用户传入的代码返回：龙虎榜、融资融券、大宗、股东户数、分红、资金流、
# 解禁、板块归属、投资者问答；另有涨停池 / 全市场成交额榜供每日复盘使用。
# ===========================================================================

_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_EM_MIN_INTERVAL = 1.0          # 两次东财请求最小间隔（秒），内置防封节流
_em_last_call = [0.0]
_EM_SESSIONS: dict = {}         # {direct(bool): requests.Session}

# 东财固定直连：Windows 系统代理（Clash 等）常把 push2.eastmoney.com 的 CONNECT 掐断，
# 导致全 A 快照分页中途 ProxyError。数据层一律 trust_env=False，不读系统/环境代理。
# AI 层（国外模型）不受影响，仍走各自客户端代理。
# 模式标记仅供诊断/测试读取；em_get 始终使用 direct 会话。
_em_mode = ["direct"]

# 全 A 快照分页：单页瞬时网络错误有限重试（不跨页重跑）
_A_SHARE_PAGE_MAX_ATTEMPTS = 3
_A_SHARE_PAGE_RETRY_BACKOFF = (0.5, 1.0, 2.0)


def _em_session(direct: bool = True):
    """东财专用会话。默认/推荐 direct=True → ``trust_env=False``，忽略系统与环境代理。"""
    if direct in _EM_SESSIONS:
        return _EM_SESSIONS[direct]
    import requests

    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.trust_env = not direct  # 直连：不读 HTTP(S)_PROXY / Windows 系统代理
    # 应用层自管重试；urllib3 层关闭自动重试，避免与分页重试叠加
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        adapter = HTTPAdapter(max_retries=Retry(total=0))
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    except Exception:
        pass
    _EM_SESSIONS[direct] = s
    return s


def em_get(url: str, params: dict | None = None, headers: dict | None = None, timeout: int = 15):
    """东财统一请求入口：串行限流 + **固定直连**（trust_env=False）。

    不读取环境/系统代理，避免 Clash 等代理导致国内站 ProxyError。
    瞬时失败由调用方（如 a_share_snapshot 分页）做有限页级重试。
    """
    wait = _EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        _em_mode[0] = "direct"
        return _em_session(True).get(url, params=params, headers=headers, timeout=timeout)
    finally:
        _em_last_call[0] = time.time()


def _is_transient_network_error(exc: BaseException) -> bool:
    """判断是否为可重试的瞬时网络错误（不含 JSON/结构/业务解析错误）。"""
    # 按类型名兼容未 import 的异常类
    transient_names = {
        "ProxyError",
        "ConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
        "Timeout",
        "TimeoutError",
        "RemoteDisconnected",
        "ProtocolError",
        "ChunkedEncodingError",
        "SSLError",
        "NewConnectionError",
        "MaxRetryError",
    }
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if type(cur).__name__ in transient_names:
            return True
        # requests 常把底层包在 args 里
        for a in getattr(cur, "args", ()):
            if isinstance(a, BaseException) and type(a).__name__ in transient_names:
                return True
            if isinstance(a, str) and any(
                k in a for k in ("ProxyError", "RemoteDisconnected", "Connection reset", "timed out")
            ):
                return True
        cur = cur.__cause__ or cur.__context__  # type: ignore[assignment]
    return False


def _em_get_page_with_retries(
    url: str,
    *,
    params: dict | None,
    headers: dict | None,
    timeout: int = 15,
    max_attempts: int = _A_SHARE_PAGE_MAX_ATTEMPTS,
    backoff: tuple[float, ...] = _A_SHARE_PAGE_RETRY_BACKOFF,
):
    """单页请求：瞬时网络错误有限重试；解析/结构类错误不重试。"""
    last_err: BaseException | None = None
    attempts = max(1, int(max_attempts))
    for attempt in range(attempts):
        try:
            return em_get(url, params=params, headers=headers, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if not _is_transient_network_error(e):
                raise
            if attempt >= attempts - 1:
                break
            delay = backoff[attempt] if attempt < len(backoff) else backoff[-1]
            time.sleep(delay)
    assert last_err is not None
    raise last_err

# ---------------------------------------------------------------------------
# 打板层 · 涨停/炸板/跌停/昨涨停 原始池（东财 push2ex，走 em_get 限流）
# 原始池含个股 code/name，由 market.py 聚合为短线情绪指标，也可输出连板股清单。
# ---------------------------------------------------------------------------
_ZTB_UT = "7eea3edcaed734bea9cbfc24409ed989"


def em_zt_topic_pool(endpoint: str, date: str, sort: str = "fbt:asc") -> list[dict]:
    """东财涨停板行情中心原始池（push2ex）。
    endpoint: getTopicZTPool(涨停) / getTopicZBPool(炸板) / getTopicDTPool(跌停) / getYesterdayZTPool(昨涨停)
    date: YYYYMMDD 交易日。非交易日 / 参数错 → []。
    池内每项字段含 lbc(连板数) / zbc(炸板次数) / hybk(行业) 等。"""
    url = f"https://push2ex.eastmoney.com/{endpoint}"
    params = {"ut": _ZTB_UT, "dpt": "wz.ztzt", "Pageindex": 0,
              "pagesize": 10000, "sort": sort, "date": date}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        return (r.json().get("data") or {}).get("pool") or []
    except Exception:
        return []


def _numf(v):
    """东财数值字段可能是 '-'（停牌/无数据）→ 归一成 float 或 None。"""
    return v if isinstance(v, (int, float)) else None


def _optional_float(value) -> float | None:
    """通用可选浮点：缺失 / 东财占位符 / 不可解析 → None；真实 0 保留为 0.0。

    比 `_numf` 更完整：可解析数字字符串（如 ``"12.5"``），不把缺失伪装成 0。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        # NaN / Inf 视为无效
        try:
            if math.isnan(value) or math.isinf(value):  # type: ignore[arg-type]
                return None
        except TypeError:
            pass
        return float(value)
    s = str(value).strip()
    if not s or s in ("-", "--"):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _optional_int(value) -> int | None:
    """可选整数：缺失 / 占位符 / 不可解析 → None；真实 0 保留为 0。"""
    f = _optional_float(value)
    if f is None:
        return None
    try:
        return int(f)
    except (TypeError, ValueError, OverflowError):
        return None


def market_turnover_rank(n: int = 20) -> list[dict]:
    """全市场成交额榜（沪深京 A 股按成交额降序 TopN）。

    东财行情中心 clist。**push2(实时) 不可达时降级 push2delay(延迟行情，日榜场景足够)**。
    返回每只: code / name / price / pct / amount(成交额,元) / mcap(总市值,元) /
    float_cap(流通市值,元) / industry。
    """
    params = {"pn": 1, "pz": n, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f6",
              "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
              "fields": "f12,f14,f2,f3,f6,f20,f21,f100"}
    diff: list[dict] = []
    for host in ("push2.eastmoney.com", "push2delay.eastmoney.com"):
        try:
            r = em_get(f"https://{host}/api/qt/clist/get", params=params,
                       headers={"User-Agent": UA}, timeout=12)
            diff = (r.json().get("data") or {}).get("diff") or []
            if diff:
                break
        except Exception:
            continue
    return [{
        "code": str(d.get("f12", "")), "name": d.get("f14", ""),
        "price": _numf(d.get("f2")), "pct": _numf(d.get("f3")),
        "amount": _numf(d.get("f6")), "mcap": _numf(d.get("f20")),
        "float_cap": _numf(d.get("f21")), "industry": d.get("f100", "") or "",
    } for d in diff]


# ---------------------------------------------------------------------------
# 全 A 股行情快照（沪深京 · 分页 clist）
# ---------------------------------------------------------------------------
_A_SHARE_FS = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048"
_A_SHARE_FIELDS = "f2,f3,f4,f5,f6,f7,f8,f12,f13,f14,f15,f16,f17,f18,f20,f21"
_A_SHARE_PAGE_SIZE = 200
_A_SHARE_CLIST_HOSTS = ("push2.eastmoney.com", "push2delay.eastmoney.com")


def _normalize_clist_diff(diff) -> list[dict]:
    """东财 clist `data.diff`：list 或以数字字符串为键的 dict，统一成 list[dict]。"""
    if diff is None:
        return []
    if isinstance(diff, list):
        return [x for x in diff if isinstance(x, dict)]
    if isinstance(diff, dict):
        def _key(k):
            s = str(k)
            return (0, int(s)) if s.isdigit() else (1, s)

        return [diff[k] for k in sorted(diff.keys(), key=_key) if isinstance(diff[k], dict)]
    raise RuntimeError(f"a_share_snapshot: unexpected clist diff type {type(diff).__name__}")


def _map_a_share_row(d: dict) -> dict | None:
    """单条 clist 记录 → 标准快照字段；无效代码/空名称返回 None（过滤）。"""
    code = str(d.get("f12") or "").strip()
    name = str(d.get("f14") or "").strip()
    if not (len(code) == 6 and code.isdigit()):
        return None
    if not name:
        return None
    market = d.get("f13")
    if market == "" or market is None:
        market = None
    return {
        "code": code,
        "name": name,
        "market": market,
        "price": _optional_float(d.get("f2")),
        "change_pct": _optional_float(d.get("f3")),
        "change": _optional_float(d.get("f4")),
        "volume": _optional_float(d.get("f5")),
        "amount": _optional_float(d.get("f6")),
        "amplitude_pct": _optional_float(d.get("f7")),
        "turnover_pct": _optional_float(d.get("f8")),
        "high": _optional_float(d.get("f15")),
        "low": _optional_float(d.get("f16")),
        "open": _optional_float(d.get("f17")),
        "prev_close": _optional_float(d.get("f18")),
        "market_cap": _optional_float(d.get("f20")),
        "float_market_cap": _optional_float(d.get("f21")),
    }


def a_share_snapshot(*, page_size: int = _A_SHARE_PAGE_SIZE) -> list[dict]:
    """一次分页获取沪 / 深 / 京全部 A 股实时或收盘快照。

    数据源：东财 ``/api/qt/clist/get``（经 ``em_get`` 串行限流）。
    失败不伪装成空市场：网络 / JSON / 结构异常抛出 ``RuntimeError``。

    分页说明：
    - 上游可能强制限制每页最多 100 条，即使请求 ``pz`` 更大；
    - 在已知 ``total`` 且尚未取完时，**不得**因本页条数 < page_size 而提前结束
      （否则只拿到第一页 100 条）；
    - 空页终止；``fetched_raw >= total`` 终止；
    - 仅当 total 未知/为 0 时，才用「本页短于 page_size」作为取尽信号。
    - 按 code 去重，保留首次出现顺序；缺 code 记录跳过。
    """
    if page_size < 1:
        raise ValueError("page_size must be >= 1")

    out: list[dict] = []
    seen_codes: set[str] = set()
    fetched_raw = 0  # 原始 diff 条数（过滤/去重前），与上游 total 对齐
    total: int | None = None  # None=尚未解析；0=未知/缺失
    host = _A_SHARE_CLIST_HOSTS[0]
    pn = 1
    prev_page_fingerprint: tuple[str, ...] | None = None
    # 安全上限：避免死循环（约 100 条/页 × 200 页 ≫ 全 A）
    _MAX_PAGES = 500

    while pn <= _MAX_PAGES:
        params = {
            "pn": str(pn),
            "pz": str(page_size),
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": _A_SHARE_FS,
            "fields": _A_SHARE_FIELDS,
        }
        headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}

        # 首页探测 push2 → push2delay；后续页固定可用主机（与 market_turnover_rank 一致）
        # 每页：同一页内有限重试瞬时网络错误；失败换主机；不回到第 1 页重跑
        hosts = _A_SHARE_CLIST_HOSTS if pn == 1 else (host,)
        payload = None
        last_err: Exception | None = None
        for h in hosts:
            try:
                r = _em_get_page_with_retries(
                    f"https://{h}/api/qt/clist/get",
                    params=params,
                    headers=headers,
                    timeout=15,
                )
                try:
                    payload = r.json()
                except Exception as e:  # noqa: BLE001 — JSON 解析失败不重试网络
                    raise RuntimeError(
                        f"a_share_snapshot page {pn}: invalid JSON from {h}: {e}"
                    ) from e
                host = h
                last_err = None
                break
            except RuntimeError:
                raise
            except Exception as e:  # noqa: BLE001 — 本主机用尽重试，尝试下一主机
                last_err = e
                continue
        if payload is None:
            # 整页失败：整体失败，不返回已抓到的部分列表
            raise RuntimeError(
                f"a_share_snapshot page {pn}: request failed: {last_err}"
            ) from last_err

        if not isinstance(payload, dict):
            raise RuntimeError(
                f"a_share_snapshot page {pn}: response is not a dict ({type(payload).__name__})"
            )
        if "data" not in payload or payload["data"] is None:
            raise RuntimeError(f"a_share_snapshot page {pn}: missing data in response")
        data = payload["data"]
        if not isinstance(data, dict):
            raise RuntimeError(
                f"a_share_snapshot page {pn}: data is not a dict ({type(data).__name__})"
            )

        if total is None:
            raw_total = data.get("total")
            if raw_total is None:
                total = 0  # 未知：仅靠空页/短页（在无可靠 total 时）结束
            else:
                try:
                    total = int(raw_total)
                except (TypeError, ValueError) as e:
                    raise RuntimeError(
                        f"a_share_snapshot: invalid total {raw_total!r}"
                    ) from e
                if total < 0:
                    raise RuntimeError(
                        f"a_share_snapshot: invalid total {raw_total!r}"
                    )

        try:
            rows = _normalize_clist_diff(data.get("diff"))
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"a_share_snapshot page {pn}: bad diff: {e}") from e

        if pn == 1 and total > 0 and not rows:
            raise RuntimeError(
                f"a_share_snapshot: total={total} but first page is empty"
            )

        if not rows:
            # 空页：正常结束（total 未知或已取尽）
            break

        # 重复页保护（同一批 code 指纹且无新增唯一股票）
        page_codes = [
            str(item.get("f12") or "").strip()
            for item in rows
            if isinstance(item, dict)
        ]
        fingerprint = tuple(page_codes)
        if prev_page_fingerprint is not None and fingerprint == prev_page_fingerprint:
            raise RuntimeError(
                f"a_share_snapshot page {pn}: repeated page content without progress "
                f"(same {len(fingerprint)} codes as previous page)"
            )
        prev_page_fingerprint = fingerprint

        fetched_raw += len(rows)
        new_unique = 0
        for item in rows:
            mapped = _map_a_share_row(item)
            if mapped is None:
                continue
            code = mapped["code"]
            if code in seen_codes:
                continue
            seen_codes.add(code)
            out.append(mapped)
            new_unique += 1

        if pn > 1 and new_unique == 0:
            raise RuntimeError(
                f"a_share_snapshot page {pn}: no new unique codes "
                f"(fetched_raw={fetched_raw}, unique={len(out)}, total={total})"
            )

        # 终止：已达到上游 total（按原始条数，避免过滤导致永远 < total）
        if total > 0 and fetched_raw >= total:
            break

        # total 未知时：本页短于请求页大小 → 视为末页
        # total 已知且未取完：即使上游强制每页 100 < page_size，也必须继续翻页
        if total <= 0 and len(rows) < page_size:
            break

        pn += 1

    if pn > _MAX_PAGES:
        raise RuntimeError(
            f"a_share_snapshot: exceeded max pages {_MAX_PAGES} "
            f"(unique={len(out)}, fetched_raw={fetched_raw}, total={total})"
        )

    return out


# ---------------------------------------------------------------------------
# 行业 / 概念 / 地域板块排名（东财 clist · 分页）
# ---------------------------------------------------------------------------
BOARD_FS: dict[str, str] = {
    "industry": "m:90+t:2",
    "concept": "m:90+t:3+f:!50",
    "region": "m:90+t:1+f:!50",
}
_BOARD_FIELDS = "f3,f8,f12,f14,f20,f104,f105,f128,f136"
_BOARD_PAGE_SIZE = 200
_BOARD_CLIST_HOSTS = ("push2.eastmoney.com", "push2delay.eastmoney.com")


def _map_board_row(d: dict) -> dict | None:
    """单条板块 clist → 标准记录；代码或名称为空则过滤。"""
    code = str(d.get("f12") or "").strip()
    name = str(d.get("f14") or "").strip()
    if not code or not name:
        return None
    up_count = _optional_int(d.get("f104"))
    down_count = _optional_int(d.get("f105"))
    # up_ratio 仅基于接口上涨/下跌家数，不含平盘（接口未提供 flat）
    if (
        up_count is not None
        and down_count is not None
        and (up_count + down_count) > 0
    ):
        up_ratio: float | None = round(up_count / (up_count + down_count), 4)
    else:
        up_ratio = None
    leader = d.get("f128")
    if leader is not None:
        leader = str(leader).strip() or None
    return {
        "code": code,
        "name": name,
        "change_pct": _optional_float(d.get("f3")),
        "turnover_pct": _optional_float(d.get("f8")),
        "market_cap": _optional_float(d.get("f20")),
        "up_count": up_count,
        "down_count": down_count,
        "up_ratio": up_ratio,
        "leader": leader,
        "leader_change_pct": _optional_float(d.get("f136")),
    }


def board_ranking(board_type: str = "industry", top_n: int = 20, *, page_size: int = _BOARD_PAGE_SIZE) -> dict:
    """统一行业 / 概念 / 地域板块涨跌幅排名（东财 clist 分页）。

    - ``board_type``: industry | concept | region
    - ``top_n``: 1..100，取最强 / 最弱各 top_n
    - 本地按 change_pct 重排，不依赖远端顺序
    - 无 change_pct 的板块计入 total/unknown_count，不进 top/bottom
    - ``up_ratio`` = up_count / (up_count + down_count)，不含平盘

    本函数只返回原始统计结构，不含 status 信封（由上层包装）。
    """
    if board_type not in BOARD_FS:
        raise ValueError(f"不支持的板块类型：{board_type}")
    if not isinstance(top_n, int) or isinstance(top_n, bool) or not (1 <= top_n <= 100):
        raise ValueError(f"top_n 必须在 1..100 之间，收到：{top_n!r}")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")

    fs = BOARD_FS[board_type]
    raw_items: list[dict] = []
    fetched = 0
    total: int | None = None
    host = _BOARD_CLIST_HOSTS[0]
    pn = 1

    while True:
        params = {
            "pn": str(pn),
            "pz": str(page_size),
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": fs,
            "fields": _BOARD_FIELDS,
        }
        headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
        hosts = _BOARD_CLIST_HOSTS if pn == 1 else (host,)
        payload = None
        last_err: Exception | None = None
        for h in hosts:
            try:
                r = em_get(
                    f"https://{h}/api/qt/clist/get",
                    params=params,
                    headers=headers,
                    timeout=15,
                )
                try:
                    payload = r.json()
                except Exception as e:  # noqa: BLE001
                    raise RuntimeError(
                        f"board_ranking({board_type}) page {pn}: invalid JSON from {h}: {e}"
                    ) from e
                host = h
                last_err = None
                break
            except RuntimeError:
                raise
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
        if payload is None:
            raise RuntimeError(
                f"board_ranking({board_type}) page {pn}: request failed: {last_err}"
            ) from last_err

        if not isinstance(payload, dict):
            raise RuntimeError(
                f"board_ranking({board_type}) page {pn}: response is not a dict"
            )
        if "data" not in payload or payload["data"] is None:
            raise RuntimeError(
                f"board_ranking({board_type}) page {pn}: missing data in response"
            )
        data = payload["data"]
        if not isinstance(data, dict):
            raise RuntimeError(
                f"board_ranking({board_type}) page {pn}: data is not a dict"
            )

        if total is None:
            raw_total = data.get("total")
            try:
                total = int(raw_total) if raw_total is not None else 0
            except (TypeError, ValueError) as e:
                raise RuntimeError(
                    f"board_ranking({board_type}): invalid total {raw_total!r}"
                ) from e

        try:
            rows = _normalize_clist_diff(data.get("diff"))
        except RuntimeError as e:
            raise RuntimeError(
                f"board_ranking({board_type}) page {pn}: {e}"
            ) from e

        if pn == 1 and total > 0 and not rows:
            raise RuntimeError(
                f"board_ranking({board_type}): total={total} but first page is empty"
            )
        if not rows:
            break

        fetched += len(rows)
        raw_items.extend(rows)

        if fetched >= total:
            break
        if len(rows) < page_size:
            break
        pn += 1

    # 映射 + 过滤 + 去重（同 code 保留第一条，稳定）
    seen: set[str] = set()
    boards: list[dict] = []
    for item in raw_items:
        mapped = _map_board_row(item)
        if mapped is None:
            continue
        if mapped["code"] in seen:
            continue
        seen.add(mapped["code"])
        boards.append(mapped)

    ranked = [b for b in boards if b["change_pct"] is not None]
    unknown_count = len(boards) - len(ranked)
    ranked_desc = sorted(ranked, key=lambda x: float(x["change_pct"]), reverse=True)
    ranked_asc = sorted(ranked, key=lambda x: float(x["change_pct"]))

    return {
        "type": board_type,
        "total": len(boards),
        "ranked_count": len(ranked),
        "unknown_count": unknown_count,
        "top": ranked_desc[:top_n],
        "bottom": ranked_asc[:top_n],
    }


def eastmoney_datacenter(report_name: str, columns: str = "ALL", filter_str: str = "",
                         page_size: int = 50, sort_columns: str = "", sort_types: str = "-1") -> list[dict]:
    """东财数据中心统一查询 —— 龙虎榜/解禁/融资融券/大宗交易/股东户数/分红 共用（已内置限流）。"""
    params = {
        "reportName": report_name, "columns": columns, "filter": filter_str,
        "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types, "source": "WEB", "client": "WEB",
    }
    try:
        d = em_get(_DATACENTER_URL, params=params, timeout=15).json()
    except Exception:
        return []
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


def margin_trading(code: str, page_size: int = 30) -> list[dict]:
    """融资融券明细（日级）：融资余额 / 融资买入 / 融券余额 / 两融合计。"""
    data = eastmoney_datacenter(
        "RPTA_WEB_RZRQ_GGMX", filter_str=f'(SCODE="{code}")',
        page_size=page_size, sort_columns="DATE", sort_types="-1")
    return [{
        "date": str(r.get("DATE", ""))[:10],
        "rzye": r.get("RZYE", 0), "rzmre": r.get("RZMRE", 0), "rzche": r.get("RZCHE", 0),
        "rqye": r.get("RQYE", 0), "rqmcl": r.get("RQMCL", 0),
        "rzrqye": r.get("RZRQYE", 0),
    } for r in data]


def block_trade(code: str, page_size: int = 20) -> list[dict]:
    """大宗交易：成交价 / 折溢价率 / 量 / 买卖方营业部。"""
    data = eastmoney_datacenter(
        "RPT_DATA_BLOCKTRADE", filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size, sort_columns="TRADE_DATE", sort_types="-1")
    rows = []
    for r in data:
        close = r.get("CLOSE_PRICE") or 0
        deal = r.get("DEAL_PRICE") or 0
        rows.append({
            "date": str(r.get("TRADE_DATE", ""))[:10],
            "price": deal, "close": close,
            "premium_pct": round((deal / close - 1) * 100, 2) if close else 0,
            "vol": r.get("DEAL_VOLUME", 0), "amount": r.get("DEAL_AMT", 0),
            "buyer": r.get("BUYER_NAME", ""), "seller": r.get("SELLER_NAME", ""),
        })
    return rows


def holder_num_change(code: str, page_size: int = 10) -> list[dict]:
    """股东户数变化（季度级）：户数 / 环比 / 户均持股。持续减少 = 筹码集中。"""
    data = eastmoney_datacenter(
        "RPT_HOLDERNUMLATEST", filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size, sort_columns="END_DATE", sort_types="-1")
    return [{
        "date": str(r.get("END_DATE", ""))[:10],
        "holder_num": r.get("HOLDER_NUM", 0),
        "change_ratio": r.get("HOLDER_NUM_RATIO", 0),
        "avg_shares": r.get("AVG_FREE_SHARES", 0),
    } for r in data]


def dividend_history(code: str, page_size: int = 20) -> list[dict]:
    """分红送转历史：每股派息（税前）/ 每10股转增 / 每10股送股 / 进度。"""
    data = eastmoney_datacenter(
        "RPT_SHAREBONUS_DET", filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size, sort_columns="EX_DIVIDEND_DATE", sort_types="-1")
    return [{
        "date": str(r.get("EX_DIVIDEND_DATE", ""))[:10],
        "bonus_rmb": r.get("PRETAX_BONUS_RMB", 0),
        "transfer_ratio": r.get("TRANSFER_RATIO", 0),
        "bonus_ratio": r.get("BONUS_RATIO", 0),
        "plan": r.get("ASSIGN_PROGRESS", ""),
    } for r in data]


def stock_fund_flow_120d(code: str) -> list[dict]:
    """个股资金流（日级，最近 120 交易日）：主力 / 小单 / 中单 / 大单 / 超大单净流入（元）。"""
    market_code = 1 if code.startswith("6") else 0
    params = {
        "secid": f"{market_code}.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "lmt": "120",
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/", "Origin": "https://quote.eastmoney.com"}
    try:
        d = em_get("https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
                   params=params, headers=headers, timeout=15).json()
    except Exception:
        return []
    rows = []
    for line in d.get("data", {}).get("klines", []):
        p = line.split(",")
        if len(p) >= 6:
            def _f(x):
                try:
                    return float(x) if x not in ("-", "") else 0.0
                except ValueError:
                    return 0.0
            rows.append({
                "date": p[0], "main_net": _f(p[1]), "small_net": _f(p[2]),
                "mid_net": _f(p[3]), "large_net": _f(p[4]), "super_net": _f(p[5]),
            })
    return rows


def dragon_tiger_board(code: str, trade_date: str | None = None, look_back: int = 30) -> dict:
    """龙虎榜：该股近期上榜记录 + 最近一次买卖席位 TOP5 + 机构专用席位净买。"""
    trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
    start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back)).strftime("%Y-%m-%d")
    records = []
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f'(TRADE_DATE>=\'{start}\')(TRADE_DATE<=\'{trade_date}\')(SECURITY_CODE="{code}")',
        page_size=50, sort_columns="TRADE_DATE", sort_types="-1")
    for r in data:
        records.append({
            "date": str(r.get("TRADE_DATE", ""))[:10],
            "reason": r.get("EXPLANATION", ""),
            "net_buy": round((r.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),  # 万元
            "turnover": round(float(r.get("TURNOVERRATE") or 0), 2),
        })

    seats = {"buy": [], "sell": []}
    institution = {"buy_amt": 0.0, "sell_amt": 0.0, "net_amt": 0.0}
    if records:
        latest = records[0]["date"]
        buy_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSBUY",
            filter_str=f'(TRADE_DATE=\'{latest}\')(SECURITY_CODE="{code}")',
            page_size=10, sort_columns="BUY", sort_types="-1")
        sell_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSSELL",
            filter_str=f'(TRADE_DATE=\'{latest}\')(SECURITY_CODE="{code}")',
            page_size=10, sort_columns="SELL", sort_types="-1")
        for r in buy_data[:5]:
            seats["buy"].append({"name": r.get("OPERATEDEPT_NAME", ""),
                                 "buy_amt": round((r.get("BUY") or 0) / 10000, 1),
                                 "sell_amt": round((r.get("SELL") or 0) / 10000, 1),
                                 "net": round((r.get("NET") or 0) / 10000, 1)})
        for r in sell_data[:5]:
            seats["sell"].append({"name": r.get("OPERATEDEPT_NAME", ""),
                                  "buy_amt": round((r.get("BUY") or 0) / 10000, 1),
                                  "sell_amt": round((r.get("SELL") or 0) / 10000, 1),
                                  "net": round((r.get("NET") or 0) / 10000, 1)})
        for detail, side in ((buy_data, "buy"), (sell_data, "sell")):
            for r in detail:
                if str(r.get("OPERATEDEPT_CODE", "")) == "0":  # 机构专用席位
                    amt = (r.get("BUY") or 0) if side == "buy" else (r.get("SELL") or 0)
                    institution[f"{side}_amt"] += amt
        institution["buy_amt"] = round(institution["buy_amt"] / 10000, 1)
        institution["sell_amt"] = round(institution["sell_amt"] / 10000, 1)
        institution["net_amt"] = round(institution["buy_amt"] - institution["sell_amt"], 1)
    return {"records": records, "seats": seats, "institution": institution}


def lockup_expiry(code: str, trade_date: str | None = None, forward_days: int = 90) -> dict:
    """限售解禁日历：历史解禁记录 + 未来 N 天待解禁事件。

    字段随东财 2026 改列名同步（a-stock-data §3.6）：旧 LIMITED_STOCK_TYPE/FREE_SHARES_NUM
    已废、致 type/shares 恒空 → 改 FREE_SHARES_TYPE/FREE_SHARES，并补 able_shares（实际可流通股数）。
    """
    trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
    history = [{
        "date": str(r.get("FREE_DATE", ""))[:10], "type": r.get("FREE_SHARES_TYPE", ""),
        "shares": r.get("FREE_SHARES", 0), "able_shares": r.get("ABLE_FREE_SHARES", 0),
        "ratio": r.get("FREE_RATIO", 0),
    } for r in eastmoney_datacenter(
        "RPT_LIFT_STAGE", filter_str=f'(SECURITY_CODE="{code}")',
        page_size=15, sort_columns="FREE_DATE", sort_types="-1")]

    end = (datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=forward_days)).strftime("%Y-%m-%d")
    upcoming = [{
        "date": str(r.get("FREE_DATE", ""))[:10], "type": r.get("FREE_SHARES_TYPE", ""),
        "shares": r.get("FREE_SHARES", 0), "able_shares": r.get("ABLE_FREE_SHARES", 0),
        "ratio": r.get("FREE_RATIO", 0),
    } for r in eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f'(SECURITY_CODE="{code}")(FREE_DATE>=\'{trade_date}\')(FREE_DATE<=\'{end}\')',
        page_size=20, sort_columns="FREE_DATE", sort_types="1")]
    return {"history": history, "upcoming": upcoming}


_MAX_STRICT_NUMERIC = 1_000_000_000


def _strict_scalar_field(
    row: dict,
    field: str,
    *,
    required: bool = False,
    text: bool = False,
    numeric: bool = False,
) -> None:
    """Validate an upstream scalar without turning malformed rows into empty data."""
    if field not in row:
        if required:
            raise ValueError(f"missing required field: {field}")
        return
    value = row[field]
    if value is None:
        if required:
            raise ValueError(f"required field is null: {field}")
        return
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"field has invalid type: {field}")
    if text and (not isinstance(value, str) or not value.strip()):
        raise ValueError(f"field is not non-empty text: {field}")
    if numeric:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"field is not numeric: {field}") from None
        if not math.isfinite(number) or abs(number) > _MAX_STRICT_NUMERIC:
            raise ValueError(f"field is not a finite reasonable number: {field}")


def _validate_strict_concept_block_row(row: dict) -> None:
    _strict_scalar_field(row, "f12", required=True, text=True)
    _strict_scalar_field(row, "f14", required=True, text=True)
    _strict_scalar_field(row, "f3", numeric=True)
    _strict_scalar_field(row, "f128", text=True)


def _validate_strict_hot_concept_row(row: dict) -> None:
    _strict_scalar_field(row, "conceptName", required=True, text=True)
    _strict_scalar_field(row, "conceptId")
    _strict_scalar_field(row, "hitCount", numeric=True)


def concept_blocks(code: str, *, strict: bool = False) -> dict:
    """个股所属板块/概念归属（东财 slist，行业/概念/地域混合，板块名自解释）。

    ``strict`` 仅供需要区分“真实空结果”和“源失败”的只读组合层使用；
    默认保持既有调用方的空结果降级语义。
    """
    market_code = 1 if code.startswith("6") else 0
    params = {"fltt": "2", "invt": "2", "secid": f"{market_code}.{code}",
              "spt": "3", "pi": "0", "pz": "200", "po": "1", "fields": "f12,f14,f3,f128"}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        d = em_get("https://push2.eastmoney.com/api/qt/slist/get", params=params, headers=headers, timeout=15).json()
        if strict:
            if not isinstance(d, dict) or not isinstance(d.get("data"), dict):
                raise ValueError("concept_blocks response missing data object")
            diff = d["data"].get("diff")
            if not isinstance(diff, (dict, list)):
                raise ValueError("concept_blocks response missing diff collection")
            items = list(diff.values()) if isinstance(diff, dict) else list(diff)
            if any(not isinstance(item, dict) for item in items):
                raise ValueError("concept_blocks response contains malformed rows")
            for item in items:
                _validate_strict_concept_block_row(item)
        else:
            diff = (d.get("data") or {}).get("diff") or {}
            items = diff.values() if isinstance(diff, dict) else diff
    except Exception:
        if strict:
            raise
        return {"total": 0, "boards": [], "concept_tags": []}
    boards = [{"name": it.get("f14", ""), "code": it.get("f12", ""),
               "change_pct": it.get("f3", ""), "lead_stock": it.get("f128", "")} for it in items]
    return {"total": len(boards), "boards": boards, "concept_tags": [b["name"] for b in boards]}


def hot_concepts(code: str, *, strict: bool = False) -> list[dict]:
    """个股当下被市场归到哪些概念在炒（东财热门概念命中，按热度降序）。

    ``strict`` 仅供需要区分“真实空结果”和“源失败”的只读组合层使用；
    默认保持既有调用方的空结果降级语义。
    """
    import requests

    try:
        prefix = "SH" if code.startswith("6") else "SZ"
        r = requests.post(
            "https://emappdata.eastmoney.com/stockrank/getHotStockRankList",
            json={"appId": "appId01", "globalId": "786e4c21-70dc-435a-93bb-38", "srcSecurityCode": prefix + code},
            headers={"User-Agent": UA}, timeout=10)
        payload = r.json()
        if strict:
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("hot_concepts response missing data list")
            data = payload["data"]
            if any(not isinstance(item, dict) for item in data):
                raise ValueError("hot_concepts response contains malformed rows")
            for item in data:
                _validate_strict_hot_concept_row(item)
        else:
            data = payload.get("data") or []
    except Exception:
        if strict:
            raise
        return []
    return [{"concept": x.get("conceptName"), "bk": x.get("conceptId"), "hit": x.get("hitCount")} for x in data]


def investor_qa(code: str, page_size: int = 30) -> list[dict]:
    """互动易问答（巨潮）：投资者提问 + 公司回复（answer=None 表示未回复）。"""
    import requests

    try:
        r1 = requests.post("https://irm.cninfo.com.cn/newircs/index/queryKeyboardInfo",
                           data={"keyWord": code}, headers={"User-Agent": UA}, timeout=10)
        d1 = r1.json().get("data") or []
        if not d1:
            return []
        org_id = d1[0].get("secid")
        params = {"_t": 1, "stockcode": code, "orgId": org_id, "pageSize": page_size,
                  "pageNum": 1, "keyWord": "", "startDay": "", "endDay": ""}
        rows = requests.post("https://irm.cninfo.com.cn/newircs/company/question",
                             params=params, headers={"User-Agent": UA}, timeout=10).json().get("rows") or []
    except Exception:
        return []
    out = []
    for it in rows:
        ts = it.get("pubDate")
        out.append({
            "company": it.get("companyShortName"),
            "question": it.get("mainContent"), "answer": it.get("attachedContent"),
            "answerer": it.get("attachedAuthor"),
            "ask_time": datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M") if ts else "",
        })
    return out


def industry_comparison(top_n: int = 20) -> dict:
    """全行业涨跌幅排名（东财行业板块，~100 个行业）：板块级涨跌 / 涨跌家数 / 领涨。"""
    params = {"pn": "1", "pz": "100", "po": "1", "np": "1", "fltt": "2", "invt": "2",
              "fid": "f3",  # fid=f3 + po=1：按涨跌幅降序，否则 top/bottom 切片非涨幅序（a-stock-data §3.7）
              "fs": "m:90+t:2", "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207"}
    try:
        d = em_get("https://push2.eastmoney.com/api/qt/clist/get",
                   params=params, headers={"User-Agent": UA}, timeout=15).json()
    except Exception:
        return {"top": [], "bottom": [], "total": 0}
    items = d.get("data", {}).get("diff", [])
    if isinstance(items, dict):
        items = list(items.values())
    if not items:
        return {"top": [], "bottom": [], "total": 0}
    rows = [{
        "rank": i + 1, "name": it.get("f14", ""), "change_pct": it.get("f3", 0),
        "code": it.get("f12", ""), "up_count": it.get("f104", 0), "down_count": it.get("f105", 0),
    } for i, it in enumerate(items)]
    return {"top": rows[:top_n], "bottom": rows[-top_n:], "total": len(rows)}
