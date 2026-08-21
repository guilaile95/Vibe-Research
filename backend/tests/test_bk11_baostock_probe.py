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
    """实现 harness 所需协议的最小 fake。

    query_all_stock 返回 ``(rows, pages)``；每次 query_history_k_day 调用
    计入 ``calls``，用于断言 request_count == 真实网络调用次数。
    """

    def __init__(
        self,
        *,
        login_ok: bool = True,
        all_stock_rows=None,
        all_pages: int = 1,
        k_map=None,
        k_error=None,
        all_error=None,
    ):
        self.login_ok = login_ok
        self.all_stock_rows = all_stock_rows if all_stock_rows is not None else []
        self.all_pages = all_pages
        self.k_map = k_map if k_map is not None else {}
        self.k_error = k_error
        self.all_error = all_error
        self.calls: list = []
        self.query_k_calls: int = 0

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

    def query_all_stock(self, day: str):
        self.calls.append(("query_all_stock", day))
        if self.all_error is not None:
            raise self.all_error
        return self.all_stock_rows, self.all_pages

    def query_history_k_day(self, code: str, day: str, fields: str) -> list:
        self.calls.append(("query_k", code, day))
        self.query_k_calls += 1
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


def _probe_kwargs(**overrides):
    kwargs = dict(
        max_requests=50,
        consecutive_fail_stop=10,
        early_window=50,
        early_fail_rate=0.05,
        fail_rate_stop=0.05,
        fail_count_stop=None,
        wall_clock_limit=60.0,
        sleep=lambda _: None,
    )
    kwargs.update(overrides)
    return kwargs


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
    targets, excluded, dup, conflict = probe.parse_all_stock_rows(raw)
    assert [t["code"] for t in targets] == ["000001", "300750", "600000", "688001"]
    assert excluded == 6
    assert dup == 0
    assert conflict == 0


def test_parse_all_stock_rows_trade_status_contract():
    raw = [
        ["sh.600000", "1", "A"],
        ["sz.000001", "0", "B"],
        ["sz.300750", "x", "C"],
    ]
    targets, _, dup, conflict = probe.parse_all_stock_rows(raw)
    by_code = {t["code"]: t for t in targets}
    assert by_code["600000"]["trade_status"] == "1"
    assert by_code["000001"]["trade_status"] == "0"
    # 未知状态保留原值供审计（不猜测语义）
    assert by_code["300750"]["trade_status"] == "x"
    assert dup == 0
    assert conflict == 0


def test_parse_all_stock_rows_duplicate_codes():
    raw = [
        ["sh.600000", "1", "A"],
        ["sh.600000", "1", "A"],
        ["sh.600000", "1", "A"],
    ]
    targets, _, dup, conflict = probe.parse_all_stock_rows(raw)
    assert len(targets) == 1
    assert dup == 2
    assert conflict == 0


def test_parse_all_stock_rows_conflicting_status():
    raw = [
        ["sh.600000", "1", "A"],
        ["sh.600000", "0", "A"],
    ]
    targets, _, dup, conflict = probe.parse_all_stock_rows(raw)
    assert len(targets) == 1
    assert dup == 1
    assert conflict == 1


def test_build_stratified_sample_deterministic():
    targets, _, _, _ = probe.parse_all_stock_rows(_sample_universe(40))
    a = probe.build_stratified_sample(targets, 10, seed=3)
    b = probe.build_stratified_sample(targets, 10, seed=3)
    assert [e["code"] for e in a] == [e["code"] for e in b]
    assert len(a) == 10


# ---------------------------------------------------------------------------
# 单股单日合同
# ---------------------------------------------------------------------------

def _probe(client, code, status="1", **kwargs):
    budget = kwargs.pop("budget", [10])
    calls = kwargs.pop("calls", [0])
    return probe.probe_stock(
        client,
        {"code": code, "trade_status": status},
        DAY,
        budget=budget,
        calls=calls,
        **kwargs,
    )


def test_active_stock_single_day_row():
    client = _make_client(k_map={"sh.600000": [_stock_row("sh.600000")]})
    result = _probe(client, "600000")
    assert result["ok"] is True
    assert result["violations"] == []
    assert len(result["rows"]) == 1


