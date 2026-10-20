"""Offline, read-only research diagnostics. PASS means only the named check passed.

No model, provider, database writes or judge. Semantic conclusions require explicit,
hash-bound human labels. Existing report validators retain identity ownership.
"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import re

SCHEMA = 'research-quality-diagnostics.v1'
DIMENSIONS = ('schema', 'citation_resolution', 'company_alignment', 'time_alignment',
              'numeric_provenance', 'coverage', 'conflict_handling', 'semantic_support', 'noise_contrast')
SEMANTIC = ('coverage', 'conflict_handling', 'semantic_support')
MAX_BYTES = 4 * 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def aggregate(checks):
    """Never average a failure or missing evidence into green."""
    statuses = [c['status'] for c in checks]
    if 'FAIL' in statuses:
        return 'FAIL'
    if not statuses or 'NOT_EVALUATED' in statuses:
        return 'NOT_EVALUATED'
    return 'PASS' if all(s == 'PASS' for s in statuses) else 'NOT_EVALUATED'


def _check(name, status='NOT_EVALUATED', reason='NO_EVALUABLE_EVIDENCE', **detail):
    return {'dimension': name, 'status': status, 'reason': reason, **detail}


def _subject(value):
    return f"{value['market']}:{value['symbol']}"


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('DATE_INVALID')
    date.fromisoformat(value)
    return value


def _adapt(kind, record, evidence, context_text):
    """Use actual persisted contracts, not a new parallel report format."""
    if kind == 'company':
        import company_research as company
        company.validate_bundle(evidence)
        company.validate_record(record, {'owner': '0' * 32, 'id': record['run_id'],
            'bundle_id': record['bundle_id'], 'status': record['status']}, evidence)
        subject = _subject(record['subject'])
        sources = {(subject, s['evidence_id']): s for s in evidence['sources']}
        parts = [{'subject': subject, 'text': s['summary'], 'refs': [(subject, ref) for ref in s['evidence_ids']]}
                 for s in record['stages']]
        return parts, sources, evidence.get('archive_cutoff'), [subject]
    if kind == 'comparison':
        import company_comparison as comparison
        comparison.validate_record(record, {'owner': '0' * 32, 'id': record['run_id'],
            'pair_hash': record['pair_sha256'], 'status': record['status']}, evidence)
        subjects = [_subject(s) for s in record['subjects']]
        sources = {(_subject(s), r['evidence_id']): r for s in record['evidence'] for r in s['sources']}
        parts = [{'subject': _subject(s), 'text': s['summary'],
                  'refs': [(_subject(r), r['evidence_id']) for r in s['citations']]}
                 for s in (record.get('output') or {}).get('subjects', [])]
        return parts, sources, record['as_of'], subjects
    if kind == 'daily':
        import ai_result_service as service
        try:
            service._validate_restored_record(record, 'daily_review_ai')
        except service.AiResultCorruptedError:
            raise ValueError('DAILY_SAVED_CONTRACT_INVALID') from None
        text = record['payload']['markdown']
        sources = {}
        if context_text is not None:
            basis = record['payload'].get('input_basis', {})
            if hashlib.sha256(context_text.encode()).hexdigest() != basis.get('context_sha256'):
                raise ValueError('DAILY_CONTEXT_BINDING_MISMATCH')
            context = json.loads(context_text)
            if context['review_metadata']['trade_date'] != record['trade_date']:
                raise ValueError('DAILY_CONTEXT_DATE_MISMATCH')
            def walk(node, path=''):
                if isinstance(node, dict):
                    for key, value in node.items():
                        walk(value, f'{path}.{key}' if path else key)
                elif not isinstance(node, list) and node is not None:
                    sources[('MARKET', path)] = {'status': 'AVAILABLE', 'payload': node,
                                               'source_as_of': record['payload']['source_data_cutoff']}
            walk(context)
        # Daily citations are exact context paths present in the text. No guessed IDs.
        refs = [('MARKET', p) for _, p in sources if re.search(r'(?<![\w.])' + re.escape(p) + r'(?![\w.])', text)]
        return [{'subject': 'MARKET', 'text': text, 'refs': refs}], sources, record['trade_date'], ['MARKET']
    raise ValueError('REPORT_KIND_INVALID')


def evaluate(kind, record, evidence=None, *, context_text=None, labels=None):
    checks = {d: _check(d) for d in DIMENSIONS}
    result = {'schema_version': SCHEMA, 'report_kind': kind,
              'scope': 'OFFLINE_STRUCTURAL_AND_EXPLICIT_HUMAN_LABELS_ONLY',
              'model_quality': 'NOT_EVALUATED', 'checks': [], 'overall': 'NOT_EVALUATED'}
    try:
        encoded = json.dumps([record, evidence, labels, context_text], allow_nan=False)
        if len(encoded.encode()) > MAX_BYTES:
            raise ValueError('INPUT_TOO_LARGE')
        result['report_sha256'] = digest(record)
        result['evidence_sha256'] = digest([evidence, context_text])
        parts, sources, cutoff, subjects = _adapt(kind, record, evidence, context_text)
        checks['schema'] = _check('schema', 'PASS', 'EXISTING_SAVED_CONTRACT_VALID')
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        checks['schema'] = _check('schema', 'FAIL', 'SAVED_CONTRACT_OR_INPUT_INVALID')
        result['checks'] = list(checks.values())
        result['overall'] = aggregate(result['checks'])
        return result
    refs = [r for p in parts for r in p['refs']]
    if refs:
        valid = all(r in sources and sources[r]['status'] == 'AVAILABLE' for r in refs)
        checks['citation_resolution'] = _check('citation_resolution', 'PASS' if valid else 'FAIL',
            'IDS_RESOLVE_ONLY_NOT_SUPPORT', citation_count=len(refs), source_ids=[list(r) for r in sorted(set(refs))])
        aligned = all(p['subject'] in subjects and all(r[0] == p['subject'] for r in p['refs']) for p in parts)
        checks['company_alignment'] = _check('company_alignment', 'PASS' if aligned else 'FAIL', 'EXPLICIT_IDENTITY_ONLY')
    if cutoff:
        try:
            _day(cutoff)
            temporal_count = 0
            available = [s for s in sources.values() if s['status'] == 'AVAILABLE']
            for source in available:
                payload = source.get('payload')
                dates = [source.get('source_as_of')]
                if isinstance(payload, dict):
                    # Request-cutoff equality does not establish publication time.
                    if payload.get('schema_version') == 'company-public-source.v1':
                        if payload.get('as_of') is not None and _day(payload['as_of']) != cutoff:
                            raise ValueError('CUTOFF_MISMATCH')
                    else:
                        dates.append(payload.get('as_of'))
                    dates.append(payload.get('source_time'))
                    block = payload.get('block')
                    if isinstance(block, dict):
                        dates.append(block.get('source_publication_time'))
                known = [v for v in dates if v is not None]
                for value in known:
                    if not isinstance(value, str):
                        raise ValueError('SOURCE_DATE_INVALID')
                    _day(value[:10])
                    if len(value) > 10:
                        datetime.fromisoformat(value.replace('Z', '+00:00'))
                    if value[:10] > cutoff:
                        raise ValueError('SOURCE_AFTER_CUTOFF')
                temporal_count += bool(known)
            complete = bool(available) and temporal_count == len(available)
            checks['time_alignment'] = _check('time_alignment', 'PASS' if complete else 'NOT_EVALUATED',
                'DECLARED_SOURCE_DATES_NOT_AFTER_CUTOFF_NOT_PIT' if complete else 'SOURCE_DATES_MISSING',
                dated_source_count=temporal_count, available_source_count=len(available))
        except (ValueError, TypeError):
            checks['time_alignment'] = _check('time_alignment', 'FAIL', 'DECLARED_DATE_OR_CUTOFF_MISMATCH')
    if labels is not None:
        _apply_labels(checks, labels, result, parts, sources)
    result['checks'] = list(checks.values())
    result['overall'] = aggregate(result['checks'])
    return result


def _apply_labels(checks, labels, result, parts, sources):
    """Sidecar labels are supplied by a human, never inferred from citation presence."""
    try:
        if (labels['schema_version'] != 'research-quality-labels.v1'
                or labels['report_sha256'] != result['report_sha256']
                or labels['evidence_sha256'] != result['evidence_sha256']
                or not isinstance(labels['reviewer'], str) or not labels['reviewer'].strip()
                or labels['origin'] != 'HUMAN_REVIEW'
                or not isinstance(labels['checks'], list) or len(labels['checks']) > 100):
            raise ValueError('LABEL_BINDING_INVALID')
        groups = {}
        for label in labels['checks']:
            dimension = label['dimension']
            if dimension not in (*SEMANTIC, 'numeric_provenance'):
                raise ValueError('LABEL_DIMENSION_INVALID')
            if label['verdict'] not in ('PASS', 'FAIL', 'NOT_EVALUATED'):
                raise ValueError('LABEL_VERDICT_INVALID')
            if not isinstance(label['rationale'], str) or not label['rationale'].strip():
                raise ValueError('LABEL_RATIONALE_REQUIRED')
            span = label['quote']
            if not isinstance(span, str) or not span or not any(span in p['text'] for p in parts):
                raise ValueError('LABEL_QUOTE_NOT_IN_REPORT')
            ids = label['source_ids']
            if not isinstance(ids, list) or not ids or any(not isinstance(r, list) or len(r) != 2 or not all(isinstance(v, str) for v in r)
                    or tuple(r) not in sources or sources[tuple(r)]['status'] != 'AVAILABLE' for r in ids):
                raise ValueError('LABEL_SOURCE_INVALID')
            if dimension == 'numeric_provenance':
                # Human must state the claimed unit/period, not merely label a number.
                if label.get('unit') not in ('CNY', 'USD', 'HKD', 'percent', 'ratio', 'shares', 'count'):
                    raise ValueError('NUMERIC_UNIT_INVALID')
                _day(label['period_end'])
            if not any(span in p['text'] and all(r[0] == p['subject'] for r in ids) for p in parts):
                raise ValueError('LABEL_CROSS_SUBJECT')
            groups.setdefault(dimension, []).append({'status': label['verdict']})
        for dimension, rows in groups.items():
            checks[dimension] = _check(dimension, aggregate(rows), 'HUMAN_LABELED_QUOTES_ONLY',
                                      labeled_count=len(rows), coverage='LABELED_SUBSET_ONLY')
    except (ValueError, KeyError, TypeError):
        checks['schema'] = _check('schema', 'FAIL', 'LABEL_CONTRACT_OR_BINDING_INVALID')


def compare_noise(case, baseline=None, perturbed=None):
    """Compare actual saved paired responses; no canned response is robustness evidence.

