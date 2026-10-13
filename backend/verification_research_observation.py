"""Freeze current research readings with versioned, restorable receipt identity.

No historical PIT inference, no invented committed_at, no historical baseline.
The same bounded receipt and value contract is applied at capture and restore.
"""
import hashlib
import json
import math
import re
from datetime import datetime, timezone
import trade_calendar

VERSION = 'verification-research-observation.v1'
KEYS = ('highest_board', 'promotion_1to2', 'money_effect_median', 'deep_loss_count', 'theme_concentration', 'market_limit_down')
DEFINITIONS = {
    'highest_board': 'provider-declared consecutive board count; descriptive only',
    'promotion_1to2': 'complete previous first-board cohort; source-declared streak + target prices and limits; not FrozenGate',
    'money_effect_median': 'complete previous limit-up cohort target close/pre_close return; percentage points',
    'deep_loss_count': 'complete previous limit-up cohort return <= -5%; inclusive threshold',
    'theme_concentration': 'largest source tag distinct stocks / qualified limit-up pool; tags may overlap',
    'market_limit_down': 'complete source market limit-down pool stock count',
}
SOURCES = {'shortline_research': ('shortline-research.v1', set(KEYS)-{'theme_concentration'}),
           'theme_research': ('short-term-theme-research-archive-v1', {'theme_concentration'})}
PROVIDERS = {'limit_up': 'eastmoney_push2ex:getTopicZTPool', 'broken': 'eastmoney_push2ex:getTopicZBPool',
             'limit_down': 'eastmoney_push2ex:getTopicDTPool', 'daily_prices': 'tushare_pro:daily',
             'daily_limits': 'tushare_pro:stk_limit', 'themes': 'ths:https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool'}


def _instant(value):
    if not isinstance(value, str) or not trade_calendar._UTC_ZERO_OFFSET_RE.fullmatch(value):
        raise ValueError('invalid receipt UTC timestamp')
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _value(key, value):
    if value is None:
        return True
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 2**53-1:
        return False
    if key in ('highest_board', 'deep_loss_count', 'market_limit_down'):
        return type(value) is int and value >= 0
    return -100 <= value <= 10000 if key == 'money_effect_median' else 0 <= value <= 1


def _receipt(kind, day, raw, *, complete, status):
    return {'kind': kind, 'trade_date': day, 'complete': complete, 'status': status, 'observation_id': raw['observation_id'],
            'raw_payload_hash': raw['raw_payload_hash'], 'captured_at': raw['captured_at'],
            'locally_received_at': raw.get('locally_received_at'), 'committed_at': raw.get('committed_at'),
            'provider_published_at': raw.get('provider_published_at', raw.get('source_available_at')),
            'source_ids': raw.get('source_ids') or [f'{raw["provider_id"]}:{raw["endpoint"]}'],
            'normalizer_version': raw['normalizer_version']}


