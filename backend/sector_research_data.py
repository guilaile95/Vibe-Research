"""板块研究数据服务 —— 复用 a-stock-data 能力，为板块研究工作台提供：
- 行业研报发现（eastmoney_industry_reports）
- 个股研报发现（eastmoney_reports）
- 研报归一化 / 相关性评分
- 板块动态数据（一致预期 / 公告 / 新闻）
- 板块数据源注册表（关键词 / 代表公司 / 回溯天数 / 动态面板）

不重新实现东财接口；全部委托 backend/astock.py。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import astock

# ---------------------------------------------------------------------------
# PCB 代表公司（代码经校验，禁止混用）
# ---------------------------------------------------------------------------

PCB_COMPANY_CODES = {
    "002463": "沪电股份",
    "002916": "深南电路",
    "300476": "胜宏科技",
    "603228": "景旺电子",
    "600183": "生益科技",
}


# ---------------------------------------------------------------------------
# 板块数据源注册表（第一轮只要求 PCB 真实可用）
# ---------------------------------------------------------------------------


@dataclass
class SectorDataSource:
    """单个板块的研报/数据源配置。"""

    key: str
    label: str
    report_keywords: list[str] = field(default_factory=list)
    representative_company_codes: list[str] = field(default_factory=list)
    report_lookback_days: int = 365
    dynamic_panels: list[str] = field(default_factory=list)


# PCB 数据源：关键词覆盖高速 PCB / 覆铜板 / HDI / 高速材料等。
PCB_SOURCES = SectorDataSource(
    key="pcb",
    label="PCB（印制电路板）",
    report_keywords=[
        "PCB", "印制电路板", "覆铜板", "高速PCB", "AI服务器PCB", "服务器PCB",
        "交换机PCB", "HDI", "高多层板", "背板", "正交背板", "铜中板",
        "低轮廓铜箔", "112G", "224G", "448G", "覆铜板材料",
    ],
    representative_company_codes=["002463", "002916", "300476", "603228", "600183"],
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# 注册表：key -> SectorDataSource。
SECTOR_SOURCES: dict[str, SectorDataSource] = {
    PCB_SOURCES.key: PCB_SOURCES,
}


def get_sector_source(key: str) -> SectorDataSource | None:
    return SECTOR_SOURCES.get(key)


def list_sector_source_keys() -> list[str]:
    return list(SECTOR_SOURCES.keys())


# ---------------------------------------------------------------------------
# 研报归一化
# ---------------------------------------------------------------------------

# 东财 reportapi 字段可能是 camelCase 或 snake_case：
#   infoCode / info_code, orgName / orgSName / org_name,
#   publishDate / publish_date, industryName / industry_name,
#   stockCode / code / rcode, stockName / companyName / ssecName,
#   rating / emRating
# 字段缺失时使用 null，不得猜测。

_PDF_HOST_ALLOW = ("pdf.dfcfw.com", "pdfcdn.eastmoney.com")


def _safe_strip(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _first_present(raw: dict, *keys: str) -> str | None:
    """按键顺序取第一个非空字段；不猜测。"""
    for k in keys:
        v = _safe_strip(raw.get(k))
        if v is not None:
            return v
    return None


def normalize_report(raw: dict) -> dict:
    """把东财原始研报 dict 归一化为统一研报结构。缺失字段用 null，不猜测。"""
    info_code = _first_present(raw, "infoCode", "info_code")
    institution = _first_present(raw, "orgName", "orgSName", "org_name")
    publish_date = _first_present(raw, "publishDate", "publish_date")
    industry_name = _first_present(raw, "industryName", "industry_name")
    company_code = _first_present(raw, "stockCode", "code", "rcode")
    company_name = _first_present(raw, "stockName", "companyName", "ssecName")
    rating = _first_present(raw, "rating", "emRating")
    pdf_url = astock.pdf_url(info_code) if info_code else None

    if company_code:
        report_scope = "company"
    elif industry_name:
        report_scope = "industry"
    else:
        report_scope = None

    return {
        "source_provider": "eastmoney",
        "external_id": info_code,
        "info_code": info_code,
        "title": _safe_strip(raw.get("title")),
        "institution": institution,
        "publish_date": publish_date,
        "industry_name": industry_name,
        "company_code": company_code,
        "company_name": company_name,
        "rating": rating,
        "pdf_url": pdf_url,
        "report_scope": report_scope,
        "report_type": "brokerage",
        "matched_keywords": [],
        "relevance_score": 0,
    }


# 研报相关性评分：标题命中关键词 + 公司代表 + 评级。

_RATING_SCORE = {
    "买入": 3, "增持": 2, "推荐": 2, "持有": 1, "中性": 1, "卖出": 0,
    "强烈推荐": 3, "审慎推荐": 2,
}


def score_report_relevance(norm: dict, keywords: list[str], company_codes: list[str]) -> int:
    """对归一化研报评分：关键词命中 + 代表公司 + 评级。"""
    score = 0
    title = (norm.get("title") or "").lower()
    hits = [k for k in keywords if k and k.lower() in title]
    score += len(hits) * 5
    norm["matched_keywords"] = hits
    if norm.get("company_code") and norm["company_code"] in company_codes:
        score += 8
    rating = norm.get("rating") or ""
    score += _RATING_SCORE.get(str(rating).strip(), 0)
    return score


# ---------------------------------------------------------------------------
# 发现服务
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryResult:
    source_key: str
    discovered: list[dict] = field(default_factory=list)
    filtered: list[dict] = field(default_factory=list)
    error: str | None = None


def _fetch_industry_raw(lookback: int, max_pages: int, keywords: list[str]) -> list[dict]:
    """拉取行业研报并按关键词过滤标题。"""
    raw_rows = astock.eastmoney_industry_reports(
        keywords=None, days=lookback, max_pages=max_pages,
    )
    if keywords:
        raw_rows = [r for r in raw_rows if any(k in (r.get("title") or "") for k in keywords)]
    return raw_rows


def _fetch_company_raw(company_codes: list[str], max_pages: int) -> list[dict]:
    """顺序拉取代表公司研报，按 external_id（info_code）去重。"""
    raw_rows: list[dict] = []
    seen: set[str] = set()
    for code in company_codes:
        for r in astock.eastmoney_reports(code, max_pages=max_pages):
            info = _first_present(r, "infoCode", "info_code")
            if info and info in seen:
                continue
            if info:
                seen.add(info)
            raw_rows.append(r)
    return raw_rows


def _sort_discovered(rows: list[dict]) -> None:
    """relevance_score desc, publish_date desc, external_id asc（稳定排序）。"""
    rows.sort(key=lambda n: n.get("external_id") or "")
    rows.sort(key=lambda n: n.get("publish_date") or "", reverse=True)
    rows.sort(key=lambda n: n.get("relevance_score") or 0, reverse=True)


def discover_sector_reports(
    sector_key: str,
    *,
    days: int | None = None,
    max_pages: int = 3,
    scope: str = "industry",
) -> DiscoveryResult:
    """发现板块研报（只返回发现结果，不自动归档）。

    scope: "industry" | "company" | "all"（由调用方校验非法值并返回 400）。
    - industry: 仅行业研报 + 关键词过滤
    - company: 顺序拉代表公司研报，external_id 去重
    - all: 合并 industry + company，按 external_id 去重
    排序：relevance_score desc, publish_date desc, external_id 作 tiebreaker。
    """
    src = get_sector_source(sector_key)
    if src is None:
        return DiscoveryResult(source_key=sector_key, error=f"未注册的板块：{sector_key}")
    lookback = days if days is not None else src.report_lookback_days
    keywords = src.report_keywords
    company_codes = src.representative_company_codes

    result = DiscoveryResult(source_key=sector_key)
    try:
        if scope == "company":
            raw_rows = _fetch_company_raw(company_codes, max_pages)
        elif scope == "all":
            industry_rows = _fetch_industry_raw(lookback, max_pages, keywords)
            company_rows = _fetch_company_raw(company_codes, max_pages)
            seen: set[str] = set()
            raw_rows = []
            for r in industry_rows + company_rows:
                info = _first_present(r, "infoCode", "info_code")
                if info and info in seen:
                    continue
                if info:
                    seen.add(info)
                raw_rows.append(r)
        else:
            # 默认 industry（调用方应对非法 scope 返回 400）
            raw_rows = _fetch_industry_raw(lookback, max_pages, keywords)

        result.discovered = [normalize_report(r) for r in raw_rows]
        for n in result.discovered:
            n["relevance_score"] = score_report_relevance(n, keywords, company_codes)
        result.filtered = [
            n for n in result.discovered
            if n.get("title") and (
                n.get("matched_keywords") or n.get("company_code") in company_codes
            )
        ]
        _sort_discovered(result.discovered)
        _sort_discovered(result.filtered)
    except Exception as e:  # noqa: BL001
        result.error = str(e)
    return result


def _safe_panel_error(exc: BaseException) -> str:
    """不向前端暴露堆栈；仅返回简短安全信息。"""
    name = type(exc).__name__
    if name == "DependencyMissing":
        return "依赖未安装"
    msg = str(exc).strip()
    if not msg:
        return f"{name}"
    # 截断路径与过长内容
    if len(msg) > 120:
        msg = msg[:117] + "..."
    if "Traceback" in msg or "\\" in msg or "/home/" in msg:
        return name
    return msg


def _panel_ok(data, summary: dict | None = None) -> dict:
    return {"status": "ok", "summary": summary or {}, "data": data, "error": None}


def _panel_err(exc: BaseException) -> dict:
    return {"status": "error", "summary": {}, "data": None, "error": _safe_panel_error(exc)}


def _summarize_individual_info(data) -> dict:
    """从 astock.individual_info 返回中提取最小摘要。"""
    if not isinstance(data, dict):
        return {}
    summary = {}
    for k in ("股票简称", "name", "简称", "公司名称"):
        if data.get(k):
            summary["name"] = str(data[k])[:50]
            break
    for k in ("所属行业", "industry", "行业"):
        if data.get(k):
            summary["industry"] = str(data[k])[:80]
            break
    for k in ("总市值", "流通市值", "market_cap"):
        if data.get(k):
            summary["market_cap"] = str(data[k])[:30]
            break
    for k in ("主营业务", "business", "经营范围"):
        if data.get(k):
            summary["business"] = str(data[k])[:200]
            break
    return summary


def _summarize_profit_forecast(data) -> dict:
    """从 astock.profit_forecast 返回中提取摘要。"""
    if not isinstance(data, dict):
        return {"note": "已取得一致预期数据，暂无法结构化摘要"}
    summary = {}
    for k in ("机构数", "coverage", "机构家数"):
        if data.get(k):
            summary["coverage"] = str(data[k])[:20]
            break
    for k in ("预测年度", "year", "最新年度"):
        if data.get(k):
            summary["year"] = str(data[k])[:10]
            break
    for k in ("预测净利润", "net_profit", "eps", "EPS"):
        if data.get(k):
            summary["forecast"] = str(data[k])[:50]
            break
    if not summary:
        summary["note"] = "已取得一致预期数据，暂无法结构化摘要"
    return summary


def _summarize_announcements(data) -> dict:
    """从 astock.announcements 返回中提取摘要。"""
    summary = {}
    if isinstance(data, list):
        summary["count"] = len(data)
        if data:
            first = data[0]
            if isinstance(first, dict):
                for k in ("标题", "title", "公告标题"):
                    if first.get(k):
                        summary["latest_title"] = str(first[k])[:120]
                        break
                for k in ("日期", "date", "公告日期"):
                    if first.get(k):
                        summary["latest_date"] = str(first[k])[:20]
                        break
    elif isinstance(data, dict) and "list" in data:
        return _summarize_announcements(data["list"])
    return summary


def get_sector_dynamic_data(sector_key: str) -> dict:
    """拉取板块动态数据（一致预期 / 公告 / 新闻）。

    合同：
      source / fetched_at / status(normal|partial|unavailable) / warnings / companies
    单家失败不导致整包空白。
    """
    from datetime import datetime, timezone

    src = get_sector_source(sector_key)
    if src is None:
        return {
            "sector_key": sector_key,
            "source": "a-stock-data",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "status": "unavailable",
            "warnings": [f"未注册的板块：{sector_key}"],
            "companies": [],
            "error": f"未注册的板块：{sector_key}",
        }

    codes = src.representative_company_codes
    name_map = PCB_COMPANY_CODES if sector_key == "pcb" else {}
    panels_enabled = list(src.dynamic_panels)
    companies: list[dict] = []
    warnings: list[str] = []
    ok_panels = 0
    fail_panels = 0

    for code in codes:
        company: dict = {
            "code": code,
            "name": name_map.get(code) or "",
            "panels": {},
        }
        if "individual_info" in panels_enabled:
            try:
                data = astock.individual_info(code)
                summary = _summarize_individual_info(data)
                company["panels"]["individual_info"] = _panel_ok(data, summary)
                # 尝试补名称
                if not company["name"] and summary.get("name"):
                    company["name"] = summary["name"]
                ok_panels += 1
            except Exception as e:  # noqa: BL001
                company["panels"]["individual_info"] = _panel_err(e)
                fail_panels += 1
                warnings.append(f"{code} 基本面：{_safe_panel_error(e)}")
        if "profit_forecast" in panels_enabled:
            try:
                data = astock.profit_forecast(code)
                summary = _summarize_profit_forecast(data)
                company["panels"]["profit_forecast"] = _panel_ok(data, summary)
                ok_panels += 1
            except Exception as e:  # noqa: BL001
                company["panels"]["profit_forecast"] = _panel_err(e)
                fail_panels += 1
                warnings.append(f"{code} 一致预期：{_safe_panel_error(e)}")
        if "announcements" in panels_enabled:
            try:
                anns = astock.announcements(code, limit=10)
                summary = _summarize_announcements(anns)
                company["panels"]["announcements"] = _panel_ok(anns, summary)
                ok_panels += 1
            except Exception as e:  # noqa: BL001
                company["panels"]["announcements"] = _panel_err(e)
                fail_panels += 1
                warnings.append(f"{code} 公告：{_safe_panel_error(e)}")
        companies.append(company)

    if ok_panels == 0:
        status = "unavailable"
    elif fail_panels == 0:
        status = "normal"
    else:
        status = "partial"

    return {
        "sector_key": sector_key,
        "source": "a-stock-data",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "warnings": warnings[:20],
        "companies": companies,
    }


def pdf_url_allowed(url: str | None) -> bool:
    """校验 PDF URL 域名是否在允许列表，且为 HTTPS。用于导入接口的 SSRF 防护。"""
    if not url:
        return False
    if not url.startswith("https://"):
        return False
    try:
        host = url.split("/", 3)[2].split(":")[0].lower()
    except (IndexError, ValueError):
        return False
    return host in _PDF_HOST_ALLOW
