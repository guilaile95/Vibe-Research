"""每日复盘 / 持仓建议对外错误文案清洗（纯函数，不联网）。

禁止向前端或 AI context 泄漏 ProxyError、完整 URL、代理地址、traceback 等。
"""

from __future__ import annotations

import re
from typing import Any

# 对外统一文案
SAFE_BREADTH_UNAVAILABLE = "全市场行情数据获取失败，市场广度暂不可用。"
SAFE_MARKET_COMPONENT_UNAVAILABLE = "外部行情数据获取失败，部分市场数据暂不可用。"
SAFE_REFRESH_FAILED = "市场数据刷新失败，请稍后重试"
SAFE_ADVICE_MARKET_UNAVAILABLE = "市场核心数据暂不可用，无法生成可靠的持仓操作建议"

_LEAK_HINTS = (
    "httpsconnectionpool",
    "httpconnectionpool",
    "proxyerror",
    "proxymanager",
    "max retries exceeded",
    "remotedisconnected",
    "connection aborted",
    "connectionerror",
    "newconnectionerror",
    "connecttimeout",
    "readtimeout",
    "traceback",
    "urllib3",
    "requests.exceptions",
    "sslerror",
    "chunkedencodingerror",
    "a_share_snapshot",
    "unable to connect to proxy",
    "cannot connect to proxy",
)

_URL_RE = re.compile(r"https?://\S+", re.I)
_IPV4_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_HOST_PORT_RE = re.compile(r"\b[\w.-]+\.(?:com|cn|net|org)(?::\d+)?\b", re.I)


def looks_like_leaky_error(text: str) -> bool:
    if not text or not isinstance(text, str):
        return False
    lower = text.lower()
    if any(h in lower for h in _LEAK_HINTS):
        return True
    if _URL_RE.search(text):
        return True
    if "ProxyError" in text or "HTTPSConnectionPool" in text:
        return True
    return False


def _is_breadth_related(text: str) -> bool:
    lower = text.lower()
    return any(
        k in lower
        for k in (
            "breadth",
            "a_share",
            "snapshot",
            "市场广度",
            "全市场",
            "clist",
        )
    ) or "a_share_snapshot" in text


def sanitize_public_message(text: Any, *, default: str = SAFE_MARKET_COMPONENT_UNAVAILABLE) -> str:
    """清洗单条对外文案；网络/代理类异常替换为安全固定句。"""
    if text is None:
        return default
    s = str(text).strip()
    if not s:
        return default
    if looks_like_leaky_error(s):
        if _is_breadth_related(s):
            return SAFE_BREADTH_UNAVAILABLE
        return default
    # 即便不像异常，也去掉 URL / IP
    cleaned = _URL_RE.sub("", s)
    cleaned = _IPV4_RE.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned or default


def sanitize_warning_list(warnings: Any, *, component_label: str = "") -> list[str]:
    """清洗 warning 列表；去重并保留顺序。"""
    out: list[str] = []
    seen: set[str] = set()
    for w in warnings if isinstance(warnings, list) else []:
        if not isinstance(w, str):
            continue
        msg = sanitize_public_message(w)
        # 组件前缀场景：若原文带 [市场广度] 且被替换为全市场句，保持可读
        if component_label and msg == SAFE_BREADTH_UNAVAILABLE and "广度" in component_label:
            msg = SAFE_BREADTH_UNAVAILABLE
        if msg and msg not in seen:
            seen.add(msg)
            out.append(msg)
    return out


def sanitize_review_public_fields(review: dict) -> dict:
    """就地清洗复盘包中可能泄漏的 warnings（返回同一 dict 便于链式调用）。"""
    if not isinstance(review, dict):
        return review
    if isinstance(review.get("warnings"), list):
        review["warnings"] = sanitize_warning_list(review["warnings"])

    def _walk_envelope(env: Any) -> None:
        if not isinstance(env, dict):
            return
        if isinstance(env.get("warnings"), list):
            env["warnings"] = sanitize_warning_list(env["warnings"])

    me = review.get("market_environment")
    if isinstance(me, dict):
        for k in ("indices", "global_indices", "breadth"):
            _walk_envelope(me.get(k))
    _walk_envelope(review.get("short_term_emotion"))
    ca = review.get("capital_activity")
    if isinstance(ca, dict):
        _walk_envelope(ca.get("turnover_top"))
    sr = review.get("sector_rotation")
    if isinstance(sr, dict):
        for k in ("industry", "concept", "region"):
            _walk_envelope(sr.get(k))
    return review
