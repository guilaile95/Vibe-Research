"""BK-11 BaoStock 零成本探测 harness 离线测试（fake client，不联网）。"""
from __future__ import annotations

import copy
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.research import bk11_baostock_probe as probe  # noqa: E402

DAY = "2026-08-05"


class FakeClient:
    """实现 harness 所需协议的最小 fake。"""

    def __init__(
        self,
        *,
        login_ok: bool = True,
        all_stock_rows=None,
        k_map=None,
        k_error=None,
        all_error=None,
    ):
        self.login_ok = login_ok
        self.all_stock_rows = all_stock_rows if all_stock_rows is not None else []
        self.k_map = k_map if k_map is not None else {}
        self.k_error = k_error
        self.all_error = all_error
        self.calls: list = []

    def login(self) -> dict:
        self.calls.append("login")
        return {
            "ok": self.login_ok,
            "error_code": "0" if self.login_ok else "10001005",
            "error_msg": "success" if self.login_ok else "login count limit",
        }

    def logout(self) -> dict:
        self.calls.append("logout")
        return {"ok": True, "error_code": "0"}

    def query_all_stock(self, day: str) -> list:
        self.calls.append(("query_all_stock", day))
        if self.all_error is not None:
            raise self.all_error
        return self.all_stock_rows

    def query_history_k_day(self, code: str, day: str, fields: str) -> list:
        self.calls.append(("query_k", code, day))
        if self.k_error is not None:
            raise self.k_error
        return self.k_map.get(code, [])


def _stock_row(
    code: str,
    *,
    day: str = DAY,
    status: str = "1",
    pct: str = "1.25",
    ohlc: str = "9.4900",
) -> dict:
    return {
        "date": day,
        "code": code,
        "open": ohlc,
        "high": ohlc,
        "low": ohlc,
        "close": ohlc,
        "preclose": ohlc,
        "tradestatus": status,
        "pctChg": pct,
        "isST": "0",
    }


def _sample_universe(n: int = 10) -> list:
    rows = []
    for i in range(n):
        code = f"{600000 + i:06d}"
        rows.append([f"sh.{code}", "1", f"股票{i}"])
    return rows


