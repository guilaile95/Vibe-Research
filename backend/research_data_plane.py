"""Bounded local bulk research data plane for unadjusted daily bars.

This module is a research-runtime read model.  It does not publish CanonicalFact,
change Fact Lake state, or create any investment/decision authority.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb

SCHEMA_VERSION = "research-data-plane.v0.1"
DATASET_ID = "ashare_daily_unadjusted"
PROVIDER_ID = "local_bulk_dump"
ADJUSTMENT = "UNADJUSTED"
LICENSE_STATUS = "UNKNOWN"
_REQUIRED_COLUMNS = ("code", "trade_date", "open", "high", "low", "close", "volume")
_CODE_RE = re.compile(r"^\d{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_LIMIT = 1000


class ResearchDataPlaneError(RuntimeError):
    """Base error for deterministic research data-plane failures."""


class ResearchDataPlaneValidationError(ResearchDataPlaneError):
    pass


class ResearchDataPlaneUnavailableError(ResearchDataPlaneError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def resolve_root(root: str | Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    configured = os.environ.get("VIBE_RESEARCH_RESEARCH_DATA_DIR", "").strip()
    if configured:
        return Path(configured)
    data_dir = os.environ.get("VR_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir) / "research_data_plane"
    return Path.home() / ".vibe-research" / "research_data_plane"


def _manifest_path(root: Path) -> Path:
    return root / "manifest.json"


def _artifact_path(root: Path, digest: str) -> Path:
    return root / "artifacts" / f"{digest}.parquet"


def _finite_number(raw: Any, field: str, row_number: int) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ResearchDataPlaneValidationError(
            f"row {row_number}: {field} must be numeric"
        ) from exc
    if not math.isfinite(value):
        raise ResearchDataPlaneValidationError(
            f"row {row_number}: {field} must be finite"
        )
    if value < 0 and field in {"volume"}:
        raise ResearchDataPlaneValidationError(
            f"row {row_number}: {field} must be non-negative"
        )
    return value


def _normalize_row(raw: dict[str, Any], row_number: int) -> tuple[str, str, float, float, float, float, float]:
    missing = [column for column in _REQUIRED_COLUMNS if column not in raw]
    if missing:
        raise ResearchDataPlaneValidationError(
            f"missing required columns: {', '.join(missing)}"
        )
    code = str(raw["code"]).strip()
    if not _CODE_RE.fullmatch(code):
        raise ResearchDataPlaneValidationError(
            f"row {row_number}: code must be a six-digit A-share code"
        )
    trade_date = str(raw["trade_date"]).strip()
    if not _DATE_RE.fullmatch(trade_date):
        raise ResearchDataPlaneValidationError(
            f"row {row_number}: trade_date must use YYYY-MM-DD"
        )
    try:
        date.fromisoformat(trade_date)
    except ValueError as exc:
        raise ResearchDataPlaneValidationError(
            f"row {row_number}: trade_date is invalid"
        ) from exc
    values = tuple(_finite_number(raw[field], field, row_number) for field in _REQUIRED_COLUMNS[2:])
    open_, high, low, close, volume = values
    if high < max(open_, close) or low > min(open_, close) or high < low:
        raise ResearchDataPlaneValidationError(
            f"row {row_number}: OHLC relationship is invalid"
        )
    return code, trade_date, open_, high, low, close, volume


def _read_csv(source: str | Path) -> list[tuple[str, str, float, float, float, float, float]]:
    path = Path(source)
    if not path.is_file():
        raise ResearchDataPlaneUnavailableError("bulk dump file is unavailable")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ResearchDataPlaneValidationError("bulk dump has no header")
            rows = [_normalize_row(row, index) for index, row in enumerate(reader, start=2)]
    except UnicodeDecodeError as exc:
        raise ResearchDataPlaneValidationError("bulk dump must be UTF-8 CSV") from exc
    if not rows:
        raise ResearchDataPlaneValidationError("bulk dump contains no rows")
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row[0], row[1])
        if key in seen:
            raise ResearchDataPlaneValidationError(
                f"duplicate observation for {row[0]} on {row[1]}"
            )
        seen.add(key)
    return sorted(rows, key=lambda row: (row[1], row[0]))


def _write_parquet(
    root: Path,
    rows: Iterable[tuple[str, str, float, float, float, float, float]],
) -> tuple[Path, str]:
    artifact_dir = root / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="research-bars-", suffix=".parquet", dir=artifact_dir)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        connection = duckdb.connect(database=":memory:")
        try:
            connection.execute(
                "CREATE TABLE daily_bars ("
                "code VARCHAR, trade_date DATE, open DOUBLE, high DOUBLE, low DOUBLE, "
                "close DOUBLE, volume DOUBLE)"
            )
            connection.executemany(
                "INSERT INTO daily_bars VALUES (?, ?, ?, ?, ?, ?, ?)",
                list(rows),
            )
            connection.execute(
                "COPY daily_bars TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                [str(temp_path)],
            )
        finally:
            connection.close()
        digest = hashlib.sha256(temp_path.read_bytes()).hexdigest()
        target = _artifact_path(root, digest)
        if target.exists():
            temp_path.unlink()
        else:
            os.replace(temp_path, target)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return target, digest


def import_csv(
    source: str | Path,
    *,
    root: str | Path | None = None,
    imported_at: str | None = None,
) -> dict[str, Any]:
    """Validate a local bulk CSV and publish one immutable Parquet artifact."""
    rows = _read_csv(source)
    root_path = resolve_root(root)
    root_path.mkdir(parents=True, exist_ok=True)
    artifact, digest = _write_parquet(root_path, rows)
    dates = [row[1] for row in rows]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "provider_id": PROVIDER_ID,
        "adjustment": ADJUSTMENT,
        "license_status": LICENSE_STATUS,
        "source_kind": "LOCAL_BULK_DUMP",
        "source_name": Path(source).name,
        "artifact_sha256": digest,
        "artifact_file": artifact.name,
        "row_count": len(rows),
        "code_count": len({row[0] for row in rows}),
        "coverage_start": min(dates),
        "coverage_end": max(dates),
        "imported_at": imported_at or _utc_now(),
        "update_semantics": "immutable_artifact_per_import",
    }
    manifest_path = _manifest_path(root_path)
    fd, temp_name = tempfile.mkstemp(prefix="manifest-", suffix=".json", dir=root_path)
    os.close(fd)
    temp_manifest = Path(temp_name)
    try:
        temp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp_manifest, manifest_path)
    except Exception:
        temp_manifest.unlink(missing_ok=True)
        raise
    return manifest


def read_manifest(root: str | Path | None = None) -> dict[str, Any]:
    root_path = resolve_root(root)
    path = _manifest_path(root_path)
    if not path.is_file():
        raise ResearchDataPlaneUnavailableError("research bulk dataset is not configured")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchDataPlaneUnavailableError("research dataset manifest is unreadable") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ResearchDataPlaneValidationError("research dataset manifest schema is invalid")
    required = {"dataset_id", "artifact_sha256", "row_count", "coverage_start", "coverage_end"}
    if not required.issubset(manifest):
        raise ResearchDataPlaneValidationError("research dataset manifest is incomplete")
    digest = manifest["artifact_sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ResearchDataPlaneValidationError("research dataset artifact hash is invalid")
    artifact = _artifact_path(root_path, digest)
    if not artifact.is_file():
        raise ResearchDataPlaneUnavailableError("research dataset artifact is unavailable")
    actual_digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if actual_digest != digest:
        raise ResearchDataPlaneValidationError("research dataset artifact hash mismatch")
    return manifest


def _validate_query(code: str | None, date_from: str | None, date_to: str | None, limit: int, offset: int) -> None:
    if code is not None and not _CODE_RE.fullmatch(code):
        raise ResearchDataPlaneValidationError("code must be a six-digit A-share code")
    for field, value in (("date_from", date_from), ("date_to", date_to)):
        if value is not None:
            if not _DATE_RE.fullmatch(value):
                raise ResearchDataPlaneValidationError(f"{field} must use YYYY-MM-DD")
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ResearchDataPlaneValidationError(f"{field} is invalid") from exc
    if date_from and date_to and date_from > date_to:
        raise ResearchDataPlaneValidationError("date_from must not exceed date_to")
    if not 1 <= limit <= _MAX_LIMIT:
        raise ResearchDataPlaneValidationError(f"limit must be between 1 and {_MAX_LIMIT}")
    if offset < 0:
        raise ResearchDataPlaneValidationError("offset must be non-negative")


def query_daily_bars(
    *,
    root: str | Path | None = None,
    code: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    _validate_query(code, date_from, date_to, limit, offset)
    manifest = read_manifest(root)
    root_path = resolve_root(root)
    artifact = _artifact_path(root_path, str(manifest["artifact_sha256"]))
    predicates: list[str] = []
    params: list[Any] = [str(artifact)]
    if code is not None:
        predicates.append("code = ?")
        params.append(code)
    if date_from is not None:
        predicates.append("trade_date >= CAST(? AS DATE)")
        params.append(date_from)
    if date_to is not None:
        predicates.append("trade_date <= CAST(? AS DATE)")
        params.append(date_to)
    where = " WHERE " + " AND ".join(predicates) if predicates else ""
    query = (
        "SELECT code, CAST(trade_date AS VARCHAR), open, high, low, close, volume "
        "FROM read_parquet(?)" + where + " ORDER BY trade_date, code LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])
    connection = duckdb.connect(database=":memory:")
    try:
        result = connection.execute(query, params).fetchall()
    finally:
        connection.close()
    rows = [
        {
            "code": row[0],
            "trade_date": row[1],
            "open": row[2],
            "high": row[3],
            "low": row[4],
            "close": row[5],
            "volume": row[6],
        }
        for row in result
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": manifest["dataset_id"],
        "provider_id": manifest.get("provider_id", PROVIDER_ID),
        "adjustment": manifest.get("adjustment", ADJUSTMENT),
        "status": "normal",
        "fetched_at": manifest.get("imported_at"),
        "as_of": manifest["coverage_end"],
        "coverage": {
            "start": manifest["coverage_start"],
            "end": manifest["coverage_end"],
            "row_count": manifest["row_count"],
            "code_count": manifest["code_count"],
        },
        "provenance": {
            "source_kind": manifest.get("source_kind"),
            "source_name": manifest.get("source_name"),
            "artifact_sha256": manifest["artifact_sha256"],
            "license_status": manifest.get("license_status", LICENSE_STATUS),
        },
        "rows": rows,
        "returned_rows": len(rows),
        "next_offset": offset + len(rows) if len(rows) == limit else None,
        "limitations": ["Research Runtime 数据不是 Canonical Fact Authority。"],
    }


def build_unavailable_envelope(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "provider_id": PROVIDER_ID,
        "adjustment": ADJUSTMENT,
        "status": "unavailable",
        "fetched_at": _utc_now(),
        "as_of": None,
        "coverage": None,
        "provenance": {"source_kind": "LOCAL_BULK_DUMP", "license_status": LICENSE_STATUS},
        "rows": [],
        "returned_rows": 0,
        "next_offset": None,
        "limitations": [reason, "未将缺失数据伪装成事实或完整市场覆盖。"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import a local bulk daily-bars CSV")
    subparsers = parser.add_subparsers(dest="command", required=True)
    import_parser = subparsers.add_parser("import-csv")
    import_parser.add_argument("source")
    import_parser.add_argument("--root")
    args = parser.parse_args(argv)
    if args.command == "import-csv":
        print(json.dumps(import_csv(args.source, root=args.root), ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
