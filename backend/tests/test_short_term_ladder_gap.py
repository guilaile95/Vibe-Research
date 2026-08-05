"""BK-11 Slice 2J 连板梯队断层纯计算层测试。

不发起任何 live 请求。覆盖合同验证、断层/缺口语义、状态抑制、
元数据、异常边界、输入不可变性与输出引用隔离。
"""
from __future__ import annotations

import copy
import inspect
import sys

import pytest

sys.path.insert(0, "backend")

import short_term_ladder_gap as gap  # noqa: E402


TRADE_DATE = "2026-07-31"
_UNSET = object()


def _envelope(status="normal", metrics=_UNSET, reason_codes=_UNSET, **overrides):
    if metrics is _UNSET:
        metrics = {
            "max_boards": 2,
            "lianban_count": 1,
            "ladder": [{"boards": 2, "count": 1}],
        }
    if reason_codes is _UNSET:
        reason_codes = []
    envelope = {
        "schema_version": "short-term-limit-up-ladder-v0.1",
        "trade_date": TRADE_DATE,
        "session": "final",
        "is_final": True,
        "source_ids": ["eastmoney_getTopicZTPool"],
        "fetched_at": "2026-07-31T15:10:00.000000Z",
        "snapshot_at": "2026-07-31T15:10:05.000000Z",
        "status": status,
        "reason_codes": reason_codes,
        "metrics": metrics,
    }
    envelope.update(overrides)
    return envelope


def _metrics(max_boards=2, lianban_count=1, ladder=None):
    if ladder is None:
        ladder = [{"boards": 2, "count": 1}]
    return {
        "max_boards": max_boards,
        "lianban_count": lianban_count,
        "ladder": ladder,
    }


def _assert_shape(result):
    assert set(result.keys()) == {
        "schema_version", "trade_date", "session", "is_final", "source_ids",
        "fetched_at", "snapshot_at", "status", "reason_codes", "warnings",
        "limitations", "source_schema_version", "source_status",
        "source_reason_codes", "metrics",
    }
    assert result["schema_version"] == gap.SCHEMA_VERSION
    assert isinstance(result["reason_codes"], list)
    assert isinstance(result["warnings"], list)
    assert isinstance(result["limitations"], list)
    assert set(result["metrics"].keys()) == {
        "max_boards", "sample_lianban_count", "occupied_boards",
        "missing_boards", "gap_segments", "gap_level_count",
        "gap_segment_count", "largest_gap_width", "first_gap_board",
        "is_continuous",
    }


def _assert_normal_metrics(result, *, max_boards, sample_lianban_count,
                           occupied, missing, segments, gap_level_count,
                           gap_segment_count, largest_gap_width,
                           first_gap_board, is_continuous):
    m = result["metrics"]
    assert m["max_boards"] == max_boards
    assert m["sample_lianban_count"] == sample_lianban_count
    assert m["occupied_boards"] == occupied
    assert m["missing_boards"] == missing
    assert m["gap_segments"] == segments
    assert m["gap_level_count"] == gap_level_count
    assert m["gap_segment_count"] == gap_segment_count
    assert m["largest_gap_width"] == largest_gap_width
    assert m["first_gap_board"] == first_gap_board
    assert m["is_continuous"] is is_continuous


def _assert_invariant(result):
    m = result["metrics"]
    assert m["gap_level_count"] == sum(
        s["width"] for s in m["gap_segments"])
    assert m["gap_segment_count"] == len(m["gap_segments"])
    assert m["largest_gap_width"] <= m["gap_level_count"]
    assert (m["first_gap_board"] is None) == (m["gap_level_count"] == 0)
    assert m["is_continuous"] == (m["gap_level_count"] == 0)
    assert len(m["occupied_boards"]) == len(set(m["occupied_boards"]))
    assert m["occupied_boards"] == sorted(m["occupied_boards"])
    for segment in m["gap_segments"]:
        assert segment["width"] == (
            segment["to_board"] - segment["from_board"] + 1)


def _assert_suppressed(result, status, expected_codes):
    _assert_shape(result)
    assert result["status"] == status
    assert result["reason_codes"] == expected_codes
    assert all(value is None for value in result["metrics"].values())


def _assert_invalid(result):
    _assert_shape(result)
    assert result["status"] == "invalid"
    assert result["reason_codes"] == [
        "LADDER_CONTRACT_INVALID", "GAP_OUTPUT_SUPPRESSED"]
    assert result["source_reason_codes"] == []
    assert all(value is None for value in result["metrics"].values())


# ---------------------------------------------------------------------------
# 1. 公开合同
# ---------------------------------------------------------------------------

class TestPublicContract:
    def test_constants(self):
        assert gap.SCHEMA_VERSION == "short-term-ladder-gap-v0.1"
        assert gap.SOURCE_SCHEMA_VERSION == "short-term-limit-up-ladder-v0.1"

    def test_all(self):
        assert gap.__all__ == ["SCHEMA_VERSION", "compute_ladder_gap"]

    def test_signature(self):
        sig = inspect.signature(gap.compute_ladder_gap)
        assert list(sig.parameters) == ["ladder_envelope"]
        for parameter in sig.parameters.values():
            assert parameter.default is inspect.Parameter.empty


# ---------------------------------------------------------------------------
# 2. 基础断层案例
# ---------------------------------------------------------------------------

