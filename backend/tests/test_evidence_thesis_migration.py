"""Explicit evidence-thesis v1 -> vNext migration safety tests.

Every database used here lives below pytest's ``tmp_path``.  The suite never
resolves the application's default data directory and never opens a user DB.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import evidence_thesis_migration as migration
import evidence_thesis_store as store


V1 = store.LEGACY_SCHEMA_VERSION
V2 = store.SCHEMA_VERSION
TS = "2026-07-01T00:00:00+00:00"

V1_SCHEMA = """
CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE evidence_records (
    id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('stock','sector','theme')),
    subject_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL CHECK (evidence_type IN
      ('news','announcement','report','research_note','financial_filing','other')),
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
CREATE INDEX idx_evidence_subject ON evidence_records(subject_type, subject_id)
  WHERE deleted = 0;
CREATE INDEX idx_evidence_classification ON evidence_records(classification)
  WHERE deleted = 0;
CREATE INDEX idx_thesis_subject ON investment_theses(subject_type, subject_id);
CREATE INDEX idx_thesis_status ON investment_theses(status);
CREATE INDEX idx_revisions_thesis ON thesis_revisions(thesis_id, revision_number);
CREATE INDEX idx_links_evidence ON thesis_evidence_links(evidence_id);
"""

V1_TABLES = (
    "evidence_records",
    "investment_theses",
    "thesis_revisions",
    "thesis_evidence_links",
)

V1_COLUMNS = {
    "evidence_records": (
        "id", "subject_type", "subject_id", "evidence_type", "claim",
        "source_title", "source_url", "source_date", "accessed_at",
        "classification", "confidence", "created_at", "updated_at", "deleted",
        "deleted_at",
    ),
    "investment_theses": (
        "id", "subject_type", "subject_id", "market", "title", "summary",
        "status", "core_claims", "catalysts", "risks", "invalidation_conditions",
        "created_at", "updated_at", "current_revision",
    ),
    "thesis_revisions": (
        "id", "thesis_id", "revision_number", "snapshot", "change_summary",
        "created_at",
    ),
    "thesis_evidence_links": (
        "thesis_id", "evidence_id", "stance", "created_at", "updated_at",
    ),
}


def _id(prefix: str, number: int) -> str:
    return f"{prefix}{number:031d}"[-32:]


def _revision_id(thesis_id: str, revision: int) -> str:
    return hashlib.sha256(f"{thesis_id}:{revision}".encode()).hexdigest()[:32]


def _snapshot(thesis: dict, revision: int, links: list[dict]) -> str:
    current = dict(thesis)
    current["current_revision"] = revision
    for name in ("core_claims", "catalysts", "risks", "invalidation_conditions"):
        current[name] = json.loads(current[name])
    return json.dumps(
        {"thesis": current, "evidence_links": links},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _create_complex_v1(path: Path) -> Path:
    """Create an exact legacy schema with intentionally non-trivial history."""
    assert path.parent.name.startswith("test_") or "pytest-" in str(path.parent)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(V1_SCHEMA)
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)",
            (V1,),
        )

        evidence = [
            (_id("e", 1), "stock", "600519", "announcement", "营收增长", "三季报", "https://example.test/a", "2026-06-30", TS, "fact", "high", TS, TS, 0, None),
            (_id("e", 2), "stock", "600519", "report", "渠道库存上升", "渠道调研", None, None, TS, "inference", "medium", TS, TS, 0, None),
            (_id("e", 3), "stock", "600519", "news", "提价传闻", "市场消息", "https://example.test/c", "2026-06-28", TS, "unknown", "low", TS, TS, 1, "2026-07-02T00:00:00+00:00"),
            (_id("e", 4), "stock", "000001", "financial_filing", "息差承压", "年报", None, "2026-03-31", TS, "fact", "high", TS, TS, 0, None),
            (_id("e", 5), "sector", "semiconductor", "research_note", "设备国产化", "行业研究", None, None, TS, "inference", "medium", TS, TS, 0, None),
            (_id("e", 6), "theme", "ai-agent", "other", "商业模式未知", "内部笔记", None, None, TS, "unknown", "low", TS, TS, 0, None),
        ]
        conn.executemany(
            "INSERT INTO evidence_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            evidence,
        )

        thesis_specs = [
            (_id("t", 1), "stock", "600519", "CN", "白酒龙头", "现金流稳定", "active", 3),
            (_id("t", 2), "stock", "000001", "CN", "银行修复", "息差待验证", "weakened", 2),
            (_id("t", 3), "sector", "semiconductor", "CN", "国产替代", "周期反转", "invalidated", 3),
            (_id("t", 4), "theme", "ai-agent", None, "AI Agent", "商业化观察", "archived", 2),
        ]
        theses: dict[str, dict] = {}
        for tid, subject_type, subject_id, market, title, summary, status, rev in thesis_specs:
            row = {
                "id": tid,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "market": market,
                "title": title,
                "summary": summary,
                "status": status,
                "core_claims": json.dumps([f"{title}-核心"], ensure_ascii=False),
                "catalysts": json.dumps(["催化 A", "催化 B"], ensure_ascii=False),
                "risks": json.dumps(["风险 A"], ensure_ascii=False),
                "invalidation_conditions": json.dumps(["条件 A"], ensure_ascii=False),
                "created_at": TS,
                "updated_at": TS,
                "current_revision": rev,
            }
            theses[tid] = row
            conn.execute(
                "INSERT INTO investment_theses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                tuple(row.values()),
            )

        links = [
            (_id("t", 1), _id("e", 1), "support", TS, TS),
            (_id("t", 1), _id("e", 2), "oppose", TS, TS),
            (_id("t", 1), _id("e", 3), "neutral", TS, TS),
            (_id("t", 2), _id("e", 4), "oppose", TS, TS),
            (_id("t", 3), _id("e", 5), "support", TS, TS),
            (_id("t", 4), _id("e", 6), "neutral", TS, TS),
        ]
        conn.executemany(
            "INSERT INTO thesis_evidence_links VALUES (?,?,?,?,?)", links
        )

        evidence_by_id = {row[0]: row for row in evidence}
        links_by_thesis: dict[str, list[dict]] = {tid: [] for tid in theses}
        for tid, eid, stance, created_at, updated_at in links:
            ev = evidence_by_id[eid]
            links_by_thesis[tid].append(
                {
                    "evidence_id": eid,
                    "stance": stance,
                    "claim": ev[4],
                    "classification": ev[9],
                    "confidence": ev[10],
                    "source_title": ev[5],
                    "source_url": ev[6],
                    "source_date": ev[7],
                    "accessed_at": ev[8],
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
        for tid, thesis in theses.items():
            for revision in range(1, int(thesis["current_revision"]) + 1):
                conn.execute(
                    "INSERT INTO thesis_revisions VALUES (?,?,?,?,?,?)",
                    (
                        _revision_id(tid, revision),
                        tid,
                        revision,
                        _snapshot(thesis, revision, links_by_thesis[tid]),
                        f"legacy revision {revision}",
                        TS,
                    ),
                )
        conn.commit()
    finally:
        conn.close()
    return path


@pytest.fixture
def v1_db(tmp_path: Path) -> Path:
    return _create_complex_v1(tmp_path / "evidence_thesis.sqlite3")


@pytest.fixture(autouse=True)
def _guard_all_python_apply_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Make accidental real-path writes impossible in every in-process apply test."""
    originals = {
        "migrate_database": migration.migrate_database,
        "rollback_database": migration.rollback_database,
    }

    def _guard(name: str):
        original = originals[name]

        def guarded(db_path, *, backup_path=None, apply=False):
            if apply:
                assert backup_path is not None, "apply tests must pass explicit backup_path"
                _assert_only_tmp_paths([Path(db_path), Path(backup_path)], tmp_path)
            return original(db_path, backup_path=backup_path, apply=apply)

        return guarded

    monkeypatch.setattr(migration, "migrate_database", _guard("migrate_database"))
    monkeypatch.setattr(migration, "rollback_database", _guard("rollback_database"))


