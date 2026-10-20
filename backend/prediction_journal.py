"""Manual, append-only forecasts in the existing local facts database.

No inference, evaluator, provider or model is invoked. Timestamps prove local
recording order, not truth or independence of a user's assertions.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
import observation_workflow_store as store

VERSION = 'manual-prediction.v1'
LIMIT = 500
REVISION_LIMIT = 100
MIN_SAMPLE = 20  # Display caution only; not a statistical calibration threshold.


def now():
    return datetime.now(timezone.utc)


def instant(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('timezone required')
    return parsed.astimezone(timezone.utc)


class Forecast(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: UUID
    question: str = Field(min_length=1, max_length=500)
    subject: str = Field(min_length=1, max_length=160)
    probability: float = Field(strict=True, ge=0, le=1, allow_inf_nan=False)
    deadline: datetime
    evidence_context: str = Field(min_length=1, max_length=2000)
    evidence_kind: Literal['USER_ASSERTION', 'SOURCE_REFERENCE']
    outcome_not_known: StrictBool
    benchmark_probability: float | None = Field(default=None, strict=True, ge=0, le=1, allow_inf_nan=False)
    benchmark_context: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode='after')
    def check(self):
        if self.outcome_not_known is not True:
            raise ValueError('unknown outcome assertion required')
        self.deadline = instant(self.deadline)
        if (self.benchmark_probability is None) != (self.benchmark_context is None):
            raise ValueError('benchmark probability and context required together')
        return self


class Resolution(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_revision: int = Field(strict=True, ge=0, lt=REVISION_LIMIT)
    outcome: Literal['TRUE', 'FALSE', 'INDETERMINATE']
    available_at: datetime
    evidence: str = Field(min_length=1, max_length=2000)
    evidence_kind: Literal['USER_ASSERTION', 'SOURCE_REFERENCE']
    correction_reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def check(self):
        self.available_at = instant(self.available_at)
        return self


class Conflict(ValueError):
    pass


def digest(value):
    return hashlib.sha256(store.encode(value).encode()).hexdigest()


def seal(value):
    return store.encode({**value, 'digest': digest(value)})


def _decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate field')
            result[key] = value
        return result
    if not isinstance(raw, str) or len(raw) > 16384:
        raise ValueError('invalid record size')
    value = json.loads(raw, object_pairs_hook=unique)
    checksum = value.pop('digest')
    if checksum != digest(value):
        raise ValueError('record integrity mismatch')
    return value


def _read(conn):
    try:
        result = []
        for table in ('prediction_forecasts', 'prediction_resolutions'):
            kind = conn.execute('SELECT type FROM sqlite_master WHERE name=?', (table,)).fetchone()
            if kind is not None:
                info = conn.execute(f'PRAGMA table_info({table})').fetchall()
                columns = ['id', 'payload'] if table.endswith('forecasts') else ['id', 'revision', 'payload']
                primary = ['id'] if table.endswith('forecasts') else ['id', 'revision']
                if kind != ('table',) or [r[1] for r in info] != columns or [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]] != primary:
                    raise ValueError('invalid table')
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='prediction_forecasts'").fetchone() is None:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='prediction_resolutions'").fetchone() and conn.execute('SELECT 1 FROM prediction_resolutions LIMIT 1').fetchone():
                raise ValueError('orphan resolutions')
            return []
        rows = conn.execute('SELECT id,payload FROM prediction_forecasts ORDER BY rowid LIMIT ?', (LIMIT + 1,)).fetchall()
        if len(rows) > LIMIT:
            raise ValueError('too many records')
        has_resolutions = conn.execute("SELECT 1 FROM sqlite_master WHERE name='prediction_resolutions'").fetchone()
        for identity, raw in rows:
            value = _decode(raw)
            if set(value) != {'schema_version', 'forecast', 'locked_at'} or value['schema_version'] != VERSION:
                raise ValueError('invalid version')
            forecast = Forecast.model_validate(value['forecast'])
            locked = instant(value['locked_at'])
            if str(forecast.id) != identity or forecast.deadline <= locked:
                raise ValueError('invalid forecast')
            history = []
            if has_resolutions:
                for revision, payload in conn.execute('SELECT revision,payload FROM prediction_resolutions WHERE id=? ORDER BY revision LIMIT ?', (identity, REVISION_LIMIT + 1)):
                    event = _decode(payload)
                    if set(event) != {'resolution', 'recorded_at', 'revision'} or event['revision'] != revision or revision != len(history) + 1 or revision > REVISION_LIMIT:
                        raise ValueError('invalid revision')
                    resolution = Resolution.model_validate(event['resolution'])
                    recorded = instant(event['recorded_at'])
                    if resolution.expected_revision != revision - 1 or not forecast.deadline <= resolution.available_at <= recorded or history and recorded < instant(history[-1]['recorded_at']):
                        raise ValueError('invalid resolution time')
                    history.append(event)
            result.append({**value, 'history': history})
        if has_resolutions and conn.execute('SELECT 1 FROM prediction_resolutions r LEFT JOIN prediction_forecasts f ON r.id=f.id WHERE f.id IS NULL LIMIT 1').fetchone():
            raise ValueError('orphan resolution')
        return result
    except (ValueError, TypeError, KeyError, AttributeError, sqlite3.Error) as exc:
        raise store.StoreError('预测记录不可核对，原记录已保留') from exc


def create(body: Forecast):
    with store.write() as conn:
        rows = _read(conn)
        if any(r['forecast']['id'] == str(body.id) for r in rows):
            raise Conflict('forecast identity already locked; reload to verify')
        if len(rows) >= LIMIT:
            raise ValueError('journal full; history retained')
        stamp = now()
        if body.deadline <= stamp or body.outcome_not_known is not True:
            raise ValueError('forecast must precede deadline and unknown outcome')
        value = {'schema_version': VERSION, 'forecast': body.model_dump(mode='json'), 'locked_at': stamp.isoformat()}
        conn.execute('INSERT INTO prediction_forecasts(id,payload) VALUES(?,?)', (str(body.id), seal(value)))
    return value


def resolve(identity: str, body: Resolution):
    with store.write() as conn:
        record = next((r for r in _read(conn) if r['forecast']['id'] == identity), None)
        if record is None:
            raise LookupError('forecast absent')
        if body.expected_revision != len(record['history']):
            raise Conflict('stale revision; reload history')
        stamp = now()
        if not instant(record['forecast']['deadline']) <= body.available_at <= stamp:
            raise ValueError('resolution must be available after deadline and no later than recording')
        if record['history'] and stamp < instant(record['history'][-1]['recorded_at']):
            raise ValueError('clock moved backwards')
        event = {'resolution': body.model_dump(mode='json'), 'recorded_at': stamp.isoformat(), 'revision': body.expected_revision + 1}
        conn.execute('INSERT INTO prediction_resolutions(id,revision,payload) VALUES(?,?,?)', (identity, event['revision'], seal(event)))
    return event


def summarize(records):
    scored = [r for r in records if r['outcome'] in ('TRUE', 'FALSE')]
    pairs = [(r['forecast']['probability'], int(r['outcome'] == 'TRUE')) for r in scored]
    bins = []
    for index in range(10):
        items = [(p, y) for p, y in pairs if min(int(p * 10), 9) == index]
        bins.append({'lower': index / 10, 'upper': (index + 1) / 10, 'upper_inclusive': index == 9,
                     'count': len(items), 'mean_probability': sum(p for p, _ in items) / len(items) if items else None,
                     'observed_frequency': sum(y for _, y in items) / len(items) if items else None,
                     'sample_caution': len(items) < MIN_SAMPLE})
    matched = [r for r in scored if r['forecast']['benchmark_probability'] is not None]
    return {'total': len(records), 'resolved_binary': len(scored),
            'unresolved': sum(r['outcome'] == 'UNRESOLVED' for r in records),
            'indeterminate': sum(r['outcome'] == 'INDETERMINATE' for r in records),
            'brier': sum((p - y) ** 2 for p, y in pairs) / len(pairs) if pairs else None,
            'benchmark_count': len(matched),
            'benchmark_brier': sum((r['forecast']['benchmark_probability'] - int(r['outcome'] == 'TRUE')) ** 2 for r in matched) / len(matched) if matched else None,
            'matched_forecast_brier': sum((r['forecast']['probability'] - int(r['outcome'] == 'TRUE')) ** 2 for r in matched) / len(matched) if matched else None,
            'sample_caution': len(scored) < MIN_SAMPLE, 'display_caution_minimum': MIN_SAMPLE, 'bins': bins}


def listing(as_of=None):
    stamp = instant(as_of) if as_of else now()
    if stamp > now():
        raise ValueError('future as-of unsupported')
    with store.read() as conn:
        all_records = _read(conn)
    records = []
    for record in all_records:
        if instant(record['locked_at']) > stamp:
            continue
        history = [e for e in record['history'] if instant(e['recorded_at']) <= stamp and instant(e['resolution']['available_at']) <= stamp]
        records.append({**record, 'history': history, 'revision': len(history),
                        'outcome': history[-1]['resolution']['outcome'] if history else 'UNRESOLVED'})
    return {'schema_version': VERSION, 'as_of': stamp.isoformat(), 'records': records, 'summary': summarize(records)}
