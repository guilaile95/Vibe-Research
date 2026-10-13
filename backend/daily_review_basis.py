"""Bounded metadata from the exact submitted review context; never truth certification.

No provider calls, prompt changes, raw context storage, or reconstruction on restore.
Free-form warnings, unknowns and unrecognized component names are counted, not saved.
"""
from __future__ import annotations

import copy
from datetime import date, datetime
import hashlib
import json
import re

SCHEMA = "daily-review-input-basis.v1"
CONTEXT_SCHEMA = "daily-review-ai-context-v0.1"
COMPONENTS = ("indices", "global_indices", "breadth", "emotion", "turnover",
              "industry_boards", "concept_boards", "region_boards")
STATUSES = frozenset({"normal", "partial", "unavailable", "unknown"})
MAX_CONTEXT_BYTES = 2 * 1024 * 1024
MAX_BASIS_BYTES = 4096
_KEYS = frozenset({"schema_version", "context_schema_version", "review_schema_version", "trade_date",
                  "source_review_generated_at", "source_data_cutoff", "review_status", "component_statuses",
                  "omitted_component_count", "warning_count", "unknown_count", "context_sha256"})


def _fail():
    raise ValueError("invalid daily review input basis")


def _stamp(value, nullable=False):
    if value is None and nullable:
        return
    if (type(value) is not str or not 1 <= len(value) <= 64
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?", value)):
        _fail()
    offset = re.search(r"[+-](\d{2}):(\d{2})$", value)
    if offset and (int(offset[1]) >= 24 or int(offset[2]) >= 60):
        _fail()
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail()


def validate_basis(value, *, trade_date, source_generated_at, source_cutoff):
    """Return a detached strict snapshot. Unknown v2 data never downgrades to v1."""
    if type(value) is not dict or set(value) != _KEYS:
        _fail()
    if value["schema_version"] != SCHEMA or value["context_schema_version"] != CONTEXT_SCHEMA:
        _fail()
    version = value["review_schema_version"]
    if version is not None and (type(version) is not str or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", version)):
        _fail()
    day = value["trade_date"]
    if type(day) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        _fail()
    try:
        date.fromisoformat(day)
    except ValueError:
        _fail()
    _stamp(value["source_review_generated_at"])
    _stamp(value["source_data_cutoff"], nullable=True)
    if (day != trade_date or value["source_review_generated_at"] != source_generated_at
            or value["source_data_cutoff"] != source_cutoff):
        _fail()
    if type(value["review_status"]) is not str or value["review_status"] not in STATUSES:
        _fail()
    components = value["component_statuses"]
    if type(components) is not dict or set(components) != set(COMPONENTS):
        _fail()
    if any(type(v) is not str or v not in STATUSES for v in components.values()):
        _fail()
    for key in ("omitted_component_count", "warning_count", "unknown_count"):
        if type(value[key]) is not int or not 0 <= value[key] <= 10000:
            _fail()
    if type(value["context_sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", value["context_sha256"]):
        _fail()
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_BASIS_BYTES:
        _fail()
    return copy.deepcopy(value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def capture_basis(context_json, review):
    """Capture before model execution from the exact UTF-8 context passed to messages."""
    if type(context_json) is not str or type(review) is not dict:
        _fail()
    raw = context_json.encode("utf-8")
    if not raw or len(raw) > MAX_CONTEXT_BYTES:
        _fail()
    try:
        ctx = json.loads(context_json, object_pairs_hook=_unique_object,
                         parse_constant=lambda _: _fail())
    except (ValueError, RecursionError):
        _fail()
    pending = [(ctx, 0)]
    while pending:
        node, depth = pending.pop()
        if depth > 32:
            _fail()
        if type(node) is dict:
            pending.extend((child, depth + 1) for child in node.values())
        elif type(node) is list:
            pending.extend((child, depth + 1) for child in node)
    if type(ctx) is not dict or ctx.get("schema_version") != CONTEXT_SCHEMA:
        _fail()
    meta, health, unknowns = ctx.get("review_metadata"), ctx.get("data_health"), ctx.get("unknowns")
    if type(meta) is not dict or type(health) is not dict or type(unknowns) is not list:
        _fail()
    components, warnings = health.get("components"), health.get("warnings")
    if type(components) is not dict or type(warnings) is not list:
        _fail()
    if any(type(x) is not str for x in warnings + unknowns):
        _fail()
    # Unrecognized names/statuses must not become persisted arbitrary strings.
    normalized = {key: (components.get(key) if type(components.get(key)) is str
                       and components[key] in STATUSES else "unknown") for key in COMPONENTS}
    status = meta.get("status")
    result = {
        "schema_version": SCHEMA, "context_schema_version": ctx["schema_version"],
        "review_schema_version": meta.get("review_schema_version"), "trade_date": meta.get("trade_date"),
        "source_review_generated_at": meta.get("generated_at"), "source_data_cutoff": meta.get("data_cutoff"),
        "review_status": status if type(status) is str and status in STATUSES else "unknown",
        "component_statuses": normalized,
        "omitted_component_count": sum(key not in COMPONENTS for key in components),
        "warning_count": len(warnings), "unknown_count": len(unknowns),
        "context_sha256": hashlib.sha256(raw).hexdigest(),
    }
    return validate_basis(result, trade_date=review.get("trade_date"),
                          source_generated_at=review.get("generated_at"), source_cutoff=review.get("data_cutoff"))
