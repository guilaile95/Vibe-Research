"""HiThink LIVE_SMOKE probe harness v0.1 —— probe-only，绝不进入生产路由。

用途（DS-H1）：
- 对官方 HiThink（同花顺）金融数据服务做孤立 LIVE_SMOKE；
- Provider response = Observation，不是 Canonical Fact；
- 本模块不修改任何生产 provider / routing / data-health / scheduler；
- 凭据只从环境变量 ``HITHINK_FINANCE_API_KEY`` 读取，任何输出路径都不含 key。

端点与参数来自 2026-08-10 对官方仓库
``HiThink-Tech/Financial-API``（HEAD f8cdea908469b1b3b8bfb88dbb4d4a3959b1905c）
``docs/api/*.md`` 的独立核验（见 docs/data/HITHINK_LIVE_SMOKE_V01.md）。

安全约束：
- API key 只进 header ``X-api-key``，绝不进入 observation / fingerprint / 日志；
- fingerprint 只含 provider / endpoint / normalized symbol / non-secret query / time；
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

# 官方端点（2026-08-10 核验，docs/api/endpoints-*.md）----
BASE_URL = "https://fuyao.aicubes.cn"
API_KEY_ENV = "HITHINK_FINANCE_API_KEY"


def _ms(date_str: str) -> int:
    """YYYY-MM-DD → Asia/Shanghai 00:00 毫秒 Unix 时间戳（探测参数用）。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return int(dt.timestamp() * 1000)


# 矩阵端点：dataset_id -> (method, path, query 构建器说明)
ENDPOINTS = {
    "symbol_search": {"path": "/api/meta/tickers/search", "query": {"q": "600519", "limit": 1}},
    "snapshot_quote": {"path": "/api/a-share/prices/snapshot", "query": {"thscodes": "600519.SH,000001.SZ"}},
    "historical_daily": {"path": "/api/a-share/prices/historical",
                         "query": {"thscode": "600519.SH", "interval": "1d", "adjust": "none",
                                   "start": _ms("2026-07-01"), "end": _ms("2026-07-10")}},
    "income_statement": {"path": "/api/a-share/financials/income-statements",
                         "query": {"thscode": "600519.SH", "period": "annual", "limit": 2}},
    "index_constituents": {"path": "/api/a-share-index/constituents/ths-stock-list",
                           "query": {"ths_code": "885001"}},  # 概念/板块成员（当前快照）
    "limit_up_pool": {"path": "/api/a-share/special-data/limit-up-pool",
                      "query": {"page": 1, "size": 5}},  # 按 date_ms 支持历史交易日
    "trading_calendar": {"path": "/api/a-share/calendar/trading-days", "query": {}},
    "valuation_snapshot": {"path": "/api/a-share/valuations/snapshot", "query": {"thscodes": "600519.SH"}},
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
    "q", "limit", "offset", "thscodes", "thscode", "interval", "start", "end",
    "adjust", "period", "report", "page", "size", "date", "date_ms", "from",
    "to", "ths_code", "board_type", "sort_field", "sort_dir",
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


def sanitize_sample(payload: Any) -> dict:
    """从 data 提取字段名/类型/非敏感样本（截断），剥离一切可能含密钥的键。"""
    data = payload.get("data") if isinstance(payload, dict) else None
    if data is None:
        return {}
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return {"_type": type(data).__name__, "value": str(data)[:200]}
    sample: dict[str, Any] = {}
    for key, value in data.items():
        if key in ("api_key", "token", "secret", "X-api-key", "x-api-key"):
            continue
        sample[key] = {"type": type(value).__name__,
                       "value": str(value)[:120] if value is not None else None}
    return sample


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
        sample_fields=sanitize_sample(payload),
        error_class=classify_envelope(envelope_code),
    )
    return obs


def run_probe(key: str) -> dict:
    observations = {dataset_id: probe_endpoint(dataset_id, spec, key).to_dict()
                    for dataset_id, spec in ENDPOINTS.items()}
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
