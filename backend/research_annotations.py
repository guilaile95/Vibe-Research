"""Append-only manual chart notes. No thesis, evidence, or trading authority writes."""
from datetime import date, datetime, timezone, timedelta
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
from uuid import uuid4, UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
import observation_workflow_store as store

LIMIT = 1000
_SECRET = secrets.token_bytes(32)  # Process-local receipts expire on restart; reload chart.


def _digest(value):
    return hashlib.sha256(store.encode(value).encode()).hexdigest()


def _signature(value):
    return hmac.new(_SECRET, store.encode(value).encode(), hashlib.sha256).hexdigest()


def _number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('invalid number')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('invalid number')
    return result


def snapshot_context(code, bars):
    """Only called with daily bars returned by the existing server source; no I/O."""
    if not re.fullmatch(r'[0-9]{6}', code):
        return None
    points = {}
    for bar in bars:
        try:
            day = str(bar.get('date', bar.get('datetime', ''))).strip()[:10]
            if date.fromisoformat(day).isoformat() != day:
                continue
            o, h, l, c = [_number(bar.get(k)) for k in ('open', 'high', 'low', 'close')]
            if min(o, h, l, c) <= 0 or not l <= min(o, c) <= max(o, c) <= h:
                continue
            volume = bar.get('volume')
            v = _number(volume) if isinstance(volume, (int, float)) and not isinstance(volume, bool) else -1
            point = [day, *[format(n, '.17g') for n in (o, h, l, c)], format(v, '.17g') if v >= 0 else None]
            if day in points and points[day] != point:
                return None  # Ambiguous source day: never attest an arbitrary duplicate.
            points.setdefault(day, point)
        except (ValueError, TypeError, OverflowError):
            continue
    kept = [points[k] for k in sorted(points)[-60:]]
    if not kept:
        return None
    body = {'code': code, 'bar_period': 'day', 'points': kept}
    body['snapshot_id'] = _digest(body)
    body['expires_at'] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec='seconds')
    return {**body, 'token': _signature(body)}


class AnnotationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    context: dict
    date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    text: str = Field(min_length=1, max_length=2000)
    price: float | None = Field(default=None, allow_inf_nan=False)
    link_kind: str | None = Field(default=None, pattern='^(evidence|thesis)$')
    link_id: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator('text')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('blank note')
        return value.strip()


def verify_context(context):
    if not isinstance(context, dict) or set(context) != {'code', 'bar_period', 'points', 'snapshot_id', 'token', 'expires_at'}:
        raise ValueError('invalid context')
    if len(store.encode(context)) > 24000:
        raise ValueError('oversized context')
    body = {k: v for k, v in context.items() if k != 'token'}
    if not isinstance(context['token'], str) or not hmac.compare_digest(context['token'], _signature(body)):
        raise ValueError('expired or changed context')
    if datetime.fromisoformat(context['expires_at']) <= datetime.now(timezone.utc):
        raise ValueError('expired context')
    return context


def _rows(conn):
    kind = conn.execute("SELECT type FROM sqlite_master WHERE name='research_annotations'").fetchone()
    if kind is None:
        return []
    if kind != ('table',):
        raise store.StoreError('研究标注归档结构无效')
    try:
        info = conn.execute('PRAGMA table_info(research_annotations)').fetchall()
        if {row[1] for row in info} != {'id', 'payload'} or [r[1] for r in info if r[5]] != ['id']:
            raise ValueError('schema')
        rows = conn.execute('SELECT id,payload FROM research_annotations ORDER BY rowid DESC LIMIT 1001').fetchall()
        if len(rows) > LIMIT:
            raise ValueError('limit')
        result = []
        for identity, payload in rows:
            if not isinstance(payload, str) or len(payload) > 16000:
                raise ValueError('oversized record')
            value = json.loads(payload)
            if set(value) != {'id', 'code', 'bar_period', 'snapshot_id', 'date', 'text', 'price', 'link_kind', 'link_id', 'link_revision', 'created_at', 'integrity'}:
                raise ValueError('fields')
            if value['id'] != identity or str(UUID(identity)) != identity or value['integrity'] != _digest({k: v for k, v in value.items() if k != 'integrity'}):
                raise ValueError('identity')
            result.append(value)
        return result
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        raise store.StoreError('研究标注归档不可核对，原记录已保留') from None


def records(code):
    if not re.fullmatch(r'[0-9]{6}', code):
        raise ValueError('invalid code')
    with store.read() as conn:
        return [r for r in _rows(conn) if r['code'] == code]


def create(body: AnnotationInput):
    context = verify_context(body.context)
    if body.date not in [p[0] for p in context['points']]:
        raise ValueError('date not in snapshot')
    if (body.link_kind is None) != (body.link_id is None):
        raise ValueError('incomplete link')
    link_revision = None
    if body.link_kind:
        import evidence_thesis_service as svc
        read = svc.get_evidence if body.link_kind == 'evidence' else svc.get_thesis
        linked = read(svc.resolve_db_path(), body.link_id)
        if body.link_kind == 'thesis' and linked:
            linked = linked.get('thesis')
        if not linked or linked.get('deleted') or linked.get('subject_type') != 'stock' or linked.get('subject_id') != context['code']:
            raise ValueError('link subject mismatch')
        link_revision = str(linked.get('current_revision') if body.link_kind == 'thesis' else linked.get('updated_at'))
    value = {'id': str(uuid4()), 'code': context['code'], 'bar_period': context['bar_period'],
             'snapshot_id': context['snapshot_id'], 'date': body.date, 'text': body.text,
             'price': body.price, 'link_kind': body.link_kind, 'link_id': body.link_id, 'link_revision': link_revision,
             'created_at': datetime.now(timezone.utc).isoformat()}
    value['integrity'] = _digest(value)
    with store.write() as conn:
        if len(_rows(conn)) >= LIMIT:
            raise ValueError('annotation capacity reached')
        conn.execute('INSERT INTO research_annotations(id,payload) VALUES (?,?)', (value['id'], store.encode(value)))
    return value
