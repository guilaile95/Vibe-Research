"""Evidence Thesis Migration → Formal Lifecycle Black-Box Acceptance v0.1（P0-S2D-M-QA3）。

验证真实用户升级链条（全部黑盒，经真实 CLI subprocess / Service / API / 临时
SQLite）：
legacy v1 → normal open 严格拒绝且零修改 → explicit migrate → v2 正常读取 →
migrated legacy thesis 开始 Formal lifecycle → confirm → freeze →
rollback round-trip。

验收点（对应工作单 1–10）：
1  LEGACY NORMAL OPEN：v1 fixture readonly/open/initialize 全部拒绝且零修改
2  EXPLICIT MIGRATION CLI：python -m evidence_thesis_migration inspect/migrate
   黑盒验证 source→v2、backup→v1、digest/counts 一致
3  BACKUP IMMUTABILITY：迁移后 backup hash 始终不变（含 v2 读写 + Formal lifecycle 后）
4  MIGRATED LEGACY → FORMAL：migrated legacy thesis 走完整 formal lifecycle，
   LEGACY NULL HISTORY + VNEXT TYPED HISTORY 合法共存
5  MIGRATED DATA READABILITY：Evidence/Thesis/Revisions/Links 全部可读，
   archived thesis 可读、delta 表初始为空
6  NEW V2 WRITE AFTER MIGRATION：迁移后新 thesis revision 1 = CONTENT
7  EXPLICIT ROLLBACK：rollback --apply → v1 + legacy digest 一致 + backup 保留不变
8  SCRATCH / BACKUP COLLISION：reserved artifacts 预存在 → fail closed + bytes 保留
9  NO-APPLY：migrate/rollback 无 --apply → 非零 + source 不变 + backup 不创建
10 NO REAL USER DATA：所有 DB/backup/scratch 位于 pytest tmp_path

纪律：只新增本文件；不修改 production；发现 contract violation 保持 failing
regression 并报告 KNOWN_DEPENDENCY_BLOCKER / BLOCKING_PRODUCT_DEFECT，
不 xfail、不调用 migration 模块的 private helper 做伪验证。
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app as app_module
import evidence_thesis_service as svc
import evidence_thesis_store as store

client = TestClient(app_module.app)
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# 真实 v1 fixture（完整 DDL/索引/FK 与 migration 模块 V1 合同精确一致）
# ---------------------------------------------------------------------------

_V1_DDL = """
CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO schema_meta (key, value) VALUES ('schema_version', 'evidence_thesis_ledger_v1');
CREATE TABLE evidence_records (
    id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('stock','sector','theme')),
    subject_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    claim TEXT NOT NULL,
    source_title TEXT NOT NULL,
    source_url TEXT,
    source_date TEXT,
    accessed_at TEXT NOT NULL,
    classification TEXT NOT NULL CHECK (classification IN ('fact','inference','unknown')),
    confidence TEXT NOT NULL CHECK (confidence IN ('high','medium','low')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1)),
    deleted_at TEXT
);
CREATE TABLE investment_theses (
    id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('stock','sector','theme')),
    subject_id TEXT NOT NULL,
    market TEXT CHECK (market IN ('CN','HK','US','KR') OR market IS NULL),
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active','weakened','invalidated','archived')),
    core_claims TEXT NOT NULL,
    catalysts TEXT NOT NULL,
    risks TEXT NOT NULL,
    invalidation_conditions TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    current_revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE thesis_revisions (
    id TEXT PRIMARY KEY,
    thesis_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    snapshot TEXT NOT NULL,
    change_summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (thesis_id) REFERENCES investment_theses(id),
    UNIQUE (thesis_id, revision_number)
);
CREATE TABLE thesis_evidence_links (
    thesis_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    stance TEXT NOT NULL CHECK (stance IN ('support','oppose','neutral')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (thesis_id, evidence_id),
    FOREIGN KEY (thesis_id) REFERENCES investment_theses(id),
    FOREIGN KEY (evidence_id) REFERENCES evidence_records(id)
);
CREATE INDEX idx_evidence_subject ON evidence_records(subject_type, subject_id) WHERE deleted = 0;
CREATE INDEX idx_evidence_classification ON evidence_records(classification) WHERE deleted = 0;
CREATE INDEX idx_thesis_subject ON investment_theses(subject_type, subject_id);
CREATE INDEX idx_thesis_status ON investment_theses(status);
CREATE INDEX idx_revisions_thesis ON thesis_revisions(thesis_id, revision_number);
CREATE INDEX idx_links_evidence ON thesis_evidence_links(evidence_id);
"""

E1_ID = "e" * 31 + "1"  # 32-hex 形状
E2_ID = "e" * 31 + "2"
T1_ID = "t" * 31 + "1"
T2_ID = "t" * 31 + "2"
R1_1_ID = "r" * 31 + "1"  # t1 rev1
R2_1_ID = "r" * 31 + "2"  # t2 rev1

_T1_SNAPSHOT = {
    "thesis": {
        "id": T1_ID, "subject_type": "stock", "subject_id": "600519", "market": "CN",
        "title": "legacy-active", "summary": "s", "status": "active",
        "core_claims": ["claim-1", "claim-2", "claim-3"],
        "catalysts": ["cat-1"], "risks": ["risk-1"],
        "invalidation_conditions": ["inv-1"],
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
        "current_revision": 1,
    },
    "evidence_links": [
        {"evidence_id": E1_ID, "stance": "support", "claim": "support-evidence",
         "classification": "fact", "confidence": "high", "source_title": "src-e1"},
        {"evidence_id": E2_ID, "stance": "oppose", "claim": "oppose-evidence",
         "classification": "inference", "confidence": "medium", "source_title": "src-e2"},
    ],
}

_T2_SNAPSHOT = {
    "thesis": {
        "id": T2_ID, "subject_type": "stock", "subject_id": "000001", "market": "CN",
        "title": "legacy-archived", "summary": "s", "status": "archived",
        "core_claims": ["a1", "a2", "a3"],
        "catalysts": ["cat-2"], "risks": ["risk-2"],
        "invalidation_conditions": ["inv-2"],
        "created_at": "2026-01-02T00:00:00+00:00", "updated_at": "2026-01-02T00:00:00+00:00",
        "current_revision": 1,
    },
    "evidence_links": [],
}


def build_v1_db(path: Path) -> None:
    """创建精确的 legacy v1 fixture（含 2 evidence、2 thesis、2 revisions、2 links）。"""
    conn = sqlite3.connect(path)
    conn.executescript(_V1_DDL)
    conn.executemany(
        "INSERT INTO evidence_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (E1_ID, "stock", "600519", "news", "support-evidence", "src-e1",
             "https://example.com/e1", "2026-01-01", "2026-01-01T08:00:00+00:00",
             "fact", "high", "2026-01-01T08:00:00+00:00", "2026-01-01T08:00:00+00:00", 0, None),
            (E2_ID, "stock", "600519", "news", "oppose-evidence", "src-e2",
             "https://example.com/e2", "2026-01-01", "2026-01-01T09:00:00+00:00",
             "inference", "medium", "2026-01-01T09:00:00+00:00", "2026-01-01T09:00:00+00:00", 0, None),
        ],
    )
    conn.executemany(
        "INSERT INTO investment_theses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (T1_ID, "stock", "600519", "CN", "legacy-active", "s", "active",
             json.dumps(["claim-1", "claim-2", "claim-3"], ensure_ascii=False),
             json.dumps(["cat-1"], ensure_ascii=False), json.dumps(["risk-1"], ensure_ascii=False),
             json.dumps(["inv-1"], ensure_ascii=False), "2026-01-01T00:00:00+00:00",
             "2026-01-01T00:00:00+00:00", 1),
            (T2_ID, "stock", "000001", "CN", "legacy-archived", "s", "archived",
             json.dumps(["a1", "a2", "a3"], ensure_ascii=False),
             json.dumps(["cat-2"], ensure_ascii=False), json.dumps(["risk-2"], ensure_ascii=False),
             json.dumps(["inv-2"], ensure_ascii=False), "2026-01-02T00:00:00+00:00",
             "2026-01-02T00:00:00+00:00", 1),
        ],
    )
    conn.executemany(
        "INSERT INTO thesis_revisions VALUES (?,?,?,?,?,?)",
        [
            (R1_1_ID, T1_ID, 1, json.dumps(_T1_SNAPSHOT, ensure_ascii=False),
             "创建投资逻辑", "2026-01-01T00:00:00+00:00"),
            (R2_1_ID, T2_ID, 1, json.dumps(_T2_SNAPSHOT, ensure_ascii=False),
             "创建投资逻辑", "2026-01-02T00:00:00+00:00"),
        ],
    )
    conn.executemany(
        "INSERT INTO thesis_evidence_links VALUES (?,?,?,?,?)",
        [
            (T1_ID, E1_ID, "support", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            (T1_ID, E2_ID, "oppose", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        ],
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def env(tmp_path, monkeypatch):
    """每测试全新临时环境：所有 DB/backup/scratch 均在 tmp_path，显式防真实用户数据。

    ``e.db`` 即 API（svc.resolve_db_path → VIBE_RESEARCH_EVIDENCE_THESIS_DB）
    实际读取的路径：迁移目标与黑盒 API 读取目标必须一致。
    """
    ev_db = str(tmp_path / "evidence_thesis.db")
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", ev_db)
    monkeypatch.setenv("VIBE_RESEARCH_CAMPAIGN_DB", str(tmp_path / "campaigns.sqlite3"))
    e = SimpleNamespace(tmp=str(tmp_path), backend=BACKEND_DIR, db=ev_db)
    return e


@pytest.fixture()
def v1_db(env) -> SimpleNamespace:
    """真实 v1 fixture 数据库（就建在 API 读取路径上）+ 预迁移快照。"""
    build_v1_db(Path(env.db))
    return SimpleNamespace(db=env.db, before=_db_state(env.db))


def _assert_tmp_only(env, *paths: str) -> None:
    """防护：所有测试文件必须位于 tmp_path。"""
    tmp = os.path.abspath(env.tmp)
    for path in paths:
        p = os.path.abspath(path)
        assert tmp in p, f"path 不在 tmp_path: {p}"
        assert ".vibe-research" not in p, f"path 指向真实用户目录: {p}"


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def _sqlite_master(path: str) -> list:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()
    finally:
        conn.close()


def _schema_meta(path: str) -> list:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT key, value FROM schema_meta ORDER BY key").fetchall()
    finally:
        conn.close()


def _journal_mode(path: str) -> str:
    """只读查询 journal mode（不修改任何状态）。"""
    conn = sqlite3.connect(path)
    try:
        return str(conn.execute("PRAGMA journal_mode").fetchone()[0])
    finally:
        conn.close()


# ---- Migration-owned reserved scratch paths（backup / 任何公开操作均不得 alias）----
RESERVED_SCRATCH_SUFFIXES = (
    ".v2.candidate",
    ".v2.candidate-wal",
    ".v2.candidate-shm",
    ".restore.candidate",
    ".restore.candidate-wal",
    ".restore.candidate-shm",
    ".v2.recovery.candidate",
    ".v2.recovery.candidate-wal",
    ".v2.recovery.candidate-shm",
)


def _read_bytes(path: str) -> bytes | None:
    """文件存在 → bytes；否则 None。"""
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()


def _sidecar_state(path: str) -> dict:
    """source/backup 的 WAL/SHM 状态（存在性 + bytes）。"""
    return {ext: _read_bytes(path + ext) for ext in ("-wal", "-shm")}


def _scratch_inventory(db: str) -> dict:
    """db 的全部 reserved scratch paths 状态（bytes 或 None）。"""
    return {suffix: _read_bytes(db + suffix) for suffix in RESERVED_SCRATCH_SUFFIXES}


def _db_state(path: str) -> dict:
    return {
        "hash": _file_hash(path),
        "size": os.path.getsize(path),
        "master": _sqlite_master(path),
        "meta": _schema_meta(path),
        "journal": _journal_mode(path),
    }


def run_cli(env, *args: str) -> subprocess.CompletedProcess:
    """黑盒执行 ``python -m evidence_thesis_migration ...``（真实 subprocess）。"""
    env_copy = dict(os.environ)
    env_copy["PYTHONPATH"] = BACKEND_DIR + os.pathsep + env_copy.get("PYTHONPATH", "")
    env_copy["VR_DATA_DIR"] = env.tmp
    return subprocess.run(
        [sys.executable, "-m", "evidence_thesis_migration", *args],
        capture_output=True,
        text=True,
        env=env_copy,
        cwd=env.tmp,
        timeout=180,
    )


def cli_ok(proc: subprocess.CompletedProcess) -> dict:
    assert proc.returncode == 0, f"CLI failed rc={proc.returncode}: {proc.stderr}"
    return json.loads(proc.stdout)


def cli_fail(proc: subprocess.CompletedProcess) -> dict:
    assert proc.returncode != 0, f"CLI should have failed: {proc.stdout}"
    return json.loads(proc.stderr)


# API helpers（migrated v2 上的黑盒读取/formal lifecycle）
def _post(path: str, body: dict, expect: int = 200) -> dict:
    resp = client.post(path, json=body)
    assert resp.status_code == expect, f"{path} -> {resp.status_code}: {resp.text}"
    payload = resp.json()
    return payload.get("data", payload)


def _get(path: str, expect: int = 200) -> dict:
    resp = client.get(path)
    assert resp.status_code == expect, f"{path} -> {resp.status_code}: {resp.text}"
    payload = resp.json()
    return payload.get("data", payload)


def _put(path: str, body: dict, expect: int = 200) -> dict:
    resp = client.put(path, json=body)
    assert resp.status_code == expect, f"{path} -> {resp.status_code}: {resp.text}"
    payload = resp.json()
    return payload.get("data", payload)


# ---------------------------------------------------------------------------
# 1. LEGACY NORMAL OPEN
# ---------------------------------------------------------------------------

def test_1_legacy_normal_open_zero_mutation(v1_db, env, monkeypatch):
    """readonly service open 与 initialize_store 必须拒绝 v1 且全部状态零修改。

    expected：hash / size / sqlite_master / schema_meta / journal_mode 完全不变。
    若 Codex S2D-M-R1（NORMAL_OPEN_ZERO_MUTATION）未合入导致 hash 改变 → 保持
    failing regression，报告 KNOWN_DEPENDENCY_BLOCKER。
    """
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", v1_db.db)
    _assert_tmp_only(env, v1_db.db)

    # readonly service open → SchemaVersionError
    with pytest.raises(store.EvidenceLedgerSchemaVersionError):
        svc.list_thesis(v1_db.db)
    assert _db_state(v1_db.db) == v1_db.before

    # initialize_store → SchemaVersionError
    with pytest.raises(store.EvidenceLedgerSchemaVersionError):
        store.initialize_store(v1_db.db)
    assert _db_state(v1_db.db) == v1_db.before


# ---------------------------------------------------------------------------
# 2. EXPLICIT MIGRATION CLI
# ---------------------------------------------------------------------------

def test_2_explicit_migration_cli(v1_db, env):
    """黑盒：inspect v1 → migrate --apply → source v2 / backup v1 / digest/counts 一致。"""
    db, backup = v1_db.db, os.path.join(env.tmp, "backup_v1.db")
    _assert_tmp_only(env, db, backup)

    inspect_before = cli_ok(run_cli(env, "inspect", "--db", db))
    assert inspect_before["schema_version"] == "evidence_thesis_ledger_v1"

    migrated = cli_ok(run_cli(env, "migrate", "--db", db, "--backup", backup, "--apply"))
    assert migrated["operation"] == "migrate"
    assert migrated["status"] == "migrated"

    # source → v2
    inspect_source = cli_ok(run_cli(env, "inspect", "--db", db))
    assert inspect_source["schema_version"] == store.SCHEMA_VERSION
    assert inspect_source["digest"] == inspect_before["digest"]  # legacy payload 不变
    for table in ("evidence_records", "investment_theses", "thesis_revisions",
                  "thesis_evidence_links"):
        assert inspect_source["counts"][table] == inspect_before["counts"][table]

    # backup → v1
    inspect_backup = cli_ok(run_cli(env, "inspect", "--db", backup))
    assert inspect_backup["schema_version"] == "evidence_thesis_ledger_v1"
    assert inspect_backup["digest"] == inspect_before["digest"]


# ---------------------------------------------------------------------------
# 3. BACKUP IMMUTABILITY
# ---------------------------------------------------------------------------

def test_3_backup_immutable_through_v2_lifecycle(v1_db, env):
    """迁移后 backup hash 恒不变：v2 正常读写 + 完整 Formal lifecycle 之后仍不变。

    P2-1：使用 checked API helpers（带状态断言）走 begin/confirm/freeze，且必须
    断言 thesis 真 FROZEN（formal_state == frozen）后才声明 backup immutable。
    """
    db, backup = v1_db.db, os.path.join(env.tmp, "backup_v1.db")
    cli_ok(run_cli(env, "migrate", "--db", db, "--backup", backup, "--apply"))
    backup_hash0 = _file_hash(backup)

    # v2 正常读写（读取 migrated data）
    assert _get(f"/api/thesis/{T1_ID}")["thesis"]["id"] == T1_ID

    # Formal lifecycle（checked helpers：每步断言状态机推进）
    began = _post(f"/api/thesis/{T1_ID}/begin-formalization", {})
    assert began["thesis"]["formal_state"] == "draft"
    assert began["thesis"]["current_revision"] == 1  # begin NO bump
    edited = _put(f"/api/thesis/{T1_ID}", {
        "title": "legacy-active", "summary": "s", "status": "active",
        "core_claims": ["c1", "c2", "c3"], "catalysts": ["cat-1"], "risks": ["risk-1"],
        "invalidation_conditions": ["inv-1"], "expected_revision": 1,
        "strategy": "SWING",
        "expected_horizon": {"unit": "TRADING_DAY", "min": 5, "max": 20, "anchor": "FREEZE_AT"},
    })
    assert edited["thesis"]["current_revision"] == 2  # CONTENT bump
    confirmed = _post(f"/api/thesis/{T1_ID}/confirm", {})
    assert confirmed["thesis"]["formal_state"] == "confirmed"
    assert confirmed["thesis"]["current_revision"] == 2  # confirm NO bump
    frozen = _post(f"/api/thesis/{T1_ID}/freeze", {"expected_revision": 2})
    # 真 FROZEN 确认后才可声明 backup immutable
    assert frozen["thesis"]["formal_state"] == "frozen"
    assert frozen["thesis"]["frozen_revision"] == 3
    assert frozen["thesis"]["current_revision"] == 3

    assert _file_hash(backup) == backup_hash0  # BACKUP IMMUTABILITY（FROZEN 后）


# ---------------------------------------------------------------------------
# 4. MIGRATED LEGACY → FORMAL（LEGACY NULL HISTORY + VNEXT TYPED HISTORY 共存）
# ---------------------------------------------------------------------------

def test_4_migrated_legacy_formal_lifecycle(v1_db, env):
    """migrated legacy thesis：formal_state NULL → 完整 formal lifecycle。

    - begin → draft，NO revision bump
    - update draft（SWING / 5..20 / 3 claims）→ CONTENT revision
    - confirm → NO bump
    - freeze → N→N+1 FORMAL_FREEZE
    - 旧 revision_kind == NULL、新 revision == CONTENT、freeze == FORMAL_FREEZE
    """
    db, backup = v1_db.db, os.path.join(env.tmp, "backup_v1.db")
    cli_ok(run_cli(env, "migrate", "--db", db, "--backup", backup, "--apply"))

    # migrated legacy thesis：formal_state NULL
    agg = _get(f"/api/thesis/{T1_ID}")
    assert agg["thesis"]["formal_state"] is None
    assert agg["thesis"]["current_revision"] == 1
    # 旧 revision kind == NULL（v1 历史无 typed kind）
    old_rev = _get(f"/api/thesis/{T1_ID}/revisions/1")
    assert old_rev["revision_kind"] is None

    # begin → draft，NO bump
    began = _post(f"/api/thesis/{T1_ID}/begin-formalization", {})
    assert began["thesis"]["formal_state"] == "draft"
    assert began["thesis"]["current_revision"] == 1

    # draft edit → CONTENT revision 2
    edited = _put(f"/api/thesis/{T1_ID}", {
        "title": "legacy-active", "summary": "s", "status": "active",
        "core_claims": ["c1", "c2", "c3"], "catalysts": ["cat-1"], "risks": ["risk-1"],
        "invalidation_conditions": ["inv-1"], "expected_revision": 1,
        "strategy": "SWING",
        "expected_horizon": {"unit": "TRADING_DAY", "min": 5, "max": 20, "anchor": "FREEZE_AT"},
    })
    assert edited["thesis"]["current_revision"] == 2
    assert _get(f"/api/thesis/{T1_ID}/revisions/2")["revision_kind"] == "CONTENT"

    # confirm → NO bump
    confirmed = _post(f"/api/thesis/{T1_ID}/confirm", {})
    assert confirmed["thesis"]["formal_state"] == "confirmed"
    assert confirmed["thesis"]["current_revision"] == 2

    # freeze → N→N+1 FORMAL_FREEZE
    frozen = _post(f"/api/thesis/{T1_ID}/freeze", {"expected_revision": 2})
    assert frozen["thesis"]["formal_state"] == "frozen"
    assert frozen["thesis"]["frozen_revision"] == 3
    assert frozen["thesis"]["current_revision"] == 3
    assert _get(f"/api/thesis/{T1_ID}/revisions/3")["revision_kind"] == "FORMAL_FREEZE"

    # LEGACY NULL HISTORY + VNEXT TYPED HISTORY 合法共存
    revisions = _get(f"/api/thesis/{T1_ID}/revisions")
    kinds = {r["revision_number"]: _get(f"/api/thesis/{T1_ID}/revisions/{r['revision_number']}")["revision_kind"]
             for r in revisions["items"]}
    assert kinds == {1: None, 2: "CONTENT", 3: "FORMAL_FREEZE"}


# ---------------------------------------------------------------------------
# 5. MIGRATED DATA READABILITY
# ---------------------------------------------------------------------------

def test_5_migrated_data_readability(v1_db, env):
    """迁移后：Evidence / Thesis（含 archived）/ Revision history / Links 全部可读，
    delta tables 初始为空。"""
    db, backup = v1_db.db, os.path.join(env.tmp, "backup_v1.db")
    cli_ok(run_cli(env, "migrate", "--db", db, "--backup", backup, "--apply"))

    # Evidence 可读
    e1 = _get(f"/api/evidence/{E1_ID}")
    assert e1["claim"] == "support-evidence"
    e2 = _get(f"/api/evidence/{E2_ID}")
    assert e2["claim"] == "oppose-evidence"

    # Thesis 可读
    t1 = _get(f"/api/thesis/{T1_ID}")
    assert t1["thesis"]["status"] == "active"
    # archived legacy thesis 仍可读
    t2 = _get(f"/api/thesis/{T2_ID}")
    assert t2["thesis"]["status"] == "archived"
    assert t2["thesis"]["current_revision"] == 1

    # Revision history 可读（archived t2 亦含 1 条）
    assert _get(f"/api/thesis/{T1_ID}/revisions")["total"] == 1
    assert _get(f"/api/thesis/{T2_ID}/revisions")["total"] == 1

    # Evidence links 可读（t1 → e1 support / e2 oppose）
    links = {l["evidence_id"]: l["stance"] for l in t1["evidence_links"]}
    assert links == {E1_ID: "support", E2_ID: "oppose"}

    # Delta tables 初始为空
    assert _get(f"/api/thesis/{T1_ID}/deltas")["total"] == 0
    assert _get(f"/api/thesis/{T2_ID}/deltas")["total"] == 0


# ---------------------------------------------------------------------------
# 6. NEW V2 WRITE AFTER MIGRATION
# ---------------------------------------------------------------------------

def test_6_new_v2_write_revision1_content(v1_db, env):
    """迁移后创建新 thesis：revision 1 必须为 CONTENT（vNext write mode 生效）。"""
    db, backup = v1_db.db, os.path.join(env.tmp, "backup_v1.db")
    cli_ok(run_cli(env, "migrate", "--db", db, "--backup", backup, "--apply"))

    created = _post("/api/thesis", {
        "subject_type": "stock", "subject_id": "600519", "title": "v2-new",
        "summary": "s", "core_claims": ["c1", "c2", "c3"],
        "catalysts": ["c"], "risks": ["r"], "invalidation_conditions": ["i"],
    })
    thesis_id = created["thesis"]["id"]
    assert _get(f"/api/thesis/{thesis_id}/revisions/1")["revision_kind"] == "CONTENT"


# ---------------------------------------------------------------------------
# 7. EXPLICIT ROLLBACK
# ---------------------------------------------------------------------------

def test_7_explicit_rollback_round_trip(v1_db, env):
    """独立 fixture：migrate → rollback --apply → v1 + legacy digest 一致 + backup 保留不变。"""
    db, backup = v1_db.db, os.path.join(env.tmp, "backup_v1.db")
    inspect_before = cli_ok(run_cli(env, "inspect", "--db", db))

    cli_ok(run_cli(env, "migrate", "--db", db, "--backup", backup, "--apply"))
    backup_hash0 = _file_hash(backup)

    rolled = cli_ok(run_cli(env, "rollback", "--db", db, "--backup", backup, "--apply"))
    assert rolled["operation"] == "rollback"
    assert rolled["status"] == "rolled_back"

    # schema = v1
    inspect_after = cli_ok(run_cli(env, "inspect", "--db", db))
    assert inspect_after["schema_version"] == "evidence_thesis_ledger_v1"
    # legacy digest == 迁移前
    assert inspect_after["digest"] == inspect_before["digest"]
    assert inspect_after["counts"] == inspect_before["counts"]
    # backup 保留且 hash 不变
    assert os.path.isfile(backup)
    assert _file_hash(backup) == backup_hash0


# ---------------------------------------------------------------------------
# 8. SCRATCH / BACKUP COLLISION MATRIX（P1-1 黑盒，全部经 CLI public surface）
# ---------------------------------------------------------------------------

def _migrated_source(env) -> tuple[str, str]:
    db = os.path.join(env.tmp, "collision.db")
    build_v1_db(Path(db))
    backup = os.path.join(env.tmp, "collision_backup.db")
    cli_ok(run_cli(env, "migrate", "--db", db, "--backup", backup, "--apply"))
    return db, backup


def test_8_backup_equals_source_fails_closed(v1_db, env):
    """backup == source（--backup 与 --db 同路径）→ fail closed。"""
    db = v1_db.db
    proc = run_cli(env, "migrate", "--db", db, "--backup", db, "--apply")
    cli_fail(proc)
    # source 不变
    assert _db_state(db) == v1_db.before


@pytest.mark.parametrize("reserved_suffix", RESERVED_SCRATCH_SUFFIXES)
def test_8_backup_never_aliases_reserved_scratch_path(env, reserved_suffix):
    """P1-1：--backup 不得 alias 任何 migration-owned reserved scratch path。

    预放置 sentinel bytes 于目标 reserved path，然后以它为 backup 执行 migrate：
    - 命令必须 fail closed（绝不 false backup success）；
    - source 状态逐字节/结构不变；
    - 预存在 sentinel artifact 完整保留；
    - 无其他 scratch 被覆盖/删除。
    """
    db = os.path.join(env.tmp, f"alias_{reserved_suffix.replace('.', '_')}.db")
    build_v1_db(Path(db))
    backup = db + reserved_suffix
    sentinel = b"SENTINEL-" + reserved_suffix.encode()
    with open(backup, "wb") as fh:
        fh.write(sentinel)

    source_before = _db_state(db)
    scratch_before = _scratch_inventory(db)
    inventory_keys = [k for k in scratch_before if k != reserved_suffix]

    proc = run_cli(env, "migrate", "--db", db, "--backup", backup, "--apply")
    cli_fail(proc)

    # source 状态不变（hash/size/master/meta/journal）
    assert _db_state(db) == source_before
    # 预存在 sentinel 完整保留
    assert _read_bytes(backup) == sentinel, f"reserved artifact 被覆盖/删除: {reserved_suffix}"
    # 无其他 scratch 被覆盖/删除
    assert _scratch_inventory(db) == scratch_before
    for key in inventory_keys:
        assert _read_bytes(db + key) == scratch_before[key]


@pytest.mark.parametrize("reserved_suffix", RESERVED_SCRATCH_SUFFIXES)
def test_8_backup_never_aliases_reserved_scratch_path_clean(env, reserved_suffix):
    """P1-1：reserved path 不存在时 --backup 指向它也必须 fail closed 且零残留。

    防「检查路径是否预存在」被绕过：干净状态下 backup 指向 reserved path →
    不得创建任何文件（绝不 false backup success）。
    """
    db = os.path.join(env.tmp, f"alias_clean_{reserved_suffix.replace('.', '_')}.db")
    build_v1_db(Path(db))
    backup = db + reserved_suffix
    assert not os.path.exists(backup)

    source_before = _db_state(db)
    scratch_before = _scratch_inventory(db)

    proc = run_cli(env, "migrate", "--db", db, "--backup", backup, "--apply")
    cli_fail(proc)

    assert _db_state(db) == source_before
    assert not os.path.exists(backup), f"backup 在 reserved path 上被创建: {reserved_suffix}"
    assert _scratch_inventory(db) == scratch_before


def test_8_precreated_candidate_fails_closed_and_preserved(env):
    """P1-1：预创建 source.v2.candidate（含 bytes）→ migrate fail closed + bytes 保留。"""
    db = os.path.join(env.tmp, "collision2.db")
    build_v1_db(Path(db))
    backup = os.path.join(env.tmp, "collision2_backup.db")
    candidate = db + ".v2.candidate"
    sentinel = b"PRE-EXISTING-CANDIDATE-BYTES"
    with open(candidate, "wb") as fh:
        fh.write(sentinel)
    before_hash = _file_hash(db)

    proc = run_cli(env, "migrate", "--db", db, "--backup", backup, "--apply")
    cli_fail(proc)
    with open(candidate, "rb") as fh:
        assert fh.read() == sentinel, "预创建 candidate 被删除或覆盖"
    assert _file_hash(db) == before_hash  # source 不变


@pytest.mark.parametrize("sidecar_suffix", [".v2.candidate-wal", ".v2.candidate-shm"])
def test_8_precreated_candidate_sidecar_fails_closed(env, sidecar_suffix):
    """P2：预创建 candidate WAL/SHM sidecar → migrate 必须 fail closed 且零副作用。

    每个 sidecar 独立验证：
    - migrate fail closed（CLI 非零）
    - sentinel bytes 完整保留
    - source 状态不变（hash/size/master/meta/journal）
    - backup 不得被创建
    - 无关 scratch（其他 reserved paths）不变
    """
    db = os.path.join(env.tmp, f"collision3_{sidecar_suffix.replace('.', '_')}.db")
    build_v1_db(Path(db))
    backup = os.path.join(env.tmp, f"collision3_{sidecar_suffix.replace('.', '_')}_backup.db")
    sidecar = db + sidecar_suffix
    sentinel = b"SENTINEL-" + sidecar_suffix.encode()
    with open(sidecar, "wb") as fh:
        fh.write(sentinel)
    source_before = _db_state(db)
    scratch_before = _scratch_inventory(db)

    proc = run_cli(env, "migrate", "--db", db, "--backup", backup, "--apply")
    cli_fail(proc)
    # sentinel bytes 保留
    assert _read_bytes(sidecar) == sentinel, f"预创建 {sidecar_suffix} 被删除/覆盖"
    # source 状态不变
    assert _db_state(db) == source_before
    # backup 不得创建
    assert not os.path.exists(backup), "backup 不得被创建"
    # 无关 scratch 不变
    assert _scratch_inventory(db) == scratch_before


@pytest.mark.parametrize("sidecar_suffix", [
    ".restore.candidate-wal",
    ".restore.candidate-shm",
    ".v2.recovery.candidate-wal",
    ".v2.recovery.candidate-shm",
])
def test_8_precreated_rollback_sidecar_fails_closed(env, sidecar_suffix):
    """P1-1：rollback 时预存在 restore/recovery candidate 的 WAL/SHM sidecar
    → fail closed + bytes 保留 + source 保持 v2 未回滚 + backup 保留。

    当前 base（ce66881）对 restore.candidate-wal / recovery candidate-wal/-shm
    预存在不检查（会被吸收/删除）→ 预期 RED（KNOWN_DEPENDENCY_BLOCKER）。
    """
    db, backup = _migrated_source(env)
    sidecar = db + sidecar_suffix
    sentinel = b"SENTINEL-" + sidecar_suffix.encode()
    with open(sidecar, "wb") as fh:
        fh.write(sentinel)
    source_before = _db_state(db)
    backup_hash0 = _file_hash(backup)

    proc = run_cli(env, "rollback", "--db", db, "--backup", backup, "--apply")
    cli_fail(proc)

    assert _read_bytes(sidecar) == sentinel, f"预创建 sidecar 被删除/覆盖: {sidecar_suffix}"
    assert _db_state(db) == source_before  # 未回滚（保持 v2）
    assert _file_hash(backup) == backup_hash0  # backup 保留不变
    # source 仍为合法 v2
    inspect = cli_ok(run_cli(env, "inspect", "--db", db))
    assert inspect["schema_version"] == store.SCHEMA_VERSION


def test_8_precreated_recovery_candidate_fails_closed(env):
    """P1-1：预创建 source.v2.recovery.candidate → rollback fail closed + bytes 保留。"""
    db, backup = _migrated_source(env)
    recovery = db + ".v2.recovery.candidate"
    sentinel = b"PRE-EXISTING-RECOVERY-BYTES"
    with open(recovery, "wb") as fh:
        fh.write(sentinel)
    source_hash0 = _file_hash(db)

    proc = run_cli(env, "rollback", "--db", db, "--backup", backup, "--apply")
    cli_fail(proc)
    with open(recovery, "rb") as fh:
        assert fh.read() == sentinel, "预创建 recovery candidate 被删除或覆盖"
    assert _file_hash(db) == source_hash0  # source 未被破坏


def test_8_precreated_restore_candidate_fails_closed(env):
    """P1-1：预创建 source.restore.candidate → rollback fail closed + bytes 保留。"""
    db, backup = _migrated_source(env)
    restore = db + ".restore.candidate"
    sentinel = b"PRE-EXISTING-RESTORE-BYTES"
    with open(restore, "wb") as fh:
        fh.write(sentinel)

    proc = run_cli(env, "rollback", "--db", db, "--backup", backup, "--apply")
    cli_fail(proc)
    with open(restore, "rb") as fh:
        assert fh.read() == sentinel, "预创建 restore candidate 被删除或覆盖"
    # source 仍存在且为合法 v2（rollback 未成功）
    inspect = cli_ok(run_cli(env, "inspect", "--db", db))
    assert inspect["schema_version"] == store.SCHEMA_VERSION


# ---------------------------------------------------------------------------
# 9. NO-APPLY
# ---------------------------------------------------------------------------

def test_9_migrate_no_apply_does_nothing(v1_db, env):
    """migrate 无 --apply → 非零 + source hash 不变 + backup 不创建。"""
    db, backup = v1_db.db, os.path.join(env.tmp, "backup_never.db")
    proc = run_cli(env, "migrate", "--db", db, "--backup", backup)
    cli_fail(proc)
    assert _db_state(db) == v1_db.before
    assert not os.path.exists(backup)


def test_9_rollback_no_apply_does_nothing(v1_db, env):
    """P1-2：rollback 无 --apply → 非零，且前后完整状态零差异。

    捕获并对比：
    - source hash/size/schema_meta/sqlite_master/journal_mode
    - backup hash/size
    - source/backup 的 WAL/SHM 存在性 + bytes
    - reserved scratch inventory
    """
    db, backup = v1_db.db, os.path.join(env.tmp, "backup_v1.db")
    cli_ok(run_cli(env, "migrate", "--db", db, "--backup", backup, "--apply"))

    source_before = _db_state(db)
    backup_before = _db_state(backup)
    source_sidecars_before = _sidecar_state(db)
    backup_sidecars_before = _sidecar_state(backup)
    scratch_before = _scratch_inventory(db)

    proc = run_cli(env, "rollback", "--db", db, "--backup", backup)
    cli_fail(proc)

    # source：hash/size/master/meta/journal 完全不变（仍为 v2，未回滚）
    assert _db_state(db) == source_before
    # backup：hash/size 完全不变
    assert _db_state(backup) == backup_before
    # source/backup WAL/SHM 存在性 + bytes 不变
    assert _sidecar_state(db) == source_sidecars_before
    assert _sidecar_state(backup) == backup_sidecars_before
    # reserved scratch inventory 不变
    assert _scratch_inventory(db) == scratch_before


# ---------------------------------------------------------------------------
# 10. NO REAL USER DATA（防护断言已内嵌于各测试，此处显式覆盖 CLI scratch）
# ---------------------------------------------------------------------------

def test_10_all_artifacts_in_tmp(env, v1_db):  # noqa: ARG001
    """迁移产生的 source/backup 均位于 tmp_path；无真实用户路径痕迹。"""
    db, backup = v1_db.db, os.path.join(env.tmp, "backup_v1.db")
    _assert_tmp_only(env, db, backup)
    cli_ok(run_cli(env, "migrate", "--db", db, "--backup", backup, "--apply"))
    _assert_tmp_only(env, db, backup, backup + "-wal", backup + "-shm")
