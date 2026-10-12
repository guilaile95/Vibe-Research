"""Explicit bounded producer + immutable FactLake replay; never called by GET.

The transport receives only a fixed allowlisted endpoint and a byte ceiling.
There is deliberately no built-in network transport, activation setting, schedule,
credentials, import path, or HTTP write endpoint in this research release.
"""
from datetime import datetime, timezone, timedelta
import os
import uuid

from data_contracts import ProviderObservation, FetchSemantics, HistoryMode, QualityStatus
from fact_lake_store import payload_sha256, open_existing_fact_lake_snapshot, FactLakeNotInitializedError, FactLakeBusyError
import public_research_contract as C
from public_research_adapters import normalize, NORMALIZER


def persist_capture(lake, raw, source, subject, captured_at, *, fixture, http_status=200):
    spec = C.identity(source, subject)
    captured_at = C.utc(captured_at)
    received = datetime.now(timezone.utc)
    if C.stamp(captured_at) > received:
        raise ValueError('future capture')
    if type(fixture) is not bool or type(http_status) is not int or not 100 <= http_status <= 599:
        raise ValueError('invalid receipt metadata')
    if type(raw) is not bytes or not 0 < len(raw) <= C.MAX_BYTES:
        raise ValueError('invalid source byte budget')
    try:
        if http_status != 200:
            raise ValueError('provider HTTP failure')
        result = normalize(raw, source, subject, captured_at, now=received)
        failed = False
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        result, failed = {'status': 'unavailable'}, True
    metadata = {'source_id': source, 'subject': subject, 'fixture': fixture, 'http_status': http_status,
                'captured_at': captured_at, 'locally_received_at': received.isoformat(timespec='microseconds').replace('+00:00', 'Z')}
    observation = ProviderObservation(
        observation_id='public-research-' + uuid.uuid4().hex, dataset_id='research_' + source + '_v1',
        provider_id=spec['provider'], provider_endpoint=spec['endpoint'], provider_symbol=subject,
        request_fingerprint=C.digest({'source_id': source, 'subject': subject}),
        source_payload_hash=payload_sha256(raw), normalizer_version=NORMALIZER,
        payload={'schema_version': C.VERSION, 'capture': metadata, 'normalization_failed': failed},
        fetch_semantics=FetchSemantics.SNAPSHOT, history_mode=HistoryMode.SNAPSHOT_ONLY, fetched_at=captured_at, trade_date=captured_at[:10],
        quality_status=QualityStatus.DEGRADED, reason_codes=('RESEARCH_ONLY_BOUNDED_PUBLIC_SOURCE',))
    saved = lake.store_observation(observation, raw, 'application/javascript' if source == 'cn_commodity_futures' else 'application/json')
    return {'observation_id': saved.stored.observation.observation_id, 'raw_payload_hash': observation.source_payload_hash,
            'fixture': fixture, 'status': result['status']}


def collect(lake, source, subject, *, transport, fixture):
    """Explicit producer entrypoint; offline tests inject a bounded byte transport.

    A future authorized runtime may supply its approved public HTTP transport.
    This function does not choose a network transport or create/open an archive.
    HTTP errors are archived verbatim with their status; no credentials accepted.
    """
    url = C.request_spec(source, subject)
    if not callable(transport) or type(fixture) is not bool:
        raise ValueError('explicit transport and fixture classification required')
    status, raw = transport(url, max_bytes=C.MAX_BYTES, timeout=20, allow_redirects=False)
    captured = datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    return persist_capture(lake, raw, source, subject, captured, fixture=fixture, http_status=status)


def replay(lake, stored, *, now=None, max_bytes=C.MAX_BYTES):
    now = now or datetime.now(timezone.utc)
    ob = stored.observation
    env = ob.payload
    if type(env) is not dict or set(env) != {'schema_version', 'capture', 'normalization_failed'} or env['schema_version'] != C.VERSION or ob.normalizer_version != NORMALIZER:
        raise ValueError('unsupported public research receipt')
    m = env['capture']
    if type(m) is not dict or set(m) != {'source_id', 'subject', 'fixture', 'http_status', 'captured_at', 'locally_received_at'}:
        raise ValueError('invalid receipt metadata')
    spec = C.identity(m['source_id'], m['subject'])
    if (type(m['fixture']) is not bool or type(m['http_status']) is not int or not 100 <= m['http_status'] <= 599
        or type(env['normalization_failed']) is not bool
        or ob.dataset_id != 'research_' + m['source_id'] + '_v1' or ob.provider_id != spec['provider']
        or ob.provider_endpoint != spec['endpoint'] or ob.provider_symbol != m['subject']
        or ob.request_fingerprint != C.digest({'source_id': m['source_id'], 'subject': m['subject']})
        or ob.fetched_at != C.utc(m['captured_at']) or ob.trade_date != C.utc(m['captured_at'])[:10]
        or not C.stamp(m['captured_at']) <= C.stamp(m['locally_received_at']) <= now):
        raise ValueError('receipt identity mismatch')
    if type(max_bytes) is not int or not 1 <= max_bytes <= C.MAX_BYTES:
        raise ValueError('invalid remaining replay budget')
    raw = lake.read_payload(ob.observation_id, max_payload_bytes=max_bytes)
    if type(raw) is not bytes or not 0 < len(raw) <= C.MAX_BYTES or payload_sha256(raw) != ob.source_payload_hash:
        raise ValueError('raw payload mismatch')
    if env['normalization_failed'] or m['http_status'] != 200:
        result = {'schema_version': C.VERSION, 'source_id': m['source_id'], 'subject': m['subject'], 'label': spec['label'],
                  'status': 'unavailable', 'rows': [], 'reason_codes': ['HTTP_OR_NORMALIZATION_FAILED'], 'guard': spec['guard'],
                  'captured_at': m['captured_at'], 'source_url': C.request_spec(m['source_id'], m['subject']),
                  'license_status': 'PROVIDER_TERMS_NOT_VERIFIED'}
    else:
        result = normalize(raw, m['source_id'], m['subject'], m['captured_at'], now=now)
    return {**result, 'fixture': m['fixture'], 'raw_bytes': len(raw), 'evidence': {
        'observation_id': ob.observation_id, 'raw_payload_hash': ob.source_payload_hash,
        'locally_received_at': m['locally_received_at'], 'normalizer_version': ob.normalizer_version,
        'point_in_time_claim': 'NONE', 'provider_revision': None}}