class TestGapBasics:
    def test_legal_zero(self):
        result = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(0, 0, [])))
        _assert_shape(result)
        assert result["status"] == "normal"
        _assert_normal_metrics(
            result, max_boards=0, sample_lianban_count=0, occupied=[],
            missing=[], segments=[], gap_level_count=0, gap_segment_count=0,
            largest_gap_width=0, first_gap_board=None, is_continuous=True)
        _assert_invariant(result)

    def test_first_board_only(self):
        result = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(1, 0, [])))
        assert result["status"] == "normal"
        _assert_normal_metrics(
            result, max_boards=1, sample_lianban_count=0, occupied=[],
            missing=[], segments=[], gap_level_count=0, gap_segment_count=0,
            largest_gap_width=0, first_gap_board=None, is_continuous=True)
        _assert_invariant(result)

    def test_two_board_only(self):
        result = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(2, 3, [{"boards": 2, "count": 3}])))
        assert result["status"] == "normal"
        _assert_normal_metrics(
            result, max_boards=2, sample_lianban_count=3, occupied=[2],
            missing=[], segments=[], gap_level_count=0, gap_segment_count=0,
            largest_gap_width=0, first_gap_board=None, is_continuous=True)
        _assert_invariant(result)

    def test_continuous_234(self):
        ladder = [{"boards": 2, "count": 5},
                  {"boards": 3, "count": 2},
                  {"boards": 4, "count": 1}]
        result = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(4, 8, ladder)))
        assert result["status"] == "normal"
        _assert_normal_metrics(
            result, max_boards=4, sample_lianban_count=8, occupied=[2, 3, 4],
            missing=[], segments=[], gap_level_count=0, gap_segment_count=0,
            largest_gap_width=0, first_gap_board=None, is_continuous=True)
        _assert_invariant(result)

    def test_single_gap(self):
        ladder = [{"boards": 2, "count": 4}, {"boards": 4, "count": 1}]
        result = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(4, 5, ladder)))
        assert result["status"] == "normal"
        _assert_normal_metrics(
            result, max_boards=4, sample_lianban_count=5, occupied=[2, 4],
            missing=[3], segments=[{"from_board": 3, "to_board": 3, "width": 1}],
            gap_level_count=1, gap_segment_count=1, largest_gap_width=1,
            first_gap_board=3, is_continuous=False)
        _assert_invariant(result)

    def test_start_gap(self):
        ladder = [{"boards": 4, "count": 1}]
        result = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(4, 1, ladder)))
        _assert_normal_metrics(
            result, max_boards=4, sample_lianban_count=1, occupied=[4],
            missing=[2, 3], segments=[{"from_board": 2, "to_board": 3, "width": 2}],
            gap_level_count=2, gap_segment_count=1, largest_gap_width=2,
            first_gap_board=2, is_continuous=False)
        _assert_invariant(result)

    def test_pre_top_gap(self):
        ladder = [{"boards": 2, "count": 6}, {"boards": 4, "count": 1}]
        result = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(4, 7, ladder)))
        _assert_normal_metrics(
            result, max_boards=4, sample_lianban_count=7, occupied=[2, 4],
            missing=[3], segments=[{"from_board": 3, "to_board": 3, "width": 1}],
            gap_level_count=1, gap_segment_count=1, largest_gap_width=1,
            first_gap_board=3, is_continuous=False)
        _assert_invariant(result)

    def test_multiple_gaps(self):
        ladder = [{"boards": 2, "count": 3},
                  {"boards": 4, "count": 1},
                  {"boards": 7, "count": 1}]
        result = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(7, 5, ladder)))
        _assert_normal_metrics(
            result, max_boards=7, sample_lianban_count=5, occupied=[2, 4, 7],
            missing=[3, 5, 6],
            segments=[{"from_board": 3, "to_board": 3, "width": 1},
                      {"from_board": 5, "to_board": 6, "width": 2}],
            gap_level_count=3, gap_segment_count=2, largest_gap_width=2,
            first_gap_board=3, is_continuous=False)
        _assert_invariant(result)

    def test_continuous_multi_level_gap(self):
        ladder = [{"boards": 2, "count": 2}, {"boards": 8, "count": 1}]
        result = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(8, 3, ladder)))
        _assert_normal_metrics(
            result, max_boards=8, sample_lianban_count=3, occupied=[2, 8],
            missing=[3, 4, 5, 6, 7],
            segments=[{"from_board": 3, "to_board": 7, "width": 5}],
            gap_level_count=5, gap_segment_count=1, largest_gap_width=5,
            first_gap_board=3, is_continuous=False)
        _assert_invariant(result)

    def test_high_top_low_sample(self):
        ladder = [{"boards": 2, "count": 1}, {"boards": 30, "count": 1}]
        result = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(30, 2, ladder)))
        assert result["status"] == "normal"
        assert result["metrics"]["missing_boards"][:3] == [3, 4, 5]
        assert result["metrics"]["gap_level_count"] == 27
        assert result["metrics"]["gap_segment_count"] == 1
        assert result["metrics"]["largest_gap_width"] == 27
        assert result["metrics"]["is_continuous"] is False
        _assert_invariant(result)

    def test_count_does_not_affect_occupied_levels(self):
        ladder_a = [{"boards": 2, "count": 1}, {"boards": 5, "count": 1}]
        ladder_b = [{"boards": 2, "count": 9}, {"boards": 5, "count": 3}]
        result_a = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(5, 2, ladder_a)))
        result_b = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(5, 12, ladder_b)))
        assert result_a["metrics"]["occupied_boards"] == [2, 5]
        assert result_a["metrics"]["missing_boards"] == [3, 4]
        assert result_b["metrics"]["occupied_boards"] == [2, 5]
        assert result_b["metrics"]["missing_boards"] == [3, 4]
        assert result_a["metrics"]["sample_lianban_count"] == 2
        assert result_b["metrics"]["sample_lianban_count"] == 12
        _assert_invariant(result_a)
        _assert_invariant(result_b)


