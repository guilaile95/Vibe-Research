"""Alert Rule 并发可靠性专项压力测试（P0-F1）。

全部确定性 / 无网络。Harness 契约（F）：
- DB path 在每轮主线程一次性固定（os.environ 只由主线程设置）；
- worker 线程**只调用 production API**（create_alert_rule），
  不做 importlib.reload、不修改 process-global env；
- 并发语义：fresh-diff 2 success；same-id 1 success + 1 duplicate；
  多 writer 全部 success；真实 corruption 立即 fail-closed。

覆盖：A/B/C/D 压力矩阵、E 损坏 fail-closed、H4 竞态回归测试
（owner 初始化窗口内进入的 waiter 不得被误判为 corruption）。
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import alert_rule_store as store
import alert_rules as ar

_DB_ENV = "VIBE_RESEARCH_ALERT_RULE_DB"
T0 = datetime(2026, 8, 1, 3, 4, 5, 123456, tzinfo=timezone.utc)


def rule(*, rule_id: str, code: str = "000001") -> ar.AlertRule:
    return ar.AlertRule(
        rule_id=rule_id,
        code=code,
        enabled=True,
        condition=ar.TechnicalTriggerCondition(
            kind="technical_trigger", trigger="sma_golden_cross"
        ),
    )


@pytest.fixture
def db_path(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "alert_rules.sqlite3"
    monkeypatch.setenv(_DB_ENV, str(path))
    monkeypatch.delenv("VR_DATA_DIR", raising=False)
    return path


def _run_threads(workers: list[callable]) -> list[str]:
    """启动并 join 全部 worker 线程；返回各 worker 的结果列表（有序）。"""
    results: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(len(workers), timeout=20)

    def wrapped(fn):
        barrier.wait()
        try:
            fn()
            with lock:
                results.append("ok")
        except store.AlertRuleAlreadyExistsError:
            with lock:
                results.append("duplicate")
        except Exception as exc:  # noqa: BLE001
            with lock:
                results.append(f"error:{type(exc).__name__}:{exc}")

    threads = [threading.Thread(target=wrapped, args=(fn,)) for fn in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def _count_all() -> int:
    """分页计数（list_alert_rules 单页上限 200，压力测试行数可超）。"""
    total = 0
    offset = 0
    while True:
        page = store.list_alert_rules(limit=200, offset=offset)
        total += len(page)
        if len(page) < 200:
            return total
        offset += 200


def _fresh_db_round(base: Path, round_idx: int, rule_ids: list[str]) -> tuple[list[str], Path]:
    """fresh DB：每轮独立新库；env 由主线程固定；workers 只调 production API。"""
    round_path = base / f"round_{round_idx}" / "alert_rules.sqlite3"
    round_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ[_DB_ENV] = str(round_path)
    results = _run_threads(
        [lambda rid=rid: store.create_alert_rule(rule(rule_id=rid), now=T0) for rid in rule_ids]
    )
    return results, round_path


# ---------------------------------------------------------------------------
# A. Fresh DB · 2 threads · different IDs · 100 rounds → 2 success, 2 rows
# ---------------------------------------------------------------------------
def test_fresh_db_different_ids_100_rounds(db_path, tmp_path):
    base = tmp_path / "stress_a"
    for i in range(100):
        results, round_path = _fresh_db_round(base, i, [f"a.{i}", f"b.{i}"])
        assert results == ["ok", "ok"], f"round {i}: {results}"
        os.environ[_DB_ENV] = str(round_path)
        row_count = _count_all()
        all_records = store.list_alert_rules(limit=200)
        assert {r.rule.rule_id for r in all_records} == {f"a.{i}", f"b.{i}"}, f"round {i} rows"


# ---------------------------------------------------------------------------
# B. Fresh DB · 2 threads · same ID · 50 rounds → 1 success + 1 duplicate, 1 row
# ---------------------------------------------------------------------------
def test_fresh_db_same_id_50_rounds(db_path, tmp_path):
    base = tmp_path / "stress_b"
    for i in range(50):
        results, round_path = _fresh_db_round(base, i, ["same.id", "same.id"])
        assert sorted(results) == ["duplicate", "ok"], f"round {i}: {results}"
        os.environ[_DB_ENV] = str(round_path)
        row_count = _count_all()
        one = store.list_alert_rules(limit=200)
        assert len(one) == 1 and one[0].rule.rule_id == "same.id", f"round {i}"


# ---------------------------------------------------------------------------
# C. Already-initialized DB · 2 threads · different IDs · 100 rounds → 2 success
# ---------------------------------------------------------------------------
def test_initialized_db_different_ids_100_rounds(db_path, tmp_path):
    base = tmp_path / "stress_c"
    db = base / "alert_rules.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    os.environ[_DB_ENV] = str(db)
    store.create_alert_rule(rule(rule_id="seed"), now=T0)  # initialize once
    for i in range(100):
        results = _run_threads(
            [lambda rid=f"c.{i}.a": store.create_alert_rule(rule(rule_id=rid), now=T0),
             lambda rid=f"c.{i}.b": store.create_alert_rule(rule(rule_id=rid), now=T0)]
        )
        assert results == ["ok", "ok"], f"round {i}: {results}"
    row_count = _count_all()
    assert row_count == 1 + 200  # seed + 100*2


# ---------------------------------------------------------------------------
# D. 8 concurrent writers · different IDs · 50 rounds → all success, exact count
# ---------------------------------------------------------------------------
def test_multi_writer_stress(db_path, tmp_path):
    base = tmp_path / "stress_d"
    db = base / "alert_rules.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    os.environ[_DB_ENV] = str(db)
    store.create_alert_rule(rule(rule_id="seed"), now=T0)
    writers = 8
    for i in range(50):
        results = _run_threads(
            [lambda w=w: store.create_alert_rule(rule(rule_id=f"mw.{i}.{w}"), now=T0)
             for w in range(writers)]
        )
        assert results == ["ok"] * writers, f"round {i}: {results}"
    row_count = _count_all()
    assert row_count == 1 + writers * 50


# ---------------------------------------------------------------------------
# E. Real corruption → immediate fail-closed（并发下也不被 retry 掩盖）
# ---------------------------------------------------------------------------
def test_corruption_fail_closed_under_concurrency(db_path, tmp_path):
    base = tmp_path / "stress_e"
    db = base / "alert_rules.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    os.environ[_DB_ENV] = str(db)
    store.create_alert_rule(rule(rule_id="seed"), now=T0)
    # 真实损坏：删除 alert_rules 表
    with sqlite3.connect(str(db)) as raw:
        raw.execute("DROP TABLE alert_rules")
    results = _run_threads(
        [lambda: store.create_alert_rule(rule(rule_id="e.1"), now=T0),
         lambda: store.create_alert_rule(rule(rule_id="e.2"), now=T0)]
    )
    for r in results:
        assert r.startswith("error:AlertRuleStoreCorruptedError"), results
    # 后续读写同样 fail-closed
    with pytest.raises(store.AlertRuleStoreCorruptedError):
        store.list_alert_rules()


# ---------------------------------------------------------------------------
# F. Harness regression：workers 不触碰 process-global state
# ---------------------------------------------------------------------------
def test_workers_do_not_mutate_global_env_or_reload(db_path, tmp_path):
    """worker 只调 production API；env 由主线程固定，reload 不在线程内发生。"""
    import importlib

    base = tmp_path / "stress_f"
    db = base / "alert_rules.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    os.environ[_DB_ENV] = str(db)
    env_before = os.environ[_DB_ENV]

    captured: list[str] = []

    def spy_reload(module):
        captured.append(f"reload:{threading.current_thread().name}")
        return importlib.reload(module)

    original_reload = importlib.reload
    importlib.reload = spy_reload  # noqa: A001 — test-only spy（主线程验证后恢复）
    try:
        results = _run_threads(
            [lambda: store.create_alert_rule(rule(rule_id="f.1"), now=T0),
             lambda: store.create_alert_rule(rule(rule_id="f.2"), now=T0)]
        )
    finally:
        importlib.reload = original_reload
    assert results == ["ok", "ok"]
    assert captured == []  # 线程内没有任何 reload
    assert os.environ[_DB_ENV] == env_before  # env 未被线程改写


# ---------------------------------------------------------------------------
# H4 regression：owner 初始化窗口内进入的 waiter 不得误判 corruption
# ---------------------------------------------------------------------------
def test_waiter_entering_during_owner_initialization_succeeds(db_path, monkeypatch):
    """确定性复现 H4 时序：owner 在 O_EXCL 之后、初始化完成之前停留，
    waiter 此时进入（existed_at_start=True + 空表）→ 必须等待而非 CorruptedError。"""
    monkeypatch.setattr(store, "_OPEN_WAIT_TOTAL_SECONDS", 10.0)
    real_acquire = store._acquire_initialization_ownership
    started = threading.Event()
    release = threading.Event()

    def slow_owner_acquire(path):
        owned = real_acquire(path)
        if owned:
            started.set()
            assert release.wait(timeout=10), "owner window release timed out"
        return owned

    monkeypatch.setattr(store, "_acquire_initialization_ownership", slow_owner_acquire)

    results: list[str] = []

    def owner():
        try:
            store.create_alert_rule(rule(rule_id="owner.a"), now=T0)
            results.append("ok")
        except Exception as exc:  # noqa: BLE001
            results.append(f"error:{type(exc).__name__}")

    def waiter():
        started.wait(timeout=10)
        try:
            store.create_alert_rule(rule(rule_id="waiter.b"), now=T0)
            results.append("ok")
        except Exception as exc:  # noqa: BLE001
            results.append(f"error:{type(exc).__name__}")

    t_owner = threading.Thread(target=owner)
    t_waiter = threading.Thread(target=waiter)
    t_owner.start()
    t_waiter.start()
    time.sleep(0.3)  # waiter 已进入「file exists + 空表」窗口
    release.set()
    t_owner.join(timeout=30)
    t_waiter.join(timeout=30)
    assert results == ["ok", "ok"], f"results={results}（owner 初始化窗口内 waiter 被误判）"
    row_count = _count_all()
    final_records = store.list_alert_rules(limit=200)
    assert {r.rule.rule_id for r in final_records} == {"owner.a", "waiter.b"}
