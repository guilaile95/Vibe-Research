"""Native Intel 服务层（NATIVE-INTEL1）：抓取编排 / 去重 / 实体映射 / 趋势 / 上下文。

设计约束：
- 复用 Vibe 自有的 ``newsradar`` 抓取与归一化实现，不引入新爬虫框架。
- 单源失败隔离：一个源失败不拖垮其他源，失败写入 source_run 并诚实上报。
- 排名不伪造：RSS 源没有真实排名，``rank`` 恒为 None，读取侧报告 UNKNOWN。
- AI 只做增强：本模块不依赖任何 AI 能力，AI 不可用不影响资讯主链路。
- astock 元数据全部 fail-closed：取不到就显式标注，不补默认值。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable

import native_intel_store as store

# 复用 Vibe 自有的 MIT newsradar 实现
import newsradar

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(HERE, "news_sources.json")

AUTHORITY_REF = "vibe:native_intel:v0.1"
USAGE_BOUNDARY = "observation_only_not_an_investment_authority"

BEIJING = timezone(timedelta(hours=8))

# 状态语义（页面按此渲染，不猜）
STATUS_NORMAL = "normal"
STATUS_PARTIAL = "partial"
STATUS_STALE = "stale"
STATUS_UNAVAILABLE = "unavailable"

FETCH_TIMEOUT = 15
FETCH_WORKERS = 32
STALE_AFTER_HOURS = 6
DIRECTORY_MAX_AGE_HOURS = 24
TERMS_MAX_AGE_HOURS = 12
BACKFILL_WINDOW_DAYS = 7
BACKFILL_MAX_ITEMS = 6000

# 实体词最短匹配长度：中文没有词边界，过短的通用词会造成大量误命中
MIN_TERM_LEN = {
    store.TERM_SECURITY_CODE: 6,
    store.TERM_COMPANY_NAME: 3,
    store.TERM_INDUSTRY: 2,
    store.TERM_CONCEPT: 2,
}

_FETCH_LOCK = threading.Lock()
_SCHEDULER_LOCK = threading.Lock()
_SCHEDULER_STARTED = False

_ENV_DB = "VIBE_NATIVE_INTEL_DB"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def db_path() -> str:
    return os.environ.get(_ENV_DB, "").strip() or str(store.get_default_db_path())


# ---------------------------------------------------------------------------
# source registry
# ---------------------------------------------------------------------------


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-") or "src"


def load_registry() -> dict[str, Any]:
    with open(SOURCES_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in cfg.get("sources", []):
        name = str(raw.get("name") or "").strip()
        url = str(raw.get("url") or "").strip()
        hint = str(raw.get("hint") or "").strip()
        if not name or not url:
            continue
        source_id = f"{hint or 'misc'}-{_slug(name)}"
        if source_id in seen:
            source_id = f"{source_id}-{len(seen)}"
        seen.add(source_id)
        sources.append(
            {
                "source_id": source_id,
                "name": name,
                "hint": hint,
                "url": url,
                "source_type": str(raw.get("type") or "rss").strip(),
                # RSS 没有真实排名；只有明确声明排名的来源才写 rank
                "has_real_rank": bool(raw.get("has_real_rank")),
            }
        )
    fingerprint = hashlib.sha256(
        json.dumps(
            [[s["source_id"], s["url"]] for s in sources], sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "sources": sources,
        "config": cfg,
        "registry_version": fingerprint,
        "industries": cfg.get("industries", []),
        "redline": [str(k).lower() for k in cfg.get("redline_keywords", [])],
        "recent_days": int((cfg.get("fetch") or {}).get("recent_days", 7)),
        "per_source": int((cfg.get("fetch") or {}).get("per_source", 6)),
    }


def sync_registry(path: str | None = None) -> int:
    registry = load_registry()
    count = store.upsert_sources(registry["sources"], path or db_path())
    store.set_meta("registry_version", registry["registry_version"], path or db_path())
    store.set_meta("registry_synced_at", utc_now_iso(), path or db_path())
    return count


# ---------------------------------------------------------------------------
# 抓取（单源隔离 + 结构化失败）
# ---------------------------------------------------------------------------


def _classify_error(exc: BaseException) -> tuple[str, str]:
    """把异常归类为安全的 error_kind；detail 只取类名，绝不携带 URL / 消息正文。"""
    name = type(exc).__name__
    if isinstance(exc, socket.timeout) or isinstance(exc, TimeoutError):
        return store.ERROR_KIND_TIMEOUT, name
    if isinstance(exc, urllib.error.HTTPError):
        return store.ERROR_KIND_HTTP, name
    if isinstance(exc, (urllib.error.URLError, socket.gaierror, OSError)):
        return store.ERROR_KIND_NETWORK, name
    if isinstance(exc, ET.ParseError):
        return store.ERROR_KIND_PARSE, name
    return store.ERROR_KIND_UNKNOWN, name


def _fetch_source_items(
    source: dict[str, Any],
    *,
    per: int,
    cutoff: datetime | None,
    redline: list[str],
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """抓单个源；返回 ``(items, error_kind, error_detail)``。

    与 ``newsradar._fetch_source`` 的区别：失败时保留结构化错误类别而不是返回 None，
    这样「源失败」永远不会退化成「该源没有数据」。
    """
    try:
        req = urllib.request.Request(
            source["url"],
            headers={
                "User-Agent": newsradar.UA,
                "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml,*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
    except Exception as exc:  # noqa: BLE001 - 单源失败必须被隔离，不能向上冒泡
        kind, detail = _classify_error(exc)
        return [], kind, detail

    items: list[dict[str, Any]] = []
    try:
        for node in root.iter():
            if newsradar._local(node.tag) not in ("item", "entry"):
                continue
            if len(items) >= per:
                break
            title = ""
            url = ""
            summary = ""
            raw_time = ""
            for child in node:
                tag = newsradar._local(child.tag)
                text = (child.text or "").strip()
                if tag == "title" and not title:
                    title = text
                elif tag == "link" and not url:
                    url = child.get("href") or text
                elif tag in ("pubDate", "published", "updated", "date") and not raw_time:
                    raw_time = text
                elif tag in ("description", "summary", "content") and not summary:
                    summary = newsradar._strip_html(text)[:300]
            if not title:
                continue
            blob = (title + " " + summary).lower()
            if any(keyword in blob for keyword in redline):
                continue

            published_at: str | None = None
            published_ts = 0
            parsed = newsradar._parse_dt(raw_time)
            if parsed is not None:
                if cutoff and parsed < cutoff:
                    continue
                published_at = parsed.astimezone(BEIJING).isoformat()
                published_ts = int(parsed.timestamp())
            # 来源未声明发布时间时 published_at 保持 None —— 绝不用抓取时间顶替

            canonical_url = newsradar._normalize_url(url)
            item_key = canonical_url or f"title:{newsradar._normalize_title(title)}"
            items.append(
                {
                    "item_key": item_key,
                    "canonical_url": canonical_url or url,
                    "url": url or canonical_url,
                    "title": title,
                    "title_key": newsradar._normalize_title(title),
                    "summary": summary,
                    "hint": source["hint"],
                    "published_at": published_at,
                    "published_ts": published_ts,
                    "rank": None,
                }
            )
    except Exception as exc:  # noqa: BLE001 - 解析失败同样要隔离单源
        kind, detail = _classify_error(exc)
        return [], kind, detail

    return items, None, None


def _dedupe_within_source(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一次抓取内去重：优先按 URL，标题归一 + 发布时间相近视为转载。

    与 newsradar._dedup 保持同一保守策略：宁可多显示一条，也不静默丢文章。
    """
    seen_keys: set[str] = set()
    seen_titles: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for item in items:
        key = item["item_key"]
        title_key = item["title_key"]
        ts = item["published_ts"]
        dup_by_key = key in seen_keys
        prev_ts = seen_titles.get(title_key) if title_key else None
        dup_by_title = (
            prev_ts is not None and bool(ts) and bool(prev_ts)
            and abs(prev_ts - ts) <= newsradar._DUP_TITLE_WINDOW_S
        )
        if dup_by_key or dup_by_title:
            continue
        seen_keys.add(key)
        if title_key and ts:
            seen_titles[title_key] = ts
        out.append(item)
    return out


