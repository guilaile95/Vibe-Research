"""Local Fact Lake S1A raw-observation and control-plane storage.

This module deliberately owns only Fact Lake publication metadata.  It does
not integrate providers, canonical facts, Parquet, DuckDB, Data Health, or any
existing application store.

Normal opens never create files or directories.  Initialization is an
explicit operation, and every existing database is version-gated through an
immutable read-only connection before any writable connection is allowed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from data_contracts import ProviderObservation, ReconciliationResult


SCHEMA_VERSION = "fact_lake_control_v1"
CONTROL_DB_FILENAME = "fact_lake_control.sqlite3"
RAW_DIRECTORY_NAME = "raw"

_SCHEMA_VERSION_RE = re.compile(r"^fact_lake_control_v(?P<version>[0-9]+)$")
_SHA256_RE = re.compile(r"^sha256:(?P<digest>[0-9a-fA-F]{64})$")
_COMMIT_STATES = frozenset({"STAGING", "COMMITTED", "FAILED", "ABORTED"})
_WRITE_LOCK = threading.RLock()


class FactLakeError(RuntimeError):
    """Base class for deterministic Fact Lake failures."""


class FactLakeNotInitializedError(FactLakeError):
    """The requested root is not an initialized Fact Lake."""


class FactLakeSchemaVersionError(FactLakeError):
    """The control database is not the exact supported schema version."""


class FactLakeCorruptedError(FactLakeError):
    """Persisted Fact Lake metadata or blob bytes are inconsistent."""


class FactLakeHashMismatchError(FactLakeError):
    """The supplied payload does not match the observation's source hash."""


class FactLakeObservationConflictError(FactLakeError):
    """An observation identity was reused with protected data changed."""


class FactLakeReadOnlyError(FactLakeError):
    """A write was attempted through a read-only handle."""


class FactLakePathError(FactLakeError):
    """A persisted or physical path escaped the owned Fact Lake layout."""


@dataclass(frozen=True)
class StoredObservation:
    observation: ProviderObservation
    content_type: str
    blob_hash: str
    blob_relpath: str
    commit_state: str


@dataclass(frozen=True)
class StoredReconciliation:
    sequence: int
    result: ReconciliationResult


@dataclass(frozen=True)
class ObservationStoreResult:
    stored: StoredObservation
    created: bool


_SCHEMA_DDL = (
    """
    CREATE TABLE schema_meta (
        key TEXT PRIMARY KEY CHECK (key = 'schema_version'),
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE observations (
        observation_id TEXT PRIMARY KEY,
        dataset_id TEXT NOT NULL,
        provider_id TEXT NOT NULL,
        provider_endpoint TEXT NOT NULL,
        request_fingerprint TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        source_payload_hash TEXT NOT NULL,
        normalizer_version TEXT NOT NULL,
        content_type TEXT NOT NULL,
        blob_hash TEXT NOT NULL,
        blob_relpath TEXT NOT NULL,
        observation_json TEXT NOT NULL,
        commit_state TEXT NOT NULL
            CHECK (commit_state IN ('STAGING', 'COMMITTED', 'FAILED', 'ABORTED'))
    )
    """,
    """
    CREATE INDEX observations_dataset_fetched_idx
        ON observations(dataset_id, fetched_at, observation_id)
    """,
    """
    CREATE INDEX observations_blob_idx
        ON observations(blob_hash, observation_id)
    """,
    """
    CREATE TABLE reconciliation_results (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        dataset_id TEXT NOT NULL,
        left_observation_id TEXT,
        right_observation_id TEXT,
        result_json TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX reconciliation_dataset_sequence_idx
        ON reconciliation_results(dataset_id, sequence)
    """,
    """
    CREATE TRIGGER observations_guard_update
    BEFORE UPDATE ON observations
    WHEN NOT (
        OLD.commit_state = 'STAGING'
        AND NEW.commit_state IN ('COMMITTED', 'FAILED', 'ABORTED')
        AND NEW.observation_id IS OLD.observation_id
        AND NEW.dataset_id IS OLD.dataset_id
        AND NEW.provider_id IS OLD.provider_id
        AND NEW.provider_endpoint IS OLD.provider_endpoint
        AND NEW.request_fingerprint IS OLD.request_fingerprint
        AND NEW.fetched_at IS OLD.fetched_at
        AND NEW.source_payload_hash IS OLD.source_payload_hash
        AND NEW.normalizer_version IS OLD.normalizer_version
        AND NEW.content_type IS OLD.content_type
        AND NEW.blob_hash IS OLD.blob_hash
        AND NEW.blob_relpath IS OLD.blob_relpath
        AND NEW.observation_json IS OLD.observation_json
    )
    BEGIN
        SELECT RAISE(ABORT, 'observations are append-only after staging');
    END
    """,
    """
    CREATE TRIGGER observations_guard_delete
    BEFORE DELETE ON observations
    BEGIN
        SELECT RAISE(ABORT, 'observations cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER reconciliation_guard_update
    BEFORE UPDATE ON reconciliation_results
    BEGIN
        SELECT RAISE(ABORT, 'reconciliation results are append-only');
    END
    """,
    """
    CREATE TRIGGER reconciliation_guard_delete
    BEFORE DELETE ON reconciliation_results
    BEGIN
        SELECT RAISE(ABORT, 'reconciliation results cannot be deleted');
    END
    """,
)

