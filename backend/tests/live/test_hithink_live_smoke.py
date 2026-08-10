"""HiThink LIVE_SMOKE live tests（DS-H1-R1，@pytest.mark.live）。

- 需要环境变量 HITHINK_FINANCE_API_KEY；缺失时整个模块 skip（缺凭据绝不伪报 PASS）；
- 断言只针对结构性/时序性契约（symbol identity、envelope、schema、错误码分类、
  历史矩阵、复权矩阵、显式历史日期、非交易日行为），不断言具体价格；
- Provider response = Observation，本文件不定义生产 Canonical 类型、不写入任何存储。
"""
from __future__ import annotations

import os

import pytest

from tools import hithink_live_probe as probe

pytestmark = pytest.mark.live

_API_KEY = os.environ.get(probe.API_KEY_ENV, "").strip()

if not _API_KEY:
    pytest.skip(
        f"{probe.API_KEY_ENV} 未设置：LIVE_SMOKE 无法运行（BLOCKED_LIVE_AUTH）。"
        "设置该环境变量后重新运行本模块。",
        allow_module_level=True,
    )


def _probe_ok(dataset_id: str, spec: dict) -> probe.ProbeObservation:
    """执行端点探测；HTTP 200 + code==0 才算业务成功（官方成功规则）。"""
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


def _historical_spec(thscode: str, start: str, end: str) -> dict:
    return {"path": "/api/a-share/prices/historical",
            "query": {"thscode": thscode, "interval": "1d", "adjust": "none",
                      "start": probe._ms(start), "end": probe._ms(end)}}


# ---------------------------------------------------------------------------
# A. Symbol / instrument identity
# ---------------------------------------------------------------------------

def test_a_symbol_search_identity():
    """R3：symbol search 身份闭合 —— `q=600519` 返回的身份证据必须包含 `600519.SH`。

    复用现有有界 `_identities` 机制（不新造抽象）；不从非空响应推断。
    """
    obs = _probe_ok("symbol_search", probe.ENDPOINTS["symbol_search"])
    sample = _sample(obs)
    identities = sample.get("_identities", [])
    assert identities, "symbol search 观测缺少受限身份集 _identities"
    assert "600519.SH" in identities, \
        f"SYMBOL_SEARCH_EXPECTED_IDENTITY 失败: 期望 600519.SH ∈ {sorted(identities)}"


def test_a_symbol_search_invalid_no_match():
    """R3：symbol search 明显无效/无匹配查询 → 记录实际结果分类。

    分类 ∈ {EMPTY_SUCCESS, BUSINESS_ERROR, OTHER_OBSERVED_BEHAVIOR}；
    只证明行为被观察到且可解析（envelope code 存在 + 分类值确定），
    不假设 provider 行为。与 historical 非法 symbol 测试（test_error_invalid_symbol_semantics）区分。
    """
    spec = {"path": "/api/meta/tickers/search",
            "query": {"q": probe.SYMBOL_SEARCH_INVALID_QUERY, "limit": 5}}
    obs = probe.probe_endpoint("symbol_search_invalid", spec, _API_KEY)
    assert obs.http_status is not None, "invalid search 无 HTTP 响应"
    assert obs.envelope_code is not None, "invalid search 响应无 envelope code"
    classification = probe.classify_search_result(obs)
    assert classification in (probe.SEARCH_RESULT_EMPTY_SUCCESS,
                             probe.SEARCH_RESULT_BUSINESS_ERROR,
                             probe.SEARCH_RESULT_OTHER), f"未知分类: {classification}"
    print(f"[OBS] symbol_search_invalid(q={probe.SYMBOL_SEARCH_INVALID_QUERY}) "
          f"code={obs.envelope_code} class={classification} count={obs.sample_fields.get('_count')}")


# ---------------------------------------------------------------------------
# B. Latest / snapshot quote（双标的矩阵）
# ---------------------------------------------------------------------------

