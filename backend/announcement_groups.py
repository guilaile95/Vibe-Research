"""Explicit, local announcement-centered evidence relationships; never inferred deduplication.

No provider currently supplies a verified original-document key. Each relationship,
period and original/commentary label is a USER_DECLARED_UNVERIFIED assertion.
Evidence records and observations are never modified by this module.
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
import evidence_thesis_service as svc
import evidence_thesis_store as store

TABLE = 'research_announcement_group_revisions'
ROLES = {'original', 'commentary', 'unknown', 'correction', 'amendment'}
OWNERSHIP_STATUS = {
    'status': 'NOT_IMPLEMENTED_PREREQUISITE_MISSING',
    'blocker': 'No verified SEC 13D/13G/Form 4 or equivalent structured ownership filing adapter, accession identity, amendment lineage, issuer/owner identity, or transaction semantics is available. User-supplied text is not a verified ownership source.',
}


class Conflict(ValueError):
    pass


def _record(conn, evidence_id):
    row = store._get_evidence_row(conn, evidence_id)
    if not row or row['deleted']:
        raise ValueError('证据不存在或已删除')
    result = store._evidence_row_to_dict(row)
    if result['subject_type'] != 'stock':
        raise ValueError('仅支持同一个股的证据')
    return result


def _history(conn):
    if not store._table_exists(conn, TABLE):
        return []
    return [json.loads(r[0]) for r in conn.execute(f'SELECT payload FROM {TABLE} ORDER BY rowid')]


def _latest(history):
    return {r['group_id']: r for r in history}


def context(evidence_id, db_path=None):
    def read(conn):
        record = _record(conn, evidence_id)
        history = _history(conn)
        groups = [r for r in _latest(history).values() if any(m['evidence_id'] == evidence_id for m in r['members'])]
        rows = conn.execute("SELECT * FROM evidence_records WHERE subject_type='stock' AND subject_id=? AND deleted=0 ORDER BY created_at DESC, id LIMIT 201", (record['subject_id'],)).fetchall()
        ids = {r['group_id'] for r in groups}
        return {'groups': groups, 'history': [r for r in history if r['group_id'] in ids],
                'candidates': [store._evidence_row_to_dict(r) for r in rows[:200]], 'has_more': len(rows) > 200,
                'relationship_basis': 'USER_DECLARED_UNVERIFIED', 'automatic_grouping': 'UNAVAILABLE_NO_VERIFIED_DOCUMENT_ID',
                'ownership_change': OWNERSHIP_STATUS}
    return store.read_transaction(svc.resolve_db_path(db_path), read)


def save(payload, db_path=None):
    """Append-only revisions, CAS and same-request idempotency in one write lock."""
    anchor_id = payload['anchor_id']
    period = payload['period'].strip()
    request_id = payload['request_id'].strip()
    members = payload['members']
    if not period or len(period) > 100 or not request_id or len(request_id) > 100:
        raise ValueError('须明确填写报告期/事件范围及请求标识')
    if not 2 <= len(members) <= 50:
        raise ValueError('每组须包含 2–50 条不同证据')
    ids = [m['evidence_id'] for m in members]
    if len(set(ids)) != len(ids) or anchor_id not in ids:
        raise ValueError('成员不可重复且须包含公告中心证据')
    for member in members:
        if member['role'] not in ROLES:
            raise ValueError('不支持的关系类型')
        target = member.get('relates_to')
        if member['role'] in ('correction', 'amendment'):
            if target not in ids or target == member['evidence_id']:
                raise ValueError('更正/修订须明确关联组内另一条原证据')
        elif target:
            raise ValueError('只有更正/修订可填写关联原证据')
    # Reject cycles instead of manufacturing a revision ordering.
    links = {m['evidence_id']: m.get('relates_to') for m in members}
    for start in ids:
        seen, node = set(), start
        while node:
            if node in seen:
                raise ValueError('更正/修订关系不可形成循环')
            seen.add(node)
            node = links.get(node)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    def write(conn):
        history = _history(conn)
        for old in history:
            if old['request_id'] == request_id:
                if old['request_digest'] != digest:
                    raise Conflict('请求标识已被用于不同内容')
                return old
        current = _latest(history)
        group_id = payload.get('group_id') or 'announcement-group:' + request_id
        previous = current.get(group_id)
        if payload.get('group_id') and not previous:
            raise Conflict('分组不存在，请刷新')
        if payload['expected_revision'] != (previous['revision'] if previous else 0):
            raise Conflict('分组已变化，请刷新后重新确认')
        anchor = _record(conn, anchor_id)
        if anchor['evidence_type'] not in ('announcement', 'financial_filing'):
            raise ValueError('中心证据须为公告或财报；该类型仍是用户声明')
        if previous and (previous['anchor_id'] != anchor_id or previous['period'] != period or previous['subject_id'] != anchor['subject_id']):
            raise Conflict('不可改变分组的主体、中心或报告期；请另建分组')
        snapshots = []
        for member in members:
            record = _record(conn, member['evidence_id'])
            if record['subject_id'] != anchor['subject_id']:
                raise Conflict('不同主体不可分为同组')
            if member['expected_edit_token'] != record['edit_token']:
                raise Conflict('证据已变化，请刷新后重新确认')
            for other in current.values():
                if other['group_id'] != group_id and any(m['evidence_id'] == record['id'] for m in other['members']):
                    raise Conflict('证据已属于其他分组，不自动合并重叠组')
            snapshots.append({'evidence_id': record['id'], 'role': member['role'], 'relates_to': member.get('relates_to'),
                              'relationship_basis': 'USER_DECLARED_UNVERIFIED', 'source_kind': record['evidence_type'],
                              'evidence_snapshot': record})
        if previous:
            new = {m['evidence_id']: m for m in snapshots}
            for old in previous['members']:
                if old['evidence_id'] not in new or any(new[old['evidence_id']][k] != old[k] for k in ('role', 'relates_to')):
                    raise Conflict('已有成员及关系须保留；修订请新增关联证据')
        value = {'group_id': group_id, 'anchor_id': anchor_id, 'subject_id': anchor['subject_id'], 'period': period,
                 'revision': (previous['revision'] if previous else 0) + 1, 'members': snapshots,
                 'relationship_basis': 'USER_DECLARED_UNVERIFIED', 'strict_asof_eligible': False,
                 'created_at': datetime.now(timezone.utc).isoformat(), 'request_id': request_id, 'request_digest': digest}
        conn.execute(f'CREATE TABLE IF NOT EXISTS {TABLE} (group_id TEXT NOT NULL, revision INTEGER NOT NULL, request_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, PRIMARY KEY(group_id, revision))')
        conn.execute(f'INSERT INTO {TABLE} VALUES (?,?,?,?)', (group_id, value['revision'], request_id, json.dumps(value, ensure_ascii=False)))
        return value
    return store.write_transaction(svc.resolve_db_path(db_path), write)
