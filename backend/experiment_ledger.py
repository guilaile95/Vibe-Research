"""Explicit compact experiment receipts; existing evaluators remain calculation authority."""
import hashlib
import json
import math
from datetime import datetime, timezone
from uuid import UUID, uuid4

import observation_workflow_store as store

VERSION = 'experiment-record.v1'
LIMIT = 500
STATUSES = {'PENDING', 'RUNNING', 'COMPLETED', 'INCOMPLETE', 'FAILED', 'CANCELLED'}


def digest(value):
    return hashlib.sha256(store.encode(value).encode()).hexdigest()


def contract(kind, body):
    if kind == 'signal':
        from historical_signal_validation_router import HistoricalSignalValidationRequest
        import historical_signal_validation as evaluator
        request = HistoricalSignalValidationRequest.model_validate(body).model_dump()
        evaluator.signal_definition(request['signal_id'])
        request['codes'] = sorted(request['codes'])
        return request, evaluator.SIGNAL_VERSION
    if kind == 'rolling-signal':
        from rolling_signal_validation import RollingSignalValidationRequest, VERSION
        request = RollingSignalValidationRequest.model_validate(body).model_dump(mode='json')
        request['codes'] = sorted(request['codes'])
        return request, VERSION
    if kind == 'factor':
        from factor_validation_router import FactorValidationRequest
        import factor_validation as evaluator
        request = FactorValidationRequest.model_validate(body).model_dump()
        if request['factor_id'] not in {x['factor_id'] for x in evaluator.FACTOR_REGISTRY}:
            raise ValueError('unknown factor')
        return request, evaluator.SCHEMA_VERSION
    from research_analytics_contract import SimulationRequest, ScenarioRequest, PerformanceRequest, LedgerPerformanceRequest
    from research_cost_comparison import CostComparisonRequest
    from research_analytics import VERSION as rules
    models = {'simulation': SimulationRequest, 'scenario': ScenarioRequest, 'performance': PerformanceRequest,
              'ledger-performance': LedgerPerformanceRequest, 'cost-comparison': CostComparisonRequest}
    if kind not in models:
        raise ValueError('unknown experiment kind')
    return models[kind].model_validate(body).model_dump(mode='json'), rules


def _rows(conn):
    table = conn.execute("SELECT type FROM sqlite_master WHERE name='experiment_records'").fetchone()
    if table is None:
        return []
    if table != ('table',):
        raise store.StoreError('实验归档结构无效')
    info = conn.execute('PRAGMA table_info(experiment_records)').fetchall()
    if {row[1] for row in info} != {'id', 'payload'} or [row[1] for row in info if row[5]] != ['id']:
        raise store.StoreError('实验归档结构无效')
    rows = conn.execute('SELECT id,payload FROM experiment_records ORDER BY rowid DESC LIMIT 501').fetchall()
    if len(rows) > LIMIT:
        raise store.StoreError('实验记录超出上限')
    out = []
    if len({row[0] for row in rows}) != len(rows):
        raise store.StoreError('实验身份重复')
    for identity, payload in rows:
        def unique(pairs):
            out = {}
            for key, item in pairs:
                if key in out:
                    raise ValueError('duplicate manifest field')
                out[key] = item
            return out
        try:
            if len(payload.encode()) > 65536:
                raise ValueError('oversized manifest')
            value = json.loads(payload, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
            validate(value, identity)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise store.StoreError('实验记录不可核对') from None
        out.append(value)
    return out


def records():
    with store.read() as conn:
        return _rows(conn)


def _find(conn, identity):
    for value in _rows(conn):
        if value['id'] == identity:
            return value
    raise LookupError('experiment absent')


def validate(value, identity):
    if not isinstance(value, dict) or value.get('schema_version') != VERSION or value.get('id') != identity or value.get('status') not in STATUSES:
        raise ValueError('invalid manifest')
    UUID(identity)
    datetime.fromisoformat(value['created_at'])
    if value['kind'] not in {'signal', 'rolling-signal', 'factor', 'simulation', 'scenario', 'performance', 'ledger-performance', 'cost-comparison'}:
        raise ValueError('invalid experiment kind')
    expected = {'schema_version', 'id', 'created_at', 'kind', 'subject', 'rules_version', 'sample', 'window', 'benchmark', 'request_identity', 'input_identity', 'snapshot', 'receipt', 'status', 'metrics', 'report_status', 'scope', 'currency', 'research_only', 'historical_validity', 'manifest_digest'}
    if set(value) != expected or value['manifest_digest'] != digest({k: v for k, v in value.items() if k != 'manifest_digest'}):
        raise ValueError('manifest integrity mismatch')
    if value['research_only'] is not True or value['historical_validity'] != 'NOT_PROVEN':
        raise ValueError('invalid authority')
    if value['receipt'] not in {'MISSING', 'SNAPSHOT', 'ARTIFACT', 'INPUT_FINGERPRINT'}:
        raise ValueError('invalid receipt')
    if not isinstance(value['metrics'], dict) or len(value['metrics']) > 50:
        raise ValueError('invalid metrics')
    for key, item in value['metrics'].items():
        if len(key) > 100 or item is not None and (isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)):
            raise ValueError('invalid metric')
    for key in ['request_identity', 'input_identity', 'snapshot']:
        item = value[key]
        if item is not None and (not isinstance(item, str) or len(item) != 64 or any(c not in '0123456789abcdef' for c in item)):
            raise ValueError('invalid identity')


