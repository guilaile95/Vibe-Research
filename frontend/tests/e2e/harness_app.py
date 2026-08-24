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


def _fake_sector_market_context(*, sector_key: str | None = None) -> dict:
    mapped = {
        "pcb": {"thscode": "884092.TI", "name": "印制电路板", "kind": "industry"},
        "humanoid": {"thscode": "886069.TI", "name": "人形机器人", "kind": "concept"},
        "cpo": {"thscode": "886033.TI", "name": "共封装光学(CPO)", "kind": "concept"},
    }

    def item(key: str, rank: int | None = None) -> dict:
        index = mapped.get(key)
        if index is None:
            return {
                "sector_key": key,
                "sector_label": key,
                "mapping_status": "unavailable",
                "index": None,
                "status": "unavailable",
                "warnings": ["未配置可核验映射"],
                "metrics": None,
                "breadth": None,
                "constituents_as_of_ms": None,
                "constituent_snapshot_as_of_ms": None,
                "rank_20d_within_mapped": None,
                "rank_change_vs_5_sessions_ago": None,
                "rank_universe_count": None,
            }
        return {
            "sector_key": key,
            "sector_label": {"pcb": "PCB（印制电路板）", "humanoid": "人形机器人", "cpo": "光互联与CPO"}[key],
            "mapping_status": "mapped",
            "index": index,
            "status": "normal",
            "warnings": [],
            "metrics": {
                "trade_date": "2026-08-24",
                "return_5d_pct": 3.21,
                "return_20d_pct": 8.76 - (rank or 1),
                "return_60d_pct": 12.34,
                "return_5d_delta_vs_previous_5d_pct": 1.11,
                "turnover_vs_prior_20d": 1.25,
                "prior_20d_return_pct": 6.5,
            },
            "breadth": ({
                "constituents_total": 47,
                "snapshot_valid_count": 47,
                "coverage_ratio": 1.0,
                "up_count": 31,
                "down_count": 15,
                "flat_count": 1,
                "up_ratio": 0.6596,
                "equal_weight_change_pct": 1.23,
                "constituents_sample": [
                    {"code": "002463", "name": "沪电股份", "change_pct": 2.5},
                    {"code": "002916", "name": "深南电路", "change_pct": -0.5},
                ],
                "constituent_semantics": "CURRENT_CONSTITUENTS_ONLY",
            } if sector_key else None),
            "constituents_as_of_ms": 1787542767000 if sector_key else None,
            "constituent_snapshot_as_of_ms": 1787542768000 if sector_key else None,
            "rank_20d_within_mapped": rank,
            "rank_change_vs_5_sessions_ago": 1 if rank else None,
            "rank_universe_count": 3 if rank else None,
        }

    items = [item(sector_key)] if sector_key else [item("pcb", 1), item("humanoid", 2), item("cpo", 3)]
    return {
        "schema_version": "sector_market_context.v0.1",
        "status": "normal" if sector_key else "partial",
        "source": "e2e-fixture",
        "fetched_at": "2026-08-24T04:00:00+00:00",
        "mapped_count": 3,
        "total_count": 20,
        "warnings": [],
        "items": items,
    }


def _fake_board_ranking(board_type: str = "industry", top_n: int = 20) -> dict:
    rows = [
        {"code": "BK1036", "name": "印制电路板", "change_pct": 3.5, "turnover_pct": 4.2, "market_cap": 1.0, "up_count": 31, "down_count": 15, "up_ratio": 0.6739, "leader": "沪电股份", "leader_change_pct": 8.0},
        {"code": "BK0475", "name": "半导体", "change_pct": 2.1, "turnover_pct": 3.1, "market_cap": 1.0, "up_count": 80, "down_count": 20, "up_ratio": 0.8, "leader": "中芯国际", "leader_change_pct": 5.0},
    ]
    return {"status": "normal", "source": "e2e-fixture", "trade_date": "2026-08-24", "data_time": None, "fetched_at": "2026-08-24 12:00:00", "is_stale": False, "warnings": [], "data": {"type": board_type, "total": 2, "ranked_count": 2, "unknown_count": 0, "top": rows[:top_n], "bottom": list(reversed(rows))[:top_n]}}


def _fake_download_pdf(url: str, max_bytes: int = 25 * 1024 * 1024) -> bytes:
    if not str(url).startswith("https://pdf.dfcfw.com/"):
        raise app_module.mr.ReportError("PDF URL 未通过 SSRF 防护校验")
    return _PDF_BYTES


def _e2e_get_cached_discovery(sector_key: str, external_id: str):
    """Directed cache miss for visible ERR row only; OK-* still use real cache."""
    if external_id == "ERR":
        return None
    return _original_get_cached_discovery(sector_key, external_id)


# Monkeypatch external IO before uvicorn serves traffic.
srd.discover_sector_reports = _fake_discover  # type: ignore[assignment]
srd.get_sector_dynamic_data = _fake_dynamic  # type: ignore[assignment]
app_module.smc.build_sector_market_context = _fake_sector_market_context  # type: ignore[assignment]
app_module.market.get_board_ranking = _fake_board_ranking  # type: ignore[assignment]
app_module._download_pdf = _fake_download_pdf  # type: ignore[assignment]
app_module._get_cached_discovery = _e2e_get_cached_discovery  # type: ignore[assignment]