def _query_rows(path: Path, table: str, columns: tuple[str, ...]) -> list[list[object]]:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        quoted = ",".join(f'"{column}"' for column in columns)
        rows = conn.execute(f'SELECT {quoted} FROM "{table}"').fetchall()
        return sorted((list(row) for row in rows), key=lambda row: repr(row))
    finally:
        conn.close()


def _legacy_payload(path: Path) -> dict[str, list[list[object]]]:
    return {
        table: _query_rows(path, table, V1_COLUMNS[table]) for table in V1_TABLES
    }


def _legacy_digest(path: Path) -> str:
    encoded = json.dumps(
        _legacy_payload(path), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_state(paths: list[Path]) -> dict[Path, tuple[bool, bytes | None, int | None]]:
    return {
        path: (
            path.exists(),
            path.read_bytes() if path.is_file() else None,
            path.stat().st_mtime_ns if path.exists() else None,
        )
        for path in paths
    }


def _artifact_fingerprints(
    paths: list[Path],
) -> dict[Path, tuple[bool, str | None, int | None]]:
    return {
        path: (
            path.exists(),
            _file_sha256(path) if path.is_file() else None,
            path.stat().st_size if path.is_file() else None,
        )
        for path in paths
    }


def _normal_open_snapshot(path: Path) -> dict[str, object]:
    uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    try:
        sqlite_master = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "ORDER BY type, name"
        ).fetchall()
        schema_meta = conn.execute(
            "SELECT key, value FROM schema_meta ORDER BY key"
        ).fetchall()
        journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0])
    finally:
        conn.close()
    stat = path.stat()
    return {
        "file_sha256": _file_sha256(path),
        "file_size": stat.st_size,
        "sqlite_master": sqlite_master,
        "schema_meta": schema_meta,
        "journal_mode": journal_mode,
    }


