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
import logging
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
import uuid

import native_intel_store as store
import native_intel_freshness as freshness

# 复用 Vibe 自有的 MIT newsradar 实现
import newsradar

import native_intel_hotlist as hotlist
import native_intel_filter as filter_engine

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
_STARTUP_FETCH_LOCK = threading.Lock()
_STARTUP_FETCHING: set[str] = set()
_LOGGER = logging.getLogger("native_intel")

_ENV_DB = "VIBE_NATIVE_INTEL_DB"
_ENV_DISABLE_STARTUP_FETCH = "VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH"


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
    for raw in cfg.get("hotlists", []):
        name = str(raw.get("name") or "").strip()
        platform = str(raw.get("platform") or "").strip()
        if not name or not platform:
            continue
        hint = str(raw.get("hint") or "macro").strip()
        source_id = f"hotlist-{_slug(platform)}"
        if source_id in seen:
            continue
        seen.add(source_id)
        sources.append(
            {
                "source_id": source_id,
                "name": name,
                "hint": hint,
                # url 存完整抓取地址：来源表自描述，user/API 侧无需额外字段
                "url": hotlist.build_source_url(platform),
                "source_type": "hotlist",
                "has_real_rank": True,
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
    proxy_url: str | None = None,
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """抓单个源；返回 ``(items, error_kind, error_detail)``。

    与 ``newsradar._fetch_source`` 的区别：失败时保留结构化错误类别而不是返回 None，
    这样「源失败」永远不会退化成「该源没有数据」。支持 HTTP/HTTPS 代理。
    """
    try:
        req = urllib.request.Request(
            source["url"],
            headers={
                "User-Agent": newsradar.UA,
                "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml,*/*",
            },
        )
        if proxy_url:
            handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
            opener = urllib.request.build_opener(handler)
            with opener.open(req, timeout=FETCH_TIMEOUT) as resp:
                raw = resp.read()
        else:
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
    hotlist_fetcher: Callable[..., tuple[list[dict[str, Any]], str | None, str | None]] | None = None,
) -> dict[str, Any]:
    """执行一次全量抓取；已加锁防并发，返回结构化 run 结果。

    抓取清单来自 DB 中 ``enabled=1`` 的来源（系统 seed 同步后），因此用户停用 /
    自建来源即时生效。按类型分发：hotlist 源走 ``hotlist_fetcher``（默认真实
    热榜抓取），其余走 ``fetcher``（默认 RSS 抓取）；测试按类型注入，互不泄漏。
    ``sources_override`` 仅供测试固定抓取清单，生产路径不传。
    """
    target = path or db_path()
    reg = registry or load_registry()
    store.initialize_store(target)
    store.upsert_sources(reg["sources"], target)

    sources = sources_override if sources_override is not None else store.list_sources(
        target, enabled_only=True
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=reg["recent_days"])
    redline = reg["redline"]
    do_fetch = fetcher or _fetch_source_items
    hotlist_do = hotlist_fetcher or hotlist.fetch_hotlist_items

    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{os.getpid()}-{uuid4_short()}"
    observed_at = utc_now_iso()

    with _FETCH_LOCK:
        store.start_run(run_id, trigger, len(sources), target)

        cfg = store.get_native_intel_config(target)
        crawler_proxy = store.resolve_crawler_proxy(cfg)
        rss_proxy = store.resolve_rss_proxy(cfg)

        def task(source: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], str | None, str | None, int]:
            started = time.monotonic()
            stype = str(source.get("source_type") or "rss")
            if stype == "hotlist":
                if bool(cfg.get("crawler_proxy_enabled")):
                    if not crawler_proxy:
                        return source, [], store.ERROR_KIND_NETWORK, "CrawlerProxyUnresolved", int((time.monotonic() - started) * 1000)
                    items, kind, detail = hotlist_do(
                        source, timeout=FETCH_TIMEOUT, redline=redline, proxy_url=crawler_proxy
                    )
                else:
                    items, kind, detail = hotlist_do(
                        source, timeout=FETCH_TIMEOUT, redline=redline
                    )
            else:
                # Wave 3：入库事实保留全量数据（cutoff=None），新鲜度在展示与分析侧作为 Policy 过滤
                if bool(cfg.get("rss_proxy_enabled")):
                    if not rss_proxy:
                        return source, [], store.ERROR_KIND_NETWORK, "RssProxyUnresolved", int((time.monotonic() - started) * 1000)
                    items, kind, detail = do_fetch(
                        source, per=reg["per_source"], cutoff=None, redline=redline, proxy_url=rss_proxy
                    )
                else:
                    items, kind, detail = do_fetch(
                        source, per=reg["per_source"], cutoff=None, redline=redline
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
                "rank_history": {
                    "available": store.any_source_has_real_rank(target),
                    "reason": None
                    if store.any_source_has_real_rank(target)
                    else "registry_sources_have_no_real_rank",
                },
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
    has_rank_sources = store.any_source_has_real_rank(target)
    items: list[dict[str, Any]] = []
    for row in current_rows:
        entry = {
            **row,
            "is_new_in_window": row["title_key"] not in prev_titles,
        }
        if row.get("has_real_rank"):
            # 热榜条目：附真实当前/上次排名与 delta（观测推导，非伪造）
            state = store.get_item_rank_state(int(row["item_id"]), target)
            entry.update(
                {
                    "rank": state.get("current_rank"),
                    "previous_rank": state.get("previous_rank"),
                    "rank_delta": state.get("rank_delta"),
                    "current_state": state.get("current_state"),
                    "rank_history": state.get("observations", []),
                }
            )
        else:
            entry.update(
                {
                    "rank": None,
                    "previous_rank": None,
                    "rank_delta": None,
                    "current_state": None,
                    "rank_history": [],
                }
            )
        items.append(entry)
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
            "available": has_rank_sources,
            "reason": None if has_rank_sources else "registry_sources_have_no_real_rank",
            "semantics": (
                "热榜条目携带上游真实排名与 delta；RSS 条目 rank 恒为 NULL，"
                "热度只统计跨来源出现次数与环比变化，不补序号"
            ),
        },
    }


# ---------------------------------------------------------------------------
# TREND-PARITY Wave 1：热榜板面 / 排名轨迹 / 来源管理
# 排名全部来自 intel_observations 的真实观测；ON_LIST / OFF_LIST / UNKNOWN
# 状态由「最近一次来源级 run 成败 + 条目是否在榜」读取侧推导（store.get_item_rank_state），
# 绝不写回存储、绝不伪造 rank=0/999。
# ---------------------------------------------------------------------------