# ---------------------------------------------------------------------------
# 3. ladder 合同验证
# ---------------------------------------------------------------------------

class TestLadderContract:
    def _assert_invalid_metrics(self, metrics):
        result = gap.compute_ladder_gap(_envelope(metrics=metrics))
        _assert_invalid(result)

    def test_unsorted_ladder(self):
        self._assert_invalid_metrics(
            _metrics(4, 2, [{"boards": 4, "count": 1},
                            {"boards": 2, "count": 1}]))

    def test_duplicate_boards(self):
        self._assert_invalid_metrics(
            _metrics(2, 2, [{"boards": 2, "count": 1},
                            {"boards": 2, "count": 1}]))

    @pytest.mark.parametrize("bad", [True, False])
    def test_boards_bool(self, bad):
        self._assert_invalid_metrics(
            _metrics(2, 1, [{"boards": bad, "count": 1}]))

    @pytest.mark.parametrize("bad", [True, False])
    def test_count_bool(self, bad):
        self._assert_invalid_metrics(
            _metrics(2, 1, [{"boards": 2, "count": bad}]))

    @pytest.mark.parametrize("bad", [2.0, "2"])
    def test_boards_float_string(self, bad):
        self._assert_invalid_metrics(
            _metrics(2, 1, [{"boards": bad, "count": 1}]))

    @pytest.mark.parametrize("bad", [1.0, "1"])
    def test_count_float_string(self, bad):
        self._assert_invalid_metrics(
            _metrics(2, 1, [{"boards": 2, "count": bad}]))

    @pytest.mark.parametrize("boards", [0, 1, -2])
    def test_boards_below_2(self, boards):
        self._assert_invalid_metrics(
            _metrics(2, 1, [{"boards": boards, "count": 1}]))

    @pytest.mark.parametrize("count", [0, -1])
    def test_count_non_positive(self, count):
        self._assert_invalid_metrics(
            _metrics(2, 1, [{"boards": 2, "count": count}]))

    def test_max_boards_mismatch(self):
        self._assert_invalid_metrics(
            _metrics(3, 1, [{"boards": 2, "count": 1}]))

    def test_lianban_count_mismatch(self):
        self._assert_invalid_metrics(
            _metrics(2, 2, [{"boards": 2, "count": 1}]))

    def test_extra_ladder_field(self):
        self._assert_invalid_metrics(
            _metrics(2, 1, [{"boards": 2, "count": 1, "extra": 1}]))

    def test_missing_ladder_field(self):
        self._assert_invalid_metrics(
            _metrics(2, 1, [{"boards": 2}]))

    def test_ladder_item_subclass(self):
        class D(dict):
            pass
        self._assert_invalid_metrics(
            _metrics(2, 1, [D(boards=2, count=1)]))

    def test_ladder_not_list(self):
        self._assert_invalid_metrics(
            {"max_boards": 2, "lianban_count": 1, "ladder": "x"})

    def test_ladder_list_subclass(self):
        class L(list):
            pass
        self._assert_invalid_metrics(
            {"max_boards": 2, "lianban_count": 1,
             "ladder": L([{"boards": 2, "count": 1}])})

    def test_max_boards_non_int(self):
        for bad in [True, 2.0, "2"]:
            self._assert_invalid_metrics(
                {"max_boards": bad, "lianban_count": 1,
                 "ladder": [{"boards": 2, "count": 1}]})

    def test_max_boards_negative(self):
        self._assert_invalid_metrics(
            {"max_boards": -1, "lianban_count": 0, "ladder": []})

    def test_lianban_count_non_int(self):
        for bad in [True, 1.0, "1"]:
            self._assert_invalid_metrics(
                {"max_boards": 2, "lianban_count": bad,
                 "ladder": [{"boards": 2, "count": 1}]})

    def test_lianban_zero_with_ladder(self):
        self._assert_invalid_metrics(
            _metrics(2, 0, [{"boards": 2, "count": 1}]))

    def test_lianban_zero_max_boards_two(self):
        self._assert_invalid_metrics(_metrics(2, 0, []))

    def test_max_boards_high_empty_ladder(self):
        self._assert_invalid_metrics(_metrics(5, 0, []))

    def test_lianban_positive_empty_ladder(self):
        self._assert_invalid_metrics(_metrics(2, 1, []))

    def test_max_boards_one_ladder_nonempty(self):
        self._assert_invalid_metrics(
            {"max_boards": 1, "lianban_count": 1,
             "ladder": [{"boards": 2, "count": 1}]})

    def test_metrics_extra_field(self):
        metrics = _metrics()
        metrics["extra"] = 1
        result = gap.compute_ladder_gap(_envelope(metrics=metrics))
        _assert_invalid(result)

    def test_metrics_missing_field(self):
        metrics = _metrics()
        del metrics["ladder"]
        result = gap.compute_ladder_gap(_envelope(metrics=metrics))
        _assert_invalid(result)

    def test_metrics_subclass(self):
        class D(dict):
            pass
        metrics = _metrics()
        subclass = D(metrics)
        result = gap.compute_ladder_gap(_envelope(metrics=subclass))
        _assert_invalid(result)