def test_suspended_stock_empty_response():
    client = _make_client(k_map={"sz.000001": []})
    result = _probe(client, "000001", status="0")
    assert result["ok"] is True
    assert result["rows"] == []
    assert result["violations"] == []


def test_suspended_stock_tradestatus_zero_row():
    client = _make_client(
        k_map={"sz.000001": [_stock_row("sz.000001", status="0", pct="-")]}
    )
    result = _probe(client, "000001", status="0")
    assert result["ok"] is True
    assert result["violations"] == []
    assert result["rows"][0]["tradestatus"] == "0"


def test_universe_zero_kline_one_status_conflict():
    # universe=0（停牌），K线=1（交易）→ trade_status_mismatch
    client = _make_client(
        k_map={"sz.000001": [_stock_row("sz.000001", status="1")]}
    )
    result = _probe(client, "000001", status="0")
    assert "trade_status_mismatch" in result["violations"]


def test_universe_one_kline_zero_status_conflict():
    # universe=1（交易），K线=0（停牌）→ trade_status_mismatch
    client = _make_client(
        k_map={"sh.600000": [_stock_row("sh.600000", status="0")]}
    )
    result = _probe(client, "600000", status="1")
    assert "trade_status_mismatch" in result["violations"]


def test_date_mismatch_violation():
    row = _stock_row("sh.600000", day="2026-08-04")
    client = _make_client(k_map={"sh.600000": [row]})
    result = _probe(client, "600000")
    assert "date_mismatch" in result["violations"]


def test_code_mismatch_violation():
    row = _stock_row("sh.600001")
    client = _make_client(k_map={"sh.600000": [row]})
    result = _probe(client, "600000")
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
    result = _probe(client, "600000")
    assert "duplicate_row" in result["violations"]


def test_invalid_pct_chg_violation():
    row = _stock_row("sh.600000", pct="abc")
    client = _make_client(k_map={"sh.600000": [row]})
    result = _probe(client, "600000")
    assert "invalid_pct_chg" in result["violations"]


def test_invalid_ohlc_violation():
    row = _stock_row("sh.600000", ohlc="nan")
    client = _make_client(k_map={"sh.600000": [row]})
    result = _probe(client, "600000")
    assert "invalid_ohlc" in result["violations"]


def test_invalid_tradestatus_violation():
    row = _stock_row("sh.600000", status="9")
    client = _make_client(k_map={"sh.600000": [row]})
    result = _probe(client, "600000")
    assert "invalid_tradestatus" in result["violations"]


# ---------------------------------------------------------------------------
# 请求错误 / 重试 / 熔断 / 预算
# ---------------------------------------------------------------------------

class BoomError(RuntimeError):
    pass


def test_request_error_fail_closed():
    client = _make_client(k_error=BoomError("boom"))
    result = _probe(client, "600000")
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
    result = _probe(client, "600000")
    assert result["ok"] is True
    assert result["retries"] == 1


def test_bounded_retry_stops_after_limit():
    class AlwaysFail(FakeClient):
        def query_history_k_day(self, code, day, fields):
            raise BoomError("boom")

    client = AlwaysFail(all_stock_rows=[], k_map={})
    result = _probe(client, "600000")
    assert result["ok"] is False
    assert result["retries"] == 1  # 最多 1 次重试（共 2 次尝试）


def test_consecutive_failure_circuit():
    class AlwaysFail(FakeClient):
        def query_history_k_day(self, code, day, fields):
            raise BoomError("boom")

    client = AlwaysFail(all_stock_rows=[], k_map={})
    targets = [{"code": f"{600000 + i:06d}", "trade_status": "1"} for i in range(20)]
    stats = probe.run_probe(client, targets, DAY, **_probe_kwargs())
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
    stats = probe.run_probe(client, targets, DAY, **_probe_kwargs())
    assert stats["circuit_open"] == "early_failure_rate"


def test_request_budget_hard_cap():
    client = _make_client()
    targets = [{"code": f"{600000 + i:06d}", "trade_status": "1"} for i in range(10)]
    stats = probe.run_probe(
        client,
        targets,
        DAY,
        **_probe_kwargs(max_requests=3),
    )
    assert stats["budget_exhausted"] is True
    assert stats["request_count"] == 3
    assert stats["primary_request_count"] == 3
    assert stats["counts"]["success"] == 3


