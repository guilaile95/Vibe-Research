"""P0-PH2-QA2 / R1：Formal Thesis 并发 / 原子性回归测试套件。

覆盖 Formal Thesis 生命周期与 canonical delta 在**并发写入**下的 invariant：

* exactly-one-wins：begin / confirm / freeze / archive / terminal 竞争，
  loser 的异常类型严格匹配（R1：Case 1/2 必须为 FormalLifecycleConflictError）
* append-only：并发 non-terminal delta 序列严格 1,2；无 duplicate / lost
* no-post-terminal：terminal 之后的 delta 必须被拒绝；success 与 persisted
  row count 必须一致（R1：Case 6/8 明确二分合法结果并逐一断言）
* evidence original 冻结：confirmed/frozen 的 live evidence mutation 不得
  污染 frozen original，也不得触发 revision bump（R1：Case 9 追加验证 live
  EvidenceRecord 已真实写入）
* failure atomicity：失败的 writer 不得留下 partial thesis / orphan revision /
  duplicate revision / partial delta / partial delta evidence snapshot
  （R1：Case 10 追加 evidence-backed terminal race，断言 snapshot 完整性与
  无 orphan link）

测试纪律（严格遵守 TASK 约束）：
* 全部使用 tmp_path + 真实 SQLite + 真实 service/store 事务
* 线程 worker 内不做 os.environ / importlib.reload / 全局 monkeypatch；
  DB 路径由主线程预先固定
* 并发使用 threading.Barrier 同步释放
* 只验证 invariant，不依赖哪个线程必然先赢（store 的进程级 _LOCK 会串行化
  同进程写事务，因此失败 writer 必然在 winner 提交后看到新状态并收到冲突）
"""
from __future__ import annotations

import sqlite3
import threading

import pytest

import evidence_thesis_service as svc
import evidence_thesis_store as store


# ---------------------------------------------------------------------------
# 基础构造 helpers（主线程固定 DB 路径，worker 只调用 service）
# ---------------------------------------------------------------------------

_THESIS_INPUT = {
    "subject_type": "stock",
    "subject_id": "600519",
    "title": "标题",
    "summary": "摘要",
    "core_claims": ["a", "b", "c"],
    "catalysts": [],
    "risks": [],
    "invalidation_conditions": [],
}

_FORMAL_UPDATE = {
    "title": "标题",
    "summary": "摘要",
    "status": "active",
    "core_claims": ["a", "b", "c"],
    "catalysts": [],
    "risks": [],
    "invalidation_conditions": [],
    "strategy": "SWING",
    "expected_horizon": {"unit": "TRADING_DAY", "min": 5, "max": 20, "anchor": "FREEZE_AT"},
    "free_notes": "note",
}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "evidence_concurrency.db"
    store.initialize_store(path)
    return path


def _thesis(db):
    return svc.create_thesis(db, dict(_THESIS_INPUT))["thesis"]["id"]


def _draft(db):
    """LEGACY -> DRAFT 完整合法 draft（current_revision=2）。"""
    tid = _thesis(db)
    svc.begin_formalization(db, tid)
    svc.update_thesis(db, tid, dict(_FORMAL_UPDATE), 1)
    return tid


def _confirmed(db):
    """完整合法 confirmed thesis（current_revision=2）。"""
    tid = _draft(db)
    svc.confirm_formalization(db, tid, 2)
    return tid


def _frozen(db):
    """FROZEN ACTIVE thesis（current_revision=frozen_revision=3）。"""
    tid = _confirmed(db)
    svc.freeze_formalization(db, tid, 2)
    return tid


def _confirmed_with_evidence(db, *, claim: str = "ORIGINAL"):
    """CONFIRMED thesis（current_revision=3）+ 一条 linked evidence。"""
    tid = _thesis(db)
    svc.begin_formalization(db, tid)
    evidence = svc.create_evidence(db, {
        "subject_type": "stock", "subject_id": "600519", "evidence_type": "news",
        "claim": claim, "source_title": "source", "source_url": None,
        "source_date": None, "accessed_at": "2026-01-02T00:00:00+00:00",
        "classification": "fact", "confidence": "high",
    })
    svc.link_evidence(db, tid, evidence["id"], "support", 1)
    svc.update_thesis(db, tid, dict(_FORMAL_UPDATE), 2)
    svc.confirm_formalization(db, tid, 3)
    return tid, evidence["id"]


