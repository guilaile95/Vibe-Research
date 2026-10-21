"""Bounded offline evaluator tests, not model-performance evidence."""
import copy
import json
from pathlib import Path
import socket

import pytest
import research_quality_diagnostics as Q

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('Offline diagnostics must not connect')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


def company():
    fixture = json.loads((FIXTURES / 'company_research/US-AAPL.json').read_text(encoding="utf-8"))
    return fixture['events'][-1]['record'], fixture['bundle']


def checks(result):
    return {r['dimension']: r for r in result['checks']}


def labels(record, evidence, verdict='PASS', dimension='semantic_support'):
    return {'schema_version': 'research-quality-labels.v1', 'report_sha256': Q.digest(record),
            'evidence_sha256': Q.digest([evidence, None]), 'origin': 'HUMAN_REVIEW', 'reviewer': 'synthetic-test-reviewer',
            'checks': [{'dimension': dimension, 'verdict': verdict,
                        'quote': record['stages'][0]['summary'], 'rationale': 'Synthetic label tests only.',
                        'source_ids': [['US:AAPL', 'global_quote_ref']]}]}


def test_saved_company_contract_does_not_certify_semantic_support():
    record, bundle = company()
    result = Q.evaluate('company', record, bundle)
    assert result['overall'] == result['model_quality'] == 'NOT_EVALUATED'
    rows = checks(result)
    assert rows['citation_resolution']['status'] == 'PASS'
    assert rows['citation_resolution']['source_ids']
    for dimension in ('numeric_provenance', 'coverage', 'conflict_handling', 'semantic_support', 'noise_contrast'):
        assert rows[dimension]['status'] == 'NOT_EVALUATED'


def test_saved_comparison_contract_keeps_qualified_source_ids():
    fixture = json.loads((FIXTURES / 'company_comparison/US-AAPL--HK-00700.json').read_text(encoding="utf-8"))
    record = fixture['record']
    pair = {key: record[key] for key in ('schema_version', 'as_of', 'subjects', 'evidence', 'pair_sha256')}
    result = Q.evaluate('comparison', record, pair)
    assert checks(result)['schema']['status'] == 'PASS'
    assert {ref[0] for ref in checks(result)['citation_resolution']['source_ids']} == {'US:AAPL', 'HK:00700'}
    assert result['overall'] == 'NOT_EVALUATED'


@pytest.mark.parametrize('mutation', ['subject', 'date', 'citation', 'empty', 'units'])
def test_critical_malformed_saved_report_cannot_average_to_green(mutation):
    record, bundle = company()
    if mutation == 'subject':
        record['subject']['symbol'] = 'MSFT'
    elif mutation == 'date':
        bundle['archive_cutoff'] = '2026-02-30'
    elif mutation == 'citation':
        record['stages'][0]['evidence_ids'] = ['unknown']
    elif mutation == 'empty':
        record = {}
    elif mutation == 'units':
        annotation = labels(record, bundle, dimension='numeric_provenance')
        annotation['checks'][0].update(unit='bananas per USD', period_end='2026-09-30')
        assert Q.evaluate('company', record, bundle, labels=annotation)['overall'] == 'FAIL'
        return
    assert Q.evaluate('company', record, bundle)['overall'] == 'FAIL'


def test_empty_checks_and_unknown_support_never_pass():
    assert Q.aggregate([]) == 'NOT_EVALUATED'
    assert Q.aggregate([{'status': 'PASS'}, {'status': 'NOT_EVALUATED'}]) == 'NOT_EVALUATED'
    assert Q.aggregate([{'status': 'PASS'}] * 100 + [{'status': 'FAIL'}]) == 'FAIL'
    record, bundle = company()
    annotation = labels(record, bundle, verdict='NOT_EVALUATED')
    assert checks(Q.evaluate('company', record, bundle, labels=annotation))['semantic_support']['status'] == 'NOT_EVALUATED'
    annotation['checks'] = []
    assert checks(Q.evaluate('company', record, bundle, labels=annotation))['semantic_support']['status'] == 'NOT_EVALUATED'


@pytest.mark.parametrize('mutation', ['hash', 'quote', 'source', 'automated', 'cross_subject'])
def test_unbound_or_nonhuman_labels_fail_closed(mutation):
    record, bundle = company()
    annotation = labels(record, bundle)
    if mutation == 'hash': annotation['report_sha256'] = '0' * 64
    if mutation == 'quote': annotation['checks'][0]['quote'] = 'Not in saved report'
    if mutation == 'source': annotation['checks'][0]['source_ids'] = [['US:AAPL', 'unknown']]
    if mutation == 'automated': annotation['origin'] = 'MODEL_JUDGE'
    if mutation == 'cross_subject': annotation['checks'][0]['source_ids'] = [['US:MSFT', 'global_quote_ref']]
    assert Q.evaluate('company', record, bundle, labels=annotation)['overall'] == 'FAIL'


