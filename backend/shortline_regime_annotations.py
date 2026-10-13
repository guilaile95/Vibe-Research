"""User-authored regime notes in the existing immutable research receipt store.

Dates and links are user claims, not verified rules or provider announcements.
No URL is fetched. Only explicit save opens an existing configured writable lake.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import os
import re
from urllib.parse import urlsplit
import uuid

from data_contracts import ProviderObservation, FetchSemantics, HistoryMode, QualityStatus
from fact_lake_store import open_existing_fact_lake, payload_sha256, FactLakeObservationConflictError
import shortline_research_contract as C

DATASET = "research_user_regime_annotations_v1"
VERSION = "user-regime-annotation.v1"


def validate_entry(value):
    if type(value) is not dict or set(value) != {"effective_date", "announcement_date", "title", "note", "source_url", "idempotency_key"}:
        raise ValueError("invalid regime annotation fields")
    C.day(value["effective_date"])
    if value["announcement_date"] is not None:
        C.day(value["announcement_date"])
    for key, limit, empty in (("title", 160, False), ("note", 2000, True)):
        text = value[key]
        if type(text) is not str or len(text) > limit or (not empty and not text.strip()) or any(ord(c) < 32 and c not in "\n\t" for c in text):
            raise ValueError("invalid annotation text")
    url = value["source_url"]
    if url is not None:
        if type(url) is not str or len(url) > 2048 or any(c.isspace() for c in url):
            raise ValueError("invalid source URL")
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.netloc.endswith(":") or "\\" in url:
            raise ValueError("source URL must be credential-free HTTP(S)")
        _ = parsed.port  # Reject malformed ports as well.
    key = value["idempotency_key"]
    if type(key) is not str or not re.fullmatch(r"[a-f0-9-]{36}", key):
        raise ValueError("invalid idempotency key")
    uuid.UUID(key)
    return {k: value[k] for k in ("effective_date", "announcement_date", "title", "note", "source_url")}


def save_regime_annotation(value):
    entry = validate_entry(value)
    root = os.environ.get("VR_FACT_LAKE_ROOT", "").strip()
    if not root:
        raise ValueError("research archive not configured")
    lake = open_existing_fact_lake(root, readonly=False)
    raw = C.canonical(entry).encode()
    identity = "regime-" + uuid.uuid5(uuid.NAMESPACE_URL, "vibe-research:regime:" + value["idempotency_key"]).hex
    existing = lake.get_observation(identity)
    if existing:
        if existing.observation.dataset_id != DATASET or lake.read_payload(identity) != raw:
            raise FactLakeObservationConflictError("idempotency key reused with different annotation")
        return {"id": identity, "created": False, "created_at": existing.observation.fetched_at, "authority": "USER_AUTHORED_UNVERIFIED"}
    created = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    observation = ProviderObservation(observation_id=identity, dataset_id=DATASET, provider_id="user_annotation",
        provider_endpoint="manual_regime_event", provider_symbol="USER_RESEARCH", request_fingerprint=C.digest(entry),
        source_payload_hash=payload_sha256(raw), normalizer_version=VERSION,
        payload={"schema_version": VERSION, "authority": "USER_AUTHORED_UNVERIFIED", "created_at": created},
        fetch_semantics=FetchSemantics.SNAPSHOT, history_mode=HistoryMode.SNAPSHOT_ONLY, fetched_at=created,
        trade_date=entry["effective_date"], quality_status=QualityStatus.UNKNOWN, reason_codes=("USER_AUTHORED_UNVERIFIED",))
    try:
        lake.store_observation(observation, raw, "application/json")
    except FactLakeObservationConflictError:
        # Concurrent duplicate click: retain the first immutable creation time.
        existing = lake.get_observation(identity)
        if not existing or lake.read_payload(identity) != raw:
            raise
        return {"id": identity, "created": False, "created_at": existing.observation.fetched_at, "authority": "USER_AUTHORED_UNVERIFIED"}
    return {"id": identity, "created": True, "created_at": created, "authority": "USER_AUTHORED_UNVERIFIED"}


def read_regime_annotations(lake, selected_date):
    selected = date.fromisoformat(C.day(selected_date))
    start, end = (selected - timedelta(days=183)).isoformat(), (selected + timedelta(days=183)).isoformat()
    records = lake.list_observations(dataset_id=DATASET, start_trade_date=start, end_trade_date=end, limit=512, max_payload_bytes=2 * 1024 * 1024)
    if len(records) == 512:
        raise ValueError("annotation window exceeds bounded read")
    events = []
    for record in records:
        obs = record.observation
        if (obs.provider_id != "user_annotation" or obs.provider_endpoint != "manual_regime_event"
                or obs.normalizer_version != VERSION or obs.payload.get("authority") != "USER_AUTHORED_UNVERIFIED"
                or obs.payload.get("created_at") != obs.fetched_at or C.instant(obs.fetched_at) > datetime.now(timezone.utc)):
            raise ValueError("invalid annotation receipt")
        raw = lake.read_payload(obs.observation_id)
        entry = C.decode(raw)
        validate_entry({**entry, "idempotency_key": "00000000-0000-0000-0000-000000000000"})
        if obs.trade_date != entry["effective_date"] or obs.source_payload_hash != payload_sha256(raw) or obs.request_fingerprint != C.digest(entry):
            raise ValueError("annotation date or hash mismatch")
        events.append({"id": obs.observation_id, **entry, "created_at": obs.fetched_at,
                       "upcoming": entry["effective_date"] > selected_date,
                       "authority": "USER_AUTHORED_UNVERIFIED", "raw_payload_hash": obs.source_payload_hash})
    return {"status": "normal" if events else "empty", "reason_codes": [], "events": events,
            "window": {"start": start, "end": end}, "authority": "USER_AUTHORED_UNVERIFIED",
            "note": "人工登记，日期和链接未经核验；将来日期只是计划记录，不表示规则已经确认。"}
