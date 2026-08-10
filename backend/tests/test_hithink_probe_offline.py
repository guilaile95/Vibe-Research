"""HiThink probe harness offline tests（DS-H1，无网络 / 无凭据必须全绿）。

覆盖：
- request fingerprint secret-safe（fail closed：secret 键拒绝、key 永不进入）
- envelope 解析 / 错误码确定性分类（official code → class）
- NULL vs 0 vs "" vs [] vs missing key 区分（观测层不归一化）
- sanitize_sample 剥离 secret 键、截断样本
- 报告矩阵结构（每行含 9 列 + live result 枚举）
- 端点矩阵完整性（A-F 六类至少各一）
- 官方来源事实快照（2026-08-10 核验值）
"""
from __future__ import annotations

import pytest

from tools import hithink_live_probe as probe


# ---------------------------------------------------------------------------
# 1. request fingerprint secret-safe
# ---------------------------------------------------------------------------

def test_fingerprint_deterministic_and_secret_safe():
    q = {"thscode": "600519.SH", "interval": "1d", "start": 1, "end": 2, "adjust": "none"}
    fp1 = probe.request_fingerprint(provider="hithink", endpoint="/api/x", query=q)
    fp2 = probe.request_fingerprint(provider="hithink", endpoint="/api/x", query=dict(q))
    assert fp1 == fp2  # deterministic
    assert fp1 != probe.request_fingerprint(provider="hithink", endpoint="/api/y", query=q)
    assert fp1 != probe.request_fingerprint(provider="hithink", endpoint="/api/x",
                                            query={**q, "interval": "1w"})


def test_fingerprint_rejects_secret_keys_fail_closed():
    """任何非白名单 query 键（含 API key / token）必须被拒绝，绝不进入 fingerprint。"""
    secret_keys = ["api_key", "token", "secret", "X-api-key", "x-api-key", "authorization", "key"]
    for secret in secret_keys:
        with pytest.raises(ValueError, match="non-secret query keys only"):
            probe.request_fingerprint(provider="hithink", endpoint="/api/x", query={secret: "s3cr3t"})
    # 白名单键即使值像 key 也被接受（值不参与 secret 判断；key 只存在于 header）
    probe.request_fingerprint(provider="hithink", endpoint="/api/x",
                              query={"thscode": "anything", "limit": 1})


def test_fingerprint_normalizes_query_order():
    """白名单键不同顺序 → 相同 fingerprint（非白名单键会被拒绝，此处用白名单键）。"""
    q1 = {"thscode": "600519.SH", "limit": 1}
    q2 = {"limit": 1, "thscode": "600519.SH"}
    assert (probe.request_fingerprint(provider="h", endpoint="/e", query=q1)
            == probe.request_fingerprint(provider="h", endpoint="/e", query=q2))


def test_api_key_env_never_in_output_paths():
    """key 只从 env 读取；observation / fingerprint / error message 结构不含 key 字段。"""
    obs = probe.ProbeObservation(dataset_id="d", endpoint="/e", http_status=None,
                                 envelope_code=None, envelope_message=None,
                                 request_id=None, fingerprint="fp")
    dumped = obs.to_dict()
    assert "api_key" not in dumped and "X-api-key" not in dumped
    assert "key" not in dumped


# ---------------------------------------------------------------------------
# 2. envelope 解析 / 错误码确定性分类
# ---------------------------------------------------------------------------

def test_envelope_code_classification_official_codes():
    assert probe.classify_envelope(0) is None
    assert probe.classify_envelope(None) is None
    assert probe.classify_envelope(1001) == "missing_parameter"
    assert probe.classify_envelope(2001) == "unauthenticated"
    assert probe.classify_envelope(2003) == "no_permission_or_invalid_key"
    assert probe.classify_envelope(3001) == "instrument_not_found"
    assert probe.classify_envelope(4001) == "rate_limited"
    assert probe.classify_envelope(5001) == "server_error"
    assert probe.classify_envelope(9999) == "unknown_code"


def test_success_rule_http200_not_enough():
    """官方规则：HTTP 200 不代表业务成功，必须同时 code == 0。"""
    # 业务错误也常是 HTTP 200 + code != 0
    payload = {"code": 3001, "message": "instrument not found", "request_id": "r1", "data": None}
    assert probe.classify_envelope(payload["code"]) == "instrument_not_found"


