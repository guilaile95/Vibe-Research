"""Native Intel 热榜抓取层（TREND-PARITY Wave 1）。

Vibe 自有的热榜 provider：把「公共热榜聚合 API 的当前榜单」归一化成与 RSS 相同的
条目形状，外加真实排名（rank = 榜单 1-based 序号）。

数据源：NewsNow 公共 HTTP API（`ourongxing/newsnow`，MIT 许可）。
上游参照（仅研究行为，不复制 GPL 代码）：`sansan0/TrendRadar` 的热榜平台清单与
「HTTPS + 域名白名单」防劫持思路；本模块为独立实现。

语义边界：
- ``status`` 仅接受 ``success`` / ``cache``（与上游观测到的契约一致）；
- ``rank`` 只写上游真实序号；抓取失败返回结构化错误，绝不伪造 rank；
- ``published_at``：上游不提供可靠发布时间 → 恒为 None，禁止用抓取时间顶替；
- 单平台失败由调用方（native_intel_service.run_fetch）按源隔离，不影响其他源。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

import native_intel_store as store
import newsradar

# NewsNow 公共实例（TrendRadar 默认同源；自部署实例可直接改 source url）
DEFAULT_API_BASE = "https://newsnow.busiyi.world/api/s"

# Wave 1 + Wave 1B 平台白名单：id → expected_domain（响应链接必须 HTTPS 且命中该域名及其子域）。
_PROVIDERS: dict[str, str] = {
    "cls-hot": "cls.cn",
    "wallstreetcn-hot": "wallstreetcn.com",
    "toutiao": "toutiao.com",
    "baidu": "baidu.com",
    "thepaper": "thepaper.cn",
    "bilibili-hot-search": "bilibili.com",
    "ifeng": "ifeng.com",
    "tieba": "baidu.com",
    "weibo": "weibo.com",
    "douyin": "douyin.com",
    "zhihu": "zhihu.com",
}

# 一次抓取保留的榜单长度上限（上游榜单通常 10~50 条；截断只影响展示宽度，
# 不影响排名语义——保留的是前 N 名真实排名）。
HOTLIST_MAX_ITEMS = 30


def build_source_url(platform: str) -> str:
    """平台 ID → 抓取 URL（source.url 存完整地址，来源表自描述）。"""
    return f"{DEFAULT_API_BASE}?id={urllib.parse.quote(platform)}&latest"


def platform_of(url: str) -> str | None:
    try:
        query = urllib.parse.urlsplit(url).query
        params = urllib.parse.parse_qs(query)
        values = params.get("id")
        return values[0] if values else None
    except ValueError:
        return None


def _classify_error(exc: BaseException) -> tuple[str, str]:
    """与 service 侧同口径的安全错误分类；detail 只存类名，不带 URL / 正文。"""
    name = type(exc).__name__
    if isinstance(exc, (TimeoutError, urllib.error.URLError)) and "timed out" in str(exc).lower():
        return store.ERROR_KIND_TIMEOUT, name
    if isinstance(exc, urllib.error.HTTPError):
        return store.ERROR_KIND_HTTP, name
    if isinstance(exc, urllib.error.URLError):
        cause = exc.reason
        if isinstance(cause, (TimeoutError, OSError)) and "timed out" in str(cause).lower():
            return store.ERROR_KIND_TIMEOUT, name
        return store.ERROR_KIND_NETWORK, name
    if isinstance(exc, (json.JSONDecodeError, ValueError, KeyError)):
        return store.ERROR_KIND_PARSE, name
    return store.ERROR_KIND_UNKNOWN, name


def _check_domain_safety(items: list[dict[str, Any]], expected_domain: str) -> str | None:
    """HTTPS + 域名（含子域）校验；返回第一个违例描述，None 表示安全。"""
    expected = expected_domain.lower().strip()
    if not expected:
        return None
    for item in items:
        url = str(item.get("url") or "")
        if not url:
            continue
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https":
            return f"non-https:{parsed.scheme}"
        hostname = (parsed.hostname or "").lower()
        if hostname != expected and not hostname.endswith("." + expected):
            return f"unexpected-host:{hostname}"
    return None


def _http_get_json(url: str, *, timeout: int, proxy_url: str | None = None) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": newsradar.UA,
            "Accept": "application/json, text/plain, */*",
        },
    )
    if proxy_url:
        handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        opener = urllib.request.build_opener(handler)
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def fetch_hotlist_items(
    source: dict[str, Any],
    *,
    timeout: int,
    redline: list[str],
    proxy_url: str | None = None,
    **_ignored: Any,
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """抓单个热榜源；返回 ``(items, error_kind, error_detail)``。

    items 与 RSS 抓取同形状（item_key/title/url/…），另带真实 ``rank``；
    失败时返回结构化错误，绝不返回「看似成功的空榜单」。
    """
    url = str(source.get("url") or "")
    platform = platform_of(url)
    if not platform:
        return [], store.ERROR_KIND_PARSE, "HotlistPlatformMissing"
    source_id = str(source.get("source_id") or "")
    if not source_id:
        source_id = f"hotlist-{platform}"
    expected_domain = _PROVIDERS.get(platform, "")
    if not expected_domain:
        # 未知平台：fail closed，不把它当空榜单
        return [], store.ERROR_KIND_PARSE, "HotlistPlatformUnsupported"

    try:
        if proxy_url:
            data = _http_get_json(url, timeout=timeout, proxy_url=proxy_url)
        else:
            data = _http_get_json(url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - 单源失败必须被隔离
        kind, detail = _classify_error(exc)
        return [], kind, detail

    status = str(data.get("status") or "")
    if status not in ("success", "cache"):
        return [], store.ERROR_KIND_PARSE, "HotlistStatusRejected"
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return [], store.ERROR_KIND_PARSE, "HotlistItemsInvalid"

    violation = _check_domain_safety(raw_items, expected_domain)
    if violation:
        # 域名校验不过 = 数据可疑，整平台丢弃（与「源失败」同语义，不当空榜）
        return [], store.ERROR_KIND_HTTP, "HotlistDomainViolation"

    now_iso = store.utc_now_iso()
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_items, 1):
        if len(items) >= HOTLIST_MAX_ITEMS:
            break
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        url_value = str(raw.get("url") or "").strip()
        canonical = newsradar._normalize_url(url_value)
        blob = title.lower()
        if any(keyword in blob for keyword in redline):
            continue
        base_key = canonical or f"title:{newsradar._normalize_title(title)}"
        items.append(
            {
                # 热榜条目没有可靠发布时间：published 恒未知，绝不伪造；
                # 排名身份以 SOURCE + ITEM 严格限定（hotlist-<platform>:...），杜绝跨平台污染
                "item_key": f"{source_id}:{base_key}",
                "canonical_url": canonical or url_value,
                "url": url_value or canonical,
                "title": title,
                "title_key": newsradar._normalize_title(title),
                "summary": "",
                "hint": source.get("hint") or "",
                "published_at": None,
                "published_ts": 0,
                "rank": index,
            }
        )
    return items, None, None