def _hotlist_enrich_row(row: dict[str, Any], target: str) -> dict[str, Any]:
    state = store.get_item_rank_state(int(row["item_id"]), target)
    return {
        **row,
        "rank": state.get("current_rank"),
        "previous_rank": state.get("previous_rank"),
        "rank_delta": state.get("rank_delta"),
        "current_state": state.get("current_state"),
        "last_run_id": state.get("last_run_id"),
    }


def hotlist_board(
    path: str | None = None,
    *,
    limit: int = 60,
    mode: str = "all",
    profile_id: str = "default",
) -> dict[str, Any]:
    """热榜板面：hotlist 来源的条目 + 真实排名与变化。

    来源失败 ≠ 掉榜：失败来源的条目 current_state=UNKNOWN（保留最后真实排名）。
    实体映射沿用既有 entity mapping；无可靠映射就不显示（不猜证券关联）。
    TREND-PARITY Wave 2：支持 mode='my_interests' 个人兴趣过滤与 'all' 全量透传。
    """
    target = path or db_path()
    result: dict[str, Any] = {
        "status": STATUS_NORMAL,
        "authority_ref": AUTHORITY_REF,
        "usage_boundary": USAGE_BOUNDARY,
        "generated_at": utc_now_iso(),
        "sources": [],
        "items": [],
        "filter_meta": None,
    }
    try:
        plane = data_status(target)
        result["status"] = str(plane["status"])
        result["error"] = plane.get("error")
        source_rows = store.list_sources(target, enabled_only=False)
        hotlist_sources = [s for s in source_rows if str(s.get("source_type")) == "hotlist"]
        for src in hotlist_sources:
            last_run = store.latest_source_run(str(src["source_id"]), target)
            result["sources"].append(
                {
                    "source_id": src["source_id"],
                    "name": src["name"],
                    "hint": src["hint"],
                    "enabled": bool(src["enabled"]),
                    "origin": src.get("origin") or "system",
                    "last_run_status": last_run["status"] if last_run else None,
                    "last_run_error_kind": last_run.get("error_kind") if last_run else None,
                }
            )
        rows = store.list_hotlist_items(target, limit=limit)
        entity_map = store.list_item_entities(
            [int(r["item_id"]) for r in rows], target
        )
        for row in rows:
            enriched = _hotlist_enrich_row(row, target)
            enriched["entities"] = entity_map.get(int(row["item_id"]), [])
            result["items"].append(enriched)

        # TREND-PARITY Wave 2：个人兴趣过滤
        try:
            matched_items, f_meta = filter_items(result["items"], profile_id=profile_id, path=target)
            result["filter_meta"] = {
                **f_meta,
                "mode": mode,
                "status": "normal",
            }
            if mode == "my_interests":
                result["items"] = matched_items
            else:
                matched_map = {int(m["item_id"]): m.get("filter_match") for m in matched_items}
                for it in result["items"]:
                    it["filter_match"] = matched_map.get(int(it["item_id"]))
        except Exception as filter_err:
            _LOGGER.warning("热榜兴趣过滤异常: %s", filter_err)
            safe_error = str(filter_err)
            result["filter_meta"] = {
                "status": "UNAVAILABLE",
                "error": safe_error,
                "mode": mode,
                "profile_id": profile_id,
                "total_evaluated": len(result["items"]),
                "matched_count": 0,
            }
            if mode == "my_interests":
                result["items"] = []
    except store.NativeIntelStoreError as exc:
        result["status"] = STATUS_UNAVAILABLE
        result["error"] = str(exc)
    return result


def item_rank_history(item_id: int, path: str | None = None) -> dict[str, Any] | None:
    """单条目排名轨迹（H 契约）。条目不存在返回 None（路由层 404）。"""
    target = path or db_path()
    state = store.get_item_rank_state(int(item_id), target)
    if not state:
        return None
    try:
        base = _load_item(int(item_id), target) or {}
    except store.NativeIntelStoreError:
        base = {}
    return {
        **state,
        "title": base.get("title"),
        "url": base.get("url"),
        "hint": base.get("hint"),
        "state_semantics": {
            "ON_LIST": "最近一次来源抓取成功且条目在榜",
            "OFF_LIST": "最近一次来源抓取成功但条目未出现（真实掉榜，不写假 rank）",
            "UNKNOWN": "来源最近一次抓取失败或尚未抓取：现状未知，绝不当作掉榜",
            "DISABLED": "来源已停用或已删除：保留末次观测供审计，不当实时在榜",
            "STALE": "抓取数据已过期（超出时效窗口）：保留末次已知排名，不当实时在榜",
            "NO_RANK_SEMANTICS": "来源无真实排名（RSS），rank 恒为 NULL",
        },
    }


def sources_list(path: str | None = None) -> dict[str, Any]:
    """来源注册表（含 origin / enabled / 最近一次 run 状态）。"""
    target = path or db_path()
    try:
        rows = store.list_sources(target, enabled_only=False)
    except store.NativeIntelStoreError as exc:
        return {"status": STATUS_UNAVAILABLE, "error": str(exc), "sources": []}
    sources: list[dict[str, Any]] = []
    for row in rows:
        last_run = store.latest_source_run(str(row["source_id"]), target)
        sources.append(
            {
                "source_id": row["source_id"],
                "name": row["name"],
                "hint": row["hint"],
                "url": row["url"],
                "source_type": row["source_type"],
                "has_real_rank": bool(row["has_real_rank"]),
                "enabled": bool(row["enabled"]),
                "origin": row.get("origin") or "system",
                "updated_at": row.get("updated_at"),
                "last_run_status": last_run["status"] if last_run else None,
                "max_age_days": row.get("max_age_days"),
            }
        )
    return {"status": STATUS_NORMAL, "sources": sources}


_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