Runs attest capture provenance. Hashes bind exact input/output bytes, not the
truth of the attestation. Report only observed differences, never robustness PASS.
"""
    result = _check('noise_contrast', reason='NO_PAIRED_SAVED_RESPONSES', model_robustness='NOT_EVALUATED')
    try:
        if len(json.dumps([case, baseline, perturbed], allow_nan=False).encode()) > MAX_BYTES:
            raise ValueError('INPUT_TOO_LARGE')
        if (case['schema_version'] != 'research-noise-case.v1' or case['fixture_only'] is not True
                or case['noise_label'] not in ('irrelevant', 'cross_company', 'conflicting', 'missing', 'prompt_injection')):
            raise ValueError('NOISE_CASE_INVALID')
        clean, noisy = case['baseline_input'], case['perturbed_input']
        if (not case['subjects'] or clean['subjects'] != case['subjects'] or noisy['subjects'] != case['subjects']
                or clean['task'] != noisy['task'] or not clean['task']
                or clean['as_of'] != noisy['as_of']
                or digest(clean['evidence']) != case['baseline_evidence_sha256']
                or clean == noisy):
            raise ValueError('UNCONTROLLED_PAIRED_INPUTS')
        _day(clean['as_of'])
        for value in (clean, noisy):
            if (set(value) != {'subjects', 'task', 'as_of', 'evidence'}
                    or not isinstance(value['evidence'], list)
                    or not isinstance(value['task'], str)
                    or not isinstance(value['subjects'], list)
                    or not all(isinstance(s, str) and s for s in value['subjects'])):
                raise ValueError('NOISE_INPUT_INVALID')
        if baseline is None or perturbed is None:
            return result
        for role, run in (('baseline', baseline), ('perturbed', perturbed)):
            model = run['model']
            if (not isinstance(model, dict) or set(model) != {'provider', 'name'}
                    or not all(isinstance(v, str) and v.strip() for v in model.values())):
                raise ValueError('MODEL_METADATA_INVALID')
            if (run['case_id'] != case['case_id'] or run['role'] != role
                    or run['input_sha256'] != digest(case[role + '_input'])
                    or run['output_sha256'] != digest(run['output'])
                    or run['subjects'] != case['subjects']
                    or run['baseline_evidence_sha256'] != case['baseline_evidence_sha256']
                    or not isinstance(run['run_id'], str) or not run['run_id']
                    or not isinstance(run['output'], str) or not run['output']
                    or run['capture_origin'] not in ('SAVED_PROVIDER_RESPONSE', 'OFFLINE_STUB')):
                raise ValueError('PAIR_BINDING_INVALID')
        if baseline['run_id'] == perturbed['run_id'] or baseline['model'] != perturbed['model']:
            raise ValueError('PAIR_CONTROL_MISMATCH')
        if baseline['capture_origin'] != 'SAVED_PROVIDER_RESPONSE' or perturbed['capture_origin'] != 'SAVED_PROVIDER_RESPONSE':
            return _check('noise_contrast', reason='OFFLINE_STUB_NOT_MODEL_EVIDENCE', model_robustness='NOT_EVALUATED')
        return _check('noise_contrast', reason='PAIRED_OUTPUT_DIFF_ONLY_NO_SEMANTIC_GOLD',
                      paired_comparison='OBSERVED', model_robustness='NOT_EVALUATED',
                      identical_output=baseline['output'] == perturbed['output'],
                      baseline_chars=len(baseline['output']), perturbed_chars=len(perturbed['output']))
    except (ValueError, KeyError, TypeError, RecursionError):
        return _check('noise_contrast', 'FAIL', 'PAIR_CONTRACT_OR_BINDING_INVALID', model_robustness='NOT_EVALUATED')
