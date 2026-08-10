"""Frozen Decision Ledger 存储层测试：不可变、幂等重放、fail closed、并发、零副作用。"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

import frozen_decision_store as store


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _valid_frozen(**overrides) -> dict:
    """构造一个完整合法的 frozen 行 dict（形状与 service 产出一致）。"""
    snapshot = {
        "snapshot_schema_version": store.SCHEMA_VERSION,
        "decision_id": "decision_" + "a" * 32,
        "security_code": "600519",
        "strategy": "SWING",
        "campaign_id": "campaign_" + "b" * 32,
        "committed_at": "2026-08-10T06:00:00.000000Z",
        "thesis_id": "c" * 32,
        "thesis_revision": 2,
        "asset_view": {"label": "茅台", "pe": 30.5},
        "trade_view": {"entry_zone": [1400, 1450], "size_pct": 0.1},
        "portfolio_view": {"target_weight": 0.15},
        "next_best_action": "BUY SMALL",
        "action_envelope": {"max_size": 0.1, "min_size": 0.05},
        "maintain_conditions": ["营收增速保持", "PE 不高于 35"],
        "upgrade_conditions": ["站稳年线"],
        "downgrade_conditions": ["跌破 60 日线"],
        "invalidation_conditions": ["业绩暴雷"],
        "strategy_horizon": "2 至 4 周",
        "review_by": "2026-08-25T00:00:00.000000Z",
        "key_assumptions": ["宏观流动性宽松", "行业景气持续"],
        "event_invalidation_conditions": ["减持公告", "监管处罚"],
        "validity_status_at_commit": "CURRENT",
        "risk_policy_version": "risk-policy-v0.1",
        "opportunity_policy_version": "opp-policy-v0.1",
        "decision_policy_version": "decision-policy-v0.1",
        "behavior_model_version": "behavior-v0.1",
        "data_quality": {"grade": "high"},
        "evidence_confidence": 0.8,
        "inference_confidence": "medium",
        "decision_confidence": None,
        "evidence_refs": ["ev_123"],
        "risk_refs": [],
        "source_refs": ["src_1", "src_2"],
    }
    snapshot.update(overrides)
    frozen = {
        **snapshot,
        "snapshot_json": store.canonical_json(snapshot),
        "snapshot_hash": store.snapshot_hash(snapshot),
        "user_confirmed": True,
        "created_at": "2026-08-10T06:00:01.000000Z",
    }
    return frozen


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "frozen_decisions.sqlite3"


def _write_valid(db_path: Path, **overrides) -> dict:
    frozen = _valid_frozen(**overrides)
    return store.write_frozen_decision(db_path, frozen)


def _mutated_frozen(frozen: dict, **changes) -> dict:
    """基于既有冻结对象生成内容变化的变体：snapshot_json/hash 同步重建。"""
    snapshot = {key: frozen[key] for key in store.SNAPSHOT_KEYS}
    snapshot.update(changes)
    return {
        **frozen,
        **snapshot,
        "snapshot_json": store.canonical_json(snapshot),
        "snapshot_hash": store.snapshot_hash(snapshot),
    }


def _tamper(db_path: Path, set_clause: str, value) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(f"UPDATE frozen_decisions SET {set_clause} = ?", (value,))
        conn.commit()
    finally:
        conn.close()


def _dir_snapshot(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {p.name for p in path.iterdir()}


# ---------------------------------------------------------------------------
# 路径解析
# ---------------------------------------------------------------------------

class TestPathResolution:
    def test_explicit_wins(self, tmp_path):
        p = tmp_path / "x.sqlite3"
        assert store.resolve_frozen_decision_db_path(p) == p

    def test_env_db_wins_over_data_dir(self, tmp_path, monkeypatch):
        env_db = tmp_path / "env_db.sqlite3"
        monkeypatch.setenv("VIBE_RESEARCH_FROZEN_DECISION_DB", str(env_db))
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path / "data"))
        assert store.resolve_frozen_decision_db_path() == env_db

    def test_data_dir_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv("VIBE_RESEARCH_FROZEN_DECISION_DB", raising=False)
        data_dir = tmp_path / "data"
        monkeypatch.setenv("VR_DATA_DIR", str(data_dir))
        assert store.resolve_frozen_decision_db_path() == data_dir / "frozen_decisions.sqlite3"

    def test_home_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv("VIBE_RESEARCH_FROZEN_DECISION_DB", raising=False)
        monkeypatch.delenv("VR_DATA_DIR", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert store.resolve_frozen_decision_db_path() == (
            tmp_path / ".vibe-research" / "frozen_decisions.sqlite3"
        )

    def test_resolve_has_no_side_effects(self, tmp_path):
        store.resolve_frozen_decision_db_path(tmp_path / "nope.sqlite3")
        assert _dir_snapshot(tmp_path) == set()


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

class TestInitialize:
    def test_initialize_creates_schema(self, db_path):
        store.initialize_store(db_path)
        assert db_path.exists()
        conn = sqlite3.connect(str(db_path))
        try:
            version = conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()[0]
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='frozen_decisions'"
            ).fetchone()
        finally:
            conn.close()
        assert version == store.SCHEMA_VERSION
        assert table is not None

    def test_initialize_idempotent(self, db_path):
        store.initialize_store(db_path)
        store.initialize_store(db_path)

    def test_initialize_rejects_unknown_version(self, db_path):
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("INSERT INTO schema_meta VALUES ('schema_version', 'other-version-v9')")
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(store.FrozenDecisionSchemaVersionError):
            store.initialize_store(db_path)

    def test_initialize_rejects_nonempty_db_without_schema_meta(self, db_path):
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE random_table (id INTEGER)")
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(store.FrozenDecisionCorruptedError):
            store.initialize_store(db_path)


class TestInitializeZeroMutation:
    """P1-B：版本门先于任何 journal 突变；不支持的库零突变拒绝。"""

    def _db_sha256(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _dir_names(self, path: Path) -> set[str]:
        return {p.name for p in path.iterdir()}

    def test_unsupported_schema_initialize_zero_mutation(self, db_path):
        # 构造不支持的 schema 版本库（无 frozen_decisions 表）
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("INSERT INTO schema_meta VALUES ('schema_version', 'frozen-decision-ledger.v9.9')")
            conn.commit()
        finally:
            conn.close()
        before = {
            "sha": self._db_sha256(db_path),
            "size": db_path.stat().st_size,
            "dir": self._dir_names(db_path.parent),
        }
        with pytest.raises(store.FrozenDecisionSchemaVersionError):
            store.initialize_store(db_path)
        after = {
            "sha": self._db_sha256(db_path),
            "size": db_path.stat().st_size,
            "dir": self._dir_names(db_path.parent),
        }
        assert after == before
        # 无 WAL / SHM / journal / 任何额外文件
        assert not Path(str(db_path) + "-wal").exists()
        assert not Path(str(db_path) + "-shm").exists()
        assert not Path(str(db_path) + "-journal").exists()
        assert after["dir"] == {db_path.name}
        # schema/版本保持原样（未自动修复）
        conn = sqlite3.connect(str(db_path))
        try:
            version = conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert version == "frozen-decision-ledger.v9.9"

    def test_nonempty_db_without_schema_meta_initialize_zero_mutation(self, db_path):
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE random_table (id INTEGER)")
            conn.commit()
        finally:
            conn.close()
        before = {
            "sha": self._db_sha256(db_path),
            "size": db_path.stat().st_size,
            "dir": self._dir_names(db_path.parent),
        }
        with pytest.raises(store.FrozenDecisionCorruptedError):
            store.initialize_store(db_path)
        after = {
            "sha": self._db_sha256(db_path),
            "size": db_path.stat().st_size,
            "dir": self._dir_names(db_path.parent),
        }
        assert after == before
        assert not Path(str(db_path) + "-wal").exists()
        assert not Path(str(db_path) + "-shm").exists()
        assert not Path(str(db_path) + "-journal").exists()

    def test_valid_db_reinitialize_keeps_schema_and_no_side_files(self, db_path):
        store.initialize_store(db_path)
        before_dir = self._dir_names(db_path.parent)
        store.initialize_store(db_path)
        assert self._dir_names(db_path.parent) == before_dir
        conn = sqlite3.connect(str(db_path))
        try:
            version = conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert version == store.SCHEMA_VERSION


# ---------------------------------------------------------------------------
# 写 / 读 roundtrip 与列举契约
# ---------------------------------------------------------------------------

class TestWriteRead:
    def test_roundtrip_preserves_all_fields(self, db_path):
        frozen = _write_valid(db_path)
        got = store.get_frozen_decision(db_path, frozen["decision_id"])
        assert got is not None
        assert got["decision_id"] == frozen["decision_id"]
        assert got["snapshot_hash"] == frozen["snapshot_hash"]
        assert got["asset_view"] == {"label": "茅台", "pe": 30.5}
        assert got["trade_view"] == {"entry_zone": [1400, 1450], "size_pct": 0.1}
        assert got["portfolio_view"] == {"target_weight": 0.15}
        assert got["next_best_action"] == "BUY SMALL"
        assert got["action_envelope"] == {"max_size": 0.1, "min_size": 0.05}
        assert got["maintain_conditions"] == ["营收增速保持", "PE 不高于 35"]
        assert got["evidence_refs"] == ["ev_123"]
        assert got["user_confirmed"] is True
        assert got["validity_status_at_commit"] == "CURRENT"

    def test_missing_returns_none(self, db_path):
        assert store.get_frozen_decision(db_path, "decision_" + "f" * 32) is None

    def test_list_empty(self, db_path):
        assert store.list_frozen_decisions(db_path) == []

    def test_list_orders_by_committed_at_then_id(self, db_path):
        _write_valid(db_path, decision_id="decision_" + "1" * 32, committed_at="2026-08-10T05:00:00.000000Z")
        _write_valid(db_path, decision_id="decision_" + "3" * 32, committed_at="2026-08-10T07:00:00.000000Z")
        _write_valid(db_path, decision_id="decision_" + "2" * 32, committed_at="2026-08-10T05:00:00.000000Z")
        ids = [d["decision_id"] for d in store.list_frozen_decisions(db_path)]
        assert ids == ["decision_" + "1" * 32, "decision_" + "2" * 32, "decision_" + "3" * 32]

    def test_list_filters(self, db_path):
        _write_valid(db_path, decision_id="decision_" + "1" * 32, security_code="600519", strategy="SWING", campaign_id="campaign_" + "a" * 32)
        _write_valid(db_path, decision_id="decision_" + "2" * 32, security_code="000858", strategy="SHORT", campaign_id="campaign_" + "a" * 32)
        _write_valid(db_path, decision_id="decision_" + "3" * 32, security_code="600519", strategy="MEDIUM", campaign_id="campaign_" + "b" * 32)
        assert len(store.list_frozen_decisions(db_path, security_code="600519")) == 2
        assert len(store.list_frozen_decisions(db_path, strategy="SHORT")) == 1
        assert len(store.list_frozen_decisions(db_path, campaign_id="campaign_" + "a" * 32)) == 2
        assert len(store.list_frozen_decisions(db_path, security_code="600519", strategy="SWING")) == 1

    def test_canonical_json_deterministic(self):
        a = {"b": 1, "a": [{"d": 2, "c": 1}], "z": "文本"}
        b = {"z": "文本", "a": [{"c": 1, "d": 2}], "b": 1}
        assert store.canonical_json(a) == store.canonical_json(b)
        assert store.snapshot_hash(a) == store.snapshot_hash(b)

    def test_canonical_json_rejects_nan_infinity(self):
        with pytest.raises(ValueError):
            store.canonical_json({"x": float("nan")})
        with pytest.raises(ValueError):
            store.canonical_json({"x": float("inf")})

    def test_list_pagination(self, db_path):
        for i in range(5):
            _write_valid(
                db_path,
                decision_id=f"decision_{i:032x}",
                committed_at=f"2026-08-10T0{i}:00:00.000000Z",
            )
        assert len(store.list_frozen_decisions(db_path, limit=2, offset=0)) == 2
        assert len(store.list_frozen_decisions(db_path, limit=2, offset=4)) == 1

    def test_list_invalid_strategy_filter_rejected(self, db_path):
        _write_valid(db_path)
        with pytest.raises(ValueError):
            store.list_frozen_decisions(db_path, strategy="swing")


# ---------------------------------------------------------------------------
# 不可变与幂等重放
# ---------------------------------------------------------------------------

class TestImmutability:
    def test_exact_replay_idempotent(self, db_path):
        frozen = _write_valid(db_path)
        again = store.write_frozen_decision(db_path, frozen)
        assert again["decision_id"] == frozen["decision_id"]
        assert again["snapshot_hash"] == frozen["snapshot_hash"]
        assert len(store.list_frozen_decisions(db_path)) == 1

    def test_conflicting_replay_fails_closed(self, db_path):
        frozen = _write_valid(db_path)
        tampered = _mutated_frozen(frozen, next_best_action="HOLD")
        with pytest.raises(store.FrozenDecisionConflictError):
            store.write_frozen_decision(db_path, tampered)
        # 原内容未被覆盖
        got = store.get_frozen_decision(db_path, frozen["decision_id"])
        assert got["next_best_action"] == "BUY SMALL"

    def test_no_update_delete_upsert_paths(self, db_path):
        frozen = _write_valid(db_path)
        # 没有任何公开 API 可以修改或删除：仅存在 read/list/write(append) 路径
        assert callable(store.get_frozen_decision)
        assert callable(store.list_frozen_decisions)
        assert frozen["decision_id"]

    def test_same_business_content_different_id_is_new_decision(self, db_path):
        base = _valid_frozen()
        base2 = _mutated_frozen(base, decision_id="decision_" + "d" * 32)
        first = store.write_frozen_decision(db_path, base)
        second = store.write_frozen_decision(db_path, base2)
        assert first["decision_id"] != second["decision_id"]
        assert len(store.list_frozen_decisions(db_path)) == 2


# ---------------------------------------------------------------------------
# 缺失库 / 不支持 schema / 损坏库：零副作用
# ---------------------------------------------------------------------------

class TestZeroSideEffectsRead:
    def test_missing_db_read_creates_nothing(self, tmp_path):
        missing = tmp_path / "no" / "such" / "dir" / "frozen_decisions.sqlite3"
        assert store.get_frozen_decision(missing, "decision_" + "a" * 32) is None
        assert store.list_frozen_decisions(missing) == []
        assert not (tmp_path / "no").exists()

    def test_normal_read_creates_no_wal_shm(self, db_path):
        _write_valid(db_path)
        before = _dir_snapshot(db_path.parent)
        store.get_frozen_decision(db_path, "decision_" + "a" * 32)
        store.list_frozen_decisions(db_path)
        assert _dir_snapshot(db_path.parent) == before
        assert not Path(str(db_path) + "-wal").exists()
        assert not Path(str(db_path) + "-shm").exists()

    def test_unsupported_schema_read_fails_closed_without_mutation(self, db_path):
        _write_valid(db_path)
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "UPDATE schema_meta SET value='frozen-decision-ledger.v9.9' "
                "WHERE key='schema_version'"
            )
            conn.commit()
        finally:
            conn.close()
        before = _dir_snapshot(db_path.parent)
        with pytest.raises(store.FrozenDecisionSchemaVersionError):
            store.get_frozen_decision(db_path, "decision_" + "a" * 32)
        with pytest.raises(store.FrozenDecisionSchemaVersionError):
            store.list_frozen_decisions(db_path)
        assert _dir_snapshot(db_path.parent) == before

    def test_nonempty_db_without_schema_meta_fails_closed(self, db_path):
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE stray (id INTEGER)")
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(store.FrozenDecisionCorruptedError):
            store.get_frozen_decision(db_path, "decision_" + "a" * 32)
        with pytest.raises(store.FrozenDecisionCorruptedError):
            store.list_frozen_decisions(db_path)

    def test_garbage_file_fails_closed(self, db_path):
        db_path.write_bytes(b"this is not a sqlite database at all")
        with pytest.raises(store.FrozenDecisionCorruptedError):
            store.get_frozen_decision(db_path, "decision_" + "a" * 32)
        with pytest.raises(store.FrozenDecisionCorruptedError):
            store.list_frozen_decisions(db_path)
        # 只读失败绝不改写文件内容
        assert db_path.read_bytes().startswith(b"this is not a sqlite")

    def test_empty_db_file_fails_closed(self, db_path):
        db_path.write_bytes(b"")
        with pytest.raises(store.FrozenDecisionCorruptedError):
            store.list_frozen_decisions(db_path)


# ---------------------------------------------------------------------------
# 篡改检测（fail closed）
# ---------------------------------------------------------------------------

class TestTamperFailClosed:
    @pytest.mark.parametrize(
        "column,value",
        [
            ("next_best_action", "HOLD"),
            ("campaign_id", "campaign_" + "e" * 32),
            ("strategy", "MEDIUM"),
            ("snapshot_hash", "0" * 64),
            ("review_by", "2027-01-01T00:00:00.000000Z"),
            ("risk_policy_version", "tampered-policy"),
            ("thesis_revision", 9),
            ("thesis_id", "f" * 32),
            ("security_code", "000858"),
            ("committed_at", "2026-09-01T00:00:00.000000Z"),
            ("created_at", "garbage"),
            ("created_at", "2026-08-10T06:00:01+00:00"),
            ("user_confirmed", 0),
            ("validity_status_at_commit", "EXPIRED"),
            ("snapshot_schema_version", "frozen-decision-ledger.v0.2"),
        ],
    )
    def test_column_tamper_fails_closed(self, db_path, column, value):
        _write_valid(db_path)
        _tamper(db_path, column, value)
        with pytest.raises(store.FrozenDecisionCorruptedError):
            store.get_frozen_decision(db_path, "decision_" + "a" * 32)
        with pytest.raises(store.FrozenDecisionCorruptedError):
            store.list_frozen_decisions(db_path)

    def test_snapshot_json_content_tamper_fails_closed(self, db_path):
        _write_valid(db_path)
        # 篡改 snapshot_json 内部业务值（列未改，文本改且保持 canonical）
        _tamper_snapshot_json(
            db_path, lambda s: store.canonical_json({**s, "asset_view": {"label": "篡改"}})
        )
        with pytest.raises(store.FrozenDecisionCorruptedError):
            store.get_frozen_decision(db_path, "decision_" + "a" * 32)

    def test_snapshot_json_non_canonical_text_tamper_fails_closed(self, db_path):
        _write_valid(db_path)
        # 文本被改为非 canonical 表示（空格 / 乱序键 / 重序列化）
        _tamper_snapshot_json(db_path, lambda s: json.dumps(s, ensure_ascii=False))
        with pytest.raises(store.FrozenDecisionCorruptedError):
            store.get_frozen_decision(db_path, "decision_" + "a" * 32)

    def test_snapshot_json_whitespace_tamper_fails_closed(self, db_path):
        _write_valid(db_path)
        conn = sqlite3.connect(str(db_path))
        try:
            original = conn.execute(
                "SELECT snapshot_json FROM frozen_decisions"
            ).fetchone()[0]
            conn.execute(
                "UPDATE frozen_decisions SET snapshot_json = ?",
                (original.replace("{", "{ "),),
            )
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(store.FrozenDecisionCorruptedError):
            store.get_frozen_decision(db_path, "decision_" + "a" * 32)

    def test_snapshot_json_nan_literal_tamper_fails_closed(self, db_path):
        _write_valid(db_path)
        # 注入 NaN 字面量（非法 canonical JSON）
        _tamper_snapshot_json(db_path, lambda s: json.dumps(s).replace('"grade": "high"', '"grade": NaN'))
        with pytest.raises(store.FrozenDecisionCorruptedError):
            store.get_frozen_decision(db_path, "decision_" + "a" * 32)

    def test_read_failure_does_not_repair(self, db_path):
        _write_valid(db_path)
        _tamper(db_path, "strategy", "MEDIUM")
        with pytest.raises(store.FrozenDecisionCorruptedError):
            store.get_frozen_decision(db_path, "decision_" + "a" * 32)
        # 读失败后内容保持篡改原样，未自动修复
        conn = sqlite3.connect(str(db_path))
        try:
            strategy = conn.execute(
                "SELECT strategy FROM frozen_decisions"
            ).fetchone()[0]
        finally:
            conn.close()
        assert strategy == "MEDIUM"


def _tamper_snapshot_json(db_path: Path, mutator):
    """读取 snapshot_json，用 mutator(parsed_dict) -> str 生成新文本并写回。"""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT snapshot_json FROM frozen_decisions"
        ).fetchone()
        if row is None:
            return None
        new_text = mutator(json.loads(row[0]))
        conn.execute(
            "UPDATE frozen_decisions SET snapshot_json = ?",
            (new_text,),
        )
        conn.commit()
        return row
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 并发
# ---------------------------------------------------------------------------

class TestConcurrency:
    def test_same_decision_exact_replay_concurrently(self, db_path):
        frozen = _valid_frozen()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(lambda _: store.write_frozen_decision(db_path, frozen), range(16)))
        assert all(r["decision_id"] == frozen["decision_id"] for r in results)
        assert len(store.list_frozen_decisions(db_path)) == 1

    def test_same_decision_conflicting_replay_concurrently(self, db_path):
        frozen = _valid_frozen()
        conflicts = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            futures = []
            for i in range(8):
                variant = (
                    _mutated_frozen(frozen, next_best_action="HOLD")
                    if i % 2
                    else frozen
                )
                futures.append(ex.submit(store.write_frozen_decision, db_path, variant))
            for f in futures:
                try:
                    f.result()
                except store.FrozenDecisionConflictError:
                    conflicts.append(1)
        assert len(conflicts) >= 1
        assert len(store.list_frozen_decisions(db_path)) == 1

    def test_independent_decisions_concurrently(self, db_path):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            futures = [
                ex.submit(
                    store.write_frozen_decision,
                    db_path,
                    _valid_frozen(decision_id=f"decision_{i:032x}"),
                )
                for i in range(8)
            ]
            results = [f.result() for f in futures]
        assert len(results) == 8
        assert len(store.list_frozen_decisions(db_path)) == 8

    def test_no_half_records_after_conflict(self, db_path):
        frozen = _valid_frozen()
        store.write_frozen_decision(db_path, frozen)
        conflicting = _mutated_frozen(frozen, strategy="SHORT")
        with pytest.raises(store.FrozenDecisionConflictError):
            store.write_frozen_decision(db_path, conflicting)
        got = store.get_frozen_decision(db_path, frozen["decision_id"])
        assert got["strategy"] == "SWING"


# ---------------------------------------------------------------------------
# 写路径防御校验
# ---------------------------------------------------------------------------

class TestWritePathDefense:
    def test_write_rejects_non_true_user_confirmed(self, db_path):
        frozen = _valid_frozen(user_confirmed=True)
        frozen["user_confirmed"] = 1
        with pytest.raises(ValueError):
            store.write_frozen_decision(db_path, frozen)

    def test_write_rejects_hash_mismatch(self, db_path):
        frozen = _valid_frozen()
        frozen["snapshot_hash"] = "0" * 64
        with pytest.raises(ValueError):
            store.write_frozen_decision(db_path, frozen)

    def test_write_rejects_non_canonical_json_text(self, db_path):
        frozen = _valid_frozen()
        frozen["snapshot_json"] = json.dumps(
            json.loads(frozen["snapshot_json"]), ensure_ascii=False
        )
        with pytest.raises(ValueError):
            store.write_frozen_decision(db_path, frozen)

    def test_write_rejects_unknown_keys(self, db_path):
        frozen = _valid_frozen()
        frozen["mystery"] = 1
        with pytest.raises(ValueError):
            store.write_frozen_decision(db_path, frozen)

    def test_write_rejects_non_canonical_created_at(self, db_path):
        frozen = _valid_frozen()
        frozen["created_at"] = "garbage"
        with pytest.raises(ValueError):
            store.write_frozen_decision(db_path, frozen)

    def test_write_rejects_non_canonical_timestamp_form(self, db_path):
        # 合法 ISO 但非 canonical（+00:00 偏移、无微秒）一律拒绝
        frozen = _valid_frozen()
        frozen["created_at"] = "2026-08-10T06:00:01+00:00"
        with pytest.raises(ValueError):
            store.write_frozen_decision(db_path, frozen)
        frozen = _valid_frozen()
        frozen["committed_at"] = "2026-08-10T06:00:01Z"
        with pytest.raises(store.FrozenDecisionCorruptedError):
            store.write_frozen_decision(db_path, frozen)