def create_user_source(payload: dict[str, Any], path: str | None = None) -> dict[str, Any]:
    """新增用户 RSS 源（origin=user）；输入非法抛 ValueError，重名抛 store 冲突。"""
    name = str((payload or {}).get("name") or "").strip()
    url = str((payload or {}).get("url") or "").strip()
    hint = str((payload or {}).get("hint") or "").strip()
    enabled = bool((payload or {}).get("enabled", True))
    if not name or len(name) > 80:
        raise ValueError("name 必填且不超过 80 字符")
    if not _URL_RE.fullmatch(url):
        raise ValueError("url 必须是 http(s) 地址")
    if len(hint) > 20:
        raise ValueError("hint 不超过 20 字符")
    max_age_arg = None
    if "max_age_days" in (payload or {}):
        val = (payload or {})["max_age_days"]
        if val is not None:
            if isinstance(val, bool) or not isinstance(val, int) or val < 0:
                raise ValueError("max_age_days 必须为非负整数或 None")
            max_age_arg = int(val)

    source_id = f"user-rss-{uuid.uuid4().hex[:12]}"
    try:
        row = store.insert_user_source(
            source_id=source_id, name=name, url=url, hint=hint, enabled=enabled,
            max_age_days=max_age_arg, db_path=path
        )
    except store.SourceAlreadyExistsError as exc:
        raise _SourceConflictError(source_id) from exc
    return {**row, "has_real_rank": bool(row.get("has_real_rank")), "enabled": bool(row["enabled"])}


class _SourceConflictError(RuntimeError):
    def __init__(self, source_id: str):
        self.source_id = source_id
        super().__init__(source_id)


def update_source(source_id: str, payload: dict[str, Any], path: str | None = None) -> dict[str, Any] | None:
    """更新来源；系统源仅允许 enabled，用户源允许 enabled + name。支持 RSS 独立的 max_age_days 设置。"""
    data = payload or {}
    enabled = data.get("enabled")
    name = data.get("name")
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError("enabled 必须是布尔值")
    if name is not None:
        name = str(name).strip()
        if not name or len(name) > 80:
            raise ValueError("name 不能为空且不超过 80 字符")

    current = store.get_source(source_id, path)
    if current is None:
        return None
    if str(current.get("origin") or "system") != "user" and name is not None and name != current["name"]:
        raise ValueError("系统来源不允许改名（可停用）")

    max_age_arg = store._UNSET
    if "max_age_days" in data:
        st = str(current.get("source_type") or "rss").lower()
        if st != "rss":
            raise ValueError("仅 RSS 来源支持设置 max_age_days")
        val = data["max_age_days"]
        if val is not None:
            if isinstance(val, bool) or not isinstance(val, int):
                raise ValueError("max_age_days 必须为非负整数或 None")
            if val < 0:
                raise ValueError("max_age_days 不能为负数")
            max_age_arg = int(val)
        else:
            max_age_arg = None

    return store.update_source(
        source_id,
        enabled=enabled,
        name=name if isinstance(name, str) else None,
        max_age_days=max_age_arg,
        db_path=path,
    )


def delete_source(source_id: str, path: str | None = None) -> dict[str, Any]:
    """删除来源；系统源 fail closed（SystemSourceDeleteBlocked）。"""
    return store.delete_user_source(source_id, path)


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
            WHERE o.observed_at >= ?
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
        state = store.get_item_rank_state(int(item["item_id"]), target)
        enriched.append(
            {
                **item,
                # 热榜条目带真实当前排名；RSS 条目保持 None（无排名语义）
                "rank": state.get("current_rank"),
                "previous_rank": state.get("previous_rank"),
                "rank_delta": state.get("rank_delta"),
                "current_state": state.get("current_state"),
                "rank_history": state.get("observations", []),
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
        "freshness": {
            "enabled": bool(store.get_native_intel_config(target).get("rss_freshness_enabled")),
            "global_max_age_days": int(store.get_native_intel_config(target).get("rss_global_max_age_days", 1)),
            "excluded_count": store.count_freshness_excluded_rss_items(target),
        },
        "proxies": {
            "crawler_proxy": {
                "enabled": bool(store.get_native_intel_config(target).get("crawler_proxy_enabled")),
                "configured": bool(store.get_native_intel_config(target).get("crawler_proxy_url")),
                "url": store.redact_proxy_url(store.get_native_intel_config(target).get("crawler_proxy_url")),
            },
            "rss_proxy": {
                "enabled": bool(store.get_native_intel_config(target).get("rss_proxy_enabled")),
                "configured": bool(store.get_native_intel_config(target).get("rss_proxy_url")),
                "url": store.redact_proxy_url(store.resolve_rss_proxy(store.get_native_intel_config(target))),
                "using_crawler_fallback": bool(
                    store.get_native_intel_config(target).get("rss_proxy_enabled")
                    and not store.get_native_intel_config(target).get("rss_proxy_url")
                    and store.get_native_intel_config(target).get("crawler_proxy_url")
                ),
            },
        },
        "standalone": {
            "enabled": bool(store.get_native_intel_config(target).get("standalone_enabled")),
            "source_count": len(store.get_native_intel_config(target).get("standalone_source_ids", [])),
            "max_items": int(store.get_native_intel_config(target).get("standalone_max_items", 20)),
        },
        "display": {
            "region_order": store.get_native_intel_config(target).get("region_order", list(store.DEFAULT_NATIVE_INTEL_CONFIG["region_order"])),
            "regions_enabled": store.get_native_intel_config(target).get("regions_enabled", dict(store.DEFAULT_NATIVE_INTEL_CONFIG["regions_enabled"])),
        },
    }


# ---------------------------------------------------------------------------
# 调度器 + 重启恢复
# ---------------------------------------------------------------------------


def _startup_fetch_key(target: str) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(target)))


def _startup_fetch_is_running(target: str) -> bool:
    key = _startup_fetch_key(target)
    with _STARTUP_FETCH_LOCK:
        return key in _STARTUP_FETCHING


def _schedule_startup_fetch(target: str, registry: dict[str, Any]) -> bool:
    """Schedule one startup refresh per database path without delaying API readiness."""
    key = _startup_fetch_key(target)
    with _STARTUP_FETCH_LOCK:
        if key in _STARTUP_FETCHING:
            return False
        _STARTUP_FETCHING.add(key)

    def worker() -> None:
        try:
            run_fetch("startup", target, registry=registry)
        except Exception as exc:  # noqa: BLE001 - data_status remains the user-visible truth
            _LOGGER.warning(
                "Native Intel background startup fetch unavailable: %s",
                type(exc).__name__,
            )
        finally:
            with _STARTUP_FETCH_LOCK:
                _STARTUP_FETCHING.discard(key)

    thread = threading.Thread(
        target=worker,
        daemon=True,
        name="native-intel-startup-fetch",
    )
    try:
        thread.start()
    except Exception:
        with _STARTUP_FETCH_LOCK:
            _STARTUP_FETCHING.discard(key)
        raise
    return True