def _frozen_with_evidence(db, *, count: int = 2):
    """FROZEN ACTIVE thesis + count 条 linked evidence。

    revision 演化：create(1) → link×count → update(count+1) → confirm →
    freeze(expected=count+2)，故 frozen_revision = count+3。
    """
    tid = _thesis(db)
    svc.begin_formalization(db, tid)
    evidence_ids = []
    for index in range(count):
        ev = svc.create_evidence(db, {
            "subject_type": "stock", "subject_id": "600519", "evidence_type": "news",
            "claim": f"claim-{index}", "source_title": "source", "source_url": None,
            "source_date": None, "accessed_at": "2026-01-02T00:00:00+00:00",
            "classification": "fact", "confidence": "high",
        })
        evidence_ids.append(ev["id"])
        svc.link_evidence(db, tid, ev["id"], "support", index + 1)
    svc.update_thesis(db, tid, dict(_FORMAL_UPDATE), count + 1)
    svc.confirm_formalization(db, tid, count + 2)
    svc.freeze_formalization(db, tid, count + 2)
    return tid, evidence_ids


# ---------------------------------------------------------------------------
# 并发 runner（threading.Barrier 同步）
# ---------------------------------------------------------------------------


def _race(*workers):
    """并发执行 workers；返回 (successes, failures)。

    success = 返回 dict；failure = 抛出任意异常。worker 只接收固定 db 路径
    的闭包，不做任何环境 / 模块级修改。
    """
    n = len(workers)
    barrier = threading.Barrier(n)
    results = []
    errors = []

    def _run(worker):
        try:
            barrier.wait(timeout=30)
        except threading.BrokenBarrierError:
            return
        try:
            results.append(worker())
        except Exception as exc:  # noqa: BLE001 — worker 内判定 winner/loser
            errors.append(exc)

    threads = [
        threading.Thread(target=_run, args=(worker,), name=f"race-{i}")
        for i, worker in enumerate(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    alive = [thread.name for thread in threads if thread.is_alive()]
    assert not alive, f"race worker 卡死：{alive}"
    assert len(results) + len(errors) == n, (
        f"race 线程未全部产出结果：successes={len(results)} errors={len(errors)}"
    )
    return results, errors


# ---------------------------------------------------------------------------
# 持久化断言 helpers（Case 10：persisted validators 必须全部 PASS）
# ---------------------------------------------------------------------------

_TERMINAL = ("DISPROVEN", "INVALIDATED")


def _thesis_row(db, tid):
    conn = sqlite3.connect(db)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM investment_theses WHERE id=?", (tid,)
        ).fetchone()
        assert row is not None, f"thesis {tid} 不存在"
        return row
    finally:
        conn.close()


def _revision_kinds(db, tid):
    """返回 [(revision_number, revision_kind)] 升序。"""
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT revision_number, revision_kind FROM thesis_revisions "
            "WHERE thesis_id=? ORDER BY revision_number",
            (tid,),
        ).fetchall()
        return [(int(r[0]), r[1]) for r in rows]
    finally:
        conn.close()


def _delta_seq(db, tid):
    """返回 [(delta_sequence, delta_state, base_revision)] 升序。"""
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT delta_sequence, delta_state, base_revision FROM thesis_deltas "
            "WHERE thesis_id=? ORDER BY delta_sequence",
            (tid,),
        ).fetchall()
        return [(int(r[0]), r[1], int(r[2])) for r in rows]
    finally:
        conn.close()


def _persisted_ok(db, tid):
    """运行全部 persisted validators；任一失败抛 EvidenceLedgerCorruptedError。"""
    conn = sqlite3.connect(db)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM investment_theses WHERE id=?", (tid,)
        ).fetchone()
        assert row is not None
        store.validate_persisted_thesis_main(row)
        store.validate_persisted_revision_history(conn, tid, row)
        store.validate_persisted_thesis_chain(conn, tid, row)
        store.validate_persisted_delta_chain(conn, tid)
    finally:
        conn.close()