def seal(value):
    value['manifest_digest'] = digest({k: v for k, v in value.items() if k != 'manifest_digest'})
    validate(value, value['id'])
    encoded = store.encode(value)
    if len(encoded.encode()) > 65536:
        raise ValueError('experiment manifest too large')
    return encoded


def _update(conn, value):
    encoded = seal(value)
    if len(encoded.encode()) > 65536:
        raise ValueError('experiment manifest too large')
    conn.execute('UPDATE experiment_records SET payload=? WHERE id=?', (encoded, value['id']))


def create(kind, body):
    request, rules = contract(kind, body)
    instruments = request.get('instruments') or request.get('securities', [])
    sample = request.get('codes') or sorted(x['code'] for x in instruments) or request.get('scope') or 'EXPLICIT_INPUT'
    if kind == 'factor':
        sample = 'RDP_OBSERVED_CROSS_SECTION'
    sessions = request.get('sessions') or [x['date'] for x in request.get('valuations', [])]
    window = {'from': request.get('date_from') or (sessions[0] if sessions else None),
              'to': request.get('date_to') or (sessions[-1] if sessions else None),
              'forward': request.get('forward_windows') or ([5, 20] if kind == 'signal' else None)}
    if kind == 'rolling-signal':
        window = {key: request[key] for key in ('selection_from', 'selection_to', 'holdout_from', 'holdout_to', 'rolling_calendar_days', 'parameter_preset', 'frozen_parameter')}
    benchmark = request.get('benchmark_code') or (request.get('benchmark') or {}).get('code')
    value = {'schema_version': VERSION, 'id': str(uuid4()), 'created_at': datetime.now(timezone.utc).isoformat(),
             'kind': kind, 'subject': request.get('signal_id') or request.get('factor_id') or (request.get('strategy') or {}).get('name') or kind,
             'rules_version': rules, 'sample': sample, 'window': window, 'benchmark': benchmark,
             'request_identity': digest({'kind': kind, 'rules': rules, 'request': request}),
             'input_identity': None, 'snapshot': None, 'receipt': 'MISSING', 'status': 'PENDING',
             'metrics': {}, 'report_status': None, 'scope': None, 'currency': request.get('currency'),
             'research_only': True, 'historical_validity': 'NOT_PROVEN'}
    with store.write() as conn:
        if len(_rows(conn)) >= LIMIT:
            raise ValueError('experiment ledger full; existing history retained')
        conn.execute('INSERT INTO experiment_records(id,payload) VALUES(?,?)', (value['id'], seal(value)))
    return value


def cancel(identity):
    with store.write() as conn:
        value = _find(conn, identity)
        if value['status'] in {'PENDING', 'RUNNING'}:
            value['status'] = 'CANCELLED'
            _update(conn, value)
        return value


def _metrics(report, kind):
    metrics = {}
    def add(key, value):
        if value is None or isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            metrics[key] = value
    if kind in {'signal', 'factor'}:
        for window, result in report.get('results', {}).items():
            for key in (['mean_ic', 'median_ic', 'mean_high_minus_low_spread', 'pair_count_total'] if kind == 'factor' else ['events_evaluated', 'failures']):
                add(f'{window}.{key}', result.get(key))
            if kind == 'signal':
                for key in ['signal_return', 'benchmark_return', 'excess_return']:
                    add(f'{window}.{key}.mean', (result.get(key) or {}).get('mean'))
    else:
        for key, metric in report.get('metrics', {}).items():
            add(key, metric.get('value') if metric.get('status') == 'SUPPORTED' else None)
        for key in ['twr', 'total_return']:
            if key in report:
                add(key, report[key])
    return metrics