def startup_recover(
    path: str | None = None,
    *,
    background_fetch: bool = True,
) -> dict[str, Any]:
    """建库、同步注册表并恢复中断 run；陈旧资讯默认在后台刷新。

    存储恢复仍在 API readiness 前完成。网络抓取不再阻塞应用启动；读取侧在刷新完成前
    继续诚实返回 unavailable / stale / partial。测试或维护工具可显式传入
    ``background_fetch=False`` 保留同步行为。
    """
    target = path or db_path()
    background_running = background_fetch and _startup_fetch_is_running(target)
    store.initialize_store(target)
    reclaimed = 0 if background_running else store.recover_stale_runs(target)
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
    if not needs_fetch:
        return result

    if os.environ.get(_ENV_DISABLE_STARTUP_FETCH, "").strip() == "1":
        result["initial_fetch"] = {
            "status": "disabled",
            "reason": "startup_fetch_disabled",
        }
        return result

    if background_fetch:
        try:
            scheduled = _schedule_startup_fetch(target, registry)
            result["initial_fetch"] = {
                "status": "scheduled" if scheduled else "already_running",
                "trigger": "startup",
            }
        except Exception as exc:  # noqa: BLE001 - 启动首抓失败不能阻止服务起来
            result["initial_fetch"] = {
                "status": store.RUN_STATUS_FAILED,
                "error": type(exc).__name__,
            }
        return result

    try:
        result["initial_fetch"] = run_fetch("startup", target, registry=registry)
    except Exception as exc:  # noqa: BLE001 - 同步维护调用也保留既有失败语义
        result["initial_fetch"] = {
            "status": store.RUN_STATUS_FAILED,
            "error": type(exc).__name__,
        }
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
                    from native_intel_timeline import scheduled_tick
                    scheduled_tick()
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=loop, daemon=True, name="native-intel-fetch").start()
        _SCHEDULER_STARTED = True


# ---------------------------------------------------------------------------
# TREND-PARITY Wave 2：个人兴趣与关键词过滤服务层
# 双轨设计：关键词/正则规则 (本地高速) + AI 自然语言标签提取与批量分类 (统一模型网关)
# 约束：零第二存储、失败隔离（AI 不可用绝不阻断抓取）、事实不可变（排名/实体/时效不篡改）
# ---------------------------------------------------------------------------


def get_filter_profile(profile_id: str = "default", path: str | None = None) -> dict[str, Any]:
    """获取指定 profile 配置；若不存在则自动用系统预置配置初始化。"""
    target = path or db_path()
    prof = store.get_filter_profile(profile_id, target)
    if prof is not None:
        return prof
    default_rules = filter_engine.get_default_keyword_rules().to_dict()
    default_text = filter_engine.DEFAULT_INTERESTS_TEXT
    fp = filter_engine.compute_keyword_fingerprint(default_rules)
    return store.upsert_filter_profile(
        profile_id=profile_id,
        name="默认关注",
        method=filter_engine.METHOD_KEYWORD,
        interests_text=default_text,
        min_score=filter_engine.DEFAULT_MIN_SCORE,
        keyword_rules=default_rules,
        tags=[],
        profile_fingerprint=fp,
        reclassify_threshold=filter_engine.DEFAULT_RECLASSIFY_THRESHOLD,
        db_path=target,
    )


def update_filter_profile(
    profile_id: str,
    payload: dict[str, Any],
    path: str | None = None,
) -> dict[str, Any]:
    """更新 profile 配置；输入非法抛出 ValueError。支持关键词/AI双向切换。"""
    target = path or db_path()
    current = get_filter_profile(profile_id, target)

    name = str(payload.get("name") if "name" in payload else current["name"]).strip()
    if not name:
        raise ValueError("name 不能为空")

    method = str(payload.get("method") if "method" in payload else current["method"]).strip().lower()
    if method not in filter_engine.VALID_METHODS:
        raise ValueError(f"无效的过滤方法: {method}，仅支持 keyword 或 ai")

    interests_text = str(
        payload.get("interests_text") if "interests_text" in payload else current.get("interests_text", "")
    )

    raw_min_score = payload.get("min_score", current.get("min_score", filter_engine.DEFAULT_MIN_SCORE))
    try:
        min_score = float(raw_min_score)
    except (ValueError, TypeError):
        raise ValueError("min_score 必须为有效浮点数") from None
    if not (0.0 <= min_score <= 1.0):
        raise ValueError("min_score 必须在 0.0 到 1.0 之间")

    raw_threshold = payload.get(
        "reclassify_threshold",
        current.get("reclassify_threshold", filter_engine.DEFAULT_RECLASSIFY_THRESHOLD),
    )
    try:
        reclassify_threshold = float(raw_threshold)
    except (ValueError, TypeError):
        raise ValueError("reclassify_threshold 必须为有效浮点数") from None
    if not (0.0 <= reclassify_threshold <= 1.0):
        raise ValueError("reclassify_threshold 必须在 0.0 到 1.0 之间")

    if "keyword_rules" in payload:
        raw_rules = payload["keyword_rules"]
        if isinstance(raw_rules, dict):
            rules = filter_engine.KeywordRules.from_dict(raw_rules).to_dict()
        else:
            rules = current.get("keyword_rules", {})
    else:
        rules = current.get("keyword_rules", {})

    if "tags" in payload:
        raw_tags = payload["tags"]
        if isinstance(raw_tags, list):
            tags: list[dict[str, Any]] = []
            for idx, t in enumerate(raw_tags, start=1):
                if isinstance(t, dict) and t.get("tag"):
                    tags.append({
                        "id": int(t.get("id") or idx),
                        "tag": str(t["tag"]).strip(),
                        "description": str(t.get("description") or "").strip(),
                    })
        else:
            tags = current.get("tags", [])
    else:
        tags = current.get("tags", [])

    if method == filter_engine.METHOD_KEYWORD:
        fp = filter_engine.compute_keyword_fingerprint(rules)
    else:
        fp = filter_engine.compute_ai_fingerprint(interests_text, tags)

    return store.upsert_filter_profile(
        profile_id=profile_id,
        name=name,
        method=method,
        interests_text=interests_text,
        min_score=min_score,
        keyword_rules=rules,
        tags=tags,
        profile_fingerprint=fp,
        reclassify_threshold=reclassify_threshold,
        db_path=target,
    )