def _assert_artifact_state(
    expected: dict[Path, tuple[bool, bytes | None, int | None]]
) -> None:
    for path, (existed, content, mtime_ns) in expected.items():
        assert path.exists() is existed, f"artifact existence changed: {path}"
        if existed:
            assert path.is_file(), f"artifact type changed: {path}"
            assert path.read_bytes() == content, f"artifact bytes changed: {path}"
            assert path.stat().st_mtime_ns == mtime_ns, f"artifact mtime changed: {path}"


def _scratch_paths(source: Path) -> dict[str, Path]:
    candidate = Path(f"{source}.v2.candidate")
    restore = Path(f"{source}.restore.candidate")
    recovery = Path(f"{source}.v2.recovery.candidate")
    return {
        "candidate": candidate,
        "candidate-wal": Path(f"{candidate}-wal"),
        "candidate-shm": Path(f"{candidate}-shm"),
        "restore": restore,
        "restore-wal": Path(f"{restore}-wal"),
        "restore-shm": Path(f"{restore}-shm"),
        "recovery": recovery,
        "recovery-wal": Path(f"{recovery}-wal"),
        "recovery-shm": Path(f"{recovery}-shm"),
    }


def _schema_version(path: Path) -> str:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        assert row is not None
        return str(row[0])
    finally:
        conn.close()


def _counts(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        names = (*V1_TABLES, "thesis_deltas", "thesis_delta_evidence_links")
        return {
            name: int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
            for name in names
        }
    finally:
        conn.close()


def _assert_unchanged(
    path: Path, sha: str, version: str = V1, mtime_ns: int | None = None
) -> None:
    assert path.is_file()
    assert _file_sha256(path) == sha
    assert _schema_version(path) == version
    if mtime_ns is not None:
        assert path.stat().st_mtime_ns == mtime_ns


def _assert_only_tmp_paths(paths: list[Path], tmp_path: Path) -> None:
    root = tmp_path.resolve()
    for path in paths:
        assert path.resolve().is_relative_to(root), f"unsafe test path: {path}"


def _run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "evidence_thesis_migration", *args]
    return subprocess.run(
        command,
        cwd=Path(__file__).parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _backup_path(path: Path) -> Path:
    return Path(f"{path}.v1.bak")


def _assert_no_candidate_artifacts(tmp_path: Path) -> None:
    leftovers = [
        path.name
        for path in tmp_path.iterdir()
        if "candidate" in path.name or path.name.endswith(".tmp")
    ]
    assert leftovers == []


def _raise_oserror(*_args, **_kwargs):
    raise OSError("injected migration stage failure")


def test_complex_v1_fixture_covers_required_legacy_shapes(v1_db: Path) -> None:
    payload = _legacy_payload(v1_db)
    assert {row[6] for row in payload["investment_theses"]} == {
        "active", "weakened", "invalidated", "archived"
    }
    assert {row[1] for row in payload["investment_theses"]} == {
        "stock", "sector", "theme"
    }
    assert {row[2] for row in payload["thesis_evidence_links"]} == {
        "support", "oppose", "neutral"
    }
    assert sum(row[13] for row in payload["evidence_records"]) == 1
    assert len(payload["thesis_revisions"]) == 10
    assert len(_legacy_digest(v1_db)) == 64


def test_migrate_complex_v1_preserves_data_digest_counts_and_backup(
    v1_db: Path, tmp_path: Path
) -> None:
    _assert_only_tmp_paths([v1_db, _backup_path(v1_db)], tmp_path)
    before_digest = _legacy_digest(v1_db)
    before_payload = _legacy_payload(v1_db)

    result = migration.migrate_database(
        v1_db, backup_path=_backup_path(v1_db), apply=True
    )

    backup = Path(result["backup_path"])
    assert backup == _backup_path(v1_db)
    assert _schema_version(v1_db) == V2
    assert _schema_version(backup) == V1
    assert _legacy_digest(v1_db) == before_digest
    assert _legacy_digest(backup) == before_digest
    assert _legacy_payload(v1_db) == before_payload
    assert _counts(v1_db) == {
        "evidence_records": 6,
        "investment_theses": 4,
        "thesis_revisions": 10,
        "thesis_evidence_links": 6,
        "thesis_deltas": 0,
        "thesis_delta_evidence_links": 0,
    }
    conn = sqlite3.connect(v1_db)
    conn.row_factory = sqlite3.Row
    try:
        thesis_rows = conn.execute("SELECT * FROM investment_theses").fetchall()
        revision_rows = conn.execute("SELECT * FROM thesis_revisions").fetchall()
        assert all(row["formal_state"] is None for row in thesis_rows)
        assert all(row["formalization_started_at"] is None for row in thesis_rows)
        assert all(row["strategy"] is None for row in thesis_rows)
        assert all(row["revision_kind"] is None for row in revision_rows)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()
    assert result["schema_version"] == V2
    assert result["digest"] == before_digest
    _assert_no_candidate_artifacts(tmp_path)


def test_inspect_unknown_version_is_read_only(v1_db: Path) -> None:
    conn = sqlite3.connect(v1_db)
    try:
        conn.execute(
            "UPDATE schema_meta SET value='evidence_thesis_ledger_v999' "
            "WHERE key='schema_version'"
        )
        conn.commit()
    finally:
        conn.close()
    sha = _file_sha256(v1_db)
    mtime = v1_db.stat().st_mtime_ns

    with pytest.raises(migration.ValidationError):
        migration.inspect_database(v1_db)

    _assert_unchanged(v1_db, sha, "evidence_thesis_ledger_v999", mtime)


def test_inspect_current_v2_is_read_only(tmp_path: Path) -> None:
    path = tmp_path / "current.sqlite3"
    store.initialize_store(path)
    sha = _file_sha256(path)
    mtime = path.stat().st_mtime_ns

    result = migration.inspect_database(path)

    assert result["schema_version"] == V2
    assert result["integrity_ok"] is True
    assert result["foreign_keys_ok"] is True
    _assert_unchanged(path, sha, V2, mtime)


def test_migrate_active_current_v2_family_rejects_before_report_with_zero_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "active-current-v2.sqlite3"
    backup = _backup_path(path)
    lock = migration._operation_lock_path(path)
    store.initialize_store(path)

    active = sqlite3.connect(path)
    try:
        active.execute("PRAGMA wal_autocheckpoint = 0")
        active.execute(
            "INSERT INTO evidence_records ("
            "id, subject_type, subject_id, evidence_type, claim, source_title, "
            "source_url, source_date, accessed_at, classification, confidence, "
            "created_at, updated_at, deleted, deleted_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                _id("e", 99), "stock", "600519", "news", "active wal fact",
                "active backend", None, None, TS, "fact", "high", TS, TS, 0, None,
            ),
        )
        active.commit()

        wal = Path(f"{path}-wal")
        shm = Path(f"{path}-shm")
        artifacts = [path, wal, shm, backup, lock]
        _assert_only_tmp_paths(artifacts, tmp_path)
        assert wal.is_file() and wal.stat().st_size > 0
        assert shm.is_file() and shm.stat().st_size > 0
        before_artifacts = _artifact_state(artifacts)
        before_fingerprints = _artifact_fingerprints(artifacts)

        def report_must_not_run(*_args, **_kwargs):
            pytest.fail("active SQLite family must be rejected before database report")

        monkeypatch.setattr(migration, "_database_report", report_must_not_run)

        with pytest.raises(migration.MigrationError):
            migration.migrate_database(path, backup_path=backup, apply=True)

        _assert_artifact_state(before_artifacts)
        assert _artifact_fingerprints(artifacts) == before_fingerprints
    finally:
        active.close()