def test_request_count_equals_fake_actual_calls():
    client = _make_client(
        k_map={
            "sh.600000": [_stock_row("sh.600000")],
            "sh.600001": [_stock_row("sh.600001")],
        }
    )
    targets = [
        {"code": "600000", "trade_status": "1"},
        {"code": "600001", "trade_status": "1"},
    ]
    stats = probe.run_probe(client, targets, DAY, **_probe_kwargs())
    assert stats["request_count"] == client.query_k_calls == 2


def test_retry_requests_counted():
    class FlakyOnce(FakeClient):
        def __init__(self):
            super().__init__(all_stock_rows=[], k_map={})
            self.failed = False

        def query_history_k_day(self, code, day, fields):
            self.calls.append(("query_k", code, day))
            if not self.failed:
                self.failed = True
                raise BoomError("boom")
            return [_stock_row(code)]

    client = FlakyOnce()
    targets = [{"code": "600000", "trade_status": "1"}]
    stats = probe.run_probe(client, targets, DAY, **_probe_kwargs())
    assert stats["primary_request_count"] == 1
    assert stats["retry_request_count"] == 1
    real_calls = sum(1 for c in client.calls if isinstance(c, tuple) and c[0] == "query_k")
    assert stats["request_count"] == real_calls == 2


def test_input_not_modified():
    client = _make_client()
    targets = [
        {"code": "600000", "trade_status": "1"},
        {"code": "000001", "trade_status": "1"},
    ]
    before = copy.deepcopy(targets)
    probe.run_probe(client, targets, DAY, **_probe_kwargs())
    assert targets == before


@pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_base_exception_propagates(exc):
    class EvilClient(FakeClient):
        def query_history_k_day(self, code, day, fields):
            raise exc()

    client = EvilClient(all_stock_rows=[], k_map={})
    targets = [{"code": "600000", "trade_status": "1"}]
    with pytest.raises(exc):
        probe.run_probe(client, targets, DAY, **_probe_kwargs())


# ---------------------------------------------------------------------------
# determinism 统一预算
# ---------------------------------------------------------------------------

def _kmap_for(codes):
    return {probe._code_to_baostock(c): [_stock_row(probe._code_to_baostock(c))] for c in codes}


def test_determinism_adds_only_one_recheck_request():
    codes = ["600000", "600001"]
    client = _make_client(k_map=_kmap_for(codes))
    targets = [{"code": c, "trade_status": "1"} for c in codes]
    stats = probe.run_probe(
        client,
        targets,
        DAY,
        **_probe_kwargs(determinism_checks=2),
    )
    # 主探测 2 次 + 复查 2 次 = 4 次真实调用
    assert stats["request_count"] == 4
    assert stats["primary_request_count"] == 2
    assert stats["determinism_request_count"] == 2
    assert client.query_k_calls == 4
    assert stats["determinism"]["all_identical"] is True
    assert stats["determinism"]["incomplete"] is False


def test_determinism_counts_toward_budget():
    codes = [f"{600000 + i:06d}" for i in range(10)]
    client = _make_client(k_map=_kmap_for(codes))
    targets = [{"code": c, "trade_status": "1"} for c in codes]
    stats = probe.run_probe(
        client,
        targets,
        DAY,
        **_probe_kwargs(max_requests=5, determinism_checks=5),
    )
    # 预算 5：主探测 5 次后预算耗尽 → determinism 未执行
    assert stats["request_count"] == 5
    assert stats["determinism_request_count"] == 0
    assert stats["determinism"]["incomplete"] is True
    assert client.query_k_calls == 5


def test_determinism_partial_when_budget_short():
    codes = [f"{600000 + i:06d}" for i in range(5)]
    client = _make_client(k_map=_kmap_for(codes))
    targets = [{"code": c, "trade_status": "1"} for c in codes]
    stats = probe.run_probe(
        client,
        targets,
        DAY,
        **_probe_kwargs(max_requests=7, determinism_checks=5),
    )
    # 预算 7：主探测 5 次后剩 2 → 只做 2 次复查，第 3 次起 incomplete
    assert stats["request_count"] == 7
    assert stats["determinism_request_count"] == 2
    assert stats["determinism"]["incomplete"] is True
    assert client.query_k_calls == 7