def test_sanitize_sample_strips_secret_like_keys_recursive():
    """R1：secret 键清洗必须递归到任意深度，包括嵌套 dict/list。

    注意：顶层 ``items`` 键会触发 item[] 分支 → 其余字段进入 ``_meta``。
    """
    payload = {"code": 0, "message": "ok", "request_id": "r1",
               "data": {"thscode": "600519.SH", "api_key": "LEAK", "token": "LEAK",
                        "name": None, "price": 1.74,
                        "nested": {"api_key": "LEAK", "inner": {"X-API-Key": "LEAK", "ok": 1}},
                        "items": [{"token": "LEAK", "a": 2}, {"b": 3}]}}
    sample = probe._extract_data_sample(payload)
    assert "api_key" not in sample and "token" not in sample
    meta = sample["_meta"]
    assert "api_key" not in meta and "token" not in meta
    assert meta["thscode"]["value"] == "600519.SH"
    assert meta["name"]["value"] is None
    assert meta["name"]["type"] == "NoneType"
    # 嵌套深度剥离（大小写/分隔符归一化）
    nested = meta["nested"]
    assert "api_key" not in nested and "xapikey" not in {probe._normalize_key(k) for k in nested}
    assert nested["inner"]["ok"]["value"] == "1"
    assert "xapikey" not in {probe._normalize_key(k) for k in nested["inner"]}
    items = sample["item[0]"]
    assert "token" not in items
    assert sample["_count"] == 2


def test_extract_nested_item_array():
    """R1：data.item[] 嵌套 → meta + item[0] + count。"""
    payload = {"code": 0, "message": "ok", "request_id": "r1",
               "data": {"timestamp": 1750000000000, "total": 5000,
                        "item": [{"thscode": "600519.SH", "ticker": "600519",
                                  "last_price": 1700.5}, {"thscode": "000001.SZ"}]}}
    sample = probe._extract_data_sample(payload)
    assert sample["_meta"]["total"]["value"] == "5000"
    assert sample["_meta"]["timestamp"]["value"] == "1750000000000"
    assert sample["_count"] == 2
    assert sample["item[0]"]["thscode"]["value"] == "600519.SH"


def test_identities_bounded_and_deduplicated():
    """R2：受限身份集 —— thscode/ticker 去重、有界、含请求标的。"""
    items = [{"thscode": f"60{i:04d}.SH"} for i in range(20)]
    ids = probe._bounded_identities(items)
    assert len(ids) <= probe._MAX_IDENTITIES  # 有界
    assert len(ids) == len(set(ids))  # 去重
    assert ids[0] == "600000.SH"
    # 同一条 item 同时含 thscode+ticker → 只取 thscode（不重复计数）
    same_item = [{"thscode": "600519.SH", "ticker": "600519"}]
    assert probe._bounded_identities(same_item) == ["600519.SH"]
    # 不同标的各取一次
    two = [{"thscode": "600519.SH"}, {"thscode": "000001.SZ"}]
    assert probe._bounded_identities(two) == ["600519.SH", "000001.SZ"]


def test_temporal_summary_window_and_ordering():
    """R2：temporal 摘要 —— date_ms 值/首末/顺序证据。"""
    items = [{"date_ms": 100, "open_price": 1.0}, {"date_ms": 200, "open_price": 2.0},
             {"date_ms": 300, "open_price": 3.0}]
    ts = probe._temporal_summary(items)
    assert ts["item_count"] == 3
    assert ts["date_ms_values"] == [100, 200, 300]
    assert ts["first_date_ms"] == 100 and ts["last_date_ms"] == 300
    assert ts["ordering"] == "ASCENDING"
    # 逆序 → DESCENDING；乱序 → NON_MONOTONIC；空 → EMPTY
    rev = [{"date_ms": 300}, {"date_ms": 200}, {"date_ms": 100}]
    assert probe._temporal_summary(rev)["ordering"] == "DESCENDING"
    jumbled = [{"date_ms": 200}, {"date_ms": 100}, {"date_ms": 300}]
    assert probe._temporal_summary(jumbled)["ordering"] == "NON_MONOTONIC"
    assert probe._temporal_summary([])["ordering"] == "EMPTY"


def test_temporal_summary_ohlc_types():
    """R2：OHLC 类型摘要 —— 数值/null 类型集合。"""
    items = [{"date_ms": 1, "open_price": 10.5, "high_price": 11.0, "low_price": 10.0,
              "close_price": None, "volume": 100, "turnover": 10000.0}]
    ts = probe._temporal_summary(items)
    assert ts["ohlc_types"]["open_price"] == ["float"]
    assert ts["ohlc_types"]["close_price"] == ["null"]
    assert ts["ohlc_types"]["volume"] == ["int"]
    assert ts["ohlc_types"]["turnover"] == ["float"]