# ---------------------------------------------------------------------------
# 4. 状态抑制
# ---------------------------------------------------------------------------

class TestStatusSuppression:
    def test_source_partial(self):
        envelope = _envelope(
            status="partial",
            reason_codes=["SOURCE_PARTIAL", "PARTIAL_COVERAGE"],
            metrics={"max_boards": None, "lianban_count": None, "ladder": None})
        result = gap.compute_ladder_gap(envelope)
        _assert_suppressed(result, "partial", [
            "SOURCE_PARTIAL", "UPSTREAM_LADDER_PARTIAL",
            "GAP_OUTPUT_SUPPRESSED"])
        assert result["source_status"] == "partial"
        assert result["source_reason_codes"] == [
            "SOURCE_PARTIAL", "PARTIAL_COVERAGE"]

    def test_partial_metrics_values_ignored(self):
        envelope = _envelope(
            status="partial",
            metrics=_metrics(30, 999, [{"boards": 2, "count": 1}]))
        result = gap.compute_ladder_gap(envelope)
        assert result["status"] == "partial"
        assert all(value is None for value in result["metrics"].values())

    def test_source_unavailable(self):
        envelope = _envelope(
            status="unavailable",
            reason_codes=["SOURCE_UNAVAILABLE"],
            metrics={"max_boards": None, "lianban_count": None, "ladder": None})
        result = gap.compute_ladder_gap(envelope)
        _assert_suppressed(result, "unavailable", [
            "SOURCE_UNAVAILABLE", "UPSTREAM_LADDER_UNAVAILABLE",
            "GAP_OUTPUT_SUPPRESSED"])
        assert result["source_status"] == "unavailable"

    def test_unavailable_metrics_values_ignored(self):
        envelope = _envelope(
            status="unavailable",
            metrics=_metrics(30, 999, [{"boards": 2, "count": 1}]))
        result = gap.compute_ladder_gap(envelope)
        assert result["status"] == "unavailable"
        assert all(value is None for value in result["metrics"].values())

    @pytest.mark.parametrize("bad_status", ["weird", 1, None, ""])
    def test_illegal_status(self, bad_status):
        result = gap.compute_ladder_gap(_envelope(status=bad_status))
        _assert_invalid(result)


# ---------------------------------------------------------------------------
# 5. source reason codes
# ---------------------------------------------------------------------------

class TestSourceReasonCodes:
    def test_dedupe_preserve_order(self):
        envelope = _envelope(
            reason_codes=["B", "A", "B", "C"],
            metrics=_metrics(2, 1, [{"boards": 2, "count": 1}]))
        result = gap.compute_ladder_gap(envelope)
        assert result["status"] == "normal"
        assert result["reason_codes"] == []
        assert result["source_reason_codes"] == ["B", "A", "C"]

    def test_unknown_codes_kept_in_source_only(self):
        envelope = _envelope(reason_codes=["UNKNOWN_UPSTREAM", "SOURCE_PARTIAL"])
        result = gap.compute_ladder_gap(envelope)
        assert result["status"] == "normal"
        assert result["reason_codes"] == []
        assert result["source_reason_codes"] == [
            "UNKNOWN_UPSTREAM", "SOURCE_PARTIAL"]

    @pytest.mark.parametrize("bad", ["not-a-list", 1, None, {"a": 1}])
    def test_not_list(self, bad):
        result = gap.compute_ladder_gap(_envelope(reason_codes=bad))
        _assert_invalid(result)

    def test_list_subclass(self):
        class L(list):
            pass
        result = gap.compute_ladder_gap(
            _envelope(reason_codes=L(["X"])))
        _assert_invalid(result)

    @pytest.mark.parametrize("bad", ["", 1, None, b"x"])
    def test_non_empty_string_items(self, bad):
        result = gap.compute_ladder_gap(
            _envelope(reason_codes=[bad]))
        _assert_invalid(result)

    def test_string_subclass_item(self):
        class S(str):
            pass
        result = gap.compute_ladder_gap(
            _envelope(reason_codes=[S("X")]))
        _assert_invalid(result)


# ---------------------------------------------------------------------------
# 6. 元数据
# ---------------------------------------------------------------------------