_EXPECTED_COLUMNS = {
    "schema_meta": ("key", "value"),
    "observations": (
        "observation_id",
        "dataset_id",
        "provider_id",
        "provider_endpoint",
        "request_fingerprint",
        "fetched_at",
        "source_payload_hash",
        "normalizer_version",
        "content_type",
        "blob_hash",
        "blob_relpath",
        "observation_json",
        "commit_state",
    ),
    "reconciliation_results": (
        "sequence",
        "dataset_id",
        "left_observation_id",
        "right_observation_id",
        "result_json",
    ),
}

_EXPECTED_INDEXES = frozenset(
    {
        "observations_dataset_fetched_idx",
        "observations_blob_idx",
        "reconciliation_dataset_sequence_idx",
    }
)

_EXPECTED_TRIGGERS = frozenset(
    {
        "observations_guard_update",
        "observations_guard_delete",
        "reconciliation_guard_update",
        "reconciliation_guard_delete",
    }
)


def payload_sha256(payload_bytes: bytes) -> str:
    """Return the canonical hash representation accepted by the raw store."""
    if type(payload_bytes) is not bytes:
        raise TypeError("payload_bytes must be bytes")
    return f"sha256:{hashlib.sha256(payload_bytes).hexdigest()}"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _validate_content_type(content_type: str) -> str:
    if type(content_type) is not str or not content_type.strip():
        raise ValueError("content_type must be a non-empty string")
    if content_type != content_type.strip() or "\r" in content_type or "\n" in content_type:
        raise ValueError("content_type must be canonical single-line text")
    return content_type


def _hash_digest(source_payload_hash: str) -> str:
    match = _SHA256_RE.fullmatch(source_payload_hash)
    if match is None:
        raise FactLakeHashMismatchError(
            "source_payload_hash must be sha256 followed by 64 hex digits"
        )
    return match.group("digest").lower()


