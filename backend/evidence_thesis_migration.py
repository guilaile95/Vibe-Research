"""Explicit, offline evidence-thesis v1 -> vNext migration tool.

This module deliberately has no database default and is never called by normal
store initialization.  Mutating operations require ``apply=True`` (or
``--apply`` on the CLI).  Migration is COPY -> VALIDATE -> ATOMIC SWAP; the
original v1 file is retained as a non-overwriting SQLite backup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterator

import evidence_thesis_service as service
import evidence_thesis_store as store


LEGACY_TABLES = (
    "evidence_records",
    "investment_theses",
    "thesis_revisions",
    "thesis_evidence_links",
)

LEGACY_COLUMNS: dict[str, tuple[str, ...]] = {
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

V2_COLUMNS: dict[str, tuple[str, ...]] = {
    "schema_meta": ("key", "value"),
    **LEGACY_COLUMNS,
    "investment_theses": LEGACY_COLUMNS["investment_theses"] + (
        "formal_state", "formalization_started_at", "strategy",
        "expected_horizon", "free_notes", "confirmed_at", "frozen_at",
        "frozen_revision", "archived_at",
    ),
    "thesis_revisions": LEGACY_COLUMNS["thesis_revisions"] + ("revision_kind",),
    "thesis_deltas": (
        "delta_id", "thesis_id", "delta_sequence", "base_revision",
        "delta_state", "reason", "confirmed_at",
    ),
    "thesis_delta_evidence_links": (
        "delta_id", "evidence_id", "evidence_type", "claim",
        "classification", "confidence", "source_title", "source_url",
        "source_date", "accessed_at", "stance", "captured_at",
    ),
}

V1_COLUMNS: dict[str, tuple[str, ...]] = {
    "schema_meta": ("key", "value"),
    **LEGACY_COLUMNS,
}

V1_NAMED_INDEXES = {
    "idx_evidence_subject",
    "idx_evidence_classification",
    "idx_thesis_subject",
    "idx_thesis_status",
    "idx_revisions_thesis",
    "idx_links_evidence",
}
V2_NAMED_INDEXES = V1_NAMED_INDEXES | {"idx_deltas_thesis"}

V1_INDEX_LAYOUT = {
    "idx_evidence_subject": ("evidence_records", ("subject_type", "subject_id"), False, True),
    "idx_evidence_classification": ("evidence_records", ("classification",), False, True),
    "idx_thesis_subject": ("investment_theses", ("subject_type", "subject_id"), False, False),
    "idx_thesis_status": ("investment_theses", ("status",), False, False),
    "idx_revisions_thesis": ("thesis_revisions", ("thesis_id", "revision_number"), False, False),
    "idx_links_evidence": ("thesis_evidence_links", ("evidence_id",), False, False),
}
V2_INDEX_LAYOUT = {
    **V1_INDEX_LAYOUT,
    "idx_deltas_thesis": ("thesis_deltas", ("thesis_id", "delta_sequence"), False, False),
}

V1_FOREIGN_KEYS = {
    "schema_meta": set(),
    "evidence_records": set(),
    "investment_theses": set(),
    "thesis_revisions": {("thesis_id", "investment_theses", "id")},
    "thesis_evidence_links": {
        ("thesis_id", "investment_theses", "id"),
        ("evidence_id", "evidence_records", "id"),
    },
}
V2_FOREIGN_KEYS = {
    **V1_FOREIGN_KEYS,
    "thesis_deltas": {("thesis_id", "investment_theses", "id")},
    "thesis_delta_evidence_links": {("delta_id", "thesis_deltas", "delta_id")},
}

V2_FORMAL_COLUMNS = (
    "formal_state",
    "formalization_started_at",
    "strategy",
    "expected_horizon",
    "free_notes",
    "confirmed_at",
    "frozen_at",
    "frozen_revision",
    "archived_at",
)


class MigrationError(RuntimeError):
    """Base class for an explicit migration failure."""


class ApplyRequiredError(MigrationError):
    """A mutating operation was requested without explicit authorization."""


class UnsafeDatabasePathError(MigrationError):
    """The supplied path cannot be used as an on-disk migration target."""


class ValidationError(MigrationError):
    """A source, candidate, backup, or post-swap database failed validation."""


def _normalized_db_path(db_path: str | Path) -> Path:
    if not isinstance(db_path, (str, Path)):
        raise UnsafeDatabasePathError("db_path must be a string or Path")
    raw = str(db_path).strip()
    if not raw or raw == ":memory:":
        raise UnsafeDatabasePathError("an explicit on-disk db_path is required")
    path = Path(raw).expanduser().resolve(strict=False)
    if path.name in ("", ".", ".."):
        raise UnsafeDatabasePathError("db_path must name a database file")
    return path


def _require_apply(apply: bool) -> None:
    if apply is not True:
        raise ApplyRequiredError("mutating migration commands require --apply")


def _readonly_connection(path: Path) -> sqlite3.Connection:
    """Open a read-only snapshot without creating SQLite sidecars.

    A non-empty WAL is readable only when the existing SHM is present.  With no
    WAL, immutable mode prevents SQLite from creating or changing any sidecar.
    """
    if not path.is_file():
        raise ValidationError(f"database does not exist: {path}")
    wal_path = Path(str(path) + "-wal")
    shm_path = Path(str(path) + "-shm")
    wal_nonempty = wal_path.is_file() and wal_path.stat().st_size > 0
    if wal_nonempty and not shm_path.is_file():
        raise ValidationError("non-empty WAL without SHM cannot be inspected safely")
    suffix = "?mode=ro" if wal_nonempty else "?mode=ro&immutable=1"
    try:
        conn = sqlite3.connect(f"{path.as_uri()}{suffix}", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn
    except sqlite3.Error as exc:
        raise ValidationError(f"cannot open database read-only: {type(exc).__name__}") from exc


def _column_names(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
    try:
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    except sqlite3.Error as exc:
        raise ValidationError(f"cannot inspect table {table}") from exc
    return tuple(str(row[1]) for row in rows)


def _schema_version(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.Error as exc:
        raise ValidationError("schema_meta is missing or unreadable") from exc
    if row is None or not isinstance(row[0], str) or not row[0]:
        raise ValidationError("schema_version is missing")
    return str(row[0])


def _legacy_payload(conn: sqlite3.Connection) -> dict[str, list[list[Any]]]:
    payload: dict[str, list[list[Any]]] = {}
    for table in LEGACY_TABLES:
        columns = LEGACY_COLUMNS[table]
        quoted = ",".join(f'"{name}"' for name in columns)
        try:
            rows = conn.execute(f'SELECT {quoted} FROM "{table}"').fetchall()
        except sqlite3.Error as exc:
            raise ValidationError(f"legacy table {table} is unreadable") from exc
        values = [list(row) for row in rows]
        payload[table] = sorted(values, key=repr)
    return payload


def _payload_digest(payload: dict[str, list[list[Any]]]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _database_report(path: Path, *, expected_version: str | None = None) -> dict[str, Any]:
    conn = _readonly_connection(path)
    try:
        try:
            integrity_row = conn.execute("PRAGMA integrity_check").fetchone()
            integrity_ok = integrity_row is not None and integrity_row[0] == "ok"
            fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        except sqlite3.Error as exc:
            raise ValidationError("SQLite integrity validation failed") from exc
        if not integrity_ok:
            raise ValidationError("PRAGMA integrity_check failed")
        if fk_rows:
            raise ValidationError("PRAGMA foreign_key_check failed")

        version = _schema_version(conn)
        if version not in (store.LEGACY_SCHEMA_VERSION, store.SCHEMA_VERSION):
            raise ValidationError(f"unsupported schema version: {version}")
        if expected_version is not None and version != expected_version:
            raise ValidationError(
                f"schema version mismatch: expected {expected_version}, got {version}"
            )

        expected_columns = (
            V1_COLUMNS if version == store.LEGACY_SCHEMA_VERSION else V2_COLUMNS
        )
        expected_indexes = (
            V1_NAMED_INDEXES
            if version == store.LEGACY_SCHEMA_VERSION
            else V2_NAMED_INDEXES
        )
        objects = conn.execute(
            "SELECT type, name FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        actual_tables = {str(row[1]) for row in objects if row[0] == "table"}
        actual_indexes = {str(row[1]) for row in objects if row[0] == "index"}
        unexpected_objects = [
            (str(row[0]), str(row[1]))
            for row in objects
            if row[0] in ("view", "trigger")
        ]
        if actual_tables != set(expected_columns):
            raise ValidationError("database has missing or unexpected user tables")
        if actual_indexes != expected_indexes:
            raise ValidationError("database has missing or unexpected named indexes")
        if unexpected_objects:
            raise ValidationError("database must not contain views or triggers")

        layout = {
            table: list(_column_names(conn, table)) for table in expected_columns
        }
        for table, required in expected_columns.items():
            if layout[table] != list(required):
                raise ValidationError(f"unexpected {table} column layout")

        expected_index_layout = (
            V1_INDEX_LAYOUT
            if version == store.LEGACY_SCHEMA_VERSION
            else V2_INDEX_LAYOUT
        )
        for index_name, (table, columns, unique, partial) in expected_index_layout.items():
            listed = {
                str(row[1]): row
                for row in conn.execute(f'PRAGMA index_list("{table}")').fetchall()
            }
            index_row = listed.get(index_name)
            if index_row is None:
                raise ValidationError(f"index {index_name} is missing from {table}")
            actual_columns = tuple(
                str(row[2])
                for row in conn.execute(f'PRAGMA index_info("{index_name}")').fetchall()
            )
            if (
                actual_columns != columns
                or bool(index_row[2]) != unique
                or bool(index_row[4]) != partial
            ):
                raise ValidationError(f"unexpected index layout: {index_name}")

        meta_rows = conn.execute(
            "SELECT key, value FROM schema_meta ORDER BY key"
        ).fetchall()
        if [tuple(row) for row in meta_rows] != [("schema_version", version)]:
            raise ValidationError("schema_meta must contain only the schema_version row")

        expected_foreign_keys = (
            V1_FOREIGN_KEYS
            if version == store.LEGACY_SCHEMA_VERSION
            else V2_FOREIGN_KEYS
        )
        for table, expected_fks in expected_foreign_keys.items():
            fk_rows = conn.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
            actual_fks = {
                (str(row[3]), str(row[2]), str(row[4])) for row in fk_rows
            }
            if actual_fks != expected_fks:
                raise ValidationError(f"unexpected {table} foreign-key layout")

        payload = _legacy_payload(conn)
        counts = {table: len(payload[table]) for table in LEGACY_TABLES}
        if version == store.SCHEMA_VERSION:
            for table in ("thesis_deltas", "thesis_delta_evidence_links"):
                columns = _column_names(conn, table)
                if not columns:
                    raise ValidationError(f"vNext table {table} is missing")
                count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
                counts[table] = int(count[0])

        return {
            "db_path": str(path),
            "schema_version": version,
            "layout": layout,
            "integrity_ok": True,
            "foreign_keys_ok": True,
            "counts": counts,
            "digest": _payload_digest(payload),
        }
    finally:
        conn.close()


def inspect_database(db_path: str | Path) -> dict[str, Any]:
    """Read-only version/layout/integrity report.  Never creates a database."""
    path = _normalized_db_path(db_path)
    report = _database_report(path)
    report.update(operation="inspect", status="ok")
    return report


def _create_backup(source: Path, backup: Path) -> None:
    """Create a consistent SQLite backup, failing if *backup* already exists."""
    if backup.exists():
        raise MigrationError(f"backup already exists and will not be overwritten: {backup}")
    backup.parent.mkdir(parents=True, exist_ok=True)
    fd: int | None = None
    src: sqlite3.Connection | None = None
    dst: sqlite3.Connection | None = None
    try:
        fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        fd = None
        src = _readonly_connection(source)
        dst = sqlite3.connect(backup)
        src.backup(dst)
        dst.commit()
    except Exception:
        if fd is not None:
            os.close(fd)
        if dst is not None:
            dst.close()
            dst = None
        if src is not None:
            src.close()
            src = None
        try:
            backup.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        if dst is not None:
            dst.close()
        if src is not None:
            src.close()


def _copy_legacy_tables(source: Path, candidate: Path) -> None:
    """Copy the four legacy tables into an already initialized vNext DB."""
    src = _readonly_connection(source)
    dst = sqlite3.connect(candidate, timeout=5)
    dst.row_factory = sqlite3.Row
    dst.execute("PRAGMA foreign_keys = ON")
    try:
        dst.execute("BEGIN IMMEDIATE")
        for table in LEGACY_TABLES:
            columns = LEGACY_COLUMNS[table]
            quoted = ",".join(f'"{name}"' for name in columns)
            placeholders = ",".join("?" for _ in columns)
            rows = src.execute(f'SELECT {quoted} FROM "{table}"').fetchall()
            if rows:
                dst.executemany(
                    f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})',
                    (tuple(row) for row in rows),
                )
        dst.commit()
        # initialize_store intentionally configures WAL for normal operation.
        # A standalone swap candidate must instead be a single self-contained
        # file: checkpoint all copied rows, then remove WAL persistence before
        # closing the last writable handle.
        checkpoint = dst.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint is None or int(checkpoint[0]) != 0:
            raise ValidationError("candidate WAL checkpoint failed")
        mode = dst.execute("PRAGMA journal_mode = DELETE").fetchone()
        if mode is None or str(mode[0]).lower() != "delete":
            raise ValidationError("candidate journal mode could not be finalized")
    except Exception:
        dst.rollback()
        raise
    finally:
        dst.close()
        src.close()


def _validate_canonical_reads(candidate: Path) -> None:
    """Exercise canonical service reads for every migrated user-owned record."""
    conn = _readonly_connection(candidate)
    try:
        evidence_ids = [str(row[0]) for row in conn.execute(
            "SELECT id FROM evidence_records ORDER BY id"
        ).fetchall()]
        thesis_rows = conn.execute(
            "SELECT id, current_revision FROM investment_theses ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    for evidence_id in evidence_ids:
        if service.get_evidence(candidate, evidence_id) is None:
            raise ValidationError(f"canonical evidence read failed: {evidence_id}")
    for row in thesis_rows:
        thesis_id = str(row[0])
        current_revision = int(row[1])
        if service.get_thesis(candidate, thesis_id) is None:
            raise ValidationError(f"canonical thesis read failed: {thesis_id}")
        revisions = service.list_revisions(candidate, thesis_id)
        if revisions is None or revisions.get("total") != current_revision:
            raise ValidationError(f"canonical revision read failed: {thesis_id}")
        deltas = service.list_thesis_deltas(candidate, thesis_id)
        if deltas is None or deltas.get("total") != 0:
            raise ValidationError(f"canonical delta read failed: {thesis_id}")


def _validate_candidate(candidate: Path, expected: dict[str, Any]) -> dict[str, Any]:
    report = _database_report(candidate, expected_version=store.SCHEMA_VERSION)
    if report["digest"] != expected["digest"]:
        raise ValidationError("legacy payload digest changed during migration")
    for table in LEGACY_TABLES:
        if report["counts"].get(table) != expected["counts"].get(table):
            raise ValidationError(f"row count changed during migration: {table}")
    if report["counts"].get("thesis_deltas") != 0:
        raise ValidationError("migrated delta table must be empty")
    if report["counts"].get("thesis_delta_evidence_links") != 0:
        raise ValidationError("migrated delta evidence table must be empty")

    conn = _readonly_connection(candidate)
    try:
        formal_expr = " OR ".join(f'"{name}" IS NOT NULL' for name in V2_FORMAL_COLUMNS)
        formal_count = conn.execute(
            f"SELECT COUNT(*) FROM investment_theses WHERE {formal_expr}"
        ).fetchone()
        kind_count = conn.execute(
            "SELECT COUNT(*) FROM thesis_revisions WHERE revision_kind IS NOT NULL"
        ).fetchone()
        if formal_count is None or int(formal_count[0]) != 0:
            raise ValidationError("legacy theses must map to NULL Formal fields")
        if kind_count is None or int(kind_count[0]) != 0:
            raise ValidationError("legacy revisions must map to NULL revision_kind")
    finally:
        conn.close()

    _validate_canonical_reads(candidate)
    return report


def _pre_swap_recheck(source: Path, expected: dict[str, Any]) -> dict[str, Any]:
    """Fail closed if the v1 source changed after the initial inspection."""
    current = _database_report(
        source, expected_version=store.LEGACY_SCHEMA_VERSION
    )
    if current["digest"] != expected["digest"]:
        raise ValidationError("v1 source changed during migration")
    if current["counts"] != expected["counts"]:
        raise ValidationError("v1 source row counts changed during migration")
    if current["layout"] != expected["layout"]:
        raise ValidationError("v1 source layout changed during migration")
    return current


def _assert_no_active_sidecars(source: Path) -> None:
    wal = Path(str(source) + "-wal")
    shm = Path(str(source) + "-shm")
    if (wal.is_file() and wal.stat().st_size > 0) or shm.exists():
        raise MigrationError(
            "database has active SQLite WAL/SHM sidecars; stop all users and retry"
        )


def _cleanup_candidate_artifacts(candidate: Path) -> None:
    """Remove only disposable files owned by this migration invocation."""
    for path in (
        candidate,
        Path(str(candidate) + "-wal"),
        Path(str(candidate) + "-shm"),
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _atomic_swap(source: Path, candidate: Path) -> None:
    """Replace *source* with the closed, fully validated candidate file."""
    _assert_no_active_sidecars(source)
    _assert_no_active_sidecars(candidate)
    os.replace(candidate, source)


def _post_swap_validate(source: Path, expected: dict[str, Any]) -> dict[str, Any]:
    return _validate_candidate(source, expected)


def _post_rollback_validate(source: Path, expected: dict[str, Any]) -> dict[str, Any]:
    report = _database_report(
        source, expected_version=store.LEGACY_SCHEMA_VERSION
    )
    if report["digest"] != expected["digest"]:
        raise ValidationError("restored v1 digest differs from backup")
    if report["counts"] != expected["counts"]:
        raise ValidationError("restored v1 row counts differ from backup")
    return report


def _restore_backup(source: Path, backup: Path) -> dict[str, Any]:
    """Validate v1 backup, copy it, and atomically restore without consuming it."""
    backup_report = _database_report(
        backup, expected_version=store.LEGACY_SCHEMA_VERSION
    )
    restore_candidate = Path(str(source) + ".restore.candidate")
    if restore_candidate.exists():
        raise MigrationError(f"restore candidate already exists: {restore_candidate}")
    try:
        _create_backup(backup, restore_candidate)
        restored_report = _database_report(
            restore_candidate, expected_version=store.LEGACY_SCHEMA_VERSION
        )
        if restored_report["digest"] != backup_report["digest"]:
            raise ValidationError("restore candidate differs from v1 backup")
        _assert_no_active_sidecars(source)
        os.replace(restore_candidate, source)
        final_report = _database_report(
            source, expected_version=store.LEGACY_SCHEMA_VERSION
        )
        if final_report["digest"] != backup_report["digest"]:
            raise ValidationError("restored database differs from v1 backup")
        return final_report
    finally:
        # Only our disposable restore candidate may be removed.  The backup is
        # immutable recovery evidence and is never consumed or overwritten.
        try:
            restore_candidate.unlink(missing_ok=True)
        except OSError:
            pass


def migrate_database(
    db_path: str | Path,
    *,
    backup_path: str | Path,
    apply: bool = False,
) -> dict[str, Any]:
    """Explicitly migrate one on-disk v1 database to vNext."""
    _require_apply(apply)
    source = _normalized_db_path(db_path)
    initial_report = _database_report(source)
    if initial_report["schema_version"] == store.SCHEMA_VERSION:
        initial_report.update(operation="migrate", status="already_current")
        return initial_report
    if initial_report["schema_version"] != store.LEGACY_SCHEMA_VERSION:
        raise ValidationError(
            f"unsupported source schema version: {initial_report['schema_version']}"
        )
    source_report = initial_report
    backup = _normalized_db_path(backup_path)
    if backup == source:
        raise UnsafeDatabasePathError("backup_path must differ from db_path")
    candidate = Path(str(source) + ".v2.candidate")
    if backup.exists():
        raise MigrationError(f"backup already exists and will not be overwritten: {backup}")
    if candidate.exists():
        raise MigrationError(f"candidate already exists and will not be overwritten: {candidate}")

    swapped = False
    try:
        _create_backup(source, backup)
        backup_report = _database_report(
            backup, expected_version=store.LEGACY_SCHEMA_VERSION
        )
        if backup_report["digest"] != source_report["digest"]:
            raise ValidationError("v1 backup differs from inspected source")

        store.initialize_store(candidate)
        _copy_legacy_tables(backup, candidate)
        _validate_candidate(candidate, source_report)
        _pre_swap_recheck(source, source_report)
        _atomic_swap(source, candidate)
        swapped = True
        final_report = _post_swap_validate(source, source_report)
    except Exception as exc:
        if swapped:
            try:
                _restore_backup(source, backup)
            except Exception as rollback_exc:
                raise MigrationError(
                    "post-swap validation failed and automatic rollback also failed"
                ) from rollback_exc
        _cleanup_candidate_artifacts(candidate)
        if isinstance(exc, MigrationError):
            raise
        raise MigrationError(f"migration failed: {type(exc).__name__}") from exc

    final_report.update(
        operation="migrate",
        status="migrated",
        backup_path=str(backup),
    )
    _cleanup_candidate_artifacts(candidate)
    return final_report


def rollback_database(
    db_path: str | Path,
    *,
    backup_path: str | Path,
    apply: bool = False,
) -> dict[str, Any]:
    """Atomically restore the validated v1 backup, preserving the backup file."""
    _require_apply(apply)
    source = _normalized_db_path(db_path)
    source_report = _database_report(source, expected_version=store.SCHEMA_VERSION)
    backup = _normalized_db_path(backup_path)
    if backup == source:
        raise UnsafeDatabasePathError("backup_path must differ from db_path")
    if not backup.is_file():
        raise ValidationError(f"v1 backup does not exist: {backup}")
    if backup == source:
        raise UnsafeDatabasePathError("backup_path must differ from db_path")
    backup_report = _database_report(
        backup, expected_version=store.LEGACY_SCHEMA_VERSION
    )
    recovery = Path(str(source) + ".v2.recovery.candidate")
    if recovery.exists():
        raise MigrationError(f"recovery candidate already exists: {recovery}")

    try:
        _create_backup(source, recovery)
        recovery_report = _database_report(
            recovery, expected_version=store.SCHEMA_VERSION
        )
        if (
            recovery_report["digest"] != source_report["digest"]
            or recovery_report["counts"] != source_report["counts"]
        ):
            raise ValidationError("v2 recovery copy differs from source")
        _restore_backup(source, backup)
        report = _post_rollback_validate(source, backup_report)
    except Exception as exc:
        if recovery.is_file():
            try:
                _assert_no_active_sidecars(source)
                os.replace(recovery, source)
                restored_v2 = _database_report(
                    source, expected_version=store.SCHEMA_VERSION
                )
                if (
                    restored_v2["digest"] != source_report["digest"]
                    or restored_v2["counts"] != source_report["counts"]
                ):
                    raise ValidationError("v2 recovery validation failed")
            except Exception as recovery_exc:
                raise MigrationError(
                    "rollback failed and v2 recovery could not be restored"
                ) from recovery_exc
        if isinstance(exc, MigrationError):
            raise
        raise MigrationError(f"rollback failed: {type(exc).__name__}") from exc
    finally:
        _cleanup_candidate_artifacts(recovery)
    report.update(
        operation="rollback",
        status="rolled_back",
        backup_path=str(backup),
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evidence_thesis_migration",
        description="Explicit evidence-thesis v1/vNext migration utility",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect", help="read-only DB inspection")
    inspect_parser.add_argument(
        "--db", dest="db_path", required=True,
        help="explicit evidence-thesis DB path",
    )
    for command in ("migrate", "rollback"):
        mutating = subparsers.add_parser(command, help=f"explicit {command}")
        mutating.add_argument(
            "--db", dest="db_path", required=True,
            help="explicit evidence-thesis DB path",
        )
        mutating.add_argument(
            "--apply",
            action="store_true",
            help="required acknowledgement for the mutating operation",
        )
        mutating.add_argument(
            "--backup", dest="backup_path", required=True,
            help="explicit v1 backup path",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_database(args.db_path)
        elif args.command == "migrate":
            result = migrate_database(
                args.db_path, backup_path=args.backup_path, apply=args.apply
            )
        else:
            result = rollback_database(
                args.db_path, backup_path=args.backup_path, apply=args.apply
            )
    except MigrationError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
