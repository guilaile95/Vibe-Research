"""Fixed public-source collection inside the disposable daily worker.

No application lifespan or private archive writes. Checkpoints are serialized under
one lock; the parent reads them only after the worker has exited or been reaped.
"""
from __future__ import annotations
import json
import threading

KEYS = ("indices", "global_indices", "breadth", "emotion", "turnover", "industry", "concept", "region")


def collect(checkpoint):
    import astock
    import market
    from public_data_budget import MAX_BYTES
    calls = {
        "indices": astock.index_quote,
        "global_indices": market.get_global_indices,
        "breadth": market.get_market_breadth,
        "emotion": market.get_short_term_emotion,
        "turnover": market.get_turnover_top,
        "industry": lambda: market.get_board_ranking("industry", top_n=10),
        "concept": lambda: market.get_board_ranking("concept", top_n=10),
        "region": lambda: market.get_board_ranking("region", top_n=10),
    }
    result = {}
    lock = threading.Lock()

    def one(key):
        try:
            entry = {"status": "complete", "value": calls[key]()}
            raw = json.dumps(entry, allow_nan=False, ensure_ascii=False).encode("utf-8")
            if len(raw) > (MAX_BYTES - 4096) // len(KEYS):
                raise ValueError("source result too large")
            entry = json.loads(raw)
        except Exception:
            entry = {"status": "unavailable"}
        with lock:
            result[key] = entry
            packet = {"sources": result, "reason_code": "SOURCE_TIMEOUT"}
            if len(json.dumps({"data": packet}, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_BYTES:
                result[key] = {"status": "unavailable"}
            checkpoint(packet)

    threads = [threading.Thread(target=one, args=(key,), daemon=True) for key in KEYS]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return {"sources": result, "reason_code": None}