def query_source(source):
    if source not in C.SOURCES:
        raise ValueError('unsupported public source')
    spec = C.SOURCES[source]
    result = {'schema_version': C.VERSION, 'source_id': source, 'label': spec['label'], 'status': 'missing',
              'reason_codes': ['ARCHIVE_NOT_CONNECTED'], 'blocks': [], 'missing_subjects': list(spec['subjects']),
              'guard': spec['guard'], 'ingestion_enabled': False, 'schedule_enabled': False,
              'research_only': True, 'fixture': False, 'selection_mode': 'CURRENT_ARCHIVED_POSTHOC', 'archive_window_days': 366,
              'archive_date_semantics': 'UTC capture date; not source publication or economic date',
              'message': '尚无已归档公开数据；读取不会联网或启动采集。'}
    root = os.environ.get('VR_FACT_LAKE_ROOT', '').strip()
    if not root:
        return result
    try:
        lake = open_existing_fact_lake_snapshot(root)
        now = datetime.now(timezone.utc)
        receipts = lake.list_observations(dataset_id='research_' + source + '_v1',
            start_trade_date=(now.date() - timedelta(days=366)).isoformat(), end_trade_date=now.date().isoformat(),
            limit=128, max_payload_bytes=16 * 1024 * 1024)
        if len(receipts) >= 128:
            raise ValueError('receipt count budget exceeded')
        chosen, total_bytes = {}, 0
        now = datetime.now(timezone.utc)
        # Validate every receipt before selection; no poisoned latest-record fallback.
        for stored in receipts:
            item = replay(lake, stored, now=now, max_bytes=min(C.MAX_BYTES, 16 * 1024 * 1024 - total_bytes))
            total_bytes += item['raw_bytes']
            if total_bytes > 16 * 1024 * 1024:
                raise ValueError('aggregate raw budget exceeded')
            key, rank = item['subject'], C.stamp(item['captured_at'])
            old = chosen.get(key)
            if old and rank == C.stamp(old['captured_at']) and (item['evidence']['raw_payload_hash'], item['fixture'], item['status']) != (old['evidence']['raw_payload_hash'], old['fixture'], old['status']):
                raise ValueError('ambiguous same-time receipt')
            if old is None or rank > C.stamp(old['captured_at']):
                chosen[key] = item
        blocks = [chosen[s] for s in spec['subjects'] if s in chosen]
        fixtures = {b['fixture'] for b in blocks}
        if len(fixtures) > 1:
            raise ValueError('mixed synthetic and acquired receipts')
        lake.assert_unchanged()
        missing = [s for s in spec['subjects'] if s not in chosen]
        result.update(blocks=blocks, missing_subjects=missing, fixture=True in fixtures,
                      status='missing' if not blocks else 'unavailable' if all(b['status'] == 'unavailable' for b in blocks) else 'partial' if missing or any(b['status'] != 'normal' for b in blocks) else 'normal',
                      reason_codes=['SUBJECT_COVERAGE_MISSING'] if missing else [],
                      message='合成案例：仅离线软件验证，非真实市场验收' if True in fixtures else '当前归档的事后研究，不证明历史当时已知')
    except FactLakeNotInitializedError:
        result.update(status='unavailable', reason_codes=['ARCHIVE_NOT_INITIALIZED'])
    except FactLakeBusyError:
        result.update(status='unavailable', reason_codes=['ARCHIVE_BUSY'])
    except Exception:
        result.update(status='unavailable', reason_codes=['ARCHIVE_VALIDATION_FAILED'], message='归档身份、时间或完整性校验失败，未展示数据')
    return result
