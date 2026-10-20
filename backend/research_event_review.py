"""Explicit event review workflow in the existing evidence/thesis ledger.

Provider observations are immutable snapshots, not a second event authority.
No formal thesis, evidence link, decision or trade is mutated by this workflow.
"""
from __future__ import annotations

import hashlib
import json
import base64
import hmac
import secrets
import time

import campaign_service
import evidence_thesis_service as thesis_service
import evidence_thesis_store as store
import research_event_calendar as calendar


class ReviewConflict(ValueError):
    pass


def observation(event):
    return {key: event.get(key) for key in (
        'event_id', 'security_code', 'event_type', 'event_date', 'state',
        'title', 'details', 'source', 'source_record_identity', 'date_semantics',
    )}


def fingerprint(event):
    return hashlib.sha256(json.dumps(observation(event), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# Process-local receipt key: a restart invalidates outstanding receipts safely.
# No credentials, provider requests, file writes or event authority on GET.
_RECEIPT_KEY = secrets.token_bytes(32)
_RECEIPT_TTL = 3600


def issue_receipt(event):
    payload = json.dumps({'event': observation(event), 'expires': int(time.time()) + _RECEIPT_TTL},
                         sort_keys=True, ensure_ascii=False).encode()
    encoded = base64.urlsafe_b64encode(payload).decode()
    return encoded + '.' + hmac.new(_RECEIPT_KEY, encoded.encode(), hashlib.sha256).hexdigest()


def verify_receipt(receipt):
    try:
        if not isinstance(receipt, str) or len(receipt) > 100000:
            raise ValueError()
        encoded, signature = receipt.rsplit('.', 1)
        expected = hmac.new(_RECEIPT_KEY, encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        payload = json.loads(base64.urlsafe_b64decode(encoded))
        if payload['expires'] < time.time():
            raise ValueError()
        return payload['event']
    except (ValueError, KeyError, TypeError):
        raise ReviewConflict('事件观察凭据失效或被修改，请刷新日历') from None


def _rows(conn, campaign_id):
    if not store._table_exists(conn, 'event_research_reviews'):
        return []
    return [_with_judgment(conn, json.loads(row['payload'])) for row in conn.execute(
        'SELECT payload FROM event_research_reviews WHERE campaign_id=? ORDER BY rowid DESC', (campaign_id,))]


def _with_judgment(conn, result):
    row = conn.execute('SELECT payload FROM event_research_judgments WHERE review_id=?', (result['id'],)).fetchone()
    if row:
        judgment = json.loads(row['payload'])
        result.update(judgment=judgment, status=judgment['outcome'], version=2)
    return result


def list_reviews(campaign_id, db_path=None):
    campaign_service.get_campaign(campaign_id)
    try:
        return store.read_transaction(thesis_service.resolve_db_path(db_path), lambda conn: _rows(conn, campaign_id))
    except FileNotFoundError:
        return []


def context(campaign_id, db_path=None):
    campaign = campaign_service.get_campaign(campaign_id)
    binding = campaign_service.get_campaign_thesis_binding(campaign_id)
    path = thesis_service.resolve_db_path(db_path)
    thesis = thesis_service.get_thesis(path, binding['thesis_id'])
    if not thesis:
        raise ReviewConflict('研究逻辑不存在')
    evidence = thesis_service.list_evidence(path, 'stock', campaign['security_code'], limit=100)
    return {'thesis': thesis['thesis'], 'evidence': evidence['items'], 'reviews': list_reviews(campaign_id, path)}


def _subject(thesis, code):
    _, normalized, _ = thesis_service.normalize_subject('stock', code)
    if thesis['subject_type'] != 'stock' or thesis['subject_id'] != normalized:
        raise ReviewConflict('研究对象不一致')


def bind(payload, db_path=None):
    thesis_service._validate_expected_revision(payload['expected_thesis_revision'])
    campaign = campaign_service.get_campaign(payload['campaign_id'])
    binding = campaign_service.get_campaign_thesis_binding(payload['campaign_id'])
    if binding['thesis_id'] != payload['thesis_id']:
        raise ReviewConflict('Campaign 正式绑定已变化，请重新读取')
    expectation = payload['expectation'].strip()
    if not expectation or len(expectation) > 2000:
        raise ValueError('请填写 1–2000 字的待验证预期')
    event = verify_receipt(payload['observation_receipt'])
    if (event['security_code'] != campaign['security_code']
            or event['event_id'] != payload['event_id']
            or event['event_type'] != payload['event_type']
            or fingerprint(event) != payload['expected_observation_hash']):
        raise ReviewConflict('事件与研究对象或所选版本不一致，请刷新后重新确认')
    path = thesis_service.resolve_db_path(db_path)
    def write(conn):
        thesis = thesis_service._get_thesis_aggregate(conn, payload['thesis_id'])['thesis']
        _subject(thesis, campaign['security_code'])
        if thesis['current_revision'] != payload['expected_thesis_revision']:
            raise ReviewConflict('研究逻辑版本已变化')
        store.ensure_event_review_tables(conn)
        existing = conn.execute('SELECT payload FROM event_research_reviews WHERE campaign_id=? AND thesis_id=? AND event_id=? AND observation_hash=?',
            (payload['campaign_id'], payload['thesis_id'], event['event_id'], fingerprint(event))).fetchone()
        if existing:
            result = json.loads(existing['payload'])
            if result['expectation'] != expectation:
                raise ReviewConflict('该事件版本已有预期，不能覆盖历史记录')
            return _with_judgment(conn, result)
        result = dict(id=store.new_id(), campaign_id=payload['campaign_id'], thesis_id=payload['thesis_id'],
            thesis_revision=thesis['current_revision'], expectation=expectation,
            observation=observation(event), observation_hash=fingerprint(event),
            status='review_required', version=1, created_at=store._utc_now_iso(), judgment=None)
        conn.execute('INSERT INTO event_research_reviews VALUES (?,?,?,?,?,?,?)',
            (result['id'], result['campaign_id'], result['thesis_id'], event['event_id'], result['observation_hash'], json.dumps(result, ensure_ascii=False), 1))
        return result
    return store.write_transaction(path, write)


def judge(review_id, payload, db_path=None):
    thesis_service._validate_expected_revision(payload['expected_version'])
    if payload['outcome'] not in ('support', 'refute', 'insufficient'):
        raise ValueError('复核结论无效')
    reason = payload['reason'].strip()
    if not reason or len(reason) > 2000 or not payload['evidence']:
        raise ValueError('请提供复核说明和至少一条证据；证据不足也需记录所审阅材料')
    if len(payload['evidence']) > 20 or len({item['id'] for item in payload['evidence']}) != len(payload['evidence']):
        raise ValueError('证据重复或超过 20 条')
    def write(conn):
        if not store._table_exists(conn, 'event_research_reviews'):
            raise ReviewConflict('复核记录不存在')
        row = conn.execute('SELECT payload,version FROM event_research_reviews WHERE id=?', (review_id,)).fetchone()
        if not row:
            raise ReviewConflict('复核记录不存在')
        result = _with_judgment(conn, json.loads(row['payload']))
        if result['version'] != payload['expected_version'] or result['status'] != 'review_required':
            raise ReviewConflict('复核已完成或版本已变化；已确认判断不可改写')
        evidence = []
        for item in payload['evidence']:
            record = store._get_evidence_row(conn, item['id'])
            if record is None or record['deleted']:
                raise ReviewConflict('证据不存在或已删除')
            snapshot = store._evidence_row_to_dict(record)
            _subject(snapshot, result['observation']['security_code'])
            if store.evidence_edit_token(record) != item['edit_token']:
                raise ReviewConflict('证据已更新，请重新审阅')
            evidence.append(snapshot)
        result.update(status=payload['outcome'], version=2,
            judgment=dict(outcome=payload['outcome'], reason=reason, evidence=evidence, reviewed_at=store._utc_now_iso()))
        conn.execute('INSERT INTO event_research_judgments (review_id,payload) VALUES (?,?)',
            (review_id, json.dumps(result['judgment'], ensure_ascii=False)))
        return result
    return store.write_transaction(thesis_service.resolve_db_path(db_path), write)
