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
from datetime import date, datetime, timedelta, timezone

import astock

# 单次发现返回上限：必须 ≤ 服务端缓存容量，保证「可见即可导入」。
MAX_DISCOVERY_RESULTS = 300

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
    total_discovered: int = 0
    returned: int = 0
    truncated: bool = False


def _parse_publish_date(value: str | None) -> date | None:
    """解析 YYYY-MM-DD / YYYY-MM / YYYY；非法或空 → None（不伪造）。"""
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # 截取日期前缀（东财可能带时间）
    s = s[:10]
    for fmt, n in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)):
        try:
            part = s[:n]
            return datetime.strptime(part, fmt).date()
        except ValueError:
            continue
    return None


def _within_lookback(publish_date: str | None, lookback_days: int, *, today: date | None = None) -> tuple[bool, bool]:
    """返回 (keep, date_unknown)。

    合法日期：在 [today-lookback, today] 内保留；更早丢弃。
    缺失/非法：保留，date_unknown=True（不伪装为今天）。
    """
    today = today or datetime.now(timezone.utc).date()
    d = _parse_publish_date(publish_date)
    if d is None:
        return True, True
    earliest = today - timedelta(days=int(lookback_days))
    return (earliest <= d <= today), False


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
    """relevance_score desc；已知日期 publish_date desc；未知日期排后；external_id 兜底。"""
    rows.sort(key=lambda n: n.get("external_id") or "")
    rows.sort(key=lambda n: n.get("publish_date") or "", reverse=True)
    rows.sort(key=lambda n: 1 if n.get("date_unknown") else 0)  # 未知日期靠后
    rows.sort(key=lambda n: n.get("relevance_score") or 0, reverse=True)


def discover_sector_reports(
    sector_key: str,
    *,
    days: int | None = None,
    max_pages: int = 3,
    scope: str = "industry",
    max_results: int = MAX_DISCOVERY_RESULTS,
) -> DiscoveryResult:
    """发现板块研报（只返回发现结果，不自动归档）。

    scope: "industry" | "company" | "all"（由调用方校验非法值并返回 400）。
    industry / company / all 均按 days 回溯过滤 publish_date。
    排序后截断至 max_results，保证返回列表可全部写入导入缓存。
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

        normalized: list[dict] = []
        for r in raw_rows:
            n = normalize_report(r)
            keep, date_unknown = _within_lookback(n.get("publish_date"), lookback)
            if not keep:
                continue
            n["date_unknown"] = date_unknown
            n["relevance_score"] = score_report_relevance(n, keywords, company_codes)
            normalized.append(n)

        filtered = [
            n for n in normalized
            if n.get("title") and (
                n.get("matched_keywords") or n.get("company_code") in company_codes
            )
        ]
        _sort_discovered(normalized)
        _sort_discovered(filtered)

        # 展示与缓存使用同一截断列表（优先 filtered，否则 discovered）
        primary = filtered if filtered else normalized
        total = len(primary)
        limit = max(1, int(max_results)) if max_results else MAX_DISCOVERY_RESULTS
        truncated = total > limit
        primary = primary[:limit]
        # discovered 与 filtered 同步截断后的可见集
        visible_ids = {n.get("external_id") for n in primary if n.get("external_id")}
        result.discovered = primary
        result.filtered = [n for n in filtered if n.get("external_id") in visible_ids][:limit]
        if not result.filtered:
            result.filtered = list(primary)
        result.total_discovered = total
        result.returned = len(primary)
        result.truncated = truncated
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


def _panel_ok(summary: dict | None = None) -> dict:
    """仅返回受控摘要，不附带原始接口响应。"""
    return {"status": "ok", "summary": summary or {}, "error": None}


def _panel_err(exc: BaseException) -> dict:
    return {"status": "error", "summary": {}, "error": _safe_panel_error(exc)}


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


def _summarize_profit_forecast(data: list | dict | None) -> dict:
    """解析 astock.profit_forecast() 的真实 list[dict]（或偶发 dict）。

    不把列表长度伪装成机构覆盖数；字段缺失不猜测。
    """
    if data is None:
        return {"note": "无一致预期数据"}
    rows: list[dict]
    if isinstance(data, list):
        rows = [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        # 兼容偶发整包 dict
        inner = data.get("data") or data.get("list") or data.get("records")
        if isinstance(inner, list):
            rows = [r for r in inner if isinstance(r, dict)]
        else:
            rows = [data]
    else:
        return {"note": "已取得一致预期数据，暂无法结构化摘要"}

    if not rows:
        return {"note": "无一致预期数据"}

    def _year_key(row: dict) -> str:
        for k in ("年度", "预测年度", "year", "YEAR", "年份", "最新年度"):
            v = row.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
        return ""

    # 选「年度」字符串最大者（通常为最新预测年）
    best = max(rows, key=lambda r: _year_key(r))
    summary: dict = {"record_count": len(rows)}

    y = _year_key(best)
    if y:
        summary["year"] = y[:10]

    # EPS / 均值
    for k in ("均值", "预测EPS", "EPS", "eps", "预测每股收益", "基本每股收益"):
        v = best.get(k)
        if v is not None and str(v).strip() not in ("", "-", "--"):
            summary["eps"] = str(v).strip()[:50]
            summary["forecast"] = summary["eps"]
            break

    # 机构数：不得用 len(rows)
    for k in ("预测机构数", "机构数", "机构家数", "coverage", "分析师数"):
        v = best.get(k)
        if v is not None and str(v).strip() not in ("", "-", "--"):
            summary["coverage"] = str(v).strip()[:20]
            break

    # 净利润预测（可选）
    for k in ("预测净利润", "净利润", "net_profit"):
        v = best.get(k)
        if v is not None and str(v).strip() not in ("", "-", "--"):
            if "forecast" not in summary:
                summary["forecast"] = str(v).strip()[:50]
            break

    if len(summary) <= 1:  # 仅 record_count
        return {"note": "已取得一致预期数据，暂无法结构化摘要", "record_count": len(rows)}
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
                company["panels"]["individual_info"] = _panel_ok(summary)
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
                company["panels"]["profit_forecast"] = _panel_ok(summary)
                ok_panels += 1
            except Exception as e:  # noqa: BL001
                company["panels"]["profit_forecast"] = _panel_err(e)
                fail_panels += 1
                warnings.append(f"{code} 一致预期：{_safe_panel_error(e)}")
        if "announcements" in panels_enabled:
            try:
                anns = astock.announcements(code, limit=10)
                summary = _summarize_announcements(anns)
                company["panels"]["announcements"] = _panel_ok(summary)
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