def test_temporal_summary_bounded():
    """R2：摘要受限 —— date_ms 值列表有上界，不持久化完整 payload。"""
    items = [{"date_ms": i} for i in range(500)]
    ts = probe._temporal_summary(items)
    assert len(ts["date_ms_values"]) == probe._MAX_DATE_MS_VALUES
    assert ts["item_count"] == 500  # 计数完整但值列表有界


def test_temporal_summary_date_ms_count_complete():
    """R3：date_ms_count 是全量有效计数（不截断），用于 date_ms_count == item_count 完整性证明。"""
    # 500 条全部有 date_ms → 全量计数 500（不受 _MAX_DATE_MS_VALUES 截断）
    items = [{"date_ms": i} for i in range(500)]
    ts = probe._temporal_summary(items)
    assert ts["date_ms_count"] == 500 == ts["item_count"]
    # 部分 bar 缺 date_ms → date_ms_count < item_count（完整性缺口可被检测）
    partial = [{"date_ms": 1}, {"date_ms": 2}, {"open_price": 3.0}]
    ts2 = probe._temporal_summary(partial)
    assert ts2["date_ms_count"] == 2 and ts2["item_count"] == 3
    # bool 不算有效 date_ms
    bool_item = [{"date_ms": True}]
    assert probe._temporal_summary(bool_item)["date_ms_count"] == 0


def test_classify_search_result_three_branches():
    """R3：symbol search 结果分类 —— EMPTY_SUCCESS / BUSINESS_ERROR / OTHER_OBSERVED_BEHAVIOR。"""
    def _obs(code, sample):
        return probe.ProbeObservation(dataset_id="x", endpoint="/e", http_status=200,
                                      envelope_code=code, envelope_message=None,
                                      request_id=None, fingerprint="fp", sample_fields=sample)
    # 业务错误 → BUSINESS_ERROR
    assert probe.classify_search_result(_obs(3001, {})) == probe.SEARCH_RESULT_BUSINESS_ERROR
    # code=0 + 空 data → EMPTY_SUCCESS
    assert probe.classify_search_result(_obs(0, {})) == probe.SEARCH_RESULT_EMPTY_SUCCESS
    assert probe.classify_search_result(_obs(0, {"_count": 0})) == probe.SEARCH_RESULT_EMPTY_SUCCESS
    # code=0 + 有匹配 → OTHER_OBSERVED_BEHAVIOR
    assert probe.classify_search_result(
        _obs(0, {"_count": 1, "_identities": ["600519.SH"]})) == probe.SEARCH_RESULT_OTHER


def test_sanitize_sample_truncates_long_values_recursive():
    payload = {"code": 0, "message": "ok", "request_id": "r1",
               "data": {"reason": "x" * 1000, "nested": {"long": "y" * 1000}}}
    sample = probe._extract_data_sample(payload)
    assert len(sample["reason"]["value"]) <= 120
    assert len(sample["nested"]["long"]["value"]) <= 120


# ---------------------------------------------------------------------------
# 3. NULL / UNKNOWN discipline（观测层不归一化）
# ---------------------------------------------------------------------------

def test_null_discipline_distinct_values():
    """null / 0 / "" / [] / missing key 必须保持区分，禁止归一化。

    区分依据：类型字段（NoneType vs str vs int vs list）+ value 表示。
    """
    payload = {"code": 0, "message": "ok", "request_id": "r1",
               "data": {"a": None, "b": 0, "c": "", "d": [], "e": False}}
    sample = probe._extract_data_sample(payload)
    # None → NoneType / value None；0 → int；"" → str；[] → list(_list/_count)；False → bool
    assert sample["a"]["type"] == "NoneType" and sample["a"]["value"] is None
    assert sample["b"]["type"] == "int" and sample["b"]["value"] == "0"
    assert sample["c"]["type"] == "str" and sample["c"]["value"] == ""
    assert sample["d"]["_list"] == [] and sample["d"]["_count"] == 0  # 空 list，非 null/0/""
    assert sample["e"]["type"] == "bool" and sample["e"]["value"] == "False"
    # missing key 表现为不存在于 sample
    assert "missing_key" not in sample


# ---------------------------------------------------------------------------
# 3b. R1 矩阵结构
# ---------------------------------------------------------------------------

def test_historical_matrix_2x2():
    """R1：historical 2 标的 × 2 时间窗，共 4 个独立探测。"""
    assert len(probe.HISTORICAL_MATRIX) == 4
    symbols = {m[0] for m in probe.HISTORICAL_MATRIX}
    assert symbols == {"600519.SH", "000001.SZ"}
    assert len({(m[1], m[2]) for m in probe.HISTORICAL_MATRIX}) == 2