def test_determinism_never_bypasses_budget():
    codes = [f"{600000 + i:06d}" for i in range(3)]
    client = _make_client(k_map=_kmap_for(codes))
    targets = [{"code": c, "trade_status": "1"} for c in codes]
    stats = probe.run_probe(
        client,
        targets,
        DAY,
        **_probe_kwargs(max_requests=3, determinism_checks=3),
    )
    assert stats["request_count"] == 3
    assert stats["budget_exhausted"] is True
    assert client.query_k_calls == 3


# ---------------------------------------------------------------------------
# CLI 参数校验（login 前拒绝）
# ---------------------------------------------------------------------------

def test_cli_rejects_retries_above_one():
    rc = probe.main(["--mode", "sample", "--trade-date", DAY, "--retries", "2"])
    assert rc == 2


def test_cli_rejects_sample_size_above_120():
    rc = probe.main(["--mode", "sample", "--trade-date", DAY, "--sample-size", "121"])
    assert rc == 2


def test_cli_rejects_full_max_requests_above_6600():
    rc = probe.main(
        ["--mode", "full", "--trade-date", DAY, "--max-requests", "6601"]
    )
    assert rc == 2


def test_cli_rejects_determinism_checks_above_five():
    rc = probe.main(
        ["--mode", "sample", "--trade-date", DAY, "--determinism-checks", "6"]
    )
    assert rc == 2


def test_cli_rejects_sample_max_requests_above_150():
    rc = probe.main(
        ["--mode", "sample", "--trade-date", DAY, "--max-requests", "151"]
    )
    assert rc == 2


def test_cli_rejects_unknown_fields_flag():
    # --fields 已删除：任何字段参数必须在 login 前被 argparse 拒绝
    with pytest.raises(SystemExit):
        probe.main(
            ["--mode", "sample", "--trade-date", DAY, "--fields", "date,code"]
        )


def test_trade_date_must_be_strict():
    rc = probe.main(["--mode", "sample", "--trade-date", "20260805"])
    assert rc == 2


def test_cli_rejects_negative_sample_size():
    rc = probe.main(["--mode", "sample", "--trade-date", DAY, "--sample-size", "0"])
    assert rc == 2


# ---------------------------------------------------------------------------
# 编排层：login / query_all_stock / 汇总输出
# ---------------------------------------------------------------------------

def test_login_success_orchestration():
    client = _make_client(k_map={"sh.600000": [_stock_row("sh.600000")]})
    summary = probe.run_sample_probe(
        client, DAY, sample_size=1, sleep=lambda _: None
    )
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
    assert not any(isinstance(c, tuple) for c in client.calls)


def test_query_all_stock_error_fails_closed():
    client = FakeClient(all_error=BoomError("boom"), all_stock_rows=[])
    with pytest.raises(probe.ProbeError):
        probe.run_sample_probe(client, DAY, sample_size=5, sleep=lambda _: None)


def test_universe_conflict_fails_closed_sample():
    universe = [
        ["sh.600000", "1", "A"],
        ["sh.600000", "0", "A"],
    ]
    client = FakeClient(all_stock_rows=universe, k_map={})
    summary = probe.run_sample_probe(client, DAY, sample_size=5, sleep=lambda _: None)
    assert summary["universe_stats"]["conflicting_status_count"] == 1
    assert summary["universe_stats"]["contract_failure"] == "conflicting_status"
    assert summary["probe"] is None


def test_universe_conflict_fails_closed_full():
    universe = [
        ["sh.600000", "1", "A"],
        ["sh.600000", "0", "A"],
    ]
    client = FakeClient(all_stock_rows=universe, k_map={})
    summary = probe.run_full_probe(client, DAY, sleep=lambda _: None)
    assert summary["universe_stats"]["contract_failure"] == "conflicting_status"
    assert summary["probe"] is None
    assert summary["breadth"] is None


