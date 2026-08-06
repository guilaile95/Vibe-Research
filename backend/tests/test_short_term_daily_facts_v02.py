"""BK-11 daily-facts v0.2 组合层离线测试。"""

from __future__ import annotations

import sys

sys.path.insert(0, "backend")

import short_term_daily_facts_v02 as v02  # noqa: E402


T = "2026-07-30"


def _facts(limit_up=1, status="normal", legal_zero=False):
    return {
        "schema_version": "bk11-tushare-facts-adapter-v0.1",
        "trade_date": T,
        "session": "final",
        "is_final": True,
        "source_ids": ["tushare_daily", "tushare_suspend_d",
                       "tushare_stk_limit", "tushare_stock_basic"],
        "fetched_at": "2026-07-31T01:00:00.000000Z",
        "snapshot_at": "2026-07-31T01:00:00.000000Z",
        "status": status,
        "reason_codes": [] if status == "normal" else ["COVERAGE_WARNING"],
        "warnings": [],
        "limitations": ["Tushare 第三方数据服务，非交易所直发"],
        "breadth": {
            "advance_count": 3000,
            "decline_count": 2000,
            "flat_count": 100,
            "suspended_count": 50,
            "eligible_count": 5150,
            "valid_count": 5100,
            "intraday_suspend_count": 0,
        },
        "limit_activity": {
            "limit_up_count": limit_up,
            "limit_down_count": 5,
            "failed_limit_up_count": 10,
            "touched_limit_up_count": limit_up + 10,
            "sealed_limit_up_count": limit_up,
            "failed_board_rate": round(10 / (limit_up + 10), 4),
            "seal_rate": round(limit_up / (limit_up + 10), 4),
        },
        "facts_data_health": {
            "transport_success": True,
            "parse_success": True,
            "required_field_present": True,
            "data_array_present": True,
            "trade_date_match": True,
            "row_count": 5100,
            "legal_zero": legal_zero,
            "upstream_null": False,
            "unexplained_empty": False,
            "coverage_warning": status == "partial",
        },
        "legal_zero": legal_zero,
        "universe": {},
        "sources": [],
    }


def _producer(trade_date=T, status="normal", rows=None):
    if rows is None:
        rows = [{"stock_code": "688981.SH", "lbc": 2}]
    if status != "normal":
        return {
            "schema_version": "short-term-limit-up-final-snapshot-v0.1",
            "requested_trade_date": trade_date,
            "observed_at": "2026-07-31T02:00:00.000000Z",
            "status": status,
            "reason_codes": ["SOURCE_UNAVAILABLE"] if status == "unavailable"
                            else ["SOURCE_PARTIAL"],
            "session": "final" if status == "normal" else "not_final",
            "is_final": status == "normal",
            "finality_basis": None,
            "required_observations": 3,
            "completed_observations": 0,
            "stable_observation_count": 0,
            "observation_interval_seconds": 2.2,
            "required_stability_window_seconds": 4.4,
            "actual_stability_window_seconds": None,
            "first_observation_monotonic": None,
            "last_observation_monotonic": None,
            "snapshot": None,
            "warnings": [],
        }
    return {
        "schema_version": "short-term-limit-up-final-snapshot-v0.1",
        "requested_trade_date": trade_date,
        "observed_at": "2026-07-31T02:00:00.000000Z",
        "status": "normal",
        "reason_codes": [],
        "session": "final",
        "is_final": True,
        "finality_basis": "three_identical_normal_observations",
        "required_observations": 3,
        "completed_observations": 3,
        "stable_observation_count": 3,
        "observation_interval_seconds": 2.2,
        "required_stability_window_seconds": 4.4,
        "actual_stability_window_seconds": 4.4,
        "first_observation_monotonic": 100.0,
        "last_observation_monotonic": 104.4,
        "snapshot": {
            "schema_version": "short-term-limit-up-pool-adapter-v0.1",
            "source_id": "eastmoney_getTopicZTPool",
            "endpoint": "getTopicZTPool",
            "requested_trade_date": trade_date,
            "observed_at": "2026-07-31T02:00:00.000000Z",
            "status": "normal",
            "reason_codes": [],
            "rows": rows,
            "transport_success": True,
            "parse_success": True,
            "required_field_present": True,
            "data_array_present": True,
            "trade_date_match": True,
            "row_count": len(rows),
            "legal_zero": False,
            "upstream_null": False,
            "unexplained_empty": False,
            "coverage_warning": False,
            "source_pool_row_count": len(rows),
            "http_status": 200,
            "error_class": "NONE",
            "excluded_universe_count": 0,
            "invalid_row_count": 0,
            "duplicate_code_count": 0,
        },
        "warnings": [],
    }


