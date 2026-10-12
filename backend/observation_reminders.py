"""Bounded briefing/task producers and private Inbox projection.

Scheduling and all external delivery are deliberately absent. Supplied producer
ports are called only by explicit software execution, never from GET/import.
"""
from datetime import datetime, timedelta
import hashlib

import observation_workflow_store as store
import observation_workflows as obs

KINDS = tuple(obs.SCHEDULE)
PREMARKET_SECTIONS = ('overseas', 'ladder_announcements', 'suspensions', 'new_listings')


def _task_window(day, kind, at):
    if kind not in KINDS or obs.session(day) != 'TRADING_DAY':
        raise obs.ObservationError('任务或交易日历不可用')
    if at.astimezone(obs.SHANGHAI).date().isoformat() != day:
        raise obs.ObservationError('任务必须使用当前交易日；历史任务不能补造当日简报')
    start = datetime.fromisoformat(f'{day}T{obs.SCHEDULE[kind]}:00+08:00')
    end = datetime.fromisoformat(f'{day}T11:30:00+08:00') if kind == 'premarket' else datetime.fromisoformat(f'{day}T23:59:59+08:00')
    if not start <= at < end:
        raise obs.ObservationError('任务不在允许窗口内')


def _public_rows(section, rows, observed):
    if not isinstance(rows, list) or len(rows) > 50:
        return False
    fields = {'symbol', 'title', 'value', 'unit', 'event_date', 'published_at'}
    for row in rows:
        if (not isinstance(row, dict) or not set(row) <= fields or not isinstance(row.get('title'), str)
                or not 1 <= len(row['title'].strip()) <= 500):
            return False
        if 'symbol' in row:
            obs.symbol(row['symbol'])
        if 'value' in row and (not obs.finite(row['value']) or not isinstance(row.get('unit'), str) or not 1 <= len(row['unit']) <= 30):
            return False
        if section == 'overseas' and ('value' not in row or 'published_at' not in row):
            return False
        if 'event_date' in row and obs.trade_calendar._parse_strict_date(row['event_date']) is None:
            return False
        if 'published_at' in row and obs.instant(row['published_at']) > observed:
            return False
        if 'published_at' not in row and 'event_date' not in row:
            return False
    return True


def premarket(day, source):
    """Complete means a bounded, timestamped source section, never [{}]."""
    sections, missing = {}, []
    observed = obs._now()
    for key in PREMARKET_SECTIONS:
        item = source.get(key) if isinstance(source, dict) else None
        valid = (isinstance(item, dict) and set(item) == {'trade_date', 'status', 'complete', 'source_total', 'rows', 'source_id', 'captured_at'}
                 and item['trade_date'] == day and item['status'] == 'COMPLETE' and item['complete'] is True
                 and type(item['source_total']) is int and isinstance(item['rows'], list) and item['source_total'] == len(item['rows'])
                 and isinstance(item['source_id'], str) and 1 <= len(item['source_id'].strip()) <= 200)
        if valid:
            try:
                valid = obs.instant(item['captured_at']) <= observed and _public_rows(key, item['rows'], observed)
            except (ValueError, TypeError):
                valid = False
        if not valid:
            missing.append(key); sections[key] = None
        else:
            sections[key] = dict(item)
    return {'trade_date': day, 'status': 'COMPLETE' if not missing else 'PARTIAL',
            'sections': sections, 'missing': missing, 'regulatory_distance': 'NOT_EVALUATED'}


def close_digest(day):
    """Use existing exact-date archive/final qualifier; never invokes a provider."""
    now = obs._now()
    fact = __import__('next_day_verification')._fact(day, now)
    # Missing data remains null. In particular, no dragon-tiger rows is not zero.
    return {'trade_date': day, 'status': 'PARTIAL',
            'facts': fact, 'dragon_tiger': None,
            'missing': ['dragon_tiger'] + ([] if fact else ['qualified_close_facts']),
            'observation_basis': 'CURRENT_STORED_CLOSE_RESEARCH', 'advice': None}