def test_universe_duplicate_marks_contract_warning():
    universe = [
        ["sh.600000", "1", "A"],
        ["sh.600000", "1", "A"],
    ]
    client = FakeClient(
        all_stock_rows=universe,
        k_map={"sh.600000": [_stock_row("sh.600000")]},
    )
    summary = probe.run_sample_probe(client, DAY, sample_size=1, sleep=lambda _: None)
    assert summary["universe_stats"]["duplicate_code_count"] == 1
    assert summary["universe_stats"]["contract_warning"] == "duplicate_codes"


def test_universe_too_large_fails_closed():
    rows = [[f"sh.{600000 + i:06d}", "1", f"S{i}"] for i in range(6501)]
    client = FakeClient(all_stock_rows=rows, k_map={})
    summary = probe.run_full_probe(client, DAY, sleep=lambda _: None)
    assert summary["universe_stats"]["universe_too_large"] is True
    assert summary["probe"] is None


_BK11_ROW_FIELD_KEYS = frozenset(
    {"date", "code", "open", "high", "low", "close", "preclose", "tradestatus", "pctChg", "isST"}
)
# fixture universe（sh.600000..sh.600009）+ k_map 中的 sz.000001：裸码与前缀码都是真实证券标识
_BK11_REAL_CODE_TOKENS = tuple(
    [f"{600000 + i}" for i in range(10)]
    + [f"sh.{600000 + i}" for i in range(10)]
    + ["sz.000001"]
)
_BK11_FORBIDDEN_STRING_TOKENS = _BK11_REAL_CODE_TOKENS + ("9.4900", "10.1000")
_BK11_FORBIDDEN_CONTAINER_KEYS = frozenset({"rows"})


def _assert_redacted_aggregate_summary(summary) -> None:
    """结构化 redaction 契约检查：汇总只允许 aggregate statistics，不得泄漏行情明细。

    三层检查：
    - 容器键：禁止 ``rows`` 这类 raw 行容器键；
    - 行结构：任何 dict 同时具备 ≥3 个 BaoStock 行字段键即为结构化行泄漏；
    - 字符串：任何 dict 键或字符串值都不得包含真实证券代码或 fixture OHLC 明细。

    int/float 数值不做数字子串扫描：``determinism.details[].elapsed`` 是原始
    monotonic 差值浮点，其十进制表示可能合法地包含任意数字序列（2026-08-21 CI
    attempt-1 实测 ``6.260000020574807e-07`` 触发旧式全文扫描的 ``"600000"``
    误报），而证券代码与行情行在 provider schema 中以字符串/结构化字段存在，
    数值豁免不影响泄漏检出。
    """

    def walk(node):
        if isinstance(node, dict):
            forbidden_keys = set(node) & _BK11_FORBIDDEN_CONTAINER_KEYS
            assert not forbidden_keys, f"raw row container key leaked: {sorted(forbidden_keys)}"
            row_keys = set(node) & _BK11_ROW_FIELD_KEYS
            assert len(row_keys) < 3, f"stock-row-shaped object leaked with keys {sorted(row_keys)}"
            for key, value in node.items():
                assert isinstance(key, str), f"non-string dict key: {key!r}"
                hits = [token for token in _BK11_FORBIDDEN_STRING_TOKENS if token in key]
                assert not hits, f"forbidden token(s) {hits} in dict key {key!r}"
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            hits = [token for token in _BK11_FORBIDDEN_STRING_TOKENS if token in node]
            assert not hits, f"forbidden token(s) {hits} leaked in string {node!r}"

    walk(summary)


def _sample_probe_summary_for_redaction():
    client = _make_client(
        k_map={
            "sh.600000": [_stock_row("sh.600000", pct="1.25", ohlc="9.4900")],
            "sz.000001": [_stock_row("sz.000001", pct="-0.50", ohlc="10.1000")],
        }
    )
    return probe.run_sample_probe(client, DAY, sample_size=2, sleep=lambda _: None)


def test_output_contains_no_full_stock_rows():
    summary = _sample_probe_summary_for_redaction()
    # 汇总中不得出现完整行情行 / 代码列表 / OHLC / pct 明细
    _assert_redacted_aggregate_summary(summary)