def execute(identity, kind, body, calculate):
    """Wrap an existing evaluator only on explicit recorded execution. No job engine."""
    if identity is None:
        return calculate()
    request, rules = contract(kind, body)
    with store.write() as conn:
        value = _find(conn, identity)
        if value['status'] != 'PENDING' or value['kind'] != kind or value['request_identity'] != digest({'kind': kind, 'rules': rules, 'request': request}):
            raise ValueError('record does not match pending request')
        value['status'] = 'RUNNING'
        _update(conn, value)
    try:
        report = calculate()
        source = report.get('source') or report.get('data') or {}
        snapshot = source.get('snapshot_id') or source.get('artifact_sha256')
        fingerprint = report.get('input_fingerprint')
        valid_hash = lambda x: isinstance(x, str) and len(x) == 64 and all(c in '0123456789abcdef' for c in x)
        receipt = ('SNAPSHOT' if valid_hash(source.get('snapshot_id')) else 'ARTIFACT' if valid_hash(snapshot) else 'MISSING') if kind in {'signal', 'factor', 'rolling-signal'} else ('INPUT_FINGERPRINT' if valid_hash(fingerprint) else 'MISSING')
        # Receipt comes solely from the evaluator that read these bytes, never a later latest-pointer lookup.
        changes = {'report_status': report.get('status'), 'scope': report.get('scope', kind),
                   'snapshot': snapshot if valid_hash(snapshot) else None, 'receipt': receipt,
                   'input_identity': fingerprint if valid_hash(fingerprint) else digest({'request': value['request_identity'], 'snapshot': snapshot}) if receipt != 'MISSING' else None,
                   'metrics': _metrics(report, kind), 'currency': report.get('currency', value['currency']),
                   'status': 'COMPLETED' if report.get('status') in {'normal', 'CALCULATED'} else 'INCOMPLETE'}
        with store.write() as conn:
            current = _find(conn, identity)
            if current['status'] == 'RUNNING':
                current.update(changes)
                _update(conn, current)
        return report
    except Exception:
        with store.write() as conn:
            current = _find(conn, identity)
            if current['status'] == 'RUNNING':
                current['status'] = 'FAILED'
                _update(conn, current)
        raise


def metric_unit(record, key):
    if record['kind'] == 'rolling-signal':
        return 'count' if key in {'trial_count', 'segment_count', 'evaluated_count', 'purged_count'} else 'UNKNOWN'
    if record['kind'] == 'signal':
        return 'percent' if key.endswith('.mean') else 'count'
    if record['kind'] == 'factor':
        return 'count' if key.endswith('pair_count_total') else 'fraction' if key.endswith('spread') else 'rank_correlation'
    if key in {'final_value'}:
        return record['currency'] or 'UNKNOWN'
    if key in {'trade_count', 'max_consecutive_loss'}:
        return 'count'
    if key == 'avg_holding_days':
        return 'stored_sessions'
    if key in {'twr', 'total_return', 'annual_return', 'max_drawdown', 'win_rate', 'benchmark_return', 'excess_return', 'tracking_error', 'avg_turnover', 'total_turnover'}:
        return 'fraction'
    if key in {'sharpe', 'calmar', 'sortino', 'profit_loss_ratio', 'profit_factor', 'information_ratio', 'benchmark_beta'}:
        return 'ratio'
    return 'UNKNOWN'


def compare(left, right):
    fields = ['kind', 'subject', 'rules_version', 'sample', 'window', 'benchmark', 'snapshot', 'receipt', 'request_identity', 'input_identity', 'scope', 'currency']
    changes = [field for field in fields if left[field] != right[field]]
    reasons = list(changes)
    if left['status'] != 'COMPLETED' or right['status'] != 'COMPLETED':
        reasons.append('RUN_NOT_COMPLETED')
    if left['receipt'] == 'MISSING' or right['receipt'] == 'MISSING' or not left['input_identity'] or not right['input_identity']:
        reasons.append('MISSING_RECEIPT')
    metrics = []
    for key in sorted(left['metrics'].keys() | right['metrics'].keys()):
        a, b = left['metrics'].get(key), right['metrics'].get(key)
        comparable = not reasons and a is not None and b is not None
        metrics.append({'name': key, 'left': a, 'right': b, 'status': 'COMPARABLE' if comparable else 'INCOMPARABLE',
                        'delta': b - a if comparable else None, 'left_unit': metric_unit(left, key), 'right_unit': metric_unit(right, key)})
    return {'left': left, 'right': right, 'changes': changes, 'reasons': reasons, 'metrics': metrics,
            'same_input': bool(left['input_identity']) and left['input_identity'] == right['input_identity'],
            'research_only': True, 'historical_validity': 'NOT_PROVEN', 'formal_writes': 0}
