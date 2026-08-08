"""Issue #48 审查项关闭测试：只使用 fake client，不联网。"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.research import bk11_baostock_probe as probe  # noqa: E402

DAY = "2026-08-05"


class FakeClient:
    def __init__(self, *, universe=None, pages: int = 1, k_rows=None):
        self.universe = universe if universe is not None else [["sh.600000", "1", "A"]]
        self.pages = pages
        self.k_rows = k_rows if k_rows is not None else {
            "sh.600000": [_row("sh.600000")]
        }
        self.calls: list[object] = []

    def login(self) -> dict:
        self.calls.append("login")
        return {"ok": True, "error_code": "0", "error_msg": "success"}

    def logout(self) -> dict:
        self.calls.append("logout")
        return {"ok": True, "error_code": "0"}

    def query_all_stock(self, day: str):
        self.calls.append(("query_all_stock", day))
        return self.universe, self.pages

    def query_history_k_day(self, code: str, day: str, fields: str):
        self.calls.append(("query_k", code, day))
        return self.k_rows.get(code, [])


def _row(code: str, *, status: object = "1", pct: str = "1.0") -> dict:
    return {
        "date": DAY,
        "code": code,
        "open": "10",
        "high": "10",
        "low": "10",
        "close": "10",
        "preclose": "9.9",
        "tradestatus": status,
        "pctChg": pct,
        "isST": "0",
    }


@pytest.mark.parametrize("bad_budget", [0, -1])
def test_explicit_non_positive_sample_budget_rejected_before_login(bad_budget: int):
    client = FakeClient()
    with pytest.raises(probe.ProbeError):
        probe.run_sample_probe(
            client,
            DAY,
            max_requests=bad_budget,
            determinism_checks=0,
            sleep=lambda _: None,
        )
    assert client.calls == []


@pytest.mark.parametrize("bad_budget", [0, -1])
def test_cli_rejects_explicit_non_positive_budget(bad_budget: int):
    rc = probe.main(
        [
            "--mode",
            "sample",
            "--trade-date",
            DAY,
            "--max-requests",
            str(bad_budget),
        ]
    )
    assert rc == 2


def test_probe_budget_does_not_claim_to_cap_session_or_sdk_pagination():
    client = FakeClient(pages=4)
    summary = probe.run_sample_probe(
        client,
        DAY,
        sample_size=1,
        max_requests=1,
        determinism_checks=0,
        sleep=lambda _: None,
    )
    assert summary["probe"]["request_count"] == 1
    assert summary["probe"]["budget_exhausted"] is False
    acc = summary["request_accounting"]
    assert acc["budget_scope"] == "query_history_k_data_plus_primary_retry_determinism_only"
    assert acc["controlled_probe_request_count"] == 1
    assert acc["uncontrolled_source_request_count"] == 6  # login/logout + 4 observed pages
    assert acc["total_source_request_count"] == 7


@pytest.mark.parametrize("bad_status", [None, "", "-", "9", 1])
def test_invalid_universe_trade_status_fails_before_kline_probe(bad_status: object):
    client = FakeClient(universe=[["sh.600000", bad_status, "A"]])
    with pytest.raises(probe.ProbeError, match="invalid universe trade status"):
        probe.run_sample_probe(
            client,
            DAY,
            sample_size=1,
            determinism_checks=0,
            sleep=lambda _: None,
        )
    assert "login" in client.calls
    assert ("query_all_stock", DAY) in client.calls
    assert not any(isinstance(call, tuple) and call[0] == "query_k" for call in client.calls)
    assert client.calls[-1] == "logout"


def test_missing_universe_trade_status_column_fails_before_kline_probe():
    client = FakeClient(universe=[["sh.600000"]])
    with pytest.raises(probe.ProbeError, match="invalid universe trade status"):
        probe.run_sample_probe(
            client,
            DAY,
            sample_size=1,
            determinism_checks=0,
            sleep=lambda _: None,
        )
    assert not any(isinstance(call, tuple) and call[0] == "query_k" for call in client.calls)
    assert client.calls[-1] == "logout"


@pytest.mark.parametrize("bad_status", [None, "", "-", "9", 1])
def test_kline_trade_status_is_strictly_string_zero_or_one(bad_status: object):
    row = _row("sh.600000", status=bad_status)
    violations = probe._row_violations(row, "600000", DAY, "1")
    assert "invalid_tradestatus" in violations


def test_breadth_identity_requires_determinism_consistency():
    universe = [{"code": "600000", "bs_code": "sh.600000", "trade_status": "1"}]
    results = [
        {
            "code": "600000",
            "ok": True,
            "rows": [_row("sh.600000")],
            "violations": [],
        }
    ]
    base_meta = {
        "processed_target_count": 1,
        "failure_count": 0,
        "empty_count": 0,
        "date_mismatch": 0,
        "code_mismatch": 0,
        "duplicate_row": 0,
        "invalid_pct_chg": 0,
        "invalid_tradestatus": 0,
        "trade_status_mismatch": 0,
        "circuit_open": "",
        "budget_exhausted": False,
        "duplicate_code_count": 0,
        "conflicting_status_count": 0,
    }

    bad = dict(base_meta, determinism_consistent=False)
    assert probe.compute_breadth(universe, results, bad)["breadth_identity"] is False

    good = dict(base_meta, determinism_consistent=True)
    assert probe.compute_breadth(universe, results, good)["breadth_identity"] is True


def test_full_probe_breaks_identity_when_determinism_differs():
    class NonDeterministicClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.k_calls = 0

        def query_history_k_day(self, code: str, day: str, fields: str):
            self.calls.append(("query_k", code, day))
            self.k_calls += 1
            pct = "1.0" if self.k_calls == 1 else "2.0"
            return [_row(code, pct=pct)]

    client = NonDeterministicClient()
    summary = probe.run_full_probe(
        client,
        DAY,
        max_requests=2,
        determinism_checks=1,
        sleep=lambda _: None,
    )
    assert summary["probe"]["determinism"]["all_identical"] is False
    assert summary["breadth"]["breadth_identity"] is False
