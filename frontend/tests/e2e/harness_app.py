"""E2E-only uvicorn entry: real app routes + offline stubs for external IO.

Not a production module. Loaded only by sector-research.browser.mjs via
PYTHONPATH / --app-dir (frontend/tests/e2e). Isolated VR_DATA_DIR /
VR_REPORTS_DIR. Does not add E2E-only HTTP endpoints and never writes into
backend/ or the product workspace.
"""
from __future__ import annotations

from datetime import datetime, timezone

import app as app_module
import sector_research_data as srd

# Re-export ASGI app for uvicorn: harness_app:app
app = app_module.app

_PDF_BYTES = b"%PDF-1.4 e2e-fixture-report\n"

# Preserve production cache lookup; only ERR is forced to miss (UI expiry path).
_original_get_cached_discovery = app_module._get_cached_discovery


def _fake_discover(sector_key: str, **kwargs):
    days = kwargs.get("days")
    if days is None:
        days = 365
    scope = kwargs.get("scope") or "industry"
    suffix = f"{scope}-{days}"
    rows = [
        {
            "source_provider": "eastmoney",
            "external_id": f"OK-{suffix}",
            "info_code": f"OK-{suffix}",
            "title": f"PCB {scope} {days}天 研究",
            "institution": "中信证券",
            "publish_date": "2026-07-20",
            "industry_name": "电子",
            "company_code": "002463" if scope == "company" else None,
            "company_name": "沪电股份" if scope == "company" else None,
            "pdf_url": f"https://pdf.dfcfw.com/pdf/H3_OK-{suffix}_1.pdf",
            "report_scope": "company" if scope == "company" else "industry",
            "report_type": "brokerage",
            "matched_keywords": ["PCB"],
            "relevance_score": 21,
            "rating": "买入",
            "date_unknown": False,
        },
        {
            "source_provider": "eastmoney",
            "external_id": "ERR",
            "info_code": "ERR",
            "title": "PCB 过期缓存错误样本",
            "institution": "中信证券",
            "publish_date": "2026-07-20",
            "industry_name": "电子",
            "company_code": None,
            "company_name": None,
            "pdf_url": "https://pdf.dfcfw.com/pdf/H3_ERR_1.pdf",
            "report_scope": "industry",
            "report_type": "brokerage",
            "matched_keywords": ["PCB"],
            "relevance_score": 18,
            "rating": "买入",
            "date_unknown": False,
        },
    ]
    # Pad to exercise truncation metadata without huge payloads
    for i in range(3, 8):
        rows.append({
            "source_provider": "eastmoney",
            "external_id": f"PAD-{scope}-{i}",
            "info_code": f"PAD-{scope}-{i}",
            "title": f"PCB 填充 {i}",
            "institution": "华泰证券",
            "publish_date": "2026-07-18",
            "industry_name": "电子",
            "company_code": None,
            "company_name": None,
            "pdf_url": f"https://pdf.dfcfw.com/pdf/H3_PAD-{i}_1.pdf",
            "report_scope": "industry",
            "report_type": "brokerage",
            "matched_keywords": ["PCB"],
            "relevance_score": 10 - i,
            "rating": None,
            "date_unknown": False,
        })
    return srd.DiscoveryResult(
        source_key=sector_key,
        discovered=list(rows),
        filtered=list(rows),
        error=None,
        total_discovered=557,
        returned=len(rows),
        truncated=True,
    )


def _fake_dynamic(sector_key: str) -> dict:
    return {
        "sector_key": sector_key,
        "source": "a-stock-data",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "status": "partial",
        "warnings": ["002463 一致预期：依赖未安装"],
        "companies": [
            {
                "code": "002463",
                "name": "沪电股份",
                "panels": {
                    "individual_info": {
                        "status": "ok",
                        "summary": {
                            "name": "沪电股份",
                            "industry": "电子",
                            "market_cap": "1000亿",
                        },
                        "error": None,
                    },
                    "profit_forecast": {
                        "status": "ok",
                        "summary": {
                            "year": "2027",
                            "eps": "1.50",
                            "coverage": "15",
                            "record_count": 2,
                        },
                        "error": None,
                    },
                    "announcements": {
                        "status": "error",
                        "summary": {},
                        "error": "依赖未安装",
                    },
                },
            }
        ],
    }


def _fake_download_pdf(url: str, max_bytes: int = 25 * 1024 * 1024) -> bytes:
    if not str(url).startswith("https://pdf.dfcfw.com/"):
        raise app_module.mr.ReportError("PDF URL 未通过 SSRF 防护校验")
    return _PDF_BYTES


def _e2e_get_cached_discovery(sector_key: str, external_id: str):
    """Directed cache miss for visible ERR row only; OK-* still use real cache."""
    if external_id == "ERR":
        return None
    return _original_get_cached_discovery(sector_key, external_id)


def _fake_stock_fund_flow_120d(code: str):
    """Fixed multi-day fund-flow for chart E2E: positive, negative, zero days."""
    # Three deterministic dates shared by all codes so aggregate is stable
    return [
        {"date": "2026-07-28", "main_net": 1_000_000.0},   # positive
        {"date": "2026-07-29", "main_net": -500_000.0},    # negative
        {"date": "2026-07-30", "main_net": 0.0},           # zero
    ]


# Monkeypatch external IO before uvicorn serves traffic.
srd.discover_sector_reports = _fake_discover  # type: ignore[assignment]
srd.get_sector_dynamic_data = _fake_dynamic  # type: ignore[assignment]
app_module._download_pdf = _fake_download_pdf  # type: ignore[assignment]
app_module._get_cached_discovery = _e2e_get_cached_discovery  # type: ignore[assignment]
app_module.astock.stock_fund_flow_120d = _fake_stock_fund_flow_120d  # type: ignore[assignment]