class TestMetadata:
    @pytest.mark.parametrize("bad", ["2026-7-31", "20260731", "2026-13-01",
                                     "2026-02-30", "", 20260731, None])
    def test_bad_trade_date(self, bad):
        result = gap.compute_ladder_gap(_envelope(trade_date=bad))
        _assert_invalid(result)

    def test_real_calendar_date_accepted(self):
        result = gap.compute_ladder_gap(_envelope(trade_date="2024-02-29"))
        assert result["status"] == "normal"

    @pytest.mark.parametrize("bad", ["draft", 1, None, ""])
    def test_bad_session(self, bad):
        result = gap.compute_ladder_gap(_envelope(session=bad))
        _assert_invalid(result)

    def test_allowed_sessions(self):
        for session in ["pre_open", "call_auction", "morning_session",
                        "midday_break", "afternoon_session", "close_pending",
                        "final", "unavailable"]:
            is_final = session == "final"
            result = gap.compute_ladder_gap(
                _envelope(session=session, is_final=is_final))
            assert result["status"] == "normal", session
            assert result["session"] == session
            assert result["is_final"] is is_final

    def test_is_final_false_with_final_session(self):
        result = gap.compute_ladder_gap(
            _envelope(session="final", is_final=False))
        _assert_invalid(result)

    def test_is_final_true_with_non_final_session(self):
        result = gap.compute_ladder_gap(
            _envelope(session="unavailable", is_final=True))
        _assert_invalid(result)

    def test_is_final_non_bool(self):
        for bad in [1, 0, "true", None]:
            result = gap.compute_ladder_gap(_envelope(is_final=bad))
            _assert_invalid(result)

    @pytest.mark.parametrize("bad", ["not-a-list", 1, None, "x"])
    def test_source_ids_not_list(self, bad):
        result = gap.compute_ladder_gap(_envelope(source_ids=bad))
        _assert_invalid(result)

    def test_source_ids_empty_string(self):
        result = gap.compute_ladder_gap(
            _envelope(source_ids=["eastmoney_getTopicZTPool", ""]))
        _assert_invalid(result)

    def test_source_ids_non_str(self):
        result = gap.compute_ladder_gap(
            _envelope(source_ids=["x", 1]))
        _assert_invalid(result)

    def test_source_ids_empty_list_accepted(self):
        # 与上游行为一致：仅约束成员为非空字符串，空列表合法
        result = gap.compute_ladder_gap(_envelope(source_ids=[]))
        assert result["status"] == "normal"
        assert result["source_ids"] == []

    def test_source_ids_dedupe(self):
        result = gap.compute_ladder_gap(
            _envelope(source_ids=["a", "b", "a"]))
        assert result["status"] == "normal"
        assert result["source_ids"] == ["a", "b"]

    @pytest.mark.parametrize("bad", [1, True, 1.5, "", "not-a-time",
                                     "2026-07-31T15:10:00",  # naive
                                     "2026-07-31T15:10:00+08:00"])
    def test_bad_fetched_at(self, bad):
        result = gap.compute_ladder_gap(_envelope(fetched_at=bad))
        _assert_invalid(result)

    @pytest.mark.parametrize("bad", [1, True, "not-a-time",
                                     "2026-07-31T15:10:00+08:00"])
    def test_bad_snapshot_at(self, bad):
        result = gap.compute_ladder_gap(_envelope(snapshot_at=bad))
        _assert_invalid(result)

    def test_timestamps_null_accepted(self):
        result = gap.compute_ladder_gap(
            _envelope(fetched_at=None, snapshot_at=None))
        assert result["status"] == "normal"
        assert result["fetched_at"] is None
        assert result["snapshot_at"] is None

    def test_one_timestamp_null_accepted(self):
        result = gap.compute_ladder_gap(
            _envelope(fetched_at=None))
        assert result["status"] == "normal"

    def test_fetched_after_snapshot_invalid(self):
        result = gap.compute_ladder_gap(_envelope(
            fetched_at="2026-07-31T15:10:06.000000Z",
            snapshot_at="2026-07-31T15:10:05.000000Z"))
        _assert_invalid(result)

    def test_equal_timestamps_accepted(self):
        result = gap.compute_ladder_gap(_envelope(
            fetched_at="2026-07-31T15:10:05.000000Z",
            snapshot_at="2026-07-31T15:10:05.000000Z"))
        assert result["status"] == "normal"

    def test_z_and_plus_zero_accepted(self):
        for value in ["2026-07-31T15:10:05Z",
                      "2026-07-31T15:10:05+00:00"]:
            result = gap.compute_ladder_gap(_envelope(
                fetched_at=value, snapshot_at=value))
            assert result["status"] == "normal", value


# ---------------------------------------------------------------------------
# 7. 输入 envelope 合同
# ---------------------------------------------------------------------------

class TestInputContract:
    def test_non_dict(self):
        for bad in [None, "x", 1, [], ("a",)]:
            result = gap.compute_ladder_gap(bad)
            _assert_invalid(result)

    def test_dict_subclass(self):
        class D(dict):
            pass
        result = gap.compute_ladder_gap(D(_envelope()))
        _assert_invalid(result)

    def test_wrong_schema(self):
        envelope = _envelope()
        envelope["schema_version"] = "wrong"
        result = gap.compute_ladder_gap(envelope)
        _assert_invalid(result)

    def test_missing_envelope_field(self):
        envelope = _envelope()
        del envelope["metrics"]
        result = gap.compute_ladder_gap(envelope)
        _assert_invalid(result)

    def test_extra_envelope_field_ignored(self):
        envelope = _envelope()
        envelope["extra"] = 1
        result = gap.compute_ladder_gap(envelope)
        assert result["status"] == "normal"
        assert "extra" not in result

    def test_caller_gap_fields_ignored(self):
        envelope = _envelope()
        envelope["gap"] = [999]
        envelope["missing_boards"] = [999]
        envelope["is_continuous"] = False
        envelope["gap_segments"] = [{"from_board": 999}]
        result = gap.compute_ladder_gap(envelope)
        assert result["status"] == "normal"
        assert result["metrics"]["missing_boards"] == []
        assert result["metrics"]["gap_segments"] == []
        assert result["metrics"]["is_continuous"] is True