@pytest.mark.parametrize(
    ("version", "expected_error"),
    [
        (V1, store.EvidenceLedgerSchemaVersionError),
        ("evidence_thesis_ledger_unknown", store.EvidenceLedgerSchemaVersionError),
        ("evidence_thesis_ledger_v999", store.EvidenceLedgerSchemaVersionError),
    ],
    ids=["legacy-v1", "unknown", "future"],
)
@pytest.mark.parametrize("open_kind", ["initialize", "read", "write"])
def test_normal_store_open_rejects_noncurrent_version_with_zero_mutation(
    tmp_path: Path,
    version: str,
    expected_error: type[Exception],
    open_kind: str,
) -> None:
    path = _create_complex_v1(tmp_path / f"{open_kind}-{version}.sqlite3")
    if version != V1:
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                "UPDATE schema_meta SET value=? WHERE key='schema_version'", (version,)
            )
            conn.commit()
        finally:
            conn.close()
    artifacts = [path, Path(f"{path}-wal"), Path(f"{path}-shm")]
    before = _artifact_state(artifacts)
    before_logical = _normal_open_snapshot(path)

    with pytest.raises(expected_error):
        if open_kind == "initialize":
            store.initialize_store(path)
        elif open_kind == "read":
            store.read_transaction(path, lambda _conn: None)
        else:
            store.write_transaction(path, lambda _conn: None)

    _assert_artifact_state(before)
    after_logical = _normal_open_snapshot(path)
    assert after_logical["file_sha256"] == before_logical["file_sha256"]
    assert after_logical["file_size"] == before_logical["file_size"]
    assert after_logical["sqlite_master"] == before_logical["sqlite_master"]
    assert after_logical["schema_meta"] == before_logical["schema_meta"]
    assert after_logical["journal_mode"] == before_logical["journal_mode"]