def run_fetch(
    trigger: str = "manual",
    path: str | None = None,
    *,
    registry: dict[str, Any] | None = None,
    sources_override: list[dict[str, Any]] | None = None,
    fetcher: Callable[..., tuple[list[dict[str, Any]], str | None, str | None]] | None = None,
) -> dict[str, Any]:
    """执行一次全量抓取；已加锁防并发，返回结构化 run 结果。

    ``sources_override`` / ``fetcher`` 供测试注入失败源，生产路径不传。
    """
    target = path or db_path()
    reg = registry or load_registry()
    store.initialize_store(target)
    store.upsert_sources(reg["sources"], target)

    sources = sources_override if sources_override is not None else reg["sources"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=reg["recent_days"])
    redline = reg["redline"]
    do_fetch = fetcher or _fetch_source_items

    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{os.getpid()}-{uuid4_short()}"
    observed_at = utc_now_iso()

    with _FETCH_LOCK:
        store.start_run(run_id, trigger, len(sources), target)

        def task(source: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], str | None, str | None, int]:
            started = time.monotonic()
            items, kind, detail = do_fetch(
                source, per=reg["per_source"], cutoff=cutoff, redline=redline
            )
            return source, items, kind, detail, int((time.monotonic() - started) * 1000)

        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            outcomes = list(pool.map(task, sources))

        source_ok = 0
        source_failed = 0
        item_seen = 0
        item_new = 0
        new_item_ids: list[int] = []
        touched_item_ids: list[int] = []
        failed_names: list[str] = []

        for source, items, kind, detail, duration in outcomes:
            if kind is not None:
                source_failed += 1
                failed_names.append(source.get("name") or source.get("source_id"))
                store.record_source_run(
                    run_id,
                    source["source_id"],
                    status=store.SOURCE_RUN_FAILED,
                    error_kind=kind,
                    error_detail=detail,
                    duration_ms=duration,
                    db_path=target,
                )
                continue

            deduped = _dedupe_within_source(items)
            count = 0
            for item in deduped:
                item_id, is_new = store.upsert_observation(
                    run_id,
                    source["source_id"],
                    item,
                    observed_at=observed_at,
                    has_real_rank=bool(source.get("has_real_rank")),
                    db_path=target,
                )
                count += 1
                item_seen += 1
                touched_item_ids.append(item_id)
                if is_new:
                    item_new += 1
                    new_item_ids.append(item_id)
            if count:
                source_ok += 1
            else:
                # 真实空结果（源可达但窗口内无新条目）—— 与失败是两种状态
                source_ok += 1
            store.record_source_run(
                run_id,
                source["source_id"],
                status=store.SOURCE_RUN_EMPTY if count == 0 else store.SOURCE_RUN_OK,
                item_count=count,
                duration_ms=duration,
                db_path=target,
            )

        # 只对本次新增条目做实体映射；已有条目在首次入库时已映射，
        # 新登记实体词通过 backfill 回补，避免每个调度周期全量重扫。
        link_entities_for_items(new_item_ids, path=target)

        if source_failed == 0:
            status = store.RUN_STATUS_OK
        elif source_ok > 0:
            status = store.RUN_STATUS_PARTIAL
        else:
            status = store.RUN_STATUS_FAILED
        note = None
        if failed_names:
            preview = ", ".join(failed_names[:8])
            note = f"failed_sources={len(failed_names)}: {preview}"
        store.finish_run(
            run_id,
            status=status,
            source_ok=source_ok,
            source_failed=source_failed,
            item_seen=item_seen,
            item_new=item_new,
            note=note,
            db_path=target,
        )

    return {
        "run_id": run_id,
        "status": status,
        "trigger": trigger,
        "observed_at": observed_at,
        "source_total": len(sources),
        "source_ok": source_ok,
        "source_failed": source_failed,
        "item_seen": item_seen,
        "item_new": item_new,
        "failed_sources": failed_names,
    }


