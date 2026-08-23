"""Bounded live qualification probe for the HiThink Financial API.

This is an operator tool, not a production authority.  It reads the API key
only from ``HITHINK_FINANCE_API_KEY`` and emits bounded, URL-free summaries.
Raw JSON responses are never persisted.  Optional market-dump downloads are
kept in an operator-selected directory and inspected with DuckDB.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import requests


BASE_URL = "https://fuyao.aicubes.cn"
API_KEY_ENV = "HITHINK_FINANCE_API_KEY"
SECRET_KEYS = {
    "api_key", "apikey", "token", "access_token", "refresh_token",
    "secret", "secret_key", "authorization", "x-api-key", "password",
    "credential", "presigned_url",
}
MAX_SAMPLE_IDENTITIES = 8


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key() -> str:
    value = os.environ.get(API_KEY_ENV, "").strip()
    if not value:
        raise RuntimeError(f"{API_KEY_ENV} is not set")
    return value


def _is_secret_key(value: str) -> bool:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "")
    return normalized in SECRET_KEYS or normalized.endswith("_token")


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def _item_summary(items: list[Any]) -> dict[str, Any]:
    rows = [item for item in items if isinstance(item, dict)]
    identities: list[str] = []
    dates: list[int] = []
    for row in rows:
        identity = row.get("thscode")
        if isinstance(identity, str) and identity not in identities:
            identities.append(identity)
        for field in ("date_ms", "period_end_ms", "ex_date_ms"):
            value = row.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                dates.append(value)
                break
    duplicate_dates = len(dates) - len(set(dates))
    if not dates:
        ordering = "EMPTY"
    elif dates == sorted(dates):
        ordering = "ASCENDING"
    elif dates == sorted(dates, reverse=True):
        ordering = "DESCENDING"
    else:
        ordering = "NON_MONOTONIC"
    first = rows[0] if rows else {}
    return {
        "count": len(items),
        "row_count": len(rows),
        "sample_identities": identities[:MAX_SAMPLE_IDENTITIES],
        "first_item_keys": sorted(
            key for key in first if not _is_secret_key(str(key))
        ),
        "first_item_types": {
            key: _type_name(value)
            for key, value in sorted(first.items())
            if not _is_secret_key(str(key))
        },
        "null_fields_in_first_item": sorted(
            key for key, value in first.items()
            if value is None and not _is_secret_key(str(key))
        ),
        "date_count": len(dates),
        "date_min_ms": min(dates) if dates else None,
        "date_max_ms": max(dates) if dates else None,
        "date_ordering": ordering,
        "duplicate_date_count": duplicate_dates,
    }


def _data_summary(data: Any) -> dict[str, Any]:
    if data is None:
        return {"type": "null"}
    if isinstance(data, list):
        return {"type": "list", **_item_summary(data)}
    if not isinstance(data, dict):
        return {"type": _type_name(data)}
    keys = sorted(key for key in data if not _is_secret_key(str(key)))
    result: dict[str, Any] = {
        "type": "dict",
        "keys": keys,
        "types": {
            key: _type_name(value)
            for key, value in sorted(data.items())
            if not _is_secret_key(str(key))
        },
    }
    items = data.get("item", data.get("items"))
    if isinstance(items, list):
        result["items"] = _item_summary(items)
    abilities = data.get("abilities")
    if isinstance(abilities, list):
        result["abilities"] = [
            {
                "ability": value.get("ability"),
                "indicator_count": len(value.get("indicators", []))
                if isinstance(value, dict) and isinstance(value.get("indicators"), list)
                else None,
                "null_indicator_count": sum(
                    1 for indicator in value.get("indicators", [])
                    if isinstance(indicator, dict) and indicator.get("value") is None
                ) if isinstance(value, dict) else None,
            }
            for value in abilities
        ]
    boards = data.get("boards")
    if isinstance(boards, dict):
        result["board_counts"] = {
            str(key): len(value) if isinstance(value, list) else None
            for key, value in sorted(boards.items())
        }
    return result


def _status(http_status: int | None, code: Any) -> str:
    if type(code) is not int:
        return "UNKNOWN"
    if http_status == 200 and code == 0:
        return "PASS"
    if code in {2001, 2002, 2003, 2004} or http_status in {401, 403}:
        return "DENIED"
    if code in {3001, 3004, 4040} or http_status == 404:
        return "NOT_AVAILABLE"
    return "UNKNOWN"


def _safe_message(value: Any, key: str) -> str | None:
    if value is None:
        return None
    # Do not trust provider-controlled error text: scrub the active credential
    # before the bounded summary can reach disk or stdout.
    return str(value).replace(key, "<redacted>")[:160]


def get_json(
    session: requests.Session,
    key: str,
    dataset_id: str,
    path: str,
    query: dict[str, Any] | None = None,
    *,
    timeout: int = 30,
) -> tuple[dict[str, Any], Any]:
    started = time.perf_counter()
    try:
        response = session.get(
            BASE_URL + path,
            params=query or {},
            headers={"X-api-key": key},
            timeout=timeout,
            allow_redirects=False,
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        raw_code = payload.get("code") if isinstance(payload, dict) else None
        code = raw_code if type(raw_code) is int else None
        data = payload.get("data") if isinstance(payload, dict) else None
        result = {
            "dataset_id": dataset_id,
            "endpoint": path,
            "status": _status(response.status_code, code),
            "http_status": response.status_code,
            "envelope_code": code,
            "envelope_code_type": _type_name(raw_code),
            "message": _safe_message(payload.get("message"), key)
            if isinstance(payload, dict) else None,
            "request_id_present": bool(
                isinstance(payload, dict) and payload.get("request_id")
            ),
            "latency_ms": latency_ms,
            "data": _data_summary(data),
        }
        return result, data
    except requests.RequestException as exc:
        return ({
            "dataset_id": dataset_id,
            "endpoint": path,
            "status": "UNKNOWN",
            "http_status": None,
            "envelope_code": None,
            "message": None,
            "request_id_present": False,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "transport_error": type(exc).__name__,
            "data": {"type": "absent"},
        }, None)


def _ms(date_value: str) -> int:
    parsed = datetime.strptime(date_value, "%Y-%m-%d").replace(
        tzinfo=ZoneInfo("Asia/Shanghai")
    )
    return int(parsed.timestamp() * 1000)


def _probe_matrix(session: requests.Session, key: str) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []

    def probe(dataset_id: str, path: str, query: dict[str, Any] | None = None) -> Any:
        observation, data = get_json(session, key, dataset_id, path, query)
        observations.append(observation)
        return data

    name_data = probe(
        "security_search_name", "/api/meta/tickers/search",
        {"q": "贵州茅台", "asset_type": "a-share", "limit": 5},
    )
    probe(
        "security_search_code", "/api/meta/tickers/search",
        {"q": "600519", "asset_type": "a-share", "limit": 5},
    )
    bse_data = probe(
        "security_list_bse", "/api/meta/tickers/list",
        {"exchange": "BJ", "asset_type": "a-share", "limit": 5, "offset": 0},
    )
    bse_symbol = None
    bse_candidates: list[dict[str, Any]] = []
    if isinstance(bse_data, dict) and isinstance(bse_data.get("item"), list):
        for item in bse_data["item"]:
            if not isinstance(item, dict):
                continue
            candidate = {
                key: item.get(key)
                for key in ("thscode", "ticker", "name", "exchange", "asset_type")
            }
            bse_candidates.append(candidate)
            if isinstance(item.get("thscode"), str) and item["thscode"].endswith(".BJ"):
                bse_symbol = item["thscode"]
    bse_search_candidates: list[dict[str, Any]] = []
    for search_term in ("920", "83", "87", "北交"):
        search_data = probe(
            f"security_search_bse_{search_term}", "/api/meta/tickers/search",
            {
                "q": search_term, "exchange": "BJ", "asset_type": "a-share",
                "limit": 10,
            },
        )
        if not isinstance(search_data, dict) or not isinstance(search_data.get("item"), list):
            continue
        for item in search_data["item"]:
            if not isinstance(item, dict):
                continue
            symbol = item.get("thscode")
            if not isinstance(symbol, str) or not symbol.endswith(".BJ"):
                continue
            candidate = {
                key: item.get(key)
                for key in ("thscode", "ticker", "name", "exchange", "asset_type")
            }
            if candidate not in bse_search_candidates:
                bse_search_candidates.append(candidate)
            if bse_symbol is None:
                bse_symbol = symbol
    # 920000.BJ was discovered from the provider's qualified 10-day market
    # dump, not guessed.  Re-query it through meta without the broken BJ
    # filter to distinguish filter drift from missing identity coverage.
    for search_term in ("920000", "920000.BJ"):
        search_data = probe(
            f"security_search_bse_exact_{search_term}",
            "/api/meta/tickers/search",
            {"q": search_term, "asset_type": "a-share", "limit": 10},
        )
        if not isinstance(search_data, dict) or not isinstance(search_data.get("item"), list):
            continue
        for item in search_data["item"]:
            if not isinstance(item, dict):
                continue
            symbol = item.get("thscode")
            if not isinstance(symbol, str) or not symbol.endswith(".BJ"):
                continue
            candidate = {
                key: item.get(key)
                for key in ("thscode", "ticker", "name", "exchange", "asset_type")
            }
            if candidate not in bse_search_candidates:
                bse_search_candidates.append(candidate)
            if bse_symbol is None:
                bse_symbol = symbol
    probe("trading_calendar", "/api/a-share/calendar/trading-days")
    snapshot_symbols = ["600519.SH", "000001.SZ"]
    if isinstance(bse_symbol, str):
        snapshot_symbols.append(bse_symbol)
    probe(
        "latest_snapshot", "/api/a-share/prices/snapshot",
        {"thscodes": ",".join(snapshot_symbols)},
    )
    probe(
        "daily_bars_short", "/api/a-share/prices/historical",
        {
            "thscode": "600519.SH", "interval": "1d", "adjust": "none",
            "start": _ms("2026-08-01"), "end": _ms("2026-08-21"),
        },
    )
    if isinstance(bse_symbol, str):
        probe(
            "daily_bars_bse", "/api/a-share/prices/historical",
            {
                "thscode": bse_symbol, "interval": "1d", "adjust": "none",
                "start": _ms("2026-08-01"), "end": _ms("2026-08-21"),
            },
        )
    probe(
        "daily_bars_long", "/api/a-share/prices/historical",
        {
            "thscode": "600519.SH", "interval": "1d", "adjust": "none",
            "start": _ms("2017-01-01"), "end": _ms("2026-08-21"),
        },
    )
    for adjust in ("forward", "backward"):
        probe(
            f"daily_bars_{adjust}", "/api/a-share/prices/historical",
            {
                "thscode": "600519.SH", "interval": "1d", "adjust": adjust,
                "start": _ms("2026-01-01"), "end": _ms("2026-08-21"),
            },
        )
    probe(
        "corporate_actions", "/api/a-share/corporate-actions/adjustment-factors",
        {"thscode": "600519.SH", "from": "2017-01-01", "to": "2026-08-21"},
    )
    for name, endpoint in (
        ("income_statements", "income-statements"),
        ("balance_sheets", "balance-sheets"),
        ("cash_flow_statements", "cash-flow-statements"),
    ):
        probe(
            name, f"/api/a-share/financials/{endpoint}",
            {"thscode": "600519.SH", "period": "annual", "limit": 5},
        )
    probe(
        "financial_indicators", "/api/a-share/financials/indicators",
        {"thscode": "600519.SH", "report": "2025-4"},
    )
    probe(
        "valuation_snapshot", "/api/a-share/valuations/snapshot",
        {"thscodes": "600519.SH,000001.SZ"},
    )
    concept_data = probe(
        "concept_catalog", "/api/a-share-index/catalog/ths-index-list",
        {"tag": "cn_concept"},
    )
    industry_data = probe(
        "industry_catalog", "/api/a-share-index/catalog/ths-index-list",
        {"tag": "industry"},
    )
    chosen_indices: list[str] = []
    for data in (concept_data, industry_data):
        if isinstance(data, dict) and isinstance(data.get("item"), list):
            for item in data["item"]:
                if isinstance(item, dict) and isinstance(item.get("thscode"), str):
                    chosen_indices.append(item["thscode"])
                    break
    for index, symbol in enumerate(chosen_indices, start=1):
        probe(
            f"index_constituents_{index}",
            "/api/a-share-index/constituents/ths-stock-list",
            {"thscode": symbol},
        )
    if chosen_indices:
        probe(
            "index_snapshot", "/api/a-share-index/prices/snapshot",
            {"thscodes": ",".join(chosen_indices)},
        )
        probe(
            "index_historical", "/api/a-share-index/prices/historical",
            {
                "thscode": chosen_indices[0], "interval": "1d",
                "start": _ms("2026-01-01"), "end": _ms("2026-08-21"),
            },
        )
    probe(
        "limit_up_pool", "/api/a-share/special-data/limit-up-pool",
        {"date_ms": _ms("2026-08-21"), "page": 1, "size": 20},
    )
    probe("limit_up_ladder", "/api/a-share/special-data/limit-up-ladder")
    probe(
        "anomaly_list", "/api/a-share/special-data/anomaly-analysis-list",
        {"tag_codes": "LIMIT_UP,LIMIT_DOWN"},
    )
    probe(
        "anomaly_stock", "/api/a-share/special-data/anomaly-analysis-stock",
        {"thscodes": "600519.SH,000001.SZ"},
    )
    probe(
        "invalid_symbol_error", "/api/a-share/prices/historical",
        {
            "thscode": "999999.ZZ", "interval": "1d", "adjust": "none",
            "start": _ms("2026-08-01"), "end": _ms("2026-08-21"),
        },
    )
    resolved = {
        "name_search_expected_symbol_present": _contains_symbol(name_data, "600519.SH"),
        "bse_symbol_discovered": bse_symbol,
        "bse_candidates": bse_candidates,
        "bse_search_candidates": bse_search_candidates,
        "selected_indices": chosen_indices,
    }
    return {"observations": observations, "resolved": resolved}


def _contains_symbol(data: Any, symbol: str) -> bool:
    if not isinstance(data, dict) or not isinstance(data.get("item"), list):
        return False
    return any(
        isinstance(item, dict) and item.get("thscode") == symbol
        for item in data["item"]
    )


def _dump_profile(path: Path, kind: str) -> dict[str, Any]:
    connection = duckdb.connect(":memory:")
    quoted = str(path).replace("'", "''")
    relation = f"read_parquet('{quoted}')"
    columns = connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    schema = [{"name": row[0], "type": row[1]} for row in columns]
    row_count = connection.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]
    security_count = connection.execute(
        f"SELECT count(DISTINCT thscode) FROM {relation}"
    ).fetchone()[0]
    date_column = "date_ms" if kind.startswith("daily-k") else "ex_date_ms"
    date_min, date_max = connection.execute(
        f"SELECT min({date_column}), max({date_column}) FROM {relation}"
    ).fetchone()
    key_columns = "thscode, date_ms" if kind.startswith("daily-k") else (
        "thscode, ex_date_ms, dividend_per_share, per_share_bonus, "
        "allotment_ratio, allotment_price"
    )
    duplicate_count = connection.execute(
        f"SELECT count(*) - count(DISTINCT ({key_columns})) FROM {relation}"
    ).fetchone()[0]
    null_counts: dict[str, int] = {}
    for column in ("thscode", date_column):
        null_counts[column] = connection.execute(
            f"SELECT count(*) FILTER (WHERE {column} IS NULL) FROM {relation}"
        ).fetchone()[0]
    bse_security_count = connection.execute(
        f"SELECT count(DISTINCT thscode) FROM {relation} "
        "WHERE thscode LIKE '%.BJ'"
    ).fetchone()[0]
    bse_sample_symbols = [
        row[0]
        for row in connection.execute(
            f"SELECT DISTINCT thscode FROM {relation} "
            "WHERE thscode LIKE '%.BJ' ORDER BY thscode LIMIT 5"
        ).fetchall()
    ]
    duplicate_examples: list[dict[str, Any]] = []
    if kind == "adjustment-factors":
        duplicate_rows = connection.execute(
            f"SELECT thscode, ex_date_ms, dividend_per_share, per_share_bonus, "
            f"allotment_ratio, allotment_price, count(*) AS n FROM {relation} "
            "GROUP BY ALL HAVING count(*) > 1 ORDER BY thscode, ex_date_ms LIMIT 5"
        ).fetchall()
        duplicate_examples = [
            {
                "thscode": row[0],
                "ex_date_ms": row[1],
                "dividend_per_share": row[2],
                "per_share_bonus": row[3],
                "allotment_ratio": row[4],
                "allotment_price": row[5],
                "count": row[6],
            }
            for row in duplicate_rows
        ]
    connection.close()
    return {
        "schema": schema,
        "row_count": row_count,
        "security_count": security_count,
        "date_column": date_column,
        "date_min_ms": date_min,
        "date_max_ms": date_max,
        "duplicate_key_count": duplicate_count,
        "duplicate_examples": duplicate_examples,
        "null_counts": null_counts,
        "bse_security_count": bse_security_count,
        "bse_sample_symbols": bse_sample_symbols,
    }


def _qualify_dumps(
    session: requests.Session,
    key: str,
    mode: str,
    output_dir: Path,
) -> list[dict[str, Any]]:
    specs = [
        ("daily-k", "/api/dump/market-dumps/daily-k/download-url"),
        ("daily-k-10d", "/api/dump/market-dumps/daily-k-10d/download-url"),
        ("adjustment-factors", "/api/dump/market-dumps/adjustment-factors/download-url"),
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for kind, endpoint in specs:
        observation, data = get_json(session, key, f"market_dump_{kind}", endpoint)
        result: dict[str, Any] = {"signing": observation, "kind": kind}
        url = data.get("presigned_url") if isinstance(data, dict) else None
        result["expires_at_present"] = bool(
            isinstance(data, dict) and data.get("presigned_url_expires_at")
        )
        should_download = mode == "all" or (
            mode == "recent" and kind in {"daily-k-10d", "adjustment-factors"}
        )
        if observation["status"] != "PASS" or not isinstance(url, str):
            result["download"] = {"status": "NOT_RUN"}
            results.append(result)
            continue
        try:
            head = session.head(url, allow_redirects=False, timeout=30)
            result["remote"] = {
                "head_status": head.status_code,
                "content_length": int(head.headers["Content-Length"])
                if head.headers.get("Content-Length", "").isdigit() else None,
                "etag_present": bool(head.headers.get("ETag")),
                "last_modified": head.headers.get("Last-Modified"),
                "content_type": head.headers.get("Content-Type"),
            }
        except requests.RequestException as exc:
            result["remote"] = {"head_error": type(exc).__name__}
        if not should_download:
            result["download"] = {"status": "NOT_RUN"}
            results.append(result)
            continue
        target = output_dir / f"hithink-{kind}-20260824.parquet"
        started = time.perf_counter()
        digest = hashlib.sha256()
        size = 0
        try:
            with session.get(
                url, stream=True, timeout=(30, 300), allow_redirects=False
            ) as response:
                response.raise_for_status()
                with target.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            profile = _dump_profile(target, kind)
            result["download"] = {
                "status": "PASS",
                "path": str(target),
                "bytes": size,
                "sha256": digest.hexdigest(),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "profile": profile,
            }
            resign, resigned_data = get_json(
                session, key, f"market_dump_{kind}_resign", endpoint
            )
            result["recovery_resign"] = {
                "status": resign["status"],
                "http_status": resign["http_status"],
                "envelope_code": resign["envelope_code"],
                "new_url_present": bool(
                    isinstance(resigned_data, dict)
                    and resigned_data.get("presigned_url")
                ),
            }
        except (requests.RequestException, duckdb.Error, OSError) as exc:
            result["download"] = {
                "status": "UNKNOWN",
                "error_class": type(exc).__name__,
                "bytes_before_failure": size,
                "path": str(target),
            }
        results.append(result)
    return results


def run(mode: str, output_dir: Path) -> dict[str, Any]:
    key = _key()
    with requests.Session() as session:
        matrix = _probe_matrix(session, key)
        dumps = _qualify_dumps(session, key, mode, output_dir)
    return {
        "schema_version": "hithink-qualification-observation-v0.1",
        "provider": "hithink",
        "fetched_at": _utc_now(),
        "probe_mode": mode,
        **matrix,
        "market_dumps": dumps,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--download-dumps", choices=("none", "recent", "all"), default="none"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dump-dir", type=Path)
    parser.add_argument("--profile-existing", type=Path)
    parser.add_argument(
        "--profile-kind",
        choices=("daily-k", "daily-k-10d", "adjustment-factors"),
    )
    args = parser.parse_args()
    if args.profile_existing is not None:
        if args.profile_kind is None:
            parser.error("--profile-existing requires --profile-kind")
        print(json.dumps(
            _dump_profile(args.profile_existing.resolve(), args.profile_kind),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    if args.output is None or args.dump_dir is None:
        parser.error("--output and --dump-dir are required for a live probe")
    result = run(args.download_dumps, args.dump_dir.resolve())
    args.output.resolve().write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
