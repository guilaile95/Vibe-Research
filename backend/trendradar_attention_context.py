"""TrendRadar 单证券 Attention Context（TR1-P2）。

这是 Vibe-owned 的只读组合层：复用现有 A 股元数据 authority 与 TrendRadar
read-only console，不复制 TrendRadar 实现，也不创建投资评分、Thesis、Decision
或 Holding authority。所有输出仅表示公开信息「值得关注/研究」。
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Callable

import astock
import trendradar_console as console
import trendradar_gateway as gateway

ATTENTION_CONTEXT_AUTHORITY_REF = "vibe:trendradar_attention_context:v0.1"
USAGE_BOUNDARY = "observation_only_not_an_investment_authority"
SEARCH_TOOL = "search_news"
SEARCH_DAYS_BACK = 7
SEARCH_LIMIT = 10
MAX_SEARCH_TERMS = 5
MAX_OBSERVATION_NUMBER = 1_000_000_000
_SAFE_ERROR_SOURCE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")

STATUS_OK = "OK"
STATUS_PARTIAL = "PARTIAL"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _base_envelope(status: str, *, error: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "retrieved_at": utc_now_iso(),
        "authority_ref": ATTENTION_CONTEXT_AUTHORITY_REF,
        "usage_boundary": USAGE_BOUNDARY,
        "upstream": gateway.upstream_identity(),
    }
    if error:
        result["error"] = error
    return result


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _first_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _text(payload.get(key))
        if value:
            return value
    return None


def _safe_loader(name: str, loader: Callable[[], Any], errors: list[dict[str, str]]) -> Any:
    try:
        return loader()
    except Exception:  # noqa: BLE001 - mapping is explicitly fail-closed
        errors.append({"source": name, "error": "数据源暂不可用"})
        return None


def _entity_mapping(code: str) -> dict[str, Any]:
    """读取既有公开股票元数据，不建立第二套股票/行业 authority。"""
    errors: list[dict[str, str]] = []
    quote_payload = _safe_loader(
        "astock.tencent_quote",
        lambda: astock.tencent_quote([code]),
        errors,
    )
    quote = quote_payload.get(code) if isinstance(quote_payload, dict) else None
    company_name = _text(quote.get("name")) if isinstance(quote, dict) else None

    info_payload = _safe_loader("astock.individual_info", lambda: astock.individual_info(code), errors)
    info = info_payload if isinstance(info_payload, dict) else {}
    sector = None
    sector_source = None
    for key in ("行业", "所属行业", "行业名称", "industry", "Industry"):
        sector = _text(info.get(key))
        if sector:
            sector_source = f"astock.individual_info:{key}"
            break

    blocks_payload = _safe_loader(
        "astock.concept_blocks",
        lambda: astock.concept_blocks(code, strict=True),
        errors,
    )
    blocks = blocks_payload if isinstance(blocks_payload, dict) else {}
    block_terms: list[dict[str, str]] = []
    for item in blocks.get("boards", []) if isinstance(blocks.get("boards"), list) else []:
        if isinstance(item, dict):
            value = _first_text(item, ("name", "concept", "label"))
            if value:
                block_terms.append({"term": value, "source": "astock.concept_blocks:boards"})
    for value in blocks.get("concept_tags", []) if isinstance(blocks.get("concept_tags"), list) else []:
        text = _text(value)
        if text:
            block_terms.append({"term": text, "source": "astock.concept_blocks:concept_tags"})

    hot_payload = _safe_loader(
        "astock.hot_concepts",
        lambda: astock.hot_concepts(code, strict=True),
        errors,
    )
    hot_terms: list[dict[str, str]] = []
    for item in hot_payload if isinstance(hot_payload, list) else []:
        if isinstance(item, dict):
            value = _first_text(item, ("concept", "conceptName", "name"))
            if value:
                hot_terms.append({"term": value, "source": "astock.hot_concepts"})

    topics: list[dict[str, str]] = []
    seen_topics: set[str] = set()
    for item in [*block_terms, *hot_terms]:
        term = item["term"]
        if term not in seen_topics:
            seen_topics.add(term)
            topics.append(item)

    matched_terms: list[str] = []
    for value in (company_name, sector, *(item["term"] for item in topics)):
        if value and value not in matched_terms:
            matched_terms.append(value)
    if not matched_terms:
        matched_terms.append(code)

    reasons = [{"kind": "security_code", "value": code, "source": "user_query_exact"}]
    if company_name:
        reasons.append({"kind": "company_name", "value": company_name, "source": "astock.tencent_quote"})
    if sector:
        reasons.append({"kind": "sector", "value": sector, "source": sector_source or "astock.individual_info"})
    for topic in topics:
        reasons.append({"kind": "topic", "value": topic["term"], "source": topic["source"]})

    mapping_status = "MAPPED" if company_name or sector or topics else "EXACT_CODE_ONLY"
    return {
        "mapping_status": mapping_status,
        "code": code,
        "company_name": company_name,
        "sector": {"value": sector, "source": sector_source} if sector else None,
        "topics": topics,
        "matched_terms": matched_terms[:MAX_SEARCH_TERMS],
        "mapping_reasons": reasons,
        "mapping_errors": errors,
    }


def _context_shell(status: str, code: str, *, error: str | None = None) -> dict[str, Any]:
    result = _base_envelope(
        status,
        error=gateway.safe_public_error(status) if error else None,
    )
    result["security"] = {"code": code, "company_name": None}
    result["mapping"] = {
        "status": "EXACT_CODE_ONLY",
        "sector": None,
        "topics": [],
        "matched_terms": [code],
        "reasons": [{"kind": "security_code", "value": code, "source": "user_query_exact"}],
        "errors": [],
    }
    result["observation"] = {
        "window_days": SEARCH_DAYS_BACK,
        "window_semantics": "TrendRadar search_news date_range relative window",
        "items": [],
        "item_count": 0,
        "rank_history_semantics": "Only returned when upstream exposes rank_timeline; missing means UNKNOWN",
    }
    result["source_statuses"] = []
    return result


def _fallback_mapping(code: str, source: str = "metadata_loader") -> dict[str, Any]:
    return {
        "mapping_status": "EXACT_CODE_ONLY",
        "code": code,
        "company_name": None,
        "sector": None,
        "topics": [],
        "matched_terms": [code],
        "mapping_reasons": [{"kind": "security_code", "value": code, "source": "user_query_exact"}],
        "mapping_errors": [{"source": source, "error": "数据源暂不可用"}],
    }


def _sanitize_mapping_errors(mapping: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    raw_errors = mapping.get("mapping_errors")
    if isinstance(raw_errors, list):
        for item in raw_errors:
            if not isinstance(item, dict):
                continue
            source = item.get("source")
            safe_source = source if isinstance(source, str) and _SAFE_ERROR_SOURCE_RE.fullmatch(source) else "metadata_loader"
            errors.append({"source": safe_source, "error": "数据源暂不可用"})
    mapping["mapping_errors"] = errors
    return mapping


def _result_payload(envelope: dict[str, Any]) -> tuple[Any, str | None]:
    if "result" in envelope:
        return envelope["result"], None
    text = envelope.get("result_text")
    if not isinstance(text, str):
        return None, "MCP search result did not contain result or result_text"
    try:
        return json.loads(text), None
    except json.JSONDecodeError:
        return None, "MCP search result_text is not valid JSON"


def _rows_from_payload(payload: Any) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if _first_text(payload, ("title", "headline", "news_title")):
            return [payload]
        for key in ("items", "news", "results", "data", "list"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return None


def _finite_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or abs(number) > MAX_OBSERVATION_NUMBER:
        return None
    return int(number) if number.is_integer() else number


def _normalize_rank_timeline(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    normalized: list[dict[str, Any]] = []
    for point in value:
        if not isinstance(point, dict):
            continue
        crawl_time = _first_text(point, ("crawl_time", "timestamp", "observed_at", "time"))
        rank = _finite_number(point.get("rank"))
        if not crawl_time or rank is None:
            continue
        normalized.append({
            "crawl_time": crawl_time,
            "rank": rank,
            "off_list": rank == 0,
        })
    return normalized or None


def _normalize_row(row: dict[str, Any], term: str) -> dict[str, Any] | None:
    title = _first_text(row, ("title", "headline", "news_title", "name"))
    if not title:
        return None
    rank = _finite_number(row.get("rank"))
    normalized_timeline = _normalize_rank_timeline(row.get("rank_timeline"))
    return {
        "title": title,
        "platform": _first_text(row, ("platform", "platform_name", "source", "source_name")),
        "url": _first_text(row, ("url", "link", "mobile_url")),
        "timestamp": _first_text(row, ("timestamp", "crawl_time", "published_at", "publish_time", "date")),
        "rank": rank,
        "off_list": rank == 0 if rank is not None else None,
        "hotness_score": _finite_number(row.get("hotness_score", row.get("hotness"))),
        "first_seen": _first_text(row, ("first_seen", "first_crawl_time")),
        "last_seen": _first_text(row, ("last_seen", "last_crawl_time")),
        "crawl_count": _finite_number(row.get("crawl_count")),
        "rank_timeline": normalized_timeline,
        "matched_terms": [term],
    }


def _merge_rows(target: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    by_key = {(item.get("url") or item["title"], item.get("platform")): item for item in target}
    for row in rows:
        key = (row.get("url") or row["title"], row.get("platform"))
        existing = by_key.get(key)
        if existing is None:
            target.append(row)
            by_key[key] = row
            continue
        terms = existing.setdefault("matched_terms", [])
        for term in row.get("matched_terms", []):
            if term not in terms:
                terms.append(term)
        for field in ("timestamp", "rank", "off_list", "hotness_score", "first_seen", "last_seen", "crawl_count", "rank_timeline"):
            if existing.get(field) is None and row.get(field) is not None:
                existing[field] = row[field]


def build_attention_context(
    code: str,
    *,
    env: dict[str, str] | None = None,
    transport_factory: Callable[[gateway.GatewayConfig], Any] = gateway.default_transport_factory,
    metadata_loader: Callable[[str], dict[str, Any]] = _entity_mapping,
) -> dict[str, Any]:
    """构造单证券公开 attention projection；输入已由 router 约束为 6 位 A 股代码。"""
    config, config_error = gateway.load_config(env)
    if config_error is not None:
        return _context_shell(gateway.STATUS_CONFIG_ERROR, code, error=config_error)
    if config is None:
        result = _context_shell(gateway.STATUS_DISABLED, code, error="TrendRadar MCP URL is not configured")
        result["source_statuses"] = [{"term": code, "status": gateway.STATUS_DISABLED, "tool": SEARCH_TOOL}]
        return result

    try:
        mapping = metadata_loader(code)
    except Exception:  # noqa: BLE001 - metadata failures remain explicit and fail-closed
        mapping = _fallback_mapping(code)
    mapping = _sanitize_mapping_errors(mapping)
    terms = mapping["matched_terms"][:MAX_SEARCH_TERMS]
    source_statuses: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    upstream: dict[str, Any] | None = None

    for term in terms:
        envelope = console.call_read_tool(
            SEARCH_TOOL,
            {
                "query": term,
                "date_range": f"最近{SEARCH_DAYS_BACK}天",
                "limit": SEARCH_LIMIT,
                "include_url": True,
            },
            env=env,
            transport_factory=transport_factory,
        )
        if isinstance(envelope.get("upstream"), dict) and upstream is None:
            upstream = envelope["upstream"]
        status = envelope.get("status", gateway.STATUS_UNAVAILABLE)
        if status not in gateway.ENVELOPE_STATUSES:
            status = gateway.STATUS_UNAVAILABLE
        source: dict[str, Any] = {"term": term, "status": status, "tool": SEARCH_TOOL}
        if status != gateway.STATUS_OK:
            source["error"] = gateway.safe_public_error(status)
        if status == gateway.STATUS_OK:
            payload, payload_error = _result_payload(envelope)
            rows = _rows_from_payload(payload) if payload_error is None else None
            if rows is None:
                source["status"] = gateway.STATUS_CONTRACT_MISMATCH
                source["error"] = payload_error or "MCP search result shape is unsupported"
            else:
                normalized = []
                for row in rows:
                    item = _normalize_row(row, term)
                    if item is not None:
                        normalized.append(item)
                source["observation_count"] = len(normalized)
                _merge_rows(observations, normalized)
        source_statuses.append(source)

    statuses = [item["status"] for item in source_statuses]
    if statuses and all(status == gateway.STATUS_DISABLED for status in statuses):
        overall_status = gateway.STATUS_DISABLED
    elif statuses and any(status == gateway.STATUS_OK for status in statuses):
        overall_status = STATUS_OK if all(status == gateway.STATUS_OK for status in statuses) else STATUS_PARTIAL
    elif statuses:
        overall_status = statuses[0]
    else:
        overall_status = gateway.STATUS_UNAVAILABLE

    result = _base_envelope(overall_status)
    if upstream is not None:
        result["upstream"] = upstream
    result["security"] = {
        "code": code,
        "company_name": mapping["company_name"],
    }
    result["mapping"] = {
        "status": mapping["mapping_status"],
        "sector": mapping["sector"],
        "topics": mapping["topics"],
        "matched_terms": terms,
        "reasons": mapping["mapping_reasons"],
        "errors": mapping["mapping_errors"],
    }
    result["observation"] = {
        "window_days": SEARCH_DAYS_BACK,
        "window_semantics": "TrendRadar search_news date_range relative window",
        "items": observations,
        "item_count": len(observations),
        "rank_history_semantics": "Only returned when upstream exposes rank_timeline; missing means UNKNOWN",
    }
    result["source_statuses"] = source_statuses
    return result
