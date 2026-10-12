"""Read-only five-session projection over one unchanged existing FactLake snapshot."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

import trade_calendar
from fact_lake_store import (open_existing_fact_lake_snapshot, FactLakeNotInitializedError,
                             FactLakeSchemaVersionError, FactLakeBusyError)
from short_term_seal_quality_service import validate_trade_date
from short_term_theme_research import THEME_DATASET, THEME_NORMALIZER, normalize_ths_theme_pages, build_theme_research
from short_term_theme_capture import PRICE_DATASET, PRICE_NORMALIZER, THS_ENDPOINT, PRICE_ENDPOINT, _json, normalize_tencent_forward_capture, verify_capture_receipt

SCHEMA_VERSION = 'short-term-theme-research-archive-v1'
_MESSAGES = {
    'ARCHIVE_NOT_CONNECTED': '题材归档未连接；不会自动启动采集或请求供应商。',
    'ARCHIVE_NOT_INITIALIZED': '已有归档尚未初始化；只读查询不会创建它。',
    'ARCHIVE_VERSION_UNSUPPORTED': '归档版本不受支持，未自动迁移。',
    'ARCHIVE_BUSY': '归档正在变化，本次未展示跨版本结果，请稍后重新读取。',
    'ARCHIVE_VALIDATION_FAILED': '归档完整性或日期校验未通过，结果已隐藏。',
    'CALENDAR_WINDOW_UNAVAILABLE': '官方离线交易日历无法确认截至所选日期的完整五个交易日。',
}


def _empty(day, code):
    return {'schema_version': SCHEMA_VERSION, 'trade_date': day, 'status': 'unavailable',
            'reason_codes': [code], 'message': _MESSAGES[code], 'projection': None,
            'archive_only': True, 'ingestion_enabled': False, 'point_in_time_claim': 'NONE'}


def _source(stored):
    o = stored.observation
    return {'observation_id': o.observation_id, 'provider_id': o.provider_id,
            'endpoint': o.provider_endpoint, 'source_trade_date': o.trade_date,
            'captured_at': o.fetched_at, 'raw_payload_hash': o.source_payload_hash,
            'normalizer_version': o.normalizer_version, 'fixture': o.payload.get('fixture'), 'selection_mode': 'CURRENT_STORED_POSTHOC',
            'source_available_at': o.published_at, 'source_finality': o.payload.get('source_finality', 'unknown')}


def _postclose(stored):
    o = stored.observation
    return datetime.fromisoformat(o.fetched_at.replace('Z', '+00:00')) >= datetime.fromisoformat(o.trade_date + 'T15:00:00+08:00')


def _themes(lake, sessions):
    receipts = lake.list_observations(dataset_id=THEME_DATASET, start_trade_date=sessions[0], end_trade_date=sessions[-1], limit=201, max_payload_bytes=128 * 1024 * 1024)
    if len(receipts) == 201:
        raise ValueError('THEME_RECEIPTS_TRUNCATED')
    groups = {}
    for r in receipts:
        o, meta = r.observation, r.observation.payload
        if o.trade_date not in sessions:
            continue
        if o.provider_id != 'ths' or o.provider_endpoint != THS_ENDPOINT or o.normalizer_version != THEME_NORMALIZER or not isinstance(meta, dict) or meta.get('schema_version') != 'theme-capture-manifest-v1':
            raise ValueError('THEME_RECEIPT_CONTRACT_INVALID')
        if not _postclose(r):
            continue
        groups.setdefault(o.trade_date, {}).setdefault((o.fetched_at, meta.get('capture_batch_id')), []).append(r)
    result = {}
    window_bytes = 0
    for day, batches in groups.items():
        newest = max(key[0] for key in batches)
        choices = [rs for key, rs in batches.items() if key[0] == newest]
        if len(choices) != 1:
            raise ValueError('THEME_REVISION_AMBIGUOUS')
        rs = sorted(choices[0], key=lambda r: r.observation.payload['page_index'])
        meta = rs[0].observation.payload
        count, hashes = meta.get('page_count'), meta.get('page_hashes')
        if type(count) is not int or not 1 <= count <= 20 or len(rs) != count or not isinstance(hashes, list) or len(hashes) != count:
            raise ValueError('THEME_BATCH_INCOMPLETE')
        for i, r in enumerate(rs):
            m = r.observation.payload
            if m.get('page_index') != i or m.get('page_count') != count or m.get('page_hashes') != hashes or r.observation.source_payload_hash != hashes[i] or m.get('fixture') != meta.get('fixture'):
                raise ValueError('THEME_BATCH_IDENTITY_INVALID')
        raws = [lake.read_payload(r.observation.observation_id) for r in rs]
        window_bytes += sum(len(raw) for raw in raws)
        if sum(len(raw) for raw in raws) > 32 * 1024 * 1024 or window_bytes > 128 * 1024 * 1024:
            raise ValueError('THEME_BATCH_BYTES_OVERSIZED')
        for receipt, raw in zip(rs, raws):
            verify_capture_receipt(receipt, raw)
        parsed = normalize_ths_theme_pages([_json(raw) for raw in raws], day)
        if any(r.observation.payload['source_total'] != parsed['source_total'] for r in rs):
            raise ValueError('THEME_MANIFEST_TOTAL_MISMATCH')
        parsed['source'] = [_source(r) for r in rs]
        parsed['fixture'] = meta.get('fixture')
        result[day] = parsed
    return result


def _prices(lake, day):
    receipts = lake.list_observations(dataset_id=PRICE_DATASET, start_trade_date=day, end_trade_date=day, limit=1001, max_payload_bytes=64 * 1024 * 1024)
    if len(receipts) == 1001:
        raise ValueError('PRICE_RECEIPTS_TRUNCATED')
    by = {}
    for r in receipts:
        o = r.observation
        if o.provider_id != 'tencent' or o.provider_endpoint != PRICE_ENDPOINT or o.normalizer_version != PRICE_NORMALIZER or o.payload.get('schema_version') != 'leader-price-capture-v1':
            raise ValueError('PRICE_RECEIPT_CONTRACT_INVALID')
        if _postclose(r):
            by.setdefault(o.provider_symbol, []).append(r)
    result = {}
    for code, rs in by.items():
        newest = max(r.observation.fetched_at for r in rs)
        choices = [r for r in rs if r.observation.fetched_at == newest]
        if len(choices) != 1:
            raise ValueError('PRICE_REVISION_AMBIGUOUS')
        r = choices[0]
        raw = lake.read_payload(r.observation.observation_id)
        verify_capture_receipt(r, raw)
        parsed = normalize_tencent_forward_capture(raw, stock_code=code)
        if any(row['date'] > day for row in parsed['rows']):
            raise ValueError('PRICE_WINDOW_END_MISMATCH')
        parsed['source'] = _source(r)
        result[code] = parsed
    return result


def _admitted_pool(value):
    # A preclose survivor set is not a lower bound for the close pool.
    if not value or value.get('post_close_observation') is not True or value.get('status') not in {'normal', 'partial'}:
        return None
    return {**value, 'complete': value.get('complete') is True and value.get('status') == 'normal'}


def query_theme_research(trade_date: str) -> dict:
    day = validate_trade_date(trade_date)
    sessions = [day]
    for _ in range(4):
        previous = trade_calendar.previous_trade_date(sessions[0])
        if previous is None:
            return _empty(day, 'CALENDAR_WINDOW_UNAVAILABLE')
        sessions.insert(0, previous)
    root = os.environ.get('VR_FACT_LAKE_ROOT', '').strip()
    if not root:
        return _empty(day, 'ARCHIVE_NOT_CONNECTED')
    try:
        # P2 owns provider pool normalization/selection. One shared store, no fetch.
        from shortline_research_archive import load_research_days
        lake = open_existing_fact_lake_snapshot(root)
        pools = load_research_days(lake, sessions)
        themes = _themes(lake, sessions)
        evidence = {}
        flags = set()
        for d in sessions:
            kinds = pools.get(d, {})
            pool, broken = _admitted_pool(kinds.get('limit_up')), _admitted_pool(kinds.get('broken'))
            down = _admitted_pool(kinds.get('limit_down'))
            if pool is None:
                continue
            if themes.get(d) and pool.get('fixture') is not themes[d].get('fixture'):
                raise ValueError('MIXED_FIXTURE_AND_REAL_INPUTS')
            flags.update(p['fixture'] for p in (pool, broken, down) if p)
            if themes.get(d):
                flags.add(themes[d]['fixture'])
            p = dict(pool)
            p['broken_complete'] = bool(broken and broken.get('complete'))
            p['broken_count'] = len(broken['rows']) if p['broken_complete'] else None
            p['broken_rows'] = broken['rows'] if broken else []
            p['limit_down_rows'] = down['rows'] if down else []
            p['limit_down_complete'] = bool(down and down.get('complete'))
            p['legal_zero'] = p.get('complete') is True and p.get('source_total') == 0
            evidence[d] = {'trade_date': d, 'pool': p, 'themes': themes.get(d),
                           'source': {'pool': pool.get('evidence'), 'themes': themes.get(d, {}).get('source')}}
        prices = _prices(lake, day)
        flags.update(p['source']['fixture'] for p in prices.values())
        if len(flags) > 1:
            raise ValueError('MIXED_FIXTURE_AND_REAL_INPUTS')
        projection = build_theme_research(sessions, evidence, prices)
        projection['fixture'] = True in flags
        lake.assert_unchanged()
        return {'schema_version': SCHEMA_VERSION, 'trade_date': day, 'status': projection['status'],
                'reason_codes': [] if projection['status'] == 'complete' else ['MISSING_OR_PARTIAL_DATED_EVIDENCE'],
                'message': '当前归档版本的五交易日事后研究；涨停原因是供应商编辑归因，不是公司确认事实。',
                'projection': projection, 'archive_only': True, 'ingestion_enabled': False,
                'calendar_authority': trade_calendar.CALENDAR_AUTHORITY_REF,
                'selection_mode': 'CURRENT_STORED_POSTHOC', 'point_in_time_claim': 'NONE'}
    except FactLakeNotInitializedError:
        return _empty(day, 'ARCHIVE_NOT_INITIALIZED')
    except FactLakeSchemaVersionError:
        return _empty(day, 'ARCHIVE_VERSION_UNSUPPORTED')
    except FactLakeBusyError:
        return _empty(day, 'ARCHIVE_BUSY')
    except Exception:
        return _empty(day, 'ARCHIVE_VALIDATION_FAILED')