def validate_sources(sources, day, observed):
    """Exact bounded canonical sources. No recursive opaque payload is trusted."""
    try:
        cutoff = _instant(observed)
        if (trade_calendar._parse_strict_date(day) is None or not isinstance(sources, list) or not 1 <= len(sources) <= 2):
            return False
        previous = trade_calendar.previous_trade_date(day)
        seen_sources = set()
        for source in sources:
            if not isinstance(source, dict) or set(source) != {'source', 'schema_version', 'values', 'receipts'}:
                return False
            name = source['source']
            if name not in SOURCES or name in seen_sources:
                return False
            seen_sources.add(name)
            version, metrics = SOURCES[name]
            if source['schema_version'] != version or not isinstance(source['values'], dict) or set(source['values']) != metrics or any(not _value(k, v) for k, v in source['values'].items()):
                return False
            receipts = source['receipts']
            if not isinstance(receipts, list) or not 1 <= len(receipts) <= 1020:
                return False
            seen = set()
            for r in receipts:
                if not isinstance(r, dict) or set(r) != {'kind', 'trade_date', 'complete', 'status', 'observation_id', 'raw_payload_hash', 'captured_at', 'locally_received_at', 'committed_at', 'provider_published_at', 'source_ids', 'normalizer_version'}:
                    return False
                kind, identity = r['kind'], r['observation_id']
                if (kind not in PROVIDERS or (name == 'shortline_research' and kind == 'themes')
                        or not isinstance(identity, str) or not 1 <= len(identity) <= 200 or any(c.isspace() for c in identity) or identity in seen
                        or not isinstance(r['raw_payload_hash'], str) or not re.fullmatch('sha256:[0-9a-f]{64}', r['raw_payload_hash'])
                        or not isinstance(r['trade_date'], str) or trade_calendar._parse_strict_date(r['trade_date']) is None or r['trade_date'] not in {day, previous}
                        or (name == 'theme_research' and (r['trade_date'] != day or kind not in ('limit_up', 'themes')))
                        or type(r['complete']) is not bool or r['status'] not in ('normal', 'partial')
                        or (kind in ('limit_up', 'broken', 'limit_down', 'themes') and (not r['complete'] or r['status'] != 'normal'))
                        or r['committed_at'] is not None or r['source_ids'] != [PROVIDERS[kind]]
                        or r['normalizer_version'] != ('ths-theme-pages-v1' if kind == 'themes' else 'shortline-captured-providers.v1')):
                    return False
                seen.add(identity)
                captured = _instant(r['captured_at'])
                if not datetime.fromisoformat(r['trade_date']+'T15:00:00+08:00') <= captured <= cutoff:
                    return False
                received = r['locally_received_at']
                if kind != 'themes' and received is None:
                    return False
                if received is not None and not captured <= _instant(received) <= cutoff:
                    return False
                if r['provider_published_at'] is not None and _instant(r['provider_published_at']) > cutoff:
                    return False
            present = {(r['trade_date'], r['kind']) for r in receipts}
            dependencies = {
                'highest_board': {(day, 'limit_up')}, 'market_limit_down': {(day, 'limit_down')},
                'money_effect_median': {(previous, 'limit_up'), (previous, 'broken'), (day, 'daily_prices')},
                'deep_loss_count': {(previous, 'limit_up'), (previous, 'broken'), (day, 'daily_prices')},
                'promotion_1to2': {(previous, 'limit_up'), (previous, 'broken'), (day, 'daily_prices'), (day, 'daily_limits'), (day, 'limit_up')},
                'theme_concentration': {(day, 'limit_up'), (day, 'themes')},
            }
            if any(value is not None and not dependencies[key] <= present for key, value in source['values'].items()):
                return False
        return True
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def read_current(day, observe):
    sources = []
    try:
        from shortline_research_service import query_shortline_research
        result = query_shortline_research(day)
        if (result.get('trade_date') == day and result.get('fixture') is False
                and result.get('selection_mode') == 'CURRENT_STORED_POSTHOC' and result.get('point_in_time_claim') == 'NONE'
                and result.get('status') in ('normal', 'partial') and isinstance(result.get('projection'), dict)):
            p = result['projection']; daily, cohort = p.get('daily', {}), p.get('cohort', {})
            group = cohort.get('groups', {}).get('yesterday_limit_up', {})
            promotion = next((r for r in cohort.get('promotion', []) if r.get('previous_boards') == 1), {})
            values = {'highest_board': daily.get('highest_board'), 'market_limit_down': daily.get('limit_down_count'),
                      'promotion_1to2': promotion.get('rate'), 'money_effect_median': group.get('median_pct'), 'deep_loss_count': group.get('loss_ge_5_count')}
            receipts = [_receipt(row['kind'], row['trade_date'], raw, complete=row['complete'], status=row['status']) for row in result['evidence']
                        if row.get('trade_date') in (day, result.get('previous_trade_date')) for raw in row['receipts']]
            sources.append({'source': 'shortline_research', 'schema_version': result['schema_version'], 'values': values, 'receipts': receipts})
    except (ImportError, KeyError, TypeError, ValueError):
        pass
    try:
        from short_term_theme_research_service import query_theme_research
        result = query_theme_research(day)
        if (result.get('trade_date') == day and (result.get('projection') or {}).get('fixture') is False
                and result.get('selection_mode') == 'CURRENT_STORED_POSTHOC' and result.get('point_in_time_claim') == 'NONE'):
            row = next((r for r in result['projection'].get('days', []) if r.get('date') == day), None)
            if row and row.get('concentration') is not None:
                receipts = [_receipt('limit_up', day, raw, complete=row['complete'], status='normal' if row['complete'] else 'partial') for raw in row['source']['pool']]
                receipts += [_receipt('themes', day, raw, complete=row['complete'], status='normal' if row['complete'] else 'partial') for raw in row['source']['themes']]
                sources.append({'source': 'theme_research', 'schema_version': result['schema_version'],
                                'values': {'theme_concentration': row['concentration']}, 'receipts': receipts})
    except (ImportError, KeyError, TypeError, ValueError):
        pass
    observed_at = observe()
    # Invalid one-source evidence cannot be attached to a valid other reading.
    admitted = []
    for source in sources:
        # Validate each receipt with null readings first. An unrelated stale or
        # failed source does not erase another metric's complete dependencies.
        empty = dict.fromkeys(source['values'])
        receipts = [r for r in source['receipts'] if validate_sources([{**source, 'values': empty, 'receipts': [r]}], day, observed_at)]
        if not receipts:
            continue
        values = dict(empty)
        for key, value in source['values'].items():
            trial = {**empty, key: value}
            if validate_sources([{**source, 'values': trial, 'receipts': receipts}], day, observed_at):
                values[key] = value
        admitted.append({**source, 'values': values, 'receipts': receipts})
    sources = admitted
    if not sources:
        return None
    values = dict.fromkeys(KEYS)
    for source in sources:
        values.update(source['values'])
    raw = json.dumps(sources, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    return {'schema_version': VERSION, 'trade_date': day, 'basis': 'CURRENT_STORED_POSTHOC',
            'point_in_time_claim': 'SERVER_READ_OBSERVATION_ONLY', 'snapshot_observed_at': observed_at,
            'values': values, 'source_receipts': sources, 'source_receipts_sha256': hashlib.sha256(raw.encode()).hexdigest(), 'definitions': DEFINITIONS}


def validate(evidence, day, written, value_validator):
    if not isinstance(evidence, dict) or set(evidence) != {'schema_version', 'trade_date', 'basis', 'point_in_time_claim', 'snapshot_observed_at', 'values', 'source_receipts', 'source_receipts_sha256', 'definitions'}:
        return False
    if (evidence['schema_version'] != VERSION or evidence['trade_date'] != day or evidence['basis'] != 'CURRENT_STORED_POSTHOC'
            or evidence['point_in_time_claim'] != 'SERVER_READ_OBSERVATION_ONLY' or evidence['snapshot_observed_at'] != written
            or evidence['definitions'] != DEFINITIONS or not isinstance(evidence['values'], dict) or set(evidence['values']) != set(KEYS)
            or not validate_sources(evidence['source_receipts'], day, written)):
        return False
    values = dict.fromkeys(KEYS)
    for source in evidence['source_receipts']:
        values.update(source['values'])
    if values != evidence['values'] or any(v is not None and value_validator({'values': values}, k) is None for k, v in values.items()):
        return False
    raw = json.dumps(evidence['source_receipts'], sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest() == evidence['source_receipts_sha256']
