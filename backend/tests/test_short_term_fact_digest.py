"""BK-11 Slice 3d 日事实摘要文本纯计算层测试。

不发起任何 live 请求。覆盖文本内容、合同、异常边界、输入不可变性。
"""
from __future__ import annotations

import copy
import inspect
import sys

import pytest

sys.path.insert(0, "backend")

import short_term_fact_digest as digest  # noqa: E402


def _summary(status="normal", window=None, stats=None, **overrides):
    if window is None:
        window = {
            "count": 3,
            "first_trade_date": "2026-07-28",
            "last_trade_date": "2026-07-30",
        }
    if stats is None:
        stats = {
            "status_distribution": {
                "normal": 3, "partial": 0, "unavailable": 0, "invalid": 0},
            "facts": {
                "limit_up_count": {"min": 8, "max": 12, "avg": 10.0,
                                   "count": 3},
                "advance_count": {"min": 90, "max": 110, "avg": 100.0,
                                  "count": 3},
                "failed_board_rate": {"min": 0.2, "max": 0.3, "avg": 0.2436,
                                      "count": 3},
                "seal_rate": {"min": 0.7, "max": 0.8, "avg": 0.7564,
                              "count": 3},
                "up_ratio": {"min": 0.45, "max": 0.55, "avg": 0.5,
                             "count": 3},
            },
            "ladder": {
                "max_boards": {"min": 2, "max": 5, "avg": 3.6667, "count": 3},
                "lianban_count": {"min": 1, "max": 5, "avg": 3.0, "count": 3},
                "days_with_ladder": 3,
            },
            "gap": {
                "gap_level_count": {"min": 0, "max": 1, "avg": 0.3333,
                                    "count": 3},
                "largest_gap_width": {"min": 0, "max": 1, "avg": 0.3333,
                                      "count": 3},
                "days_with_gap_section": 3,
                "continuous_days": 2,
            },
        }
    return {
        "schema_version": "short-term-fact-summary-v0.1",
        "window": window,
        "status": status,
        "reason_codes": [],
        "warnings": [],
        "limitations": ["fixed"],
        "stats": stats,
        **overrides,
    }


def _assert_shape(result):
    assert set(result.keys()) == {
        "schema_version", "status", "reason_codes", "warnings",
        "limitations", "digest_text",
    }
    assert result["schema_version"] == digest.SCHEMA_VERSION
    assert isinstance(result["digest_text"], str)


def _assert_invalid(result, reason_code):
    _assert_shape(result)
    assert result["status"] == "invalid"
    assert result["reason_codes"] == [reason_code, "OUTPUT_SUPPRESSED"]
    assert result["digest_text"] == ""


# ---------------------------------------------------------------------------
# 1. 公开合同
# ---------------------------------------------------------------------------

class TestPublicContract:
    def test_constants(self):
        assert digest.SCHEMA_VERSION == "short-term-fact-digest-v0.1"

    def test_all(self):
        assert digest.__all__ == ["SCHEMA_VERSION", "build_fact_digest"]

    def test_signature(self):
        sig = inspect.signature(digest.build_fact_digest)
        assert list(sig.parameters) == ["summary_envelope"]
        for parameter in sig.parameters.values():
            assert parameter.default is inspect.Parameter.empty


# ---------------------------------------------------------------------------
# 2. 文本内容
# ---------------------------------------------------------------------------

class TestDigestText:
    def test_header(self):
        result = digest.build_fact_digest(_summary())
        _assert_shape(result)
        assert result["status"] == "normal"
        assert result["reason_codes"] == []
        assert "短线市场事实摘要（3 天，2026-07-28 ~ 2026-07-30）" \
            in result["digest_text"]
        assert "摘要状态：normal" in result["digest_text"]

    def test_stats_lines(self):
        text = digest.build_fact_digest(_summary())["digest_text"]
        assert "状态分布：normal 3 / partial 0 / unavailable 0 / invalid 0" \
            in text
        assert "limit_up_count：min 8 / max 12 / avg 10（3 天）" in text
        assert "failed_board_rate：min 0.2 / max 0.3 / avg 0.2436（3 天）" \
            in text
        assert "梯队最高板：max 5 / avg 3.6667（3 天有梯队数据）" in text
        assert "断层层级数：avg 0.3333 / max 1；连续梯队日 2 天" in text

    def test_footer_disclaimers(self):
        text = digest.build_fact_digest(_summary())["digest_text"]
        assert "统计基于 normal 状态天" in text
        assert "不包含晋级率" in text
        assert "不包含……交易建议或预测" in text or "交易建议或预测" in text

    def test_partial_status_line(self):
        result = digest.build_fact_digest(_summary(status="partial"))
        assert result["status"] == "partial"
        assert result["reason_codes"] == ["OUTPUT_SUPPRESSED"]
        assert "摘要状态：partial" in result["digest_text"]
        assert "状态分布：normal 3" in result["digest_text"]

    def test_deterministic(self):
        first = digest.build_fact_digest(_summary())["digest_text"]
        second = digest.build_fact_digest(_summary())["digest_text"]
        assert first == second