# ---------------------------------------------------------------------------
# 8. 输出合同
# ---------------------------------------------------------------------------

class TestOutputContract:
    def test_limitations_fixed(self):
        result = gap.compute_ladder_gap(_envelope())
        assert result["limitations"] == [
            "derived from an already-computed ladder envelope",
            "gap domain starts at board level 2",
            "does not validate upstream consecutive-limit-up semantics",
            "does not compute layered promotion rates",
        ]

    def test_caller_limitations_not_passed_through(self):
        envelope = _envelope()
        envelope["limitations"] = ["caller limitation"]
        result = gap.compute_ladder_gap(envelope)
        assert "caller limitation" not in result["limitations"]

    def test_normal_envelope(self):
        result = gap.compute_ladder_gap(_envelope())
        _assert_shape(result)
        assert result["status"] == "normal"
        assert result["reason_codes"] == []
        assert result["warnings"] == []
        assert result["trade_date"] == TRADE_DATE
        assert result["session"] == "final"
        assert result["is_final"] is True
        assert result["source_ids"] == ["eastmoney_getTopicZTPool"]
        assert result["fetched_at"] == "2026-07-31T15:10:00.000000Z"
        assert result["snapshot_at"] == "2026-07-31T15:10:05.000000Z"
        assert result["source_schema_version"] == (
            "short-term-limit-up-ladder-v0.1")
        assert result["source_status"] == "normal"
        assert result["source_reason_codes"] == []


# ---------------------------------------------------------------------------
# 9. 输入不可变性与引用隔离
# ---------------------------------------------------------------------------

class TestImmutability:
    def test_input_deep_equal_after(self):
        ladder = [{"boards": 2, "count": 1}, {"boards": 5, "count": 2}]
        envelope = _envelope(metrics=_metrics(5, 3, ladder))
        original = copy.deepcopy(envelope)
        gap.compute_ladder_gap(envelope)
        assert envelope == original

    @pytest.mark.parametrize("status", ["partial", "unavailable", "invalid"])
    def test_input_deep_equal_after_failures(self, status):
        envelope = _envelope(status=status)
        original = copy.deepcopy(envelope)
        gap.compute_ladder_gap(envelope)
        assert envelope == original

    def test_no_shared_mutable_references(self):
        ladder = [{"boards": 2, "count": 1}, {"boards": 5, "count": 2}]
        envelope = _envelope(metrics=_metrics(5, 3, ladder))
        result = gap.compute_ladder_gap(envelope)
        assert result["metrics"]["occupied_boards"] is not ladder
        assert result["metrics"]["missing_boards"] is not ladder
        assert result["source_ids"] is not envelope["source_ids"]
        assert result["source_reason_codes"] is not envelope["reason_codes"]
        # 修改输出不得影响输入
        result["metrics"]["occupied_boards"].append(999)
        result["metrics"]["missing_boards"].append(999)
        assert [item["boards"] for item in envelope["metrics"]["ladder"]] == [2, 5]


# ---------------------------------------------------------------------------
# 10. 普通异常边界与进程控制
# ---------------------------------------------------------------------------

class TestExceptionBoundary:
    HELPERS = [
        "_validate_input_contract",
        "_validate_metadata",
        "_validate_metrics",
        "_compute_gap_metrics",
        "_normal_envelope",
    ]

    @pytest.mark.parametrize("target", HELPERS)
    @pytest.mark.parametrize("exc", [
        RuntimeError("boom-ladder-gap"),
        ValueError("boom-ladder-gap"),
        TypeError("boom-ladder-gap"),
    ])
    def test_ordinary_exception_fixed_fallback(self, monkeypatch, target, exc):
        def raiser(*args, **kwargs):
            raise exc
        monkeypatch.setattr(gap, target, raiser)
        result = gap.compute_ladder_gap(_envelope())
        _assert_invalid(result)
        assert "boom-ladder-gap" not in repr(result)
        assert "boom-ladder-gap" not in str(result)

    @pytest.mark.parametrize("target", HELPERS)
    @pytest.mark.parametrize("exc", [
        KeyboardInterrupt(),
        SystemExit(1),
        GeneratorExit(),
    ])
    def test_process_control_propagates(self, monkeypatch, target, exc):
        def raiser(*args, **kwargs):
            raise exc
        monkeypatch.setattr(gap, target, raiser)
        with pytest.raises(type(exc)):
            gap.compute_ladder_gap(_envelope())

    def test_exception_text_not_leaked_from_nested_helper(self, monkeypatch):
        def raiser(*args, **kwargs):
            raise RuntimeError("secret-token-ladder-gap")
        monkeypatch.setattr(gap, "_compute_gap_metrics", raiser)
        result = gap.compute_ladder_gap(_envelope())
        assert "secret-token-ladder-gap" not in str(result)


# ---------------------------------------------------------------------------
# 11. 与真实上游输出的联合路径
# ---------------------------------------------------------------------------