def announcement_batch(conn, day, code, batch, observed):
    """Validate a complete <=50 batch before atomic notices+cursor persistence."""
    obs.symbol(code)
    old = conn.execute('SELECT since FROM observation_cursors WHERE symbol=?', (code,)).fetchone()
    since = old[0] if old else None
    if (not isinstance(batch, dict) or batch.get('status') != 'COMPLETE'
            or batch.get('since') != since or not isinstance(batch.get('items'), list)
            or len(batch['items']) > 50 or batch.get('has_more') is not False):
        return {'symbol': code, 'status': 'NOT_CHECKED', 'reason': 'BATCH_INCOMPLETE_OR_CURSOR_CONFLICT', 'since': since}
    through = obs.instant(batch.get('through'))
    if through > observed or (since and through <= obs.instant(since)):
        raise obs.ObservationError('公告批次时间冲突')
    ready, seen, previous = [], set(), None
    for item in batch['items']:
        if (not isinstance(item, dict) or set(item) != {'id', 'symbol', 'published_at', 'title', 'source_id'}
                or item['symbol'] != code or any(not isinstance(item[k], str) or not item[k].strip() for k in ('id', 'title', 'source_id'))
                or len(item['title']) > 500 or item['id'] in seen):
            raise obs.ObservationError('公告记录身份或内容冲突')
        at = obs.instant(item['published_at'])
        identity = (at, item['id'])
        if at > through or (since and at <= obs.instant(since)) or (previous and identity <= previous):
            raise obs.ObservationError('公告排序或时间范围冲突')
        previous = identity
        seen.add(item['id'])
        key = hashlib.sha256(f'{code}|{item["source_id"]}|{item["id"]}'.encode()).hexdigest()
        payload = {**item, 'id': key, 'provider_notice_id': item['id'], 'observed_at': obs.stamp(observed)}
        existing = store.rows(conn, 'observation_notices', 'WHERE id=?', (key,))
        if existing and any(existing[0].get(k) != payload[k] for k in ('symbol', 'published_at', 'title', 'source_id')):
            raise obs.ObservationError('已保存公告身份发生冲突')
        ready.append((key, payload))
    for key, payload in ready:
        conn.execute('INSERT OR IGNORE INTO observation_notices VALUES (?,?,?)', (key, day, store.encode(payload)))
    conn.execute('INSERT INTO observation_cursors VALUES (?,?) ON CONFLICT(symbol) DO UPDATE SET since=excluded.since', (code, obs.stamp(through)))
    return {'symbol': code, 'status': 'COMPLETE', 'since': obs.stamp(through), 'count': len(ready)}


