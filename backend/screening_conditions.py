"""Named, immutable research screens over RDP's existing computed cross-section.

No expression language, providers, watchlist writes or formal authority writes.
Records live in the existing observation materialization database.
"""
import hashlib
import json
import math
import operator
import re
import uuid
from datetime import datetime, timezone

import observation_workflow_store as store
import research_data_plane as rdp

VERSION = 'screening-conditions.v1'
MAX_UNIVERSE = 10000
OPS = dict(gt=operator.gt, gte=operator.ge, lt=operator.lt, lte=operator.le, eq=operator.eq, neq=operator.ne)


def digest(value):
    return hashlib.sha256(store.encode(value).encode()).hexdigest()


def unit(metric):
    if metric.startswith('return_') or metric.startswith('close_vs_'): return 'fraction'
    if metric in ('latest_close', 'ma20', 'ma60'): return 'source price unit (undeclared by RDP)'
    if metric == 'volume_ratio_20d': return 'ratio'
    return 'source volume unit (undeclared by RDP)'


def strict_json(payload):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out: raise ValueError('Duplicate JSON key')
            out[key] = value
        return out
    return json.loads(payload, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def validate_card(card):
    if (not isinstance(card, dict) or not re.fullmatch(r'[a-f0-9]{32}', card.get('id', ''))
        or not isinstance(card.get('name'), str) or not 1 <= len(card['name'].strip()) <= 80
        or type(card.get('version')) is not int or card['version'] < 1): raise ValueError('Invalid saved card')
    if card.get('schema_version') != VERSION or card.get('integrity') != digest({k:v for k,v in card.items() if k != 'integrity'}): raise ValueError('Invalid card integrity')
    normalized = rdp._validate_full_market_query(as_of=None, latest=True, filter_metric=None, filter_operator=None,
        filter_value=None, filters=card.get('filters'), sort_by='code', sort_order='asc', limit=1000, offset=0)
    if not normalized: raise ValueError('Empty saved card')


def _read(table):
    if table not in ('screening_cards', 'screening_runs'): raise ValueError('Invalid archive table')
    with store.read() as conn:
        kind = conn.execute('SELECT type FROM sqlite_schema WHERE name=?', (table,)).fetchone()
        if kind is None: return []
        if kind != ('table',): raise ValueError('Invalid screening archive object')
        count, size = conn.execute(f'SELECT COUNT(*),COALESCE(SUM(LENGTH(payload)),0) FROM {table}').fetchone()
        if count > 1000 or size > 64_000_000: raise ValueError('Screen archive exceeds read budget')
        columns = 'id,payload,name,version' if table == 'screening_cards' else 'id,payload'
        rows = conn.execute(f'SELECT {columns} FROM {table} LIMIT 1001').fetchall()
        if len(rows) > 1000: raise ValueError('Screen archive exceeds read budget')
        result = []; total_bytes = 0
        for record in rows:
            identity, payload = record[:2]
            total_bytes += len(payload)
            if len(payload) > 32_000_000 or total_bytes > 64_000_000: raise ValueError('Screen archive exceeds byte budget')
            value = strict_json(payload)
            if value.get('id') != identity or value.get('schema_version') != VERSION or value.get('integrity') != digest({k:v for k,v in value.items() if k != 'integrity'}):
                raise ValueError('Screen archive integrity mismatch')
            validate_card(value if table == 'screening_cards' else value['card'])
            if table == 'screening_cards' and tuple(record[2:]) != (value['name'], value['version']): raise ValueError('Card index mismatch')
            if table == 'screening_runs':
                if value.get('subject') != 'RDP full-market cross-section' or not isinstance(value.get('rows'), list) or not isinstance(value.get('snapshot_id'), str) or not value.get('receipts'): raise ValueError('Invalid run structure')
                from datetime import date
                date.fromisoformat(value['cutoff']); date.fromisoformat(value['as_of'])
                for receipt in value['receipts']:
                    if receipt['snapshot_id'] != value['snapshot_id'] or receipt['query'] != 'query_full_market' or receipt['parameters']['as_of'] != value['cutoff']: raise ValueError('Saved receipt mismatch')
                if any(not re.fullmatch(r'[a-f0-9]{64}', receipt.get('artifact_sha256', '')) or not re.fullmatch(r'[a-f0-9]{64}', receipt.get('result_sha256', '')) for receipt in value['receipts']): raise ValueError('Invalid replay digest')
                codes = [r['code'] for r in value['rows']]
                if len(codes) > MAX_UNIVERSE or len(set(codes)) != len(codes) or any(not re.fullmatch(r'[0-9]{6}', c) for c in codes): raise ValueError('Invalid saved universe')
                for row in value['rows']:
                    if row['status'] not in ('PASS', 'FAIL', 'UNKNOWN') or len(row['conditions']) != len(value['card']['filters']): raise ValueError('Invalid saved evidence')
                    for condition, rule in zip(row['conditions'], value['card']['filters']):
                        if any(condition[k] != rule[k] for k in rule) or condition['status'] not in ('PASS','FAIL','UNKNOWN'): raise ValueError('Invalid condition evidence')
                        observed = condition['observed']
                        if observed is not None and (type(observed) not in (int, float) or not math.isfinite(observed)): raise ValueError('Invalid saved metric')
                        expected = 'UNKNOWN' if condition['missingness'] or observed is None else 'PASS' if OPS[rule['operator']](observed, rule['value']) else 'FAIL'
                        if condition['status'] != expected or condition['unit'] != unit(rule['metric']): raise ValueError('Saved condition result mismatch')
                    statuses = [c['status'] for c in row['conditions']]
                    expected = 'UNKNOWN' if 'UNKNOWN' in statuses else 'FAIL' if 'FAIL' in statuses else 'PASS'
                    if row['status'] != expected: raise ValueError('Saved eligibility mismatch')
                if value['counts'] != {status: sum(r['status'] == status for r in value['rows']) for status in ('PASS','FAIL','UNKNOWN')}: raise ValueError('Saved counts mismatch')
            result.append(value)
        return result


def get(table, identity):
    for record in _read(table):
        if record['id'] == identity: return record
    raise LookupError('Saved screen not found')


def catalog():
    return {'cards': _read('screening_cards'), 'runs': [{k:v for k,v in r.items() if k != 'rows'} for r in _read('screening_runs')]}


def save_card(name, filters):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80: raise ValueError('Card name must contain 1–80 characters')
    normalized = rdp._validate_full_market_query(as_of=None, latest=True, filter_metric=None, filter_operator=None,
        filter_value=None, filters=filters, sort_by='code', sort_order='asc', limit=1000, offset=0)
    if not normalized: raise ValueError('A card needs at least one condition')
    with store.write() as conn:
        if conn.execute('SELECT COUNT(*) FROM screening_cards').fetchone()[0] >= 1000: raise ValueError('Card archive is full')
        version = conn.execute('SELECT COALESCE(MAX(version),0)+1 FROM screening_cards WHERE name=?', (name.strip(),)).fetchone()[0]
        card = {'schema_version': VERSION, 'id': uuid.uuid4().hex, 'name': name.strip(), 'version': version,
                'filters': [dict(metric=m, operator=o, value=v) for m,o,v in normalized]}
        card['integrity'] = digest(card)
        conn.execute('INSERT INTO screening_cards VALUES (?,?,?,?)', (card['id'], card['name'], version, store.encode(card)))
    return card


def explain(row, filters):
    conditions = []
    for rule in filters:
        metric = rule['metric']; value = row.get(metric)
        status = row.get('metric_status', {}).get(metric, 'normal')
        missing = 'STALE' if row.get('status') == 'stale' else status if status != 'normal' else 'MISSING_VALUE' if value is None else None
        if value is not None and (not isinstance(value, (int,float)) or not math.isfinite(value)): missing = 'INVALID_VALUE'
        passed = None if missing else OPS[rule['operator']](value, rule['value'])
        conditions.append({**rule, 'observed': value, 'unit': unit(metric), 'status': 'UNKNOWN' if passed is None else 'PASS' if passed else 'FAIL', 'missingness': missing})
    statuses = [c['status'] for c in conditions]
    return {'code': row['code'], 'latest_date': row.get('latest_date'), 'status': 'UNKNOWN' if 'UNKNOWN' in statuses else 'FAIL' if 'FAIL' in statuses else 'PASS', 'conditions': conditions}


def execute(card_id, as_of=None, *, root=None):
    card = get('screening_cards', card_id)
    manifest = rdp.read_manifest(root)
    cutoff = as_of or manifest['coverage_end']
    rows = []; receipts = []; offset = 0; first = None
    while True:
        page = rdp.query_full_market(root=root, snapshot_id=manifest['snapshot_id'], as_of=cutoff, latest=True,
                                     filters=[], sort_by='code', limit=1000, offset=offset)
        if page['status'] == 'unavailable': raise ValueError('RDP snapshot is unavailable at this cutoff')
        if page['total_rows'] > MAX_UNIVERSE: raise ValueError('Screen universe exceeds the 10000-row budget; no partial run saved')
        if (page.get('snapshot_id') != manifest['snapshot_id'] or page['replay_receipt'].get('snapshot_id') != manifest['snapshot_id']
            or page['replay_receipt'].get('artifact_sha256') != manifest['artifact_sha256']
            or page['returned_rows'] != len(page['rows']) or (first and page['total_rows'] != first['total_rows'])):
            raise ValueError('RDP snapshot or page mismatch')
        first = first or page
        rows.extend(explain(row, card['filters']) for row in page['rows'])
        receipts.append(page['replay_receipt'])
        if page['next_offset'] is None: break
        if page['next_offset'] <= offset: raise ValueError('RDP pagination did not advance')
        offset = page['next_offset']
    if len(rows) != first['total_rows'] or len({r['code'] for r in rows}) != len(rows): raise ValueError('RDP universe incomplete')
    run = {'schema_version': VERSION, 'id': uuid.uuid4().hex, 'card': card,
        'subject': 'RDP full-market cross-section', 'snapshot_id': manifest['snapshot_id'], 'cutoff': cutoff,
        'as_of': first['as_of'], 'provider_id': first['provider_id'], 'adjustment': first['adjustment'],
        'coverage': first['coverage'], 'receipts': receipts, 'rows': rows,
        'saved_at': datetime.now(timezone.utc).isoformat(),
        'counts': {status: sum(r['status'] == status for r in rows) for status in ('PASS','FAIL','UNKNOWN')},
        'limitations': ['Research only; no automatic watchlist or trade action', 'UNKNOWN means missing/stale coverage, never fundamental deterioration', 'Latest available observations at or before cutoff; not historical publication-vintage proof', 'Eligibility excludes stale/unknown metrics; legacy Full Market can retain stale numeric matches']}
    run['integrity'] = digest(run)
    encoded = store.encode(run)
    if len(encoded) > 32_000_000: raise ValueError('Screen run exceeds byte budget; no partial run saved')
    with store.write() as conn:
        count, size = conn.execute('SELECT COUNT(*),COALESCE(SUM(LENGTH(payload)),0) FROM screening_runs').fetchone()
        if count >= 1000 or size + len(encoded) > 64_000_000: raise ValueError('Run archive is full')
        conn.execute('INSERT INTO screening_runs VALUES (?,?)', (run['id'], encoded))
    return run


def compare(before_id, after_id):
    before, after = get('screening_runs', before_id), get('screening_runs', after_id)
    rule_changed = before['card']['filters'] != after['card']['filters']
    data_changed = (before['snapshot_id'], before['cutoff']) != (after['snapshot_id'], after['cutoff'])
    left = {r['code']:r for r in before['rows']}; right = {r['code']:r for r in after['rows']}
    changes = []
    for code in sorted(left.keys() | right.keys()):
        a, b = left.get(code), right.get(code)
        x, y = a['status'] if a else 'UNKNOWN', b['status'] if b else 'UNKNOWN'
        if a == b: continue
        reasons = []
        if rule_changed: reasons.append('RULE_CHANGED')
        if data_changed: reasons.append('DATA_CHANGED')
        if a is None or b is None or 'UNKNOWN' in (x,y): reasons.append('COVERAGE_MISSING_OR_STALE')
        changes.append({'code': code, 'before': a, 'after': b, 'transition': 'ENTERED' if y == 'PASS' and x != 'PASS' else 'EXITED' if x == 'PASS' and y != 'PASS' else 'CHANGED', 'reasons': reasons})
    return {'before_id': before_id, 'after_id': after_id, 'rule_changed': rule_changed, 'data_changed': data_changed,
        'changes': changes, 'limitations': ['Changes identify differing inputs, not causal attribution. Missing coverage does not imply fundamental decline.']}