def test_redaction_check_rejects_bare_real_code():
    poisoned = copy.deepcopy(_sample_probe_summary_for_redaction())
    poisoned["circuit_open"] = "600000"
    with pytest.raises(AssertionError):
        _assert_redacted_aggregate_summary(poisoned)


def test_redaction_check_rejects_prefixed_real_codes():
    for token in ("sh.600000", "sz.000001"):
        poisoned = copy.deepcopy(_sample_probe_summary_for_redaction())
        poisoned["circuit_open"] = token
        with pytest.raises(AssertionError):
            _assert_redacted_aggregate_summary(poisoned)


def test_redaction_check_rejects_raw_rows_container():
    poisoned = copy.deepcopy(_sample_probe_summary_for_redaction())
    poisoned["probe"]["rows"] = [_stock_row("sh.600000")]
    with pytest.raises(AssertionError):
        _assert_redacted_aggregate_summary(poisoned)


def test_redaction_check_rejects_row_shaped_object_without_container_key():
    poisoned = copy.deepcopy(_sample_probe_summary_for_redaction())
    poisoned["universe_stats"]["leaked"] = {
        "date": DAY,
        "code": "sh.600000",
        "close": "9.49",
    }
    with pytest.raises(AssertionError):
        _assert_redacted_aggregate_summary(poisoned)


def test_redaction_check_tolerates_timing_float_digit_collisions():
    """2026-08-21 CI 事故回归：timing 浮点 repr 含 ``600000`` 不是代码泄漏。

    attempt-1 实测碰撞值 ``6.260000020574807e-07`` 出现在 determinism.details[]
    的原始 elapsed 中；旧式对 json.dumps 全文的裸子串扫描会因此误报，而输出中
    并不存在任何证券标识。结构化检查必须 PASS，末尾断言保留事故机制存档。
    """
    poisoned = copy.deepcopy(_sample_probe_summary_for_redaction())
    poisoned["probe"]["determinism"]["details"][0]["elapsed"] = 6.260000020574807e-07
    poisoned["probe"]["requests_per_second"] = 600000.5
    _assert_redacted_aggregate_summary(poisoned)
    assert "600000" in json.dumps(poisoned, ensure_ascii=False)


def _breadth_summary(universe, k_map, **kwargs):
    client = FakeClient(all_stock_rows=universe, k_map=k_map)
    return probe.run_full_probe(client, DAY, sleep=lambda _: None, **kwargs)


def test_full_probe_breadth_identity():
    universe = [
        ["sh.600000", "1", "A"],
        ["sz.000001", "1", "B"],
        ["sz.300001", "0", "C"],
    ]
    summary = _breadth_summary(
        universe,
        {
            "sh.600000": [_stock_row("sh.600000", pct="1.0")],
            "sz.000001": [_stock_row("sz.000001", pct="-2.0")],
            "sz.300001": [_stock_row("sz.300001", status="0", pct="-")],
        },
    )
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
    summary = _breadth_summary(
        universe,
        {"sh.600000": [_stock_row("sh.600000", pct="-")]},
    )
    assert summary["breadth"]["breadth_identity"] is False
    assert summary["breadth"]["missing_pct_chg"] == 1


def test_full_probe_breadth_identity_accepts_suspended_empty_pct():
    universe = [
        ["sh.600000", "1", "A"],
        ["sz.000001", "0", "B"],
    ]
    summary = _breadth_summary(
        universe,
        {
            "sh.600000": [_stock_row("sh.600000", pct="1.0")],
            "sz.000001": [_stock_row("sz.000001", status="0", pct="-")],
        },
    )
    breadth = summary["breadth"]
    assert breadth["suspended_count"] == 1
    assert breadth["valid_count"] == 1
    assert breadth["breadth_identity"] is True
    assert breadth["missing_pct_chg"] == 0


def test_status_conflict_breaks_identity():
    universe = [
        ["sh.600000", "1", "A"],
        ["sz.000001", "0", "B"],
    ]
    summary = _breadth_summary(
        universe,
        {
            # B 在 universe 中为停牌（0），K线却返回交易（1）→ 状态冲突
            "sh.600000": [_stock_row("sh.600000", pct="1.0")],
            "sz.000001": [_stock_row("sz.000001", status="1", pct="1.0")],
        },
    )
    assert summary["probe"]["counts"]["trade_status_mismatch"] == 1
    assert summary["breadth"]["breadth_identity"] is False