def _identity_component(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_path_identity(value: str, field: str) -> None:
    if value in {".", ".."} or any(token in value for token in ("/", "\\", "\x00")):
        raise FactLakePathError(f"{field} contains a path-control token")


def _blob_relpath(observation: ProviderObservation, digest: str) -> str:
    return PurePosixPath(
        RAW_DIRECTORY_NAME,
        _identity_component(observation.dataset_id),
        _identity_component(observation.provider_id),
        f"{digest}.blob",
    ).as_posix()


def _root_path(root: str | Path) -> Path:
    path = Path(root)
    if not path.is_absolute():
        raise FactLakePathError("Fact Lake root must be an absolute path")
    return path


def _control_db_path(root: Path) -> Path:
    return root / CONTROL_DB_FILENAME


def _raw_root(root: Path) -> Path:
    return root / RAW_DIRECTORY_NAME


def _sqlite_uri(path: Path, mode: str, *, immutable: bool = False) -> str:
    uri = path.resolve(strict=False).as_uri()
    suffix = f"mode={mode}"
    if immutable:
        suffix += "&immutable=1"
    return f"{uri}?{suffix}"


def _connect_immutable(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(
        _sqlite_uri(path, "ro", immutable=True),
        uri=True,
        timeout=5.0,
    )


def _connect_existing(path: Path, *, readonly: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(
        _sqlite_uri(path, "ro" if readonly else "rw"),
        uri=True,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    return conn


def _assert_current_version_on_connection(conn: sqlite3.Connection) -> None:
    try:
        rows = conn.execute(
            "SELECT key, value FROM schema_meta ORDER BY key"
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise FactLakeCorruptedError("Fact Lake schema metadata is unreadable") from exc
    normalized = [tuple(row) for row in rows]
    if normalized != [("schema_version", SCHEMA_VERSION)]:
        if len(normalized) == 1 and normalized[0][0] == "schema_version":
            value = normalized[0][1]
            if isinstance(value, str) and _SCHEMA_VERSION_RE.fullmatch(value):
                raise FactLakeSchemaVersionError(
                    f"unsupported Fact Lake schema version: {value}"
                )
        raise FactLakeCorruptedError("Fact Lake schema metadata is corrupted")


def _read_exact_schema_version_immutable(path: Path) -> str:
    try:
        conn = _connect_immutable(path)
        try:
            rows = conn.execute(
                "SELECT key, value FROM schema_meta ORDER BY key"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise FactLakeCorruptedError("Fact Lake schema metadata is unreadable") from exc

    if rows != [("schema_version", SCHEMA_VERSION)]:
        if len(rows) == 1 and rows[0][0] == "schema_version":
            value = rows[0][1]
            if type(value) is not str:
                raise FactLakeCorruptedError("Fact Lake schema version is corrupted")
            match = _SCHEMA_VERSION_RE.fullmatch(value)
            if match is not None:
                raise FactLakeSchemaVersionError(
                    f"unsupported Fact Lake schema version: {value}"
                )
        raise FactLakeCorruptedError("Fact Lake schema metadata is corrupted")
    return SCHEMA_VERSION


def _validate_schema_layout(conn: sqlite3.Connection) -> None:
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name NOT LIKE 'sqlite_%'"
            )
        }
        if tables != set(_EXPECTED_COLUMNS):
            raise FactLakeCorruptedError("Fact Lake table layout is corrupted")

        for table, expected in _EXPECTED_COLUMNS.items():
            actual = tuple(
                row[1] for row in conn.execute(f"PRAGMA table_info({table})")
            )
            if actual != expected:
                raise FactLakeCorruptedError(
                    f"Fact Lake columns are corrupted for {table}"
                )

        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
                " AND name NOT LIKE 'sqlite_%'"
            )
        }
        if indexes != _EXPECTED_INDEXES:
            raise FactLakeCorruptedError("Fact Lake index layout is corrupted")

        triggers = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        }
        if triggers != _EXPECTED_TRIGGERS:
            raise FactLakeCorruptedError("Fact Lake trigger layout is corrupted")

        row = conn.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            raise FactLakeCorruptedError("Fact Lake integrity check failed")
    except sqlite3.DatabaseError as exc:
        raise FactLakeCorruptedError("Fact Lake schema layout is unreadable") from exc


def _validate_existing_lake(root: Path) -> Path:
    db_path = _control_db_path(root)
    if root.is_symlink() or db_path.is_symlink():
        raise FactLakePathError("Fact Lake root and control DB must not be symlinks")
    if not root.is_dir() or not db_path.is_file():
        raise FactLakeNotInitializedError("Fact Lake is not initialized")
    raw_root = _raw_root(root)
    if not raw_root.is_dir() or raw_root.is_symlink():
        raise FactLakeCorruptedError("Fact Lake raw directory is missing or unsafe")

    # This is the mandatory zero-mutation gate.  No normal SQLite connection
    # or writable PRAGMA is allowed before the exact version is established.
    _read_exact_schema_version_immutable(db_path)
    conn = _connect_existing(db_path, readonly=True)
    try:
        _validate_schema_layout(conn)
    finally:
        conn.close()
    return db_path


def _initialize_candidate(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for ddl in _SCHEMA_DDL:
            conn.execute(ddl)
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()
        _validate_schema_layout(conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _publish_new_file_no_replace(candidate: Path, destination: Path) -> bool:
    """Atomically publish a durable file without replacing an existing path."""
    try:
        os.link(candidate, destination)
        return True
    except FileExistsError:
        return False


def _fsync_directory(path: Path) -> None:
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def initialize_fact_lake(root: str | Path) -> "FactLake":
    """Explicitly create a new lake, or validate an already-current lake."""
    root_path = _root_path(root)
    if root_path.is_symlink():
        raise FactLakePathError("Fact Lake root cannot be a symbolic link")
    db_path = _control_db_path(root_path)
    if db_path.exists():
        _validate_existing_lake(root_path)
        return FactLake(root_path, readonly=False)

    root_path.mkdir(parents=True, exist_ok=True)
    raw_root = _raw_root(root_path)
    raw_root.mkdir(exist_ok=True)
    if raw_root.is_symlink():
        raise FactLakePathError("Fact Lake raw directory cannot be a symbolic link")

    candidate = root_path / f".{CONTROL_DB_FILENAME}.{uuid.uuid4().hex}.tmp"
    try:
        _initialize_candidate(candidate)
        # Windows requires a writable descriptor for fsync on a regular file.
        with candidate.open("r+b") as handle:
            os.fsync(handle.fileno())
        if not _publish_new_file_no_replace(candidate, db_path):
            _validate_existing_lake(root_path)
        _fsync_directory(root_path)
    finally:
        if candidate.exists():
            candidate.unlink()

    _validate_existing_lake(root_path)
    return FactLake(root_path, readonly=False)


def open_existing_fact_lake(
    root: str | Path,
    *,
    readonly: bool = True,
) -> "FactLake":
    """Open only a fully initialized current-version lake without creating it."""
    root_path = _root_path(root)
    _validate_existing_lake(root_path)
    return FactLake(root_path, readonly=readonly)


class FactLake:
    """A lightweight handle that opens short-lived SQLite transactions."""

    def __init__(self, root: Path, *, readonly: bool) -> None:
        self._root = root
        self._db_path = _control_db_path(root)
        self._readonly = readonly

    @property
    def root(self) -> Path:
        return self._root

    @property
    def readonly(self) -> bool:
        return self._readonly

    def _require_write(self) -> None:
        if self._readonly:
            raise FactLakeReadOnlyError("Fact Lake handle is read-only")

    def _connect(self, *, readonly: bool | None = None) -> sqlite3.Connection:
        use_readonly = self._readonly if readonly is None else readonly
        # A handle may outlive an external file replacement.  Re-run the
        # immutable zero-write gate before every actual connection, then bind
        # the same connection to the exact current version before any writable
        # PRAGMA or transaction is allowed.
        _read_exact_schema_version_immutable(self._db_path)
        conn = _connect_existing(self._db_path, readonly=use_readonly)
        try:
            _assert_current_version_on_connection(conn)
            if not use_readonly:
                conn.execute("PRAGMA foreign_keys = ON")
        except Exception:
            conn.close()
            raise
        return conn

    def _blob_path(
        self,
        relpath: str,
        observation: ProviderObservation,
        *,
        create_parent: bool = False,
    ) -> Path:
        pure = PurePosixPath(relpath)
        expected_digest = _hash_digest(observation.source_payload_hash)
        expected = PurePosixPath(_blob_relpath(observation, expected_digest))
        if pure.is_absolute() or ".." in pure.parts or pure != expected:
            raise FactLakePathError("persisted blob path is not canonical")

        path = self._root.joinpath(*pure.parts)
        raw_root = _raw_root(self._root).resolve(strict=True)
        parent = path.parent
        if create_parent:
            parent.mkdir(parents=True, exist_ok=True)
        elif not parent.is_dir():
            raise FactLakeCorruptedError("committed blob directory is missing")
        if parent.is_symlink() or raw_root not in parent.resolve(strict=True).parents:
            raise FactLakePathError("blob path escaped the raw directory")
        if path.is_symlink():
            raise FactLakePathError("blob path cannot be a symbolic link")
        return path

    def _row_to_stored(self, row: sqlite3.Row, *, verify_blob: bool) -> StoredObservation:
        try:
            payload = json.loads(row["observation_json"])
            observation = ProviderObservation.from_dict(payload)
        except Exception as exc:
            raise FactLakeCorruptedError("stored observation JSON is corrupted") from exc

        expected_values = {
            "observation_id": observation.observation_id,
            "dataset_id": observation.dataset_id,
            "provider_id": observation.provider_id,
            "provider_endpoint": observation.provider_endpoint,
            "request_fingerprint": observation.request_fingerprint,
            "fetched_at": observation.fetched_at,
            "source_payload_hash": observation.source_payload_hash,
            "normalizer_version": observation.normalizer_version,
        }
        for field, expected in expected_values.items():
            if row[field] != expected:
                raise FactLakeCorruptedError(
                    f"stored observation index drifted for {field}"
                )
        if row["blob_hash"] != observation.source_payload_hash:
            raise FactLakeCorruptedError("stored observation blob hash drifted")
        if row["commit_state"] not in _COMMIT_STATES:
            raise FactLakeCorruptedError("stored observation state is invalid")

        stored = StoredObservation(
            observation=observation,
            content_type=row["content_type"],
            blob_hash=row["blob_hash"],
            blob_relpath=row["blob_relpath"],
            commit_state=row["commit_state"],
        )
        if verify_blob:
            blob_path = self._blob_path(stored.blob_relpath, observation)
            if not blob_path.is_file():
                raise FactLakeCorruptedError("committed observation blob is missing")
            try:
                actual_hash = payload_sha256(blob_path.read_bytes())
            except OSError as exc:
                raise FactLakeCorruptedError("committed observation blob is unreadable") from exc
            if actual_hash.lower() != stored.blob_hash.lower():
                raise FactLakeCorruptedError("committed observation blob is corrupted")
        return stored

    def _select_observation_row(
        self,
        conn: sqlite3.Connection,
        observation_id: str,
        *,
        committed_only: bool,
    ) -> sqlite3.Row | None:
        sql = "SELECT * FROM observations WHERE observation_id = ?"
        params: tuple[Any, ...] = (observation_id,)
        if committed_only:
            sql += " AND commit_state = 'COMMITTED'"
        return conn.execute(sql, params).fetchone()

    def _ensure_staging_row(
        self,
        observation: ProviderObservation,
        *,
        content_type: str,
        blob_relpath: str,
        observation_json: str,
    ) -> tuple[StoredObservation | None, bool]:
        conn = self._connect(readonly=False)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = self._select_observation_row(
                conn, observation.observation_id, committed_only=False
            )
            if row is not None:
                stored = self._row_to_stored(
                    row,
                    verify_blob=row["commit_state"] == "COMMITTED",
                )
                exact = (
                    row["observation_json"] == observation_json
                    and row["content_type"] == content_type
                    and row["blob_relpath"] == blob_relpath
                    and row["blob_hash"] == observation.source_payload_hash
                )
                if not exact:
                    raise FactLakeObservationConflictError(
                        "observation_id was reused with protected metadata changed"
                    )
                conn.commit()
                return stored if stored.commit_state == "COMMITTED" else None, False

            conn.execute(
                """
                INSERT INTO observations(
                    observation_id, dataset_id, provider_id, provider_endpoint,
                    request_fingerprint, fetched_at, source_payload_hash,
                    normalizer_version, content_type, blob_hash, blob_relpath,
                    observation_json, commit_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'STAGING')
                """,
                (
                    observation.observation_id,
                    observation.dataset_id,
                    observation.provider_id,
                    observation.provider_endpoint,
                    observation.request_fingerprint,
                    observation.fetched_at,
                    observation.source_payload_hash,
                    observation.normalizer_version,
                    content_type,
                    observation.source_payload_hash,
                    blob_relpath,
                    observation_json,
                ),
            )
            conn.commit()
            return None, True
        except sqlite3.DatabaseError as exc:
            conn.rollback()
            if isinstance(exc, sqlite3.IntegrityError):
                raise FactLakeObservationConflictError(
                    "observation staging conflicted with persisted data"
                ) from exc
            raise FactLakeCorruptedError("observation manifest write failed") from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _publish_blob(self, destination: Path, payload_bytes: bytes) -> None:
        if destination.exists():
            if destination.is_symlink() or not destination.is_file():
                raise FactLakePathError("existing blob destination is unsafe")
            if payload_sha256(destination.read_bytes()) != payload_sha256(payload_bytes):
                raise FactLakeCorruptedError("content-addressed blob collision")
            return

        candidate = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
        try:
            with candidate.open("xb") as handle:
                handle.write(payload_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            if not _publish_new_file_no_replace(candidate, destination):
                if destination.is_symlink() or not destination.is_file():
                    raise FactLakePathError("concurrent blob destination is unsafe")
                if payload_sha256(destination.read_bytes()) != payload_sha256(payload_bytes):
                    raise FactLakeCorruptedError("content-addressed blob collision")
            _fsync_directory(destination.parent)
        finally:
            if candidate.exists():
                candidate.unlink()

    def _commit_observation(self, observation_id: str) -> StoredObservation:
        conn = self._connect(readonly=False)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = self._select_observation_row(
                conn, observation_id, committed_only=False
            )
            if row is None:
                raise FactLakeCorruptedError("staged observation disappeared")
            if row["commit_state"] == "STAGING":
                conn.execute(
                    "UPDATE observations SET commit_state = 'COMMITTED'"
                    " WHERE observation_id = ? AND commit_state = 'STAGING'",
                    (observation_id,),
                )
            elif row["commit_state"] != "COMMITTED":
                raise FactLakeObservationConflictError(
                    "observation is in a terminal non-committed state"
                )
            conn.commit()
            committed = self._select_observation_row(
                conn, observation_id, committed_only=True
            )
            if committed is None:
                raise FactLakeCorruptedError("observation commit was not visible")
            return self._row_to_stored(committed, verify_blob=True)
        except sqlite3.DatabaseError as exc:
            conn.rollback()
            raise FactLakeCorruptedError("observation commit failed") from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def store_observation(
        self,
        observation: ProviderObservation,
        payload_bytes: bytes,
        content_type: str,
    ) -> ObservationStoreResult:
        """Persist exact bytes and publish one immutable observation."""
        self._require_write()
        if not isinstance(observation, ProviderObservation):
            raise TypeError("observation must be ProviderObservation")
        if type(payload_bytes) is not bytes:
            raise TypeError("payload_bytes must be bytes")
        content_type = _validate_content_type(content_type)

        expected_hash = payload_sha256(payload_bytes)
        _validate_path_identity(observation.dataset_id, "dataset_id")
        _validate_path_identity(observation.provider_id, "provider_id")
        digest = _hash_digest(observation.source_payload_hash)
        if observation.source_payload_hash.lower() != expected_hash:
            raise FactLakeHashMismatchError(
                "payload bytes do not match source_payload_hash"
            )

        observation_json = _canonical_json(observation.to_dict())
        blob_relpath = _blob_relpath(observation, digest)

        with _WRITE_LOCK:
            existing, created = self._ensure_staging_row(
                observation,
                content_type=content_type,
                blob_relpath=blob_relpath,
                observation_json=observation_json,
            )
            if existing is not None:
                return ObservationStoreResult(stored=existing, created=False)

            # No physical directory is created until the manifest connection
            # has passed its immutable and same-connection schema gates.
            blob_path = self._blob_path(
                blob_relpath,
                observation,
                create_parent=True,
            )
            # The blob becomes durable before the manifest can become COMMITTED.
            # A crash after this call leaves only an orphan blob plus STAGING row.
            self._publish_blob(blob_path, payload_bytes)
            stored = self._commit_observation(observation.observation_id)
            return ObservationStoreResult(stored=stored, created=created)

    def get_observation(self, observation_id: str) -> StoredObservation | None:
        if type(observation_id) is not str or not observation_id:
            raise ValueError("observation_id must be non-empty")
        conn = self._connect(readonly=True)
        try:
            row = self._select_observation_row(
                conn, observation_id, committed_only=True
            )
            return None if row is None else self._row_to_stored(row, verify_blob=True)
        finally:
            conn.close()

    def read_payload(self, observation_id: str) -> bytes | None:
        stored = self.get_observation(observation_id)
        if stored is None:
            return None
        blob_path = self._blob_path(stored.blob_relpath, stored.observation)
        payload = blob_path.read_bytes()
        if payload_sha256(payload).lower() != stored.blob_hash.lower():
            raise FactLakeCorruptedError("committed observation blob is corrupted")
        return payload

    def append_reconciliation(
        self,
        result: ReconciliationResult,
    ) -> StoredReconciliation:
        """Append a DS-A1 reconciliation result without selecting a winner."""
        self._require_write()
        if not isinstance(result, ReconciliationResult):
            raise TypeError("result must be ReconciliationResult")
        result_json = _canonical_json(result.to_dict())

        with _WRITE_LOCK:
            conn = self._connect(readonly=False)
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute(
                    """
                    INSERT INTO reconciliation_results(
                        dataset_id, left_observation_id,
                        right_observation_id, result_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        result.dataset_id,
                        result.left_observation_id,
                        result.right_observation_id,
                        result_json,
                    ),
                )
                sequence = int(cursor.lastrowid)
                conn.commit()
            except sqlite3.DatabaseError as exc:
                conn.rollback()
                raise FactLakeCorruptedError(
                    "reconciliation append failed"
                ) from exc
            finally:
                conn.close()
        return StoredReconciliation(sequence=sequence, result=result)

    def list_reconciliations(
        self,
        *,
        dataset_id: str | None = None,
    ) -> tuple[StoredReconciliation, ...]:
        if dataset_id is not None and (
            type(dataset_id) is not str or not dataset_id
        ):
            raise ValueError("dataset_id must be non-empty when provided")
        conn = self._connect(readonly=True)
        try:
            if dataset_id is None:
                rows = conn.execute(
                    "SELECT sequence, dataset_id, left_observation_id,"
                    " right_observation_id, result_json"
                    " FROM reconciliation_results ORDER BY sequence"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT sequence, dataset_id, left_observation_id,"
                    " right_observation_id, result_json"
                    " FROM reconciliation_results WHERE dataset_id = ?"
                    " ORDER BY sequence",
                    (dataset_id,),
                ).fetchall()
        finally:
            conn.close()

        results: list[StoredReconciliation] = []
        for row in rows:
            try:
                result = ReconciliationResult.from_dict(
                    json.loads(row["result_json"])
                )
            except Exception as exc:
                raise FactLakeCorruptedError(
                    "stored reconciliation JSON is corrupted"
                ) from exc
            if (
                row["dataset_id"] != result.dataset_id
                or row["left_observation_id"] != result.left_observation_id
                or row["right_observation_id"] != result.right_observation_id
            ):
                raise FactLakeCorruptedError(
                    "stored reconciliation index drifted"
                )
            results.append(
                StoredReconciliation(sequence=int(row["sequence"]), result=result)
            )
        return tuple(results)


__all__ = [
    "CONTROL_DB_FILENAME",
    "RAW_DIRECTORY_NAME",
    "SCHEMA_VERSION",
    "FactLake",
    "FactLakeCorruptedError",
    "FactLakeError",
    "FactLakeHashMismatchError",
    "FactLakeNotInitializedError",
    "FactLakeObservationConflictError",
    "FactLakePathError",
    "FactLakeReadOnlyError",
    "FactLakeSchemaVersionError",
    "ObservationStoreResult",
    "StoredObservation",
    "StoredReconciliation",
    "initialize_fact_lake",
    "open_existing_fact_lake",
    "payload_sha256",
]
