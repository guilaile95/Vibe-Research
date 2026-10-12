"""Offline provider adapters over exact captured bytes, never network clients.

An EastMoney receipt without source totals/date proof is retained but is not
complete. Tushare daily rows cover requested identities, never yesterday's
survivors only. All display truncation occurs after these adapters.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import shortline_research_contract as C

NORMALIZER = "shortline-captured-providers.v1"
_SH = timezone(timedelta(hours=8))


def _source_day(value):
    if type(value) is int:
        value = str(value)
    if type(value) is str and len(value) == 8 and value.isdigit():
        value = f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return C.day(value)


def _seal(value):
    if type(value) is int:
        value = str(value).zfill(6)
    if type(value) is not str or len(value) != 6 or not value.isdigit():
        return None
    try:
        datetime.strptime(value, "%H%M%S")
    except ValueError:
        return None
    return value if "092500" <= value <= "113000" or "130000" <= value <= "150000" else None


def normalize_capture(raw: bytes, metadata: dict) -> dict:
    """Normalize a single exact provider page; metadata contains no credentials.

    Page coordination and receipt integrity belong to the archive/capture layer.
    Metadata is transport evidence, not source business-date or finality proof.
    """
    kind, requested = metadata["kind"], C.day(metadata["trade_date"])
    if kind not in C.KINDS or metadata["endpoint"] != C.ENDPOINTS[kind]:
        raise ValueError("unsupported endpoint")
    captured = C.instant(metadata["captured_at"])
    if captured.astimezone(_SH).date().isoformat() < requested:
        raise ValueError("capture predates business date")
    out = {"schema_version": C.VERSION, "normalizer_version": NORMALIZER, "kind": kind,
           "trade_date": requested, "status": "unavailable", "reason_codes": [], "rows": [],
           "raw_row_count": 0, "excluded_count": 0, "source_total": None,
           "source_fields": None, "source_finality": "unknown", "source_revision": None, "complete": False,
           "post_close_observation": captured >= datetime.fromisoformat(requested + "T15:00:00+08:00"),
           "fixture": metadata["fixture"], "price_unit": "CNY/share", "source_group": {
               "provider": metadata["provider"], "endpoint": metadata["endpoint"],
               "normalizer_version": NORMALIZER, "request_shape": metadata["request_shape"]}}
    if metadata["http_status"] != 200:
        out["reason_codes"] = ["TRANSPORT_FAILED"]
        return out
    payload = C.decode(raw)
    data = payload.get("data")
    if type(data) is not dict:
        out["reason_codes"] = ["SOURCE_DATA_MISSING"]
        return out
    revision = data.get("revision_id")
    if type(revision) is str and 0 < len(revision) <= 128:
        out["source_revision"] = revision
    rows = []
    if kind in ("limit_up", "broken", "limit_down"):
        if metadata["provider"] != "eastmoney_push2ex":
            raise ValueError("provider mismatch")
        dates = [payload[key] for key in ("date", "trade_date") if key in payload]
        dates += [data[key] for key in ("date", "trade_date") if key in data]
        if not dates or any(_source_day(value) != requested for value in dates):
            out["reason_codes"] = ["SOURCE_DATE_UNPROVEN"]
            return out
        rows = data.get("pool")
        totals = [data[key] for key in ("tc", "total") if key in data]
        if totals and all(C.integer(n) is not None and n == totals[0] for n in totals):
            out["source_total"] = totals[0]
        elif totals:
            raise ValueError("conflicting source totals")
    else:
        if metadata["provider"] != "tushare_pro" or payload.get("code") != 0 or type(payload.get("code")) is not int:
            out["reason_codes"] = ["PROVIDER_RESPONSE_FAILED"]
            return out
        fields, items = data.get("fields"), data.get("items")
        if (type(fields) is not list or not fields or any(type(x) is not str for x in fields)
                or len(set(fields)) != len(fields) or type(items) is not list
                or any(type(x) is not list or len(x) != len(fields) for x in items)):
            raise ValueError("invalid tabular response")
        rows = [dict(zip(fields, item)) for item in items]
        # Request is an explicit bounded identity batch. Completion is decided
        # by identity coverage after all rows are preserved, not row-count guess.
    if type(rows) is not list or len(rows) > C.MAX_ROWS or any(type(row) is not dict for row in rows):
        raise ValueError("invalid or oversized source rows")
    out["raw_row_count"], out["source_fields"] = len(rows), C.source_fields(rows)
    if data.get("is_final") is True:
        out["source_finality"] = "source_declared_final"
    elif data.get("is_final") is False:
        out["source_finality"] = "source_declared_provisional"
    seen = set()
    for row in rows:
        symbol = C.code(row.get("c") if kind in ("limit_up", "broken", "limit_down") else row.get("ts_code"))
        if symbol in seen:
            raise ValueError("duplicate source stock")
        seen.add(symbol)
        if symbol.startswith(("43", "83", "87", "88", "92")):
            out["excluded_count"] += 1
            continue
        normalized = {"stock_code": symbol, "source_trade_date": requested}
        if kind in ("limit_up", "broken", "limit_down"):
            first, last = _seal(row.get("fbt")), _seal(row.get("lbt"))
            if first is not None and last is not None and first > last:
                first = last = None
            boards = C.integer(row.get("lbc"), minimum=1)
            boards = boards if boards is not None and boards <= 10000 else None
            normalized.update(boards=boards, first_seal=first, last_seal=last,
                              broken_times=C.integer(row.get("zbc")), seal_fund_yuan=C.finite(row.get("fund")),
                              zt_stat=row.get("zttj") if type(row.get("zttj")) is dict else None)
            if normalized["seal_fund_yuan"] is not None and normalized["seal_fund_yuan"] < 0:
                normalized["seal_fund_yuan"] = None
        else:
            if _source_day(row.get("trade_date")) != requested:
                raise ValueError("mixed source business dates")
            if kind == "daily_limits":
                normalized.update(limit_up=C.finite(row.get("up_limit"), positive=True),
                                  limit_down=C.finite(row.get("down_limit"), positive=True))
                if normalized["limit_up"] is not None and normalized["limit_down"] is not None and normalized["limit_down"] > normalized["limit_up"]:
                    normalized.update(limit_up=None, limit_down=None)
            else:
                values = {key: C.finite(row.get(source), positive=True) for key, source in
                          (("open", "open"), ("high", "high"), ("low", "low"), ("close", "close"), ("previous_close", "pre_close"))}
                volume = C.finite(row.get("vol"), positive=True)
                # Positive provider daily volume is explicit session trading evidence.
                # A row of stale OHLC with zero/unknown volume is not flat trading.
                trading_status = row.get("trade_status", "traded" if volume is not None else "unknown")
                valid = trading_status == "traded" and volume is not None and all(v is not None and 0.01 <= v <= 1_000_000_000 for v in values.values())
                if valid:
                    valid = values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"]
                # Daily pre_close is the provider's ex-right reference for this
                # session, not an independently joined previous raw close.
                return_pct = C.finite(float((Decimal(str(values["close"])) / Decimal(str(values["previous_close"])) - 1) * 100)) if valid else None
                open_premium = C.finite(float((Decimal(str(values["open"])) / Decimal(str(values["previous_close"])) - 1) * 100)) if valid else None
                valid = valid and return_pct is not None and open_premium is not None
                normalized.update(**values, volume_lots=volume, price_valid=valid, trading_status="traded" if valid else trading_status if trading_status in ("suspended", "delisted") else "unknown",
                                  adjustment="unadjusted", reference_basis="provider_daily_exright_reference",
                                  return_pct=return_pct if valid else None,
                                  open_premium_pct=open_premium if valid else None)
        out["rows"].append(normalized)
    out["rows"].sort(key=lambda row: row["stock_code"])
    if kind in ("limit_up", "broken", "limit_down"):
        out["complete"] = out["source_total"] is not None and out["source_total"] == len(rows) and metadata["page_index"] == 0
        # Explicit total=0 plus bound business date is positive zero evidence.
        if not out["complete"]:
            out["reason_codes"].append("POOL_TOTAL_OR_PAGES_INCOMPLETE")
    else:
        expected = set(metadata["requested_codes"])
        actual = {row["stock_code"] for row in out["rows"]}
        if actual - expected:
            raise ValueError("unexpected identity in requested price batch")
        out["complete"] = actual == expected
        if not expected or not out["complete"]:
            out["reason_codes"].append("REQUESTED_IDENTITIES_MISSING")
    if not out["post_close_observation"]:
        out["reason_codes"].append("PRE_CLOSE_OBSERVATION")
    if out["source_finality"] == "source_declared_provisional":
        out["reason_codes"].append("SOURCE_PROVISIONAL")
    out["status"] = "normal" if out["complete"] and out["post_close_observation"] and out["source_finality"] != "source_declared_provisional" else "partial"
    return out


def same_cent(left, right):
    """Exact cent grid, no loose percentage threshold or one-cent tolerance."""
    if C.finite(left, positive=True) is None or C.finite(right, positive=True) is None:
        return None
    a, b = Decimal(str(left)) * 100, Decimal(str(right)) * 100
    if a != a.to_integral_value() or b != b.to_integral_value():
        return None
    return a == b