def test_request_failure_breaks_identity():
    universe = [["sh.600000", "1", "A"]]
    client = FakeClient(all_stock_rows=universe, k_map={}, k_error=BoomError("boom"))
    summary = probe.run_full_probe(client, DAY, sleep=lambda _: None)
    assert summary["probe"]["counts"]["failure"] >= 1
    assert summary["breadth"]["breadth_identity"] is False


def test_suspended_request_failure_breaks_identity():
    universe = [
        ["sh.600000", "1", "A"],
        ["sz.000001", "0", "B"],
    ]
    client = FakeClient(
        all_stock_rows=universe,
        k_map={
            "sh.600000": [_stock_row("sh.600000", pct="1.0")],
            "sz.000001": [],  # 停牌股空响应：不得视为停牌证明
        },
    )
    summary = probe.run_full_probe(client, DAY, sleep=lambda _: None)
    assert summary["probe"]["counts"]["empty"] == 1
    assert summary["breadth"]["breadth_identity"] is False


def test_date_violation_breaks_identity():
    universe = [["sh.600000", "1", "A"]]
    summary = _breadth_summary(
        universe,
        {"sh.600000": [_stock_row("sh.600000", day="2026-08-04")]},
    )
    assert summary["probe"]["counts"]["date_mismatch"] == 1
    assert summary["breadth"]["breadth_identity"] is False


def test_circuit_open_breaks_identity():
    class AlwaysFail(FakeClient):
        def query_history_k_day(self, code, day, fields):
            raise BoomError("boom")

    universe = [[f"sh.{600000 + i:06d}", "1", f"S{i}"] for i in range(15)]
    client = AlwaysFail(all_stock_rows=universe, k_map={})
    summary = probe.run_full_probe(client, DAY, sleep=lambda _: None)
    assert summary["probe"]["circuit_open"] == "consecutive_failures"
    assert summary["breadth"]["breadth_identity"] is False


def test_budget_exhaustion_breaks_identity():
    universe = [[f"sh.{600000 + i:06d}", "1", f"S{i}"] for i in range(10)]
    client = FakeClient(all_stock_rows=universe, k_map={})
    summary = probe.run_full_probe(
        client, DAY, max_requests=5, sleep=lambda _: None
    )
    assert summary["probe"]["budget_exhausted"] is True
    assert summary["breadth"]["breadth_identity"] is False


def test_incomplete_universe_coverage_breaks_identity():
    # processed_target_count < universe target_count（提前熔断）→ identity=false
    class FailAfter3(FakeClient):
        def __init__(self):
            super().__init__(all_stock_rows=[], k_map={})
            self.n = 0

        def query_history_k_day(self, code, day, fields):
            self.n += 1
            if self.n > 3:
                raise BoomError("boom")
            return [_stock_row(code)]

    universe = [[f"sh.{600000 + i:06d}", "1", f"S{i}"] for i in range(6)]
    client = FailAfter3()
    client.all_stock_rows = universe
    summary = probe.run_full_probe(client, DAY, sleep=lambda _: None)
    assert summary["breadth"]["breadth_identity"] is False


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


def test_request_accounting_totals():
    client = _make_client(
        all_pages=3,
        k_map={
            "sh.600000": [_stock_row("sh.600000")],
            "sh.600001": [_stock_row("sh.600001")],
        },
    )
    summary = probe.run_sample_probe(
        client, DAY, sample_size=2, determinism_checks=0, sleep=lambda _: None
    )
    acc = summary["request_accounting"]
    assert acc["session_request_count"] == 2
    assert acc["universe_request_count"] == 3
    assert acc["primary_request_count"] == 2
    assert acc["retry_request_count"] == 0
    assert acc["determinism_request_count"] == 0
    assert acc["total_source_request_count"] == 7
    # session 2 + universe 3 页 + 主探测 2 次真实调用
    assert acc["total_source_request_count"] == 2 + 3 + client.query_k_calls