def extract_filter_tags(
    interests_text: str,
    cfg: dict[str, Any] | None = None,
    model_runner: Callable[[Any, list[dict[str, str]]], str] | None = None,
) -> list[dict[str, Any]]:
    return filter_engine.extract_interest_tags(interests_text, cfg=cfg, model_runner=model_runner)


def update_filter_tags(
    old_tags: list[dict[str, Any]],
    new_interests_text: str,
    cfg: dict[str, Any] | None = None,
    model_runner: Callable[[Any, list[dict[str, str]]], str] | None = None,
) -> dict[str, Any]:
    return filter_engine.update_interest_tags(
        old_tags, new_interests_text, cfg=cfg, model_runner=model_runner
    )


def classify_items(
    profile_id: str = "default",
    item_ids: list[int] | None = None,
    limit: int = 100,
    cfg: dict[str, Any] | None = None,
    model_runner: Callable[[Any, list[dict[str, str]]], str] | None = None,
    path: str | None = None,
    batch_size: int = 15,
    **kwargs: Any,
) -> dict[str, Any]:
    """批量调用 AI 对未分类或分类失败的条目执行分类。

    状态模型：
    - CLASSIFIED: 命中并已分类（cache hit，不重复请求）
    - NOT_RELEVANT: 成功评估但未命中（cache hit，不重复请求）
    - ERROR: 批次失败（允许重试）
    - UNCLASSIFIED: 尚未评估（调用 AI）
    """
    target = path or db_path()
    prof = get_filter_profile(profile_id, target)
    tags = prof.get("tags") or []
    fp = prof["profile_fingerprint"]
    if not tags:
        return {
            "status": "NO_TAGS",
            "message": "当前 profile 未配置兴趣标签，无法执行 AI 分类",
            "total": 0,
            "classified": 0,
            "failed": 0,
            "unclassified": 0,
            "profile_fingerprint": fp,
        }

    if item_ids is not None:
        all_candidates = store.list_recent_items_for_filter(target, limit=500)
        items = [i for i in all_candidates if i["item_id"] in item_ids]
    else:
        items = store.list_recent_items_for_filter(target, limit=limit)

    if not items:
        return {
            "status": "EMPTY",
            "total": 0,
            "classified": 0,
            "failed": 0,
            "unclassified": 0,
            "profile_fingerprint": fp,
        }

    # Wave 3：在 AI 分类候选收集时剔除已过期的 RSS 条目，旧事实保留于库中但不浪费 AI 配额
    cfg = store.get_native_intel_config(target)
    fresh_items = []
    for item in items:
        st = str(item.get("source_type") or "rss")
        if st == "rss":
            res = freshness.evaluate_item_freshness(
                item,
                global_enabled=bool(cfg.get("rss_freshness_enabled")),
                global_max_age_days=int(cfg.get("rss_global_max_age_days", 1)),
                source_max_age_days=item.get("source_max_age_days") if item.get("source_max_age_days") is not None else item.get("max_age_days"),
            )
            if not res.eligible:
                continue
        fresh_items.append(item)
    items = fresh_items

    candidate_ids = [int(i["item_id"]) for i in items]
    analyses = store.get_item_analyses(profile_id, fp, candidate_ids, db_path=target)

    # 仅当 analysis_state 为 ERROR 或未在 analyses 中时，才需要发送给 AI
    pending_items = [
        i for i in items
        if int(i["item_id"]) not in analyses or analyses[int(i["item_id"])]["analysis_state"] == store.ANALYSIS_STATE_ERROR
    ]

    existing_classified = [
        iid for iid, a in analyses.items() if a["analysis_state"] == store.ANALYSIS_STATE_CLASSIFIED
    ]

    if not pending_items:
        return {
            "status": "UP_TO_DATE",
            "total": len(items),
            "classified": len(existing_classified),
            "failed": 0,
            "unclassified": 0,
            "profile_fingerprint": fp,
        }

    succeeded, not_relevant_ids, failed_ids = filter_engine.classify_items_batch(
        items=pending_items,
        tags=tags,
        interests_text=prof.get("interests_text", ""),
        cfg=cfg,
        batch_size=batch_size,
        model_runner=model_runner,
    )

    now = utc_now_iso()
    provider_id = filter_engine.get_provider_identity(cfg)

    # 1. 保存命中的分类记录
    records = []
    analysis_records = []
    for s in succeeded:
        records.append({
            "item_id": s["item_id"],
            "profile_id": profile_id,
            "profile_fingerprint": fp,
            "primary_tag": s["primary_tag"],
            "relevance_score": s["relevance_score"],
            "classified_at": now,
            "provider_identity": provider_id,
        })
        analysis_records.append({
            "item_id": s["item_id"],
            "profile_id": profile_id,
            "profile_fingerprint": fp,
            "analysis_state": store.ANALYSIS_STATE_CLASSIFIED,
            "analyzed_at": now,
            "provider_identity": provider_id,
            "error_kind": None,
        })
    store.save_item_classifications(records, db_path=target)

    # 2. 保存未命中的 NOT_RELEVANT 记录（不写 classifications 表）
    for n_id in not_relevant_ids:
        analysis_records.append({
            "item_id": n_id,
            "profile_id": profile_id,
            "profile_fingerprint": fp,
            "analysis_state": store.ANALYSIS_STATE_NOT_RELEVANT,
            "analyzed_at": now,
            "provider_identity": provider_id,
            "error_kind": None,
        })

    # 3. 保存失败批次的 ERROR 记录
    for f_id in failed_ids:
        analysis_records.append({
            "item_id": f_id,
            "profile_id": profile_id,
            "profile_fingerprint": fp,
            "analysis_state": store.ANALYSIS_STATE_ERROR,
            "analyzed_at": now,
            "provider_identity": provider_id,
            "error_kind": "BATCH_FAILURE",
        })

    store.record_item_analyses(analysis_records, db_path=target)

    return {
        "status": "PARTIAL_FAILURE" if failed_ids else "SUCCESS",
        "total": len(items),
        "classified": len(existing_classified) + len(succeeded),
        "newly_classified": len(succeeded),
        "not_relevant": len(not_relevant_ids),
        "failed": len(failed_ids),
        "unclassified": max(0, len(pending_items) - len(succeeded) - len(not_relevant_ids) - len(failed_ids)),
        "failed_item_ids": failed_ids,
        "profile_fingerprint": fp,
    }