def uuid4_short() -> str:
    import uuid

    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# 实体目录与映射
# ---------------------------------------------------------------------------


def ensure_directory(
    path: str | None = None,
    *,
    force: bool = False,
    loader: Callable[[], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """惰性刷新全市场代码→名称目录；失败不覆盖已有目录，并显式上报。"""
    target = path or db_path()
    store.initialize_store(target)
    size = store.get_security_directory_size(target)
    synced_at = store.get_meta("directory_synced_at", target)
    fresh = False
    if synced_at:
        try:
            parsed = datetime.fromisoformat(synced_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - parsed < timedelta(hours=DIRECTORY_MAX_AGE_HOURS):
                fresh = True
        except ValueError:
            fresh = False

    if force or not fresh or size == 0:
        try:
            if loader is None:
                import astock

                loader = astock.a_share_snapshot
            rows = loader() or []
            if rows:
                size = store.upsert_security_directory(
                    [
                        {
                            "code": r.get("code"),
                            "name": _normalize_security_name(r.get("name")),
                            "industry": r.get("industry"),
                        }
                        for r in rows
                    ],
                    target,
                )
                store.set_meta("directory_synced_at", utc_now_iso(), target)
                fresh = True
        except Exception:  # noqa: BLE001 - 目录刷新失败不能中断资讯主链路
            pass

    current = store.get_security_directory_size(target)
    if current == 0:
        return {
            "status": STATUS_UNAVAILABLE,
            "size": 0,
            "synced_at": store.get_meta("directory_synced_at", target),
            "note": "A 股代码目录不可用；代码→名称解析将回退到单只行情查询",
        }
    return {
        "status": STATUS_NORMAL if fresh else STATUS_STALE,
        "size": current,
        "synced_at": store.get_meta("directory_synced_at", target),
        "note": None,
    }


def resolve_security_name(code: str, path: str | None = None) -> tuple[str | None, str]:
    """代码 → 名称；目录优先，回退单只行情查询，两者都失败返回 (None, reason)。"""
    target = path or db_path()
    name = store.get_security_name(code, target)
    if name:
        return name, "native_intel.directory"
    try:
        import astock

        payload = astock.tencent_quote([code]) or {}
        quote = payload.get(code) if isinstance(payload, dict) else None
        candidate = _normalize_security_name(quote.get("name")) if isinstance(quote, dict) else None
        if candidate:
            store.upsert_security_directory([{"code": code, "name": candidate}], target)
            return str(candidate), "astock.tencent_quote"
    except Exception:  # noqa: BLE001
        pass
    return None, "unresolved"


def _normalize_security_name(value: Any) -> str:
    """A-share short names have no meaningful internal spaces; quote feeds sometimes pad them."""
    return "".join(str(value or "").split())


def _refresh_security_profile(code: str, path: str) -> dict[str, Any]:
    """Cache one security's name/industry; never require a full-market directory fetch."""
    existing_name = store.get_security_name(code, path)
    existing_industry = store.get_security_industry(code, path)
    if existing_name and existing_industry:
        return {"status": STATUS_NORMAL, "error": None}
    try:
        import astock

        profile = astock.security_profile(code, strict=True)
        name = _normalize_security_name(profile.get("name"))
        if not name:
            raise ValueError("security profile missing name")
        store.upsert_security_directory(
            [{"code": code, "name": name, "industry": profile.get("industry")}], path
        )
        return {"status": STATUS_NORMAL, "error": None}
    except Exception:  # noqa: BLE001 - profile 失败后仍允许名称/概念独立降级
        return {"status": STATUS_UNAVAILABLE, "error": "A 股证券资料暂不可用"}


def _astock_terms(
    code: str,
    path: str | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """取某证券的行业 / 概念词；每个数据源独立 fail-closed，失败单独记录。"""
    import astock

    terms: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    def _safe(label: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception:  # noqa: BLE001
            errors.append({"source": label, "error": "数据源暂不可用"})
            return None

    industry = store.get_security_industry(code, path or db_path())
    industry_source = "native_intel.directory"
    if not industry:
        industry_source = "astock.individual_info"
        info = _safe("astock.individual_info", lambda: astock.individual_info(code))
        if isinstance(info, dict):
            for key in ("行业", "所属行业", "行业名称", "industry", "Industry"):
                value = info.get(key)
                if isinstance(value, str) and value.strip():
                    industry = value.strip()
                    break
    if industry:
        terms.append(
            {"term": industry, "term_kind": store.TERM_INDUSTRY, "source_ref": industry_source}
        )

    blocks = _safe("astock.concept_blocks", lambda: astock.concept_blocks(code, strict=True))
    if isinstance(blocks, dict):
        for item in blocks.get("boards") or []:
            if isinstance(item, dict):
                value = str(item.get("name") or "").strip()
                if value:
                    terms.append(
                        {"term": value, "term_kind": store.TERM_CONCEPT, "source_ref": "astock.concept_blocks"}
                    )

    hot = _safe("astock.hot_concepts", lambda: astock.hot_concepts(code, strict=True))
    for item in hot if isinstance(hot, list) else []:
        if isinstance(item, dict):
            for key in ("concept", "conceptName", "name"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    terms.append(
                        {
                            "term": value.strip(),
                            "term_kind": store.TERM_CONCEPT,
                            "source_ref": "astock.hot_concepts",
                        }
                    )
                    break
    return terms, errors


def ensure_security_terms(
    code: str,
    path: str | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """确保某证券的实体词已登记（代码 / 公司名 / 行业 / 概念），并回补历史条目。

    astock 元数据全部 fail-closed：取不到就记录 errors，不补默认值。
    """
    target = path or db_path()
    store.initialize_store(target)
    profile_status = _refresh_security_profile(code, target)
    existing = store.list_entity_terms(target, security_code=code)
    mapped_at = store.get_meta(f"terms_mapped_at:{code}", target)
    fresh = False
    if mapped_at and not force:
        try:
            parsed = datetime.fromisoformat(mapped_at.replace("Z", "+00:00"))
            fresh = datetime.now(timezone.utc) - parsed < timedelta(hours=TERMS_MAX_AGE_HOURS)
        except ValueError:
            fresh = False

    link_version_key = f"entity_links_backfilled:{code}"
    links_current = store.get_meta(link_version_key, target) == "v2"
    if existing and fresh and links_current:
        return {"code": code, "refreshed": False, "term_count": len(existing), "errors": []}

    if existing and fresh:
        backfilled = backfill_entities_for_terms(code, target)
        store.set_meta(link_version_key, "v2", target)
        return {
            "code": code,
            "refreshed": False,
            "term_count": len(existing),
            "backfilled": backfilled,
            "errors": [] if profile_status["status"] != STATUS_UNAVAILABLE else [
                {"source": "astock.security_profile", "error": profile_status["error"]}
            ],
        }

    company_name, name_source = resolve_security_name(code, target)
    terms: list[dict[str, str]] = [
        {"term": code, "term_kind": store.TERM_SECURITY_CODE, "source_ref": "user_query_exact"}
    ]
    if company_name:
        terms.append(
            {"term": company_name, "term_kind": store.TERM_COMPANY_NAME, "source_ref": name_source}
        )
    extra, errors = _astock_terms(code, target)
    if profile_status["status"] == STATUS_UNAVAILABLE:
        errors.append({"source": "astock.security_profile", "error": profile_status["error"]})
    seen: set[tuple[str, str]] = {(t["term"], t["term_kind"]) for t in terms}
    for term in extra:
        key = (term["term"], term["term_kind"])
        if key not in seen:
            seen.add(key)
            terms.append(term)

    if not company_name:
        errors.append({"source": name_source, "error": "代码→名称解析不可用"})

    store.replace_entity_terms(code, terms, target)
    store.set_meta(f"terms_mapped_at:{code}", utc_now_iso(), target)
    backfilled = backfill_entities_for_terms(code, target)
    store.set_meta(link_version_key, "v2", target)
    return {
        "code": code,
        "refreshed": True,
        "term_count": len(terms),
        "backfilled": backfilled,
        "errors": errors,
    }


def _match_terms(text: str, terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """在文本里匹配实体词；按 MIN_TERM_LEN 控制最短匹配长度以抑制误命中。"""
    if not text:
        return []
    haystack = text.lower()
    matches: list[dict[str, Any]] = []
    for term in terms:
        value = str(term.get("term") or "")
        kind = term.get("term_kind")
        if not value or kind not in store.TERM_KINDS:
            continue
        if len(value) < MIN_TERM_LEN.get(kind, 2):
            continue
        if kind == store.TERM_SECURITY_CODE:
            # 代码必须独立成词：前后不接数字，避免命中金额 / 日期里的六位数字
            if not re.search(r"(?<!\d)" + re.escape(value) + r"(?!\d)", text):
                continue
        elif value.isascii():
            if not re.search(
                r"(?<![A-Za-z0-9])" + re.escape(value) + r"(?![A-Za-z0-9])",
                text,
                flags=re.IGNORECASE,
            ):
                continue
        elif value.lower() not in haystack:
            continue
        matches.append(
            {
                "term_kind": kind,
                "term": value,
                "security_code": term.get("security_code"),
            }
        )
    return matches


def link_entities_for_items(
    item_ids: list[int],
    path: str | None = None,
) -> int:
    """给指定条目做实体映射并写入关联；返回写入的关联条数。"""
    target = path or db_path()
    if not item_ids:
        return 0
    terms = store.list_entity_terms(target)
    if not terms:
        return 0
    written = 0
    for item_id in item_ids:
        item = _load_item(item_id, target)
        if not item:
            continue
        title = item.get("title") or ""
        summary = item.get("summary") or ""
        title_matches = _match_terms(title, terms)
        summary_matches = _match_terms(summary, terms)
        merged: dict[tuple[str, str, str | None], dict[str, Any]] = {}
        for match in title_matches:
            match = dict(match, matched_in="title")
            merged[(match["term_kind"], match["term"], match.get("security_code"))] = match
        for match in summary_matches:
            key = (match["term_kind"], match["term"], match.get("security_code"))
            if key not in merged:
                merged[key] = dict(match, matched_in="summary")
        if merged:
            store.link_item_entities(item_id, list(merged.values()), target)
            written += len(merged)
    return written


def _load_item(item_id: int, path: str) -> dict[str, Any] | None:
    import sqlite3

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM intel_items WHERE item_id = ?", (item_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def backfill_entities_for_terms(code: str, path: str | None = None) -> int:
    """新登记实体词后，回补近 BACKFILL_WINDOW_DAYS 天历史条目，保证首次查询即有结果。"""
    target = path or db_path()
    since = (datetime.now(timezone.utc) - timedelta(days=BACKFILL_WINDOW_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    item_ids: list[int] = []
    offset = 0
    while len(item_ids) < BACKFILL_MAX_ITEMS:
        page_size = min(500, BACKFILL_MAX_ITEMS - len(item_ids))
        rows, total = store.query_items(
            target, since=since, limit=page_size, offset=offset
        )
        if not rows:
            break
        item_ids.extend(int(row["item_id"]) for row in rows)
        offset += len(rows)
        if offset >= total:
            break
    return link_entities_for_items(item_ids, target)


# ---------------------------------------------------------------------------
# 趋势
# ---------------------------------------------------------------------------


def _iso_hours_ago(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def data_status(path: str | None = None) -> dict[str, Any]:
    """Return the honest data-plane status without triggering directory/network work."""
    target = path or db_path()
    try:
        store.initialize_store(target)
        latest = store.get_latest_run(target)
        item_count = store.count_items(target)
    except store.NativeIntelStoreError as exc:
        return {"status": STATUS_UNAVAILABLE, "error": str(exc), "last_run": None, "item_count": 0}

    if latest is None:
        surface = STATUS_STALE if item_count else STATUS_UNAVAILABLE
    elif latest["status"] == store.RUN_STATUS_OK:
        surface = STATUS_NORMAL
    elif latest["status"] == store.RUN_STATUS_PARTIAL:
        surface = STATUS_PARTIAL
    else:
        surface = STATUS_STALE if item_count else STATUS_UNAVAILABLE

    if latest and surface in (STATUS_NORMAL, STATUS_PARTIAL):
        try:
            started = datetime.fromisoformat(str(latest["started_at"]).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - started > timedelta(hours=STALE_AFTER_HOURS):
                surface = STATUS_STALE
        except ValueError:
            surface = STATUS_STALE
    return {"status": surface, "error": None, "last_run": latest, "item_count": item_count}


def trending(
    path: str | None = None,
    *,
    window_hours: int = 24,
    top_n: int = 20,
) -> dict[str, Any]:
    """关注度趋势：跨来源出现次数 + 实体词热度与环比变化。

    排名语义：RSS 源没有真实排名，因此这里的热度只由「跨来源出现次数 / 条目数 /
    环比变化」构成，绝不补一个不存在的位置序号。
    """
    target = path or db_path()
    since = _iso_hours_ago(window_hours)
    prev_since = _iso_hours_ago(window_hours * 2)

    try:
        plane = data_status(target)
        if plane["status"] == STATUS_UNAVAILABLE:
            return {
                "status": STATUS_UNAVAILABLE,
                "error": plane["error"] or "Native Intel 尚无可用抓取数据",
                "authority_ref": AUTHORITY_REF,
                "usage_boundary": USAGE_BOUNDARY,
                "generated_at": utc_now_iso(),
                "window_hours": window_hours,
                "item_count": 0,
                "items": [],
                "entities": [],
                "rank_history": {"available": False, "reason": "registry_sources_have_no_real_rank"},
            }
        current_rows, _ = store.query_items(target, since=since, limit=500, order_by="last_seen")
        prev_rows, _ = store.query_items(
            target, since=prev_since, until=since, limit=500, order_by="last_seen"
        )
        entity_rows = _entity_trend_rows(target, since, prev_since)
        status = str(plane["status"])
        error = None
    except store.NativeIntelStoreError as exc:
        current_rows, prev_rows, entity_rows = [], [], []
        status = STATUS_UNAVAILABLE
        error = str(exc)

    prev_titles = {r["title_key"] for r in prev_rows}
    items: list[dict[str, Any]] = []
    for row in current_rows:
        items.append(
            {
                **row,
                "is_new_in_window": row["title_key"] not in prev_titles,
                "rank": None,
                "rank_history": [],
            }
        )
    items.sort(
        key=lambda r: (
            -int(bool(r["is_new_in_window"])),
            -int(r["observation_count"] or 0),
            r["last_seen_at"],
        )
    )

    return {
        "status": status,
        "error": error,
        "authority_ref": AUTHORITY_REF,
        "usage_boundary": USAGE_BOUNDARY,
        "generated_at": utc_now_iso(),
        "window_hours": window_hours,
        "item_count": len(items),
        "items": items[: max(1, min(int(top_n), 100))],
        "entities": entity_rows[: max(1, min(int(top_n), 100))],
        "rank_history": {
            "available": False,
            "reason": "registry_sources_have_no_real_rank",
            "semantics": "RSS 源不提供真实排名；此处热度只统计跨来源出现次数与环比变化，不补序号",
        },
    }


def _entity_trend_rows(target: str, since: str, prev_since: str) -> list[dict[str, Any]]:
    import sqlite3

    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    try:
        current = conn.execute(
            """
            SELECT e.term AS term, e.term_kind AS term_kind, e.security_code AS security_code,
                   COUNT(DISTINCT ie.item_id) AS item_count,
                   COUNT(DISTINCT o.source_id) AS source_count,
                   MIN(i.first_seen_at) AS first_seen_at,
                   MAX(i.last_seen_at) AS last_seen_at
            FROM intel_item_entities ie
            JOIN intel_entity_terms e
              ON e.term = ie.term AND e.term_kind = ie.term_kind
             AND IFNULL(e.security_code, '') = IFNULL(ie.security_code, '')
            JOIN intel_items i ON i.item_id = ie.item_id
            JOIN intel_observations o ON o.item_id = i.item_id
            WHERE i.last_seen_at >= ?
            GROUP BY e.term, e.term_kind, e.security_code
            """,
            (since,),
        ).fetchall()
        previous = conn.execute(
            """
            SELECT ie.term AS term, ie.term_kind AS term_kind,
                   COUNT(DISTINCT ie.item_id) AS item_count
            FROM intel_item_entities ie
            JOIN intel_items i ON i.item_id = ie.item_id
            WHERE i.last_seen_at >= ? AND i.last_seen_at < ?
            GROUP BY ie.term, ie.term_kind
            """,
            (prev_since, since),
        ).fetchall()
    finally:
        conn.close()

    prev_map = {(r["term"], r["term_kind"]): int(r["item_count"] or 0) for r in previous}
    rows: list[dict[str, Any]] = []
    for row in current:
        term = row["term"]
        kind = row["term_kind"]
        count = int(row["item_count"] or 0)
        prev = prev_map.get((term, kind), 0)
        rows.append(
            {
                "term": term,
                "term_kind": kind,
                "security_code": row["security_code"],
                "item_count": count,
                "source_count": int(row["source_count"] or 0),
                "previous_item_count": prev,
                "delta": count - prev,
                "first_seen_at": row["first_seen_at"],
                "last_seen_at": row["last_seen_at"],
            }
        )
    rows.sort(key=lambda r: (-r["delta"], -r["item_count"], -r["source_count"]))
    return rows


# ---------------------------------------------------------------------------
# 上下文：单证券 / Watchlist
# ---------------------------------------------------------------------------


def security_context(
    code: str,
    path: str | None = None,
    *,
    window_hours: int = 24 * 7,
    limit: int = 30,
) -> dict[str, Any]:
    """单证券的 Native Intel 上下文；只读观察，不进入投资权威链。"""
    target = path or db_path()
    result: dict[str, Any] = {
        "status": STATUS_NORMAL,
        "authority_ref": AUTHORITY_REF,
        "usage_boundary": USAGE_BOUNDARY,
        "retrieved_at": utc_now_iso(),
        "window_hours": window_hours,
    }
    try:
        store.initialize_store(target)
    except store.NativeIntelStoreError as exc:
        return {
            **result,
            "status": STATUS_UNAVAILABLE,
            "error": str(exc),
            "security": {"code": code, "company_name": None},
            "mapping": {"status": "UNAVAILABLE", "terms": [], "errors": []},
            "observation": {"items": [], "item_count": 0},
            "source_statuses": [],
        }

    mapping_info = ensure_security_terms(code, target)
    plane = data_status(target)
    name, _ = resolve_security_name(code, target)
    terms = store.list_entity_terms(target, security_code=code)

    items = store.query_items_by_security(code, target, limit=limit, window_hours=window_hours)
    stats = store.get_security_mention_stats([code], target, window_hours=window_hours).get(
        code,
        {"mention_count": 0, "source_count": 0, "first_seen_at": None, "last_seen_at": None},
    )

    enriched: list[dict[str, Any]] = []
    for item in items:
        enriched.append(
            {
                **item,
                "rank": None,
                "rank_history": store.get_item_rank_history(int(item["item_id"]), target),
            }
        )

    mapping_status = "MAPPED" if name or len(terms) > 1 else "EXACT_CODE_ONLY"

    context_status = str(plane["status"])
    if context_status == STATUS_NORMAL and mapping_info.get("errors"):
        context_status = STATUS_PARTIAL

    return {
        **result,
        "status": context_status,
        "error": plane.get("error"),
        "security": {"code": code, "company_name": name},
        "mapping": {
            "status": mapping_status,
            "term_count": len(terms),
            "terms": [
                {"term": t["term"], "term_kind": t["term_kind"], "source_ref": t["source_ref"]}
                for t in terms
            ],
            "errors": mapping_info.get("errors", []),
            "refreshed": mapping_info.get("refreshed", False),
        },
        "observation": {
            "items": enriched,
            "item_count": len(enriched),
            "mention_count": int(stats.get("mention_count") or 0),
            "source_count": int(stats.get("source_count") or 0),
            "first_seen_at": stats.get("first_seen_at"),
            "last_seen_at": stats.get("last_seen_at"),
        },
        "rank_history": {
            "available": False,
            "reason": "registry_sources_have_no_real_rank",
            "semantics": "RSS 源不提供真实排名；rank 与 rank_history 保持为空，不补 0",
        },
    }


def watchlist_context(
    path: str | None = None,
    *,
    window_hours: int = 24 * 7,
    per_code_limit: int = 8,
) -> dict[str, Any]:
    """Watchlist 权威列表的批量资讯上下文；Watchlist 本身仍由 watchlist_store 独占。"""
    target = path or db_path()
    result: dict[str, Any] = {
        "status": STATUS_NORMAL,
        "authority_ref": AUTHORITY_REF,
        "usage_boundary": USAGE_BOUNDARY,
        "retrieved_at": utc_now_iso(),
        "window_hours": window_hours,
    }
    try:
        store.initialize_store(target)
    except store.NativeIntelStoreError as exc:
        return {
            **result,
            "status": STATUS_UNAVAILABLE,
            "error": str(exc),
            "watchlist_status": "unavailable",
            "codes": [],
            "securities": [],
        }

    import watchlist_store

    try:
        wl_status = watchlist_store.get_watchlist_status()
    except Exception:  # noqa: BLE001
        wl_status = {"status": "unavailable", "data": {"codes": []}}
    codes: list[str] = []
    if isinstance(wl_status, dict) and wl_status.get("status") == "valid":
        data = wl_status.get("data") or {}
        codes = [str(c) for c in (data.get("codes") or [])]

    if not codes:
        return {
            **result,
            "watchlist_status": str(wl_status.get("status", "unavailable")),
            "codes": [],
            "securities": [],
            "note": "自选股为空或不可用，无聚合上下文",
        }

    plane = data_status(target)
    mapping_by_code: dict[str, dict[str, Any]] = {}
    for code in codes:
        try:
            mapping_by_code[code] = ensure_security_terms(code, target)
        except Exception as exc:  # noqa: BLE001 - 单只映射失败不拖垮整批
            mapping_by_code[code] = {"errors": [{"source": "mapping", "error": type(exc).__name__}]}

    stats = store.get_security_mention_stats(codes, target, window_hours=window_hours)
    securities: list[dict[str, Any]] = []
    degraded: list[dict[str, str]] = []
    for code in codes:
        try:
            mapping_info = mapping_by_code[code]
            if mapping_info.get("errors"):
                degraded.append({"code": code, "error": "mapping_partial"})
            name, _ = resolve_security_name(code, target)
            items = store.query_items_by_security(
                code, target, limit=per_code_limit, window_hours=window_hours
            )
            stat = stats.get(
                code,
                {
                    "mention_count": 0,
                    "source_count": 0,
                    "first_seen_at": None,
                    "last_seen_at": None,
                },
            )
            securities.append(
                {
                    "code": code,
                    "company_name": name,
                    "mention_count": int(stat.get("mention_count") or 0),
                    "source_count": int(stat.get("source_count") or 0),
                    "first_seen_at": stat.get("first_seen_at"),
                    "last_seen_at": stat.get("last_seen_at"),
                    "items": [
                        {
                            "item_id": i["item_id"],
                            "title": i["title"],
                            "url": i["url"],
                            "source_name": i.get("source_name"),
                            "hint": i["hint"],
                            "published_at": i["published_at"],
                            "first_seen_at": i["first_seen_at"],
                            "last_seen_at": i["last_seen_at"],
                            "rank": None,
                        }
                        for i in items
                    ],
                }
            )
        except Exception as exc:  # noqa: BLE001 - 单只失败不拖垮整批
            degraded.append({"code": code, "error": type(exc).__name__})

    return {
        **result,
        "status": (
            str(plane["status"])
            if plane["status"] != STATUS_NORMAL
            else (STATUS_PARTIAL if degraded else STATUS_NORMAL)
        ),
        "error": plane.get("error"),
        "watchlist_status": str(wl_status.get("status", "unavailable")),
        "codes": codes,
        "securities": securities,
        "degraded": degraded,
    }


# ---------------------------------------------------------------------------
# 状态
# ---------------------------------------------------------------------------


def status(path: str | None = None) -> dict[str, Any]:
    """Native Intel 运行状态：存储 / 最近抓取 / 来源健康 / 目录 / 调度器。"""
    target = path or db_path()
    try:
        store.initialize_store(target)
    except store.NativeIntelStoreError as exc:
        return {
            "status": STATUS_UNAVAILABLE,
            "authority_ref": AUTHORITY_REF,
            "usage_boundary": USAGE_BOUNDARY,
            "generated_at": utc_now_iso(),
            "error": str(exc),
            "store": {"db_path": target, "readable": False},
        }

    plane = data_status(target)
    last_run = plane["last_run"]
    last_good = store.get_latest_run(
        target, statuses=(store.RUN_STATUS_OK, store.RUN_STATUS_PARTIAL)
    )
    health = store.get_source_health(target)
    item_count = store.count_items(target)

    failing = [h for h in health if h["last_status"] == store.SOURCE_RUN_FAILED]
    never_run = [h for h in health if h["run_count"] == 0]

    overall = str(plane["status"])

    return {
        "status": overall,
        "authority_ref": AUTHORITY_REF,
        "usage_boundary": USAGE_BOUNDARY,
        "generated_at": utc_now_iso(),
        "store": {
            "db_path": target,
            "readable": True,
            "schema_version": store.get_meta("schema_version", target),
            "item_count": item_count,
        },
        "scheduler": {
            "started": _SCHEDULER_STARTED,
            "interval_seconds": int(os.environ.get("VIBE_NATIVE_INTEL_INTERVAL", "1800")),
            "enabled": os.environ.get("VIBE_NATIVE_INTEL_DISABLE_SCHEDULER", "").strip() != "1",
        },
        "last_run": last_run,
        "last_successful_run": last_good,
        "sources": {
            "total": len(health),
            "healthy": len(health) - len(failing) - len(never_run),
            "failing": len(failing),
            "never_run": len(never_run),
            "failing_names": [h["name"] for h in failing][:20],
        },
        "source_health": health,
        "directory": {
            "status": STATUS_NORMAL if store.get_security_directory_size(target) else STATUS_UNAVAILABLE,
            "size": store.get_security_directory_size(target),
            "synced_at": store.get_meta("directory_synced_at", target),
            "note": "按证券查询并缓存名称/行业，不阻塞页面同步全市场目录",
        },
        "rank_history": {
            "available": False,
            "reason": "registry_sources_have_no_real_rank",
            "semantics": "RSS 源不提供真实排名；rank / rank_history 恒为空，不补 0",
        },
    }


# ---------------------------------------------------------------------------
# 调度器 + 重启恢复
# ---------------------------------------------------------------------------


def startup_recover(path: str | None = None) -> dict[str, Any]:
    """进程启动恢复：建库 / 同步注册表 / 回收中断 run / 无历史数据时首抓。"""
    target = path or db_path()
    store.initialize_store(target)
    reclaimed = store.recover_stale_runs(target)
    registry = load_registry()
    store.upsert_sources(registry["sources"], target)
    store.set_meta("registry_version", registry["registry_version"], target)

    result = {
        "reclaimed_runs": reclaimed,
        "sources": len(registry["sources"]),
        "initial_fetch": None,
    }
    last_good = store.get_latest_run(
        target, statuses=(store.RUN_STATUS_OK, store.RUN_STATUS_PARTIAL)
    )
    needs_fetch = last_good is None
    if not needs_fetch:
        started = str(last_good["started_at"]).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(started)
            needs_fetch = datetime.now(timezone.utc) - parsed > timedelta(hours=STALE_AFTER_HOURS)
        except ValueError:
            needs_fetch = True
    if needs_fetch:
        try:
            result["initial_fetch"] = run_fetch("startup", target, registry=registry)
        except Exception as exc:  # noqa: BLE001 - 启动首抓失败不能阻止服务起来
            result["initial_fetch"] = {"status": store.RUN_STATUS_FAILED, "error": type(exc).__name__}
    return result


def start_scheduler(interval: int | None = None) -> None:
    """启动后台定时抓取（daemon 线程，幂等）。"""
    global _SCHEDULER_STARTED
    if os.environ.get("VIBE_NATIVE_INTEL_DISABLE_SCHEDULER", "").strip() == "1":
        return
    seconds = int(interval or os.environ.get("VIBE_NATIVE_INTEL_INTERVAL", "1800"))
    with _SCHEDULER_LOCK:
        if _SCHEDULER_STARTED:
            return

        def loop() -> None:
            while True:
                time.sleep(seconds)
                try:
                    run_fetch("scheduled")
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=loop, daemon=True, name="native-intel-fetch").start()
        _SCHEDULER_STARTED = True
