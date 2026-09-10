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

from research_data_plane_path import resolve_research_data_root as resolve_root

SCHEMA_VERSION = "research-data-plane.v0.1"
FULL_MARKET_SCHEMA_VERSION = "research-data-plane.full-market.v0.1"
PATTERN_SCHEMA_VERSION = "research-data-plane.patterns.v0.1"
DATASET_ID = "ashare_daily_unadjusted"
PROVIDER_ID = "local_bulk_dump"
ADJUSTMENT = "UNADJUSTED"
LICENSE_STATUS = "UNKNOWN"
_REQUIRED_COLUMNS = ("code", "trade_date", "open", "high", "low", "close", "volume")
_CODE_RE = re.compile(r"^\d{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_LIMIT = 1000
_MAX_OFFSET = 10_000_000
_FULL_MARKET_METRICS = frozenset(
    {
        "code",
        "latest_date",
        "latest_close",
        "return_5d",
        "return_20d",
        "return_60d",
        "ma20",
        "ma60",
        "close_vs_ma20",
        "close_vs_ma60",
        "avg_volume_20d",
        "current_volume",
        "volume_ratio_20d",
    }
)
_FULL_MARKET_NUMERIC_METRICS = frozenset(
    {
        "latest_close",
        "return_5d",
        "return_20d",
        "return_60d",
        "ma20",
        "ma60",
        "close_vs_ma20",
        "close_vs_ma60",
        "avg_volume_20d",
        "current_volume",
        "volume_ratio_20d",
    }
)
_FULL_MARKET_OPERATORS = frozenset({"gt", "gte", "lt", "lte", "eq", "neq"})
_FULL_MARKET_OPERATORS_SQL = {
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "eq": "=",
    "neq": "<>",
}

# The single-stock technical API predates the RDP pattern read model and keeps
# its historical trigger names.  The RDP contract uses stable semantic codes;
# the source alias is retained in each event's evidence for parity audits.
_PATTERN_EVENT_REGISTRY = (
    {
        "event_type": "close_above_20d_high",
        "source_trigger_type": "close_above_20d_high",
        "label": "收盘突破20日高点",
    },
    {
        "event_type": "close_below_20d_low",
        "source_trigger_type": "close_below_20d_low",
        "label": "收盘跌破20日低点",
    },
    {
        "event_type": "sma20_cross_above_sma60",
        "source_trigger_type": "sma_golden_cross",
        "label": "SMA20 上穿 SMA60",
    },
    {
        "event_type": "sma20_cross_below_sma60",
        "source_trigger_type": "sma_death_cross",
        "label": "SMA20 下穿 SMA60",
    },
    {
        "event_type": "volume_surge",
        "source_trigger_type": "volume_spike",
        "label": "5/20 日均量比超过 2.0",
    },
)
_PATTERN_EVENT_TYPES = frozenset(item["event_type"] for item in _PATTERN_EVENT_REGISTRY)
_PATTERN_EVENT_ORDER = {
    item["event_type"]: index for index, item in enumerate(_PATTERN_EVENT_REGISTRY)
}
_PATTERN_MAX_LIMIT = 100
_PATTERN_AS_OF_SEMANTICS = "ARTIFACT_DERIVED_LATEST_TRADE_DATE_AT_OR_BEFORE_REQUESTED_AS_OF"


class ResearchDataPlaneError(RuntimeError):
    """Base error for deterministic research data-plane failures."""


class ResearchDataPlaneValidationError(ResearchDataPlaneError):
    pass


class ResearchDataPlaneQueryValidationError(ResearchDataPlaneValidationError):
    """Invalid full-market query parameters, distinct from artifact corruption."""


class ResearchDataPlaneUnavailableError(ResearchDataPlaneError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


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
    if field in {"open", "high", "low", "close"} and value <= 0:
        raise ResearchDataPlaneValidationError(
            f"row {row_number}: {field} must be positive"
        )
    if field == "volume" and value < 0:
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
            actual_columns = tuple(column.strip() for column in reader.fieldnames)
            if actual_columns != _REQUIRED_COLUMNS:
                raise ResearchDataPlaneValidationError(
                    "bulk dump schema must exactly match: " + ",".join(_REQUIRED_COLUMNS)
                )
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
) -> tuple[Path, str, bool]:
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
        created = not target.exists()
        if created:
            os.replace(temp_path, target)
        else:
            temp_path.unlink()
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return target, digest, created


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
    artifact, digest, artifact_created = _write_parquet(root_path, rows)
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
        if artifact_created:
            artifact.unlink(missing_ok=True)
        raise
    return manifest


def _manifest_date(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise ResearchDataPlaneValidationError(f"research dataset manifest {field} is invalid")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ResearchDataPlaneValidationError(f"research dataset manifest {field} is invalid") from exc
    return value


def _manifest_datetime(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchDataPlaneValidationError(f"research dataset manifest {field} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchDataPlaneValidationError(f"research dataset manifest {field} is invalid") from exc
    if parsed.tzinfo is None:
        raise ResearchDataPlaneValidationError(f"research dataset manifest {field} must include timezone")
    return value


def _manifest_count(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ResearchDataPlaneValidationError(f"research dataset manifest {field} is invalid")
    return value


def _read_artifact_bytes(artifact: Path) -> bytes:
    try:
        if not artifact.is_file():
            raise ResearchDataPlaneUnavailableError("research dataset artifact is unavailable")
        return artifact.read_bytes()
    except ResearchDataPlaneUnavailableError:
        raise
    except OSError as exc:
        raise ResearchDataPlaneUnavailableError("research dataset artifact is unreadable") from exc


def read_manifest(root: str | Path | None = None) -> dict[str, Any]:
    root_path = resolve_root(root)
    path = _manifest_path(root_path)
    try:
        if not path.is_file():
            raise ResearchDataPlaneUnavailableError("research bulk dataset is not configured")
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except ResearchDataPlaneUnavailableError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchDataPlaneUnavailableError("research dataset manifest is unreadable") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ResearchDataPlaneValidationError("research dataset manifest schema is invalid")
    required = {
        "dataset_id",
        "provider_id",
        "adjustment",
        "license_status",
        "source_kind",
        "source_name",
        "artifact_sha256",
        "artifact_file",
        "row_count",
        "code_count",
        "coverage_start",
        "coverage_end",
        "imported_at",
        "update_semantics",
    }
    if not required.issubset(manifest):
        raise ResearchDataPlaneValidationError("research dataset manifest is incomplete")
    expected_values = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "provider_id": PROVIDER_ID,
        "adjustment": ADJUSTMENT,
        "license_status": LICENSE_STATUS,
        "source_kind": "LOCAL_BULK_DUMP",
        "update_semantics": "immutable_artifact_per_import",
    }
    for field, expected in expected_values.items():
        if manifest.get(field) != expected:
            raise ResearchDataPlaneValidationError(
                f"research dataset manifest {field} is invalid"
            )
    if not isinstance(manifest["source_name"], str) or not manifest["source_name"].strip():
        raise ResearchDataPlaneValidationError("research dataset manifest source_name is invalid")
    row_count = _manifest_count(manifest["row_count"], "row_count")
    code_count = _manifest_count(manifest["code_count"], "code_count")
    if code_count > row_count:
        raise ResearchDataPlaneValidationError(
            "research dataset manifest code_count exceeds row_count"
        )
    coverage_start = _manifest_date(manifest["coverage_start"], "coverage_start")
    coverage_end = _manifest_date(manifest["coverage_end"], "coverage_end")
    if coverage_start > coverage_end:
        raise ResearchDataPlaneValidationError(
            "research dataset manifest coverage_start exceeds coverage_end"
        )
    _manifest_datetime(manifest["imported_at"], "imported_at")
    digest = manifest["artifact_sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ResearchDataPlaneValidationError("research dataset artifact hash is invalid")
    artifact = _artifact_path(root_path, digest)
    if manifest.get("artifact_file") != artifact.name:
        raise ResearchDataPlaneValidationError("research dataset artifact filename is invalid")
    actual_digest = hashlib.sha256(_read_artifact_bytes(artifact)).hexdigest()
    if actual_digest != digest:
        raise ResearchDataPlaneValidationError("research dataset artifact hash mismatch")
    connection = duckdb.connect(database=":memory:")
    try:
        try:
            stats = connection.execute(
                "SELECT COUNT(*), COUNT(DISTINCT code), "
                "CAST(MIN(trade_date) AS VARCHAR), CAST(MAX(trade_date) AS VARCHAR) "
                "FROM read_parquet(?)",
                [str(artifact)],
            ).fetchone()
        except Exception as exc:
            raise ResearchDataPlaneValidationError(
                "research dataset artifact schema is invalid"
            ) from exc
    finally:
        connection.close()
    artifact_row_count = int(stats[0] or 0)
    artifact_code_count = int(stats[1] or 0)
    artifact_coverage_start = stats[2]
    artifact_coverage_end = stats[3]
    if (
        artifact_row_count != row_count
        or artifact_code_count != code_count
        or artifact_coverage_start != coverage_start
        or artifact_coverage_end != coverage_end
    ):
        raise ResearchDataPlaneValidationError(
            "research dataset manifest metadata does not match artifact"
        )
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
    if not 0 <= offset <= _MAX_OFFSET:
        raise ResearchDataPlaneValidationError(
            f"offset must be between 0 and {_MAX_OFFSET}"
        )


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
        try:
            result = connection.execute(query, params).fetchall()
        except Exception as exc:
            raise ResearchDataPlaneValidationError(
                "research dataset query failed closed"
            ) from exc
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


def _validate_full_market_query(
    *,
    as_of: str | None,
    latest: bool,
    filter_metric: str | None,
    filter_operator: str | None,
    filter_value: float | None,
    filters: list[dict[str, Any]] | None,
    sort_by: str,
    sort_order: str,
    limit: int,
    offset: int,
) -> list[tuple[str, str, float]]:
    if as_of is not None:
        if not _DATE_RE.fullmatch(as_of):
            raise ResearchDataPlaneQueryValidationError("as_of must use YYYY-MM-DD")
        try:
            date.fromisoformat(as_of)
        except ValueError as exc:
            raise ResearchDataPlaneQueryValidationError("as_of is invalid") from exc
    if not isinstance(latest, bool):
        raise ResearchDataPlaneQueryValidationError("latest must be boolean")
    if not latest and as_of is None:
        raise ResearchDataPlaneQueryValidationError("as_of is required when latest=false")
    if filters is not None:
        if filter_metric is not None or filter_operator is not None or filter_value is not None:
            raise ResearchDataPlaneQueryValidationError(
                "filters cannot be combined with legacy filter fields"
            )
        if not isinstance(filters, list):
            raise ResearchDataPlaneQueryValidationError("filters must be a JSON array")
        if len(filters) > 20:
            raise ResearchDataPlaneQueryValidationError("filters must contain at most 20 conditions")
        normalized_filters: list[tuple[str, str, float]] = []
        for item in filters:
            if not isinstance(item, dict) or set(item) != {"metric", "operator", "value"}:
                raise ResearchDataPlaneQueryValidationError(
                    "each filter must contain metric, operator, and value"
                )
            metric = item["metric"]
            operator = item["operator"]
            value = item["value"]
            if not isinstance(metric, str) or metric not in _FULL_MARKET_NUMERIC_METRICS:
                raise ResearchDataPlaneQueryValidationError(
                    f"filter metric must be a numeric named metric: {', '.join(sorted(_FULL_MARKET_NUMERIC_METRICS))}"
                )
            if not isinstance(operator, str) or operator not in _FULL_MARKET_OPERATORS:
                raise ResearchDataPlaneQueryValidationError(
                    f"filter operator must be one of: {', '.join(sorted(_FULL_MARKET_OPERATORS))}"
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ResearchDataPlaneQueryValidationError("filter value must be a finite number")
            try:
                numeric = float(value)
            except OverflowError as exc:
                raise ResearchDataPlaneQueryValidationError("filter value must be a finite number") from exc
            if not math.isfinite(numeric):
                raise ResearchDataPlaneQueryValidationError("filter value must be a finite number")
            normalized_filters.append((metric, operator, numeric))
    elif filter_metric is None:
        if filter_operator is not None or filter_value is not None:
            raise ResearchDataPlaneQueryValidationError(
                "filter_metric is required when a filter is provided"
            )
        normalized_filters = []
    else:
        if filter_metric not in _FULL_MARKET_NUMERIC_METRICS:
            raise ResearchDataPlaneQueryValidationError(
                f"filter_metric must be a numeric named metric: {', '.join(sorted(_FULL_MARKET_NUMERIC_METRICS))}"
            )
        if filter_operator is None or filter_operator not in _FULL_MARKET_OPERATORS:
            raise ResearchDataPlaneQueryValidationError(
                f"filter_operator must be one of: {', '.join(sorted(_FULL_MARKET_OPERATORS))}"
            )
        if filter_value is None:
            raise ResearchDataPlaneQueryValidationError("filter_value is required when filter_metric is provided")
        try:
            numeric = float(filter_value)
        except (TypeError, ValueError) as exc:
            raise ResearchDataPlaneQueryValidationError("filter_value must be numeric") from exc
        if not math.isfinite(numeric):
            raise ResearchDataPlaneQueryValidationError("filter_value must be finite")
        normalized_filters = [(filter_metric, filter_operator, numeric)]
    if sort_by not in _FULL_MARKET_METRICS:
        raise ResearchDataPlaneQueryValidationError(
            f"sort_by must be one of: {', '.join(sorted(_FULL_MARKET_METRICS))}"
        )
    if sort_order not in {"asc", "desc"}:
        raise ResearchDataPlaneQueryValidationError("sort_order must be asc or desc")
    if not 1 <= limit <= _MAX_LIMIT:
        raise ResearchDataPlaneQueryValidationError(f"limit must be between 1 and {_MAX_LIMIT}")
    if not 0 <= offset <= _MAX_OFFSET:
        raise ResearchDataPlaneQueryValidationError(f"offset must be between 0 and {_MAX_OFFSET}")
    return normalized_filters


def _full_market_provenance(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_kind": manifest.get("source_kind"),
        "source_name": manifest.get("source_name"),
        "artifact_sha256": manifest["artifact_sha256"],
        "license_status": manifest.get("license_status", LICENSE_STATUS),
    }


def build_full_market_unavailable_envelope(
    reason: str,
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": FULL_MARKET_SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "provider_id": PROVIDER_ID,
        "adjustment": ADJUSTMENT,
        "status": "unavailable",
        "fetched_at": _utc_now(),
        "as_of": as_of,
        "latest_date": None,
        "coverage": None,
        "provenance": {
            "source_kind": "LOCAL_BULK_DUMP",
            "source_name": None,
            "artifact_sha256": None,
            "license_status": LICENSE_STATUS,
        },
        "breadth": {
            "ma20": {
                "breadth": None,
                "above_count": 0,
                "evaluable_count": 0,
                "insufficient_count": 0,
                "status": "INSUFFICIENT_HISTORY",
            },
            "ma60": {
                "breadth": None,
                "above_count": 0,
                "evaluable_count": 0,
                "insufficient_count": 0,
                "status": "INSUFFICIENT_HISTORY",
            },
        },
        "rows": [],
        "returned_rows": 0,
        "total_rows": 0,
        "next_offset": None,
        "limitations": [reason, "未将缺失数据伪装成事实或回退到逐票 HTTP/K 线请求。"],
    }


def query_full_market(
    *,
    root: str | Path | None = None,
    as_of: str | None = None,
    latest: bool = True,
    filter_metric: str | None = None,
    filter_operator: str | None = None,
    filter_value: float | None = None,
    filters: list[dict[str, Any]] | None = None,
    sort_by: str = "code",
    sort_order: str = "asc",
    sort_metric: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    """Build one bounded full-market cross-section from the immutable Parquet artifact.

    This path intentionally performs set-based DuckDB aggregation. It does not invoke
    Screener's per-stock evaluator, any HTTP provider, or the legacy K-line client.
    ``latest=true`` resolves the latest available observation at or before ``as_of``;
    ``latest=false`` requires an explicit ``as_of`` date.
    """
    if sort_metric is not None:
        if sort_by != "code":
            raise ResearchDataPlaneValidationError("use only one of sort_by and sort_metric")
        sort_by = sort_metric
    normalized_filters = _validate_full_market_query(
        as_of=as_of,
        latest=latest,
        filter_metric=filter_metric,
        filter_operator=filter_operator,
        filter_value=filter_value,
        filters=filters,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )
    manifest = read_manifest(root)
    root_path = resolve_root(root)
    artifact = _artifact_path(root_path, str(manifest["artifact_sha256"]))
    connection = duckdb.connect(database=":memory:")
    try:
        try:
            target_row = connection.execute(
                "SELECT MAX(trade_date) FROM read_parquet(?) "
                "WHERE trade_date <= CAST(? AS DATE)",
                [str(artifact), as_of or manifest["coverage_end"]],
            ).fetchone()
            target_date = target_row[0] if target_row else None
            if target_date is None:
                return build_full_market_unavailable_envelope(
                    "as_of 之前没有可用的研究数据",
                    as_of=as_of,
                )
            target_date_text = target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date)

            base_cte = (
                "WITH ranked AS ("
                "SELECT code, trade_date, close, volume, "
                "ROW_NUMBER() OVER (PARTITION BY code ORDER BY trade_date DESC) AS rn "
                "FROM read_parquet(?) WHERE trade_date <= CAST(? AS DATE)"
                "), features AS ("
                "SELECT code, "
                "MAX(CASE WHEN rn = 1 THEN CAST(trade_date AS VARCHAR) END) AS latest_date, "
                "MAX(CASE WHEN rn = 1 THEN close END) AS latest_close, "
                "MAX(CASE WHEN rn = 6 THEN close END) AS prior_5_close, "
                "MAX(CASE WHEN rn = 21 THEN close END) AS prior_20_close, "
                "MAX(CASE WHEN rn = 61 THEN close END) AS prior_60_close, "
                "AVG(close) FILTER (WHERE rn <= 20) AS ma20, "
                "AVG(close) FILTER (WHERE rn <= 60) AS ma60, "
                "AVG(volume) FILTER (WHERE rn <= 20) AS avg_volume_20d, "
                "MAX(CASE WHEN rn = 1 THEN volume END) AS current_volume, "
                "COUNT(*) AS observations_count, "
                "SUM(CASE WHEN rn <= 20 THEN 1 ELSE 0 END) AS observations_20, "
                "SUM(CASE WHEN rn <= 60 THEN 1 ELSE 0 END) AS observations_60 "
                "FROM ranked GROUP BY code"
                "), computed AS ("
                "SELECT code, latest_date, latest_close, "
                "CASE WHEN observations_count >= 6 THEN latest_close / prior_5_close - 1 END AS return_5d, "
                "CASE WHEN observations_count >= 21 THEN latest_close / prior_20_close - 1 END AS return_20d, "
                "CASE WHEN observations_count >= 61 THEN latest_close / prior_60_close - 1 END AS return_60d, "
                "CASE WHEN observations_20 >= 20 THEN ma20 END AS ma20, "
                "CASE WHEN observations_60 >= 60 THEN ma60 END AS ma60, "
                "CASE WHEN observations_20 >= 20 THEN latest_close / ma20 - 1 END AS close_vs_ma20, "
                "CASE WHEN observations_60 >= 60 THEN latest_close / ma60 - 1 END AS close_vs_ma60, "
                "CASE WHEN observations_20 >= 20 THEN avg_volume_20d END AS avg_volume_20d, "
                "current_volume, "
                "CASE WHEN observations_20 >= 20 AND avg_volume_20d > 0 THEN current_volume / avg_volume_20d END AS volume_ratio_20d, "
                "observations_count, "
                "CASE WHEN observations_count >= 6 THEN 'normal' ELSE 'INSUFFICIENT_HISTORY' END AS return_5d_status, "
                "CASE WHEN observations_count >= 21 THEN 'normal' ELSE 'INSUFFICIENT_HISTORY' END AS return_20d_status, "
                "CASE WHEN observations_count >= 61 THEN 'normal' ELSE 'INSUFFICIENT_HISTORY' END AS return_60d_status, "
                "CASE WHEN observations_20 >= 20 THEN 'normal' ELSE 'INSUFFICIENT_HISTORY' END AS ma20_status, "
                "CASE WHEN observations_60 >= 60 THEN 'normal' ELSE 'INSUFFICIENT_HISTORY' END AS ma60_status, "
                "CASE WHEN observations_20 >= 20 THEN 'normal' ELSE 'INSUFFICIENT_HISTORY' END AS close_vs_ma20_status, "
                "CASE WHEN observations_60 >= 60 THEN 'normal' ELSE 'INSUFFICIENT_HISTORY' END AS close_vs_ma60_status, "
                "CASE WHEN observations_20 >= 20 THEN 'normal' ELSE 'INSUFFICIENT_HISTORY' END AS avg_volume_20d_status, "
                "CASE WHEN observations_20 >= 20 AND avg_volume_20d > 0 THEN 'normal' ELSE 'INSUFFICIENT_HISTORY' END AS volume_ratio_20d_status "
                "FROM features"
                ") "
            )
            cte_params = [str(artifact), target_date_text]
            stats = connection.execute(
                base_cte
                + "SELECT COUNT(*), "
                + "COUNT(*) FILTER (WHERE ma20_status = 'normal'), "
                + "COUNT(*) FILTER (WHERE ma20_status != 'normal'), "
                + "COUNT(*) FILTER (WHERE close_vs_ma20 > 0), "
                + "COUNT(*) FILTER (WHERE ma60_status = 'normal'), "
                + "COUNT(*) FILTER (WHERE ma60_status != 'normal'), "
                + "COUNT(*) FILTER (WHERE close_vs_ma60 > 0) FROM computed",
                cte_params,
            ).fetchone()
            total_universe = int(stats[0] or 0)
            ma20_evaluable = int(stats[1] or 0)
            ma20_insufficient = int(stats[2] or 0)
            ma20_above = int(stats[3] or 0)
            ma60_evaluable = int(stats[4] or 0)
            ma60_insufficient = int(stats[5] or 0)
            ma60_above = int(stats[6] or 0)

            filter_clause = ""
            filter_params: list[Any] = []
            if normalized_filters:
                filter_clause = " WHERE " + " AND ".join(
                    f"{metric} {_FULL_MARKET_OPERATORS_SQL[operator]} ?"
                    for metric, operator, _ in normalized_filters
                )
                filter_params = [value for _, _, value in normalized_filters]
            rows_query = (
                base_cte
                + "SELECT code, latest_date, latest_close, return_5d, return_20d, return_60d, "
                "ma20, ma60, close_vs_ma20, close_vs_ma60, avg_volume_20d, current_volume, volume_ratio_20d, "
                "observations_count, return_5d_status, return_20d_status, return_60d_status, ma20_status, ma60_status, "
                "close_vs_ma20_status, close_vs_ma60_status, avg_volume_20d_status, volume_ratio_20d_status "
                "FROM computed"
                + filter_clause
                + f" ORDER BY {sort_by} {sort_order.upper()} NULLS LAST, code ASC LIMIT ? OFFSET ?"
            )
            rows_result = connection.execute(
                rows_query,
                cte_params + filter_params + [limit, offset],
            ).fetchall()
            count_query = base_cte + "SELECT COUNT(*) FROM computed" + filter_clause
            filtered_total = int(
                connection.execute(count_query, cte_params + filter_params).fetchone()[0] or 0
            )
        except Exception as exc:
            raise ResearchDataPlaneValidationError("full-market cross-section query failed closed") from exc
    finally:
        connection.close()

    columns = (
        "code", "latest_date", "latest_close", "return_5d", "return_20d", "return_60d",
        "ma20", "ma60", "close_vs_ma20", "close_vs_ma60", "avg_volume_20d", "current_volume",
        "volume_ratio_20d", "observations_count", "return_5d_status", "return_20d_status",
        "return_60d_status", "ma20_status", "ma60_status", "close_vs_ma20_status",
        "close_vs_ma60_status", "avg_volume_20d_status", "volume_ratio_20d_status",
    )
    output_rows: list[dict[str, Any]] = []
    for raw in rows_result:
        row = dict(zip(columns, raw))
        metric_status = {
            key: row[f"{key}_status"]
            for key in (
                "return_5d", "return_20d", "return_60d", "ma20", "ma60",
                "close_vs_ma20", "close_vs_ma60", "avg_volume_20d", "volume_ratio_20d",
            )
        }
        row["metric_status"] = metric_status
        output_rows.append(row)

    def breadth_payload(evaluable: int, insufficient: int, above: int) -> dict[str, Any]:
        return {
            "breadth": (above / evaluable) if evaluable else None,
            "above_count": above,
            "evaluable_count": evaluable,
            "insufficient_count": insufficient,
            "status": "normal" if evaluable else "INSUFFICIENT_HISTORY",
        }

    return {
        "schema_version": FULL_MARKET_SCHEMA_VERSION,
        "dataset_id": manifest["dataset_id"],
        "provider_id": manifest.get("provider_id", PROVIDER_ID),
        "adjustment": manifest.get("adjustment", ADJUSTMENT),
        "status": "normal",
        "fetched_at": manifest.get("imported_at"),
        "as_of": target_date_text,
        "latest_date": target_date_text,
        "coverage": {
            "start": manifest["coverage_start"],
            "end": manifest["coverage_end"],
            "row_count": manifest["row_count"],
            "code_count": manifest["code_count"],
            "universe_count": total_universe,
        },
        "provenance": _full_market_provenance(manifest),
        "breadth": {
            "ma20": breadth_payload(ma20_evaluable, ma20_insufficient, ma20_above),
            "ma60": breadth_payload(ma60_evaluable, ma60_insufficient, ma60_above),
        },
        "rows": output_rows,
        "returned_rows": len(output_rows),
        "total_rows": filtered_total,
        "next_offset": offset + len(output_rows) if offset + len(output_rows) < filtered_total else None,
        "limitations": [
            "Research Runtime 数据不是 Canonical Fact Authority。",
            "当前 schema 仅提供 volume；未声明 turnover、amount 或 liquidity amount。",
            "各指标在历史观测不足时返回 null，并标记 INSUFFICIENT_HISTORY。",
        ],
    }


def _validate_pattern_query(
    *,
    as_of: str | None,
    latest: bool,
    event_type: str | None,
    limit: int,
    offset: int,
) -> str | None:
    if as_of is not None:
        if not _DATE_RE.fullmatch(as_of):
            raise ResearchDataPlaneQueryValidationError("as_of must use YYYY-MM-DD")
        try:
            date.fromisoformat(as_of)
        except ValueError as exc:
            raise ResearchDataPlaneQueryValidationError("as_of is invalid") from exc
    if not isinstance(latest, bool):
        raise ResearchDataPlaneQueryValidationError("latest must be boolean")
    if not latest and as_of is None:
        raise ResearchDataPlaneQueryValidationError("as_of is required when latest=false")
    if event_type is not None and event_type not in _PATTERN_EVENT_TYPES:
        raise ResearchDataPlaneQueryValidationError(
            "event_type must be one of: " + ", ".join(item["event_type"] for item in _PATTERN_EVENT_REGISTRY)
        )
    if not 1 <= limit <= _PATTERN_MAX_LIMIT:
        raise ResearchDataPlaneQueryValidationError(
            f"limit must be between 1 and {_PATTERN_MAX_LIMIT}"
        )
    if not 0 <= offset <= _MAX_OFFSET:
        raise ResearchDataPlaneQueryValidationError(
            f"offset must be between 0 and {_MAX_OFFSET}"
        )
    return event_type


def _pattern_provenance(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset_id": manifest["dataset_id"],
        "provider_id": manifest.get("provider_id", PROVIDER_ID),
        "adjustment": manifest.get("adjustment", ADJUSTMENT),
        "source_kind": manifest.get("source_kind"),
        "source_name": manifest.get("source_name"),
        "license_status": manifest.get("license_status", LICENSE_STATUS),
    }


def build_patterns_unavailable_envelope(
    reason: str,
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": PATTERN_SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "provider_id": PROVIDER_ID,
        "adjustment": ADJUSTMENT,
        "status": "unavailable",
        "fetched_at": _utc_now(),
        "requested_as_of": as_of,
        "as_of": None,
        "as_of_semantics": _PATTERN_AS_OF_SEMANTICS,
        "latest_date": None,
        "source": None,
        "artifact_identity": None,
        "coverage": None,
        "source_scope": None,
        "pattern_registry": list(_PATTERN_EVENT_REGISTRY),
        "event_type_filter": None,
        "total_universe": 0,
        "evaluable_count": 0,
        "matched_stock_count": 0,
        "not_evaluable_count": 0,
        "not_evaluable": [],
        "not_evaluable_returned": 0,
        "events": [],
        "returned_events": 0,
        "total_events": 0,
        "next_offset": None,
        "formal_state_write": {"performed": False, "scope": "pattern discovery read-only"},
        "limitations": [reason, "Pattern 扫描只使用现有本地 RDP artifact；未回退逐票 HTTP 请求。"],
    }


def _pattern_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _pattern_date(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _evaluate_pattern_record(
    row: dict[str, Any],
    registry: Iterable[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Shape one set-based latest-row result into matched or NOT_EVALUABLE events."""
    code = str(row["code"])
    trade_date = _pattern_date(row.get("trade_date"))
    current_close = _pattern_number(row.get("close"))
    observations_count = int(row.get("observations_count") or 0)
    prior_high_count = int(row.get("prior_high_count") or 0)
    prior_low_count = int(row.get("prior_low_count") or 0)
    close20_count = int(row.get("close20_count") or 0)
    close60_count = int(row.get("close60_count") or 0)
    volume5_count = int(row.get("volume5_count") or 0)
    volume20_count = int(row.get("volume20_count") or 0)
    prior_high = _pattern_number(row.get("prior_high"))
    prior_low = _pattern_number(row.get("prior_low"))
    sma20 = _pattern_number(row.get("sma20"))
    sma60 = _pattern_number(row.get("sma60"))
    previous_sma20 = _pattern_number(row.get("previous_sma20"))
    previous_sma60 = _pattern_number(row.get("previous_sma60"))
    avg_volume5 = _pattern_number(row.get("avg_volume5"))
    avg_volume20 = _pattern_number(row.get("avg_volume20"))
    current_volume = _pattern_number(row.get("volume"))

    events: list[dict[str, Any]] = []
    not_evaluable: list[dict[str, Any]] = []

    reason_text = {
        "INSUFFICIENT_HISTORY": "历史观测不足，不能把未触发与不可评估混同。",
        "MISSING_CLOSE": "所需收盘价历史含缺失值。",
        "MISSING_HIGH": "过去20日 high 历史含缺失值。",
        "MISSING_LOW": "过去20日 low 历史含缺失值。",
        "MISSING_VOLUME": "所需成交量历史含缺失值。",
        "ZERO_VOLUME_BASELINE": "20日平均成交量为零，量比不可评估。",
    }

    def unavailable(spec: dict[str, str], reason_code: str) -> None:
        not_evaluable.append(
            {
                "code": code,
                "trade_date": trade_date,
                "event_type": spec["event_type"],
                "status": "NOT_EVALUABLE",
                "reason_code": reason_code,
                "reason": reason_text[reason_code],
            }
        )

    def matched(spec: dict[str, str], evidence: dict[str, Any]) -> None:
        events.append(
            {
                "code": code,
                "trade_date": trade_date,
                "event_type": spec["event_type"],
                "event_label": spec["label"],
                "status": "MATCHED",
                "current_close": current_close,
                "evidence": {
                    **evidence,
                    "source_trigger_type": spec["source_trigger_type"],
                },
            }
        )

    for spec in registry:
        event_type = spec["event_type"]
        if event_type == "close_above_20d_high":
            if observations_count < 21:
                unavailable(spec, "INSUFFICIENT_HISTORY")
            elif prior_high_count < 20:
                unavailable(spec, "MISSING_HIGH")
            elif current_close is None or prior_high is None:
                unavailable(spec, "MISSING_CLOSE" if current_close is None else "MISSING_HIGH")
            elif current_close > prior_high:
                matched(
                    spec,
                    {
                        "current_close": current_close,
                        "previous_20d_high": prior_high,
                        "window_size": 20,
                        "comparison": "current_close > previous_20d_high",
                    },
                )
        elif event_type == "close_below_20d_low":
            if observations_count < 21:
                unavailable(spec, "INSUFFICIENT_HISTORY")
            elif prior_low_count < 20:
                unavailable(spec, "MISSING_LOW")
            elif current_close is None or prior_low is None:
                unavailable(spec, "MISSING_CLOSE" if current_close is None else "MISSING_LOW")
            elif current_close < prior_low:
                matched(
                    spec,
                    {
                        "current_close": current_close,
                        "previous_20d_low": prior_low,
                        "window_size": 20,
                        "comparison": "current_close < previous_20d_low",
                    },
                )
        elif event_type == "sma20_cross_above_sma60":
            if observations_count < 61:
                unavailable(spec, "INSUFFICIENT_HISTORY")
            elif (
                close20_count < 20
                or close60_count < 60
                or any(value is None for value in (sma20, sma60, previous_sma20, previous_sma60))
            ):
                unavailable(spec, "MISSING_CLOSE")
            elif previous_sma20 <= previous_sma60 and sma20 > sma60:
                matched(
                    spec,
                    {
                        "previous_sma20": previous_sma20,
                        "previous_sma60": previous_sma60,
                        "current_sma20": sma20,
                        "current_sma60": sma60,
                        "comparison": "previous_sma20 <= previous_sma60 and current_sma20 > current_sma60",
                    },
                )
        elif event_type == "sma20_cross_below_sma60":
            if observations_count < 61:
                unavailable(spec, "INSUFFICIENT_HISTORY")
            elif (
                close20_count < 20
                or close60_count < 60
                or any(value is None for value in (sma20, sma60, previous_sma20, previous_sma60))
            ):
                unavailable(spec, "MISSING_CLOSE")
            elif previous_sma20 >= previous_sma60 and sma20 < sma60:
                matched(
                    spec,
                    {
                        "previous_sma20": previous_sma20,
                        "previous_sma60": previous_sma60,
                        "current_sma20": sma20,
                        "current_sma60": sma60,
                        "comparison": "previous_sma20 >= previous_sma60 and current_sma20 < current_sma60",
                    },
                )
        elif event_type == "volume_surge":
            if observations_count < 20:
                unavailable(spec, "INSUFFICIENT_HISTORY")
            elif volume5_count < 5 or volume20_count < 20:
                unavailable(spec, "MISSING_VOLUME")
            elif avg_volume5 is None or avg_volume20 is None or current_volume is None:
                unavailable(spec, "MISSING_VOLUME")
            elif avg_volume20 <= 0:
                unavailable(spec, "ZERO_VOLUME_BASELINE")
            else:
                ratio = avg_volume5 / avg_volume20
                if ratio > 2.0:
                    matched(
                        spec,
                        {
                            "current_volume": current_volume,
                            "avg_volume_5": avg_volume5,
                            "avg_volume_20": avg_volume20,
                            "volume_ratio_5_20": ratio,
                            "threshold": 2.0,
                            "comparison": "avg_volume_5 / avg_volume_20 > 2.0",
                        },
                    )

    return events, not_evaluable


def query_patterns(
    *,
    root: str | Path | None = None,
    as_of: str | None = None,
    latest: bool = True,
    event_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Scan the local RDP artifact once for the five existing technical events.

    SQL computes one latest observation row per code with bounded windows.  Python
    only shapes those rows into the read model; it never fetches or evaluates a
    stock through a per-security HTTP/K-line path.
    """
    selected_event_type = _validate_pattern_query(
        as_of=as_of,
        latest=latest,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )
    manifest = read_manifest(root)
    root_path = resolve_root(root)
    artifact = _artifact_path(root_path, str(manifest["artifact_sha256"]))
    registry = tuple(
        item for item in _PATTERN_EVENT_REGISTRY
        if selected_event_type is None or item["event_type"] == selected_event_type
    )
    cutoff = as_of or manifest["coverage_end"]
    query = """
        WITH source AS (
            SELECT
                code,
                CAST(trade_date AS DATE) AS trade_date,
                high,
                low,
                close,
                volume
            FROM read_parquet(?)
            WHERE trade_date <= CAST(? AS DATE)
        ), meta AS (
            SELECT
                COUNT(*) AS raw_row_count,
                COUNT(DISTINCT code || '|' || CAST(trade_date AS VARCHAR)) AS unique_observation_count,
                COUNT(*) FILTER (WHERE code IS NULL OR trade_date IS NULL) AS invalid_identity_count,
                COUNT(DISTINCT code) AS total_universe,
                CAST(MIN(trade_date) AS VARCHAR) AS source_start,
                CAST(MAX(trade_date) AS VARCHAR) AS source_end
            FROM source
        ), ordered AS (
            SELECT
                source.*,
                ROW_NUMBER() OVER (PARTITION BY code ORDER BY trade_date ASC) AS sequence_no
            FROM source
        ), windows AS (
            SELECT
                ordered.*,
                COUNT(close) OVER (
                    PARTITION BY code ORDER BY trade_date
                    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                ) AS close20_count,
                AVG(close) OVER (
                    PARTITION BY code ORDER BY trade_date
                    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                ) AS sma20,
                COUNT(close) OVER (
                    PARTITION BY code ORDER BY trade_date
                    ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
                ) AS close60_count,
                AVG(close) OVER (
                    PARTITION BY code ORDER BY trade_date
                    ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
                ) AS sma60,
                COUNT(high) OVER (
                    PARTITION BY code ORDER BY trade_date
                    ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                ) AS prior_high_count,
                MAX(high) OVER (
                    PARTITION BY code ORDER BY trade_date
                    ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                ) AS prior_high,
                COUNT(low) OVER (
                    PARTITION BY code ORDER BY trade_date
                    ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                ) AS prior_low_count,
                MIN(low) OVER (
                    PARTITION BY code ORDER BY trade_date
                    ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                ) AS prior_low,
                COUNT(volume) OVER (
                    PARTITION BY code ORDER BY trade_date
                    ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                ) AS volume5_count,
                AVG(volume) OVER (
                    PARTITION BY code ORDER BY trade_date
                    ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                ) AS avg_volume5,
                COUNT(volume) OVER (
                    PARTITION BY code ORDER BY trade_date
                    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                ) AS volume20_count,
                AVG(volume) OVER (
                    PARTITION BY code ORDER BY trade_date
                    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                ) AS avg_volume20
            FROM ordered
        ), crossings AS (
            SELECT
                windows.*,
                LAG(sma20) OVER (PARTITION BY code ORDER BY trade_date) AS previous_sma20,
                LAG(sma60) OVER (PARTITION BY code ORDER BY trade_date) AS previous_sma60
            FROM windows
        ), latest AS (
            SELECT
                crossings.*,
                ROW_NUMBER() OVER (PARTITION BY code ORDER BY trade_date DESC) AS reverse_sequence,
                COUNT(*) OVER (PARTITION BY code) AS observations_count
            FROM crossings
        )
        SELECT
            meta.raw_row_count,
            meta.unique_observation_count,
            meta.invalid_identity_count,
            meta.total_universe,
            meta.source_start,
            meta.source_end,
            latest.code,
            latest.trade_date,
            latest.close,
            latest.observations_count,
            latest.close20_count,
            latest.close60_count,
            latest.prior_high_count,
            latest.prior_high,
            latest.prior_low_count,
            latest.prior_low,
            latest.sma20,
            latest.sma60,
            latest.previous_sma20,
            latest.previous_sma60,
            latest.volume5_count,
            latest.avg_volume5,
            latest.volume20_count,
            latest.avg_volume20,
            latest.volume
        FROM meta
        LEFT JOIN latest ON latest.reverse_sequence = 1
        ORDER BY latest.code ASC NULLS LAST
    """
    connection = duckdb.connect(database=":memory:")
    try:
        try:
            rows_result = connection.execute(query, [str(artifact), cutoff]).fetchall()
        except Exception as exc:
            raise ResearchDataPlaneValidationError("pattern scan query failed closed") from exc
    finally:
        connection.close()

    columns = (
        "raw_row_count", "unique_observation_count", "invalid_identity_count", "total_universe",
        "source_start", "source_end", "code", "trade_date", "close", "observations_count",
        "close20_count", "close60_count", "prior_high_count", "prior_high", "prior_low_count",
        "prior_low", "sma20", "sma60", "previous_sma20", "previous_sma60", "volume5_count",
        "avg_volume5", "volume20_count", "avg_volume20", "volume",
    )
    if not rows_result:
        return build_patterns_unavailable_envelope("as_of 之前没有可用的研究数据", as_of=as_of)
    raw_rows = [dict(zip(columns, raw)) for raw in rows_result]
    meta = raw_rows[0]
    raw_row_count = int(meta["raw_row_count"] or 0)
    unique_observation_count = int(meta["unique_observation_count"] or 0)
    invalid_identity_count = int(meta["invalid_identity_count"] or 0)
    if raw_row_count == 0 or not meta["source_end"]:
        return build_patterns_unavailable_envelope("as_of 之前没有可用的研究数据", as_of=as_of)
    if invalid_identity_count or unique_observation_count != raw_row_count:
        return build_patterns_unavailable_envelope(
            "PATTERN_SOURCE_DUPLICATE_OR_INVALID_OBSERVATION_IDENTITY",
            as_of=as_of,
        )

    events: list[dict[str, Any]] = []
    not_evaluable: list[dict[str, Any]] = []
    evaluable_by_code: dict[str, int] = {}
    for row in raw_rows:
        if row["code"] is None:
            continue
        row_events, row_not_evaluable = _evaluate_pattern_record(row, registry)
        events.extend(row_events)
        not_evaluable.extend(row_not_evaluable)
        code = str(row["code"])
        evaluable_by_code[code] = len(registry) - len(row_not_evaluable)

    events.sort(
        key=lambda item: (
            -(date.fromisoformat(item["trade_date"]).toordinal() if item["trade_date"] else 0),
            item["code"],
            _PATTERN_EVENT_ORDER[item["event_type"]],
        )
    )
    not_evaluable.sort(
        key=lambda item: (
            item["code"],
            item["trade_date"] or "",
            _PATTERN_EVENT_ORDER[item["event_type"]],
        )
    )
    page = events[offset : offset + limit]
    target_date = str(meta["source_end"])
    status = "partial" if not_evaluable else "normal"
    limitations = [
        "Research Runtime 数据不是 Canonical Fact Authority。",
        "Pattern 仅复用现有五类技术触发语义；不包含评分、预测、买卖建议或写入。",
        "source date 取自 artifact 中不晚于 requested as_of 的最新交易日；未使用未来行。",
    ]
    if not_evaluable:
        limitations.append("存在 NOT_EVALUABLE 技术事件；不可评估不等于未触发。")
    if selected_event_type:
        limitations.append(f"当前仅筛选 event_type={selected_event_type}。")
    return {
        "schema_version": PATTERN_SCHEMA_VERSION,
        "dataset_id": manifest["dataset_id"],
        "provider_id": manifest.get("provider_id", PROVIDER_ID),
        "adjustment": manifest.get("adjustment", ADJUSTMENT),
        "status": status,
        "fetched_at": manifest.get("imported_at"),
        "requested_as_of": as_of,
        "as_of": target_date,
        "as_of_semantics": _PATTERN_AS_OF_SEMANTICS,
        "latest_date": target_date,
        "source": _pattern_provenance(manifest),
        "artifact_identity": {
            "sha256": manifest["artifact_sha256"],
            "file": manifest["artifact_file"],
        },
        "coverage": {
            "start": manifest["coverage_start"],
            "end": manifest["coverage_end"],
            "row_count": manifest["row_count"],
            "code_count": manifest["code_count"],
        },
        "source_scope": {
            "start": meta["source_start"],
            "end": meta["source_end"],
            "row_count": raw_row_count,
            "code_count": int(meta["total_universe"] or 0),
        },
        "pattern_registry": list(_PATTERN_EVENT_REGISTRY),
        "event_type_filter": selected_event_type,
        "total_universe": int(meta["total_universe"] or 0),
        "evaluable_count": sum(
            count == len(registry) for count in evaluable_by_code.values()
        ),
        "matched_stock_count": len({item["code"] for item in events}),
        "not_evaluable_count": len(not_evaluable),
        "not_evaluable": not_evaluable[:limit],
        "not_evaluable_returned": min(limit, len(not_evaluable)),
        "events": page,
        "returned_events": len(page),
        "total_events": len(events),
        "next_offset": offset + len(page) if offset + len(page) < len(events) else None,
        "formal_state_write": {"performed": False, "scope": "pattern discovery read-only"},
        "limitations": limitations,
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