@pytest.mark.parametrize(
    "version",
    [V1, "evidence_thesis_ledger_unknown", "evidence_thesis_ledger_v999"],
    ids=["legacy-v1", "unknown", "future"],
)
@pytest.mark.parametrize("open_kind", ["initialize", "read", "write"])
def test_normal_store_open_wal_without_shm_rejects_version_with_zero_mutation(
    tmp_path: Path,
    version: str,
    open_kind: str,
) -> None:
    """A crash-tail WAL must not bypass or mutate the immutable main-file gate."""
    path = _create_complex_v1(tmp_path / f"wal-crash-{open_kind}-{version}.sqlite3")
    if version != V1:
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                "UPDATE schema_meta SET value=? WHERE key='schema_version'", (version,)
            )
            conn.commit()
        finally:
            conn.close()

    wal = Path(f"{path}-wal")
    shm = Path(f"{path}-shm")
    wal.write_bytes(b"non-empty simulated crash WAL\x00" + version.encode("utf-8"))
    shm.unlink(missing_ok=True)
    artifacts = [path, wal, shm]
    assert wal.stat().st_size > 0
    assert not shm.exists()
    before_artifacts = _artifact_state(artifacts)
    before_fingerprints = _artifact_fingerprints(artifacts)
    before_logical = _normal_open_snapshot(path)

    with pytest.raises(store.EvidenceLedgerSchemaVersionError):
        if open_kind == "initialize":
            store.initialize_store(path)
        elif open_kind == "read":
            store.read_transaction(path, lambda _conn: None)
        else:
            store.write_transaction(path, lambda _conn: None)

    _assert_artifact_state(before_artifacts)
    assert _artifact_fingerprints(artifacts) == before_fingerprints
    after_logical = _normal_open_snapshot(path)
    assert after_logical["file_sha256"] == before_logical["file_sha256"]
    assert after_logical["file_size"] == before_logical["file_size"]
    assert after_logical["sqlite_master"] == before_logical["sqlite_master"]
    assert after_logical["schema_meta"] == before_logical["schema_meta"]
    assert after_logical["journal_mode"] == before_logical["journal_mode"]