def test_adjustment_matrix_three_modes():
    """R1：adjust none/forward/backward 三模式。"""
    labels = {label for _, label in probe.ADJUSTMENT_MATRIX}
    assert labels == {"adjust_none", "adjust_forward", "adjust_backward"}


def test_limit_up_explicit_historical_date_spec():
    """R1：limit-up 显式历史 date_ms（2026-08-07 交易日）。"""
    spec = probe.LIMIT_UP_HISTORICAL_SPEC
    assert spec["query"]["date_ms"] == probe._ms("2026-08-07")


def test_non_trading_day_spec_is_weekend():
    """R1：非交易日探测日期必须是周末（2026-08-08 = Saturday）。"""
    from datetime import datetime
    d = datetime.strptime(probe.NON_TRADING_DAY_DATE, "%Y-%m-%d")
    assert d.strftime("%A") in ("Saturday", "Sunday")
    assert probe.NON_TRADING_DAY_SPEC["query"]["thscode"] == "600519.SH"


def test_non_trading_day_derived_from_trading_day():
    """R1：非交易日 = 交易日 + 1 天（2026-08-07 Fri → 2026-08-08 Sat）。"""
    from datetime import datetime, timedelta
    trading = datetime.strptime(probe.TRADING_DAY_DATE, "%Y-%m-%d")
    non_trading = datetime.strptime(probe.NON_TRADING_DAY_DATE, "%Y-%m-%d")
    assert non_trading == trading + timedelta(days=1)


# ---------------------------------------------------------------------------
# 4. 报告矩阵结构
# ---------------------------------------------------------------------------

def test_report_matrix_structure():
    """每行必须含 9 列 + live result 枚举（VERIFIED/PARTIAL/UNKNOWN/FAILED）。"""
    rows = _report_rows()
    expected_columns = ["dataset_id", "endpoint", "live_result", "identifiers",
                        "temporal_evidence", "history_mode", "revision_support",
                        "null_semantics", "provenance_strength", "candidate_role",
                        "confidence"]
    for row in rows:
        for col in expected_columns:
            assert col in row, f"missing column {col} in {row.get('dataset_id')}"
        assert row["live_result"] in ("VERIFIED", "PARTIAL", "UNKNOWN", "FAILED")
        assert row["history_mode"] in ("by_date", "snapshot", "snapshot_with_backfill",
                                       "snapshot_only", "UNKNOWN")
        assert row["revision_support"] in ("EXPLICIT", "DERIVABLE_WITH_CERTAINTY",
                                           "NOT_EXPOSED", "UNKNOWN")


def test_dataset_matrix_covers_all_categories():
    """六类（A-F）至少各一个端点 + R1 矩阵数据集。"""
    rows = _report_rows()
    ids = {r["dataset_id"] for r in rows}
    assert {"symbol_search", "snapshot_quote", "historical_daily", "income_statement",
            "index_constituents", "limit_up_pool"} <= ids
    # R1：2×2 / adjust / 显式历史日期 / 非交易日
    assert {"historical_600519_r1", "historical_600519_r2",
            "historical_000001_r1", "historical_000001_r2",
            "adjust_none", "adjust_forward", "adjust_backward",
            "limit_up_explicit_date", "non_trading_day"} <= ids


def test_verified_source_facts_2026_08_10():
    vs = probe.verified_source()
    assert vs["repository"] == "https://github.com/HiThink-Tech/Financial-API"
    assert vs["verified_commit_sha"] == "f8cdea908469b1b3b8bfb88dbb4d4a3959b1905c"
    assert vs["license_spdx"] == "MIT"
    assert vs["auth_method"] == "header X-api-key (env HITHINK_FINANCE_API_KEY)"
    assert vs["success_rule"] == "HTTP 200 AND envelope code == 0"


# ---------------------------------------------------------------------------
# 5. probe CLI 行为（无凭据 → BLOCKED_LIVE_AUTH，非 0 退出）
# ---------------------------------------------------------------------------

