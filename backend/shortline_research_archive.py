"""Immutable research receipt producer/replay on the existing FactLake.

No network clients, credentials, scheduler, database initialization or shadow
activation. The caller supplies already captured provider bytes. Capture is an
explicit software operation; viewing research never calls it.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import uuid
import trade_calendar

from data_contracts import ProviderObservation, FetchSemantics, HistoryMode, QualityStatus
from fact_lake_store import payload_sha256
import shortline_research_contract as C
from shortline_research_adapters import NORMALIZER, normalize_capture

_METADATA = {"kind", "trade_date", "provider", "endpoint", "captured_at", "http_status", "fixture",
             "page_index", "page_count", "batch_id", "request_shape", "requested_codes"}


def validate_metadata(metadata):
    if type(metadata) is not dict or set(metadata) != _METADATA:
        raise ValueError("invalid capture metadata fields")
    kind = metadata["kind"]
    if kind not in C.KINDS or metadata["endpoint"] != C.ENDPOINTS[kind]:
        raise ValueError("unsupported research capture")
    C.day(metadata["trade_date"])
    C.utc(metadata["captured_at"])
    if (type(metadata["fixture"]) is not bool or type(metadata["http_status"]) is not int
            or not 100 <= metadata["http_status"] <= 599):
        raise ValueError("invalid capture transport")
    if (type(metadata["page_count"]) is not int or not 1 <= metadata["page_count"] <= C.MAX_PAGES
            or type(metadata["page_index"]) is not int or not 0 <= metadata["page_index"] < metadata["page_count"]):
        raise ValueError("invalid page coverage")
    for key in ("batch_id", "request_shape"):
        value = metadata[key]
        if type(value) is not str or not 1 <= len(value) <= 160 or any(x in value for x in ("/", "?", "=", "@", "\\")):
            raise ValueError("unsafe capture identity")
    codes = metadata["requested_codes"]
    if (type(codes) is not list or len(codes) > C.MAX_ROWS or len(set(codes)) != len(codes)
            or any(C.code(x) != x for x in codes)):
        raise ValueError("invalid requested identity batch")
    expected_provider = "eastmoney_push2ex" if kind in C.KINDS[:3] else "tushare_pro"
    if metadata["provider"] != expected_provider:
        raise ValueError("provider contract mismatch")
    if kind in C.KINDS[:3] and codes:
        raise ValueError("market pool must not be narrowed by requested stock filter")
    if kind in C.KINDS[3:] and not codes:
        raise ValueError("price batch requires explicit complete cohort identities")
    return metadata


def persist_capture(lake, raw: bytes, metadata: dict):
    """Archive raw receipt before any row truncation, including partial evidence.

    Caller must already have an explicit writable FactLake. No automatic setup.
    Local receipt time is server-generated and is NOT immutable commit/PIT proof.
    """
    metadata = validate_metadata(metadata)
    if type(raw) is not bytes or not 0 < len(raw) <= C.MAX_BYTES:
        raise ValueError("invalid raw capture size")
    try:
        projection = normalize_capture(raw, metadata)
        normalization_failed = False
    except (ValueError, TypeError, KeyError, OverflowError):
        projection = {"status": "unavailable", "reason_codes": ["NORMALIZATION_FAILED"]}
        normalization_failed = True
    received = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if C.instant(metadata["captured_at"]) > C.instant(received):
        raise ValueError("capture is in the future")
    observation = ProviderObservation(
        observation_id="shortline-" + uuid.uuid4().hex, dataset_id=C.DATASETS[metadata["kind"]],
        provider_id=metadata["provider"], provider_endpoint=metadata["endpoint"], provider_symbol="SH_SZ_A",
        request_fingerprint=C.digest({key: metadata[key] for key in metadata if key not in ("captured_at", "http_status")}),
        source_payload_hash=payload_sha256(raw), normalizer_version=NORMALIZER,
        payload={"schema_version": C.VERSION, "capture": metadata, "locally_received_at": received,
                 "normalization_failed": normalization_failed},
        fetch_semantics=FetchSemantics.BY_DATE, history_mode=HistoryMode.BY_DATE,
        fetched_at=C.utc(metadata["captured_at"]), trade_date=metadata["trade_date"],
        quality_status=QualityStatus.VALID if projection["status"] == "normal" else QualityStatus.DEGRADED,
        reason_codes=tuple(projection["reason_codes"]) or (() if projection["status"] == "normal" else ("PARTIAL_CAPTURE",)),
    )
    stored = lake.store_observation(observation, raw, "application/json")
    return {"observation_id": stored.stored.observation.observation_id, "status": projection["status"],
            "reason_codes": projection["reason_codes"], "raw_payload_hash": observation.source_payload_hash,
            "fixture": metadata["fixture"]}


def replay_capture(lake, stored):
    observation = stored.observation
    envelope = observation.payload
    if (type(envelope) is not dict or envelope.get("schema_version") != C.VERSION
            or observation.normalizer_version != NORMALIZER):
        raise ValueError("unsupported research receipt")
    metadata = validate_metadata(envelope.get("capture"))
    if (observation.dataset_id != C.DATASETS[metadata["kind"]] or observation.trade_date != metadata["trade_date"]
            or observation.provider_id != metadata["provider"] or observation.provider_endpoint != metadata["endpoint"]
            or observation.fetched_at != C.utc(metadata["captured_at"])
            or observation.provider_symbol != "SH_SZ_A"
            or observation.request_fingerprint != C.digest({key: metadata[key] for key in metadata if key not in ("captured_at", "http_status")})):
        raise ValueError("receipt identity mismatch")
    if not C.instant(observation.fetched_at) <= C.instant(envelope.get("locally_received_at")) <= datetime.now(timezone.utc):
        raise ValueError("receipt timestamp mismatch")
    raw = lake.read_payload(observation.observation_id)
    if raw is None or payload_sha256(raw) != observation.source_payload_hash:
        raise ValueError("raw receipt mismatch")
    if envelope.get("normalization_failed") is True:
        # Failed original bytes remain auditable; they are never reinterpreted
        # silently by a later normalizer or upgraded to complete observations.
        result = {"schema_version": C.VERSION, "normalizer_version": NORMALIZER,
                  "kind": metadata["kind"], "trade_date": metadata["trade_date"],
                  "status": "unavailable", "reason_codes": ["NORMALIZATION_FAILED"], "rows": [],
                  "raw_row_count": 0, "excluded_count": 0, "source_total": None,
                  "source_fields": None, "source_finality": "unknown", "source_revision": None, "complete": False,
                  "post_close_observation": False, "fixture": metadata["fixture"],
                  "source_group": {"provider": metadata["provider"], "endpoint": metadata["endpoint"],
                                   "normalizer_version": NORMALIZER, "request_shape": metadata["request_shape"]}}
    else:
        result = normalize_capture(raw, metadata)
    result["raw_bytes"] = len(raw)
    result["capture"] = metadata
    result["evidence"] = {"observation_id": observation.observation_id,
                          "raw_payload_hash": observation.source_payload_hash,
                          "source_ids": [observation.provider_id + ":" + observation.provider_endpoint],
                          "captured_at": observation.fetched_at,
                          "locally_received_at": envelope["locally_received_at"], "committed_at": None,
                          "provider_published_at": observation.published_at,
                          "normalizer_version": observation.normalizer_version}
    return result


def _merge_pages(pages):
    first = pages[0]
    metadata = first["capture"]
    expected_count = metadata["page_count"]
    indexes = [page["capture"]["page_index"] for page in pages]
    if len(indexes) != len(set(indexes)):
        raise ValueError("duplicate or conflicting page receipts")
    common = ("kind", "trade_date", "provider", "endpoint", "fixture", "page_count", "batch_id", "request_shape", "requested_codes")
    if any(any(page["capture"][key] != metadata[key] for key in common) for page in pages):
        raise ValueError("conflicting page identity")
    if len({page["source_finality"] for page in pages}) != 1:
        raise ValueError("inconsistent source finality")
    result = {key: value for key, value in first.items() if key not in ("capture", "evidence")}
    rows = [row for page in sorted(pages, key=lambda p: p["capture"]["page_index"]) for row in page["rows"]]
    if len(rows) > C.MAX_ROWS or len({row["stock_code"] for row in rows}) != len(rows):
        raise ValueError("duplicate or excessive source rows")
    result["rows"] = sorted(rows, key=lambda row: row["stock_code"])
    result["raw_row_count"] = sum(page["raw_row_count"] for page in pages)
    result["excluded_count"] = sum(page["excluded_count"] for page in pages)
    result["source_fields"] = sorted({field for page in pages for field in page["source_fields"] or []}) or None
    if result["source_fields"] and len(result["source_fields"]) > 512:
        raise ValueError("field catalogue exceeds bounded research schema")
    totals = {page["source_total"] for page in pages}
    if len(totals) != 1:
        raise ValueError("unstable source pool totals")
    revision_proof = expected_count == 1 or (first.get("source_revision") is not None and all(p.get("source_revision") == first["source_revision"] for p in pages))
    page_complete = sorted(indexes) == list(range(expected_count)) and all(p["capture"]["http_status"] == 200 for p in pages) and revision_proof
    if first["kind"] in C.KINDS[:3]:
        complete = page_complete and first["source_total"] is not None and result["raw_row_count"] == first["source_total"]
    else:
        complete = page_complete and {row["stock_code"] for row in rows} == set(metadata["requested_codes"])
    result["complete"] = complete
    result["post_close_observation"] = all(p["post_close_observation"] for p in pages)
    result["status"] = "normal" if complete and result["post_close_observation"] and result["source_finality"] != "source_declared_provisional" else "partial"
    result["reason_codes"] = ([] if complete else ["INCOMPLETE_CAPTURE_BATCH"]) + ([] if result["post_close_observation"] else ["PRE_CLOSE_OBSERVATION"])
    # An error/malformed payload cannot be promoted by batch count arithmetic.
    if any(p["status"] == "unavailable" for p in pages):
        result.update(status="unavailable", complete=False, reason_codes=["CAPTURE_RESPONSE_UNAVAILABLE"])
    result["evidence"] = [page["evidence"] for page in pages]
    result["batch_id"] = metadata["batch_id"]
    result["requested_codes"] = metadata["requested_codes"]
    return result


def load_research_days(lake, days: list[str]):
    """One snapshot handle, current archived batches only. Does not fetch.

    Retains a complete post-close batch over later partial/intraday attempts.
    Competing complete batches at identical capture time fail closed. Fixture
    and acquired receipts are never combined in a batch or silently mixed.
    """
    if not days or len(days) > 100 or len(set(days)) != len(days):
        raise ValueError("invalid research window")
    for day in days:
        C.day(day)
    output = {day: {kind: None for kind in C.KINDS} for day in days}
    remaining_bytes = 64 * 1024 * 1024
    remaining_receipts = 2048
    for kind in C.KINDS:
        if remaining_bytes <= 0 or remaining_receipts <= 0:
            raise ValueError("research replay budget exhausted")
        receipts = lake.list_observations(dataset_id=C.DATASETS[kind], start_trade_date=min(days), end_trade_date=max(days), limit=min(512, remaining_receipts), max_payload_bytes=remaining_bytes)
        if len(receipts) == min(512, remaining_receipts):
            raise ValueError("receipt window exceeds safe read bound")
        batches = {}
        for stored in receipts:
            if stored.observation.trade_date not in output:
                continue
            page = replay_capture(lake, stored)
            remaining_bytes -= page["raw_bytes"]
            remaining_receipts -= 1
            key = (page["trade_date"], page["capture"]["batch_id"])
            batches.setdefault(key, []).append(page)
        per_day = {}
        for (day, _), pages in batches.items():
            item = _merge_pages(pages)
            rank = (item["status"] == "normal", item["source_finality"] == "source_declared_final", max(e["captured_at"] for e in item["evidence"]))
            previous = per_day.get(day)
            if previous and rank == previous[0] and item["batch_id"] != previous[1]["batch_id"]:
                raise ValueError("ambiguous same-time research batches")
            if previous is None or rank > previous[0]:
                per_day[day] = (rank, item)
        for day, (_, result) in per_day.items():
            output[day][kind] = result
    return output


def capture_close_batch(lake, *, trade_date: str, capture_one, requested_codes: list[str]):
    """Explicit injected producer for five source families, no live defaults.

    ``capture_one(kind, trade_date, requested_codes)`` returns [(raw, metadata)].
    The existing configured runtime owns transport/rate limits and permission.
    Every endpoint is attempted independently; partial never means complete.
    This function neither registers nor starts the 15:35 schedule.
    """
    C.day(trade_date)
    if type(requested_codes) is not list or not requested_codes or len(requested_codes) > C.MAX_ROWS:
        raise ValueError("complete cohort identities required")
    if len(set(requested_codes)) != len(requested_codes) or any(C.code(code) != code for code in requested_codes):
        raise ValueError("invalid cohort identity set")
    expected_codes = set(requested_codes)
    previous = trade_calendar.previous_trade_date(trade_date)
    if previous is None:
        raise ValueError("previous trading session is unconfirmed")
    previous_inputs = load_research_days(lake, [previous])[previous]
    prior_pools = [previous_inputs[kind] for kind in ("limit_up", "broken")]
    if any(pool is None or pool["status"] != "normal" or not pool["complete"] for pool in prior_pools):
        raise ValueError("complete prior cohort receipts required before price capture")
    fixed_codes = {row["stock_code"] for pool in prior_pools for row in pool["rows"]}
    if not fixed_codes.issubset(expected_codes):
        raise ValueError("requested identities omit prior cohort members")
    cohort_binding = {"previous_trade_date": previous, "denominator": len(fixed_codes),
                      "membership_sha256": C.digest(sorted(fixed_codes)),
                      "source_observation_ids": [e["observation_id"] for pool in prior_pools for e in pool["evidence"]]}
    results = []
    for kind in C.KINDS:
        receipts = []
        try:
            pages = capture_one(kind, trade_date, sorted(expected_codes) if kind in C.KINDS[3:] else [])
            if type(pages) is not list or not 1 <= len(pages) <= C.MAX_PAGES:
                raise ValueError("empty capture")
            for raw, metadata in pages:
                if metadata["kind"] != kind or metadata["trade_date"] != trade_date:
                    raise ValueError("capture request mismatch")
                if kind in C.KINDS[3:] and set(metadata["requested_codes"]) != expected_codes:
                    raise ValueError("narrowed cohort capture")
                receipts.append(persist_capture(lake, raw, metadata))
            # Replay the exact batch rather than trusting individual-page flags.
            selected = [lake.get_observation(r["observation_id"]) for r in receipts]
            merged = _merge_pages([replay_capture(lake, r) for r in selected])
            if kind == "limit_up" and merged["status"] == "normal":
                expected_codes.update(row["stock_code"] for row in merged["rows"])
            results.append({"kind": kind, "status": merged["status"], "reason_codes": merged["reason_codes"], "receipts": receipts})
        except Exception:
            results.append({"kind": kind, "status": "unavailable", "reason_codes": ["CAPTURE_FAILED"], "receipts": receipts})
    return {"schema_version": C.VERSION, "trade_date": trade_date,
            "status": "normal" if all(r["status"] == "normal" for r in results) else "partial" if any(r["status"] != "unavailable" for r in results) else "unavailable",
            "endpoints": results, "cohort_binding": cohort_binding, "requested_price_identity_count": len(expected_codes), "schedule_enabled": False, "external_notifications": False}