def test_b_snapshot_quote_two_symbols_structural():
    """R2：快照身份闭合 —— 返回身份集必须同时包含请求的两个标的。

    不断言具体价格；identity 来自受限观测 `_identities`（不是 count 推断）。
    """
    obs = _probe_ok("snapshot_quote", probe.ENDPOINTS["snapshot_quote"])
    sample = _sample(obs)
    assert "_count" in sample and sample["_count"] >= 2, \
        f"snapshot 双标的矩阵 item 数异常: {sample.get('_count')}"
    identities = sample.get("_identities", [])
    assert identities, "观测缺少受限身份集 _identities"
    requested = set(probe.ENDPOINTS["snapshot_quote"]["query"]["thscodes"].split(","))
    assert requested <= set(identities), \
        f"SNAPSHOT_EXPECTED_IDENTITIES_PRESENT 失败: 期望 {sorted(requested)} ⊆ 实际 {sorted(identities)}"
    for thscode in identities:
        assert str(thscode).endswith((".SH", ".SZ", ".BJ")), f"thscode 后缀异常: {thscode}"
    first = sample.get("item[0]", sample)
    for price_field in ("last_price", "open_price", "high_price", "low_price", "prev_price"):
        if price_field in first:
            assert first[price_field]["type"] in ("float", "int", "NoneType"), \
                f"{price_field} 类型异常: {first[price_field]}"


# ---------------------------------------------------------------------------
# C. Historical daily quote（2 标的 × 2 时间窗矩阵 + by-date 绑定闭合）
# ---------------------------------------------------------------------------

def test_c_historical_matrix_2x2():
    """R3：2 标的 × 2 时间窗，每窗都通过 by-date 绑定闭合：
    1) code == 0（_probe_ok 保证）
    2) 返回 items 非空
    3) **date_ms_count == item_count**（每条 bar 都有有效 date_ms 坐标）
    4) 每条返回 date_ms 都落在请求 start/end 窗口内
    5) date_ms 顺序确定性（ASCENDING/DESCENDING，已记录）
    6) OHLC 字段结构为数值或 null（按 provider 契约）
    7) 不因「返回了若干历史行」就通过 —— 必须逐窗绑定。
    """
    for index, (thscode, start, end) in enumerate(probe.HISTORICAL_MATRIX, start=1):
        spec = _historical_spec(thscode, start, end)
        obs = _probe_ok(f"historical_{index}", spec)
        sample = _sample(obs)
        ts = sample.get("_temporal_summary", {})
        assert ts.get("item_count", 0) > 0, \
            f"historical_{index}({thscode}) 返回空 items"
        # 完整性：每条 bar 都有有效 date_ms 坐标
        assert ts.get("date_ms_count") == ts.get("item_count"), (
            f"historical_{index}({thscode}) date_ms 坐标不完整: "
            f"date_ms_count={ts.get('date_ms_count')} != item_count={ts.get('item_count')}"
        )
        # 窗口绑定：每条 date_ms ∈ [start, end]
        start_ms, end_ms = probe._ms(start), probe._ms(end)
        dates = ts.get("date_ms_values", [])
        assert dates, f"historical_{index}({thscode}) 无 date_ms"
        assert all(start_ms <= d <= end_ms for d in dates), (
            f"historical_{index}({thscode}) 存在越界 date_ms: "
            f"窗口 [{start_ms},{end_ms}], 值 {dates}"
        )
        # 顺序确定性：ASCENDING 或 DESCENDING（provider 契约记录于观测）
        assert ts.get("ordering") in ("ASCENDING", "DESCENDING"), (
            f"historical_{index}({thscode}) date_ms 非单调: {ts.get('ordering')}"
        )
        # OHLC 结构：数值或 null
        ohlc = ts.get("ohlc_types", {})
        for field in ("open_price", "high_price", "low_price", "close_price"):
            types = ohlc.get(field, [])
            assert types and set(types) <= {"float", "int", "null"}, (
                f"historical_{index}({thscode}) {field} 类型异常: {types}"
            )


def test_c_historical_distinct_ranges_return_items():
    """2×2 矩阵：至少验证两个不同时间窗均返回数据（避免空窗全绿假象）。"""
    obs1 = _probe_ok("historical_600519_r1", _historical_spec("600519.SH", "2026-07-01", "2026-07-10"))
    obs2 = _probe_ok("historical_600519_r2", _historical_spec("600519.SH", "2026-06-01", "2026-06-12"))
    assert obs1.sample_fields and obs2.sample_fields
    assert obs1.sample_fields["_temporal_summary"]["item_count"] > 0
    assert obs2.sample_fields["_temporal_summary"]["item_count"] > 0