class TestComposer:
    def test_facts_source_is_tushare(self):
        env = v02.compute_daily_facts_v02(
            _facts(), {"kind": "producer", "envelope": _producer()})
        assert env["schema_version"] == "short-term-daily-facts-v0.2"
        assert env["status"] == "normal"
        facts_section = env["sections"]["facts"]
        assert facts_section["source_ids"] == [
            "tushare_daily", "tushare_suspend_d",
            "tushare_stk_limit", "tushare_stock_basic"]
        assert facts_section["facts"]["advance_count"] == 3000
        assert facts_section["facts"]["limit_up_count"] == 1

    def test_ladder_source_is_eastmoney(self):
        env = v02.compute_daily_facts_v02(
            _facts(), {"kind": "producer", "envelope": _producer()})
        ladder = env["sections"]["ladder"]
        assert ladder["source_ids"] == ["eastmoney_getTopicZTPool"]
        assert ladder["metrics"]["max_boards"] == 2
        assert ladder["metrics"]["lianban_count"] == 1
        gap = env["sections"]["gap"]
        assert gap is not None

    def test_top_level_source_union(self):
        env = v02.compute_daily_facts_v02(
            _facts(), {"kind": "producer", "envelope": _producer()})
        assert "tushare_daily" in env["source_ids"]
        assert "eastmoney_getTopicZTPool" in env["source_ids"]
        assert env["source_ids"] == sorted(env["source_ids"])

    def test_trade_date_mismatch_fails_closed(self):
        env = v02.compute_daily_facts_v02(
            _facts(), {"kind": "producer",
                       "envelope": _producer(trade_date="2026-07-29")})
        assert env["status"] == "invalid"
        assert "TRADE_DATE_MISMATCH" in env["reason_codes"]

    def test_cross_source_counts_match(self):
        env = v02.compute_daily_facts_v02(
            _facts(limit_up=1),
            {"kind": "producer", "envelope": _producer(rows=[
                {"stock_code": "688981.SH", "lbc": 2}])})
        assert env["status"] == "normal"
        assert "CROSS_SOURCE_COUNT_MISMATCH" not in env["reason_codes"]

    def test_cross_source_count_mismatch_partial(self):
        env = v02.compute_daily_facts_v02(
            _facts(limit_up=10),
            {"kind": "producer", "envelope": _producer(rows=[
                {"stock_code": "688981.SH", "lbc": 2}])})
        assert env["status"] == "partial"
        assert "CROSS_SOURCE_COUNT_MISMATCH" in env["reason_codes"]
        assert any("跨源涨停数量不一致" in l for l in env["limitations"])

    def test_zero_legal_proof_empty_ladder(self):
        env = v02.compute_daily_facts_v02(
            _facts(limit_up=0, legal_zero=True),
            {"kind": "empty_ladder_proof"})
        assert env["status"] == "normal"
        ladder = env["sections"]["ladder"]
        assert ladder["metrics"]["max_boards"] == 0
        assert ladder["metrics"]["lianban_count"] == 0
        assert ladder["data_health"]["legal_zero"] is True
        gap = env["sections"]["gap"]
        assert gap["metrics"]["gap_level_count"] == 0

    def test_zero_without_proof_rejected(self):
        env = v02.compute_daily_facts_v02(
            _facts(limit_up=0, legal_zero=False),
            {"kind": "empty_ladder_proof"})
        assert env["status"] == "invalid"
        assert "LEGAL_ZERO_PROOF_INVALID" in env["reason_codes"]

    def test_producer_unavailable_keeps_facts_partial(self):
        env = v02.compute_daily_facts_v02(
            _facts(), {"kind": "producer",
                       "envelope": _producer(status="unavailable")})
        # worst-status 语义与 v0.1 一致：producer unavailable → 整体 unavailable
        assert env["status"] == "unavailable"
        assert env["sections"]["facts"] is not None
        assert env["sections"]["ladder"] is None
        assert env["sections"]["gap"] is None
        assert "UPSTREAM_LADDER_UNAVAILABLE" in env["reason_codes"]

    def test_invalid_ladder_input(self):
        env = v02.compute_daily_facts_v02(_facts(), {"kind": "bogus"})
        assert env["status"] == "invalid"

    def test_malformed_producer_rows_never_raise(self):
        producer = _producer(rows=[{"stock_code": 12345, "lbc": "x"}])
        env = v02.compute_daily_facts_v02(
            _facts(), {"kind": "producer", "envelope": producer})
        assert env["status"] in ("invalid", "partial", "unavailable")

    def test_top_level_shape_compatible(self):
        env = v02.compute_daily_facts_v02(
            _facts(), {"kind": "producer", "envelope": _producer()})
        assert set(env.keys()) == {
            "schema_version", "trade_date", "session", "is_final",
            "source_ids", "fetched_at", "snapshot_at", "status",
            "reason_codes", "warnings", "limitations",
            "source_schema_version", "source_status",
            "source_reason_codes", "sections"}
        assert env["session"] == "final"
        assert env["is_final"] is True
        assert env["trade_date"] == T

    def test_facts_partial_overall_partial(self):
        env = v02.compute_daily_facts_v02(
            _facts(status="partial"),
            {"kind": "producer", "envelope": _producer()})
        assert env["status"] == "partial"


