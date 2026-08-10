"""HiThink LIVE_SMOKE probe harness v0.1-R1 —— probe-only，绝不进入生产路由。

用途（DS-H1）：
- 对官方 HiThink（同花顺）金融数据服务做孤立 LIVE_SMOKE；
- Provider response = Observation，不是 Canonical Fact；
- 本模块不修改任何生产 provider / routing / data-health / scheduler；
- 凭据只从环境变量 ``HITHINK_FINANCE_API_KEY`` 读取，任何输出路径都不含 key。

R1 增强：
- 嵌套 ``data.item[]`` 观测（meta + 首条 item 字段/类型/样本）；
- 递归 secret 键清洗（任意深度剥离 api_key/token/secret/authorization 等）；
- snapshot 双标的矩阵；
- historical 2 标的 × 2 时间窗矩阵；
- adjust none/forward/backward 矩阵；
- limit-up 显式历史 ``date_ms`` 请求；
- 非交易日（周六）行为探测。

端点与参数来自 2026-08-10 对官方仓库
``HiThink-Tech/Financial-API``（HEAD f8cdea908469b1b3b8bfb88dbb4d4a3959b1905c）
``docs/api/*.md`` 的独立核验（见 docs/data/HITHINK_LIVE_SMOKE_V01.md）。

安全约束：
- API key 只进 header ``X-api-key``，绝不进入 observation / fingerprint / 日志；
- fingerprint 只含 provider / endpoint / non-secret query / time；
- 响应只记录字段名 / 类型 / 样本 / 状态 / request_id / 错误码，不落盘原始大文件。

CLI:
    python -m tools.hithink_live_probe run --output obs.json
    python -m tools.hithink_live_probe verify-source   # 打印已核实的来源事实
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

# ---- 官方端点（2026-08-10 核验，docs/api/endpoints-*.md）----
BASE_URL = "https://fuyao.aicubes.cn"
API_KEY_ENV = "HITHINK_FINANCE_API_KEY"


def _ms(date_str: str) -> int:
    """YYYY-MM-DD → Asia/Shanghai 00:00 毫秒 Unix 时间戳（探测参数用）。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return int(dt.timestamp() * 1000)


# ---- 单探测端点矩阵（A–F 六类各至少一个）----
ENDPOINTS: dict[str, dict] = {
    "symbol_search": {"path": "/api/meta/tickers/search", "query": {"q": "600519", "limit": 1}},
    "snapshot_quote": {"path": "/api/a-share/prices/snapshot",
                       "query": {"thscodes": "600519.SH,000001.SZ"}},
    "income_statement": {"path": "/api/a-share/financials/income-statements",
                         "query": {"thscode": "600519.SH", "period": "annual", "limit": 2}},
    "index_constituents": {"path": "/api/a-share-index/constituents/ths-stock-list",
                           "query": {"thscode": "000300.SH"}},  # 沪深300标准指数成分（文档：thscode 需 .TI/.SH 后缀）
    "trading_calendar": {"path": "/api/a-share/calendar/trading-days", "query": {}},
    "valuation_snapshot": {"path": "/api/a-share/valuations/snapshot",
                           "query": {"thscodes": "600519.SH"}},
}

# ---- R1 矩阵探测 ----
# C. historical：2 标的 × 2 时间窗
HISTORICAL_MATRIX: list[tuple[str, str]] = [
    ("600519.SH", "2026-07-01", "2026-07-10"),
    ("600519.SH", "2026-06-01", "2026-06-12"),
    ("000001.SZ", "2026-07-01", "2026-07-10"),
    ("000001.SZ", "2026-06-01", "2026-06-12"),
]

# C. adjust 矩阵：none / forward(前复权) / backward(后复权)
ADJUSTMENT_MATRIX: list[tuple[str, str]] = [  # (adjust, label)
    ("none", "adjust_none"),
    ("forward", "adjust_forward"),
    ("backward", "adjust_backward"),
]

# 2026-08-07 = Friday（交易日）；2026-08-08 = Saturday（非交易日，已核验星期）
TRADING_DAY_DATE = "2026-08-07"
NON_TRADING_DAY_DATE = "2026-08-08"

LIMIT_UP_HISTORICAL_SPEC = {
    "path": "/api/a-share/special-data/limit-up-pool",
    "query": {"date_ms": _ms(TRADING_DAY_DATE), "page": 1, "size": 5},
}

NON_TRADING_DAY_SPEC = {
    "path": "/api/a-share/prices/historical",
    "query": {"thscode": "600519.SH", "interval": "1d", "adjust": "none",
              "start": _ms(NON_TRADING_DAY_DATE), "end": _ms(NON_TRADING_DAY_DATE)},
}