def run_task(day, kind, producer=None, symbols=()):
    """Run/retry one finite task. Automatic dispatch and external send stay off.

    producer is an internal dependency-injection port, never callable content or
    URL from HTTP. Defaults read local archives only and explicitly show gaps.
    """
    start = obs._now()
    _task_window(day, kind, start)
    with store.write() as conn:
        now = obs._now()
        _task_window(day, kind, now)
        old = store.rows(conn, 'observation_tasks', 'WHERE day=? AND kind=?', (day, kind))
        previous = old[0] if old else None
        if previous and previous['status'] == 'COMPLETE':
            return previous
        if previous and (previous['attempts'] >= 3 or now < obs.instant(previous['finished_at']) + timedelta(seconds=30)):
            raise obs.ObservationError('任务重试已用尽或尚未到重试时间')
        task = {'id': f'{day}:{kind}', 'trade_date': day, 'kind': kind, 'status': 'FAILED',
                'attempts': previous['attempts']+1 if previous else 1, 'started_at': obs.stamp(now),
                'external_delivery': 'DISABLED', 'acknowledged': False, 'reason': None}
        conn.execute('SAVEPOINT producer')
        try:
            if kind == 'premarket':
                output = premarket(day, producer() if producer else {})
            elif kind == 'close_digest':
                output = producer() if producer else close_digest(day)
                if output.get('trade_date') != day:
                    raise obs.ObservationError('收盘简报日期不匹配')
            elif kind == 'verification_due':
                output = producer() if producer else {'status': 'COMPLETE', **obs.due_projection(now)}
            else:
                symbols = sorted(set(obs.symbol(code) for code in symbols))
                if len(symbols) > 50:
                    raise obs.ObservationError('公告任务每批最多 50 只股票')
                results = []
                for code in symbols:
                    cursor = conn.execute('SELECT since FROM observation_cursors WHERE symbol=?', (code,)).fetchone()
                    conn.execute('SAVEPOINT symbol_batch')
                    try:
                        batch = producer(code, cursor[0] if cursor else None) if producer else None
                        result = announcement_batch(conn, day, code, batch, obs._now())
                        conn.execute('RELEASE symbol_batch')
                    except Exception:
                        conn.execute('ROLLBACK TO symbol_batch')
                        conn.execute('RELEASE symbol_batch')
                        result = {'symbol': code, 'status': 'NOT_CHECKED', 'reason': 'SOURCE_FAILED_OR_INVALID', 'since': cursor[0] if cursor else None}
                    results.append(result)
                missing = [x['symbol'] for x in results if x['status'] != 'COMPLETE']
                output = {'status': 'COMPLETE' if symbols and not missing else 'PARTIAL', 'symbols': results,
                          'missing': missing, 'universe_status': 'EXPLICIT_WATCHLIST' if symbols else 'WATCHLIST_NOT_CONNECTED'}
            end = obs._now()
            _task_window(day, kind, end)
            if end < now:
                raise obs.ObservationError('任务时钟回退')
            validate_output(kind, day, output, end)
            task.update(status=output['status'], output=output)
            conn.execute('RELEASE producer')
        except Exception:
            conn.execute('ROLLBACK TO producer')
            conn.execute('RELEASE producer')
            task['reason'] = 'PRODUCER_FAILED_OR_WINDOW_CLOSED'
        task['finished_at'] = obs.stamp(obs._now())
        conn.execute('INSERT INTO observation_tasks VALUES (?,?,?) ON CONFLICT(day,kind) DO UPDATE SET payload=excluded.payload', (day, kind, store.encode(task)))
        return task


def acknowledge(day, kind):
    if kind not in KINDS:
        raise obs.ObservationError('未知任务')
    with store.write() as conn:
        rows = store.rows(conn, 'observation_tasks', 'WHERE day=? AND kind=?', (day, kind))
        if not rows:
            raise obs.ObservationError('任务不存在')
        item = rows[0]
        item.update(acknowledged=True, acknowledged_at=obs.stamp(obs._now()))
        conn.execute('UPDATE observation_tasks SET payload=? WHERE day=? AND kind=?', (store.encode(item), day, kind))
        return item