# ---------------------------------------------------------------------------
# 3. 合同
# ---------------------------------------------------------------------------

class TestContract:
    @pytest.mark.parametrize("bad", [None, "x", 1, [], ("a",)])
    def test_non_dict(self, bad):
        _assert_invalid(
            digest.build_fact_digest(bad), "SUMMARY_CONTRACT_INVALID")

    def test_wrong_schema(self):
        s = _summary()
        s["schema_version"] = "wrong"
        _assert_invalid(digest.build_fact_digest(s),
                        "SUMMARY_CONTRACT_INVALID")

    def test_missing_stats(self):
        s = _summary()
        del s["stats"]
        _assert_invalid(digest.build_fact_digest(s),
                        "SUMMARY_CONTRACT_INVALID")

    def test_stats_none(self):
        s = _summary()
        s["stats"] = None
        _assert_invalid(digest.build_fact_digest(s),
                        "SUMMARY_CONTRACT_INVALID")

    def test_extra_key(self):
        s = _summary()
        s["extra"] = 1
        _assert_invalid(digest.build_fact_digest(s),
                        "SUMMARY_CONTRACT_INVALID")

    def test_bad_window(self):
        _assert_invalid(
            digest.build_fact_digest(_summary(window={"count": 1})),
            "SUMMARY_CONTRACT_INVALID")

    def test_bad_status(self):
        _assert_invalid(
            digest.build_fact_digest(_summary(status="weird")),
            "SUMMARY_CONTRACT_INVALID")


# ---------------------------------------------------------------------------
# 4. 不可变性与异常边界
# ---------------------------------------------------------------------------

class TestImmutabilityAndExceptions:
    def test_input_deep_equal_after(self):
        s = _summary()
        original = copy.deepcopy(s)
        digest.build_fact_digest(s)
        assert s == original

    def test_limitations_fixed(self):
        result = digest.build_fact_digest(_summary())
        assert result["limitations"] == [
            "deterministic digest of a fact-summary envelope",
            "stats describe normal-status days only",
            "does not compute layered promotion rates",
            "does not validate consecutive-limit-up semantics",
            "no per-stock cross-day identity tracking",
            "no trade advice, prediction, or scoring",
        ]

    @pytest.mark.parametrize("target", [
        "_validate_summary",
        "_render_stats_text",
        "_normal_envelope",
    ])
    @pytest.mark.parametrize("exc", [
        RuntimeError("boom-digest"),
        ValueError("boom-digest"),
        TypeError("boom-digest"),
    ])
    def test_ordinary_exception_fixed_fallback(self, monkeypatch, target, exc):
        def raiser(*args, **kwargs):
            raise exc
        monkeypatch.setattr(digest, target, raiser)
        result = digest.build_fact_digest(_summary())
        _assert_invalid(result, reason_code="INPUT_CONTRACT_INVALID")
        assert "boom-digest" not in repr(result)
        assert "boom-digest" not in str(result)

    @pytest.mark.parametrize("target", [
        "_validate_summary",
        "_render_stats_text",
        "_normal_envelope",
    ])
    @pytest.mark.parametrize("exc", [
        KeyboardInterrupt(),
        SystemExit(1),
        GeneratorExit(),
    ])
    def test_process_control_propagates(self, monkeypatch, target, exc):
        def raiser(*args, **kwargs):
            raise exc
        monkeypatch.setattr(digest, target, raiser)
        with pytest.raises(type(exc)):
            digest.build_fact_digest(_summary())

    def test_cross_call_isolation(self):
        first = digest.build_fact_digest(_summary())
        second = digest.build_fact_digest(_summary())
        first["limitations"].append("mutated")
        assert second["limitations"] == [
            "deterministic digest of a fact-summary envelope",
            "stats describe normal-status days only",
            "does not compute layered promotion rates",
            "does not validate consecutive-limit-up semantics",
            "no per-stock cross-day identity tracking",
            "no trade advice, prediction, or scoring",
        ]