# 官方错误码 → 确定性分类（docs/api/README.md 核验）
ERROR_CODE_CLASS = {
    1001: "missing_parameter",
    1002: "invalid_parameter_format",
    1003: "parameter_out_of_range",
    1004: "parameter_conflict",
    2001: "unauthenticated",
    2003: "no_permission_or_invalid_key",
    3001: "instrument_not_found",
    3002: "data_not_ready",
    3004: "target_type_unsupported",
    4001: "rate_limited",
    5001: "server_error",
    5002: "server_error",
    5003: "server_error",
}

_NON_SECRET_QUERY_KEYS = (
    "q", "limit", "offset", "thscodes", "thscode", "ths_code", "interval", "start", "end",
    "adjust", "period", "report", "page", "size", "date", "date_ms", "from",
    "to", "board_type", "sort_field", "sort_dir",
)


def _normalize_key(key: str) -> str:
    return str(key).strip().lower().replace(" ", "").replace("_", "").replace("-", "")


# 任意深度都要剥离的 secret 键名（归一化后比较；集合本身也存归一化形式）。
# 必须在 _normalize_key 定义之后求值。
_SECRET_KEY_NAMES = frozenset(
    _normalize_key(name) for name in (
        "api_key", "apikey", "token", "access_token", "refresh_token", "secret",
        "secret_key", "authorization", "x-api-key", "key", "password", "credential",
    )
)


def api_key() -> str | None:
    """只读环境变量中的 API key；缺失返回 None。绝不打印。"""
    raw = os.environ.get(API_KEY_ENV, "").strip()
    return raw or None


# ---------------------------------------------------------------------------
# 观测模型（中性证据，不定义生产 Canonical 类型）
# ---------------------------------------------------------------------------

@dataclass
class ProbeObservation:
    """单个端点的 sanitized 观测。只含字段名/类型/样本/元数据，绝不含 key。"""
    dataset_id: str
    endpoint: str
    http_status: int | None
    envelope_code: int | None
    envelope_message: str | None
    request_id: str | None
    fingerprint: str
    sample_fields: dict = field(default_factory=dict)
    error_class: str | None = None
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "dataset_id": self.dataset_id,
            "endpoint": self.endpoint,
            "http_status": self.http_status,
            "envelope_code": self.envelope_code,
            "envelope_message": self.envelope_message,
            "request_id": self.request_id,
            "fingerprint": self.fingerprint,
            "error_class": self.error_class,
            "sample_fields": self.sample_fields,
            "fetched_at": self.fetched_at,
        }


