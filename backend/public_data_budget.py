"""Hard lifetime bounds for legacy synchronous public-provider calls.

A spawned process owns provider threads/sockets. No app/lifespan is imported.
At most four children exist per backend; a timed-out child is killed and reaped.
"""
from __future__ import annotations

import copy
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import time

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 12.0
_SLOTS = threading.BoundedSemaphore(4)


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
            value = market.get_overview()
        elif operation == "valuation":
            import astock
            def checkpoint(value):
                partial = dict(value, status="partial", reason_code="SOURCE_TIMEOUT", analyst_count=None,
                               forecast_note="估值或一致预期来源尚未完成；保留已取得的行情与估值字段")
                _write_result(path + ".checkpoint", partial)
            value = astock.full_valuation(code, on_quote=checkpoint)
        elif operation == "financials":
            import astock
            value = astock.financials(code, include_health=True)
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


def _run_process(operation, code=None, *, timeout=TIMEOUT, _target=None):
    if operation not in {"overview", "valuation", "financials"}:
        raise ValueError("unsupported public operation")
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
            process.join(timeout=max(0, deadline - time.monotonic()))
            timed_out = process.is_alive()
            if timed_out:
                process.kill()
                process.join(timeout=1)
            reaped = not process.is_alive()
            if not reaped:
                raise RuntimeError("Public data worker could not be reaped")
            if timed_out:
                checkpoint = path + ".checkpoint"
                if operation == "valuation" and os.path.isfile(checkpoint):
                    return _read_result(checkpoint)
                raise PublicDataUnavailable("SOURCE_TIMEOUT")
            if not os.path.isfile(path):
                checkpoint = path + ".checkpoint"
                if operation == "valuation" and os.path.isfile(checkpoint):
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


def run(operation, code=None, *, timeout=TIMEOUT, _target=None):
    if _target is not None:  # internal synthetic process-lifetime tests
        return _run_process(operation, code, timeout=timeout, _target=_target)
    key = (operation, code)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and time.monotonic() - hit[0] < 30:
            return copy.deepcopy(hit[1])
        if key in _INFLIGHT:
            raise PublicDataUnavailable("SOURCE_BUSY")
        _INFLIGHT.add(key)
    try:
        value = _run_process(operation, code, timeout=timeout)
        # Cache only usable successes. Missing/failed results never suppress retry.
        cacheable = isinstance(value, dict) and (
            operation == "valuation" and value.get("price") is not None and value.get("status") != "partial" or
            operation == "overview" and value.get("sentiment", {}).get("status") == "normal" or
            operation == "financials" and value.get("revenue") is not None and value.get("net_profit") is not None)
        if cacheable:
            with _LOCK:
                if len(_CACHE) >= 128:
                    _CACHE.pop(next(iter(_CACHE)))
                _CACHE[key] = (time.monotonic(), copy.deepcopy(value))
        return value
    finally:
        with _LOCK:
            _INFLIGHT.discard(key)