def _assert_winner_loser(results, errors, *, exception_type):
    """exactly 1 success / exactly 1 conflict，且 conflict 类型必须严格匹配。"""
    assert len(results) == 1, f"期望 exactly 1 success，实际 {len(results)}"
    assert len(errors) == 1, f"期望 exactly 1 conflict，实际 {len(errors)}"
    assert type(errors[0]) is exception_type, (
        f"冲突类型必须严格为 {exception_type.__name__}，"
        f"实际 {type(errors[0]).__name__}: {errors[0]}"
    )


# ---------------------------------------------------------------------------
# CASE 1 — Begin Formalization Race
# ---------------------------------------------------------------------------


def test_begin_formalization_race_exactly_one_wins(db):
    tid = _thesis(db)
    results, errors = _race(
        lambda: svc.begin_formalization(db, tid),
        lambda: svc.begin_formalization(db, tid),
    )
    # Case 1：loser 必须严格为 FormalLifecycleConflictError
    _assert_winner_loser(results, errors, exception_type=svc.FormalLifecycleConflictError)

    row = _thesis_row(db, tid)
    assert row["formal_state"] == "draft"
    assert row["formalization_started_at"] is not None
    assert int(row["current_revision"]) == 1
    # 不得产生额外 revision
    assert _revision_kinds(db, tid) == [(1, "CONTENT")]
    _persisted_ok(db, tid)


# ---------------------------------------------------------------------------
# CASE 2 — Confirm Race
# ---------------------------------------------------------------------------


def test_confirm_race_exactly_one_wins(db):
    tid = _draft(db)
    results, errors = _race(
        lambda: svc.confirm_formalization(db, tid, 2),
        lambda: svc.confirm_formalization(db, tid, 2),
    )
    # Case 2：loser 必须严格为 FormalLifecycleConflictError
    _assert_winner_loser(results, errors, exception_type=svc.FormalLifecycleConflictError)

    row = _thesis_row(db, tid)
    assert row["formal_state"] == "confirmed"
    assert row["confirmed_at"] is not None
    assert int(row["current_revision"]) == 2
    # Confirm 不产生 revision bump
    assert _revision_kinds(db, tid) == [(1, "CONTENT"), (2, "CONTENT")]
    _persisted_ok(db, tid)


# ---------------------------------------------------------------------------
# CASE 3 — Freeze CAS Race
# ---------------------------------------------------------------------------


def test_freeze_cas_race_exactly_one_freeze(db):
    tid = _confirmed(db)
    results, errors = _race(
        lambda: svc.freeze_formalization(db, tid, 2),
        lambda: svc.freeze_formalization(db, tid, 2),
    )
    # 失败 writer 在 winner 已提交后读到 formal_state=frozen，冲突类型确定
    _assert_winner_loser(results, errors, exception_type=svc.FormalLifecycleConflictError)

    row = _thesis_row(db, tid)
    assert row["formal_state"] == "frozen"
    assert int(row["frozen_revision"]) == 3
    assert int(row["current_revision"]) == 3
    # FORMAL_FREEZE 恰好 1 条；无 duplicate / 无 N+2
    assert _revision_kinds(db, tid) == [
        (1, "CONTENT"), (2, "CONTENT"), (3, "FORMAL_FREEZE"),
    ]
    _persisted_ok(db, tid)


# ---------------------------------------------------------------------------
# CASE 4 — Archive Race
# ---------------------------------------------------------------------------


def test_archive_race_exactly_one_archive(db):
    tid = _frozen(db)
    results, errors = _race(
        lambda: svc.archive_formalization(db, tid, 3),
        lambda: svc.archive_formalization(db, tid, 3),
    )
    # 失败 writer 在 winner 已提交后读到 status=archived，冲突类型确定
    _assert_winner_loser(results, errors, exception_type=svc.FormalLifecycleConflictError)

    row = _thesis_row(db, tid)
    assert row["status"] == "archived"
    assert int(row["frozen_revision"]) == 3
    assert int(row["current_revision"]) == 4
    # FORMAL_ARCHIVE 恰好 1 条
    assert _revision_kinds(db, tid) == [
        (1, "CONTENT"), (2, "CONTENT"), (3, "FORMAL_FREEZE"), (4, "FORMAL_ARCHIVE"),
    ]
    _persisted_ok(db, tid)


