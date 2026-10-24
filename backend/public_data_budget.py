"""Hard lifetime bounds for legacy synchronous public-provider calls.

A spawned process owns provider threads/sockets. No app/lifespan is imported.
At most four children exist per backend; a timed-out child is killed and reaped.
"""
from __future__ import annotations

import copy
from concurrent.futures import Future, TimeoutError as FutureTimeout
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import time

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 12.0
# Full-A pagination alone owns a 120s cooperative budget. Preserve a hard
# process lifetime while allowing pagination + four pools + sector completion.
OVERVIEW_TIMEOUT = 210.0
PUBLIC_DATA_WORKERS = 4
_SLOTS = threading.BoundedSemaphore(PUBLIC_DATA_WORKERS)


class PublicDataUnavailable(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _write_result(path, value):
    raw = json.dumps({"data": value}, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("oversized result")
    temporary = path + ".part"
    with open(temporary, "wb") as handle:
        handle.write(raw)
    os.replace(temporary, path)


def _child(path, operation, code):
    try:
        if operation == "overview":
            import market
            if isinstance(code, dict) and code.get("snapshot_seed"):
                market._CACHE["a_share_snapshot"] = code["snapshot_seed"]
            value = market.get_overview()
        elif operation == "valuation":
            import astock
            def checkpoint(value):
                partial = dict(value, status="partial", reason_code="SOURCE_TIMEOUT", analyst_count=None,
                               forecast_note="估值或一致预期来源尚未完成；保留已取得的行情与估值字段")
                _write_result(path + ".checkpoint", partial)
            value = astock.full_valuation(code, on_quote=checkpoint)
        elif operation == "daily_review":
            import daily_review_sources
            value = daily_review_sources.collect(lambda packet: _write_result(path + ".checkpoint", packet))
        elif operation.startswith("kline_"):
            import astock
            value = astock._kline_source(operation.removeprefix("kline_"), *code)
        elif operation == "discovery_financials":
            import astock
            value = astock.financials(code, include_health=False)
        elif operation == "discovery_announcements":
            import astock
            value = astock.announcements(code, strict=True, with_coverage=True)
        elif operation == "financials":
            import astock
            def summary_checkpoint(summary):
                _write_result(path + ".checkpoint", dict(summary, status="partial", reason_code="SOURCE_TIMEOUT"))
            value = astock.financials(code, include_health=True, on_summary=summary_checkpoint)
            if not isinstance(value, dict) or not value:
                raise ValueError("financial source returned no usable summary")
        else:
            raise ValueError("unknown operation")
        _write_result(path, value)
    except Exception:
        # The parent reports a fixed unavailable code; never expose provider bodies.
        return


def _read_result(path):
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError()
        result = json.loads(raw)
        if not isinstance(result, dict) or "data" not in result:
            raise ValueError()
        return result["data"]
    except (OSError, ValueError):
        raise PublicDataUnavailable("SOURCE_BAD_RESPONSE") from None


def _run_process(operation, code=None, *, timeout=TIMEOUT, _target=None, cancel_event=None):
    if operation not in {"overview", "valuation", "financials", "daily_review",
                         "discovery_financials", "discovery_announcements",
                         "kline_hithink", "kline_mootdx", "kline_tencent"}:
        raise ValueError("unsupported public operation")
    if operation.startswith("kline_"):
        if (not isinstance(code, tuple) or len(code) != 3 or
                not isinstance(code[0], str) or len(code[0]) != 6 or
                not code[0].isascii() or not code[0].isdigit() or
                type(code[1]) is not int or code[1] not in (4, 5, 6, 11) or
                type(code[2]) is not int or not 1 <= code[2] <= 2000):
            raise ValueError("invalid kline arguments")
        import astock
        source = operation.removeprefix("kline_")
        if (source == "hithink" and code[1] != 4 or
                source == "mootdx" and code[0].startswith("92") or
                source == "tencent" and (code[1] not in (4, 5, 6) or astock.get_prefix(code[0]) == "bj")):
            raise ValueError("unsupported kline source route")
    if cancel_event is not None and cancel_event.is_set():
        raise PublicDataUnavailable("SOURCE_CANCELLED")
    if not _SLOTS.acquire(blocking=False):
        raise PublicDataUnavailable("SOURCE_BUSY")
    process = None
    started = False
    reaped = True
    try:
        deadline = time.monotonic() + timeout
        with tempfile.TemporaryDirectory(prefix="vibe-public-worker-") as temporary:
            path = str(Path(temporary) / "result.json")
            context = multiprocessing.get_context("spawn")
            process = context.Process(target=_target or _child, args=(path, operation, code), daemon=True)
            process.start()
            started = True
            if cancel_event is None:
                process.join(timeout=max(0, deadline - time.monotonic()))
            else:
                while process.is_alive() and not cancel_event.is_set() and time.monotonic() < deadline:
                    process.join(timeout=min(.05, max(0, deadline - time.monotonic())))
            cancelled = cancel_event is not None and cancel_event.is_set()
            timed_out = process.is_alive()
            if timed_out:
                process.kill()
                process.join(timeout=1)
            reaped = not process.is_alive()
            if not reaped:
                raise RuntimeError("Public data worker could not be reaped")
            if cancelled:
                raise PublicDataUnavailable("SOURCE_CANCELLED")
            if timed_out:
                checkpoint = path + ".checkpoint"
                if operation in {"valuation", "financials", "daily_review"} and os.path.isfile(checkpoint):
                    return _read_result(checkpoint)
                raise PublicDataUnavailable("SOURCE_TIMEOUT")
            if not os.path.isfile(path):
                checkpoint = path + ".checkpoint"
                if operation in {"valuation", "financials", "daily_review"} and os.path.isfile(checkpoint):
                    value = _read_result(checkpoint)
                    value["reason_code"] = "SOURCE_UNAVAILABLE"
                    return value
                raise PublicDataUnavailable("SOURCE_UNAVAILABLE")
            return _read_result(path)
    finally:
        if process is not None:
            if started and process.is_alive():
                process.kill()
                process.join(timeout=1)
                reaped = not process.is_alive()
            if not started or reaped:
                process.close()
        if reaped:
            _SLOTS.release()


_CACHE = {}
_INFLIGHT = set()
_LOCK = threading.Lock()


_OVERVIEW_LOCK = threading.Lock()
_OVERVIEW_FLIGHT = None
_OVERVIEW_THREAD = None
_OVERVIEW_CANCEL = None
_OVERVIEW_CLOSING = False


def startup():
    global _OVERVIEW_CLOSING
    with _OVERVIEW_LOCK:
        _OVERVIEW_CLOSING = False


def shutdown():
    """Cancel the admitted refresh and reap its actual provider process."""
    global _OVERVIEW_CLOSING
    with _OVERVIEW_LOCK:
        _OVERVIEW_CLOSING = True
        thread = _OVERVIEW_THREAD
        if _OVERVIEW_CANCEL is not None:
            _OVERVIEW_CANCEL.set()
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=3)
        if thread.is_alive():
            raise RuntimeError("Public overview supervisor did not stop")


def _refresh_overview(flight, cancel_event, seed, session):
    import market
    try:
        value = _run_process("overview", {"snapshot_seed": seed},
                             timeout=OVERVIEW_TIMEOUT, cancel_event=cancel_event)
        if market.overview_cacheable(value, session):
            with _LOCK:
                if len(_CACHE) >= 128:
                    _CACHE.pop(next(iter(_CACHE)))
                _CACHE[("overview", None)] = (time.monotonic(), copy.deepcopy(value))
        flight.set_result(value)
    except BaseException as error:
        flight.set_exception(error)


def _overview(*, timeout):
    """Bound response time separately from one globally admitted refresh lifetime."""
    global _OVERVIEW_FLIGHT, _OVERVIEW_THREAD, _OVERVIEW_CANCEL
    import market
    deadline = time.monotonic() + max(0, min(timeout, TIMEOUT))
    session = market.observation_session()
    completed = market.completed_overview()
    if completed is not None:
        return completed
    if not _OVERVIEW_LOCK.acquire(timeout=max(0, deadline - time.monotonic())):
        raise PublicDataUnavailable("SOURCE_REFRESH_PENDING")
    try:
        if _OVERVIEW_CLOSING:
            raise PublicDataUnavailable("SOURCE_CANCELLED")
        if not _LOCK.acquire(timeout=max(0, deadline - time.monotonic())):
            raise PublicDataUnavailable("SOURCE_REFRESH_PENDING")
        try:
            hit = _CACHE.get(("overview", None))
            if (hit and time.monotonic() - hit[0] < 300
                    and market.overview_cacheable(hit[1], session)):
                return copy.deepcopy(hit[1])
        finally:
            _LOCK.release()
        flight = _OVERVIEW_FLIGHT
        if flight is None or flight.done():
            if market.push2_guard.is_read_only():
                raise PublicDataUnavailable("SOURCE_READ_ONLY")
            flight = Future()
            cancel = threading.Event()
            _OVERVIEW_FLIGHT, _OVERVIEW_CANCEL = flight, cancel
            thread = threading.Thread(target=_refresh_overview,
                                      args=(flight, cancel, market.completed_snapshot_seed(), session),
                                      name="public-overview-refresh", daemon=True)
            _OVERVIEW_THREAD = thread
            try:
                thread.start()
            except BaseException:
                _OVERVIEW_FLIGHT = None
                _OVERVIEW_THREAD = None
                raise
    finally:
        _OVERVIEW_LOCK.release()
    try:
        value = copy.deepcopy(flight.result(timeout=max(0, deadline - time.monotonic())))
        # A refresh can straddle a session boundary. Keep its date/provenance;
        # never represent yesterday's completed observation as current.
        if isinstance(value, dict) and isinstance(value.get("sentiment"), dict):
            current_session = market.observation_session()
            if value["sentiment"].get("date") != current_session or current_session is None:
                value.update(status="partial", is_stale=True, reason_code="SOURCE_SESSION_CHANGED")
                value["sentiment"].update(status="partial", is_stale=True)
        return value
    except FutureTimeout:
        # No cancellation here: other readers share this single admitted refresh.
        raise PublicDataUnavailable("SOURCE_REFRESH_PENDING") from None


def run(operation, code=None, *, timeout=None, _target=None, cancel_event=None):
    if timeout is None:
        timeout = TIMEOUT
    if _target is not None:  # internal synthetic process-lifetime tests
        return _run_process(operation, code, timeout=timeout, _target=_target, cancel_event=cancel_event)
    if operation == "overview":
        return _overview(timeout=timeout)
    key = (operation, code)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and time.monotonic() - hit[0] < 30:
            return copy.deepcopy(hit[1])
        if key in _INFLIGHT:
            raise PublicDataUnavailable("SOURCE_BUSY")
        _INFLIGHT.add(key)
    try:
        kwargs = {"timeout": timeout}
        if cancel_event is not None:
            kwargs["cancel_event"] = cancel_event
        value = _run_process(operation, code, **kwargs)
        # Missing/failed results never suppress retry.
        cacheable = isinstance(value, dict) and (
            operation == "valuation" and value.get("price") is not None and value.get("status") != "partial" or
            operation == "financials" and value.get("revenue") is not None and value.get("net_profit") is not None and value.get("status") != "partial")
        if cacheable:
            with _LOCK:
                if len(_CACHE) >= 128:
                    _CACHE.pop(next(iter(_CACHE)))
                _CACHE[key] = (time.monotonic(), copy.deepcopy(value))
        return value
    finally:
        with _LOCK:
            _INFLIGHT.discard(key)
