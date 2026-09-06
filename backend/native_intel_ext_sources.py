"""GitHub Trending, Hugging Face Daily Papers, and Hacker News fetchers.

These are Vibe-native parsers dispatched from run_fetch. They reuse the
existing Native Intel item shape. They do not invent a second source_type,
hotness score, or GitHub Search fallback.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import native_intel_store as store
import newsradar

GITHUB_TRENDING_URL = "https://github.com/trending?since=daily"
HF_DAILY_PAPERS_URL = "https://huggingface.co/api/daily_papers"
HN_RSS_URL = "https://hnrss.org/frontpage"
HN_FIREBASE_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
_BEIJING = timezone(timedelta(hours=8))

_REPO_HREF = re.compile(r'href="(/[^/]+/[^/?"#]+)"')
_COUNT = re.compile(r"([\d,]+)")
_STARS_PERIOD = re.compile(
    r"([\d,]+)\s+stars?\s+(today|this week|this month)", re.IGNORECASE
)
_SPONSOR_LABEL = re.compile(r">\s*Sponsored?\s*</?", re.IGNORECASE)
_HN_ITEM_ID = re.compile(r"news\.ycombinator\.com/item\?id=(\d+)", re.IGNORECASE)


def is_github_trending(source: dict[str, Any]) -> bool:
    url = str(source.get("url") or "")
    return "github.com/trending" in url


def is_hf_daily_papers(source: dict[str, Any]) -> bool:
    url = str(source.get("url") or "")
    return "huggingface.co" in url and "daily_papers" in url


def is_hacker_news(source: dict[str, Any]) -> bool:
    url = str(source.get("url") or "")
    return "hnrss.org" in url


def _classify_error(exc: BaseException) -> tuple[str, str]:
    name = type(exc).__name__
    if isinstance(exc, TimeoutError) or (
        isinstance(exc, (urllib.error.URLError, OSError)) and "timed out" in str(exc).lower()
    ):
        return store.ERROR_KIND_TIMEOUT, name
    if isinstance(exc, urllib.error.HTTPError):
        return store.ERROR_KIND_HTTP, name
    if isinstance(exc, urllib.error.URLError):
        cause = exc.reason
        if isinstance(cause, OSError) and "timed out" in str(cause).lower():
            return store.ERROR_KIND_TIMEOUT, name
        return store.ERROR_KIND_NETWORK, name
    if isinstance(exc, (json.JSONDecodeError, ValueError, TypeError, KeyError)):
        return store.ERROR_KIND_PARSE, name
    return store.ERROR_KIND_UNKNOWN, name


def _http_get(url: str, *, timeout: int, accept: str, proxy_url: str | None = None) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("unsupported url scheme")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": newsradar.UA,
            "Accept": accept,
        },
    )
    if proxy_url:
        handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        opener = urllib.request.build_opener(handler)
        with opener.open(req, timeout=timeout) as resp:
            return resp.read()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_int(raw: str | None) -> int | None:
    if not raw:
        return None
    digits = raw.replace(",", "").strip()
    if not digits.isdigit():
        return None
    return int(digits)


def parse_github_trending_html(
    html: str,
    source: dict[str, Any],
    redline: list[str],
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """Parse GitHub Trending HTML. Sponsored rows are dropped, not ranked."""
    text = html or ""
    articles = re.findall(
        r"<article\b[^>]*class=\"[^\"]*Box-row[^\"]*\"[^>]*>(.*?)</article>",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not articles:
        return [], store.ERROR_KIND_PARSE, "GitHubTrendingUnparseable"

    source_id = str(source.get("source_id") or "tech-github-trending")
    items: list[dict[str, Any]] = []
    upstream_rank = 0
    for article in articles:
        if _SPONSOR_LABEL.search(article):
            continue
        repo = None
        for match in _REPO_HREF.finditer(article):
            href = match.group(1)
            parts = href.strip("/").split("/")
            if len(parts) == 2 and parts[0] not in {"topics", "settings", "orgs", "ads", "sponsors"}:
                repo = "/".join(parts)
                break
        if not repo:
            continue
        upstream_rank += 1
        title = repo
        desc_match = re.search(
            r"<p\b[^>]*>(.*?)</p>", article, flags=re.IGNORECASE | re.DOTALL
        )
        description = ""
        if desc_match:
            description = re.sub(r"<[^>]+>", "", desc_match.group(1))
            description = re.sub(r"\s+", " ", description).strip()
        lang_match = re.search(
            r'itemprop="programmingLanguage"[^>]*>([^<]+)',
            article,
            flags=re.IGNORECASE,
        )
        language = lang_match.group(1).strip() if lang_match else None
        stars_total = None
        forks_total = None
        star_link = re.search(
            r'href="/' + re.escape(repo) + r'/stargazers"[^>]*>(.*?)</a>',
            article,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if star_link:
            nums = _COUNT.findall(star_link.group(1).replace("\n", " "))
            if nums:
                stars_total = _parse_int(nums[-1])
        fork_link = re.search(
            r'href="/' + re.escape(repo) + r'/forks"[^>]*>(.*?)</a>',
            article,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if fork_link:
            nums = _COUNT.findall(fork_link.group(1).replace("\n", " "))
            if nums:
                forks_total = _parse_int(nums[-1])
        period_match = _STARS_PERIOD.search(article)
        stars_period = _parse_int(period_match.group(1)) if period_match else None
        blob = f"{title} {description}".lower()
        if any(keyword in blob for keyword in redline):
            continue
        url_value = f"https://github.com/{repo}"
        items.append(
            {
                "item_key": f"{source_id}:{url_value}",
                "canonical_url": url_value,
                "url": url_value,
                "title": title,
                "title_key": newsradar._normalize_title(title),
                "summary": description,
                "hint": source.get("hint") or "tech",
                "published_at": None,
                "published_ts": 0,
                "rank": upstream_rank,
                "source_facts": {
                    "stars_total": stars_total,
                    "forks_total": forks_total,
                    "stars_period": stars_period,
                    "language": language,
                },
            }
        )
    if upstream_rank == 0:
        return [], store.ERROR_KIND_PARSE, "GitHubTrendingUnparseable"
    return items, None, None


def fetch_github_trending(
    source: dict[str, Any],
    *,
    timeout: int,
    redline: list[str],
    proxy_url: str | None = None,
    html: str | None = None,
    **_ignored: Any,
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    url = str(source.get("url") or GITHUB_TRENDING_URL)
    if html is None:
        try:
            raw = _http_get(
                url, timeout=timeout, accept="text/html,application/xhtml+xml", proxy_url=proxy_url
            )
        except Exception as exc:  # noqa: BLE001 - source failure is isolated
            kind, detail = _classify_error(exc)
            return [], kind, detail
        html = raw.decode("utf-8", errors="replace")
    return parse_github_trending_html(html, source, redline)


def _author_names(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    names: list[str] = []
    for author in value:
        if isinstance(author, str) and author.strip():
            names.append(author.strip())
        elif isinstance(author, dict):
            name = str(author.get("name") or author.get("fullname") or "").strip()
            if name:
                names.append(name)
    return ", ".join(names)


def parse_hf_daily_papers(
    payload: Any,
    source: dict[str, Any],
    redline: list[str],
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    if not isinstance(payload, list):
        return [], store.ERROR_KIND_PARSE, "HfDailyPapersInvalid"
    source_id = str(source.get("source_id") or "ai-hugging-face-daily-papers")
    items: list[dict[str, Any]] = []
    invalid = 0
    for raw in payload:
        if not isinstance(raw, dict):
            invalid += 1
            continue
        paper_obj = raw.get("paper")
        paper: dict[str, Any] = paper_obj if isinstance(paper_obj, dict) else {}
        paper_id = str(paper.get("id") or raw.get("id") or "").strip()
        title = str(raw.get("title") or paper.get("title") or "").strip()
        if not paper_id or not title:
            invalid += 1
            continue
        summary = str(raw.get("summary") or paper.get("summary") or "").strip()
        authors = _author_names(paper.get("authors") or raw.get("authors"))
        published = raw.get("publishedAt") or paper.get("publishedAt")
        published_at = str(published).strip() if published else None
        published_ts = 0
        if published_at:
            try:
                from datetime import datetime

                published_ts = int(
                    datetime.fromisoformat(published_at.replace("Z", "+00:00")).timestamp()
                )
            except (TypeError, ValueError):
                published_ts = 0
        hf_url = f"https://huggingface.co/papers/{paper_id}"
        arxiv_url = f"https://arxiv.org/abs/{paper_id}"
        github_repo = (
            paper.get("githubRepo")
            or paper.get("github_repo")
            or raw.get("githubRepo")
            or raw.get("github_repo")
        )
        github_repo_s = str(github_repo).strip() if github_repo else None
        github_stars = paper.get("githubStars") or raw.get("githubStars")
        if github_stars is not None and not isinstance(github_stars, int):
            github_stars = _parse_int(str(github_stars))
        upvotes = raw.get("upvotes")
        if upvotes is None:
            upvotes = paper.get("upvotes")
        if upvotes is not None and not isinstance(upvotes, int):
            upvotes = _parse_int(str(upvotes))
        comments = raw.get("numComments")
        if comments is None:
            comments = paper.get("numComments")
        if comments is not None and not isinstance(comments, int):
            comments = _parse_int(str(comments))
        blob = f"{title} {summary}".lower()
        if any(keyword in blob for keyword in redline):
            continue
        extra = f"Authors: {authors}" if authors else ""
        full_summary = "\n".join(part for part in (summary, extra) if part)
        items.append(
            {
                "item_key": f"{source_id}:hf-paper:{paper_id}",
                "canonical_url": hf_url,
                "url": hf_url,
                "title": title,
                "title_key": newsradar._normalize_title(title),
                "summary": full_summary,
                "hint": source.get("hint") or "ai",
                "published_at": published_at,
                "published_ts": published_ts,
                "rank": None,
                "source_facts": {
                    "upvotes": upvotes,
                    "num_comments": comments,
                    "github_stars": github_stars,
                    "github_repo": github_repo_s,
                    "arxiv_url": arxiv_url,
                },
            }
        )
    if payload and not items and invalid == len(payload):
        return [], store.ERROR_KIND_PARSE, "HfDailyPapersUnparseable"
    return items, None, None


def fetch_hf_daily_papers(
    source: dict[str, Any],
    *,
    timeout: int,
    redline: list[str],
    proxy_url: str | None = None,
    payload: Any = None,
    **_ignored: Any,
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    url = str(source.get("url") or HF_DAILY_PAPERS_URL)
    if payload is None:
        try:
            raw = _http_get(url, timeout=timeout, accept="application/json", proxy_url=proxy_url)
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001 - source failure is isolated
            kind, detail = _classify_error(exc)
            return [], kind, detail
    return parse_hf_daily_papers(payload, source, redline)


def _hn_story_id(*candidates: str) -> int | None:
    for raw in candidates:
        match = _HN_ITEM_ID.search(raw or "")
        if match:
            return int(match.group(1))
    return None


def _hn_discussion_url(story_id: int) -> str:
    return f"https://news.ycombinator.com/item?id={story_id}"


def parse_hn_rss(
    xml_text: str,
    source: dict[str, Any],
    redline: list[str],
    *,
    per: int = 30,
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    try:
        root = ET.fromstring(xml_text or "")
    except ET.ParseError:
        return [], store.ERROR_KIND_PARSE, "HnRssUnparseable"

    source_id = str(source.get("source_id") or "tech-hacker-news")
    items: list[dict[str, Any]] = []
    for node in root.iter():
        if newsradar._local(node.tag) not in ("item", "entry"):
            continue
        if len(items) >= per:
            break
        title = ""
        url = ""
        summary = ""
        raw_time = ""
        comments = ""
        guid = ""
        for child in node:
            tag = newsradar._local(child.tag)
            text = (child.text or "").strip()
            if tag == "title" and not title:
                title = text
            elif tag == "link" and not url:
                url = child.get("href") or text
            elif tag == "comments" and not comments:
                comments = child.get("href") or text
            elif tag == "guid" and not guid:
                guid = text
            elif tag in ("pubDate", "published", "updated", "date") and not raw_time:
                raw_time = text
            elif tag in ("description", "summary", "content") and not summary:
                summary = newsradar._strip_html(text)[:300]
        if not title:
            continue
        blob = f"{title} {summary}".lower()
        if any(keyword in blob for keyword in redline):
            continue
        story_id = _hn_story_id(comments, guid, url, summary)
        discussion_url = _hn_discussion_url(story_id) if story_id else (comments or None)
        published_at: str | None = None
        published_ts = 0
        parsed = newsradar._parse_dt(raw_time)
        if parsed is not None:
            published_at = parsed.astimezone(_BEIJING).isoformat()
            published_ts = int(parsed.timestamp())
        canonical_url = newsradar._normalize_url(url) if url else ""
        if story_id:
            item_key = f"{source_id}:hn:{story_id}"
            if not canonical_url or "news.ycombinator.com/item" in canonical_url:
                canonical_url = discussion_url or canonical_url
        else:
            item_key = canonical_url or f"title:{newsradar._normalize_title(title)}"
        items.append(
            {
                "item_key": item_key,
                "canonical_url": canonical_url or url or discussion_url,
                "url": url or canonical_url or discussion_url,
                "title": title,
                "title_key": newsradar._normalize_title(title),
                "summary": summary,
                "hint": source.get("hint") or "tech",
                "published_at": published_at,
                "published_ts": published_ts,
                "rank": None,
                "source_facts": {
                    "hn_story_id": story_id,
                    "score": None,
                    "num_comments": None,
                    "author": None,
                    "discussion_url": discussion_url,
                }
                if story_id
                else None,
            }
        )
    return items, None, None


def _hydrate_hn_item(item: dict[str, Any], payload: dict[str, Any]) -> None:
    facts = dict(item.get("source_facts") or {})
    story_id = payload.get("id") if payload.get("id") is not None else facts.get("hn_story_id")
    if story_id is not None:
        facts["hn_story_id"] = int(story_id) if not isinstance(story_id, int) else story_id
        if not isinstance(facts["hn_story_id"], int):
            parsed_id = _parse_int(str(story_id))
            if parsed_id is not None:
                facts["hn_story_id"] = parsed_id
    if payload.get("score") is not None:
        score = payload["score"]
        facts["score"] = score if isinstance(score, int) else _parse_int(str(score))
    descendants = payload.get("descendants")
    if descendants is not None:
        facts["num_comments"] = (
            descendants if isinstance(descendants, int) else _parse_int(str(descendants))
        )
    by = payload.get("by")
    if by:
        facts["author"] = str(by)
    sid = facts.get("hn_story_id")
    if isinstance(sid, int):
        facts["discussion_url"] = _hn_discussion_url(sid)
        prefix = str(item.get("item_key") or "tech-hacker-news:hn:0").split(":hn:")[0]
        item["item_key"] = f"{prefix}:hn:{sid}"
    firebase_url = payload.get("url")
    if firebase_url:
        item["url"] = str(firebase_url)
        item["canonical_url"] = newsradar._normalize_url(str(firebase_url)) or str(firebase_url)
    elif isinstance(sid, int):
        discussion = facts["discussion_url"]
        if not item.get("url") or "news.ycombinator.com/item" in str(item.get("url") or ""):
            item["url"] = discussion
        if not item.get("canonical_url") or "news.ycombinator.com/item" in str(
            item.get("canonical_url") or ""
        ):
            item["canonical_url"] = discussion
    time_raw = payload.get("time")
    if isinstance(time_raw, (int, float)):
        instant = datetime.fromtimestamp(int(time_raw), tz=timezone.utc)
        item["published_at"] = instant.strftime("%Y-%m-%dT%H:%M:%SZ")
        item["published_ts"] = int(time_raw)
    item["rank"] = None
    item["source_facts"] = facts


def fetch_hacker_news(
    source: dict[str, Any],
    *,
    timeout: int,
    redline: list[str],
    proxy_url: str | None = None,
    per: int = 30,
    rss_xml: str | None = None,
    item_loader: Callable[[int], Any] | None = None,
    **_ignored: Any,
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    url = str(source.get("url") or HN_RSS_URL)
    if rss_xml is None:
        try:
            raw = _http_get(
                url,
                timeout=timeout,
                accept="application/rss+xml,application/xml,text/xml,*/*",
                proxy_url=proxy_url,
            )
            rss_xml = raw.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - RSS discovery failure is the source failure
            kind, detail = _classify_error(exc)
            return [], kind, detail
    items, kind, detail = parse_hn_rss(rss_xml, source, redline, per=per)
    if kind is not None:
        return items, kind, detail

    def _load(story_id: int) -> Any:
        if item_loader is not None:
            return item_loader(story_id)
        raw = _http_get(
            HN_FIREBASE_ITEM_URL.format(story_id=story_id),
            timeout=timeout,
            accept="application/json",
            proxy_url=proxy_url,
        )
        return json.loads(raw.decode("utf-8", errors="replace"))

    for item in items:
        facts = item.get("source_facts") or {}
        story_id = facts.get("hn_story_id") if isinstance(facts, dict) else None
        if not isinstance(story_id, int):
            continue
        try:
            payload = _load(story_id)
        except Exception:  # noqa: BLE001 - enrichment must not fail the source
            continue
        if isinstance(payload, dict):
            _hydrate_hn_item(item, payload)
    return items, None, None