def validate_output(kind, day, value, observed):
    """Public task completion contract, shared by producer and stored restore."""
    def check(ok):
        if not ok:
            raise obs.ObservationError('任务结果合同无效')
    check(isinstance(value, dict) and value.get('status') in ('COMPLETE', 'PARTIAL'))
    if kind == 'premarket':
        check(set(value) == {'trade_date', 'status', 'sections', 'missing', 'regulatory_distance'} and value['trade_date'] == day
              and value['regulatory_distance'] == 'NOT_EVALUATED' and isinstance(value['sections'], dict) and set(value['sections']) == set(PREMARKET_SECTIONS)
              and isinstance(value['missing'], list) and set(value['missing']) <= set(PREMARKET_SECTIONS))
        missing = []
        for key, item in value['sections'].items():
            if item is None:
                missing.append(key); continue
            check(isinstance(item, dict) and set(item) == {'trade_date', 'status', 'complete', 'source_total', 'rows', 'source_id', 'captured_at'}
                  and item['trade_date'] == day and item['status'] == 'COMPLETE' and item['complete'] is True and isinstance(item['rows'], list)
                  and type(item['source_total']) is int and item['source_total'] == len(item['rows'])
                  and isinstance(item['source_id'], str) and 1 <= len(item['source_id'].strip()) <= 200
                  and obs.instant(item['captured_at']) <= observed and _public_rows(key, item['rows'], observed))
        check(set(missing) == set(value['missing']) and len(missing) == len(value['missing']) and (value['status'] == 'COMPLETE') == (not missing))
    elif kind == 'close_digest':
        check(set(value) == {'trade_date', 'status', 'facts', 'dragon_tiger', 'missing', 'observation_basis', 'advice'}
              and value['trade_date'] == day and value['observation_basis'] == 'CURRENT_STORED_CLOSE_RESEARCH' and value['advice'] is None)
        fact = value['facts']
        if fact is not None:
            import next_day_verification as verification
            check(isinstance(fact, dict) and set(fact) == {'values', 'source_ids', 'fetched_at', 'snapshot_at', 'stored_at'}
                  and isinstance(fact['values'], dict) and set(fact['values']) == verification.LEGACY_METRICS
                  and isinstance(fact['source_ids'], list) and fact['source_ids'] and all(isinstance(x, str) and x for x in fact['source_ids']))
            check(all(v is None or verification._value(fact, k) is not None for k, v in fact['values'].items()))
            check(datetime.fromisoformat(day+'T15:00:00+08:00') <= obs.instant(fact['fetched_at']) <= obs.instant(fact['snapshot_at']) <= obs.instant(fact['stored_at']) <= observed)
        # This archive-only adapter has no qualified dragon-tiger completeness
        # port. Never turn missing into zero or mark this summary complete.
        check(value['dragon_tiger'] is None and value['status'] == 'PARTIAL'
              and value['missing'] == ['dragon_tiger'] + ([] if fact else ['qualified_close_facts']))
    elif kind == 'verification_due':
        check(set(value) == {'status', 'items', 'coverage'} and value['status'] == 'COMPLETE' and isinstance(value['items'], list) and len(value['items']) <= 20)
        coverage = value['coverage']
        check(isinstance(coverage, dict) and set(coverage) == {'eligible_plans', 'evaluated_plans', 'has_more', 'order', 'maximum'}
              and type(coverage['eligible_plans']) is int and coverage['eligible_plans'] >= len(value['items'])
              and coverage['evaluated_plans'] == len(value['items']) and coverage['has_more'] == (coverage['eligible_plans'] > 20)
              and coverage['maximum'] == 20 and coverage['order'] == 'latest_set_date_first')
        for item in value['items']:
            check(isinstance(item, dict) and set(item) == {'id', 'set_date', 'target_date', 'due_at', 'state', 'summary', 'items'}
                  and item['state'] in ('DUE_UNRESOLVED', 'RECONCILED', 'CALENDAR_UNKNOWN') and isinstance(item['items'], list))
            import next_day_verification as verification
            check(item['summary'] == verification._summary(item['items']))
            check((item['state'] == 'RECONCILED') == all(x['verified'] is not None for x in item['items']))
            if item['due_at'] is not None:
                check(obs.instant(item['due_at']) <= observed)
    elif kind == 'watch_changes':
        check(set(value) == {'status', 'symbols', 'missing', 'universe_status'} and isinstance(value['symbols'], list) and len(value['symbols']) <= 50
              and isinstance(value['missing'], list) and value['universe_status'] in ('EXPLICIT_WATCHLIST', 'WATCHLIST_NOT_CONNECTED'))
        seen, missing = set(), []
        for item in value['symbols']:
            obs.symbol(item['symbol']); check(item['symbol'] not in seen); seen.add(item['symbol'])
            check(item['status'] in ('COMPLETE', 'NOT_CHECKED'))
            if item['status'] == 'COMPLETE':
                check(set(item) == {'symbol', 'status', 'since', 'count'} and type(item['count']) is int and 0 <= item['count'] <= 50 and obs.instant(item['since']) <= observed)
            else:
                check(set(item) == {'symbol', 'status', 'since', 'reason'} and isinstance(item['reason'], str))
                if item['since'] is not None:
                    check(obs.instant(item['since']) <= observed)
                missing.append(item['symbol'])
        check(value['missing'] == missing and (value['status'] == 'COMPLETE') == (bool(seen) and not missing))
    else:
        raise obs.ObservationError('未知任务')


def run_local_task(day, kind):
    """Explicit API run, local watchlist identity only, never a market fetch."""
    symbols = []
    if kind == 'watch_changes':
        import watchlist_store
        from astock import get_prefix
        status = watchlist_store.get_watchlist_status()
        if status.get('status') == 'valid':
            symbols = [get_prefix(code)+code for code in status['data']['codes']]
    return run_task(day, kind, symbols=symbols)