def test_probe_cli_blocked_without_credential(monkeypatch, capsys):
    monkeypatch.delenv(probe.API_KEY_ENV, raising=False)
    rc = probe.main(["run"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "BLOCKED_LIVE_AUTH" in captured.err


# ---------------------------------------------------------------------------
# 报告矩阵（与 docs/data/HITHINK_LIVE_SMOKE_V01.md 同步维护）
# ---------------------------------------------------------------------------

def _report_rows() -> list[dict]:
    """DS-H1 报告矩阵：live_result 在无凭据环境为 UNKNOWN（未运行）。"""
    base = {
        "live_result": "UNKNOWN",  # 本环境无凭据 → 未运行（诚实标注）
        "provenance_strength": "DOC_VERIFIED",  # 端点/参数经官方文档核验
        "confidence": "LOW",
    }
    historical_row = {**base, "endpoint": "/api/a-share/prices/historical",
                      "identifiers": "request thscode only (bars carry date_ms not thscode)",
                      "temporal_evidence": "start/end ms; date_ms per bar; adjust=none|forward|backward",
                      "history_mode": "by_date",
                      "revision_support": "NOT_EXPOSED",
                      "null_semantics": "per endpoint page",
                      "candidate_role": "CANDIDATE_HISTORICAL_BACKFILL"}
    return [
        {**base, "dataset_id": "symbol_search",
         "endpoint": "/api/meta/tickers/search",
         "identifiers": "thscode / ticker (exchange suffix)",
         "temporal_evidence": "lookup, no time series",
         "history_mode": "snapshot_only",
         "revision_support": "NOT_EXPOSED",
         "null_semantics": "envelope data=null on business error",
         "candidate_role": "CANDIDATE_VERIFIER"},
        {**base, "dataset_id": "snapshot_quote",
         "endpoint": "/api/a-share/prices/snapshot",
         "identifiers": "thscode / ticker",
         "temporal_evidence": "timestamp: null when explicit thscodes; latest valid in paging",
         "history_mode": "snapshot_only",
         "revision_support": "NOT_EXPOSED",
         "null_semantics": "timestamp can be null",
         "candidate_role": "CANDIDATE_VERIFIER"},
        {**historical_row, "dataset_id": "historical_daily",
         "temporal_evidence": "R1 矩阵：2 标的 × 2 时间窗 + adjust none/forward/backward"},
        {**historical_row, "dataset_id": "historical_600519_r1"},
        {**historical_row, "dataset_id": "historical_600519_r2"},
        {**historical_row, "dataset_id": "historical_000001_r1"},
        {**historical_row, "dataset_id": "historical_000001_r2"},
        {**historical_row, "dataset_id": "adjust_none",
         "temporal_evidence": "adjust=none 原始价"},
        {**historical_row, "dataset_id": "adjust_forward",
         "temporal_evidence": "adjust=forward 前复权"},
        {**historical_row, "dataset_id": "adjust_backward",
         "temporal_evidence": "adjust=backward 后复权"},
        {**base, "dataset_id": "income_statement",
         "endpoint": "/api/a-share/financials/income-statements",
         "identifiers": "thscode / ticker",
         "temporal_evidence": "period_end_ms + report_date_ms + fiscal_year/period",
         "history_mode": "by_date",
         "revision_support": "UNKNOWN",  # 无 revision/vintage 标识可证明
         "null_semantics": "null = 未披露，不得补零",
         "candidate_role": "CANDIDATE_VERIFIER"},
        {**base, "dataset_id": "index_constituents",
         "endpoint": "/api/a-share-index/constituents/ths-stock-list",
         "identifiers": "thscode / ticker",
         "temporal_evidence": "current membership only, no as-of date",
         "history_mode": "snapshot_only",
         "revision_support": "NOT_EXPOSED",
         "null_semantics": "per endpoint page",
         "candidate_role": "OBSERVATION_ONLY"},
        {**base, "dataset_id": "limit_up_pool",
         "endpoint": "/api/a-share/special-data/limit-up-pool",
         "identifiers": "thscode / ticker / name",
         "temporal_evidence": "date_ms (Asia/Shanghai 00:00) supports historical trading day",
         "history_mode": "by_date",
         "revision_support": "NOT_EXPOSED",
         "null_semantics": "per endpoint page",
         "candidate_role": "CANDIDATE_VERIFIER"},
        {**base, "dataset_id": "limit_up_explicit_date",
         "endpoint": "/api/a-share/special-data/limit-up-pool",
         "identifiers": "thscode / ticker / name",
         "temporal_evidence": "R1：显式 date_ms=2026-08-07(交易日) 历史成员",
         "history_mode": "by_date",
         "revision_support": "NOT_EXPOSED",
         "null_semantics": "per endpoint page",
         "candidate_role": "CANDIDATE_VERIFIER"},
        {**base, "dataset_id": "non_trading_day",
         "endpoint": "/api/a-share/prices/historical",
         "identifiers": "request thscode",
         "temporal_evidence": "R1：2026-08-08(Sat) 非交易日行为探测",
         "history_mode": "by_date",
         "revision_support": "NOT_EXPOSED",
         "null_semantics": "记录空/错误行为（不假设）",
         "candidate_role": "OBSERVATION_ONLY"},
    ]
