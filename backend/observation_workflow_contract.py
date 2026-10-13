"""Strict persisted materialization identities; no record becomes an authority."""
import hashlib
import math


def validate_record(table, keys, value):
    # Import lazily: store and producers share this one restore contract.
    import observation_workflows as obs
    def require(ok):
        if not ok:
            raise ValueError('invalid stored observation record')
    def text(v, maximum=500):
        return isinstance(v, str) and 0 < len(v) <= maximum
    def count(v):
        return type(v) is int and 0 <= v <= 2**53-1
    def when(v):
        return obs.instant(v)
    def number(v):
        return obs.finite(v)
    def bounded_tree(node, depth=0):
        require(depth <= 14)
        if isinstance(node, dict):
            require(len(node) <= 250)
            for k, v in node.items():
                require(isinstance(k, str) and len(k) <= 500)
                bounded_tree(v, depth+1)
        elif isinstance(node, list):
            require(len(node) <= 1000)
            for v in node:
                bounded_tree(v, depth+1)
        elif isinstance(node, str):
            require(len(node) <= 20000)
        elif node is not None and type(node) is not bool:
            require(number(node))
    require(isinstance(value, dict))
    bounded_tree(value)
    def observation(record, day, slot):
        require(isinstance(record, dict) and record.get('schema_version') == obs.SCHEMA and record.get('trade_date') == day
                and record.get('slot') == slot and record.get('status') in ('SAVED', 'PARTIAL') and record.get('research_only') is True)
        start, end = obs.window(day, slot)
        observed = when(record['observed_at'])
        require(start <= observed < end and when(record['cutoff_at']) == end)
        require(record['price_basis'] == ('open_vs_previous_close' if slot == '09:25' else 'latest_vs_previous_close'))
        rows, missing, cohort = record['rows'], record['missing'], record['cohort']
        require(isinstance(rows, list) and len(rows) <= 200 and isinstance(missing, dict) and isinstance(cohort, dict))
        seen = set()
        for row in rows:
            obs.symbol(row['symbol'])
            require(row['symbol'] not in seen and number(row['price']) and row['price'] > 0 and number(row['previous_close']) and row['previous_close'] > 0
                    and number(row['pct']) and abs(row['pct']) <= 1_000_000 and text(row['source_id'])
                    and isinstance(row['sources'], list) and row['sources'] and all(s in {'watchlist', 'holdings', 'yesterday_ladder', 'large_cap', 'turnover_top'} for s in row['sources'])
                    and (row['is_limit_up'] is None or type(row['is_limit_up']) is bool)
                    and (row['turnover_yuan'] is None or number(row['turnover_yuan']) and row['turnover_yuan'] >= 0))
            source = when(row['provider_at'])
            require(source <= observed and (observed-source).total_seconds() <= 60 and source.astimezone(obs.SHANGHAI).date() == observed.astimezone(obs.SHANGHAI).date())
            derived = (row['price']/row['previous_close']-1)*100
            require(number(derived) and abs(derived-row['pct']) <= 1e-7)
            seen.add(row['symbol'])
        for code, reason in missing.items():
            obs.symbol(code)
            require(code not in seen and text(reason))
        require(count(cohort['expected']) and 1 <= cohort['expected'] <= 200 and cohort['expected'] == len(rows)+len(missing))
        require(cohort == obs.cohort_stats(rows, cohort['expected']))
        require((record['status'] == 'SAVED') == cohort['all_expected_present'])
        require(isinstance(record.get('cohorts'), dict))
        for reason, stats in record['cohorts'].items():
            require(reason in {'watchlist', 'holdings', 'yesterday_ladder', 'large_cap', 'turnover_top'} and isinstance(stats, dict) and count(stats['expected']))
            require(stats == obs.cohort_stats([row for row in rows if reason in row['sources']], stats['expected']))
    if table == 'observation_slots':
        observation(value, *keys)
        require(value['status'] == 'SAVED')
    elif table == 'observation_attempts':
        day, slot, attempt = keys
        require(type(attempt) is int and 1 <= attempt <= obs.MAX_ATTEMPTS and value.get('attempt') == attempt
                and value.get('status') in ('SAVED', 'PARTIAL', 'FAILED'))
        start, end = obs.window(day, slot)
        require(start <= when(value['started_at']) < end)
        when(value['finished_at'])
        require(value.get('reason') is None or text(value['reason']))
        if value['status'] in ('SAVED', 'PARTIAL'):
            observation(value['observation'], day, slot)
            require(value['observation']['status'] == value['status'] and when(value['started_at']) <= when(value['finished_at']) < end)
    elif table == 'observation_watch':
        day, code = keys
        require(value.get('symbol') == code and when(value['observed_at']).astimezone(obs.SHANGHAI).date().isoformat() == day)
        obs.symbol(code)
        at = when(value['provider_at'])
        require(obs.continuous_session(at) == value.get('part') and text(value.get('source_id')) and number(value['price']) and value['price'] > 0 and number(value['previous_close']) and value['previous_close'] > 0)
        require(value['is_limit_up'] is None or type(value['is_limit_up']) is bool)
        frames = value['frames']
        require(isinstance(frames, list) and 1 <= len(frames) <= 1000)
        previous = None
        for frame in frames:
            t = when(frame['at'])
            require(number(frame['price']) and frame['price'] > 0 and t <= at and (at-t).total_seconds() <= 180 and (previous is None or previous < t))
            previous = t
        require(frames[-1]['at'] == value['provider_at'] and frames[-1]['price'] == value['price'] and isinstance(value['cooldowns'], dict))
        for kind, t in value['cooldowns'].items():
            require(kind in ('RAPID_UP', 'RAPID_DOWN', 'SEALED', 'OPENED') and when(t) <= at)
    elif table == 'observation_events':
        identity, day = keys
        require(value.get('id') == identity and value.get('trade_date') == day and value.get('rule_version') == obs.RULE)
        obs.symbol(value['symbol'])
        require(value['kind'] in ('RAPID_UP', 'RAPID_DOWN', 'SEALED', 'OPENED') and text(value['source_id']) and isinstance(value['sources'], list) and all(text(x) for x in value['sources']))
        at, received = when(value['provider_at']), when(value['observed_at'])
        require(at <= received and (received-at).total_seconds() <= 60 and at.astimezone(obs.SHANGHAI).date().isoformat() == day)
        expected = hashlib.sha256(f'{obs.RULE}|{day}|{value["symbol"]}|{value["kind"]}|{value["provider_at"]}'.encode()).hexdigest()
        require(identity == expected)
        move = value['move_pct']
        require(move is None if value['kind'] in ('SEALED', 'OPENED') else number(move) and 1.5 <= abs(move) <= 1_000_000 and (move > 0) == (value['kind'] == 'RAPID_UP'))
    elif table == 'observation_tasks':
        day, kind = keys
        require(kind in obs.SCHEDULE and value.get('id') == f'{day}:{kind}' and value.get('trade_date') == day and value.get('kind') == kind
                and value.get('status') in ('COMPLETE', 'PARTIAL', 'FAILED') and type(value.get('attempts')) is int and 1 <= value['attempts'] <= 3
                and value.get('external_delivery') == 'DISABLED' and type(value.get('acknowledged')) is bool)
        when(value['started_at']); when(value['finished_at'])
        require(value.get('reason') is None or text(value['reason']))
        if value['status'] != 'FAILED':
            require(isinstance(value.get('output'), dict) and value['output'].get('status') == value['status'])
            from observation_reminders import validate_output
            validate_output(kind, day, value['output'], when(value['finished_at']))
        if value['acknowledged']:
            when(value['acknowledged_at'])
    elif table == 'observation_notices':
        identity, day = keys
        obs.symbol(value['symbol'])
        require(value.get('id') == identity and text(value['provider_notice_id']) and text(value['title']) and text(value['source_id']))
        require(when(value['published_at']) <= when(value['observed_at']) and when(value['observed_at']).astimezone(obs.SHANGHAI).date().isoformat() == day)
        require(identity == hashlib.sha256(f'{value["symbol"]}|{value["source_id"]}|{value["provider_notice_id"]}'.encode()).hexdigest())
    else:
        raise ValueError('unknown record type')
