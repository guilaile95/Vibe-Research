"""Finite, opt-in software producers. No threads, timers, providers or notifications.

Upstream design reference: simonlin1212/vibe-astock d5bf80d (Apache-2.0),
shortline/watch.ts and intraday.ts. Implemented against this app's authorities.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextvars import ContextVar
import hashlib
import math
import re
from typing import Callable

import next_day_verification as verification
import observation_workflow_store as store
import trade_calendar

_preview_clock = ContextVar('observation_preview_clock', default=None)
SCHEMA = 'observation-workflows.v1'
RULE = 'move-180s-1.5pct-cooldown300s.v1'
SHANGHAI = timezone(timedelta(hours=8))
SLOTS = ('09:25', '09:35', '10:00', '11:30', '14:00', '15:00')
MAX_ATTEMPTS = 3
SCHEDULE = {'premarket': '09:05', 'close_digest': '15:40', 'watch_changes': '16:15', 'verification_due': '16:30'}

class ObservationError(ValueError):
    pass


def _now():
    return _preview_clock.get() or datetime.now(timezone.utc)


def stamp(at):
    return at.astimezone(timezone.utc).isoformat(timespec='microseconds')


def instant(value):
    if not isinstance(value, str) or not trade_calendar._UTC_ZERO_OFFSET_RE.fullmatch(value):
        raise ObservationError('来源时间必须为带秒数的 UTC 时间')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ObservationError('来源时间无效') from exc


def session(day):
    if not isinstance(day, str) or trade_calendar._parse_strict_date(day) is None:
        raise ObservationError('日期无效')
    calendar = trade_calendar._load_calendar()
    if calendar is None:
        return 'CALENDAR_UNKNOWN'
    if not calendar[0] <= day <= calendar[-1]:
        return 'CALENDAR_UNKNOWN'
    return 'TRADING_DAY' if day in calendar else 'MARKET_CLOSED'


def window(day, slot):
    if slot not in SLOTS:
        raise ObservationError('未知观察时点')
    start = datetime.fromisoformat(f'{day}T{slot}:00+08:00')
    # End exclusive: auction never includes continuous trading or 09:29.
    return start, start + timedelta(minutes=4 if slot == '09:25' else 8)


def slot_state(day, slot, at):
    state = session(day)
    if state != 'TRADING_DAY':
        return state
    start, end = window(day, slot)
    return 'UPCOMING' if at < start else 'MISSING' if at >= end else 'AVAILABLE'


def finite(value, positive=False):
    return type(value) in (float, int) and math.isfinite(value) and abs(value) <= 2**53 - 1 and (not positive or value > 0)


def symbol(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:sh|sz|bj)\d{6}', value):
        raise ObservationError('股票标识必须含市场前缀')
    return value


def watch_universe(groups: dict[str, list[str]]):
    allowed = {'watchlist', 'holdings', 'yesterday_ladder', 'large_cap', 'turnover_top'}
    if not isinstance(groups, dict) or not set(groups) <= allowed:
        raise ObservationError('观察名单来源无效')
    result = {}
    for reason, symbols in groups.items():
        if not isinstance(symbols, list):
            raise ObservationError('观察名单无效')
        for code in symbols:
            result.setdefault(symbol(code), []).append(reason)
    if len(result) > 200:
        raise ObservationError('每批最多观察 200 只')
    return {code: sorted(set(reasons)) for code, reasons in sorted(result.items())}


def qualify_quotes(raw, universe, observed, *, auction=False, slot=None):
    """Provider fields are explicit. Missing open/clock never becomes latest/zero."""
    if not isinstance(raw, list) or len(raw) > 200:
        raise ObservationError('报价批次无效')
    rows, missing, seen = [], {}, set()
    for row in raw:
        if not isinstance(row, dict):
            raise ObservationError('报价记录无效')
        code = symbol(row.get('symbol'))
        if code not in universe or code in seen:
            raise ObservationError('报价身份重复或不在观察名单')
        seen.add(code)
        try:
            at = instant(row.get('provider_at'))
            current = row.get('open_price') if auction else row.get('price')
            prior = row.get('previous_close')
            if not finite(current, True) or not finite(prior, True):
                raise ObservationError('PRICE_UNKNOWN')
            if not isinstance(row.get('source_id'), str) or not row['source_id'].strip() or len(row['source_id']) > 200:
                raise ObservationError('SOURCE_UNKNOWN')
            if at > observed or observed - at > timedelta(seconds=60):
                raise ObservationError('QUOTE_STALE_OR_FUTURE')
            if at.astimezone(SHANGHAI).date() != observed.astimezone(SHANGHAI).date():
                raise ObservationError('QUOTE_WRONG_DAY')
            if slot and auction and at < window(observed.astimezone(SHANGHAI).date().isoformat(), slot)[0]:
                raise ObservationError('AUCTION_NOT_FINAL')
            pct = (current / prior - 1) * 100
            if not finite(pct) or abs(pct) > 1_000_000:
                raise ObservationError('DERIVED_RETURN_OUT_OF_RANGE')
            is_limit_up = row.get('is_limit_up')
            if is_limit_up is not None and type(is_limit_up) is not bool:
                raise ObservationError('LIMIT_STATE_UNKNOWN')
            rows.append({'symbol': code, 'price': current, 'previous_close': prior,
                         'pct': pct, 'provider_at': stamp(at),
                         'source_id': row['source_id'], 'is_limit_up': is_limit_up,
                         'turnover_yuan': row.get('turnover_yuan') if finite(row.get('turnover_yuan')) and row['turnover_yuan'] >= 0 else None,
                         'sources': universe[code]})
        except ObservationError as exc:
            missing[code] = str(exc)
    missing.update({code: 'QUOTE_MISSING' for code in universe if code not in seen})
    return rows, missing


def cohort_stats(rows, expected):
    values = sorted(row['pct'] for row in rows)
    if any(not finite(v) for v in values):
        raise ObservationError('DERIVED_RETURN_OUT_OF_RANGE')
    n = len(values)
    median = values[(n-1)//2]/2 + values[n//2]/2 if n else None
    return {'expected': expected, 'samples': n, 'coverage': n / expected if expected else None,
            'median_pct': median, 'positive': sum(v > 0 for v in values) if n else None,
            'non_negative': sum(v >= 0 for v in values) if n else None,
            'strong_ge_3pct': sum(v >= 3 for v in values) if n else None,
            'all_expected_present': expected > 0 and n == expected}


def capture_slot(day: str, slot: str, groups: dict, fetch: Callable[[list[str]], list[dict]]):
    """A finite producer adapter for an authorized runner; never scheduled here.

    Acquires the shared write lock before checking state/fetching. Other windows
    cannot dispatch duplicate fetches. Receipt time is sampled after fetch;
    recheck after all computation before immutable insertion. Exceptions are
    sanitized and count as attempts; a crash rolls back and consumes no slot.
    """
    universe = watch_universe(groups)
    if not universe:
        raise ObservationError('观察名单为空')
    start = _now()
    if slot_state(day, slot, start) != 'AVAILABLE':
        raise ObservationError('当前不在允许取样窗口，禁止补写')
    with store.write() as conn:
        existing = store.rows(conn, 'observation_slots', 'WHERE day=? AND slot=?', (day, slot))
        if existing:
            return existing[0]
        now = _now()
        attempts = store.rows(conn, 'observation_attempts', 'WHERE day=? AND slot=? ORDER BY attempt', (day, slot))
        if slot_state(day, slot, now) != 'AVAILABLE' or now < start:
            raise ObservationError('取样窗口已关闭或时钟回退')
        if len(attempts) >= MAX_ATTEMPTS:
            raise ObservationError('此时点的有限重试已用尽')
        if attempts and now < instant(attempts[-1]['finished_at']) + timedelta(seconds=30):
            raise ObservationError('重试至少间隔 30 秒，或时钟已回退')
        attempt = {'attempt': len(attempts)+1, 'started_at': stamp(now), 'status': 'FAILED', 'reason': 'PRODUCER_FAILED'}
        result = None
        try:
            raw = fetch(list(universe))
            observed = _now()
            if observed < now or slot_state(day, slot, observed) != 'AVAILABLE':
                raise ObservationError('WINDOW_EXPIRED_OR_CLOCK_REVERSED')
            rows, missing = qualify_quotes(raw, universe, observed, auction=slot == '09:25', slot=slot)
            stats = cohort_stats(rows, len(universe))
            result = {'schema_version': SCHEMA, 'trade_date': day, 'slot': slot,
                      'observed_at': stamp(observed), 'cutoff_at': stamp(window(day, slot)[1]),
                      'price_basis': 'open_vs_previous_close' if slot == '09:25' else 'latest_vs_previous_close',
                      'status': 'SAVED' if stats['all_expected_present'] else 'PARTIAL',
                      'rows': rows, 'missing': missing, 'cohort': stats,
                      'cohorts': {reason: cohort_stats([row for row in rows if reason in row['sources']], sum(reason in reasons for reasons in universe.values())) for reason in groups},
                      'research_only': True}
            attempt.update(status=result['status'], reason=None if not missing else 'INCOMPLETE_QUOTES', observation=result)
        except Exception as exc:
            attempt['reason'] = str(exc) if isinstance(exc, ObservationError) else 'PRODUCER_FAILED'
        finished = _now()
        if finished < now or slot_state(day, slot, finished) != 'AVAILABLE':
            result = None
            attempt.update(status='FAILED', reason='WINDOW_EXPIRED_OR_CLOCK_REVERSED')
        attempt['finished_at'] = stamp(finished)
        conn.execute('INSERT INTO observation_attempts VALUES (?,?,?,?)', (day, slot, attempt['attempt'], store.encode(attempt)))
        if result and result['status'] == 'SAVED':
            conn.execute('INSERT INTO observation_slots VALUES (?,?,?)', (day, slot, store.encode(result)))
        return result if result else attempt


def continuous_session(at):
    local = at.astimezone(SHANGHAI)
    day = local.date().isoformat()
    if session(day) != 'TRADING_DAY':
        return None
    t = local.strftime('%H:%M:%S.%f')
    return 'morning' if '09:30:00' <= t < '11:30:00' else 'afternoon' if '13:00:00' <= t < '15:00:00' else None


def record_watch_quotes(groups: dict, raw: list[dict]):
    """Consume one existing authorized quote response; does not fetch or poll."""
    observed = _now()
    part = continuous_session(observed)
    if part is None:
        raise ObservationError('连续竞价时段以外不比较异动')
    day = observed.astimezone(SHANGHAI).date().isoformat()
    universe = watch_universe(groups)
    rows, missing = qualify_quotes(raw, universe, observed)
    events = []
    with store.write() as conn:
        for row in rows:
            at = instant(row['provider_at'])
            if continuous_session(at) != part:
                missing[row['symbol']] = 'QUOTE_WRONG_SESSION'
                continue
            code = row['symbol']
            old_rows = store.rows(conn, 'observation_watch', 'WHERE day=? AND symbol=?', (day, code))
            old = old_rows[0] if old_rows else None
            if old and (instant(old['observed_at']) > observed or instant(old['provider_at']) >= at):
                missing[code] = 'QUOTE_NOT_NEW_OR_CLOCK_REVERSED'
                continue
            same = old and old['part'] == part and old['source_id'] == row['source_id'] and old['previous_close'] == row['previous_close']
            frames = [frame for frame in old['frames'] if at - instant(frame['at']) <= timedelta(seconds=180)] if same else []
            if len(frames) >= 181:
                missing[code] = 'QUOTE_RATE_EXCEEDS_RETENTION_BOUND'
                continue
            cooldowns = old['cooldowns'] if same else {}
            kinds = []
            if frames and at - instant(frames[0]['at']) >= timedelta(seconds=60):
                move = (row['price']/frames[0]['price'] - 1)*100
                if finite(move) and 1.5 <= abs(move) <= 1_000_000:
                    kinds.append(('RAPID_UP' if move > 0 else 'RAPID_DOWN', move))
            if same and type(old.get('is_limit_up')) is bool and type(row['is_limit_up']) is bool and old['is_limit_up'] != row['is_limit_up']:
                kinds.append(('SEALED' if row['is_limit_up'] else 'OPENED', None))
            for kind, move in kinds:
                if kind in cooldowns and at - instant(cooldowns[kind]) < timedelta(seconds=300):
                    continue
                identity = hashlib.sha256(f'{RULE}|{day}|{code}|{kind}|{row["provider_at"]}'.encode()).hexdigest()
                event = {'id': identity, 'rule_version': RULE, 'trade_date': day, 'symbol': code, 'kind': kind,
                         'provider_at': row['provider_at'], 'observed_at': stamp(observed), 'move_pct': move,
                         'source_id': row['source_id'], 'sources': row['sources']}
                conn.execute('INSERT OR IGNORE INTO observation_events VALUES (?,?,?)', (identity, day, store.encode(event)))
                events.append(event)
                cooldowns[kind] = row['provider_at']
            frames.append({'at': row['provider_at'], 'price': row['price']})
            state = {**row, 'part': part, 'observed_at': stamp(observed), 'frames': frames, 'cooldowns': cooldowns}
            conn.execute('INSERT INTO observation_watch VALUES (?,?,?) ON CONFLICT(day,symbol) DO UPDATE SET payload=excluded.payload', (day, code, store.encode(state)))
    return {'events': events, 'missing': missing, 'observed_at': stamp(observed)}


def due_projection(at=None):
    """Projection only. A due reminder never marks a prediction fulfilled."""
    at = at or _now()
    plans = verification._read_plans(verification.journal_path())
    items = []
    eligible = []
    for day, plan in sorted(plans.items(), reverse=True):
        if not plan['items']:
            continue
        target = trade_calendar.next_trade_date(day)
        due = datetime.fromisoformat(f'{target}T16:30:00+08:00') if target else None
        if due is None or at >= due:
            eligible.append((day, plan, target, due))
    for day, plan, target, due in eligible[:20]:
            results = verification._results(day, plan, at)
            items.append({'id': f'verification:{day}:r{plan["revision"]}', 'set_date': day,
                          'target_date': target, 'due_at': stamp(due) if due else None,
                          'state': 'CALENDAR_UNKNOWN' if due is None else 'RECONCILED' if all(x['verified'] is not None for x in results) else 'DUE_UNRESOLVED',
                          'summary': verification._summary(results), 'items': results})
    return {'items': items, 'coverage': {'eligible_plans': len(eligible), 'evaluated_plans': len(items), 'has_more': len(eligible) > 20, 'order': 'latest_set_date_first', 'maximum': 20}}


def due_verifications(at=None):
    return due_projection(at)['items']


def view(day, *, include_due=True):
    now = _now()
    calendar = session(day)
    with store.read() as conn:
        saved = {x['slot']: x for x in store.rows(conn, 'observation_slots', 'WHERE day=?', (day,))}
        attempts = {slot: store.rows(conn, 'observation_attempts', 'WHERE day=? AND slot=? ORDER BY attempt', (day, slot)) for slot in SLOTS}
        events = store.rows(conn, 'observation_events', "WHERE day=? ORDER BY json_extract(payload, '$.provider_at') DESC,id DESC LIMIT 500", (day,))
        event_total = conn.execute('SELECT count(*) FROM observation_events WHERE day=?', (day,)).fetchone()[0] if conn.execute("SELECT 1 FROM sqlite_schema WHERE name='observation_events'").fetchone() else 0
        tasks = store.rows(conn, 'observation_tasks', 'WHERE day=? ORDER BY kind', (day,))
    slots = []
    for slot in SLOTS:
        tries = attempts[slot]
        state = 'SAVED' if slot in saved else slot_state(day, slot, now)
        if state == 'AVAILABLE' and len(tries) >= MAX_ATTEMPTS:
            state = 'RETRIES_EXHAUSTED'
        slots.append({'slot': slot, 'state': state, 'cutoff_at': stamp(window(day, slot)[1]),
                      'observation': saved.get(slot), 'attempts': tries,
                      'reason': None if slot in saved else tries[-1]['reason'] if tries else 'NOT_COLLECTED'})
    due = due_projection(now) if include_due else {'items': [], 'coverage': {'eligible_plans': 0, 'evaluated_plans': 0, 'has_more': False, 'order': 'latest_set_date_first', 'maximum': 20}}
    return {'schema_version': SCHEMA, 'trade_date': day, 'calendar_state': calendar,
            'generated_at': stamp(now), 'collector_enabled': False, 'scheduler_enabled': False,
            'external_notifications_enabled': False, 'research_only': True,
            'slots': slots, 'events': sorted(events, key=lambda x: (x['provider_at'], x['id']), reverse=True)[:500],
            'event_coverage': {'total': event_total, 'returned': len(events), 'has_more': event_total > len(events)},
            'tasks': tasks, 'due': due['items'], 'due_coverage': due['coverage'], 'schedule': SCHEDULE}
