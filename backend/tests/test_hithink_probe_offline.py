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


def test_sanitize_sample_strips_secret_like_keys():
    payload = {"code": 0, "message": "ok", "request_id": "r1",
               "data": {"thscode": "600519.SH", "api_key": "LEAK", "token": "LEAK",
                        "name": None, "price": 1.74}}
    sample = probe.sanitize_sample(payload)
    assert "api_key" not in sample and "token" not in sample
    assert sample["thscode"]["value"] == "600519.SH"
    assert sample["name"]["value"] is None
    assert sample["name"]["type"] == "NoneType"


def test_sanitize_sample_truncates_long_values():
    payload = {"code": 0, "message": "ok", "request_id": "r1",
               "data": {"reason": "x" * 1000}}
    sample = probe.sanitize_sample(payload)
    assert len(sample["reason"]["value"]) <= 120


# ---------------------------------------------------------------------------
# 3. NULL / UNKNOWN discipline（观测层不归一化）
# ---------------------------------------------------------------------------

def test_null_discipline_distinct_values():
    """null / 0 / "" / [] / missing key 必须保持区分，禁止归一化。

    区分依据：类型字段（NoneType vs str vs int vs list）+ value 表示。
    """
    payload = {"code": 0, "message": "ok", "request_id": "r1",
               "data": {"a": None, "b": 0, "c": "", "d": [], "e": False}}
    sample = probe.sanitize_sample(payload)
    # None → NoneType / value None；0 → int；"" → str；[] → list；False → bool
    assert sample["a"]["type"] == "NoneType" and sample["a"]["value"] is None
    assert sample["b"]["type"] == "int" and sample["b"]["value"] == "0"
    assert sample["c"]["type"] == "str" and sample["c"]["value"] == ""
    assert sample["d"]["type"] == "list" and sample["d"]["value"] == "[]"
    assert sample["e"]["type"] == "bool" and sample["e"]["value"] == "False"
    # missing key 表现为不存在于 sample
    assert "missing_key" not in sample


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
    """六类（A-F）至少各一个端点。"""
    rows = _report_rows()
    ids = {r["dataset_id"] for r in rows}
    assert {"symbol_search", "snapshot_quote", "historical_daily", "income_statement",
            "index_constituents", "limit_up_pool"} <= ids


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
        {**base, "dataset_id": "historical_daily",
         "endpoint": "/api/a-share/prices/historical",
         "identifiers": "request thscode only (bars carry date_ms not thscode)",
         "temporal_evidence": "start/end ms; date_ms per bar; adjust=none|forward|backward",
         "history_mode": "by_date",
         "revision_support": "NOT_EXPOSED",
         "null_semantics": "per endpoint page",
         "candidate_role": "CANDIDATE_HISTORICAL_BACKFILL"},
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
    ]