def request_fingerprint(*, provider: str, endpoint: str, query: dict) -> str:
    """确定性请求指纹：只含 provider / endpoint / 规范化 query / 时间范围。

    query 只允许 _NON_SECRET_QUERY_KEYS 中的键；任何未知/secret 键都会被拒绝
    （fail closed），保证 API key 永远无法进入 fingerprint。
    """
    allowed = {k: v for k, v in query.items() if k in _NON_SECRET_QUERY_KEYS}
    denied = sorted(set(query) - set(_NON_SECRET_QUERY_KEYS))
    if denied:
        raise ValueError(f"non-secret query keys only, denied: {denied}")
    canonical = json.dumps({"provider": provider, "endpoint": endpoint, "query": allowed},
                           sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def classify_envelope(code: int | None) -> str | None:
    """官方业务错误码 → 分类；code 0 / None 视为业务成功。"""
    if code is None or code == 0:
        return None
    return ERROR_CODE_CLASS.get(code, "unknown_code")


def _is_secret_key(key: str) -> bool:
    return _normalize_key(key) in _SECRET_KEY_NAMES


_MAX_STR = 120
_MAX_LIST = 3
_MAX_DEPTH = 5


def _sanitize_value(value: Any, depth: int = 0) -> Any:
    """递归清洗任意值：secret 键剥离、长值截断、深度限制；保留 null/0/""/[] 区分。"""
    if depth > _MAX_DEPTH:
        return {"type": type(value).__name__, "value": "<depth-limit>"}
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if _is_secret_key(key):
                continue  # 递归：任意深度 secret 键都不进入观测
            out[key] = _sanitize_value(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        items = [_sanitize_value(item, depth + 1) for item in list(value)[:_MAX_LIST]]
        total = len(value)
        return {"_list": items, "_count": total}
    if value is None:
        return {"type": "NoneType", "value": None}
    return {"type": type(value).__name__, "value": str(value)[:_MAX_STR]}


def _extract_data_sample(payload: Any) -> dict:
    """从 data 提取字段名/类型/样本：处理嵌套 item[]（meta + 首条 item）。

    返回结构（全部经递归清洗，secret 键已剥离）：
    - data 为 dict 且含 item/items 列表 → {"_meta": <非 item 字段>, "item[0]": <首条>}
    - data 为 list → {"_list": ..., "_count": ...}
    - data 为 dict → 清洗后的字段样本
    - 其他 → 类型 + 截断值
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if data is None:
        return {}
    if isinstance(data, dict) and any(k in data for k in ("item", "items")):
        meta = {k: v for k, v in data.items() if k not in ("item", "items")}
        items = data.get("item", data.get("items")) or []
        sample: dict[str, Any] = {"_meta": _sanitize_value(meta)}
        if isinstance(items, list) and items:
            sample["item[0]"] = _sanitize_value(items[0])
        sample["_count"] = len(items) if isinstance(items, list) else None
        return sample
    return _sanitize_value(data)


def probe_endpoint(dataset_id: str, spec: dict, key: str, *, timeout: int = 15) -> ProbeObservation:
    """执行一次端点探测并返回 sanitized observation。"""
    url = BASE_URL + spec["path"]
    query = dict(spec["query"])
    fp = request_fingerprint(provider="hithink", endpoint=spec["path"], query=query)
    try:
        resp = requests.get(url, params=query, headers={"X-api-key": key}, timeout=timeout)
    except requests.RequestException as exc:
        return ProbeObservation(dataset_id=dataset_id, endpoint=spec["path"], http_status=None,
                                envelope_code=None, envelope_message=None, request_id=None,
                                fingerprint=fp, error_class=f"transport:{type(exc).__name__}")
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    envelope_code = payload.get("code") if isinstance(payload, dict) else None
    obs = ProbeObservation(
        dataset_id=dataset_id,
        endpoint=spec["path"],
        http_status=resp.status_code,
        envelope_code=envelope_code,
        envelope_message=payload.get("message") if isinstance(payload, dict) else None,
        request_id=payload.get("request_id") if isinstance(payload, dict) else None,
        fingerprint=fp,
        sample_fields=_extract_data_sample(payload),
        error_class=classify_envelope(envelope_code),
    )
    return obs


def run_probe(key: str) -> dict:
    observations: dict[str, dict] = {}

    def _probe(dataset_id: str, spec: dict) -> None:
        observations[dataset_id] = probe_endpoint(dataset_id, spec, key).to_dict()

    for dataset_id, spec in ENDPOINTS.items():
        _probe(dataset_id, spec)

    # historical 2×2 矩阵
    for index, (thscode, start, end) in enumerate(HISTORICAL_MATRIX, start=1):
        _probe(f"historical_{index}", {
            "path": "/api/a-share/prices/historical",
            "query": {"thscode": thscode, "interval": "1d", "adjust": "none",
                      "start": _ms(start), "end": _ms(end)},
        })

    # adjust 矩阵（单标的 3 模式）
    for adjust, label in ADJUSTMENT_MATRIX:
        _probe(label, {
            "path": "/api/a-share/prices/historical",
            "query": {"thscode": "600519.SH", "interval": "1d", "adjust": adjust,
                      "start": _ms("2026-07-01"), "end": _ms("2026-07-10")},
        })

    # limit-up 显式历史 date_ms
    _probe("limit_up_explicit_date", LIMIT_UP_HISTORICAL_SPEC)
    # 非交易日行为探测（周六）
    _probe("non_trading_day", NON_TRADING_DAY_SPEC)

    return {"observations": observations, "fetched_at": datetime.now(timezone.utc).isoformat()}


def verified_source() -> dict:
    """已独立核实的官方来源事实（2026-08-10）。"""
    return {
        "provider": "HiThink (Tonghuashun) Financial-API",
        "repository": "https://github.com/HiThink-Tech/Financial-API",
        "verified_commit_sha": "f8cdea908469b1b3b8bfb88dbb4d4a3959b1905c",
        "verified_at": "2026-08-10",
        "default_branch": "main",
        "license_spdx": "MIT",
        "docs_location": ["README.md", "docs/README.md", "docs/api/README.md",
                          "https://fuyao.aicubes.cn/llms-full.txt"],
        "api_base": "https://fuyao.aicubes.cn",
        "auth_method": "header X-api-key (env HITHINK_FINANCE_API_KEY)",
        "success_rule": "HTTP 200 AND envelope code == 0",
        "error_envelope": "{code, message, request_id, data}",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.hithink_live_probe",
                                     description="HiThink LIVE_SMOKE probe harness (probe-only)")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run probe matrix; requires HITHINK_FINANCE_API_KEY")
    run.add_argument("--output", help="write observations JSON to this path")
    sub.add_parser("verify-source", help="print verified official source facts")

    args = parser.parse_args(argv)
    if args.command == "verify-source":
        print(json.dumps(verified_source(), ensure_ascii=False, sort_keys=True, indent=2))
        return 0

    key = api_key()
    if key is None:
        print(json.dumps({"status": "BLOCKED_LIVE_AUTH",
                          "reason": f"{API_KEY_ENV} not set"}, ensure_ascii=False), file=sys.stderr)
        return 2
    result = run_probe(key)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
    else:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