class TestUpstreamJoint:
    """用真实 compute_limit_up_ladder 输出作为输入（纯内存，无网络）。"""

    @staticmethod
    def _upstream_envelope(**overrides):
        import short_term_limit_up_ladder as ladder
        snapshot = {
            "trade_date": "2026-07-31",
            "session": "final",
            "is_final": True,
            "source_ids": ["eastmoney_getTopicZTPool"],
            "fetched_at": "2026-07-31T15:10:00.000000Z",
            "snapshot_at": "2026-07-31T15:10:05.000000Z",
            "data_health": {
                "transport_success": True,
                "parse_success": True,
                "required_field_present": True,
                "data_array_present": True,
                "trade_date_match": True,
                "row_count": 3,
                "legal_zero": False,
                "upstream_null": False,
                "unexplained_empty": False,
                "coverage_warning": False,
            },
            "limit_up_pool": [
                {"stock_code": "600001", "consecutive_limit_up_days": 2},
                {"stock_code": "600002", "consecutive_limit_up_days": 2},
                {"stock_code": "600003", "consecutive_limit_up_days": 4},
            ],
        }
        snapshot.update(overrides)
        return ladder.compute_limit_up_ladder(snapshot)

    def test_normal_upstream_envelope(self):
        envelope = self._upstream_envelope()
        assert envelope["status"] == "normal"
        result = gap.compute_ladder_gap(envelope)
        assert result["status"] == "normal"
        assert result["metrics"]["occupied_boards"] == [2, 4]
        assert result["metrics"]["missing_boards"] == [3]
        assert result["metrics"]["gap_segments"] == [
            {"from_board": 3, "to_board": 3, "width": 1}]
        _assert_invariant(result)

    def test_upstream_legal_zero(self):
        envelope = self._upstream_envelope(
            limit_up_pool=[],
            data_health={
                "transport_success": True,
                "parse_success": True,
                "required_field_present": True,
                "data_array_present": True,
                "trade_date_match": True,
                "row_count": 0,
                "legal_zero": True,
                "upstream_null": False,
                "unexplained_empty": False,
                "coverage_warning": False,
            })
        assert envelope["status"] == "normal"
        result = gap.compute_ladder_gap(envelope)
        assert result["status"] == "normal"
        assert result["metrics"]["occupied_boards"] == []
        assert result["metrics"]["missing_boards"] == []
        assert result["metrics"]["is_continuous"] is True

    def test_upstream_unavailable_suppressed(self):
        envelope = self._upstream_envelope(
            data_health={
                "transport_success": False,
                "parse_success": False,
                "required_field_present": False,
                "data_array_present": False,
                "trade_date_match": False,
                "row_count": 0,
                "legal_zero": False,
                "upstream_null": True,
                "unexplained_empty": False,
                "coverage_warning": False,
            })
        assert envelope["status"] == "unavailable"
        result = gap.compute_ladder_gap(envelope)
        _assert_suppressed(result, "unavailable", [
            "SOURCE_UNAVAILABLE", "UPSTREAM_LADDER_UNAVAILABLE",
            "GAP_OUTPUT_SUPPRESSED"])


# ---------------------------------------------------------------------------
# 12. 有界板级合同（P1）
# ---------------------------------------------------------------------------

class TestBoardBounds:
    def test_max_boards_1001_invalid(self):
        result = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(1001, 1, [{"boards": 1001, "count": 1}])))
        _assert_invalid(result)

    def test_max_boards_huge_integer_invalid(self):
        result = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(
                10 ** 30, 1, [{"boards": 10 ** 30, "count": 1}])))
        _assert_invalid(result)

    def test_huge_integer_does_not_enter_gap_helper(self, monkeypatch):
        calls = {"n": 0}
        original = gap._compute_gap_metrics

        def wrapper(*args, **kwargs):
            calls["n"] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(gap, "_compute_gap_metrics", wrapper)
        result = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(
                10 ** 30, 1, [{"boards": 10 ** 30, "count": 1}])))
        _assert_invalid(result)
        assert calls["n"] == 0

    def test_max_boards_1001_does_not_enter_gap_helper(self, monkeypatch):
        calls = {"n": 0}
        original = gap._compute_gap_metrics

        def wrapper(*args, **kwargs):
            calls["n"] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(gap, "_compute_gap_metrics", wrapper)
        result = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(1001, 1, [{"boards": 1001, "count": 1}])))
        _assert_invalid(result)
        assert calls["n"] == 0

    @pytest.mark.parametrize("bad_boards", [1001, 10 ** 30])
    def test_boards_over_limit_invalid(self, bad_boards):
        result = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(2, 1, [{"boards": bad_boards, "count": 1}])))
        _assert_invalid(result)

    def test_max_boards_1000_boundary_valid(self):
        metrics = _metrics(1000, 1, [{"boards": 1000, "count": 1}])
        result = gap.compute_ladder_gap(_envelope(metrics=metrics))
        assert result["status"] == "normal"
        m = result["metrics"]
        assert m["max_boards"] == 1000
        assert m["occupied_boards"] == [1000]
        assert m["missing_boards"] == list(range(2, 1000))
        assert m["gap_segments"] == [
            {"from_board": 2, "to_board": 999, "width": 998}]
        assert m["gap_level_count"] == 998
        assert m["gap_segment_count"] == 1
        assert m["largest_gap_width"] == 998
        assert m["first_gap_board"] == 2
        assert m["is_continuous"] is False
        _assert_invariant(result)

    def test_ladder_length_over_999_invalid(self):
        ladder = [{"boards": boards, "count": 1}
                  for boards in range(2, 1002)]
        assert len(ladder) == 1000
        result = gap.compute_ladder_gap(
            _envelope(metrics=_metrics(1001, 1000, ladder)))
        _assert_invalid(result)


