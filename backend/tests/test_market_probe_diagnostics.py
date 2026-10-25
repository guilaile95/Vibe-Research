"""Offline checks for the opt-in live probe; never contact a provider."""
import http.client
import json
import importlib.util
import os
import socket
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import requests
_SCRIPT = Path(__file__).resolve().parents[2] / 'tools' / 'performance' / 'probe_market_refresh.py'
_SPEC = importlib.util.spec_from_file_location('market_refresh_probe', _SCRIPT)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def request(page=1):
    return requests.Request('GET', 'https://push2.eastmoney.com/api/qt/clist/get',
                            params={'pn': page, 'pz': 500, 'token': 'DO-NOT-LOG'}).prepare()


def response(rows, total=3):
    return SimpleNamespace(content=b'{}', status_code=200,
                           json=lambda: {'data': {'total': total, 'diff': rows}})


def row(code):
    return {'f12': code, 'f13': 1, 'f14': 'PRIVATE-TEXT', 'f2': 123.45}


class ProbeDiagnosticsTests(unittest.TestCase):
    def test_count_evidence_rejects_non_integer_or_unbounded_values(self):
        for value in (True, -1, 1.0, '1.0', '１２', 'SECRET', 1_000_001, '1000001'):
            self.assertIsNone(probe._count(value))
        self.assertEqual(probe._count('500'), 500)

    def test_non_allowlisted_endpoint_never_records_query_or_userinfo(self):
        value = probe._request_identity(SimpleNamespace(url='https://user:SECRET@example.invalid/?pn=3&token=SECRET'))
        self.assertEqual(value, {'host': 'example.invalid'})

    def test_error_chain_distinguishes_dns_without_messages_or_cycles(self):
        dns = socket.gaierror('DO-NOT-LOG')
        error = requests.ConnectionError('SECRET', dns)
        error.__cause__ = dns
        dns.__context__ = error
        self.assertEqual(probe._error_details(error)['error_chain_types'], ['ConnectionError', 'gaierror'])

    def test_exception_categories_are_safe_observations_not_root_causes(self):
        cases = [
            (socket.gaierror(-2, 'SECRET-DNS'), 'dns', [-2]),
            (requests.exceptions.ProxyError('SECRET-PROXY'), 'proxy', []),
            (requests.exceptions.SSLError('SECRET-TLS'), 'tls', []),
            (http.client.RemoteDisconnected('SECRET-REMOTE'), 'remote_disconnect', []),
            (PermissionError(13, 'SECRET-PATH'), 'permission', [13]),
            (requests.ConnectionError('SECRET-UNKNOWN'), 'unknown', []),
        ]
        for cause, category, errnos in cases:
            with self.subTest(category=category):
                wrapper = requests.ConnectionError('SECRET-URL')
                wrapper.__cause__ = cause
                details = probe._error_details(wrapper)
                self.assertEqual(details['error_categories'], [category])
                self.assertEqual(details['error_chain_errnos'], errnos)
                self.assertNotIn('SECRET', json.dumps(details))

    def test_exception_diagnostics_bound_cycles_depth_and_errno(self):
        root = current = requests.ConnectionError('PRIVATE')
        for _ in range(40):
            cause = OSError(10**100, 'PRIVATE')
            current.__cause__ = cause
            current = cause
        current.__cause__ = root
        details = probe._error_details(root)
        self.assertEqual(details['error_chain_errnos'], [])
        self.assertEqual(details['error_categories'], ['unknown'])
        self.assertNotIn('PRIVATE', json.dumps(details))

    def test_counts_keep_page_size_total_and_unique_coverage_separate(self):
        diagnostics = probe._PageDiagnostics()
        first = diagnostics.observe(response([row('600001'), row('600002')]), probe._request_identity(request()))
        second = diagnostics.observe(response({'0': row('600002'), '1': row('600003')}), probe._request_identity(request(2)))
        self.assertEqual(first['provider_total'], 3)
        self.assertEqual(first['raw_rows'], 2)
        self.assertEqual(second['page_unique_identities'], 2)
        self.assertEqual(second['previously_observed_identities'], 1)
        self.assertEqual(second['cumulative_observed_unique_identities'], 3)
        serialized = json.dumps([first, second, probe._request_identity(request())])
        for private in ('600001', 'PRIVATE-TEXT', '123.45', 'DO-NOT-LOG', 'token'):
            self.assertNotIn(private, serialized)

    def test_retries_do_not_inflate_unique_observed_identity_count(self):
        diagnostics = probe._PageDiagnostics()
        identity = probe._request_identity(request())
        for _ in range(3):
            counts = diagnostics.observe(response([row('600001')]), identity)
        self.assertEqual(counts['cumulative_observed_unique_identities'], 1)
        self.assertEqual(counts['previously_observed_identities'], 1)

    def test_invalid_counts_rows_and_duplicate_identities_are_not_trusted(self):
        diagnostics = probe._PageDiagnostics()
        counts = diagnostics.observe(response([row('600001'), row('600001'), None, {'f12': 'SECRET'}], True),
                                     probe._request_identity(request()))
        self.assertIsNone(counts['provider_total'])
        self.assertEqual(counts['raw_rows'], 4)
        self.assertEqual(counts['page_unique_identities'], 1)
        self.assertEqual(counts['invalid_identity_rows'], 2)
        self.assertNotIn('SECRET', json.dumps(counts))

    def test_market_identity_is_bounded_and_normalized(self):
        diagnostics = probe._PageDiagnostics()
        invalid = [True, -1, 1.0, '１２', '1' * 100_000, 1_000_001, '1000001']
        rows = [{**row('600001'), 'f13': market} for market in invalid + [1, '1', '0000001']]
        counts = diagnostics.observe(response(rows), probe._request_identity(request()))
        self.assertEqual(counts['invalid_identity_rows'], len(invalid))
        self.assertEqual(counts['page_unique_identities'], 1)
        self.assertEqual(diagnostics.seen, {(1, '600001')})

    def test_unrelated_provider_body_is_not_inspected(self):
        result = probe._PageDiagnostics().observe(SimpleNamespace(), {'host': 'data.10jqka.com.cn'})
        self.assertEqual(result, {})

    def test_large_or_invalid_response_stays_diagnostic_only(self):
        diagnostics = probe._PageDiagnostics()
        identity = probe._request_identity(request())
        self.assertEqual(diagnostics.observe(SimpleNamespace(content=b'x' * (4 * 1024 * 1024 + 1)), identity),
                         {'page_diagnostic': 'size_limit'})
        def invalid_json():
            raise ValueError('DO-NOT-LOG')
        self.assertEqual(diagnostics.observe(SimpleNamespace(content=b'x', json=invalid_json), identity),
                         {'page_diagnostic': 'invalid_json'})

    def test_network_failure_event_keeps_page_but_never_exception_text(self):
        def fail(*args, **kwargs):
            raise requests.ConnectionError('DO-NOT-LOG https://name:password@example.invalid/') from socket.gaierror(-2, 'PRIVATE-DNS')
        def child(*args):
            try:
                requests.Session().send(request(13))
            except requests.ConnectionError:
                pass
        events = self._run_child(child, fail)
        ended = next(event for event in events if event['event'] == 'request_ended')
        self.assertEqual(ended['page'], 13)
        self.assertEqual(ended['requested_page_size'], 500)
        self.assertEqual(ended['error_type'], 'ConnectionError')
        self.assertEqual(ended['error_categories'], ['dns'])
        self.assertEqual(ended['error_chain_errnos'], [-2])
        self.assertNotIn('PRIVATE-DNS', json.dumps(events))
        self.assertNotIn('DO-NOT-LOG', json.dumps(events))
        self.assertNotIn('password', json.dumps(events))

    def test_diagnostic_exception_preserves_successful_provider_response(self):
        expected = response([row('600001')])
        def child(*args):
            self.assertIs(requests.Session().send(request()), expected)
        with patch.object(probe._PageDiagnostics, 'observe', side_effect=ValueError('DO-NOT-LOG')):
            events = self._run_child(child, lambda *args, **kwargs: expected)
        ended = next(event for event in events if event['event'] == 'request_ended')
        self.assertEqual(ended['page_diagnostic'], 'diagnostic_error')
        self.assertEqual(ended['http_status'], 200)
        self.assertNotIn('DO-NOT-LOG', json.dumps(events))

    def _run_child(self, child, send):
        noop = lambda *args, **kwargs: None
        market = SimpleNamespace(calculate_market_breadth=noop, get_market_breadth=noop, _emotion=noop, _sectors=noop)
        modules = {'market': market, 'astock': SimpleNamespace(a_share_snapshot=noop),
                   'public_data_budget': SimpleNamespace(_child=child)}
        with tempfile.TemporaryDirectory() as tmp:
            events = Path(tmp) / 'events.jsonl'
            with patch.dict('sys.modules', modules), patch.dict(os.environ, {'VR_PERF_EVENT_FILE': str(events)}), \
                    patch.object(requests.sessions.Session, 'send', send):
                probe._measured_child(None, 'overview', None)
            return [json.loads(line) for line in events.read_text().splitlines()]


if __name__ == '__main__':
    unittest.main()