def test_human_fail_is_critical_but_pass_is_explicitly_subset_only():
    record, bundle = company()
    result = Q.evaluate('company', record, bundle, labels=labels(record, bundle, 'FAIL'))
    assert result['overall'] == 'FAIL'
    result = Q.evaluate('company', record, bundle, labels=labels(record, bundle))
    assert checks(result)['semantic_support']['coverage'] == 'LABELED_SUBSET_ONLY'
    assert result['overall'] == result['model_quality'] == 'NOT_EVALUATED'


def test_daily_actual_persistence_roundtrip_no_invented_sources(tmp_path, monkeypatch):
    import ai_result_service as service
    import daily_review_context
    import daily_review_basis
    monkeypatch.setattr(service.review_history, 'resolve_review_db_path', lambda: tmp_path / 'daily.sqlite3')
    review = {'schema_version': 'daily-review-v0.1', 'trade_date': '2026-07-23',
              'generated_at': '2026-07-23 15:30:00', 'data_cutoff': '2026-07-23 15:00:00',
              'status': 'partial', 'data_health': {'components': {'breadth': 'partial'}},
              'warnings': [], 'market_environment': {}}
    context = daily_review_context.render_daily_review_ai_context(review)
    basis = daily_review_basis.capture_basis(context, review)
    record = service.save_daily_review_ai(review, 'review_metadata.trade_date is the explicit research date.',
                                         {'provider': 'fixture', 'model': 'offline-stub'}, input_basis=basis)
    result = Q.evaluate('daily', record, context_text=context)
    assert checks(result)['schema']['status'] == 'PASS'
    assert checks(result)['citation_resolution']['source_ids'] == [['MARKET', 'review_metadata.trade_date']]
    assert checks(Q.evaluate('daily', record))['citation_resolution']['status'] == 'NOT_EVALUATED'
    assert Q.evaluate('daily', record, context_text=context + ' ')['overall'] == 'FAIL'
    record['trade_date'] = '2026-07-24'
    assert Q.evaluate('daily', record, context_text=context)['overall'] == 'FAIL'


def case_and_runs(origin='SAVED_PROVIDER_RESPONSE'):
    case = json.loads((FIXTURES / 'research_quality/cross_company.json').read_text(encoding="utf-8"))
    runs = []
    for role in ('baseline', 'perturbed'):
        output = 'Synthetic test of saved-response contract, not an observed model run.'
        runs.append({'case_id': case['case_id'], 'role': role, 'input_sha256': Q.digest(case[role + '_input']),
                     'output': output, 'output_sha256': Q.digest(output), 'subjects': case['subjects'],
                     'baseline_evidence_sha256': case['baseline_evidence_sha256'],
                     'run_id': role + '-test-id', 'model': {'provider': 'fixture', 'name': 'fixture'},
                     'capture_origin': origin})
    return case, *runs


@pytest.mark.parametrize('label', ['irrelevant', 'cross_company', 'conflicting', 'missing', 'prompt_injection'])
def test_noise_inputs_without_saved_responses_have_no_robustness_evidence(label):
    case = json.loads((FIXTURES / f'research_quality/{label}.json').read_text(encoding="utf-8"))
    result = Q.compare_noise(case)
    assert result['status'] == result['model_robustness'] == 'NOT_EVALUATED'


def test_noise_stub_never_proves_model_robustness():
    result = Q.compare_noise(*case_and_runs('OFFLINE_STUB'))
    assert result['reason'] == 'OFFLINE_STUB_NOT_MODEL_EVIDENCE'
    assert result['status'] == 'NOT_EVALUATED'


def test_paired_saved_contract_only_reports_observed_difference():
    result = Q.compare_noise(*case_and_runs())
    assert result['paired_comparison'] == 'OBSERVED'
    assert result['status'] == result['model_robustness'] == 'NOT_EVALUATED'