def apply_interest_update(
    profile_id: str = "default",
    interests_text: str = "",
    new_interests_text: str = "",
    cfg: dict[str, Any] | None = None,
    ai_config: dict[str, Any] | None = None,
    full_reclassify_threshold: float | None = None,
    min_score: float | None = None,
    model_runner: Callable[[Any, list[dict[str, str]]], str] | None = None,
    path: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """完整编排兴趣更新与重分类决策（FULL vs INCREMENTAL）。"""
    target = path or db_path()
    prof = get_filter_profile(profile_id, target)
    old_tags = prof.get("tags") or []
    old_fp = prof["profile_fingerprint"]
    clean_text = (interests_text or new_interests_text or kwargs.get("interests_text") or kwargs.get("new_interests_text") or "").strip()
    if not clean_text:
        raise ValueError("兴趣描述文本为空")
    effective_cfg = cfg or ai_config or kwargs.get("cfg") or kwargs.get("ai_config")
    if not effective_cfg and model_runner is None:
        raise ValueError("AI_CONFIG_REQUIRED: 未提供有效的 AI 模型配置")

    effective_min_score: float | None = None
    raw_min_score = min_score if min_score is not None else kwargs.get("min_score")
    if raw_min_score is not None:
        try:
            effective_min_score = float(raw_min_score)
        except (ValueError, TypeError):
            raise ValueError("min_score 必须为有效浮点数") from None
        if not (0.0 <= effective_min_score <= 1.0):
            raise ValueError("min_score 必须在 0.0 到 1.0 之间")

    def _build_payload(tags_list: list[dict[str, Any]]) -> dict[str, Any]:
        payload_data: dict[str, Any] = {
            "interests_text": clean_text,
            "tags": tags_list,
            "method": filter_engine.METHOD_AI,
        }
        if effective_min_score is not None:
            payload_data["min_score"] = effective_min_score
        return payload_data

    # 首次配置，无旧标签 -> 必须执行完整提取
    if not old_tags:
        new_tags = filter_engine.extract_interest_tags(clean_text, cfg=effective_cfg, model_runner=model_runner)
        updated = update_filter_profile(
            profile_id=profile_id,
            payload=_build_payload(new_tags),
            path=target,
        )
        return {
            "decision": "FULL",
            "reclassification_mode": "FULL",
            "full_reclassify_required": True,
            "change_ratio": 1.0,
            "profile": updated,
        }

    # 已有标签时，先尝试对比更新
    update_res = None
    try:
        update_res = filter_engine.update_interest_tags(
            old_tags, clean_text, cfg=effective_cfg, model_runner=model_runner
        )
    except Exception as update_err:
        _LOGGER.warning("对比更新标签失败，尝试回退全量提取: %s", update_err)
        try:
            fallback_tags = filter_engine.extract_interest_tags(
                clean_text, cfg=effective_cfg, model_runner=model_runner
            )
            update_res = {
                "keep": [],
                "add": fallback_tags,
                "remove": [t.get("tag") for t in old_tags],
                "change_ratio": 1.0,
                "new_tags": fallback_tags,
            }
        except Exception as extract_err:
            _LOGGER.error("回退全量提取亦失败，Fail Closed 保持原配置不变: %s", extract_err)
            raise ValueError(f"AI 标签更新与提取均失败: {extract_err}") from extract_err

    change_ratio = float(update_res.get("change_ratio", 0.5))
    threshold = (
        float(full_reclassify_threshold)
        if full_reclassify_threshold is not None
        else float(prof.get("reclassify_threshold", filter_engine.DEFAULT_RECLASSIFY_THRESHOLD))
    )

    if change_ratio >= threshold:
        # FULL 重分类（对齐 TrendRadar）：
        # 确认触发 FULL 决策后，执行一次完整的 fresh extract_interest_tags
        # 若 fresh extract 失败，立即抛出异常且不修改数据库，保持旧配置与旧分析状态完全不变（Fail-Closed / Rollback）
        fresh_tags = filter_engine.extract_interest_tags(
            clean_text, cfg=effective_cfg, model_runner=model_runner
        )
        updated = update_filter_profile(
            profile_id=profile_id,
            payload=_build_payload(fresh_tags),
            path=target,
        )
        return {
            "decision": "FULL",
            "reclassification_mode": "FULL",
            "full_reclassify_required": True,
            "change_ratio": change_ratio,
            "profile": updated,
        }
    else:
        # INCREMENTAL 增量更新：保留 tags 的分类继承到新 fingerprint
        new_tags = update_res.get("new_tags") or []
        updated = update_filter_profile(
            profile_id=profile_id,
            payload=_build_payload(new_tags),
            path=target,
        )
        new_fp = updated["profile_fingerprint"]
        kept_tag_names = [
            str(k.get("tag") if isinstance(k, dict) else k).strip()
            for k in (update_res.get("keep") or [])
        ]
        has_added_tags = len(update_res.get("add") or []) > 0

        carried_cls, carried_ana = store.carry_forward_analysis_and_classifications(
            profile_id=profile_id,
            old_fingerprint=old_fp,
            new_fingerprint=new_fp,
            kept_tags=kept_tag_names,
            carry_not_relevant=not has_added_tags,
            db_path=target,
        )
        return {
            "decision": "INCREMENTAL",
            "reclassification_mode": "INCREMENTAL",
            "full_reclassify_required": False,
            "change_ratio": change_ratio,
            "keep": update_res.get("keep") or [],
            "add": update_res.get("add") or [],
            "remove": update_res.get("remove") or [],
            "carried_classifications": carried_cls,
            "carried_analyses": carried_ana,
            "profile": updated,
        }


def filter_items(
    items: list[dict[str, Any]],
    profile_id: str = "default",
    path: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """根据 profile 规则或 AI 分类过滤条目列表，保留原始属性并附带匹配元数据。"""
    target = path or db_path()
    prof = get_filter_profile(profile_id, target)
    method = prof.get("method", filter_engine.METHOD_KEYWORD)

    filtered: list[dict[str, Any]] = []

    if method == filter_engine.METHOD_KEYWORD:
        rules = prof.get("keyword_rules") or {}
        # 预先获取每个 group 的 max_count
        group_max_counts: dict[str, int] = {}
        if isinstance(rules, dict):
            for g in rules.get("groups") or []:
                if isinstance(g, dict) and g.get("name") and g.get("max_count") is not None:
                    try:
                        group_max_counts[str(g["name"])] = int(g["max_count"])
                    except (ValueError, TypeError):
                        pass

        group_emitted_counts: dict[str, int] = {}
        for item in items:
            title = item.get("title") or ""
            summary = item.get("summary")
            matched, groups = filter_engine.evaluate_keyword_rules(title, summary, rules)
            if matched:
                # 检查 max_count 限制
                if group_max_counts:
                    eligible_groups = [
                        g for g in groups
                        if g not in group_max_counts or group_emitted_counts.get(g, 0) < group_max_counts[g]
                    ]
                    if groups and not eligible_groups:
                        continue
                    for g in groups:
                        group_emitted_counts[g] = group_emitted_counts.get(g, 0) + 1

                item_copy = dict(item)
                item_copy["filter_match"] = {
                    "method": "keyword",
                    "matched_groups": groups,
                }
                filtered.append(item_copy)
        classified_count = len(filtered)
        not_relevant_count = max(0, len(items) - len(filtered))
        error_count = 0
        unclassified_count = 0
    else:
        fp = prof["profile_fingerprint"]
        item_ids = [int(i["item_id"]) for i in items if i.get("item_id")]
        analyses = store.get_item_analyses(profile_id, fp, item_ids, db_path=target)
        classified_count = sum(1 for a in analyses.values() if a["analysis_state"] == store.ANALYSIS_STATE_CLASSIFIED)
        not_relevant_count = sum(1 for a in analyses.values() if a["analysis_state"] == store.ANALYSIS_STATE_NOT_RELEVANT)
        error_count = sum(1 for a in analyses.values() if a["analysis_state"] == store.ANALYSIS_STATE_ERROR)
        unclassified_count = max(0, len(item_ids) - len(analyses))

        classifications = store.get_item_classifications(
            profile_id=profile_id,
            profile_fingerprint=fp,
            item_ids=item_ids,
            min_score=prof.get("min_score", filter_engine.DEFAULT_MIN_SCORE),
            db_path=target,
        )
        for item in items:
            iid = int(item.get("item_id") or 0)
            if iid in classifications:
                cls_info = classifications[iid]
                item_copy = dict(item)
                item_copy["filter_match"] = {
                    "method": "ai",
                    "primary_tag": cls_info["primary_tag"],
                    "relevance_score": cls_info["relevance_score"],
                }
                filtered.append(item_copy)

    meta = {
        "profile_id": prof["profile_id"],
        "profile_name": prof["name"],
        "method": method,
        "profile_fingerprint": prof["profile_fingerprint"],
        "total_evaluated": len(items),
        "matched_count": len(filtered),
        "classified_count": classified_count,
        "not_relevant_count": not_relevant_count,
        "unclassified_count": unclassified_count,
        "error_count": error_count,
    }
    return filtered, meta


def list_filtered_items(
    profile_id: str = "default",
    source_type: str = "all",
    mode: str = "my_interests",
    limit: int = 100,
    path: str | None = None,
) -> dict[str, Any]:
    """统一返回经过个人兴趣过滤的近期资讯（包含热榜与 RSS 真实全源）。"""
    target = path or db_path()
    raw_items = store.list_all_recent_items_with_sources(limit=max(limit * 2, 100), db_path=target)

    # 来源类型筛选
    if source_type == "hotlist":
        filtered_by_src = [i for i in raw_items if i.get("source_type") == "hotlist"]
    elif source_type == "rss":
        filtered_by_src = [i for i in raw_items if i.get("source_type") != "hotlist"]
    else:
        filtered_by_src = raw_items

    # Wave 3：应用 RSS 新鲜度过滤（先于关键词/AI过滤，不影响热榜与原始事实）
    cfg = store.get_native_intel_config(target)
    fresh_candidates = []
    freshness_excluded_count = 0
    for it in filtered_by_src:
        st = str(it.get("source_type") or "rss")
        if st == "rss":
            res = freshness.evaluate_item_freshness(
                it,
                global_enabled=bool(cfg.get("rss_freshness_enabled")),
                global_max_age_days=int(cfg.get("rss_global_max_age_days", 1)),
                source_max_age_days=it.get("source_max_age_days") if it.get("source_max_age_days") is not None else it.get("max_age_days"),
            )
            if not res.eligible:
                freshness_excluded_count += 1
                continue
        fresh_candidates.append(it)
    filtered_by_src = fresh_candidates

    # 实体关联与热榜位次补充
    item_ids = [int(i["item_id"]) for i in filtered_by_src]
    entity_map = store.list_item_entities(item_ids, target)

    enriched_items: list[dict[str, Any]] = []
    plane = data_status(target)
    is_plane_stale = plane.get("status") == STATUS_STALE

    for it in filtered_by_src:
        row = dict(it)
        iid = int(it["item_id"])
        row["entities"] = entity_map.get(iid, [])

        if it.get("source_type") == "hotlist":
            state = store.get_item_rank_state(iid, target)
            row["rank"] = state.get("current_rank")
            row["previous_rank"] = state.get("previous_rank")
            row["rank_delta"] = state.get("rank_delta")
            row["observation_count"] = int(it.get("observation_count") or 1)
            row["current_state"] = state.get("current_state") or ("STALE" if is_plane_stale else "ON_LIST")
        else:
            row["rank"] = None
            row["previous_rank"] = None
            row["rank_delta"] = None
            row["observation_count"] = int(it.get("observation_count") or 1)
            row["current_state"] = "NORMAL"

        enriched_items.append(row)

    enriched_items = enriched_items[:limit]

    try:
        matched_items, f_meta = filter_items(enriched_items, profile_id=profile_id, path=target)
        f_meta["mode"] = mode
        f_meta["source_type"] = source_type
        f_meta["status"] = "normal"
        f_meta["freshness_excluded_count"] = freshness_excluded_count
        if mode == "my_interests":
            display_items = matched_items
        else:
            matched_map = {int(m["item_id"]): m.get("filter_match") for m in matched_items}
            display_items = []
            for it in enriched_items:
                it_copy = dict(it)
                it_copy["filter_match"] = matched_map.get(int(it["item_id"]))
                display_items.append(it_copy)
    except Exception as filter_err:
        _LOGGER.warning("资讯过滤失败: %s", filter_err)
        f_meta = {
            "status": "UNAVAILABLE",
            "error": str(filter_err),
            "mode": mode,
            "source_type": source_type,
            "profile_id": profile_id,
            "total_evaluated": len(enriched_items),
            "matched_count": 0,
        }
        if mode == "my_interests":
            display_items = []
        else:
            display_items = enriched_items

    return {
        "status": "normal",
        "items": display_items,
        "filter_meta": f_meta,
    }


def filter_status(profile_id: str = "default", path: str | None = None) -> dict[str, Any]:
    """查询过滤器运行状态与条目分类覆盖率统计（支持诚实状态呈现）。"""
    target = path or db_path()
    prof = get_filter_profile(profile_id, target)
    fp = prof["profile_fingerprint"]

    recent_items = store.list_recent_items_for_filter(target, limit=100)
    total_recent = len(recent_items)
    item_ids = [int(i["item_id"]) for i in recent_items]

    if prof["method"] == filter_engine.METHOD_AI:
        analyses = store.get_item_analyses(profile_id, fp, item_ids, db_path=target)
        classifications = store.get_item_classifications(
            profile_id=profile_id,
            profile_fingerprint=fp,
            item_ids=item_ids,
            db_path=target,
        )

        classified_count = sum(1 for a in analyses.values() if a["analysis_state"] == store.ANALYSIS_STATE_CLASSIFIED)
        not_relevant_count = sum(1 for a in analyses.values() if a["analysis_state"] == store.ANALYSIS_STATE_NOT_RELEVANT)
        error_count = sum(1 for a in analyses.values() if a["analysis_state"] == store.ANALYSIS_STATE_ERROR)
        analyzed_set = set(analyses.keys())
        unclassified_count = max(0, sum(1 for iid in item_ids if iid not in analyzed_set))

        min_score = float(prof.get("min_score", filter_engine.DEFAULT_MIN_SCORE))
        matched_count = sum(1 for c in classifications.values() if float(c["relevance_score"]) >= min_score)
        below_threshold_count = max(0, classified_count - matched_count)
    else:
        rules = prof.get("keyword_rules") or {}
        matched_cnt = 0
        for i in recent_items:
            m, _ = filter_engine.evaluate_keyword_rules(i["title"], i.get("summary"), rules)
            if m:
                matched_cnt += 1
        classified_count = matched_cnt
        not_relevant_count = max(0, total_recent - matched_cnt)
        error_count = 0
        unclassified_count = 0
        below_threshold_count = 0
        matched_count = matched_cnt

    return {
        "status": "normal",
        "profile": prof,
        "metrics": {
            "recent_items_count": total_recent,
            "classified_count": classified_count,
            "not_relevant_count": not_relevant_count,
            "unclassified_count": unclassified_count,
            "error_count": error_count,
            "below_threshold_count": below_threshold_count,
            "matched_count": matched_count,
        },
    }


# ---------------------------------------------------------------------------
# TREND-PARITY Wave 3：独立免过滤展示区 (Standalone Region)
# 语义：绕过关键词与 AI 个人兴趣过滤，但 RSS 仍然遵守新鲜度策略；
# Hotlist 保持真实排名与位次变化轨迹。
# ---------------------------------------------------------------------------


def get_standalone_items(path: str | None = None) -> dict[str, Any]:
    """获取独立展示区条目数据。"""
    target = path or db_path()
    store.initialize_store(target)
    cfg = store.get_native_intel_config(target)

    if not cfg.get("standalone_enabled", True):
        return {
            "status": "disabled",
            "items": [],
            "total": 0,
            "configured_sources": [],
            "freshness_excluded_count": 0,
        }

    source_ids = cfg.get("standalone_source_ids") or []
    if not source_ids:
        return {
            "status": "empty",
            "items": [],
            "total": 0,
            "configured_sources": [],
            "freshness_excluded_count": 0,
        }

    max_per_source = int(cfg.get("standalone_max_items", 20))
    plane = data_status(target)
    is_plane_stale = plane.get("status") == STATUS_STALE

    items_out: list[dict[str, Any]] = []
    freshness_excluded_count = 0

    # Wave 3 Standalone：真正 freshness-first，再做 per-source cap（PER_SOURCE_QUERY -> FRESHNESS -> CAP）
    for sid in source_ids:
        emitted_for_source = 0
        offset = 0
        batch_size = max(50, max_per_source)
        while emitted_for_source < max_per_source:
            batch = store.list_recent_items_by_source(
                sid, limit=batch_size, offset=offset, db_path=target
            )
            if not batch:
                break
            for it in batch:
                st = str(it.get("source_type") or "rss").lower()
                if st == "rss":
                    res = freshness.evaluate_item_freshness(
                        it,
                        global_enabled=bool(cfg.get("rss_freshness_enabled")),
                        global_max_age_days=int(cfg.get("rss_global_max_age_days", 1)),
                        source_max_age_days=it.get("source_max_age_days") if it.get("source_max_age_days") is not None else it.get("max_age_days"),
                    )
                    if not res.eligible:
                        freshness_excluded_count += 1
                        continue
                items_out.append(it)
                emitted_for_source += 1
                if emitted_for_source >= max_per_source:
                    break
            offset += len(batch)
            if len(batch) < batch_size:
                break

    # 补充实体与排名状态
    item_ids = [int(i["item_id"]) for i in items_out]
    entity_map = store.list_item_entities(item_ids, target)

    enriched: list[dict[str, Any]] = []
    for it in items_out:
        row = dict(it)
        iid = int(it["item_id"])
        row["entities"] = entity_map.get(iid, [])
        if it.get("source_type") == "hotlist":
            state = store.get_item_rank_state(iid, target)
            row["rank"] = state.get("current_rank")
            row["previous_rank"] = state.get("previous_rank")
            row["rank_delta"] = state.get("rank_delta")
            row["observation_count"] = int(it.get("observation_count") or 1)
            row["current_state"] = state.get("current_state") or ("STALE" if is_plane_stale else "ON_LIST")
        else:
            row["rank"] = None
            row["previous_rank"] = None
            row["rank_delta"] = None
            row["observation_count"] = int(it.get("observation_count") or 1)
            row["current_state"] = "NORMAL"
        enriched.append(row)

    return {
        "status": "normal",
        "items": enriched,
        "total": len(enriched),
        "configured_sources": source_ids,
        "freshness_excluded_count": freshness_excluded_count,
    }
