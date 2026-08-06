"""Tushare Pro 最小 HTTPS JSON 客户端（BK-11 ingestion v0.2）。

仅使用标准库实现；不引入 Tushare SDK、Pandas 或新网络依赖。

安全边界：

- Endpoint 固定为 ``https://api.tushare.pro``，不接受调用方自定义 URL；
- API name 使用固定 allowlist（daily / suspend_d / stk_limit /
  stock_basic）；
- Token 只从环境变量 ``TUSHARE_TOKEN`` 读取；不落盘、不打印、不进日志、
  不进异常文本；
- 响应严格校验 code/msg/data/fields/items；code != 0 失败关闭；
  code=2002 映射为稳定的权限异常；
- 对外异常不包含 provider 原始错误文本、URL、Token、路径或 traceback；
- 仅对网络瞬时错误与 HTTP 5xx 做有界重试；权限/参数/结构错误不重试；
- KeyboardInterrupt / SystemExit / GeneratorExit 自然传播；
- 输入 params 与 fields 不被修改。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

ENDPOINT = "https://api.tushare.pro"
ENV_TOKEN = "TUSHARE_TOKEN"

ALLOWED_API_NAMES = frozenset({"daily", "suspend_d", "stk_limit", "stock_basic"})

_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 30.0
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024  # 64MB
_MAX_ROWS = 200_000
_MAX_RETRIES = 2  # 网络瞬时错误 / HTTP 5xx 的额外重试次数
_RETRY_BACKOFF_SECONDS = (1.0, 2.0)
_UA = "vibe-research-bk11/0.2"


class TushareClientError(RuntimeError):
    """客户端基础异常（对外文案稳定，不含原始错误）。"""


class TushareCredentialMissing(TushareClientError):
    """TUSHARE_TOKEN 环境变量缺失。"""


class TusharePermissionDenied(TushareClientError):
    """Tushare 返回 code=2002（权限不足）。"""


class TushareProtocolError(TushareClientError):
    """参数/结构错误（code 非 0 且非 2002，或响应结构非法）。"""


class TushareTransportError(TushareClientError):
    """网络瞬时错误或 HTTP 5xx（重试后仍失败）。"""


def _token_from_env() -> str:
    token = os.environ.get(ENV_TOKEN, "").strip()
    if not token:
        raise TushareCredentialMissing("TUSHARE_TOKEN 未配置")
    return token


def _safe_message(payload: Any) -> str:
    """把 provider 原始 msg 映射为稳定公开文案（绝不透传原始文本）。"""
    return "Tushare 接口返回非零状态码"


def _parse_response(raw: bytes, api_name: str) -> list[dict[str, Any]]:
    """精确校验 code/msg/data/fields/items，返回普通 dict 行。"""
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise TushareProtocolError("Tushare 响应超过大小上限")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise TushareProtocolError("Tushare 响应不是合法 JSON") from None
    if type(payload) is not dict:
        raise TushareProtocolError("Tushare 响应结构非法")
    code = payload.get("code")
    if code == 2002:
        raise TusharePermissionDenied("Tushare 权限不足")
    if code != 0:
        raise TushareProtocolError(_safe_message(payload))
    data = payload.get("data")
    if data is None:
        raise TushareProtocolError("Tushare 响应缺少 data")
    if type(data) is not dict:
        raise TushareProtocolError("Tushare 响应 data 结构非法")
    fields = data.get("fields")
    items = data.get("items")
    if type(fields) is not list or not fields:
        raise TushareProtocolError("Tushare 响应缺少 fields")
    if type(items) is not list:
        raise TushareProtocolError("Tushare 响应缺少 items")
    if len(set(fields)) != len(fields):
        raise TushareProtocolError("Tushare 响应 fields 重复")
    if len(items) > _MAX_ROWS:
        raise TushareProtocolError("Tushare 响应行数超过上限")
    if any(not isinstance(f, str) for f in fields):
        raise TushareProtocolError("Tushare 响应 fields 非法")
    rows: list[dict[str, Any]] = []
    for item in items:
        if type(item) is not list or len(item) != len(fields):
            raise TushareProtocolError("Tushare 响应行长度与字段不一致")
        rows.append(dict(zip(fields, item)))
    return rows


def _is_retryable_http_status(status: int) -> bool:
    return 500 <= status <= 599


class TushareClient:
    """无状态 Tushare Pro 客户端（Token 每次从环境变量读取）。"""

    def __init__(
        self,
        *,
        endpoint: str = ENDPOINT,
        token_env: str = ENV_TOKEN,
        connect_timeout: float = _CONNECT_TIMEOUT,
        read_timeout: float = _READ_TIMEOUT,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        if endpoint != ENDPOINT:
            raise ValueError("custom endpoint is not allowed")
        if token_env != ENV_TOKEN:
            raise ValueError("custom token env is not allowed")
        self._endpoint = endpoint
        self._token_env = token_env
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._max_retries = max_retries

    def query(
        self,
        api_name: str,
        params: dict[str, Any],
        fields: str | None = None,
    ) -> list[dict[str, Any]]:
        """调用 allowlist 内接口，返回普通 dict 行列表（不修改输入）。"""
        if api_name not in ALLOWED_API_NAMES:
            raise TushareProtocolError(f"不允许的 Tushare 接口：{api_name}")
        if type(params) is not dict:
            raise TushareProtocolError("Tushare params 必须为 dict")
        if fields is not None and (not isinstance(fields, str) or not fields.strip()):
            raise TushareProtocolError("Tushare fields 必须为非空字符串")
        token = _token_from_env()
        body = {
            "api_name": api_name,
            "token": token,
            "params": dict(params),
            "fields": fields,
        }
        payload_bytes = json.dumps(
            body, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint,
            data=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "User-Agent": _UA,
                "Accept": "application/json",
            },
            method="POST",
        )

        attempt = 0
        while True:
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self._connect_timeout + self._read_timeout,
                ) as resp:
                    raw = resp.read(_MAX_RESPONSE_BYTES + 1)
                    status = getattr(resp, "status", 200)
                if status not in (200,):
                    if _is_retryable_http_status(status) and attempt < self._max_retries:
                        attempt += 1
                        time.sleep(_RETRY_BACKOFF_SECONDS[
                            min(attempt - 1, len(_RETRY_BACKOFF_SECONDS) - 1)])
                        continue
                    raise TushareTransportError("Tushare 服务暂时不可用")
                return _parse_response(raw, api_name)
            except (TushareClientError, TushareCredentialMissing,
                    TusharePermissionDenied, TushareProtocolError):
                raise
            except (KeyboardInterrupt, SystemExit, GeneratorExit):
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError,
                    OSError) as exc:
                if attempt < self._max_retries:
                    attempt += 1
                    time.sleep(_RETRY_BACKOFF_SECONDS[
                        min(attempt - 1, len(_RETRY_BACKOFF_SECONDS) - 1)])
                    continue
                raise TushareTransportError("Tushare 网络请求失败") from exc