def test_corrupt_database_rejected_without_write(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.sqlite3"
    path.write_bytes(b"not a sqlite database\x00\xff")
    sha = _file_sha256(path)
    mtime = path.stat().st_mtime_ns

    with pytest.raises(migration.MigrationError):
        migration.inspect_database(path)

    assert _file_sha256(path) == sha
    assert path.stat().st_mtime_ns == mtime


@pytest.mark.parametrize(
    "drift_sql",
    [
        "ALTER TABLE evidence_records ADD COLUMN unrecognized TEXT",
        "CREATE TABLE unrecognized_table (id TEXT)",
        "INSERT INTO schema_meta(key, value) VALUES ('unexpected', 'row')",
        "CREATE INDEX unrecognized_index ON evidence_records(claim)",
        "DROP INDEX idx_links_evidence",
    ],
    ids=["extra-column", "extra-table", "extra-meta", "extra-index", "missing-index"],
)
def test_v1_schema_drift_rejected_before_backup(
    v1_db: Path, drift_sql: str
) -> None:
    conn = sqlite3.connect(v1_db)
    try:
        conn.execute(drift_sql)
        conn.commit()
    finally:
        conn.close()
    sha = _file_sha256(v1_db)
    mtime = v1_db.stat().st_mtime_ns

    with pytest.raises(migration.ValidationError):
        migration.migrate_database(
            v1_db, backup_path=_backup_path(v1_db), apply=True
        )

    _assert_unchanged(v1_db, sha, V1, mtime)
    assert not _backup_path(v1_db).exists()


def test_existing_backup_is_never_overwritten(v1_db: Path, tmp_path: Path) -> None:
    backup = _backup_path(v1_db)
    _assert_only_tmp_paths([v1_db, backup], tmp_path)
    backup.write_bytes(b"pre-existing user backup")
    source_sha = _file_sha256(v1_db)
    source_mtime = v1_db.stat().st_mtime_ns
    backup_sha = _file_sha256(backup)
    backup_mtime = backup.stat().st_mtime_ns

    with pytest.raises(migration.MigrationError):
        migration.migrate_database(v1_db, backup_path=backup, apply=True)

    _assert_unchanged(v1_db, source_sha, V1, source_mtime)
    assert _file_sha256(backup) == backup_sha
    assert backup.stat().st_mtime_ns == backup_mtime


def test_preexisting_operation_lock_fails_closed_without_touching_any_artifact(
    v1_db: Path, tmp_path: Path
) -> None:
    backup = _backup_path(v1_db)
    lock = migration._operation_lock_path(v1_db)
    lock.write_bytes(b"preexisting-operation-lock")
    guarded = [v1_db, backup, lock, *_scratch_paths(v1_db).values()]
    _assert_only_tmp_paths(guarded, tmp_path)
    before = _artifact_state(guarded)

    with pytest.raises(migration.MigrationError):
        migration.migrate_database(v1_db, backup_path=backup, apply=True)

    _assert_artifact_state(before)


def test_concurrent_same_source_migrate_loser_never_enters_write_or_deletes_winner(
    v1_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    winner_backup = _backup_path(v1_db)
    loser_backup = tmp_path / "loser.v1.bak"
    lock_path = migration._operation_lock_path(v1_db)
    scratch = _scratch_paths(v1_db)
    _assert_only_tmp_paths(
        [v1_db, winner_backup, loser_backup, lock_path, *scratch.values()], tmp_path
    )

    entered_copy = threading.Event()
    release_winner = threading.Event()
    counter_guard = threading.Lock()
    locked_entries = 0
    original_locked = migration._migrate_database_locked
    original_copy = migration._copy_legacy_tables

    def count_locked_entry(source: Path, backup: Path, paths: dict[str, Path]):
        nonlocal locked_entries
        with counter_guard:
            locked_entries += 1
        return original_locked(source, backup, paths)

    def block_winner_copy(source: Path, candidate: Path) -> None:
        entered_copy.set()
        if not release_winner.wait(timeout=10):
            raise TimeoutError("test did not release winner migration")
        original_copy(source, candidate)

    monkeypatch.setattr(migration, "_migrate_database_locked", count_locked_entry)
    monkeypatch.setattr(migration, "_copy_legacy_tables", block_winner_copy)

    winner_result: dict[str, object] = {}
    winner_errors: list[BaseException] = []

    def run_winner() -> None:
        try:
            winner_result.update(
                migration.migrate_database(
                    v1_db, backup_path=winner_backup, apply=True
                )
            )
        except BaseException as exc:  # noqa: BLE001 - captured from worker thread
            winner_errors.append(exc)

    winner = threading.Thread(target=run_winner, name="migration-winner")
    winner.start()
    assert entered_copy.wait(timeout=10), "winner did not reach its write stage"

    guarded_during_winner = [
        v1_db,
        winner_backup,
        loser_backup,
        lock_path,
        *scratch.values(),
    ]
    during_winner = _artifact_state(guarded_during_winner)
    assert during_winner[lock_path][0] is True
    assert during_winner[scratch["candidate"]][0] is True
    assert during_winner[winner_backup][0] is True

    try:
        with pytest.raises(migration.MigrationError):
            migration.migrate_database(
                v1_db, backup_path=loser_backup, apply=True
            )
        _assert_artifact_state(during_winner)
        assert locked_entries == 1
    finally:
        release_winner.set()
        winner.join(timeout=15)

    assert not winner.is_alive(), "winner migration thread did not finish"
    assert winner_errors == []
    assert winner_result["status"] == "migrated"
    assert locked_entries == 1
    assert _schema_version(v1_db) == V2
    assert _schema_version(winner_backup) == V1
    assert not loser_backup.exists()
    assert not lock_path.exists()
    for artifact in scratch.values():
        assert not artifact.exists()


@pytest.mark.parametrize(
    "backup_alias", ["main", "candidate", "candidate-wal", "candidate-shm"]
)
def test_migrate_rejects_backup_aliasing_main_or_reserved_candidate_namespace(
    v1_db: Path, tmp_path: Path, backup_alias: str
) -> None:
    scratch = _scratch_paths(v1_db)
    backup = v1_db if backup_alias == "main" else scratch[backup_alias]
    guarded = [v1_db, *scratch.values()]
    _assert_only_tmp_paths([backup, *guarded], tmp_path)
    before = _artifact_state(guarded)

    with pytest.raises(migration.MigrationError):
        migration.migrate_database(v1_db, backup_path=backup, apply=True)

    _assert_artifact_state(before)


@pytest.mark.parametrize("artifact_name", ["candidate-wal", "candidate-shm"])
def test_migrate_preserves_preexisting_candidate_sidecar_bytes_on_refusal(
    v1_db: Path, tmp_path: Path, artifact_name: str
) -> None:
    backup = _backup_path(v1_db)
    scratch = _scratch_paths(v1_db)
    artifact = scratch[artifact_name]
    sentinel = f"preexisting-{artifact_name}".encode()
    artifact.write_bytes(sentinel)
    guarded = [v1_db, backup, *scratch.values()]
    _assert_only_tmp_paths(guarded, tmp_path)
    before = _artifact_state(guarded)

    with pytest.raises(migration.MigrationError):
        migration.migrate_database(v1_db, backup_path=backup, apply=True)

    _assert_artifact_state(before)


@pytest.mark.parametrize(
    "seam",
    ["_create_backup", "_copy_legacy_tables", "_validate_candidate"],
)
def test_pre_swap_stage_failure_leaves_source_unchanged_and_cleans_candidate(
    v1_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seam: str
) -> None:
    _assert_only_tmp_paths([v1_db, _backup_path(v1_db)], tmp_path)
    sha = _file_sha256(v1_db)
    mtime = v1_db.stat().st_mtime_ns
    digest = _legacy_digest(v1_db)
    monkeypatch.setattr(migration, seam, _raise_oserror)

    with pytest.raises(migration.MigrationError):
        migration.migrate_database(
            v1_db, backup_path=_backup_path(v1_db), apply=True
        )

    _assert_unchanged(v1_db, sha, V1, mtime)
    assert _legacy_digest(v1_db) == digest
    _assert_no_candidate_artifacts(tmp_path)
    if seam == "_create_backup":
        assert not _backup_path(v1_db).exists()


def test_atomic_swap_failure_keeps_or_restores_original(
    v1_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_only_tmp_paths([v1_db, _backup_path(v1_db)], tmp_path)
    sha = _file_sha256(v1_db)
    digest = _legacy_digest(v1_db)
    monkeypatch.setattr(migration, "_atomic_swap", _raise_oserror)

    with pytest.raises(migration.MigrationError):
        migration.migrate_database(
            v1_db, backup_path=_backup_path(v1_db), apply=True
        )

    _assert_unchanged(v1_db, sha)
    assert _legacy_digest(v1_db) == digest
    assert _schema_version(_backup_path(v1_db)) == V1
    _assert_no_candidate_artifacts(tmp_path)


def test_candidate_validation_failure_cleans_candidate_wal_and_shm(
    v1_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_sha = _file_sha256(v1_db)

    def fail_with_sidecars(candidate: Path, _expected: dict) -> None:
        Path(f"{candidate}-wal").write_bytes(b"injected wal")
        Path(f"{candidate}-shm").write_bytes(b"injected shm")
        raise migration.ValidationError("injected candidate validation failure")

    monkeypatch.setattr(migration, "_validate_candidate", fail_with_sidecars)

    with pytest.raises(migration.ValidationError):
        migration.migrate_database(
            v1_db, backup_path=_backup_path(v1_db), apply=True
        )

    _assert_unchanged(v1_db, source_sha)
    _assert_no_candidate_artifacts(tmp_path)


def test_pre_swap_source_recheck_rejects_concurrent_source_drift(
    v1_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before_digest = _legacy_digest(v1_db)
    original_recheck = migration._pre_swap_recheck

    def drift_then_recheck(source: Path, expected: dict) -> None:
        conn = sqlite3.connect(source)
        try:
            conn.execute(
                "UPDATE evidence_records SET claim='concurrent source edit' WHERE id=?",
                (_id("e", 1),),
            )
            conn.commit()
        finally:
            conn.close()
        original_recheck(source, expected)

    monkeypatch.setattr(migration, "_pre_swap_recheck", drift_then_recheck)

    with pytest.raises(migration.ValidationError):
        migration.migrate_database(
            v1_db, backup_path=_backup_path(v1_db), apply=True
        )

    assert _schema_version(v1_db) == V1
    assert _legacy_digest(v1_db) != before_digest
    assert _legacy_digest(_backup_path(v1_db)) == before_digest
    assert _query_rows(v1_db, "evidence_records", ("claim",))[0] is not None
    _assert_no_candidate_artifacts(tmp_path)


def test_post_swap_validation_failure_rolls_back_from_verified_backup(
    v1_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_only_tmp_paths([v1_db, _backup_path(v1_db)], tmp_path)
    before_digest = _legacy_digest(v1_db)
    before_counts = {table: len(rows) for table, rows in _legacy_payload(v1_db).items()}
    monkeypatch.setattr(migration, "_post_swap_validate", _raise_oserror)

    with pytest.raises(migration.MigrationError):
        migration.migrate_database(
            v1_db, backup_path=_backup_path(v1_db), apply=True
        )

    assert _schema_version(v1_db) == V1
    assert _legacy_digest(v1_db) == before_digest
    assert {
        table: len(rows) for table, rows in _legacy_payload(v1_db).items()
    } == before_counts
    assert _schema_version(_backup_path(v1_db)) == V1
    _assert_no_candidate_artifacts(tmp_path)


def test_rollback_rejects_corrupt_backup_without_touching_v2(
    v1_db: Path, tmp_path: Path
) -> None:
    migration.migrate_database(
        v1_db, backup_path=_backup_path(v1_db), apply=True
    )
    backup = _backup_path(v1_db)
    _assert_only_tmp_paths([v1_db, backup], tmp_path)
    backup.write_bytes(b"corrupt backup")
    source_sha = _file_sha256(v1_db)
    source_mtime = v1_db.stat().st_mtime_ns

    with pytest.raises(migration.MigrationError):
        migration.rollback_database(v1_db, backup_path=backup, apply=True)

    _assert_unchanged(v1_db, source_sha, V2, source_mtime)


def test_rollback_rejects_wrong_version_backup_without_touching_v2(
    v1_db: Path, tmp_path: Path
) -> None:
    migration.migrate_database(
        v1_db, backup_path=_backup_path(v1_db), apply=True
    )
    backup = _backup_path(v1_db)
    backup.unlink()
    store.initialize_store(backup)
    _assert_only_tmp_paths([v1_db, backup], tmp_path)
    source_sha = _file_sha256(v1_db)
    source_mtime = v1_db.stat().st_mtime_ns

    with pytest.raises(migration.ValidationError):
        migration.rollback_database(v1_db, backup_path=backup, apply=True)

    _assert_unchanged(v1_db, source_sha, V2, source_mtime)


def test_rerun_migration_on_v2_is_already_current_without_overwriting_backup(
    v1_db: Path, tmp_path: Path
) -> None:
    migration.migrate_database(
        v1_db, backup_path=_backup_path(v1_db), apply=True
    )
    backup = _backup_path(v1_db)
    _assert_only_tmp_paths([v1_db, backup], tmp_path)
    source_sha = _file_sha256(v1_db)
    source_mtime = v1_db.stat().st_mtime_ns
    backup_sha = _file_sha256(backup)
    backup_mtime = backup.stat().st_mtime_ns

    result = migration.migrate_database(v1_db, backup_path=backup, apply=True)

    assert result["status"] == "already_current"
    assert result["schema_version"] == V2
    _assert_unchanged(v1_db, source_sha, V2, source_mtime)
    assert _file_sha256(backup) == backup_sha
    assert backup.stat().st_mtime_ns == backup_mtime


@pytest.mark.parametrize(
    "artifact_name",
    [
        "restore", "restore-wal", "restore-shm",
        "recovery", "recovery-wal", "recovery-shm",
    ],
)
def test_rollback_rejects_reserved_restore_or_recovery_artifact_conflict_without_write(
    v1_db: Path,
    tmp_path: Path,
    artifact_name: str,
) -> None:
    backup = _backup_path(v1_db)
    migration.migrate_database(v1_db, backup_path=backup, apply=True)
    scratch = _scratch_paths(v1_db)
    artifact = scratch[artifact_name]
    artifact.write_bytes(f"preexisting-{artifact_name}".encode())
    guarded = [v1_db, backup, *scratch.values()]
    _assert_only_tmp_paths(guarded, tmp_path)
    before = _artifact_state(guarded)

    with pytest.raises(migration.MigrationError):
        migration.rollback_database(v1_db, backup_path=backup, apply=True)

    _assert_artifact_state(before)


def test_python_api_requires_explicit_apply_for_migrate_and_rollback(
    v1_db: Path
) -> None:
    sha = _file_sha256(v1_db)
    mtime = v1_db.stat().st_mtime_ns
    with pytest.raises(migration.ApplyRequiredError):
        migration.migrate_database(v1_db, backup_path=_backup_path(v1_db))
    _assert_unchanged(v1_db, sha, V1, mtime)
    assert not _backup_path(v1_db).exists()

    migration.migrate_database(
        v1_db, backup_path=_backup_path(v1_db), apply=True
    )
    v2_sha = _file_sha256(v1_db)
    v2_mtime = v1_db.stat().st_mtime_ns
    with pytest.raises(migration.ApplyRequiredError):
        migration.rollback_database(v1_db, backup_path=_backup_path(v1_db))
    _assert_unchanged(v1_db, v2_sha, V2, v2_mtime)


def test_cli_migrate_without_apply_is_nonzero_and_writes_nothing(
    v1_db: Path, tmp_path: Path
) -> None:
    _assert_only_tmp_paths([v1_db, _backup_path(v1_db)], tmp_path)
    sha = _file_sha256(v1_db)
    mtime = v1_db.stat().st_mtime_ns

    completed = _run_cli(
        "migrate", "--db", str(v1_db), "--backup", str(_backup_path(v1_db))
    )

    assert completed.returncode != 0
    _assert_unchanged(v1_db, sha, V1, mtime)
    assert not _backup_path(v1_db).exists()


def test_cli_explicit_inspect_migrate_and_rollback_round_trip(
    v1_db: Path, tmp_path: Path
) -> None:
    backup = _backup_path(v1_db)
    _assert_only_tmp_paths([v1_db, backup], tmp_path)
    before_digest = _legacy_digest(v1_db)

    inspected = _run_cli("inspect", "--db", str(v1_db))
    assert inspected.returncode == 0, inspected.stderr
    assert json.loads(inspected.stdout)["schema_version"] == V1
    assert _schema_version(v1_db) == V1

    migrated = _run_cli(
        "migrate",
        "--db", str(v1_db),
        "--backup", str(backup),
        "--apply",
    )
    assert migrated.returncode == 0, migrated.stderr
    assert json.loads(migrated.stdout)["status"] == "migrated"
    assert _schema_version(v1_db) == V2
    assert _legacy_digest(v1_db) == before_digest

    rolled_back = _run_cli(
        "rollback",
        "--db", str(v1_db),
        "--backup", str(backup),
        "--apply",
    )
    assert rolled_back.returncode == 0, rolled_back.stderr
    assert json.loads(rolled_back.stdout)["status"] == "rolled_back"
    assert _schema_version(v1_db) == V1
    assert _legacy_digest(v1_db) == before_digest


def test_cli_without_db_argument_refuses_and_never_uses_environment_default(
    tmp_path: Path,
) -> None:
    would_be_default = tmp_path / "must-not-be-created.sqlite3"
    env = os.environ.copy()
    env["VIBE_RESEARCH_EVIDENCE_THESIS_DB"] = str(would_be_default)
    env["VR_DATA_DIR"] = str(tmp_path / "also-must-not-be-used")

    completed = _run_cli("migrate", "--apply", env=env)

    assert completed.returncode != 0
    assert not would_be_default.exists()
    assert not (tmp_path / "also-must-not-be-used").exists()
