"""Read-only research continuity from existing immutable authorities."""

from __future__ import annotations

import copy
import json
from datetime import date, datetime, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import astock
import campaign_service
import formal_thesis_projection
import frozen_decision_service


SCHEMA_VERSION = "research_continuity.v0.1"
CHANGE_TYPES = ("ADDED", "REMOVED", "CHANGED", "SOURCE_CONFLICT")
_COMPARE_FIELDS = (
    "claim", "evidence_type", "classification", "confidence", "stance",
    "source_title", "source_url", "source_date", "accessed_at",
)


class ResearchContinuityError(RuntimeError):
    pass


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _field_state(value: Any) -> str:
    if isinstance(value, str) and value in {"UNKNOWN", "ERROR", "NOT_EVALUATED"}:
        return str(value)
    if value is None:
        return "UNKNOWN"
    if value == "":
        return "EMPTY"
    return "VALUE"


def _record_key(item: Mapping[str, Any]) -> str:
    value = item.get("evidence_id", item.get("id"))
    if not isinstance(value, str) or not value:
        raise ResearchContinuityError("immutable evidence snapshot is missing its record key")
    return value


def _normalize(item: Mapping[str, Any]) -> dict[str, Any]:
    values = {field: copy.deepcopy(item.get(field)) for field in _COMPARE_FIELDS}
    source = values["source_url"] or values["source_title"]
    return {
        "record_key": _record_key(item),
        "claim_identity": values["claim"],
        "source": source,
        "field_states": {
            key: _field_state(value)
            for key, value in {
                "claim_identity": values["claim"],
                "source": source,
            }.items()
        },
        "values": values,
    }