def _make_client(universe=None, k_map=None, **kwargs):
    return FakeClient(
        all_stock_rows=universe if universe is not None else _sample_universe(),
        k_map=k_map,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 股票池解析与过滤
# ---------------------------------------------------------------------------

def test_is_target_code_boundaries():
    assert probe.is_target_code("sh.600000")
    assert probe.is_target_code("sh.688001")
    assert probe.is_target_code("sz.000001")
    assert probe.is_target_code("sz.300001")
    # 指数与股票数字相同，必须靠交易所前缀区分
    assert not probe.is_target_code("sh.000001")
    assert not probe.is_target_code("sz.399998")
    assert not probe.is_target_code("sh.510300")
    assert not probe.is_target_code("sz.200001")
    assert not probe.is_target_code("bj.430001")
    assert not probe.is_target_code("sh.113001")
    assert not probe.is_target_code("sh.1234567")
    assert not probe.is_target_code("sh.60000a")
    assert not probe.is_target_code("600000")
    assert not probe.is_target_code(600000)


def test_parse_all_stock_rows_filters_universe():
    raw = [
        ["sh.600000", "1", "浦发银行"],
        ["sz.000001", "1", "平安银行"],
        ["sz.300750", "0", "宁德时代"],
        ["sh.688001", "1", "华兴源创"],
        ["sh.000001", "1", "上证综合指数"],  # 指数排除
        ["sz.399998", "1", "中证煤炭指数"],  # 指数排除
        ["sh.510300", "1", "300ETF"],  # ETF 排除
        ["sz.200001", "1", "深B"],  # B 股排除
        ["bj.430001", "1", "北交所"],  # 北交所排除
        ["sh.113001", "1", "可转债"],  # 排除
    ]
    targets, excluded = probe.parse_all_stock_rows(raw)
    assert [t["code"] for t in targets] == ["000001", "300750", "600000", "688001"]
    assert excluded == 6


def test_parse_all_stock_rows_trade_status_contract():
    raw = [
        ["sh.600000", "1", "A"],
        ["sz.000001", "0", "B"],
        ["sz.300750", "x", "C"],
    ]
    targets, _ = probe.parse_all_stock_rows(raw)
    by_code = {t["code"]: t for t in targets}
    assert by_code["600000"]["trade_status"] == "1"
    assert by_code["000001"]["trade_status"] == "0"
    # 未知状态保留原值供审计（不猜测语义）
    assert by_code["300750"]["trade_status"] == "x"


def test_dedupe_codes_keeps_first():
    entries = [
        {"code": "600000", "trade_status": "1"},
        {"code": "600000", "trade_status": "0"},
        {"code": "000001", "trade_status": "0"},
    ]
    out = probe.dedupe_codes(entries)
    assert len(out) == 2
    assert out[0]["trade_status"] == "1"


def test_build_stratified_sample_deterministic():
    targets, _ = probe.parse_all_stock_rows(_sample_universe(40))
    a = probe.build_stratified_sample(targets, 10, seed=3)
    b = probe.build_stratified_sample(targets, 10, seed=3)
    assert [e["code"] for e in a] == [e["code"] for e in b]
    assert len(a) == 10


# ---------------------------------------------------------------------------
# 单股单日合同
# ---------------------------------------------------------------------------

def test_active_stock_single_day_row():
    client = _make_client(
        k_map={"sh.600000": [_stock_row("sh.600000")]}
    )
    result = probe.probe_stock(client, "600000", DAY)
    assert result["ok"] is True
    assert result["violations"] == []
    assert len(result["rows"]) == 1


def test_suspended_stock_empty_response():
    client = _make_client(k_map={"sz.000001": []})
    result = probe.probe_stock(client, "000001", DAY)
    assert result["ok"] is True
    assert result["rows"] == []
    assert result["violations"] == []


def test_suspended_stock_tradestatus_zero_row():
    client = _make_client(
        k_map={"sz.000001": [_stock_row("sz.000001", status="0", pct="-")]}
    )
    result = probe.probe_stock(client, "000001", DAY)
    assert result["ok"] is True
    assert result["violations"] == []
    assert result["rows"][0]["tradestatus"] == "0"


def test_date_mismatch_violation():
    row = _stock_row("sh.600000", day="2026-08-04")
    client = _make_client(k_map={"sh.600000": [row]})
    result = probe.probe_stock(client, "600000", DAY)
    assert "date_mismatch" in result["violations"]


def test_code_mismatch_violation():
    row = _stock_row("sh.600001")
    client = _make_client(k_map={"sh.600000": [row]})
    result = probe.probe_stock(client, "600000", DAY)
    assert "code_mismatch" in result["violations"]


def test_duplicate_date_violation():
    client = _make_client(
        k_map={
            "sh.600000": [
                _stock_row("sh.600000"),
                _stock_row("sh.600000"),
            ]
        }
    )
    result = probe.probe_stock(client, "600000", DAY)
    assert "duplicate_row" in result["violations"]


def test_invalid_pct_chg_violation():
    row = _stock_row("sh.600000", pct="abc")
    client = _make_client(k_map={"sh.600000": [row]})
    result = probe.probe_stock(client, "600000", DAY)
    assert "invalid_pct_chg" in result["violations"]


def test_invalid_ohlc_violation():
    row = _stock_row("sh.600000", ohlc="nan")
    client = _make_client(k_map={"sh.600000": [row]})
    result = probe.probe_stock(client, "600000", DAY)
    assert "invalid_ohlc" in result["violations"]


def test_invalid_tradestatus_violation():
    row = _stock_row("sh.600000", status="9")
    client = _make_client(k_map={"sh.600000": [row]})
    result = probe.probe_stock(client, "600000", DAY)
    assert "invalid_tradestatus" in result["violations"]


# ---------------------------------------------------------------------------
# 请求错误 / 重试 / 熔断 / 预算
# ---------------------------------------------------------------------------

class BoomError(RuntimeError):
    pass


def test_request_error_fail_closed():
    client = _make_client(k_error=BoomError("boom"))
    result = probe.probe_stock(client, "600000", DAY)
    assert result["ok"] is False
    assert result["error"] == "request_error"
    assert "request_error" in result["violations"]


def test_bounded_retry_success_after_one_failure():
    class FlakyClient(FakeClient):
        def __init__(self):
            super().__init__(all_stock_rows=[], k_map={})
            self.fail_first = True

        def query_history_k_day(self, code, day, fields):
            if self.fail_first:
                self.fail_first = False
                raise BoomError("boom")
            return [_stock_row(code)]

    client = FlakyClient()
    result = probe.probe_stock(client, "600000", DAY)
    assert result["ok"] is True
    assert result["retries"] == 1


def test_bounded_retry_stops_after_limit():
    class AlwaysFail(FakeClient):
        def query_history_k_day(self, code, day, fields):
            raise BoomError("boom")

    client = AlwaysFail(all_stock_rows=[], k_map={})
    result = probe.probe_stock(client, "600000", DAY)
    assert result["ok"] is False
    assert result["retries"] == 1  # 最多 1 次重试（共 2 次尝试）


def test_consecutive_failure_circuit():
    class AlwaysFail(FakeClient):
        def query_history_k_day(self, code, day, fields):
            raise BoomError("boom")

    client = AlwaysFail(all_stock_rows=[], k_map={})
    targets = [{"code": f"{600000 + i:06d}", "trade_status": "1"} for i in range(20)]
    stats = probe.run_probe(
        client,
        targets,
        DAY,
        max_requests=50,
        consecutive_fail_stop=10,
        early_window=50,
        early_fail_rate=0.05,
        fail_rate_stop=0.05,
        fail_count_stop=None,
        wall_clock_limit=60.0,
        sleep=lambda _: None,
    )
    assert stats["circuit_open"] == "consecutive_failures"
    assert stats["counts"]["failure"] == 10


def test_early_failure_rate_circuit():
    class HalfFail(FakeClient):
        def __init__(self):
            super().__init__(all_stock_rows=[], k_map={})
            self.n = 0

        def query_history_k_day(self, code, day, fields):
            self.n += 1
            if self.n % 2 == 0:
                raise BoomError("boom")
            return [_stock_row(code)]

    client = HalfFail()
    targets = [{"code": f"{600000 + i:06d}", "trade_status": "1"} for i in range(60)]
    stats = probe.run_probe(
        client,
        targets,
        DAY,
        max_requests=150,
        consecutive_fail_stop=10,
        early_window=50,
        early_fail_rate=0.05,
        fail_rate_stop=0.05,
        fail_count_stop=None,
        wall_clock_limit=60.0,
        sleep=lambda _: None,
    )
    assert stats["circuit_open"] == "early_failure_rate"


def test_request_budget_hard_cap():
    client = _make_client()
    targets = [{"code": f"{600000 + i:06d}", "trade_status": "1"} for i in range(10)]
    stats = probe.run_probe(
        client,
        targets,
        DAY,
        max_requests=3,
        consecutive_fail_stop=10,
        early_window=50,
        early_fail_rate=0.05,
        fail_rate_stop=0.05,
        fail_count_stop=None,
        wall_clock_limit=60.0,
        sleep=lambda _: None,
    )
    assert stats["budget_exhausted"] is True
    assert stats["request_count"] == 3
    assert stats["counts"]["success"] == 3


def test_input_not_modified():
    client = _make_client()
    targets = [
        {"code": "600000", "trade_status": "1"},
        {"code": "000001", "trade_status": "1"},
    ]
    before = copy.deepcopy(targets)
    probe.run_probe(
        client,
        targets,
        DAY,
        max_requests=10,
        consecutive_fail_stop=10,
        early_window=50,
        early_fail_rate=0.05,
        fail_rate_stop=0.05,
        fail_count_stop=None,
        wall_clock_limit=60.0,
        sleep=lambda _: None,
    )
    assert targets == before


@pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_base_exception_propagates(exc):
    class EvilClient(FakeClient):
        def query_history_k_day(self, code, day, fields):
            raise exc()

    client = EvilClient(all_stock_rows=[], k_map={})
    targets = [{"code": "600000", "trade_status": "1"}]
    with pytest.raises(exc):
        probe.run_probe(
            client,
            targets,
            DAY,
            max_requests=10,
            consecutive_fail_stop=10,
            early_window=50,
            early_fail_rate=0.05,
            fail_rate_stop=0.05,
            fail_count_stop=None,
            wall_clock_limit=60.0,
            sleep=lambda _: None,
        )


# ---------------------------------------------------------------------------
# 编排层：login / query_all_stock / 汇总输出
# ---------------------------------------------------------------------------

def test_login_success_orchestration():
    client = _make_client(
        k_map={"sh.600000": [_stock_row("sh.600000")]}
    )
    summary = probe.run_sample_probe(client, DAY, sample_size=1, sleep=lambda _: None)
    assert summary["login"]["ok"] is True
    assert summary["probe"] is not None
    assert summary["universe_stats"]["target_count"] == 10
    assert client.calls[0] == "login"
    assert client.calls[-1] == "logout"


def test_login_failure_stops_probe():
    client = FakeClient(login_ok=False)
    summary = probe.run_sample_probe(client, DAY, sample_size=5, sleep=lambda _: None)
    assert summary["login"]["ok"] is False
    assert summary["probe"] is None
    assert not any(c == "query_all_stock" for c in client.calls if isinstance(c, tuple))


def test_query_all_stock_error_fails_closed():
    client = FakeClient(all_error=BoomError("boom"), all_stock_rows=[])
    with pytest.raises(probe.ProbeError):
        probe.run_sample_probe(client, DAY, sample_size=5, sleep=lambda _: None)


def test_output_contains_no_full_stock_rows():
    client = _make_client(
        k_map={
            "sh.600000": [_stock_row("sh.600000", pct="1.25", ohlc="9.4900")],
            "sz.000001": [_stock_row("sz.000001", pct="-0.50", ohlc="10.1000")],
        }
    )
    summary = probe.run_sample_probe(
        client, DAY, sample_size=2, sleep=lambda _: None
    )
    text = json.dumps(summary, ensure_ascii=False)
    # 汇总中不得出现完整行情行 / 代码列表 / OHLC / pct 明细
    assert '"rows"' not in text
    assert "9.4900" not in text
    assert "10.1000" not in text
    assert "1.25" not in text
    assert "600000" not in text


def test_full_probe_breadth_identity():
    universe = [
        ["sh.600000", "1", "A"],
        ["sz.000001", "1", "B"],
        ["sz.300001", "0", "C"],
    ]
    client = FakeClient(
        all_stock_rows=universe,
        k_map={
            "sh.600000": [_stock_row("sh.600000", pct="1.0")],
            "sz.000001": [_stock_row("sz.000001", pct="-2.0")],
            "sz.300001": [],
        },
    )
    summary = probe.run_full_probe(client, DAY, sleep=lambda _: None)
    breadth = summary["breadth"]
    assert breadth["eligible_count"] == 3
    assert breadth["suspended_count"] == 1
    assert breadth["advance_count"] == 1
    assert breadth["decline_count"] == 1
    assert breadth["flat_count"] == 0
    assert breadth["valid_count"] == 2
    assert breadth["breadth_identity"] is True


def test_full_probe_breadth_identity_fails_on_missing_pct():
    universe = [["sh.600000", "1", "A"]]
    client = FakeClient(
        all_stock_rows=universe,
        k_map={"sh.600000": [_stock_row("sh.600000", pct="-")]},
    )
    summary = probe.run_full_probe(client, DAY, sleep=lambda _: None)
    assert summary["breadth"]["breadth_identity"] is False
    assert summary["breadth"]["missing_pct_chg"] == 1


def test_full_probe_breadth_identity_accepts_suspended_empty_pct():
    universe = [
        ["sh.600000", "1", "A"],
        ["sz.000001", "0", "B"],
    ]
    client = FakeClient(
        all_stock_rows=universe,
        k_map={
            "sh.600000": [_stock_row("sh.600000", pct="1.0")],
            "sz.000001": [_stock_row("sz.000001", status="0", pct="-")],
        },
    )
    summary = probe.run_full_probe(client, DAY, sleep=lambda _: None)
    breadth = summary["breadth"]
    assert breadth["suspended_count"] == 1
    assert breadth["valid_count"] == 1
    assert breadth["breadth_identity"] is True
    assert breadth["missing_pct_chg"] == 0


def test_cross_check_suspension_math():
    result = probe.cross_check_suspension(
        ["600000", "000001", "300001"],
        ["000001", "300001", "688001"],
    )
    assert result["baostock_suspended_count"] == 3
    assert result["eastmoney_suspended_count"] == 3
    assert result["intersection_count"] == 2
    assert result["only_baostock_count"] == 1
    assert result["only_eastmoney_count"] == 1
    assert result["jaccard"] == pytest.approx(2 / 4)


def test_cross_probe_orchestration(tmp_path):
    em_file = tmp_path / "em_suspended.txt"
    em_file.write_text("000001\n300001\n", encoding="utf-8")
    universe = [
        ["sh.600000", "1", "A"],
        ["sz.000001", "0", "B"],
        ["sz.300001", "0", "C"],
    ]
    client = FakeClient(all_stock_rows=universe, k_map={})
    summary = probe.run_cross_probe(client, DAY, str(em_file))
    cross = summary["suspension_cross"]
    assert cross["baostock_suspended_count"] == 2
    assert cross["eastmoney_suspended_count"] == 2
    assert cross["intersection_count"] == 2
    assert cross["jaccard"] == 1.0


def test_trade_date_must_be_strict():
    with pytest.raises(probe.ProbeError):
        probe.main(["--mode", "sample", "--trade-date", "20260805"])
