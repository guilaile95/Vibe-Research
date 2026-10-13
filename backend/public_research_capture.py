"""Explicit, one-response public quote capture; never imported by an app router.

Default CLI mode only prints a plan. Execution writes only an already initialized,
explicit FactLake. It does not initialize data, schedule work, or call a model.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import httpx

from fact_lake_store import FactLakeError, open_existing_fact_lake
import public_research_archive as archive
import public_research_contract as C

SOURCE = "cn_quote_ref"
SOCKET_TIMEOUT = 5.0
ELAPSED_BUDGET = 20.0


class CaptureError(ValueError):
    """Fixed safe error code, never provider text or transport exception details."""


def plan(source: str, subject: str, archive_root: str) -> dict:
    if source != SOURCE:
        raise CaptureError("SOURCE_NOT_ENABLED_FOR_MANUAL_CAPTURE")
    if not archive_root or not Path(archive_root).is_absolute():
        raise CaptureError("EXPLICIT_ABSOLUTE_ARCHIVE_REQUIRED")
    url = C.request_spec(source, subject)
    return {"source_id": source, "subject": subject, "url": url,
            "archive_root": str(Path(archive_root)), "mode": "PLAN_ONLY",
            "request_count": 1, "max_response_bytes": C.MAX_BYTES,
            "socket_timeout_seconds": SOCKET_TIMEOUT,
            "elapsed_budget_seconds": ELAPSED_BUDGET,
            "schedule_enabled": False, "model_calls": 0,
            "point_in_time_claim": "NONE", "provider_terms": "NOT_VERIFIED"}


def bounded_transport(expected_url, *, client_factory=httpx.Client, clock=time.monotonic):
    def fetch(url, *, max_bytes, timeout, allow_redirects):
        if (url != expected_url or max_bytes != C.MAX_BYTES or timeout != ELAPSED_BUDGET
                or allow_redirects is not False):
            raise CaptureError("TRANSPORT_CONTRACT_MISMATCH")
        started = clock()
        try:
            with client_factory(timeout=SOCKET_TIMEOUT, follow_redirects=False,
                                trust_env=False, verify=True) as client:
                with client.stream("GET", url, headers={"Accept-Encoding": "identity",
                        "User-Agent": "Vibe-Research-Manual-Public-Capture"}) as response:
                    if 300 <= response.status_code < 400:
                        raise CaptureError("REDIRECT_REJECTED")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise CaptureError("ENCODED_RESPONSE_REJECTED")
                    length = response.headers.get("content-length")
                    if length is not None and (not length.isascii() or not length.isdecimal()
                                               or int(length) > max_bytes):
                        raise CaptureError("RESPONSE_SIZE_REJECTED")
                    raw = bytearray()
                    if clock() - started > timeout:
                        raise CaptureError("ELAPSED_BUDGET_EXCEEDED")
                    for chunk in response.iter_raw():
                        if clock() - started > timeout:
                            raise CaptureError("ELAPSED_BUDGET_EXCEEDED")
                        if len(raw) + len(chunk) > max_bytes:
                            raise CaptureError("RESPONSE_SIZE_REJECTED")
                        raw.extend(chunk)
                    if not raw:
                        raise CaptureError("EMPTY_RESPONSE")
                    return response.status_code, bytes(raw)
        except httpx.HTTPError:
            raise CaptureError("PUBLIC_TRANSPORT_UNAVAILABLE") from None
    return fetch


def capture_once(source, subject, archive_root, *, execute=False,
                 client_factory=httpx.Client, clock=time.monotonic):
    proposal = plan(source, subject, archive_root)
    if execute is not True:
        return proposal
    # Opening fails before any request if the explicit archive is missing/corrupt.
    lake = open_existing_fact_lake(archive_root, readonly=False)
    receipt = archive.collect(lake, source, subject,
        transport=bounded_transport(proposal["url"], client_factory=client_factory, clock=clock),
        fixture=False)
    observed = archive.replay(lake, lake.get_observation(receipt["observation_id"]))
    return {**proposal, "mode": "CAPTURED", "receipt": receipt,
            "status": observed["status"], "raw_bytes": observed["raw_bytes"],
            "evidence": observed["evidence"], "reason_codes": observed.get("reason_codes", []),
            "message": "Current archived public response; not historical PIT or verified investment evidence"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=[SOURCE])
    parser.add_argument("--subject", required=True, help="A:600000@YYYY-MM-DD; exact source identity and cutoff")
    parser.add_argument("--archive-root", required=True, help="Absolute path to an already initialized isolated FactLake")
    parser.add_argument("--execute", action="store_true", help="Perform one public GET and archive its bounded raw response")
    args = parser.parse_args(argv)
    try:
        result = capture_once(args.source, args.subject, args.archive_root, execute=args.execute)
    except CaptureError as error:
        result = {"status": "unavailable", "reason_codes": [str(error)], "model_calls": 0}
    except (FactLakeError, ValueError, OSError):
        result = {"status": "unavailable", "reason_codes": ["ARCHIVE_OR_IDENTITY_UNAVAILABLE"], "model_calls": 0}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2 if result.get("status") == "unavailable" else 0


if __name__ == "__main__":
    raise SystemExit(main())
