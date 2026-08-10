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
import errno
import json
import os
import re
import sqlite3
import stat
import threading
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from data_contracts import CanonicalFact, ProviderObservation, ReconciliationResult


SCHEMA_VERSION = "fact_lake_control_v2"
CONTROL_DB_FILENAME = "fact_lake_control.sqlite3"
RAW_DIRECTORY_NAME = "raw"
CANONICAL_DIRECTORY_NAME = "canonical"

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


class FactLakePublicationConflictError(FactLakeError):
    """A canonical publication identity conflicted with persisted metadata."""


class FactLakeNormalizationConflictError(FactLakeError):
    """One raw observation/normalizer pair produced conflicting output."""


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


@dataclass(frozen=True)
class StoredCanonicalPublication:
    publication_id: str
    dataset_id: str
    canonical_key: str
    trade_date: str
    vintage_sequence: int
    fact: CanonicalFact
    source_observation_id: str
    dataset_contract_revision: str
    normalizer_version: str
    raw_payload_hash: str
    artifact_schema_version: str
    artifact_relpath: str
    artifact_sha256: str | None
    commit_state: str


@dataclass(frozen=True)
class PublicationStageResult:
    stored: StoredCanonicalPublication
    created: bool


@dataclass(frozen=True)
class StoredNormalization:
    source_observation_id: str
    dataset_id: str
    normalizer_version: str
    normalized_sha256: str
    normalized_payload: Any


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
    CREATE TABLE normalized_observations (
        source_observation_id TEXT PRIMARY KEY,
        dataset_id TEXT NOT NULL,
        normalizer_version TEXT NOT NULL,
        normalized_sha256 TEXT NOT NULL,
        normalized_json TEXT NOT NULL,
        FOREIGN KEY(source_observation_id)
            REFERENCES observations(observation_id)
    )
    """,
    """
    CREATE INDEX normalized_observations_dataset_idx
        ON normalized_observations(dataset_id, source_observation_id)
    """,
    """
    CREATE TABLE canonical_publications (
        publication_id TEXT PRIMARY KEY,
        dataset_id TEXT NOT NULL,
        canonical_key TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        vintage_sequence INTEGER NOT NULL CHECK (vintage_sequence > 0),
        fact_id TEXT NOT NULL,
        canonical_fact_json TEXT NOT NULL,
        source_observation_id TEXT NOT NULL,
        dataset_contract_revision TEXT NOT NULL,
        normalizer_version TEXT NOT NULL,
        raw_payload_hash TEXT NOT NULL,
        artifact_schema_version TEXT NOT NULL,
        artifact_relpath TEXT NOT NULL,
        artifact_sha256 TEXT,
        commit_state TEXT NOT NULL
            CHECK (commit_state IN ('STAGING', 'COMMITTED', 'FAILED', 'ABORTED')),
        UNIQUE(dataset_id, canonical_key, vintage_sequence),
        FOREIGN KEY(source_observation_id)
            REFERENCES observations(observation_id)
    )
    """,
    """
    CREATE INDEX canonical_publications_lookup_idx
        ON canonical_publications(dataset_id, trade_date, vintage_sequence,
                                  publication_id)
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
    """
    CREATE TRIGGER normalized_observations_guard_update
    BEFORE UPDATE ON normalized_observations
    BEGIN
        SELECT RAISE(ABORT, 'normalized observations are immutable');
    END
    """,
    """
    CREATE TRIGGER normalized_observations_guard_delete
    BEFORE DELETE ON normalized_observations
    BEGIN
        SELECT RAISE(ABORT, 'normalized observations cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER canonical_publications_guard_update
    BEFORE UPDATE ON canonical_publications
    WHEN NOT (
        OLD.commit_state = 'STAGING'
        AND NEW.commit_state IN ('COMMITTED', 'FAILED', 'ABORTED')
        AND NEW.publication_id IS OLD.publication_id
        AND NEW.dataset_id IS OLD.dataset_id
        AND NEW.canonical_key IS OLD.canonical_key
        AND NEW.trade_date IS OLD.trade_date
        AND NEW.vintage_sequence IS OLD.vintage_sequence
        AND NEW.fact_id IS OLD.fact_id
        AND NEW.canonical_fact_json IS OLD.canonical_fact_json
        AND NEW.source_observation_id IS OLD.source_observation_id
        AND NEW.dataset_contract_revision IS OLD.dataset_contract_revision
        AND NEW.normalizer_version IS OLD.normalizer_version
        AND NEW.raw_payload_hash IS OLD.raw_payload_hash
        AND NEW.artifact_schema_version IS OLD.artifact_schema_version
        AND NEW.artifact_relpath IS OLD.artifact_relpath
        AND (
            (NEW.commit_state = 'COMMITTED'
             AND OLD.artifact_sha256 IS NULL
             AND NEW.artifact_sha256 IS NOT NULL)
            OR
            (NEW.commit_state IN ('FAILED', 'ABORTED')
             AND NEW.artifact_sha256 IS OLD.artifact_sha256)
        )
    )
    BEGIN
        SELECT RAISE(ABORT, 'canonical publications are immutable after staging');
    END
    """,
    """
    CREATE TRIGGER canonical_publications_guard_delete
    BEFORE DELETE ON canonical_publications
    BEGIN
        SELECT RAISE(ABORT, 'canonical publications cannot be deleted');
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
    "normalized_observations": (
        "source_observation_id",
        "dataset_id",
        "normalizer_version",
        "normalized_sha256",
        "normalized_json",
    ),
    "canonical_publications": (
        "publication_id",
        "dataset_id",
        "canonical_key",
        "trade_date",
        "vintage_sequence",
        "fact_id",
        "canonical_fact_json",
        "source_observation_id",
        "dataset_contract_revision",
        "normalizer_version",
        "raw_payload_hash",
        "artifact_schema_version",
        "artifact_relpath",
        "artifact_sha256",
        "commit_state",
    ),
}

_EXPECTED_INDEXES = frozenset(
    {
        "observations_dataset_fetched_idx",
        "observations_blob_idx",
        "reconciliation_dataset_sequence_idx",
        "normalized_observations_dataset_idx",
        "canonical_publications_lookup_idx",
    }
)

_EXPECTED_TRIGGERS = frozenset(
    {
        "observations_guard_update",
        "observations_guard_delete",
        "reconciliation_guard_update",
        "reconciliation_guard_delete",
        "normalized_observations_guard_update",
        "normalized_observations_guard_delete",
        "canonical_publications_guard_update",
        "canonical_publications_guard_delete",
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


def _is_link_or_reparse(path: Path, path_stat: os.stat_result | None = None) -> bool:
    try:
        current = path.lstat() if path_stat is None else path_stat
    except OSError:
        return False
    if stat.S_ISLNK(current.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(getattr(current, "st_file_attributes", 0) & reparse_flag)


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


def _canonical_root(root: Path) -> Path:
    return root / CANONICAL_DIRECTORY_NAME


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


def _normalized_schema_sql(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", value.strip()).lower()


def _schema_layout_fingerprint(conn: sqlite3.Connection) -> tuple[Any, ...]:
    objects = tuple(
        (
            row[0],
            row[1],
            row[2],
            _normalized_schema_sql(row[3]),
        )
        for row in conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master"
            " WHERE name NOT LIKE 'sqlite_%'"
            " ORDER BY type, name"
        )
    )
    table_details = tuple(
        (
            table,
            tuple(tuple(row) for row in conn.execute(
                f'PRAGMA table_xinfo("{table}")'
            )),
            tuple(tuple(row) for row in conn.execute(
                f'PRAGMA foreign_key_list("{table}")'
            )),
        )
        for table in sorted(_EXPECTED_COLUMNS)
    )
    index_details = tuple(
        (
            index,
            tuple(tuple(row) for row in conn.execute(
                f'PRAGMA index_xinfo("{index}")'
            )),
        )
        for index in sorted(_EXPECTED_INDEXES)
    )
    return objects, table_details, index_details


@lru_cache(maxsize=1)
def _expected_schema_layout_fingerprint() -> tuple[Any, ...]:
    conn = sqlite3.connect(":memory:")
    try:
        for ddl in _SCHEMA_DDL:
            conn.execute(ddl)
        return _schema_layout_fingerprint(conn)
    finally:
        conn.close()


def _validate_schema_fingerprint(conn: sqlite3.Connection) -> None:
    try:
        if _schema_layout_fingerprint(conn) \
                != _expected_schema_layout_fingerprint():
            raise FactLakeCorruptedError("Fact Lake schema fingerprint drifted")
    except sqlite3.DatabaseError as exc:
        raise FactLakeCorruptedError("Fact Lake schema layout is unreadable") from exc


def _validate_schema_layout(conn: sqlite3.Connection) -> None:
    _validate_schema_fingerprint(conn)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            raise FactLakeCorruptedError("Fact Lake integrity check failed")
    except sqlite3.DatabaseError as exc:
        raise FactLakeCorruptedError("Fact Lake schema layout is unreadable") from exc


def _validate_existing_lake(root: Path) -> Path:
    db_path = _control_db_path(root)
    if _is_link_or_reparse(root) or _is_link_or_reparse(db_path):
        raise FactLakePathError("Fact Lake root and control DB must not be symlinks")
    if not root.is_dir() or not db_path.is_file():
        raise FactLakeNotInitializedError("Fact Lake is not initialized")
    # This is the mandatory zero-mutation gate.  No normal SQLite connection
    # or writable PRAGMA is allowed before the exact version is established.
    _read_exact_schema_version_immutable(db_path)
    raw_root = _raw_root(root)
    canonical_root = _canonical_root(root)
    if not raw_root.is_dir() or _is_link_or_reparse(raw_root):
        raise FactLakeCorruptedError("Fact Lake raw directory is missing or unsafe")
    if not canonical_root.is_dir() or _is_link_or_reparse(canonical_root):
        raise FactLakeCorruptedError(
            "Fact Lake canonical directory is missing or unsafe"
        )
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
    # Python does not expose a portable Windows directory fsync primitive.
    # File bytes are still flushed before no-replace publication; the missing
    # directory primitive is an explicit platform limitation, not a swallowed
    # runtime failure.  POSIX filesystems must accept the barrier or report one
    # of the narrowly-recognized unsupported-operation errors below.
    if os.name == "nt":
        return
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno in {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
            return
        raise
    try:
        os.fsync(fd)
    except OSError as exc:
        if exc.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
            raise
    finally:
        os.close(fd)


def initialize_fact_lake(root: str | Path) -> "FactLake":
    """Explicitly create a new lake, or validate an already-current lake."""
    root_path = _root_path(root)
    if _is_link_or_reparse(root_path):
        raise FactLakePathError("Fact Lake root cannot be a symbolic link")
    db_path = _control_db_path(root_path)
    if db_path.exists():
        _validate_existing_lake(root_path)
        return FactLake(root_path, readonly=False)

    root_path.mkdir(parents=True, exist_ok=True)
    raw_root = _raw_root(root_path)
    raw_root.mkdir(exist_ok=True)
    if _is_link_or_reparse(raw_root):
        raise FactLakePathError("Fact Lake raw directory cannot be a symbolic link")
    canonical_root = _canonical_root(root_path)
    canonical_root.mkdir(exist_ok=True)
    if _is_link_or_reparse(canonical_root):
        raise FactLakePathError(
            "Fact Lake canonical directory cannot be a symbolic link"
        )

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
            _validate_schema_fingerprint(conn)
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
        parent = self._safe_blob_parent(pure, create=create_parent)
        if path.parent != parent:
            raise FactLakePathError("blob path escaped the raw directory")
        try:
            blob_stat = path.lstat()
        except FileNotFoundError:
            blob_stat = None
        except OSError as exc:
            raise FactLakePathError("blob path cannot be inspected safely") from exc
        if blob_stat is not None and _is_link_or_reparse(path, blob_stat):
            raise FactLakePathError("blob path cannot be a symbolic link")
        return path

    @staticmethod
    def _assert_plain_directory(path: Path, *, missing_is_corrupt: bool) -> None:
        try:
            path_stat = path.lstat()
            mode = path_stat.st_mode
        except FileNotFoundError as exc:
            if missing_is_corrupt:
                raise FactLakeCorruptedError(
                    "committed blob directory is missing"
                ) from exc
            raise
        except OSError as exc:
            raise FactLakePathError("blob directory cannot be inspected safely") from exc
        if _is_link_or_reparse(path, path_stat):
            raise FactLakePathError("blob directory ancestor cannot be a symbolic link")
        if not stat.S_ISDIR(mode):
            raise FactLakePathError("blob directory ancestor is not a directory")

    def _safe_blob_parent(self, pure: PurePosixPath, *, create: bool) -> Path:
        """Walk the fixed hashed layout without following unverified ancestors."""
        if len(pure.parts) != 4 or pure.parts[0] != RAW_DIRECTORY_NAME:
            raise FactLakePathError("persisted blob path has an unsafe layout")

        return self._safe_owned_parent(pure, create=create)

    def _safe_owned_parent(self, pure: PurePosixPath, *, create: bool) -> Path:
        """Walk one fixed four-component owned layout without symlink descent."""
        if len(pure.parts) != 4 or pure.parts[0] not in {
            RAW_DIRECTORY_NAME,
            CANONICAL_DIRECTORY_NAME,
        }:
            raise FactLakePathError("persisted artifact path has an unsafe layout")

        current = self._root
        self._assert_plain_directory(current, missing_is_corrupt=True)
        for index, component in enumerate(pure.parts[0:-1]):
            current = current / component
            if index == 0:
                # The raw root is initialization-owned and must always exist.
                self._assert_plain_directory(current, missing_is_corrupt=True)
                continue
            try:
                self._assert_plain_directory(
                    current,
                    missing_is_corrupt=not create,
                )
            except FileNotFoundError:
                # Never use parents=True here: every already-existing ancestor
                # has been inspected with lstat before descending into it.
                try:
                    current.mkdir()
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise FactLakePathError(
                        "blob directory could not be created safely"
                    ) from exc
                self._assert_plain_directory(current, missing_is_corrupt=False)

        # Re-check the complete chain immediately before the caller performs
        # any file mutation/read.  This also catches a long-lived handle whose
        # raw or hashed directory was replaced after construction.
        current = self._root
        self._assert_plain_directory(current, missing_is_corrupt=True)
        for component in pure.parts[0:-1]:
            current = current / component
            self._assert_plain_directory(current, missing_is_corrupt=True)
        return current

    def canonical_artifact_path(
        self,
        relpath: str,
        *,
        create_parent: bool = False,
    ) -> Path:
        """Resolve one canonical artifact path under the owned canonical root."""
        pure = self._canonical_relpath(relpath)
        path = self._root.joinpath(*pure.parts)
        parent = self._safe_owned_parent(pure, create=create_parent)
        if path.parent != parent:
            raise FactLakePathError("canonical artifact escaped the owned directory")
        try:
            artifact_stat = path.lstat()
        except FileNotFoundError:
            artifact_stat = None
        except OSError as exc:
            raise FactLakePathError(
                "canonical artifact path cannot be inspected safely"
            ) from exc
        if artifact_stat is not None and _is_link_or_reparse(path, artifact_stat):
            raise FactLakePathError("canonical artifact cannot be a symbolic link")
        return path

    @staticmethod
    def _canonical_relpath(relpath: str) -> PurePosixPath:
        pure = PurePosixPath(relpath)
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or len(pure.parts) != 4
            or pure.parts[0] != CANONICAL_DIRECTORY_NAME
            or re.fullmatch(r"[0-9a-f]{64}", pure.parts[1]) is None
            or re.fullmatch(r"\d{4}-\d{2}-\d{2}", pure.parts[2]) is None
            or re.fullmatch(r"[0-9a-f]{64}\.parquet", pure.parts[3]) is None
        ):
            raise FactLakePathError("canonical artifact path is not canonical")
        return pure

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise FactLakeCorruptedError(
                "canonical artifact is unreadable"
            ) from exc
        return f"sha256:{digest.hexdigest()}"

    def publish_canonical_artifact(
        self,
        relpath: str,
        writer: Callable[[Path], None],
    ) -> str:
        """Durably publish one immutable artifact and return its SHA-256."""
        self._require_write()
        if not callable(writer):
            raise TypeError("writer must be callable")
        destination = self.canonical_artifact_path(
            relpath,
            create_parent=True,
        )
        if destination.exists():
            if _is_link_or_reparse(destination) or not destination.is_file():
                raise FactLakePathError("existing canonical artifact is unsafe")
            digest = self._file_sha256(destination)
            _fsync_directory(destination.parent)
            return digest

        candidate = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
        try:
            writer(candidate)
            try:
                mode = candidate.lstat().st_mode
            except OSError as exc:
                raise FactLakeCorruptedError(
                    "canonical artifact writer did not create a readable file"
                ) from exc
            if _is_link_or_reparse(candidate) or not stat.S_ISREG(mode):
                raise FactLakePathError(
                    "canonical artifact writer produced an unsafe file"
                )
            with candidate.open("r+b") as handle:
                os.fsync(handle.fileno())
            digest = self._file_sha256(candidate)
            if not _publish_new_file_no_replace(candidate, destination):
                if _is_link_or_reparse(destination) or not destination.is_file():
                    raise FactLakePathError(
                        "concurrent canonical artifact destination is unsafe"
                    )
                if self._file_sha256(destination) != digest:
                    raise FactLakePublicationConflictError(
                        "canonical artifact identity collided with different bytes"
                    )
            _fsync_directory(destination.parent)
            return digest
        finally:
            if candidate.exists():
                candidate.unlink()

    def verify_canonical_artifact(
        self,
        relpath: str,
        expected_sha256: str,
    ) -> Path:
        """Resolve and hash-check one committed canonical artifact."""
        _hash_digest(expected_sha256)
        path = self.canonical_artifact_path(relpath)
        if not path.is_file():
            raise FactLakeCorruptedError("committed canonical artifact is missing")
        if self._file_sha256(path).lower() != expected_sha256.lower():
            raise FactLakeCorruptedError("committed canonical artifact hash mismatch")
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
            if _is_link_or_reparse(destination) or not destination.is_file():
                raise FactLakePathError("existing blob destination is unsafe")
            if payload_sha256(destination.read_bytes()) != payload_sha256(payload_bytes):
                raise FactLakeCorruptedError("content-addressed blob collision")
            # A previous attempt may have published the blob and then failed
            # its directory durability barrier.  Repeat the barrier before the
            # manifest is allowed to become COMMITTED.
            _fsync_directory(destination.parent)
            return

        candidate = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
        try:
            with candidate.open("xb") as handle:
                handle.write(payload_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            if not _publish_new_file_no_replace(candidate, destination):
                if _is_link_or_reparse(destination) or not destination.is_file():
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

    def _row_to_normalization(self, row: sqlite3.Row) -> StoredNormalization:
        try:
            payload = json.loads(row["normalized_json"])
        except Exception as exc:
            raise FactLakeCorruptedError(
                "stored normalized observation JSON is corrupted"
            ) from exc
        canonical = _canonical_json(payload)
        digest = payload_sha256(canonical.encode("utf-8"))
        if digest.lower() != row["normalized_sha256"].lower():
            raise FactLakeCorruptedError(
                "stored normalized observation hash drifted"
            )
        source = self.get_observation(row["source_observation_id"])
        if source is None:
            raise FactLakeCorruptedError(
                "normalized observation source is not committed"
            )
        if (
            source.observation.dataset_id != row["dataset_id"]
            or source.observation.normalizer_version != row["normalizer_version"]
        ):
            raise FactLakeCorruptedError(
                "normalized observation index drifted"
            )
        return StoredNormalization(
            source_observation_id=row["source_observation_id"],
            dataset_id=row["dataset_id"],
            normalizer_version=row["normalizer_version"],
            normalized_sha256=row["normalized_sha256"],
            normalized_payload=payload,
        )

    def store_normalization(
        self,
        source_observation_id: str,
        normalized_payload: Any,
        *,
        normalizer_version: str,
    ) -> StoredNormalization:
        """Append one deterministic normalization result or replay it exactly."""
        self._require_write()
        self._require_publication_text(
            source_observation_id,
            "source_observation_id",
        )
        self._require_publication_text(normalizer_version, "normalizer_version")
        source = self.get_observation(source_observation_id)
        if source is None:
            raise FactLakeNormalizationConflictError(
                "normalization requires a committed source observation"
            )
        if source.observation.normalizer_version != normalizer_version:
            raise FactLakeNormalizationConflictError(
                "normalizer version does not match source observation"
            )
        normalized_json = _canonical_json(normalized_payload)
        normalized_sha256 = payload_sha256(normalized_json.encode("utf-8"))
        with _WRITE_LOCK:
            conn = self._connect(readonly=False)
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT * FROM normalized_observations"
                    " WHERE source_observation_id = ?",
                    (source_observation_id,),
                ).fetchone()
                if row is not None:
                    if (
                        row["dataset_id"] != source.observation.dataset_id
                        or row["normalizer_version"] != normalizer_version
                        or row["normalized_sha256"].lower()
                            != normalized_sha256.lower()
                        or row["normalized_json"] != normalized_json
                    ):
                        raise FactLakeNormalizationConflictError(
                            "raw observation/normalizer produced conflicting output"
                        )
                    conn.commit()
                    return self._row_to_normalization(row)
                conn.execute(
                    """
                    INSERT INTO normalized_observations(
                        source_observation_id, dataset_id, normalizer_version,
                        normalized_sha256, normalized_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        source_observation_id,
                        source.observation.dataset_id,
                        normalizer_version,
                        normalized_sha256,
                        normalized_json,
                    ),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM normalized_observations"
                    " WHERE source_observation_id = ?",
                    (source_observation_id,),
                ).fetchone()
                if row is None:
                    raise FactLakeCorruptedError(
                        "normalization append was not visible"
                    )
                return self._row_to_normalization(row)
            except sqlite3.DatabaseError as exc:
                conn.rollback()
                raise FactLakeCorruptedError("normalization append failed") from exc
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def get_normalization(
        self,
        source_observation_id: str,
    ) -> StoredNormalization | None:
        self._require_publication_text(
            source_observation_id,
            "source_observation_id",
        )
        conn = self._connect(readonly=True)
        try:
            row = conn.execute(
                "SELECT * FROM normalized_observations"
                " WHERE source_observation_id = ?",
                (source_observation_id,),
            ).fetchone()
        finally:
            conn.close()
        return None if row is None else self._row_to_normalization(row)

    @staticmethod
    def _require_publication_text(value: str, field: str) -> str:
        if type(value) is not str or not value.strip() or value != value.strip():
            raise ValueError(f"{field} must be canonical non-empty text")
        return value

    def _row_to_publication(
        self,
        row: sqlite3.Row,
        *,
        verify_artifact: bool,
    ) -> StoredCanonicalPublication:
        try:
            fact = CanonicalFact.from_dict(json.loads(row["canonical_fact_json"]))
        except Exception as exc:
            raise FactLakeCorruptedError(
                "stored canonical fact JSON is corrupted"
            ) from exc
        if (
            fact.fact_id != row["fact_id"]
            or fact.dataset_id != row["dataset_id"]
            or fact.canonical_key != row["canonical_key"]
            or fact.trade_date != row["trade_date"]
            or fact.dataset_contract_revision != row["dataset_contract_revision"]
            or fact.source_observation_ids != (row["source_observation_id"],)
            or len(fact.provenance_chain) != 1
            or fact.provenance_chain[0].observation_id
                != row["source_observation_id"]
            or fact.provenance_chain[0].normalizer_version
                != row["normalizer_version"]
            or fact.provenance_chain[0].source_payload_hash
                != row["raw_payload_hash"]
        ):
            raise FactLakeCorruptedError(
                "stored canonical publication index drifted"
            )
        state = row["commit_state"]
        artifact_hash = row["artifact_sha256"]
        if state not in _COMMIT_STATES:
            raise FactLakeCorruptedError(
                "stored canonical publication state is invalid"
            )
        if state == "COMMITTED" and artifact_hash is None:
            raise FactLakeCorruptedError(
                "committed canonical publication lacks an artifact hash"
            )
        if state == "STAGING" and artifact_hash is not None:
            raise FactLakeCorruptedError(
                "staging canonical publication has a committed artifact hash"
            )
        normalization = self.get_normalization(row["source_observation_id"])
        if normalization is None or _canonical_json(
            normalization.normalized_payload
        ) != _canonical_json(fact.canonical_payload):
            raise FactLakeCorruptedError(
                "canonical publication is not bound to normalized evidence"
            )
        stored = StoredCanonicalPublication(
            publication_id=row["publication_id"],
            dataset_id=row["dataset_id"],
            canonical_key=row["canonical_key"],
            trade_date=row["trade_date"],
            vintage_sequence=int(row["vintage_sequence"]),
            fact=fact,
            source_observation_id=row["source_observation_id"],
            dataset_contract_revision=row["dataset_contract_revision"],
            normalizer_version=row["normalizer_version"],
            raw_payload_hash=row["raw_payload_hash"],
            artifact_schema_version=row["artifact_schema_version"],
            artifact_relpath=row["artifact_relpath"],
            artifact_sha256=artifact_hash,
            commit_state=state,
        )
        if verify_artifact and state == "COMMITTED":
            self.verify_canonical_artifact(
                stored.artifact_relpath,
                stored.artifact_sha256 or "",
            )
        return stored

    @staticmethod
    def _select_publication_row(
        conn: sqlite3.Connection,
        publication_id: str,
        *,
        committed_only: bool,
    ) -> sqlite3.Row | None:
        sql = "SELECT * FROM canonical_publications WHERE publication_id = ?"
        if committed_only:
            sql += " AND commit_state = 'COMMITTED'"
        return conn.execute(sql, (publication_id,)).fetchone()

    def stage_canonical_publication(
        self,
        fact: CanonicalFact,
        *,
        publication_id: str,
        source_observation_id: str,
        normalizer_version: str,
        raw_payload_hash: str,
        artifact_schema_version: str,
        artifact_relpath: str,
        equivalent_replay: Callable[[CanonicalFact, CanonicalFact], bool]
            | None = None,
    ) -> PublicationStageResult:
        """Create or replay one invisible canonical publication staging row."""
        self._require_write()
        if not isinstance(fact, CanonicalFact):
            raise TypeError("fact must be CanonicalFact")
        if equivalent_replay is not None and not callable(equivalent_replay):
            raise TypeError("equivalent_replay must be callable when provided")
        for field, value in (
            ("publication_id", publication_id),
            ("source_observation_id", source_observation_id),
            ("normalizer_version", normalizer_version),
            ("artifact_schema_version", artifact_schema_version),
        ):
            self._require_publication_text(value, field)
        _hash_digest(raw_payload_hash)
        self._canonical_relpath(artifact_relpath)
        if fact.trade_date is None:
            raise FactLakePublicationConflictError(
                "canonical publication requires an explicit trade_date"
            )
        if fact.source_observation_ids != (source_observation_id,):
            raise FactLakePublicationConflictError(
                "canonical publication must bind exactly one source observation"
            )
        source = self.get_observation(source_observation_id)
        if source is None:
            raise FactLakePublicationConflictError(
                "canonical source observation is not committed"
            )
        if (
            source.observation.dataset_id != fact.dataset_id
            or source.observation.provider_id != fact.canonical_source
            or source.observation.provider_id
                != fact.provenance_chain[0].provider_id
            or source.observation.provider_endpoint
                != fact.provenance_chain[0].provider_endpoint
            or source.observation.trade_date != fact.trade_date
            or source.observation.quality_status != fact.quality_status
            or source.observation.source_payload_hash.lower()
                != raw_payload_hash.lower()
            or source.observation.normalizer_version != normalizer_version
        ):
            raise FactLakePublicationConflictError(
                "canonical publication provenance does not match its observation"
            )
        normalization = self.get_normalization(source_observation_id)
        if normalization is None:
            raise FactLakePublicationConflictError(
                "canonical publication requires persisted normalized evidence"
            )
        if (
            normalization.normalizer_version != normalizer_version
            or _canonical_json(normalization.normalized_payload)
                != _canonical_json(fact.canonical_payload)
        ):
            raise FactLakePublicationConflictError(
                "canonical payload does not match persisted normalized evidence"
            )

        fact_json = _canonical_json(fact.to_dict())
        exact_values = (
            fact.dataset_id,
            fact.canonical_key,
            fact.trade_date,
            fact.fact_id,
            fact_json,
            source_observation_id,
            fact.dataset_contract_revision,
            normalizer_version,
            raw_payload_hash,
            artifact_schema_version,
            artifact_relpath,
        )
        with _WRITE_LOCK:
            conn = self._connect(readonly=False)
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = self._select_publication_row(
                    conn,
                    publication_id,
                    committed_only=False,
                )
                if row is not None:
                    persisted_values = (
                        row["dataset_id"],
                        row["canonical_key"],
                        row["trade_date"],
                        row["fact_id"],
                        row["canonical_fact_json"],
                        row["source_observation_id"],
                        row["dataset_contract_revision"],
                        row["normalizer_version"],
                        row["raw_payload_hash"],
                        row["artifact_schema_version"],
                        row["artifact_relpath"],
                    )
                    if persisted_values != exact_values:
                        try:
                            persisted_fact = CanonicalFact.from_dict(
                                json.loads(row["canonical_fact_json"])
                            )
                            equivalent = (
                                equivalent_replay is not None
                                and row["dataset_id"] == fact.dataset_id
                                and row["canonical_key"] == fact.canonical_key
                                and row["trade_date"] == fact.trade_date
                                and row["dataset_contract_revision"]
                                    == fact.dataset_contract_revision
                                and row["normalizer_version"]
                                    == normalizer_version
                                and row["raw_payload_hash"].lower()
                                    == raw_payload_hash.lower()
                                and row["artifact_schema_version"]
                                    == artifact_schema_version
                                and row["artifact_relpath"] == artifact_relpath
                                and equivalent_replay(persisted_fact, fact)
                            )
                        except Exception as exc:
                            raise FactLakePublicationConflictError(
                                "publication replay equivalence validation failed"
                            ) from exc
                        if not equivalent:
                            raise FactLakePublicationConflictError(
                                "publication_id was reused with different semantics"
                            )
                    conn.commit()
                    return PublicationStageResult(
                        stored=self._row_to_publication(
                            row,
                            verify_artifact=row["commit_state"] == "COMMITTED",
                        ),
                        created=False,
                    )

                sequence = int(conn.execute(
                    "SELECT COALESCE(MAX(vintage_sequence), 0) + 1"
                    " FROM canonical_publications"
                    " WHERE dataset_id = ? AND canonical_key = ?",
                    (fact.dataset_id, fact.canonical_key),
                ).fetchone()[0])
                conn.execute(
                    """
                    INSERT INTO canonical_publications(
                        publication_id, dataset_id, canonical_key, trade_date,
                        vintage_sequence, fact_id, canonical_fact_json,
                        source_observation_id, dataset_contract_revision,
                        normalizer_version, raw_payload_hash,
                        artifact_schema_version, artifact_relpath,
                        artifact_sha256, commit_state
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'STAGING')
                    """,
                    (
                        publication_id,
                        fact.dataset_id,
                        fact.canonical_key,
                        fact.trade_date,
                        sequence,
                        fact.fact_id,
                        fact_json,
                        source_observation_id,
                        fact.dataset_contract_revision,
                        normalizer_version,
                        raw_payload_hash,
                        artifact_schema_version,
                        artifact_relpath,
                    ),
                )
                conn.commit()
                row = self._select_publication_row(
                    conn,
                    publication_id,
                    committed_only=False,
                )
                if row is None:
                    raise FactLakeCorruptedError(
                        "canonical publication staging was not visible"
                    )
                return PublicationStageResult(
                    stored=self._row_to_publication(row, verify_artifact=False),
                    created=True,
                )
            except sqlite3.DatabaseError as exc:
                conn.rollback()
                raise FactLakeCorruptedError(
                    "canonical publication staging failed"
                ) from exc
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def commit_canonical_publication(
        self,
        publication_id: str,
        artifact_sha256: str,
    ) -> StoredCanonicalPublication:
        """Make one durable artifact authoritative and query-visible."""
        self._require_write()
        self._require_publication_text(publication_id, "publication_id")
        _hash_digest(artifact_sha256)
        with _WRITE_LOCK:
            conn = self._connect(readonly=False)
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = self._select_publication_row(
                    conn,
                    publication_id,
                    committed_only=False,
                )
                if row is None:
                    raise FactLakePublicationConflictError(
                        "canonical publication was not staged"
                    )
                if row["commit_state"] == "COMMITTED":
                    if row["artifact_sha256"].lower() != artifact_sha256.lower():
                        raise FactLakePublicationConflictError(
                            "committed publication artifact hash changed"
                        )
                    conn.commit()
                    return self._row_to_publication(row, verify_artifact=True)
                if row["commit_state"] != "STAGING":
                    raise FactLakePublicationConflictError(
                        "canonical publication is in a terminal state"
                    )
                self.verify_canonical_artifact(
                    row["artifact_relpath"],
                    artifact_sha256,
                )
                conn.execute(
                    "UPDATE canonical_publications"
                    " SET artifact_sha256 = ?, commit_state = 'COMMITTED'"
                    " WHERE publication_id = ? AND commit_state = 'STAGING'",
                    (artifact_sha256, publication_id),
                )
                conn.commit()
                committed = self._select_publication_row(
                    conn,
                    publication_id,
                    committed_only=True,
                )
                if committed is None:
                    raise FactLakeCorruptedError(
                        "canonical publication commit was not visible"
                    )
                return self._row_to_publication(
                    committed,
                    verify_artifact=True,
                )
            except sqlite3.DatabaseError as exc:
                conn.rollback()
                raise FactLakeCorruptedError(
                    "canonical publication commit failed"
                ) from exc
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def get_canonical_publication(
        self,
        publication_id: str,
    ) -> StoredCanonicalPublication | None:
        self._require_publication_text(publication_id, "publication_id")
        conn = self._connect(readonly=True)
        try:
            row = self._select_publication_row(
                conn,
                publication_id,
                committed_only=True,
            )
        finally:
            conn.close()
        return None if row is None else self._row_to_publication(
            row,
            verify_artifact=True,
        )

    def list_canonical_publications(
        self,
        *,
        dataset_id: str,
        trade_date: str,
    ) -> tuple[StoredCanonicalPublication, ...]:
        self._require_publication_text(dataset_id, "dataset_id")
        self._require_publication_text(trade_date, "trade_date")
        conn = self._connect(readonly=True)
        try:
            rows = conn.execute(
                "SELECT * FROM canonical_publications"
                " WHERE dataset_id = ? AND trade_date = ?"
                " AND commit_state = 'COMMITTED'"
                " ORDER BY vintage_sequence, publication_id",
                (dataset_id, trade_date),
            ).fetchall()
        finally:
            conn.close()
        return tuple(
            self._row_to_publication(row, verify_artifact=True)
            for row in rows
        )

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
    "CANONICAL_DIRECTORY_NAME",
    "CONTROL_DB_FILENAME",
    "RAW_DIRECTORY_NAME",
    "SCHEMA_VERSION",
    "FactLake",
    "FactLakeCorruptedError",
    "FactLakeError",
    "FactLakeHashMismatchError",
    "FactLakeNotInitializedError",
    "FactLakeNormalizationConflictError",
    "FactLakeObservationConflictError",
    "FactLakePathError",
    "FactLakePublicationConflictError",
    "FactLakeReadOnlyError",
    "FactLakeSchemaVersionError",
    "ObservationStoreResult",
    "PublicationStageResult",
    "StoredCanonicalPublication",
    "StoredNormalization",
    "StoredObservation",
    "StoredReconciliation",
    "initialize_fact_lake",
    "open_existing_fact_lake",
    "payload_sha256",
]
