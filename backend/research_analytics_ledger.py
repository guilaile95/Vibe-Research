"""One bounded immutable ledger image shared by research projections. No source SQLite opens."""
import re
from datetime import datetime
import account_event_store
import formal_trade_attribution
import performance_attribution_service as pa
from personal_review_snapshot import Snapshot

UTC_STAMP = re.compile(r'^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|\+00:00)$')


def read_frozen_ledger(path):
    snapshot = Snapshot(path)
    if snapshot.source is None:
        raise ValueError('canonical ledger source absent')
    def frozen_rows(conn):
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'trade_records', 'account_events'} <= tables:
            raise ValueError('canonical ledger tables missing')
        required = {
            'trade_records': {'trade_id', 'code', 'operation', 'execution_status', 'actual_price', 'actual_quantity', 'executed_at', 'fee', 'other_cost', 'created_at', 'voided_at'},
            'account_events': {'event_id', 'event_type', 'target_event_id', 'target_event_type', 'before_payload', 'after_payload', 'created_at', 'voided_at'},
        }
        for table, columns in required.items():
            info = list(conn.execute('PRAGMA table_info(' + table + ')'))
            if not columns <= {r[1] for r in info} or [r[1] for r in info if r[5]] != [('trade_id' if table == 'trade_records' else 'event_id')]:
                raise ValueError('canonical ledger schema invalid')
        rows = [dict(r) for r in conn.execute("SELECT * FROM trade_records WHERE voided_at IS NULL ORDER BY executed_at,created_at,trade_id LIMIT 10001")] if 'trade_records' in tables else []
        events = [dict(r) for r in conn.execute("SELECT * FROM account_events WHERE voided_at IS NULL ORDER BY created_at,rowid LIMIT 20001")] if 'account_events' in tables else []
        if len(rows) > 10000 or len(events) > 20000:
            raise ValueError('source row budget exceeded')
        if len({r['trade_id'] for r in rows}) != len(rows) or len({e['event_id'] for e in events}) != len(events):
            raise ValueError('duplicate authoritative identity')
        for row in rows:
            pa._validate_trade_id(row.get('trade_id'), 0)
            formal_trade_attribution.verify_trade_record(row)
            for field in ('created_at', 'executed_at'):
                if row.get(field) is not None and not UTC_STAMP.fullmatch(row[field]):
                    raise ValueError('noncanonical stored timestamp')
            if row.get('execution_status') not in {'full', 'partial', 'not_executed'}:
                raise ValueError('invalid execution state')
        rows.sort(key=lambda r: (datetime.fromisoformat((r['executed_at'] or r['created_at']).replace('Z', '+00:00')), datetime.fromisoformat(r['created_at'].replace('Z', '+00:00')), r['trade_id']))
        for event in events:
            account_event_store.validate_event_type(event.get('event_type'))
        return rows, events
    rows, events = snapshot.read(frozen_rows, ([], []))
    return snapshot, rows, events
