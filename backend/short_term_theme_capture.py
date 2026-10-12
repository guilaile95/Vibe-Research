"""Offline provider-byte adapters. No provider calls, credentials or schedules.

The ingestion functions accept already captured public-market bytes. They are
never called by GET, app startup, a collector, or a scheduler. Each page is stored
through the existing FactLake immutable observation API, not a second store.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
import trade_calendar

from data_contracts import (ProviderObservation, FetchSemantics, HistoryMode, QualityStatus)
from short_term_theme_research import THEME_DATASET, THEME_NORMALIZER, normalize_ths_theme_pages

PRICE_DATASET = 'research_shortline_leader_prices'
PRICE_NORMALIZER = 'tencent-forward-captured-series-v1'
THS_ENDPOINT = 'https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool'
PRICE_ENDPOINT = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'


def _json(raw: bytes):
    if not isinstance(raw, bytes) or not raw or len(raw) > 16 * 1024 * 1024:
        raise ValueError('CAPTURE_BYTES_INVALID')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('CAPTURE_DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('CAPTURE_NONFINITE_JSON')))


def _hash(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _receipt(*, dataset, provider, endpoint, symbol, day, captured_at, raw, normalizer, metadata):
    if type(metadata.get('fixture')) is not bool:
        raise ValueError('FIXTURE_FLAG_REQUIRED')
    captured = datetime.fromisoformat(captured_at.replace('Z', '+00:00'))
    if captured.tzinfo is None or captured.utcoffset() != timezone.utc.utcoffset(captured) or captured.date().isoformat() < day or captured > datetime.now(timezone.utc):
        raise ValueError('CAPTURE_TIME_INVALID')
    captured_at = captured.isoformat(timespec='microseconds').replace('+00:00', 'Z')
    fingerprint = _hash(json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode())
    identity = _hash((dataset + fingerprint + _hash(raw) + captured_at).encode()).split(':')[1]
    return ProviderObservation(
        observation_id='research-' + identity, dataset_id=dataset, provider_id=provider,
        provider_endpoint=endpoint, provider_symbol=symbol, request_fingerprint=fingerprint,
        source_payload_hash=_hash(raw), normalizer_version=normalizer, payload=metadata,
        fetch_semantics=FetchSemantics.SNAPSHOT, history_mode=HistoryMode.SNAPSHOT_WITH_BACKFILL,
        fetched_at=captured_at, trade_date=day, quality_status=QualityStatus.VALID,
    )


def store_ths_theme_capture(lake, pages: list[bytes], *, trade_date: str, captured_at: str, fixture: bool = False):
    """Validate complete dated batch before storing original page bytes unchanged."""
    if not isinstance(pages, list) or not pages or any(type(p) is not bytes for p in pages) or sum(len(p) for p in pages) > 32 * 1024 * 1024:
        raise ValueError('THEME_BATCH_BYTES_OVERSIZED')
    normalized = normalize_ths_theme_pages([_json(p) for p in pages], trade_date)
    hashes = [_hash(p) for p in pages]
    batch = _hash(json.dumps(hashes, separators=(',', ':')).encode())
    receipts = [_receipt(dataset=THEME_DATASET, provider='ths', endpoint=THS_ENDPOINT, symbol='HS,GEM2STAR',
                        day=trade_date, captured_at=captured_at, raw=raw, normalizer=THEME_NORMALIZER,
                        metadata={'schema_version': 'theme-capture-manifest-v1', 'capture_batch_id': batch,
                                  'page_index': i, 'page_count': len(pages), 'page_hashes': hashes,
                                  'fixture': fixture, 'source_available_at': None, 'source_finality': 'unknown',
                                  'source_total': normalized['source_total'], 'completeness': 'complete'})
                for i, raw in enumerate(pages)]
    return tuple(lake.store_observation(r, raw, content_type='application/json').stored for r, raw in zip(receipts, pages))


def normalize_tencent_forward_capture(raw: bytes, *, stock_code: str) -> dict:
    """One qfqday response = one provider adjustment basis; never join vintages.

    Same-response basis is provider asserted, not independently reconciled. Zero
    trading volume is unknown/paused, and no carried-forward return is calculated.
    """
    if not re.fullmatch(r'(?:60|68|00|30)\d{4}', stock_code):
        raise ValueError('PRICE_SYMBOL_UNSUPPORTED')
    if type(raw) is not bytes or len(raw) > 1024 * 1024:
        raise ValueError('PRICE_CAPTURE_BYTES_OVERSIZED')
    symbol = ('sh' if stock_code.startswith(('60', '68')) else 'sz') + stock_code
    payload = _json(raw)
    series = payload.get('data', {}).get(symbol, {}) if isinstance(payload, dict) else {}
    bars = series.get('qfqday') if isinstance(series, dict) else None
    if not isinstance(bars, list) or not bars or len(bars) > 320:
        raise ValueError('FORWARD_ADJUSTED_SERIES_REQUIRED')
    previous, rows = None, []
    for item in bars:
        if not isinstance(item, list) or len(item) < 6 or not isinstance(item[0], str):
            raise ValueError('PRICE_ROW_INVALID')
        day = date.fromisoformat(item[0]).isoformat()
        if day != item[0] or trade_calendar.previous_trade_date(day) is None or previous is not None and day <= previous:
            raise ValueError('PRICE_DATES_INVALID')
        vals = []
        for value in item[1:6]:
            if value is None or isinstance(value, bool):
                raise ValueError('PRICE_VALUE_INVALID')
            try:
                n = float(value)
            except (TypeError, ValueError):
                raise ValueError('PRICE_VALUE_INVALID') from None
            if not math.isfinite(n):
                raise ValueError('PRICE_VALUE_INVALID')
            vals.append(n)
        op, close, high, low, volume = vals
        if min(op, close, high, low) <= 0 or volume < 0 or not low <= op <= high or not low <= close <= high:
            raise ValueError('PRICE_OHLC_INVALID')
        rows.append({'date': day, 'open': op if volume > 0 else None, 'high': high if volume > 0 else None,
                     'low': low if volume > 0 else None, 'close': close if volume > 0 else None,
                     'paused_or_unknown': volume == 0})
        previous = day
    return {'stock_code': stock_code, 'rows': rows, 'price_unit': 'CNY/share', 'adjustment': 'forward_adjusted',
            'adjustment_basis_id': _hash(raw), 'single_capture': True,
            'adjustment_basis_policy': 'ONE_PROVIDER_RESPONSE_NOT_INDEPENDENTLY_RECONCILED'}


def store_tencent_forward_capture(lake, raw: bytes, *, stock_code: str, trade_date: str, captured_at: str, fixture: bool = False):
    normalized = normalize_tencent_forward_capture(raw, stock_code=stock_code)
    if any(r['date'] > trade_date for r in normalized['rows']):
        raise ValueError('PRICE_WINDOW_END_MISMATCH')
    receipt = _receipt(dataset=PRICE_DATASET, provider='tencent', endpoint=PRICE_ENDPOINT, symbol=stock_code,
                       day=trade_date, captured_at=captured_at, raw=raw, normalizer=PRICE_NORMALIZER,
                       metadata={'schema_version': 'leader-price-capture-v1', 'fixture': fixture,
                                 'source_available_at': None, 'source_finality': 'unknown',
                                 'price_unit': 'CNY/share', 'adjustment': 'forward_adjusted'})
    return lake.store_observation(receipt, raw, content_type='application/json').stored


def verify_capture_receipt(stored, raw: bytes):
    """Replay the versioned receipt identity as well as its original raw bytes."""
    o, meta = stored.observation, stored.observation.payload
    if not isinstance(meta, dict):
        raise ValueError('CAPTURE_MANIFEST_INVALID')
    common = {'schema_version', 'fixture', 'source_available_at', 'source_finality'}
    if o.dataset_id == THEME_DATASET:
        expected = common | {'capture_batch_id', 'page_index', 'page_count', 'page_hashes', 'source_total', 'completeness'}
        if set(meta) != expected or meta['schema_version'] != 'theme-capture-manifest-v1' or meta['completeness'] != 'complete':
            raise ValueError('THEME_MANIFEST_INVALID')
        hashes, count, index = meta['page_hashes'], meta['page_count'], meta['page_index']
        if type(count) is not int or not 1 <= count <= 20 or type(index) is not int or not 0 <= index < count or not isinstance(hashes, list) or len(hashes) != count or any(not isinstance(h, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', h) for h in hashes):
            raise ValueError('THEME_PAGE_IDENTITY_INVALID')
        if hashes[index] != _hash(raw) or meta['capture_batch_id'] != _hash(json.dumps(hashes, separators=(',', ':')).encode()):
            raise ValueError('THEME_BATCH_HASH_INVALID')
        if type(meta['source_total']) is not int or not 1 <= meta['source_total'] <= 10000:
            raise ValueError('THEME_SOURCE_TOTAL_INVALID')
        provider, endpoint, symbol, version = 'ths', THS_ENDPOINT, 'HS,GEM2STAR', THEME_NORMALIZER
    elif o.dataset_id == PRICE_DATASET:
        if set(meta) != common | {'price_unit', 'adjustment'} or meta['schema_version'] != 'leader-price-capture-v1' or meta['price_unit'] != 'CNY/share' or meta['adjustment'] != 'forward_adjusted':
            raise ValueError('PRICE_MANIFEST_INVALID')
        provider, endpoint, symbol, version = 'tencent', PRICE_ENDPOINT, o.provider_symbol, PRICE_NORMALIZER
    else:
        raise ValueError('CAPTURE_DATASET_INVALID')
    if meta['source_available_at'] is not None or meta['source_finality'] != 'unknown':
        raise ValueError('CAPTURE_SOURCE_AUTHORITY_UNSUPPORTED')
    expected = _receipt(dataset=o.dataset_id, provider=provider, endpoint=endpoint, symbol=symbol,
                        day=o.trade_date, captured_at=o.fetched_at, raw=raw, normalizer=version, metadata=meta)
    if o.to_dict() != expected.to_dict():
        raise ValueError('CAPTURE_RECEIPT_IDENTITY_MISMATCH')