def _semantic_key(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ResearchContinuityError("evidence semantic identity is invalid") from exc


def compare_evidence(
    baseline: list[Mapping[str, Any]],
    current: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Compare immutable evidence snapshots by their formal record identity."""
    before = {_record_key(item): _normalize(item) for item in baseline}
    after = {_record_key(item): _normalize(item) for item in current}
    if len(before) != len(baseline) or len(after) != len(current):
        raise ResearchContinuityError("duplicate immutable evidence record key")

    changes: list[dict[str, Any]] = []
    for key in sorted(before.keys() - after.keys()):
        changes.append({"change_type": "REMOVED", "record_key": key, "before": before[key], "after": None})
    for key in sorted(after.keys() - before.keys()):
        changes.append({"change_type": "ADDED", "record_key": key, "before": None, "after": after[key]})
    for key in sorted(before.keys() & after.keys()):
        old, new = before[key], after[key]
        changed_fields = [
            field for field in _COMPARE_FIELDS
            if old["values"][field] != new["values"][field]
        ]
        if changed_fields:
            changes.append({
                "change_type": "CHANGED", "record_key": key,
                "changed_fields": changed_fields, "before": old, "after": new,
            })

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in after.values():
        semantic_key = _semantic_key(item["claim_identity"])
        grouped.setdefault(semantic_key, []).append(item)
    for items in grouped.values():
        sources = {item["source"] for item in items if item["source"]}
        conclusions = {
            (
                item["values"]["classification"], item["values"]["confidence"],
                item["values"]["stance"],
            )
            for item in items
        }
        if len(sources) > 1 and len(conclusions) > 1:
            changes.append({
                "change_type": "SOURCE_CONFLICT",
                "record_key": ",".join(sorted(item["record_key"] for item in items)),
                "sources": sorted(sources),
                "records": sorted((item for item in items), key=lambda item: item["record_key"]),
            })
    order = {kind: index for index, kind in enumerate(CHANGE_TYPES)}
    return sorted(changes, key=lambda item: (order[item["change_type"]], item["record_key"]))


def _snapshot_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping):
        raise ResearchContinuityError("immutable thesis snapshot is unavailable")
    items = value.get("evidence_links")
    if not isinstance(items, list):
        raise ResearchContinuityError("immutable thesis evidence bundle is unavailable")
    if any(not isinstance(item, Mapping) for item in items):
        raise ResearchContinuityError("immutable thesis evidence bundle is invalid")
    return [copy.deepcopy(dict(item)) for item in items]


def _chain(projection: Mapping[str, Any], cutoff: datetime | None = None) -> tuple[list[dict[str, Any]], int]:
    original = _snapshot_items(projection.get("original_snapshot"))
    by_id = {_record_key(item): item for item in original}
    if len(by_id) != len(original):
        raise ResearchContinuityError("duplicate Formal Original evidence record key")
    deltas = projection.get("deltas")
    if not isinstance(deltas, list):
        raise ResearchContinuityError("Current Thesis delta chain is unavailable")
    observations = 0
    for delta in sorted(deltas, key=lambda item: item.get("delta_sequence", 0) if isinstance(item, Mapping) else 0):
        if not isinstance(delta, Mapping):
            raise ResearchContinuityError("Current Thesis delta chain is invalid")
        confirmed_at = _parse_datetime(delta.get("confirmed_at"))
        if confirmed_at is None:
            raise ResearchContinuityError("Current Thesis delta time is invalid")
        if cutoff is not None and confirmed_at > cutoff:
            continue
        observations += 1
        items = delta.get("evidence_links")
        if not isinstance(items, list) or any(not isinstance(item, Mapping) for item in items):
            raise ResearchContinuityError("immutable Delta evidence bundle is invalid")
        for item in items:
            snapshot = copy.deepcopy(dict(item))
            by_id[_record_key(snapshot)] = snapshot
    return [by_id[key] for key in sorted(by_id)], observations


def _continuity(campaign: Mapping[str, Any]) -> dict[str, Any]:
    campaign_id = str(campaign["campaign_id"])
    try:
        projection = formal_thesis_projection.project_current_thesis(campaign_id)
    except campaign_service.ThesisBindingNotFoundError:
        return {
            "baseline": {"status": "NO_BASELINE", "authority_type": None},
            "changes": {"status": "NO_BASELINE", "items": [], "observation_count": 0},
            "authority_refs": [],
        }
    except Exception:
        return {
            "baseline": {"status": "UNAVAILABLE", "authority_type": None},
            "changes": {"status": "UNAVAILABLE", "items": [], "observation_count": 0},
            "authority_refs": [],
        }
    if projection.get("formal_status") != "READY" or projection.get("ready") is not True:
        return {
            "baseline": {"status": "NO_BASELINE", "authority_type": None},
            "changes": {"status": "NO_BASELINE", "items": [], "observation_count": 0},
            "authority_refs": [],
        }
    try:
        current, _ = _chain(projection)
        decisions = frozen_decision_service.list_decisions(campaign_id=campaign_id, limit=1000)
        if decisions:
            frozen = decisions[-1]
            cutoff = _parse_datetime(frozen.get("committed_at"))
            refs = frozen.get("evidence_refs")
            if cutoff is None or not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
                raise ResearchContinuityError("Frozen Decision evidence authority is invalid")
            baseline_all, _ = _chain(projection, cutoff)
            baseline_by_id = {_record_key(item): item for item in baseline_all}
            missing = sorted(set(refs) - baseline_by_id.keys())
            if missing:
                raise ResearchContinuityError("Frozen Decision evidence snapshot cannot be reconstructed")
            baseline = [baseline_by_id[ref] for ref in refs]
            observations = sum(
                1 for delta in projection["deltas"]
                if (_parse_datetime(delta.get("confirmed_at")) or datetime.min.replace(tzinfo=timezone.utc)) > cutoff
            )
            baseline_info = {
                "status": "READY", "authority_type": "FROZEN_DECISION",
                "decision_id": frozen.get("decision_id"), "as_of": frozen.get("committed_at"),
                "snapshot_hash": frozen.get("snapshot_hash"),
            }
            authority_refs = [
                f"frozen_decision:{frozen.get('decision_id')}:{frozen.get('snapshot_hash')}",
                f"current_thesis:{campaign_id}:{projection.get('thesis_id')}:v{projection.get('frozen_revision')}",
            ]
        else:
            baseline = _snapshot_items(projection.get("original_snapshot"))
            observations = len(projection["deltas"])
            baseline_info = {
                "status": "READY", "authority_type": "CANDIDATE_RESEARCH_FORMAL_ORIGINAL",
                "decision_id": None, "as_of": projection.get("binding", {}).get("bound_at"),
                "snapshot_hash": None,
            }
            authority_refs = [
                f"formal_original:{projection.get('thesis_id')}:v{projection.get('frozen_revision')}"
            ]
        items = compare_evidence(baseline, current)
        return {
            "baseline": baseline_info,
            "changes": {
                "status": "NORMAL" if observations else "NOT_EVALUATED",
                "items": items if observations else [],
                "observation_count": observations,
            },
            "authority_refs": authority_refs,
        }
    except Exception:
        return {
            "baseline": {"status": "UNAVAILABLE", "authority_type": None},
            "changes": {"status": "UNAVAILABLE", "items": [], "observation_count": 0},
            "authority_refs": [],
        }


def project_disclosure_calendar(
    rows: list[Mapping[str, Any]], *, as_of: date, fetched_at: str,
) -> dict[str, Any]:
    records = []
    malformed = 0
    for row in rows:
        if not isinstance(row, Mapping):
            malformed += 1
            continue
        report_date = _parse_date(row.get("REPORT_DATE"))
        appointment = _parse_date(row.get("APPOINT_PUBLISH_DATE"))
        actual = _parse_date(row.get("ACTUAL_PUBLISH_DATE"))
        if report_date is None or (appointment is None and actual is None):
            malformed += 1
            continue
        records.append({
            "report_date": report_date.isoformat(),
            "appointment_date": appointment.isoformat() if appointment else None,
            "actual_date": actual.isoformat() if actual else None,
        })
    if not records:
        state = "UNAVAILABLE" if rows and malformed else "NO_RECORD"
        return {
            "state": state, "next": None, "latest_actual": None,
            "fetched_at": fetched_at, "source": "eastmoney:RPT_PUBLIC_BS_APPOIN",
        }
    pending = [record for record in records if record["appointment_date"] and not record["actual_date"]]
    delayed = sorted(
        (record for record in pending if date.fromisoformat(record["appointment_date"]) < as_of),
        key=lambda record: record["appointment_date"],
    )
    expected = sorted(
        (record for record in pending if date.fromisoformat(record["appointment_date"]) >= as_of),
        key=lambda record: record["appointment_date"],
    )
    actuals = sorted(
        (record for record in records if record["actual_date"]),
        key=lambda record: record["actual_date"], reverse=True,
    )
    if delayed:
        state, next_record = "DELAYED_SIGNAL", delayed[0]
    elif expected:
        state, next_record = "EXPECTED", expected[0]
    elif actuals:
        state, next_record = "CONFIRMED", None
    else:
        state, next_record = "NO_RECORD", None
    return {
        "state": state,
        "next": ({**next_record, "semantics": state} if next_record else None),
        "latest_actual": ({**actuals[0], "semantics": "CONFIRMED"} if actuals else None),
        "fetched_at": fetched_at,
        "source": "eastmoney:RPT_PUBLIC_BS_APPOIN",
    }


def _calendar(security_code: str, fetched_at: str) -> dict[str, Any]:
    params = {
        "reportName": "RPT_PUBLIC_BS_APPOIN", "columns": "ALL",
        "filter": f'(SECURITY_CODE="{security_code}")',
        "pageNumber": "1", "pageSize": "50", "sortColumns": "REPORT_DATE",
        "sortTypes": "-1", "source": "WEB", "client": "WEB",
    }
    try:
        response = astock.em_get(astock._DATACENTER_URL, params=params, timeout=15)
        if getattr(response, "status_code", 200) >= 400:
            raise ResearchContinuityError("disclosure provider unavailable")
        payload = response.json()
        result = payload.get("result")
        if result is None and payload.get("success") is False:
            raise ResearchContinuityError("disclosure provider rejected the request")
        rows = (result or {}).get("data") or []
        if not isinstance(rows, list):
            raise ResearchContinuityError("disclosure provider returned an invalid payload")
        return project_disclosure_calendar(
            rows, as_of=datetime.now(ZoneInfo("Asia/Shanghai")).date(), fetched_at=fetched_at,
        )
    except Exception:
        return {
            "state": "ERROR", "next": None, "latest_actual": None,
            "fetched_at": fetched_at, "source": "eastmoney:RPT_PUBLIC_BS_APPOIN",
        }


def _result(campaign: Mapping[str, Any], fetched_at: str, calendar: dict[str, Any]) -> dict[str, Any]:
    continuity = _continuity(campaign)
    overall = "NORMAL"
    if continuity["changes"]["status"] in {"UNAVAILABLE"} or calendar["state"] == "ERROR":
        overall = "PARTIAL"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": overall,
        "campaign_id": campaign["campaign_id"],
        "security_code": campaign["security_code"],
        "strategy": campaign["strategy"],
        "fetched_at": fetched_at,
        **continuity,
        "decision_calendar": calendar,
        "writes": {"thesis": 0, "decision": 0, "campaign": 0, "trade": 0},
    }


def get_research_continuities(campaign_ids: list[str]) -> list[dict[str, Any]]:
    campaigns = [campaign_service.get_campaign(campaign_id) for campaign_id in dict.fromkeys(campaign_ids)]
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    calendars = {
        security_code: _calendar(security_code, fetched_at)
        for security_code in sorted({campaign["security_code"] for campaign in campaigns})
    }
    return [
        _result(campaign, fetched_at, calendars[campaign["security_code"]])
        for campaign in campaigns
    ]


def get_research_continuity(campaign_id: str) -> dict[str, Any]:
    return get_research_continuities([campaign_id])[0]