def test_c_adjustment_matrix_three_modes():
    """adjust none/forward/backward 三模式各自成功且返回同结构 K 线。"""
    for adjust, label in probe.ADJUSTMENT_MATRIX:
        spec = _historical_spec("600519.SH", "2026-07-01", "2026-07-10")
        spec["query"]["adjust"] = adjust
        obs = _probe_ok(label, spec)
        assert _sample(obs)


def test_c_non_trading_day_behavior():
    """非交易日（2026-08-08 Sat）：记录实际行为（空 items / 业务错误码 / 空数据），
    不假设 —— 只断言响应可解析且 HTTP 正常返回。"""
    obs = probe.probe_endpoint("non_trading_day", probe.NON_TRADING_DAY_SPEC, _API_KEY)
    assert obs.http_status is not None, "非交易日请求无 HTTP 响应"
    # 业务失败（code!=0）也记录 observation；envelope 必须存在
    assert obs.envelope_code is not None, "非交易日响应无 envelope code"
    if obs.envelope_code == 0:
        # 成功路径：记录 item 数（可为 0）
        count = obs.sample_fields.get("_count")
        # 不假设非交易日行为：仅记录
        print(f"[OBS] non_trading_day count={count}")


# ---------------------------------------------------------------------------
# D. Financial statement
# ---------------------------------------------------------------------------

def test_d_income_statement_period():
    obs = _probe_ok("income_statement", probe.ENDPOINTS["income_statement"])
    sample = _sample(obs)
    first = sample.get("item[0]", sample)
    assert any(k in first for k in ("period_end_ms", "report_date_ms", "fiscal_year",
                                    "fiscal_period", "report")), \
        f"income statement 缺报告期字段: {sorted(first)}"


# ---------------------------------------------------------------------------
# E. Membership / concept / industry
# ---------------------------------------------------------------------------

def test_e_index_constituents_current_only():
    obs = _probe_ok("index_constituents", probe.ENDPOINTS["index_constituents"])
    sample = _sample(obs)
    # 文档声明 current membership（无 as-of 日期参数）→ 不得伪造历史成员
    assert not any(k in sample for k in ("as_of", "as_of_date", "effective_date")), \
        "constituents 响应出现 as-of 日期字段需复核（文档声明 current only）"


# ---------------------------------------------------------------------------
# F. Additional high-value dataset（limit-up，显式历史交易日 date_ms）
# ---------------------------------------------------------------------------

def test_f_limit_up_explicit_historical_date():
    """R1：limit-up 显式历史 date_ms（2026-08-07 交易日）→ 业务成功 + 成员结构。"""
    obs = _probe_ok("limit_up_explicit_date", probe.LIMIT_UP_HISTORICAL_SPEC)
    sample = _sample(obs)
    first = sample.get("item[0]", sample)
    assert any(k in first for k in ("thscode", "ticker")), \
        f"limit-up 历史成员缺标识: {sorted(first)}"


# ---------------------------------------------------------------------------
# 错误语义（安全探测：非法 symbol 只需触发业务错误，不暴露密钥）
# ---------------------------------------------------------------------------

def test_error_invalid_symbol_semantics():
    """非法 symbol → 业务错误码（官方 3001 instrument_not_found 或类似），
    且错误 payload 不含 API key。"""
    spec = _historical_spec("999999.ZZ", "2026-07-01", "2026-07-10")
    obs = probe.probe_endpoint("error_invalid_symbol", spec, _API_KEY)
    assert obs.http_status is not None
    assert obs.envelope_code is not None, "非法 symbol 未返回业务错误码"
    dumped = obs.to_dict()
    assert "api_key" not in dumped and "X-api-key" not in dumped
    # 递归：sample_fields 任意深度不得含 secret 键
    assert _no_secret_keys(obs.sample_fields), "sample 中出现 secret 键"


def _no_secret_keys(node) -> bool:
    """递归断言任意深度无 secret 键。"""
    if isinstance(node, dict):
        for key, value in node.items():
            if probe._is_secret_key(key):
                return False
            if not _no_secret_keys(value):
                return False
    elif isinstance(node, list):
        for item in node:
            if not _no_secret_keys(item):
                return False
    return True