# ---------------------------------------------------------------------------
# 13. 时间戳前后空白（P2-1）
# ---------------------------------------------------------------------------

class TestTimestampWhitespace:
    @pytest.mark.parametrize("bad", [
        " 2026-07-31T15:10:00Z",
        "2026-07-31T15:10:00Z ",
        " 2026-07-31T15:10:00Z ",
        "\t2026-07-31T15:10:00Z",
        "2026-07-31T15:10:00Z\n",
    ])
    def test_fetched_at_whitespace_invalid(self, bad):
        result = gap.compute_ladder_gap(_envelope(fetched_at=bad))
        _assert_invalid(result)

    @pytest.mark.parametrize("bad", [
        " 2026-07-31T15:10:05Z",
        "2026-07-31T15:10:05Z ",
        " 2026-07-31T15:10:05Z ",
        "\t2026-07-31T15:10:05Z",
        "2026-07-31T15:10:05Z\n",
    ])
    def test_snapshot_at_whitespace_invalid(self, bad):
        result = gap.compute_ladder_gap(_envelope(snapshot_at=bad))
        _assert_invalid(result)

    def test_whitespace_not_stripped_and_accepted(self):
        # 空白值不得被 strip 后放行
        result = gap.compute_ladder_gap(
            _envelope(fetched_at=" 2026-07-31T15:10:00Z"))
        assert result["status"] == "invalid"

    def test_lowercase_z_uppercase_formats_accepted(self):
        # 仅时区指示符小写 z 且格式合法时应可接受
        result = gap.compute_ladder_gap(_envelope(
            fetched_at="2026-07-31T15:10:00z",
            snapshot_at="2026-07-31T15:10:05Z"))
        assert result["status"] == "normal"


# ---------------------------------------------------------------------------
# 14. 模块全局污染与跨调用隔离（P2-2）
# ---------------------------------------------------------------------------

class TestGlobalPollution:
    STANDARD_LIMITATIONS = [
        "derived from an already-computed ladder envelope",
        "gap domain starts at board level 2",
        "does not validate upstream consecutive-limit-up semantics",
        "does not compute layered promotion rates",
    ]

    @pytest.fixture
    def polluted(self, monkeypatch):
        monkeypatch.setattr(
            gap, "_METRICS_NULL", {"max_boards": 999}, raising=False)
        monkeypatch.setattr(
            gap, "_LIMITATIONS", ("hacked",), raising=False)

    def _assert_standard_limitations(self, result):
        assert result["limitations"] == self.STANDARD_LIMITATIONS

    def test_normal_immune(self, polluted):
        result = gap.compute_ladder_gap(_envelope())
        self._assert_standard_limitations(result)
        assert result["status"] == "normal"

    def test_partial_immune(self, polluted):
        result = gap.compute_ladder_gap(
            _envelope(status="partial", reason_codes=["SOURCE_PARTIAL"]))
        self._assert_standard_limitations(result)
        assert result["status"] == "partial"
        assert all(value is None for value in result["metrics"].values())

    def test_unavailable_immune(self, polluted):
        result = gap.compute_ladder_gap(
            _envelope(status="unavailable", reason_codes=["SOURCE_UNAVAILABLE"]))
        self._assert_standard_limitations(result)
        assert result["status"] == "unavailable"
        assert all(value is None for value in result["metrics"].values())

    def test_invalid_immune(self, polluted):
        result = gap.compute_ladder_gap(_envelope(metrics=_metrics(1001, 1, [
            {"boards": 1001, "count": 1}])))
        self._assert_standard_limitations(result)
        assert result["status"] == "invalid"
        assert all(value is None for value in result["metrics"].values())

    def test_emergency_immune(self, polluted, monkeypatch):
        def raiser(*args, **kwargs):
            raise RuntimeError("boom")
        monkeypatch.setattr(gap, "_validate_metrics", raiser)
        result = gap.compute_ladder_gap(_envelope())
        self._assert_standard_limitations(result)
        assert result["status"] == "invalid"
        assert all(value is None for value in result["metrics"].values())

    def test_cross_call_isolation(self):
        first = gap.compute_ladder_gap(_envelope())
        second = gap.compute_ladder_gap(_envelope())
        first["limitations"].append("mutated")
        first["metrics"]["occupied_boards"] = [999]
        assert second["limitations"] == self.STANDARD_LIMITATIONS
        assert second["metrics"]["occupied_boards"] == [2]

    def test_failure_cross_call_isolation(self):
        first = gap.compute_ladder_gap(
            _envelope(status="partial", reason_codes=["SOURCE_PARTIAL"]))
        second = gap.compute_ladder_gap(
            _envelope(status="partial", reason_codes=["SOURCE_PARTIAL"]))
        first["limitations"].append("mutated")
        first["metrics"]["max_boards"] = 5
        assert second["limitations"] == self.STANDARD_LIMITATIONS
        assert second["metrics"]["max_boards"] is None