# ---------------------------------------------------------------------------
# CASE 5 — Concurrent Non-Terminal Delta（≥20 rounds）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("_round_index", range(20))
def test_concurrent_non_terminal_delta_rounds(db, _round_index):
    tid = _frozen(db)
    results, errors = _race(
        lambda: svc.create_thesis_delta(db, tid, "STRENGTHENED", "strengthen"),
        lambda: svc.create_thesis_delta(db, tid, "WEAKENED", "weaken"),
    )
    # 两者都成功：non-terminal 无互斥
    assert len(results) == 2, f"round 失败：{[type(e).__name__ for e in errors]}"
    assert len(errors) == 0

    seqs = _delta_seq(db, tid)
    # delta_sequence 必须严格为 1, 2：无 duplicate / 无 lost
    assert [seq for seq, _, _ in seqs] == [1, 2]
    assert sorted(state for _, state, _ in seqs) == ["STRENGTHENED", "WEAKENED"]
    # base_revision 全部 == frozen_revision
    assert all(base == 3 for _, _, base in seqs)
    _persisted_ok(db, tid)


# ---------------------------------------------------------------------------
# CASE 6 — Terminal vs Non-Terminal Race（≥20 rounds each）
# ---------------------------------------------------------------------------


def _terminal_non_terminal_round(db, terminal: str, nontrivial: str):
    tid = _frozen(db)
    results, errors = _race(
        lambda: svc.create_thesis_delta(db, tid, terminal, "terminal"),
        lambda: svc.create_thesis_delta(db, tid, nontrivial, "nontrivial"),
    )
    seqs = _delta_seq(db, tid)
    states = [state for _, state, _ in seqs]
    if len(results) == 2:
        # 合法结果 A：nontrivial seq1 + terminal seq2 → 两者成功
        assert len(errors) == 0, f"2 success 时不得有冲突：{[type(e).__name__ for e in errors]}"
        assert [seq for seq, _, _ in seqs] == [1, 2]
        assert states == [nontrivial, terminal]
    elif len(results) == 1:
        # 合法结果 B：terminal seq1 → nontrivial 收到 conflict
        assert len(errors) == 1
        assert type(errors[0]) is svc.ThesisDeltaConflictError, (
            f"terminal 先赢时 nontrivial 必须 ThesisDeltaConflictError："
            f"{type(errors[0]).__name__}: {errors[0]}"
        )
        assert [seq for seq, _, _ in seqs] == [1]
        assert states == [terminal]
    else:
        assert False, f"unexpected results={len(results)} errors={len(errors)}"
    # 绝对禁止 NO POST-TERMINAL DELTA：terminal 必须是链尾；success 与 persisted 一致
    assert sum(1 for s in states if s in _TERMINAL) == 1
    assert all(base == 3 for _, _, base in seqs)
    _persisted_ok(db, tid)


@pytest.mark.parametrize("_round_index", range(20))
def test_terminal_vs_non_terminal_disproven_strengthened(db, _round_index):
    _terminal_non_terminal_round(db, "DISPROVEN", "STRENGTHENED")


@pytest.mark.parametrize("_round_index", range(20))
def test_terminal_vs_non_terminal_invalidated_weakened(db, _round_index):
    _terminal_non_terminal_round(db, "INVALIDATED", "WEAKENED")


# ---------------------------------------------------------------------------
# CASE 7 — Terminal vs Terminal Race（≥20 rounds）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("_round_index", range(20))
def test_terminal_vs_terminal_race_exactly_one_terminal(db, _round_index):
    tid = _frozen(db)
    results, errors = _race(
        lambda: svc.create_thesis_delta(db, tid, "DISPROVEN", "terminal-a"),
        lambda: svc.create_thesis_delta(db, tid, "INVALIDATED", "terminal-b"),
    )
    # exactly 1 success / exactly 1 conflict，loser 严格为 ThesisDeltaConflictError
    _assert_winner_loser(results, errors, exception_type=svc.ThesisDeltaConflictError)

    seqs = _delta_seq(db, tid)
    # canonical chain 只有一个 terminal delta
    assert len(seqs) == 1
    assert seqs[0][1] in _TERMINAL
    assert seqs[0][2] == 3
    _persisted_ok(db, tid)


