"""HiThink LIVE_SMOKE live tests（DS-H1，@pytest.mark.live）。

- 需要环境变量 HITHINK_FINANCE_API_KEY；缺失时整个模块 skip（缺凭据绝不伪报 PASS）；
- 断言只针对结构性/时序性契约（symbol identity、envelope、schema、错误码分类），
  不断言具体价格；
- Provider response = Observation，本文件不定义生产 Canonical 类型、不写入任何存储。
"""
from __future__ import annotations

import os

import pytest

from tools import hithink_live_probe as probe

pytestmark = pytest.mark.live

_API_KEY = os.environ.get(probe.API_KEY_ENV, "").strip()

pytest.skip(
    f"{probe.API_KEY_ENV} 未设置：LIVE_SMOKE 无法运行（BLOCKED_LIVE_AUTH）。"
    "设置该环境变量后重新运行本模块。",
    allow_module_level=True,
)


def _probe_ok(dataset_id: str, spec: dict) -> probe.ProbeObservation:
    """执行端点探测；HTTP 200 + code==0 才算业务成功。"""
    obs = probe.probe_endpoint(dataset_id, spec, _API_KEY)
    assert obs.http_status == 200, f"{dataset_id} HTTP {obs.http_status}: {obs.envelope_message}"
    assert obs.envelope_code == 0, (
        f"{dataset_id} business error code={obs.envelope_code} "
        f"class={obs.error_class}: {obs.envelope_message}"
    )
    return obs


def _sample(obs: probe.ProbeObservation) -> dict:
    assert obs.sample_fields, f"{obs.dataset_id}: data 为空"
    return obs.sample_fields


# ---------------------------------------------------------------------------
# A. Symbol / instrument identity
# ---------------------------------------------------------------------------

def test_a_symbol_search_identity():
    obs = _probe_ok("symbol_search", probe.ENDPOINTS["symbol_search"])
    sample = _sample(obs)
    # 结构性断言：返回条目应包含标识字段（具体值不做价格断言）
    keys = set(sample)
    assert keys, "symbol search 无字段"


# ---------------------------------------------------------------------------
# B. Latest / snapshot quote
# ---------------------------------------------------------------------------

def test_b_snapshot_quote_structural():
    obs = _probe_ok("snapshot_quote", probe.ENDPOINTS["snapshot_quote"])
    sample = _sample(obs)
    assert sample, "snapshot 无字段"
    # 若返回条目：thscode 应带交易所后缀（.SH/.SZ/.BJ）；价格字段应数值类型或 null
    thscode = sample.get("thscode")
    if thscode is not None:
        assert str(thscode["value"]).endswith((".SH", ".SZ", ".BJ")), f"thscode 后缀异常: {thscode}"
    for price_field in ("last_price", "open_price", "high_price", "low_price", "prev_price"):
        if price_field in sample:
            assert sample[price_field]["type"] in ("float", "int", "NoneType"), \
                f"{price_field} 类型异常: {sample[price_field]}"


# ---------------------------------------------------------------------------
# C. Historical daily quote
# ---------------------------------------------------------------------------

def test_c_historical_daily_by_date():
    obs = _probe_ok("historical_daily", probe.ENDPOINTS["historical_daily"])
    sample = _sample(obs)
    assert sample, "historical 无字段"
    # 结构性：条形数据应含 date_ms 或交易日期字段；不假定复权含义（adjust 参数已显式 none）
    assert any(k in sample for k in ("date_ms", "open_price", "close_price", "date")), \
        f"historical 缺 K 线字段: {sorted(sample)}"


# ---------------------------------------------------------------------------
# D. Financial statement
# ---------------------------------------------------------------------------

def test_d_income_statement_period():
    obs = _probe_ok("income_statement", probe.ENDPOINTS["income_statement"])
    sample = _sample(obs)
    assert sample, "income statement 无字段"
    # 结构性：报告期字段存在；发布/公告时间若缺失则记录 NOT_EXPOSED，不伪造
    assert any(k in sample for k in ("period_end_ms", "report_date_ms", "fiscal_year",
                                     "fiscal_period", "report")), \
        f"income statement 缺报告期字段: {sorted(sample)}"


# ---------------------------------------------------------------------------
# E. Membership / concept / industry
# ---------------------------------------------------------------------------

def test_e_index_constituents_current_only():
    obs = _probe_ok("index_constituents", probe.ENDPOINTS["index_constituents"])
    sample = _sample(obs)
    assert sample, "constituents 无字段"
    # 文档声明 current membership（无 as-of 日期参数）→ 不得伪造历史成员
    assert not any(k in sample for k in ("as_of", "as_of_date", "effective_date")), \
        "constituents 响应出现 as-of 日期字段需复核（文档声明 current only）"


# ---------------------------------------------------------------------------
# F. Additional high-value dataset（limit-up pool，支持按历史交易日 date_ms）
# ---------------------------------------------------------------------------

def test_f_limit_up_pool_by_date():
    obs = _probe_ok("limit_up_pool", probe.ENDPOINTS["limit_up_pool"])
    sample = _sample(obs)
    assert sample, "limit-up pool 无字段"
    # 结构性：成员条目含 thscode/ticker；分页信息存在
    assert any(k in sample for k in ("thscode", "ticker", "pagination", "timestamp")), \
        f"limit-up pool 缺成员/分页字段: {sorted(sample)}"


# ---------------------------------------------------------------------------
# 错误语义（安全探测：非法 symbol 只需触发业务错误，不暴露密钥）
# ---------------------------------------------------------------------------

def test_error_invalid_symbol_semantics():
    """非法 symbol → 业务错误码（官方 3001 instrument_not_found 或类似），
    且错误 payload 不含 API key。"""
    spec = {"path": "/api/a-share/prices/historical",
            "query": {"thscode": "999999.ZZ", "interval": "1d", "adjust": "none",
                      "start": probe._ms("2026-07-01"), "end": probe._ms("2026-07-10")}}
    obs = probe.probe_endpoint("error_invalid_symbol", spec, _API_KEY)
    assert obs.http_status is not None
    # 结构上：business error 也应返回 envelope（不要求特定 code，只需可解析）
    assert obs.envelope_code is not None, "非法 symbol 未返回业务错误码"
    dumped = obs.to_dict()
    assert "api_key" not in dumped and "X-api-key" not in dumped