@pytest.mark.parametrize('mutation', ['stale', 'subject', 'baseline', 'model', 'same_run', 'output', 'task', 'date'])
def test_paired_control_mismatch_rejected(mutation):
    case, baseline, noisy = copy.deepcopy(case_and_runs())
    if mutation == 'stale': noisy['input_sha256'] = baseline['input_sha256']
    if mutation == 'subject': noisy['subjects'] = ['US:OTHER']
    if mutation == 'baseline': noisy['baseline_evidence_sha256'] = 'f' * 64
    if mutation == 'model': noisy['model'] = {'provider': 'other', 'name': 'other'}
    if mutation == 'same_run': noisy['run_id'] = baseline['run_id']
    if mutation == 'output': noisy['output'] += ' changed'
    if mutation == 'task': case['perturbed_input']['task'] = 'Different question'
    if mutation == 'date': case['perturbed_input']['as_of'] = '2026-10-01'
    assert Q.compare_noise(case, baseline, noisy)['status'] == 'FAIL'


def test_missing_source_dates_do_not_pass_from_archive_request_cutoff():
    record, bundle = company()
    assert checks(Q.evaluate('company', record, bundle))['time_alignment']['status'] == 'NOT_EVALUATED'


def test_future_source_receipt_date_fails_independently(monkeypatch):
    # Isolate the dimension after the saved-contract boundary, not a model test.
    monkeypatch.setattr(Q, '_adapt', lambda *args: (
        [{'subject': 'US:A', 'text': 'x', 'refs': [('US:A', 's')]}],
        {('US:A', 's'): {'status': 'AVAILABLE', 'source_as_of': '2026-10-01'}},
        '2026-09-30', ['US:A']))
    result = Q.evaluate('company', {})
    assert checks(result)['time_alignment']['status'] == 'FAIL'
    assert result['overall'] == 'FAIL'


def test_older_source_date_is_not_a_cutoff_mismatch(monkeypatch):
    monkeypatch.setattr(Q, '_adapt', lambda *args: (
        [{'subject': 'US:A', 'text': 'x', 'refs': [('US:A', 's')]}],
        {('US:A', 's'): {'status': 'AVAILABLE', 'source_as_of': '2026-06-30'}},
        '2026-09-30', ['US:A']))
    assert checks(Q.evaluate('company', {}))['time_alignment']['status'] == 'PASS'


def test_cli_saved_export_returns_incomplete_without_mutation(tmp_path):
    import subprocess
    import sys
    record, bundle = company()
    paths = [tmp_path / 'run.json', tmp_path / 'bundle.json']
    for path, value in zip(paths, [record, bundle]):
        path.write_text(json.dumps(value))
    before = [p.read_bytes() for p in paths]
    cli = Path(__file__).resolve().parents[2] / 'tools/research/research_quality_check.py'
    completed = subprocess.run([sys.executable, str(cli), 'report', '--kind', 'company',
                                '--report', str(paths[0]), '--evidence', str(paths[1])],
                               capture_output=True, text=True, check=False)
    assert completed.returncode == 3
    assert json.loads(completed.stdout)['overall'] == 'NOT_EVALUATED'
    assert [p.read_bytes() for p in paths] == before
    assert record['stages'][0]['summary'] not in completed.stdout
    paths[0].write_text('{invalid')
    completed = subprocess.run([sys.executable, str(cli), 'report', '--kind', 'company',
                                '--report', str(paths[0])], capture_output=True, text=True, check=False)
    assert completed.returncode == 2
    assert str(paths[0]) not in completed.stdout


@pytest.mark.parametrize('source_day,expected', [('2026-06-30', 'PASS'), ('2026-10-01', 'FAIL')])
def test_generic_payload_asof_is_source_date_not_archive_request(monkeypatch, source_day, expected):
    monkeypatch.setattr(Q, '_adapt', lambda *args: (
        [{'subject': 'US:A', 'text': 'x', 'refs': [('US:A', 's')]}],
        {('US:A', 's'): {'status': 'AVAILABLE', 'payload': {'as_of': source_day}}},
        '2026-09-30', ['US:A']))
    assert checks(Q.evaluate('company', {}))['time_alignment']['status'] == expected


def test_noise_case_invalid_even_without_responses():
    assert Q.compare_noise({})['status'] == 'FAIL'


@pytest.mark.parametrize('raw', ['{"x":1,"x":2}', '{"x":NaN}'])
def test_cli_strict_json_rejects_duplicate_keys_and_nonfinite(tmp_path, raw):
    import importlib.util
    cli = Path(__file__).resolve().parents[2] / 'tools/research/research_quality_check.py'
    spec = importlib.util.spec_from_file_location('quality_cli_test', cli)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / 'input.json'
    path.write_text(raw)
    with pytest.raises(ValueError):
        module.read(path)
