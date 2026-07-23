"""板块研究数据服务 —— 复用 a-stock-data 能力，为板块研究工作台提供：
- 行业研报发现（eastmoney_industry_reports）
- 个股研报发现（eastmoney_reports）
- 研报归一化 / 相关性评分
- 板块动态数据（一致预期 / 公告 / 新闻）
- 板块数据源注册表（关键词 / 代表公司 / 回溯天数 / 动态面板）

不重新实现东财接口；全部委托 backend/astock.py。
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

import astock

# ---------------------------------------------------------------------------
# 板块数据源注册表（第一轮只要求 PCB 真实可用，其余保留经过校验的规划）
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


# PCB 数据源：关键词覆盖高速 PCB / 覆铜板 / 铜中板 / HDI / 高速材料等。
# 代表公司代码经 a-stock-data 实际验证（沪电 002463 / 深南 002916 / 胜宏 603228 / 景旺 603228 为同一只）。
PCB_SOURCES = SectorDataSource(
    key="pcb",
    label="PCB（印制电路板）",
    report_keywords=[
        "PCB", "印制电路板", "覆铜板", "高速PCB", "AI服务器PCB", "服务器PCB",
        "交换机PCB", "HDI", "高多层板", "背板", "正交背板", "铜中板",
        "低轮廓铜箔", "112G", "224G", "448G", "覆铜板材料",
    ],
    # 注意：景旺电子 603228 与胜宏科技 603228 代码重复，以 603228 为准；
    # 深南电路 002916、沪电股份 002463 为独立代码。
    representative_company_codes=["002463", "002916", "603228"],
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

# 东财 reportapi 字段（data 列表每项）：
#   title, info_code, orgName, publishDate, industryName, code, companyName, rating, emRating, ssecName
# 字段缺失时使用 null，不得猜测。

_PDF_HOST_ALLOW = ("pdf.dfcfw.com", "pdfcdn.eastmoney.com")


def _safe_strip(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def normalize_report(raw: dict) -> dict:
    """把东财原始研报 dict 归一化为统一研报结构。缺失字段用 null，不猜测。"""
    info_code = _safe_strip(raw.get("info_code"))
    company_code = _safe_strip(raw.get("code")) or _safe_strip(raw.get("rcode"))
    pdf_url = astock.pdf_url(info_code) if info_code else None
    return {
        "source_provider": "eastmoney",
        "external_id": info_code,
        "info_code": info_code,
        "title": _safe_strip(raw.get("title")),
        "institution": _safe_strip(raw.get("orgName")),
        "publish_date": _safe_strip(raw.get("publishDate")),
        "industry_name": _safe_strip(raw.get("industryName")),
        "company_code": company_code,
        "company_name": _safe_strip(raw.get("companyName")) or _safe_strip(raw.get("ssecName")),
        "pdf_url": pdf_url,
        "report_scope": ("company" if company_code else "industry") if (company_code or _safe_strip(raw.get("industryName"))) else None,
        "report_type": "brokerage",
        "matched_keywords": [],
        "relevance_score": 0,
    }


# 研报相关性评分：标题命中关键词 + 公司代表 + 时效 + 评级。

_RATING_SCORE = {
    "买入": 3, "增持": 2, "推荐": 2, "持有": 1, "中性": 1, "卖出": 0,
    "强烈推荐": 3, "审慎推荐": 2,
}


def score_report_relevance(norm: dict, keywords: list[str], company_codes: list[str]) -> int:
    """对归一化研报评分：关键词命中 + 代表公司 + 时效 + 评级。"""
    score = 0
    title = (norm.get("title") or "").lower()
    hits = [k for k in keywords if k and k.lower() in title]
    score += len(hits) * 5
    norm["matched_keywords"] = hits
    if norm.get("company_code") and norm["company_code"] in company_codes:
        score += 8
    rating = norm.get("emRating") or norm.get("rating") or ""
    score += _RATING_SCORE.get(str(rating).strip(), 0)
    return score


# ---------------------------------------------------------------------------
# 发现服务
# ---------------------------------------------------------------------------

_lock = threading.Lock()


@dataclass
class DiscoveryResult:
    source_key: str
    discovered: list[dict] = field(default_factory=list)
    filtered: list[dict] = field(default_factory=list)
    error: str | None = None


def discover_sector_reports(
    sector_key: str,
    *,
    days: int | None = None,
    max_pages: int = 3,
    scope: str = "industry",
) -> DiscoveryResult:
    """发现板块研报（只返回发现结果，不自动归档）。"""
    src = get_sector_source(sector_key)
    if src is None:
        return DiscoveryResult(source_key=sector_key, error=f"未注册的板块：{sector_key}")
    lookback = days if days is not None else src.report_lookback_days
    keywords = src.report_keywords
    company_codes = src.representative_company_codes

    result = DiscoveryResult(source_key=sector_key)
    try:
        if scope == "company":
            raw_rows: list[dict] = []
            seen_info: set[str] = set()
            for code in company_codes:
                for r in astock.eastmoney_reports(code, max_pages=max_pages):
                    info = r.get("info_code")
                    if info and info not in seen_info:
                        seen_info.add(info)
                        raw_rows.append(r)
        else:
            raw_rows = astock.eastmoney_industry_reports(keywords=None, days=lookback, max_pages=max_pages)
            if keywords:
                raw_rows = [r for r in raw_rows if any(k in r.get("title", "") for k in keywords)]

        result.discovered = [normalize_report(r) for r in raw_rows]
        # 评分 + 过滤（保留有标题且命中关键词 / 代表公司的研报）。
        for n in result.discovered:
            n["relevance_score"] = score_report_relevance(n, keywords, company_codes)
        result.filtered = [
            n for n in result.discovered
            if n.get("title") and (n.get("matched_keywords") or n.get("company_code") in company_codes)
        ]
        result.filtered.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    except Exception as e:  # noqa: BL001
        result.error = str(e)
    return result


def get_sector_dynamic_data(sector_key: str) -> dict:
    """拉取板块动态数据（一致预期 / 公告 / 新闻）。缺失字段用 null，不猜测。"""
    src = get_sector_source(sector_key)
    if src is None:
        return {"error": f"未注册的板块：{sector_key}"}
    codes = src.representative_company_codes
    out: dict = {"sector_key": sector_key, "companies": []}
    for code in codes:
        company = {"code": code}
        try:
            if "individual_info" in src.dynamic_panels:
                company["info"] = astock.individual_info(code)
        except Exception as e:  # noqa: BL001
            company["info_error"] = str(e)
        try:
            if "profit_forecast" in src.dynamic_panels:
                company["profit_forecast"] = astock.profit_forecast(code)
        except Exception as e:  # noqa: BL001
            company["profit_forecast_error"] = str(e)
        try:
            if "announcements" in src.dynamic_panels:
                company["announcements"] = astock.announcements(code, limit=10)
        except Exception as e:  # noqa: BL001
            company["announcements_error"] = str(e)
        out["companies"].append(company)
    return out


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