class TestChainCompatibility:
    def test_compare_summary_digest_accept_v02(self):
        prev_facts = dict(_facts())
        prev_facts["trade_date"] = "2026-07-29"
        prev_facts["fetched_at"] = "2026-07-30T01:00:00.000000Z"
        prev_facts["snapshot_at"] = "2026-07-30T01:00:00.000000Z"
        prev_env = v02.compute_daily_facts_v02(
            prev_facts, {"kind": "producer",
                         "envelope": _producer(trade_date="2026-07-29")})
        curr_env = v02.compute_daily_facts_v02(
            _facts(), {"kind": "producer", "envelope": _producer()})
        import short_term_fact_compare as compare
        import short_term_fact_digest as digest
        import short_term_fact_summary as summary
        cmp = compare.compute_fact_compare(prev_env, curr_env)
        assert cmp["status"] == "normal"
        summ = summary.compute_fact_summary([prev_env, curr_env])
        assert summ["status"] == "normal"
        dig = digest.build_fact_digest(summ)
        assert dig["digest_text"]

    def test_store_reads_v02_after_monotonic_save(self, tmp_path):
        import short_term_fact_store as store
        env = v02.compute_daily_facts_v02(
            _facts(), {"kind": "producer", "envelope": _producer()})
        db = tmp_path / "facts.sqlite3"
        result = store.save_daily_facts_monotonic(env, db_path=db)
        assert result["saved"] is True
        loaded = store.load_daily_facts(T, "final", db_path=db)
        assert loaded["schema_version"] == "short-term-daily-facts-v0.2"
        assert loaded["sections"]["ladder"] is not None

    def test_mixed_v01_v02_history(self, tmp_path):
        import short_term_fact_store as store
        db = tmp_path / "facts.sqlite3"
        v01 = {
            "schema_version": "short-term-daily-facts-v0.1",
            "trade_date": "2026-07-28", "session": "final",
            "is_final": True, "source_ids": ["eastmoney_getTopicZTPool"],
            "fetched_at": "2026-07-28T15:10:00.000000Z",
            "snapshot_at": "2026-07-28T15:10:00.000000Z",
            "status": "normal", "reason_codes": [], "warnings": [],
            "limitations": ["fixture"],
            "source_schema_version": "short-term-limit-up-final-snapshot-v0.1",
            "source_status": "normal", "source_reason_codes": [],
            "sections": {
                "facts": {"schema_version": "short-term-market-facts-v0.1",
                          "status": "normal",
                          "facts": {"advance_count": 100}},
                "ladder": {"schema_version": "short-term-limit-up-ladder-v0.1",
                           "status": "normal",
                           "metrics": {"max_boards": 6, "lianban_count": 3,
                                       "ladder": []}},
                "gap": {"schema_version": "short-term-ladder-gap-v0.1",
                        "status": "normal",
                        "metrics": {"gap_level_count": 0,
                                    "gap_segment_count": 0,
                                    "largest_gap_width": 0,
                                    "first_gap_board": None,
                                    "is_continuous": True}},
            },
        }
        store.save_daily_facts(v01, db_path=db)
        env = v02.compute_daily_facts_v02(
            _facts(), {"kind": "producer", "envelope": _producer()})
        result = store.save_daily_facts_monotonic(env, db_path=db)
        assert result["saved"] is True
        dates = store.list_trade_dates(db_path=db)
        assert dates == ["2026-07-28", "2026-07-30"]