# ---------------------------------------------------------------------------
# CASE 8 — Archive vs Delta Race（≥20 rounds）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("_round_index", range(20))
def test_archive_vs_delta_race(db, _round_index):
    tid = _frozen(db)
    results, errors = _race(
        lambda: svc.create_thesis_delta(db, tid, "STRENGTHENED", "delta"),
        lambda: svc.archive_formalization(db, tid, 3),
    )
    row = _thesis_row(db, tid)
    assert row["status"] == "archived"
    assert int(row["current_revision"]) == 4

    seqs = _delta_seq(db, tid)
    if len(results) == 2:
        # delta 先提交 → delta 保留，随后 archive（两者成功）
        assert len(errors) == 0, f"2 success 时不得有冲突：{[type(e).__name__ for e in errors]}"
        assert [seq for seq, _, _ in seqs] == [1], f"delta 必须真实存在：{seqs}"
        assert seqs[0][1] == "STRENGTHENED"
        assert seqs[0][2] == 3
    elif len(results) == 1:
        # archive 先提交 → delta 收到 conflict
        assert len(errors) == 1
        assert type(errors[0]) is svc.ThesisDeltaConflictError, (
            f"archive 已完成后 delta 必须 ThesisDeltaConflictError："
            f"{type(errors[0]).__name__}: {errors[0]}"
        )
        # delta rows == []：绝对禁止 archive 完成后仍产生 delta
        assert seqs == []
    else:
        assert False, f"unexpected results={len(results)} errors={len(errors)}"
    _persisted_ok(db, tid)


# ---------------------------------------------------------------------------
# CASE 9 — Confirmed Evidence Mutation vs Freeze（≥10 rounds）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("_round_index", range(10))
def test_confirmed_evidence_mutation_vs_freeze(db, _round_index):
    tid, evidence_id = _confirmed_with_evidence(db, claim="ORIGINAL")

    # 记录 CONFIRMED 权威快照
    confirmed = svc.get_thesis(db, tid)
    confirmed_claims = [link["claim"] for link in confirmed["evidence_links"]]
    assert confirmed_claims == ["ORIGINAL"]

    results, errors = _race(
        lambda: svc.update_evidence(db, evidence_id, {
            "evidence_type": "news", "claim": "MUTATED", "source_title": "source",
            "source_url": None, "source_date": None,
            "accessed_at": "2026-01-03T00:00:00+00:00",
            "classification": "fact", "confidence": "high",
        }),
        lambda: svc.freeze_formalization(db, tid, 3),
    )
    # 无论调度顺序，两个 writer 都成功（mutation 不 bump confirmed thesis；
    # freeze 读取已持久化的 original snapshot）
    assert len(results) == 2, f"round 失败：{[type(e).__name__ for e in errors]}"
    assert len(errors) == 0

    frozen = svc.get_thesis(db, tid)
    frozen_claims = [link["claim"] for link in frozen["evidence_links"]]
    # live evidence mutation 不得污染 frozen original
    assert frozen_claims == ["ORIGINAL"], f"frozen original 被污染：{frozen_claims}"
    # live EvidenceRecord 已被 mutation 真实写入（confirmed/frozen 不 bump thesis，
    # 但 evidence 行本身始终更新）
    live = svc.get_evidence(db, evidence_id)
    assert live["claim"] == "MUTATED", f"live evidence 未更新：{live['claim']}"

    row = _thesis_row(db, tid)
    assert row["formal_state"] == "frozen"
    assert int(row["current_revision"]) == 4
    assert int(row["frozen_revision"]) == 4
    # evidence mutation 不得导致 confirmed/frozen thesis revision bump
    assert _revision_kinds(db, tid) == [
        (1, "CONTENT"), (2, "CONTENT"), (3, "CONTENT"), (4, "FORMAL_FREEZE"),
    ]
    _persisted_ok(db, tid)


# ---------------------------------------------------------------------------
# CASE 10 — Failure Atomicity
# ---------------------------------------------------------------------------


def test_failure_atomicity_no_partial_state_on_losing_writers(db):
    """失败 writer 不得产生 partial thesis / orphan revision / duplicate revision /
    partial delta / partial delta evidence snapshot。每轮结束运行 persisted validators。
    """
    # 1) Begin race 失败者 → 无额外 revision
    tid1 = _thesis(db)
    results, errors = _race(
        lambda: svc.begin_formalization(db, tid1),
        lambda: svc.begin_formalization(db, tid1),
    )
    _assert_winner_loser(results, errors, exception_type=svc.FormalLifecycleConflictError)
    assert _revision_kinds(db, tid1) == [(1, "CONTENT")]
    _persisted_ok(db, tid1)

    # 2) Freeze CAS race 失败者 → 无 duplicate FORMAL_FREEZE / 无 N+2
    tid2 = _confirmed(db)
    results, errors = _race(
        lambda: svc.freeze_formalization(db, tid2, 2),
        lambda: svc.freeze_formalization(db, tid2, 2),
    )
    _assert_winner_loser(results, errors, exception_type=svc.FormalLifecycleConflictError)
    assert _revision_kinds(db, tid2) == [
        (1, "CONTENT"), (2, "CONTENT"), (3, "FORMAL_FREEZE"),
    ]
    _persisted_ok(db, tid2)

    # 3) Terminal race 失败者 → 无第二个 terminal / 无 partial delta
    tid3 = _frozen(db)
    results, errors = _race(
        lambda: svc.create_thesis_delta(db, tid3, "DISPROVEN", "t"),
        lambda: svc.create_thesis_delta(db, tid3, "INVALIDATED", "t"),
    )
    _assert_winner_loser(results, errors, exception_type=svc.ThesisDeltaConflictError)
    assert len(_delta_seq(db, tid3)) == 1
    _persisted_ok(db, tid3)

    # 4) Archive race 失败者 → 无 duplicate FORMAL_ARCHIVE / 无 N+2
    tid4 = _frozen(db)
    results, errors = _race(
        lambda: svc.archive_formalization(db, tid4, 3),
        lambda: svc.archive_formalization(db, tid4, 3),
    )
    _assert_winner_loser(results, errors, exception_type=svc.FormalLifecycleConflictError)
    assert _revision_kinds(db, tid4) == [
        (1, "CONTENT"), (2, "CONTENT"), (3, "FORMAL_FREEZE"), (4, "FORMAL_ARCHIVE"),
    ]
    _persisted_ok(db, tid4)


def test_failure_atomicity_evidence_backed_terminal_race(db):
    """evidence-backed terminal race：两个 writer 都携带 evidence_ids。

    要求：
    * exactly 1 success / exactly 1 ThesisDeltaConflictError
    * thesis_deltas 恰好 1 条
    * winner delta 的 evidence snapshot == 完整 expected set（无 missing / 无 extra）
    * 无 orphan thesis_delta_evidence_links
    * 最后四个 persisted validators 全部 PASS
    """
    tid, evidence_ids = _frozen_with_evidence(db, count=2)
    expected_set = sorted(evidence_ids)
    frozen_rev = int(_thesis_row(db, tid)["frozen_revision"])

    results, errors = _race(
        lambda: svc.create_thesis_delta(db, tid, "DISPROVEN", "terminal-a", evidence_ids),
        lambda: svc.create_thesis_delta(db, tid, "INVALIDATED", "terminal-b", evidence_ids),
    )
    _assert_winner_loser(results, errors, exception_type=svc.ThesisDeltaConflictError)

    # thesis_deltas 恰好 1 条（无 duplicate / 无 partial delta）
    seqs = _delta_seq(db, tid)
    assert [seq for seq, _, _ in seqs] == [1]
    assert seqs[0][1] in _TERMINAL
    assert seqs[0][2] == frozen_rev

    # winner delta 的 evidence snapshot == 完整 expected set（无 missing / 无 extra）
    deltas = svc.list_thesis_deltas(db, tid)["items"]
    assert len(deltas) == 1
    snapshot_ids = sorted(link["evidence_id"] for link in deltas[0]["evidence_links"])
    assert snapshot_ids == expected_set, (
        f"evidence snapshot 不完整：{snapshot_ids} != {expected_set}"
    )

    # 无 orphan thesis_delta_evidence_links
    conn = sqlite3.connect(db)
    try:
        orphans = conn.execute(
            "SELECT COUNT(*) FROM thesis_delta_evidence_links l "
            "LEFT JOIN thesis_deltas d ON l.delta_id = d.delta_id "
            "WHERE d.delta_id IS NULL",
        ).fetchone()[0]
    finally:
        conn.close()
    assert orphans == 0, f"存在 orphan thesis_delta_evidence_links：{orphans}"

    _persisted_ok(db, tid)
